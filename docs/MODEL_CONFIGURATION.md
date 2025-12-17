# Model Configuration Guide

> **Purpose:** How to switch models, add new models, and understand the tier system.
> 
> **Last Updated:** December 2024

---

## Quick Reference

### Switch Quality Tier (Most Common)

```bash
# Development (fast iteration, 8GB VRAM)
export CONTINUUM_MODEL_TIER=dev

# Production (balanced, 24GB VRAM)
export CONTINUUM_MODEL_TIER=standard

# VC Demo / Pilot (max quality, 40GB VRAM)
export CONTINUUM_MODEL_TIER=beast
```

### Current Model Tiers

| Tier | T2V Model | I2V Model | VRAM | Use Case |
|------|-----------|-----------|------|----------|
| `dev` | 1.3B fp16 | 480p 14B fp16 | 8-16GB | Daily testing |
| `standard` | 14B bf16 | 720p 14B bf16 | 24GB | Production |
| `beast` | 14B fp16 | 720p 14B fp16 | 40GB | VC demos, pilots |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    MODEL CONFIGURATION FLOW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Environment Variable                                        │
│     CONTINUUM_MODEL_TIER=beast                                  │
│              │                                                  │
│              ▼                                                  │
│  2. models.json (registry)                                      │
│     Returns: { "unet": "wan2.1_t2v_14B_fp16.safetensors", ... } │
│              │                                                  │
│              ▼                                                  │
│  3. Workflow Loader                                             │
│     Replaces: {{UNET_MODEL}} → wan2.1_t2v_14B_fp16.safetensors  │
│              │                                                  │
│              ▼                                                  │
│  4. ComfyUI                                                     │
│     Loads the specified model, generates video                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Locations

| File | Purpose |
|------|---------|
| `workflows/models.json` | Model registry (tiers, filenames, VRAM requirements) |
| `workflows/pass1_*.json` | Workflow templates with `{{UNET_MODEL}}` placeholders |
| `src/core/config.py` | Reads `CONTINUUM_MODEL_TIER` environment variable |
| `src/studio/wan_renderer.py` | Injects model paths into workflows |

---

## Placeholder Reference

Workflows use these placeholders (injected at runtime):

| Placeholder | Example Value | Used In |
|-------------|---------------|---------|
| `{{UNET_MODEL}}` | `wan2.1_t2v_14B_fp16.safetensors` | All Pass 1 workflows |
| `{{VAE_MODEL}}` | `wan_2.1_vae.safetensors` | All Pass 1 workflows |
| `{{CLIP_MODEL}}` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | All Pass 1 workflows |
| `{{CLIP_VISION_MODEL}}` | `clip_vision_h.safetensors` | I2V workflows only |

---

## Common Operations

### 1. Switch to Beast Mode for Demo

```bash
export CONTINUUM_MODEL_TIER=beast
python main.py render my_script.json
```

### 2. Check Current Tier

```bash
echo $CONTINUUM_MODEL_TIER
# If empty, defaults to "dev"
```

### 3. Override Tier in Python

```python
import os
os.environ["CONTINUUM_MODEL_TIER"] = "beast"

# Or in config
from src.core.config import get_config
config = get_config()
config.model_tier = "beast"
```

---

## Adding New Models

### Scenario A: New Wan Version (e.g., Wan 2.2)

**Step 1:** Update `models.json`:
```json
"wan22": {
  "_description": "Wan 2.2 video generation models",
  "t2v": {
    "dev": {
      "unet": "wan2.2_t2v_1.3B_fp16.safetensors",
      "vae": "wan_2.2_vae.safetensors",
      "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
      "vram_required_gb": 8
    },
    "beast": {
      "unet": "wan2.2_t2v_14B_fp16.safetensors",
      "vae": "wan_2.2_vae.safetensors",
      "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
      "vram_required_gb": 40
    }
  }
}
```

**Step 2:** Update config to use new model family:
```python
VIDEO_MODEL_FAMILY = "wan22"  # was "wan21"
```

**Step 3:** No workflow changes needed (same node types).

---

### Scenario B: Different Model (e.g., Hunyuan)

**Step 1:** Update `models.json`:
```json
"hunyuan": {
  "_description": "Hunyuan video generation",
  "t2v": {
    "standard": {
      "unet": "hunyuan_video_720p.safetensors",
      "vae": "hunyuan_vae.safetensors",
      "clip": "hunyuan_clip.safetensors",
      "vram_required_gb": 24
    }
  }
}
```

**Step 2:** Check if workflows need changes:
- If Hunyuan uses same ComfyUI nodes → No workflow changes
- If Hunyuan uses different nodes → Create `pass1_structural_hunyuan.json`

**Step 3:** Create renderer if needed:
```python
# src/studio/hunyuan_renderer.py
class HunyuanRenderer(BaseRenderer):
    MODEL_FAMILY = "hunyuan"
    DEFAULT_WORKFLOW = "pass1_structural_hunyuan"
```

---

### Scenario C: API Model (e.g., Veo, Sora)

API models don't use ComfyUI workflows. They need a renderer class only.

**Step 1:** Update `models.json`:
```json
"veo": {
  "_description": "Google Veo (Pro Lane - API)",
  "_type": "api",
  "t2v": {
    "standard": {
      "api_endpoint": "https://veo.googleapis.com/v1/generate",
      "api_key_env": "VEO_API_KEY",
      "max_duration_seconds": 60,
      "max_resolution": "1080p",
      "cost_per_second": 0.10
    }
  }
}
```

**Step 2:** Create API renderer:
```python
# src/studio/veo_renderer.py
class VeoRenderer(BaseRenderer):
    """Pro Lane renderer using Google Veo API."""
    
    def render(self, spec: RenderSpec) -> RenderResult:
        api_key = os.environ[self.config["api_key_env"]]
        response = requests.post(
            self.config["api_endpoint"],
            headers={"Authorization": f"Bearer {api_key}"},
            json={"prompt": spec.prompt, "duration": spec.duration}
        )
        return RenderResult(video_url=response.json()["output_url"])
```

**Step 3:** No workflows needed for API models.

---

## Model File Naming Convention

```
{family}{version}_{type}_{resolution}_{params}_{precision}.safetensors

Examples:
- wan2.1_t2v_1.3B_fp16.safetensors      (Wan 2.1, Text-to-Video, 1.3B params, FP16)
- wan2.1_i2v_480p_14B_fp16.safetensors  (Wan 2.1, Image-to-Video, 480p, 14B params, FP16)
- wan2.1_i2v_720p_14B_bf16.safetensors  (Wan 2.1, Image-to-Video, 720p, 14B params, BF16)
```

| Precision | VRAM | Quality | Speed |
|-----------|------|---------|-------|
| `fp16` | High | Best | Slower |
| `bf16` | Medium | Good | Faster |
| `fp8` | Low | Acceptable | Fastest |

---

## Troubleshooting

### "Model not found" Error

1. Check model file exists in ComfyUI models directory
2. Verify filename in `models.json` matches exactly (case-sensitive)
3. Check tier is valid: `dev`, `standard`, or `beast`

### "Out of memory" Error

1. Check VRAM requirement in `models.json`
2. Switch to lower tier: `export CONTINUUM_MODEL_TIER=dev`
3. Or use `bf16` variant instead of `fp16`

### "Placeholder not replaced" Error

1. Workflow has `{{UNET_MODEL}}` but loader didn't inject it
2. Check `wan_renderer.py` is calling model loader
3. Run tests: `pytest tests/test_workflow_stress.py -k placeholder`

### Workflow Works Locally but Fails on Cloud

1. Cloud GPU may have different model files
2. Ensure model files are synced to cloud ComfyUI
3. Check cloud has enough VRAM for selected tier

---

## Testing Model Changes

After any model configuration change:

```bash
# Run all workflow tests
pytest tests/test_workflow_contracts.py tests/test_workflow_stress.py -v

# Specific test for model consistency
pytest tests/test_workflow_contracts.py -k "model" -v

# Test placeholder injection
pytest tests/test_workflow_stress.py -k "placeholder" -v
```

---

## Version History

| Date | Change | Author |
|------|--------|--------|
| Dec 2024 | Initial tier system (dev/standard/beast) | - |
| Dec 2024 | Added model placeholders to Pass 1 workflows | - |
| - | - | - |

---

## Related Documents

- `ARCHITECTURE_SUMMARY.md` - Overall system design
- `LESSONS_LEARNED.md` - Debugging history and gotchas
- `workflows/models.json` - The actual model registry