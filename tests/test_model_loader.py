"""
Tests for model_loader.py

Tests the tier-based model configuration system that reads models.json
and returns appropriate model paths for workflow injection.

Run with:
    pytest tests/test_model_loader.py -v
"""

import json
import os
import pytest
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, MagicMock

# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def sample_models_json() -> Dict[str, Any]:
    """Minimal valid models.json structure for testing."""
    return {
        "_description": "Test model registry",
        "_version": "1.0.0",
        
        "wan21": {
            "_description": "Wan 2.1 models",
            "t2v": {
                "dev": {
                    "unet": "wan2.1_t2v_1.3B_fp16.safetensors",
                    "vae": "wan_2.1_vae.safetensors",
                    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                    "vram_required_gb": 8,
                    "max_resolution": "480p"
                },
                "standard": {
                    "unet": "wan2.1_t2v_14B_bf16.safetensors",
                    "vae": "wan_2.1_vae.safetensors",
                    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                    "vram_required_gb": 24,
                    "max_resolution": "720p"
                },
                "beast": {
                    "unet": "wan2.1_t2v_14B_fp16.safetensors",
                    "vae": "wan_2.1_vae.safetensors",
                    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                    "vram_required_gb": 40,
                    "max_resolution": "1080p"
                }
            },
            "i2v": {
                "dev": {
                    "unet": "wan2.1_i2v_480p_14B_fp16.safetensors",
                    "vae": "wan_2.1_vae.safetensors",
                    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                    "clip_vision": "clip_vision_h.safetensors",
                    "vram_required_gb": 16,
                    "max_resolution": "480p"
                },
                "beast": {
                    "unet": "wan2.1_i2v_720p_14B_fp16.safetensors",
                    "vae": "wan_2.1_vae.safetensors",
                    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                    "clip_vision": "clip_vision_h.safetensors",
                    "vram_required_gb": 40,
                    "max_resolution": "1080p"
                }
            }
        },
        
        "hunyuan": {
            "_description": "Placeholder",
            "_status": "placeholder"
        }
    }


@pytest.fixture
def temp_models_json(tmp_path: Path, sample_models_json: Dict) -> Path:
    """Create a temporary models.json file."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    models_path = workflows_dir / "models.json"
    models_path.write_text(json.dumps(sample_models_json, indent=2))
    return workflows_dir


# =============================================================================
# SECTION 1: ModelTier Enum Tests
# =============================================================================

class TestModelTierEnum:
    """Tests for the ModelTier enum."""
    
    def test_tier_values_exist(self):
        """All expected tiers should exist."""
        from src.core.model_loader import ModelTier
        
        assert ModelTier.DEV.value == "dev"
        assert ModelTier.STANDARD.value == "standard"
        assert ModelTier.BEAST.value == "beast"
    
    def test_tier_from_env_dev(self):
        """DEV tier should be parsed from environment."""
        from src.core.model_loader import ModelTier
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "dev"}):
            assert ModelTier.from_env() == ModelTier.DEV
    
    def test_tier_from_env_beast(self):
        """BEAST tier should be parsed from environment."""
        from src.core.model_loader import ModelTier
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "beast"}):
            assert ModelTier.from_env() == ModelTier.BEAST
    
    def test_tier_from_env_case_insensitive(self):
        """Tier parsing should be case-insensitive."""
        from src.core.model_loader import ModelTier
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "BEAST"}):
            assert ModelTier.from_env() == ModelTier.BEAST
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "Beast"}):
            assert ModelTier.from_env() == ModelTier.BEAST
    
    def test_tier_from_env_defaults_to_dev(self):
        """Missing env var should default to DEV."""
        from src.core.model_loader import ModelTier
        
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if it exists
            os.environ.pop("CONTINUUM_MODEL_TIER", None)
            assert ModelTier.from_env() == ModelTier.DEV
    
    def test_tier_from_env_invalid_raises(self):
        """Invalid tier should raise ValueError with helpful message."""
        from src.core.model_loader import ModelTier
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "ultra"}):
            with pytest.raises(ValueError) as exc_info:
                ModelTier.from_env()
            
            # Error message should list valid options
            assert "ultra" in str(exc_info.value)
            assert "dev" in str(exc_info.value)
            assert "beast" in str(exc_info.value)


# =============================================================================
# SECTION 2: ModelConfig Dataclass Tests
# =============================================================================

class TestModelConfig:
    """Tests for the ModelConfig dataclass."""
    
    def test_model_config_creation(self):
        """ModelConfig should accept all required fields."""
        from src.core.model_loader import ModelConfig
        
        config = ModelConfig(
            unet="test_unet.safetensors",
            vae="test_vae.safetensors",
            clip="test_clip.safetensors",
        )
        
        assert config.unet == "test_unet.safetensors"
        assert config.vae == "test_vae.safetensors"
        assert config.clip == "test_clip.safetensors"
        assert config.clip_vision is None  # Optional
    
    def test_model_config_with_clip_vision(self):
        """ModelConfig should accept optional clip_vision."""
        from src.core.model_loader import ModelConfig
        
        config = ModelConfig(
            unet="test_unet.safetensors",
            vae="test_vae.safetensors",
            clip="test_clip.safetensors",
            clip_vision="test_clip_vision.safetensors",
        )
        
        assert config.clip_vision == "test_clip_vision.safetensors"
    
    def test_model_config_is_frozen(self):
        """ModelConfig should be immutable."""
        from src.core.model_loader import ModelConfig
        
        config = ModelConfig(
            unet="test.safetensors",
            vae="test.safetensors",
            clip="test.safetensors",
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            config.unet = "modified.safetensors"
    
    def test_to_workflow_params_basic(self):
        """to_workflow_params should return correct keys for T2V."""
        from src.core.model_loader import ModelConfig
        
        config = ModelConfig(
            unet="wan2.1_t2v.safetensors",
            vae="wan_vae.safetensors",
            clip="umt5.safetensors",
        )
        
        params = config.to_workflow_params()
        
        assert params["UNET_MODEL"] == "wan2.1_t2v.safetensors"
        assert params["VAE_MODEL"] == "wan_vae.safetensors"
        assert params["CLIP_MODEL"] == "umt5.safetensors"
        assert "CLIP_VISION_MODEL" not in params  # Not set
    
    def test_to_workflow_params_with_clip_vision(self):
        """to_workflow_params should include CLIP_VISION_MODEL for I2V."""
        from src.core.model_loader import ModelConfig
        
        config = ModelConfig(
            unet="wan2.1_i2v.safetensors",
            vae="wan_vae.safetensors",
            clip="umt5.safetensors",
            clip_vision="clip_vision_h.safetensors",
        )
        
        params = config.to_workflow_params()
        
        assert params["CLIP_VISION_MODEL"] == "clip_vision_h.safetensors"
        assert len(params) == 4  # All 4 keys present


# =============================================================================
# SECTION 3: get_model_config Function Tests
# =============================================================================

class TestGetModelConfig:
    """Tests for the get_model_config function."""
    
    def test_get_t2v_dev_config(self, temp_models_json: Path):
        """Should return correct T2V dev config."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config(
            "wan21", "t2v",
            tier=ModelTier.DEV,
            workflows_dir=temp_models_json
        )
        
        assert config.unet == "wan2.1_t2v_1.3B_fp16.safetensors"
        assert config.vram_required_gb == 8
        assert config.max_resolution == "480p"
    
    def test_get_t2v_beast_config(self, temp_models_json: Path):
        """Should return correct T2V beast config."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config(
            "wan21", "t2v",
            tier=ModelTier.BEAST,
            workflows_dir=temp_models_json
        )
        
        assert config.unet == "wan2.1_t2v_14B_fp16.safetensors"
        assert config.vram_required_gb == 40
        assert config.max_resolution == "1080p"
    
    def test_get_i2v_config_has_clip_vision(self, temp_models_json: Path):
        """I2V config should include clip_vision."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config(
            "wan21", "i2v",
            tier=ModelTier.DEV,
            workflows_dir=temp_models_json
        )
        
        assert config.clip_vision == "clip_vision_h.safetensors"
    
    def test_get_config_uses_env_tier(self, temp_models_json: Path):
        """Should use CONTINUUM_MODEL_TIER when tier not specified."""
        from src.core.model_loader import get_model_config, clear_cache
        clear_cache()
        
        with patch.dict(os.environ, {"CONTINUUM_MODEL_TIER": "beast"}):
            config = get_model_config(
                "wan21", "t2v",
                workflows_dir=temp_models_json
            )
        
        assert config.unet == "wan2.1_t2v_14B_fp16.safetensors"
    
    def test_invalid_family_raises(self, temp_models_json: Path):
        """Invalid model family should raise ValueError."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        with pytest.raises(ValueError) as exc_info:
            get_model_config(
                "invalid_family", "t2v",
                tier=ModelTier.DEV,
                workflows_dir=temp_models_json
            )
        
        assert "invalid_family" in str(exc_info.value)
        assert "wan21" in str(exc_info.value)  # Lists available
    
    def test_invalid_type_raises(self, temp_models_json: Path):
        """Invalid model type should raise ValueError."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        with pytest.raises(ValueError) as exc_info:
            get_model_config(
                "wan21", "invalid_type",
                tier=ModelTier.DEV,
                workflows_dir=temp_models_json
            )
        
        assert "invalid_type" in str(exc_info.value)
    
    def test_invalid_tier_raises(self, temp_models_json: Path):
        """Tier not in models.json should raise ValueError."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        # I2V doesn't have 'standard' tier in our test fixture
        with pytest.raises(ValueError) as exc_info:
            get_model_config(
                "wan21", "i2v",
                tier=ModelTier.STANDARD,
                workflows_dir=temp_models_json
            )
        
        assert "standard" in str(exc_info.value)
    
    def test_missing_models_json_raises(self, tmp_path: Path):
        """Missing models.json should raise FileNotFoundError."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        empty_dir = tmp_path / "empty_workflows"
        empty_dir.mkdir()
        
        with pytest.raises(FileNotFoundError) as exc_info:
            get_model_config(
                "wan21", "t2v",
                tier=ModelTier.DEV,
                workflows_dir=empty_dir
            )
        
        assert "models.json" in str(exc_info.value)


# =============================================================================
# SECTION 4: Cache Behavior Tests
# =============================================================================

class TestCacheBehavior:
    """Tests for the lru_cache behavior."""
    
    def test_cache_is_used(self, temp_models_json: Path):
        """Multiple calls should use cached data."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache, _load_models_json
        clear_cache()
        
        # First call loads from disk
        config1 = get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        
        # Check cache info
        cache_info = _load_models_json.cache_info()
        assert cache_info.hits == 0
        assert cache_info.misses == 1
        
        # Second call should hit cache
        config2 = get_model_config("wan21", "t2v", ModelTier.BEAST, temp_models_json)
        
        cache_info = _load_models_json.cache_info()
        assert cache_info.hits == 1
        assert cache_info.misses == 1
    
    def test_clear_cache_reloads(self, temp_models_json: Path):
        """clear_cache should force reload on next call."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache, _load_models_json
        clear_cache()
        
        # First call
        get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        
        # Clear and call again
        clear_cache()
        get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        
        cache_info = _load_models_json.cache_info()
        assert cache_info.misses == 1  # Reset after clear


# =============================================================================
# SECTION 5: Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for the shorthand functions."""
    
    def test_get_wan21_t2v_config(self, temp_models_json: Path):
        """get_wan21_t2v_config should return T2V config."""
        from src.core.model_loader import clear_cache
        clear_cache()
        
        # Patch the default workflows_dir lookup
        with patch("src.core.model_loader._load_models_json") as mock_load:
            mock_load.return_value = {
                "wan21": {
                    "t2v": {
                        "dev": {
                            "unet": "test_t2v.safetensors",
                            "vae": "test_vae.safetensors",
                            "clip": "test_clip.safetensors",
                        }
                    }
                }
            }
            
            from src.core.model_loader import get_wan21_t2v_config, ModelTier
            config = get_wan21_t2v_config(tier=ModelTier.DEV)
            
            assert config.unet == "test_t2v.safetensors"
    
    def test_get_wan21_i2v_config(self, temp_models_json: Path):
        """get_wan21_i2v_config should return I2V config."""
        from src.core.model_loader import clear_cache
        clear_cache()
        
        with patch("src.core.model_loader._load_models_json") as mock_load:
            mock_load.return_value = {
                "wan21": {
                    "i2v": {
                        "dev": {
                            "unet": "test_i2v.safetensors",
                            "vae": "test_vae.safetensors",
                            "clip": "test_clip.safetensors",
                            "clip_vision": "test_vision.safetensors",
                        }
                    }
                }
            }
            
            from src.core.model_loader import get_wan21_i2v_config, ModelTier
            config = get_wan21_i2v_config(tier=ModelTier.DEV)
            
            assert config.unet == "test_i2v.safetensors"
            assert config.clip_vision == "test_vision.safetensors"


# =============================================================================
# SECTION 6: Integration with Workflow Params
# =============================================================================

class TestWorkflowIntegration:
    """Tests ensuring model params work with workflow injection."""
    
    def test_params_match_workflow_placeholders(self, temp_models_json: Path):
        """Param keys should match workflow placeholder names."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        params = config.to_workflow_params()
        
        # These must match the placeholders in pass1_*.json
        expected_keys = {"UNET_MODEL", "VAE_MODEL", "CLIP_MODEL"}
        assert expected_keys.issubset(set(params.keys()))
    
    def test_i2v_params_include_clip_vision(self, temp_models_json: Path):
        """I2V params should include CLIP_VISION_MODEL."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config("wan21", "i2v", ModelTier.DEV, temp_models_json)
        params = config.to_workflow_params()
        
        assert "CLIP_VISION_MODEL" in params
    
    def test_params_are_strings(self, temp_models_json: Path):
        """All param values should be strings (model filenames)."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        params = config.to_workflow_params()
        
        for key, value in params.items():
            assert isinstance(value, str), f"{key} should be string, got {type(value)}"
    
    def test_params_are_safetensors_filenames(self, temp_models_json: Path):
        """Model params should be .safetensors filenames."""
        from src.core.model_loader import get_model_config, ModelTier, clear_cache
        clear_cache()
        
        config = get_model_config("wan21", "t2v", ModelTier.DEV, temp_models_json)
        params = config.to_workflow_params()
        
        for key, value in params.items():
            assert value.endswith(".safetensors"), (
                f"{key}={value} should end with .safetensors"
            )