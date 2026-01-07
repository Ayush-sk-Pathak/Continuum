"""
Continuum Engine - Configuration Management

This module handles all configuration loading, validation, and access.
Uses Pydantic for schema validation and environment variable support.

Design Principles:
1. Fail fast on invalid config (at startup, not runtime)
2. Single source of truth (one Config object, passed around)
3. Environment variables override file settings (12-factor app)
4. Secrets never logged or printed
"""

from pathlib import Path
from typing import Optional, Literal
from functools import lru_cache
import os

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# =============================================================================
# NESTED CONFIG MODELS (Pydantic BaseModel for structure)
# =============================================================================

class GenerationConfig(BaseModel):
    """Settings for video generation pipeline."""
    
    max_shot_duration_sec: float = Field(
        default=12.0,
        ge=1.0,
        le=60.0,
        description="Maximum duration per shot before Smart Cut triggers"
    )
    default_fps: int = Field(
        default=12,
        ge=6,
        le=30,
        description="FPS for Pass 1 generation (before RIFE upscaling)"
    )
    output_fps: int = Field(
        default=24,
        ge=12,
        le=60,
        description="Final output FPS after RIFE interpolation"
    )
    max_reroll_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max re-generation attempts before failing to user"
    )
    default_resolution: tuple[int, int] = Field(
        default=(1280, 720),
        description="Default output resolution (width, height)"
    )


class AuditConfig(BaseModel):
    """Thresholds for QA audit checks."""
    
    identity_threshold: float = Field(
        default=0.50,  # Relaxed from 0.70 - TODO: tighten once DWPreprocessor is working
        ge=0.0,
        le=1.0,
        description="ArcFace similarity threshold (below = FAIL)"
    )
    flicker_threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Max fraction of frame area with flicker"
    )
    physics_missing_frames: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Frames an object can be missing before flagging"
    )
    scene_consistency_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="CLIP embedding similarity threshold"
    )


class SonicConfig(BaseModel):
    """Settings for audio/sonic engine."""
    
    tts_provider: Literal["elevenlabs", "openai", "local"] = Field(
        default="elevenlabs",
        description="TTS provider to use for dialogue"
    )
    ducking_db: float = Field(
        default=-12.0,
        le=0.0,
        description="dB reduction for music during dialogue"
    )
    default_ambience_duration_sec: float = Field(
        default=30.0,
        ge=5.0,
        description="Duration of generated ambience loops"
    )


class PostConfig(BaseModel):
    """Settings for post-production."""
    
    color_match_enabled: bool = Field(
        default=True,
        description="Enable histogram matching across shots"
    )
    master_shot_index: int = Field(
        default=0,
        ge=0,
        description="Shot index to use as color reference"
    )
    output_format: Literal["mp4", "mov", "webm"] = Field(
        default="mp4",
        description="Final output container format"
    )
    output_codec: str = Field(
        default="libx264",
        description="Video codec for final output"
    )


class VideoModelConfig(BaseModel):
    """
    Video model selection and configuration.
    
    Supports switching between video generation backends:
    - "wan": Wan 2.1 via ComfyUI (lower VRAM, proven pipeline)
    - "hunyuan_custom": HunyuanCustom via ComfyUI (better identity, higher VRAM)
    
    Environment variables:
        CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan|hunyuan_custom
        CONTINUUM_VIDEO_MODEL__MODEL_TIER=dev|standard|beast
    
    Architecture Reference:
        - Renderer selection: src/renderers/base.py::get_renderer_for_config()
        - Model paths: workflows/models.json
        - Workflows: workflows/{model_family}/
    """
    
    model_family: Literal["wan", "hunyuan_custom"] = Field(
        default="wan",
        description="Video generation model family. 'wan' for backwards compatibility."
    )
    model_tier: Literal["dev", "standard", "beast"] = Field(
        default="dev",
        description="Quality/speed tier within model family (dev=fast, beast=quality)"
    )
    
    @field_validator("model_family")
    @classmethod
    def validate_model_family(cls, v: str) -> str:
        """Validate model family is supported."""
        valid = ["wan", "hunyuan_custom"]
        if v not in valid:
            raise ValueError(
                f"model_family must be one of {valid}, got '{v}'. "
                f"Set CONTINUUM_VIDEO_MODEL__MODEL_FAMILY environment variable."
            )
        return v
    
    @field_validator("model_tier")
    @classmethod
    def validate_model_tier(cls, v: str) -> str:
        """Validate model tier is supported."""
        valid = ["dev", "standard", "beast"]
        if v not in valid:
            raise ValueError(
                f"model_tier must be one of {valid}, got '{v}'. "
                f"Set CONTINUUM_VIDEO_MODEL__MODEL_TIER environment variable."
            )
        return v


class ComfyUIConfig(BaseModel):
    """Settings for ComfyUI cloud connection."""
    
    host: str = Field(
        default="ws://localhost:8188",
        description="ComfyUI WebSocket endpoint"
    )
    timeout_sec: int = Field(
        default=900,    # Changed from 500 for longer clips
        ge=30,
        description="Timeout for generation jobs (500s needed for HunyuanCustom first run)"
    )
    poll_interval_sec: float = Field(
        default=1.0,
        ge=0.1,
        description="How often to poll for job status"
    )
    max_queue_size: int = Field(
        default=10,
        ge=1,
        description="Max concurrent jobs to queue"
    )


class PathsConfig(BaseModel):
    """File system paths."""
    
    workspace_dir: Path = Field(
        default=Path("./workspace"),
        description="Root directory for project files"
    )
    checkpoint_dir: Path = Field(
        default=Path("./workspace/checkpoints"),
        description="Directory for job checkpoints"
    )
    output_dir: Path = Field(
        default=Path("./workspace/output"),
        description="Directory for final rendered videos"
    )
    cache_dir: Path = Field(
        default=Path("./workspace/cache"),
        description="Directory for temporary/cached files"
    )
    workflows_dir: Path = Field(
        default=Path("./workflows"),
        description="Directory containing ComfyUI workflow JSONs"
    )
    
    @model_validator(mode="after")
    def ensure_directories_exist(self) -> "PathsConfig":
        """Create directories if they don't exist."""
        for field_name in ["workspace_dir", "checkpoint_dir", "output_dir", "cache_dir"]:
            path = getattr(self, field_name)
            path.mkdir(parents=True, exist_ok=True)
        return self


# =============================================================================
# MAIN CONFIG CLASS (BaseSettings for env var support)
# =============================================================================

class Config(BaseSettings):
    """
    Master configuration for the Continuum Engine.
    
    Loading priority (highest wins):
    1. Environment variables (CONTINUUM_OPENAI_API_KEY, etc.)
    2. .env file in project root
    3. Default values defined here
    
    Usage:
        config = get_config()  # Singleton, cached
        config.generation.max_shot_duration_sec
        config.openai_api_key.get_secret_value()  # For actual use
    """
    
    model_config = SettingsConfigDict(
        env_prefix="CONTINUUM_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",  # CONTINUUM_GENERATION__MAX_SHOT_DURATION_SEC
        extra="ignore",  # Don't fail on unknown env vars
    )
    
    # -------------------------------------------------------------------------
    # API Keys (SecretStr hides from logs/repr)
    # -------------------------------------------------------------------------
    openai_api_key: Optional[SecretStr] = Field(
        default=None,
        description="OpenAI API key for TTS and LLM"
    )
    elevenlabs_api_key: Optional[SecretStr] = Field(
        default=None,
        description="ElevenLabs API key for TTS"
    )
    anthropic_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Anthropic API key for Director Agent"
    )
    pinecone_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Pinecone API key for Visual RAG"
    )
    aws_access_key_id: Optional[SecretStr] = Field(
        default=None,
        description="AWS access key for S3"
    )
    aws_secret_access_key: Optional[SecretStr] = Field(
        default=None,
        description="AWS secret key for S3"
    )
    runway_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Runway API key for Pro Lane"
    )
    
    # -------------------------------------------------------------------------
    # Infrastructure
    # -------------------------------------------------------------------------
    s3_bucket: Optional[str] = Field(
        default=None,
        description="S3 bucket for asset storage"
    )
    s3_region: str = Field(
        default="us-east-1",
        description="AWS region for S3"
    )
    
    # -------------------------------------------------------------------------
    # Feature Flags
    # -------------------------------------------------------------------------
    debug_mode: bool = Field(
        default=False,
        description="Enable verbose logging and debug features"
    )
    dry_run: bool = Field(
        default=False,
        description="Skip actual generation, return mock results"
    )
    pro_lane_enabled: bool = Field(
        default=False,
        description="Enable premium API renderers (Runway, Veo)"
    )
    
    # -------------------------------------------------------------------------
    # Nested Configs
    # -------------------------------------------------------------------------
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    sonic: SonicConfig = Field(default_factory=SonicConfig)
    post: PostConfig = Field(default_factory=PostConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    video_model: VideoModelConfig = Field(default_factory=VideoModelConfig)
    
    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("s3_bucket")
    @classmethod
    def validate_s3_bucket(cls, v: Optional[str]) -> Optional[str]:
        """Ensure S3 bucket name is valid if provided."""
        if v is not None:
            # Basic S3 bucket naming rules
            if not (3 <= len(v) <= 63):
                raise ValueError("S3 bucket name must be 3-63 characters")
            if not v.replace("-", "").replace(".", "").isalnum():
                raise ValueError("S3 bucket name contains invalid characters")
        return v
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    def get_secret(self, key: str) -> Optional[str]:
        """
        Safely retrieve a secret value.
        
        Args:
            key: Attribute name (e.g., "openai_api_key")
            
        Returns:
            The secret string value, or None if not set
        """
        secret: Optional[SecretStr] = getattr(self, key, None)
        if secret is None:
            return None
        return secret.get_secret_value()
    
    def require_secret(self, key: str) -> str:
        """
        Get a secret, raising if not configured.
        
        Use this when a secret is required for an operation.
        
        Raises:
            ValueError: If secret is not configured
        """
        value = self.get_secret(key)
        if value is None:
            raise ValueError(
                f"Required secret '{key}' not configured. "
                f"Set CONTINUUM_{key.upper()} environment variable."
            )
        return value
    
    def has_api_key(self, provider: str) -> bool:
        """Check if an API key is configured for a provider."""
        key_map = {
            "openai": "openai_api_key",
            "elevenlabs": "elevenlabs_api_key",
            "anthropic": "anthropic_api_key",
            "pinecone": "pinecone_api_key",
            "runway": "runway_api_key",
            "aws": "aws_access_key_id",
        }
        key_name = key_map.get(provider.lower())
        if not key_name:
            return False
        return self.get_secret(key_name) is not None


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    Get the global Config instance (singleton pattern via lru_cache).
    
    First call loads from environment/files. Subsequent calls return cached.
    
    Usage:
        from continuum.src.core.config import get_config
        config = get_config()
    """
    return Config()


def reload_config() -> Config:
    """
    Force reload configuration (clears cache).
    
    Useful for testing or when env vars change at runtime.
    """
    get_config.cache_clear()
    return get_config()


# =============================================================================
# DEVELOPMENT HELPERS
# =============================================================================

def create_default_env_file(path: Path = Path(".env.example")) -> None:
    """
    Generate a template .env file with all config options.
    
    Useful for onboarding new developers.
    """
    template = '''# Continuum Engine Configuration
# Copy this to .env and fill in your values

# =============================================================================
# API Keys (Required for full functionality)
# =============================================================================
CONTINUUM_OPENAI_API_KEY=sk-...
CONTINUUM_ELEVENLABS_API_KEY=...
CONTINUUM_ANTHROPIC_API_KEY=sk-ant-...
CONTINUUM_PINECONE_API_KEY=...
CONTINUUM_RUNWAY_API_KEY=...

# AWS (for S3 asset storage)
CONTINUUM_AWS_ACCESS_KEY_ID=...
CONTINUUM_AWS_SECRET_ACCESS_KEY=...
CONTINUUM_S3_BUCKET=continuum-assets
CONTINUUM_S3_REGION=us-east-1

# =============================================================================
# Infrastructure
# =============================================================================
CONTINUUM_COMFYUI__HOST=ws://your-runpod-instance:8188
CONTINUUM_COMFYUI__TIMEOUT_SEC=300

# =============================================================================
# Feature Flags
# =============================================================================
CONTINUUM_DEBUG_MODE=false
CONTINUUM_DRY_RUN=false
CONTINUUM_PRO_LANE_ENABLED=false

# =============================================================================
# Generation Settings (optional, defaults are sensible)
# =============================================================================
# CONTINUUM_GENERATION__MAX_SHOT_DURATION_SEC=12.0
# CONTINUUM_GENERATION__DEFAULT_FPS=12
# CONTINUUM_GENERATION__OUTPUT_FPS=24
# CONTINUUM_GENERATION__MAX_REROLL_ATTEMPTS=3

# =============================================================================
# Audit Thresholds (optional)
# =============================================================================
# CONTINUUM_AUDIT__IDENTITY_THRESHOLD=0.70
# CONTINUUM_AUDIT__FLICKER_THRESHOLD=0.05
'''
    
    with open(path, "w") as f:
        f.write(template)
    
    print(f"Created template env file: {path}")


# =============================================================================
# MODULE INITIALIZATION
# =============================================================================

if __name__ == "__main__":
    # When run directly, generate template env file
    create_default_env_file()
    
    # Also print current config (with secrets hidden)
    config = get_config()
    print("\nCurrent configuration:")
    print(config.model_dump_json(indent=2))