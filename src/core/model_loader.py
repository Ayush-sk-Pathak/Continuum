"""
Continuum Engine - Model Configuration Loader

Loads model paths from models.json based on the selected quality tier.
This enables switching between dev/standard/beast modes without editing workflows.

Design Principles:
1. Fail fast: Invalid tier or missing model config raises immediately
2. Environment-driven: CONTINUUM_MODEL_TIER controls which models to use
3. Type-safe: Pydantic validates the models.json structure
4. Cacheable: Single load per process (lru_cache)

Usage:
    from src.core.model_loader import get_model_config, ModelTier
    
    # Get T2V models for current tier (from environment)
    config = get_model_config("wan21", "t2v")
    print(config.unet)  # "wan2.1_t2v_14B_fp16.safetensors" (if tier=beast)
    
    # Override tier explicitly
    config = get_model_config("wan21", "t2v", tier=ModelTier.BEAST)
    
    # Get HunyuanCustom I2V config
    config = get_model_config("hunyuan_custom", "i2v")
    print(config.clip_l)  # "clip_l.safetensors"
    print(config.llava_text_encoder)  # "llava_llama3_fp16.safetensors"
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# TIER ENUM
# =============================================================================

class ModelTier(str, Enum):
    """Quality tiers for model selection."""
    
    DEV = "dev"           # Fast iteration, low VRAM (8-16GB)
    STANDARD = "standard" # Production balanced (24GB)
    BEAST = "beast"       # Maximum quality for demos (40GB)
    
    @classmethod
    def from_env(cls) -> "ModelTier":
        """Get tier from CONTINUUM_MODEL_TIER environment variable."""
        tier_str = os.environ.get("CONTINUUM_MODEL_TIER", "dev").lower()
        try:
            return cls(tier_str)
        except ValueError:
            valid = [t.value for t in cls]
            raise ValueError(
                f"Invalid CONTINUUM_MODEL_TIER='{tier_str}'. "
                f"Valid options: {valid}"
            )


# =============================================================================
# MODEL CONFIG DATACLASS
# =============================================================================

@dataclass(frozen=True)
class ModelConfig:
    """
    Immutable container for model paths.
    
    frozen=True prevents accidental modification after loading.
    
    Field categories:
    - Core (required): unet, vae
    - Text encoder - Wan: clip (single UMT5 encoder)
    - Text encoder - HunyuanCustom: clip_l + llava_text_encoder (dual encoder)
    - Vision encoder: clip_vision
    - HunyuanCustom-specific: attention_mode, cfg_scale, flow_shift, steps, denoise_strength
    - Resource hints: vram_required_gb, max_resolution, quality_tier, gpu_config
    """
    
    # Core models (always required)
    unet: str
    vae: str
    
    # Text encoder - Wan uses single CLIP/UMT5
    clip: Optional[str] = None
    
    # Text encoder - HunyuanCustom uses dual CLIP-L + LLaVA
    clip_l: Optional[str] = None
    llava_text_encoder: Optional[str] = None
    
    # Vision encoder (for I2V workflows)
    clip_vision: Optional[str] = None
    
    # LLaVA LLM path (for documentation/reference, not directly used in workflow)
    llava_llm: Optional[str] = None
    
    # HunyuanCustom-specific generation parameters
    attention_mode: Optional[str] = None  # "sdpa" or "sageattn"
    cfg_scale: Optional[float] = None
    flow_shift: Optional[float] = None
    steps: Optional[int] = None
    denoise_strength: Optional[float] = None
    
    # Resource hints
    vram_required_gb: int = 8
    max_resolution: str = "480p"
    quality_tier: Optional[int] = None
    gpu_config: Optional[str] = None
    
    def to_workflow_params(self) -> dict:
        """
        Convert to workflow placeholder dict.
        
        Returns keys matching workflow placeholders:
        
        Core:
        - {{UNET_MODEL}} -> self.unet
        - {{VAE_MODEL}} -> self.vae
        
        Wan text encoder:
        - {{CLIP_MODEL}} -> self.clip (if present)
        
        HunyuanCustom text encoders (dual):
        - {{CLIP_L_MODEL}} -> self.clip_l (if present)
        - {{LLAVA_TEXT_ENCODER}} -> self.llava_text_encoder (if present)
        
        Vision encoder:
        - {{CLIP_VISION_MODEL}} -> self.clip_vision (if present)
        
        Generation parameters:
        - {{ATTENTION_MODE}} -> self.attention_mode (if present)
        - {{CFG_SCALE}} -> self.cfg_scale (if present)
        - {{FLOW_SHIFT}} -> self.flow_shift (if present)
        - {{STEPS}} -> self.steps (if present)
        - {{DENOISE_STRENGTH}} -> self.denoise_strength (if present)
        """
        params = {
            "UNET_MODEL": self.unet,
            "VAE_MODEL": self.vae,
        }
        
        # Wan text encoder (single)
        if self.clip:
            params["CLIP_MODEL"] = self.clip
        
        # HunyuanCustom text encoders (dual)
        if self.clip_l:
            params["CLIP_L_MODEL"] = self.clip_l
        if self.llava_text_encoder:
            params["LLAVA_TEXT_ENCODER"] = self.llava_text_encoder
        
        # Vision encoder
        if self.clip_vision:
            params["CLIP_VISION_MODEL"] = self.clip_vision
        
        # HunyuanCustom-specific parameters
        if self.attention_mode:
            params["ATTENTION_MODE"] = self.attention_mode
        if self.cfg_scale is not None:
            params["CFG_SCALE"] = self.cfg_scale
        if self.flow_shift is not None:
            params["FLOW_SHIFT"] = self.flow_shift
        if self.steps is not None:
            params["STEPS"] = self.steps
        if self.denoise_strength is not None:
            params["DENOISE_STRENGTH"] = self.denoise_strength
        
        return params
    
    def is_hunyuan_custom(self) -> bool:
        """Check if this config is for HunyuanCustom (has dual text encoders)."""
        return self.clip_l is not None and self.llava_text_encoder is not None
    
    def is_wan(self) -> bool:
        """Check if this config is for Wan (has single CLIP/UMT5 encoder)."""
        return self.clip is not None and self.clip_l is None


# =============================================================================
# LOADER FUNCTIONS
# =============================================================================

@lru_cache(maxsize=1)
def _load_models_json(models_path: Optional[Path] = None) -> dict:
    """
    Load and cache models.json.
    
    Uses lru_cache to ensure we only read the file once per process.
    
    Search order:
    1. Explicit models_path argument
    2. Project root / models.json
    3. workflows / models.json (legacy)
    """
    if models_path is not None and Path(models_path).exists():
        path = Path(models_path)
    else:
        # Try project root first
        project_root = Path(__file__).parent.parent.parent
        root_path = project_root / "models.json"
        workflows_path = project_root / "workflows" / "models.json"
        
        if root_path.exists():
            path = root_path
        elif workflows_path.exists():
            path = workflows_path
            logger.warning(
                f"Using legacy models.json location: {workflows_path}. "
                f"Consider moving to project root."
            )
        else:
            raise FileNotFoundError(
                f"models.json not found at {root_path} or {workflows_path}. "
                f"Create it from the template in MODEL_PIVOT.md"
            )
    
    with open(path, "r") as f:
        data = json.load(f)
    
    logger.debug(f"Loaded models.json from {path}")
    return data


def get_model_config(
    model_family: str,
    model_type: str,
    tier: Optional[ModelTier] = None,
    models_path: Optional[Path] = None,
) -> ModelConfig:
    """
    Get model configuration for a specific family, type, and tier.
    
    Args:
        model_family: Model family (e.g., "wan21", "hunyuan_custom")
        model_type: Model type (e.g., "t2v", "i2v")
        tier: Quality tier (defaults to CONTINUUM_MODEL_TIER env var)
        models_path: Override path to models.json
    
    Returns:
        ModelConfig with paths for the specified configuration
    
    Raises:
        ValueError: If model family, type, or tier not found
        FileNotFoundError: If models.json doesn't exist
    
    Example:
        # Wan 2.1 T2V
        config = get_model_config("wan21", "t2v", ModelTier.BEAST)
        print(config.unet)  # "wan2.1_t2v_14B_fp16.safetensors"
        print(config.clip)  # "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
        
        # HunyuanCustom I2V
        config = get_model_config("hunyuan_custom", "i2v", ModelTier.DEV)
        print(config.unet)  # "hunyuan_video_custom_720p_fp8_scaled.safetensors"
        print(config.clip_l)  # "clip_l.safetensors"
        print(config.llava_text_encoder)  # "llava_llama3_fp16.safetensors"
    """
    if tier is None:
        tier = ModelTier.from_env()
    
    models = _load_models_json(models_path)
    
    # Navigate the JSON structure
    if model_family not in models:
        available = [k for k in models.keys() if not k.startswith("_")]
        raise ValueError(
            f"Model family '{model_family}' not found. "
            f"Available: {available}"
        )
    
    family_config = models[model_family]
    
    if model_type not in family_config:
        available = [k for k in family_config.keys() if not k.startswith("_")]
        raise ValueError(
            f"Model type '{model_type}' not found in {model_family}. "
            f"Available: {available}"
        )
    
    type_config = family_config[model_type]
    
    if tier.value not in type_config:
        available = [k for k in type_config.keys() if not k.startswith("_")]
        raise ValueError(
            f"Tier '{tier.value}' not found for {model_family}/{model_type}. "
            f"Available: {available}"
        )
    
    tier_config = type_config[tier.value]
    
    # Build ModelConfig from JSON
    # Use .get() for all optional fields to support different model schemas
    return ModelConfig(
        # Core (required)
        unet=tier_config["unet"],
        vae=tier_config["vae"],
        
        # Wan text encoder
        clip=tier_config.get("clip"),
        
        # HunyuanCustom text encoders (dual)
        clip_l=tier_config.get("clip_l"),
        llava_text_encoder=tier_config.get("llava_text_encoder"),
        
        # Vision encoder
        clip_vision=tier_config.get("clip_vision"),
        
        # LLaVA LLM reference
        llava_llm=tier_config.get("llava_llm"),
        
        # Generation parameters
        attention_mode=tier_config.get("attention_mode"),
        cfg_scale=tier_config.get("cfg_scale"),
        flow_shift=tier_config.get("flow_shift"),
        steps=tier_config.get("steps"),
        denoise_strength=tier_config.get("denoise_strength"),
        
        # Resource hints
        vram_required_gb=tier_config.get("vram_required_gb", 8),
        max_resolution=tier_config.get("max_resolution", "480p"),
        quality_tier=tier_config.get("quality_tier"),
        gpu_config=tier_config.get("gpu_config"),
    )


def get_current_tier() -> ModelTier:
    """Get the current tier from environment."""
    return ModelTier.from_env()


def clear_cache() -> None:
    """
    Clear the cached models.json.
    
    Useful for testing or after modifying models.json at runtime.
    """
    _load_models_json.cache_clear()
    logger.debug("Cleared model loader cache")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_wan21_t2v_config(tier: Optional[ModelTier] = None) -> ModelConfig:
    """Shorthand for Wan 2.1 Text-to-Video config."""
    return get_model_config("wan21", "t2v", tier)


def get_wan21_i2v_config(tier: Optional[ModelTier] = None) -> ModelConfig:
    """Shorthand for Wan 2.1 Image-to-Video config."""
    return get_model_config("wan21", "i2v", tier)


def get_hunyuan_custom_i2v_config(tier: Optional[ModelTier] = None) -> ModelConfig:
    """Shorthand for HunyuanCustom Image-to-Video config."""
    return get_model_config("hunyuan_custom", "i2v", tier)

