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
    All fields are strings (model filenames) except vram_required_gb.
    """
    
    unet: str
    vae: str
    clip: str
    clip_vision: Optional[str] = None  # Only for I2V
    vram_required_gb: int = 8
    max_resolution: str = "480p"
    
    def to_workflow_params(self) -> dict:
        """
        Convert to workflow placeholder dict.
        
        Returns keys matching workflow placeholders:
        - {{UNET_MODEL}} -> self.unet
        - {{VAE_MODEL}} -> self.vae
        - {{CLIP_MODEL}} -> self.clip
        - {{CLIP_VISION_MODEL}} -> self.clip_vision (if present)
        """
        params = {
            "UNET_MODEL": self.unet,
            "VAE_MODEL": self.vae,
            "CLIP_MODEL": self.clip,
        }
        if self.clip_vision:
            params["CLIP_VISION_MODEL"] = self.clip_vision
        return params


# =============================================================================
# LOADER FUNCTIONS
# =============================================================================

@lru_cache(maxsize=1)
def _load_models_json(workflows_dir: Optional[Path] = None) -> dict:
    """
    Load and cache models.json.
    
    Uses lru_cache to ensure we only read the file once per process.
    """
    if workflows_dir is None:
        # Default to ./workflows relative to project root
        workflows_dir = Path(__file__).parent.parent.parent / "workflows"
    
    models_path = workflows_dir / "models.json"
    
    if not models_path.exists():
        raise FileNotFoundError(
            f"models.json not found at {models_path}. "
            f"Create it from the template in MODEL_CONFIGURATION.md"
        )
    
    with open(models_path, "r") as f:
        data = json.load(f)
    
    logger.debug(f"Loaded models.json from {models_path}")
    return data


def get_model_config(
    model_family: str,
    model_type: str,
    tier: Optional[ModelTier] = None,
    workflows_dir: Optional[Path] = None,
) -> ModelConfig:
    """
    Get model configuration for a specific family, type, and tier.
    
    Args:
        model_family: Model family (e.g., "wan21", "hunyuan")
        model_type: Model type (e.g., "t2v", "i2v")
        tier: Quality tier (defaults to CONTINUUM_MODEL_TIER env var)
        workflows_dir: Override path to workflows directory
    
    Returns:
        ModelConfig with paths for the specified configuration
    
    Raises:
        ValueError: If model family, type, or tier not found
        FileNotFoundError: If models.json doesn't exist
    
    Example:
        config = get_model_config("wan21", "t2v", ModelTier.BEAST)
        print(config.unet)  # "wan2.1_t2v_14B_fp16.safetensors"
    """
    if tier is None:
        tier = ModelTier.from_env()
    
    models = _load_models_json(workflows_dir)
    
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
    return ModelConfig(
        unet=tier_config["unet"],
        vae=tier_config["vae"],
        clip=tier_config["clip"],
        clip_vision=tier_config.get("clip_vision"),  # Optional
        vram_required_gb=tier_config.get("vram_required_gb", 8),
        max_resolution=tier_config.get("max_resolution", "480p"),
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