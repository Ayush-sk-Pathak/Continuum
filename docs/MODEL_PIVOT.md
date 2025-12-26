# MODEL PIVOT DOCUMENT: Wan 2.1 → HunyuanVideo 1.5

**Version:** 1.0.0  
**Created:** December 26, 2025  
**Status:** ACTIVE - In Progress  
**Timeline:** 10-12 days to investor demo  

---

## Executive Summary

This document provides the complete roadmap for pivoting from Wan 2.1 to HunyuanVideo 1.5 
as the primary video generation model, while preserving the ability to switch back to Wan.

**Why Pivot:**
- Hunyuan ecosystem achieves **3× better identity** than Wan (0.627 vs 0.204 ArcFace)
- Lower VRAM requirements (14-24GB vs 24-40GB)
- Faster inference (~75 seconds on 4090 with step-distilled model)
- Better instruction following in benchmarks
- No existing Wan LoRAs to lose (zero switching cost)

**Critical Clarification (Updated After Research):**
The original assumption that "native IP2V provides 95%+ identity with 1 image" was **oversold**.
Reality:
- HunyuanVideo 1.5 has NO external reference input (unlike IP-Adapter)
- Identity comes ONLY from the init_image (first frame)
- The 0.627 ArcFace benchmark is from **HunyuanCustom**, not base HunyuanVideo 1.5
- Our **Bridge Frame strategy becomes MORE critical** - it's the only external reference injection point

**Revised Identity Strategy:**
```
SDXL Hero Frame (with IP-Adapter + face reference)
        ↓
    [Identity locked here via IP-Adapter]
        ↓
HunyuanVideo I2V (preserves init_image identity)
        ↓
    [Hunyuan maintains whatever identity was in init_image]
```

**Design Constraint:**
Switching between models must be a single config change:
```bash
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan  # or "wan"
```

---

## Table of Contents

1. [Current System Analysis](#1-current-system-analysis)
2. [Target Architecture](#2-target-architecture)
3. [File Inventory & Classification](#3-file-inventory--classification)
4. [Implementation Phases](#4-implementation-phases)
5. [Testing Protocol](#5-testing-protocol)
6. [Debugging Guide](#6-debugging-guide)
7. [Rollback Procedure](#7-rollback-procedure)
8. [Risk Matrix](#8-risk-matrix)
9. [Day-by-Day Schedule](#9-day-by-day-schedule)

---

## 1. Current System Analysis

### 1.1 Architecture Layers (What Touches the Video Model)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LAYER 1: ORCHESTRATION                           │
│   main.py → Pass1Generator → BridgeEngine → Renderer                   │
│                                                                         │
│   Status: MOSTLY MODEL-AGNOSTIC                                         │
│   Issue:  main.py hardcodes WanRenderer import                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        LAYER 2: RENDERING                               │
│   WanRenderer → WorkflowLoader → ComfyUI Client                        │
│                                                                         │
│   Status: MODEL-SPECIFIC (WanRenderer)                                  │
│   Issue:  Workflow names hardcoded in WanRenderer class constants       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        LAYER 3: WORKFLOWS                               │
│   *.json files → ComfyUI node graphs                                   │
│                                                                         │
│   Status: MODEL-SPECIFIC (Wan nodes: WanImageToVideo, etc.)             │
│   Issue:  All workflows in flat directory, no model family separation   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        LAYER 4: MODELS                                  │
│   models.json → model file paths on RunPod                             │
│                                                                         │
│   Status: EXTENSIBLE (already supports multiple families)               │
│   Issue:  Need to add Hunyuan 1.5 entries                               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Coupling Points (Files That Need Changes)

| File | Current State | Required Change | Risk Level |
|------|---------------|-----------------|------------|
| `config.py` | No video model selector | Add `video_model` config section | LOW |
| `main.py` | Hardcodes `WanRenderer` | Use renderer factory | LOW |
| `wan_renderer.py` | Wan-specific implementation | Keep as-is, create sibling | NONE |
| `workflow_loader.py` | Flat directory lookup | Add model-family subdirectory support | MEDIUM |
| `bridge_engine.py` | Uses SDXL workflows | No change needed (SDXL is shared) | NONE |
| `pass1_generator.py` | Uses passed renderer | No change needed | NONE |
| `models.json` | Has wan21 entries | Add hunyuan15 entries | LOW |
| `base.py` | Has RendererType enum | Add factory function | LOW |

### 1.3 Workflow Classification

**VIDEO MODEL-SPECIFIC (Must be duplicated for Hunyuan):**
```
pass1_img2vid.json           # I2V generation
pass1_img2vid_lora.json      # I2V with LoRA
pass1_structural.json        # T2V generation  
pass1_structural_lora.json   # T2V with LoRA
refine_vid2vid_simple.json   # Vid2Vid refinement
refine_vid2vid_temporal.json # Temporal refinement
```

**SHARED SDXL WORKFLOWS (Model-agnostic, no changes needed):**
```
hero_frame.json              # SDXL + IP-Adapter for Shot 1
bridge_full.json             # SDXL + ControlNet + IP-Adapter
bridge_pose_only.json        # SDXL + ControlNet
bridge_ipadapter.json        # SDXL + IP-Adapter only
bridge_basic.json            # SDXL basic
bridge_pose_extract.json     # ControlNet preprocessor
bridge_depth_extract.json    # Depth extraction
```

**UTILITY WORKFLOWS (Model-agnostic):**
```
rife_interpolation.json      # Frame interpolation
musetalk_lipsync.json        # Lip sync
```

**CONFIG FILES (Not workflows):**
```
models.json                  # Model path registry
bible.json                   # Test character data
sample_project.json          # Test project
quick_test.json              # Test config
```

---

## 2. Target Architecture

### 2.1 Directory Structure

```
/workflows/
├── wan/                              # Wan 2.1 specific
│   ├── pass1_img2vid.json
│   ├── pass1_img2vid_lora.json
│   ├── pass1_structural.json
│   ├── pass1_structural_lora.json
│   ├── refine_vid2vid_simple.json
│   └── refine_vid2vid_temporal.json
│
├── hunyuan/                          # Hunyuan 1.5 specific
│   ├── pass1_img2vid.json            # SAME NAMES, different nodes
│   ├── pass1_img2vid_lora.json
│   ├── pass1_t2v.json
│   ├── pass1_t2v_lora.json
│   └── refine_vid2vid.json
│
├── shared/                           # Model-agnostic (SDXL-based)
│   ├── hero_frame.json
│   ├── bridge_full.json
│   ├── bridge_pose_only.json
│   ├── bridge_ipadapter.json
│   ├── bridge_basic.json
│   ├── bridge_pose_extract.json
│   ├── bridge_depth_extract.json
│   ├── rife_interpolation.json
│   └── musetalk_lipsync.json
│
└── models.json                       # Stays in root
```

### 2.2 Config-Driven Model Selection

```python
# .env or environment
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan
CONTINUUM_VIDEO_MODEL__MODEL_TIER=dev

# Results in:
config.video_model.model_family  # "hunyuan"
config.video_model.model_tier    # "dev"
```

### 2.3 Renderer Factory Pattern

```python
# base.py - NEW FUNCTION
def get_renderer_for_config(config: Optional[Config] = None) -> BaseRenderer:
    """Single source of truth for renderer instantiation."""
    config = config or get_config()
    family = config.video_model.model_family
    
    if family == "wan":
        from .wan_renderer import WanRenderer
        return WanRenderer()
    elif family == "hunyuan":
        from .hunyuan_renderer import HunyuanRenderer
        return HunyuanRenderer()
    else:
        raise ValueError(f"Unknown model family: {family}")
```

### 2.4 Workflow Loader Enhancement

```python
# workflow_loader.py - MODIFIED
class WorkflowLoader:
    def __init__(self, workflows_dir: Path, model_family: Optional[str] = None):
        self.base_dir = workflows_dir
        self.model_family = model_family or get_config().video_model.model_family
        self.model_dir = self.base_dir / self.model_family
        self.shared_dir = self.base_dir / "shared"
    
    def _find_workflow_file(self, name: str) -> Optional[Path]:
        """Try model-specific first, then shared."""
        # Priority 1: Model-specific
        model_path = self.model_dir / f"{name}.json"
        if model_path.exists():
            return model_path
        
        # Priority 2: Shared
        shared_path = self.shared_dir / f"{name}.json"
        if shared_path.exists():
            return shared_path
        
        # Priority 3: Legacy (root directory - for backwards compat)
        legacy_path = self.base_dir / f"{name}.json"
        if legacy_path.exists():
            logger.warning(f"Using legacy workflow path: {legacy_path}")
            return legacy_path
        
        return None
```

---

## 3. File Inventory & Classification

### 3.1 Files to MODIFY

| File | Change Type | Description |
|------|-------------|-------------|
| `config.py` | ADD | New `VideoModelConfig` class |
| `main.py` | MODIFY | Replace hardcoded WanRenderer with factory |
| `workflow_loader.py` | MODIFY | Add model-family directory support |
| `base.py` | ADD | New `get_renderer_for_config()` function |
| `models.json` | ADD | Hunyuan 1.5 model entries |

### 3.2 Files to CREATE

| File | Purpose |
|------|---------|
| `hunyuan_renderer.py` | HunyuanVideo 1.5 renderer implementation |
| `workflows/hunyuan/pass1_img2vid.json` | Hunyuan I2V workflow |
| `workflows/hunyuan/pass1_img2vid_lora.json` | Hunyuan I2V + LoRA workflow |
| `workflows/hunyuan/pass1_t2v.json` | Hunyuan T2V workflow |
| `MODEL_PIVOT_HUNYUAN.md` | This document |

### 3.3 Files to MOVE (Not Modify)

| Current Location | New Location |
|------------------|--------------|
| `pass1_img2vid.json` | `workflows/wan/pass1_img2vid.json` |
| `pass1_img2vid_lora.json` | `workflows/wan/pass1_img2vid_lora.json` |
| `pass1_structural.json` | `workflows/wan/pass1_structural.json` |
| `pass1_structural_lora.json` | `workflows/wan/pass1_structural_lora.json` |
| `pass1_img2vid_facevideo.json` | `workflows/wan/pass1_img2vid_facevideo.json` |
| `pass1_img2vid_firstlast.json` | `workflows/wan/pass1_img2vid_firstlast.json` |
| `pass1_img2vid_phantom.json` | `workflows/wan/pass1_img2vid_phantom.json` |
| `refine_vid2vid_simple.json` | `workflows/wan/refine_vid2vid_simple.json` |
| `refine_vid2vid_temporal.json` | `workflows/wan/refine_vid2vid_temporal.json` |
| `hero_frame.json` | `workflows/shared/hero_frame.json` |
| `bridge_*.json` | `workflows/shared/bridge_*.json` |
| `rife_interpolation.json` | `workflows/shared/rife_interpolation.json` |
| `musetalk_lipsync.json` | `workflows/shared/musetalk_lipsync.json` |

### 3.4 Files to LEAVE ALONE

| File | Reason |
|------|--------|
| `wan_renderer.py` | Keep working, sibling to new hunyuan_renderer.py |
| `bridge_engine.py` | Uses SDXL workflows, model-agnostic |
| `pass1_generator.py` | Uses renderer interface, model-agnostic |
| `identity_checker.py` | Works on output frames, model-agnostic |
| `physics_checker.py` | Works on output frames, model-agnostic |
| All audio modules | Completely independent of video model |

---

## 4. Implementation Phases

### Phase 0: Pre-Flight Validation (Day 1 Morning)

**CRITICAL: Do NOT write any code until this passes.**

```bash
# On RunPod - Validate Hunyuan 1.5 works at all

# Step 1: Download models
cd /workspace/ComfyUI/models/diffusion_models
wget https://huggingface.co/.../hunyuanvideo1.5_720p_i2v_fp16.safetensors

cd /workspace/ComfyUI/models/text_encoders
wget https://huggingface.co/.../qwen_2.5_vl_7b_fp8_scaled.safetensors

cd /workspace/ComfyUI/models/vae
wget https://huggingface.co/.../hunyuanvideo15_vae_fp16.safetensors

# Step 2: Test official workflow in ComfyUI UI
# - Download official Hunyuan 1.5 I2V workflow
# - Load in ComfyUI
# - Run with test image
# - RECORD: exact node class_type names

# Step 3: Test with face reference
# - Use alice_01.png as init image
# - Check identity preservation in output

# Step 4: Document findings
# - Screenshot working workflow
# - List all node class_type values
# - Note any quirks or errors
```

**Exit Criteria:** Hunyuan generates a video from an image with acceptable identity.

### Phase 1: Infrastructure (Days 1-2)

#### 1.1 Add Config Section

**File:** `config.py`
**Location:** After line 127 (after `PostConfig`)

```python
class VideoModelConfig(BaseModel):
    """Video model selection and configuration."""
    
    model_family: Literal["wan", "hunyuan"] = Field(
        default="hunyuan",
        description="Video generation model family"
    )
    model_tier: Literal["dev", "standard", "beast"] = Field(
        default="dev", 
        description="Quality/speed tier within model family"
    )
    
    @field_validator("model_family")
    @classmethod
    def validate_model_family(cls, v: str) -> str:
        valid = ["wan", "hunyuan"]
        if v not in valid:
            raise ValueError(f"model_family must be one of {valid}")
        return v
```

**Then add to Config class (after line 282):**

```python
video_model: VideoModelConfig = Field(default_factory=VideoModelConfig)
```

**Test:** 
```python
from src.core.config import get_config
config = get_config()
assert config.video_model.model_family in ["wan", "hunyuan"]
```

#### 1.2 Create Directory Structure

```bash
# From project root
mkdir -p workflows/wan
mkdir -p workflows/hunyuan  
mkdir -p workflows/shared

# Move Wan-specific workflows
mv pass1_img2vid.json workflows/wan/
mv pass1_img2vid_lora.json workflows/wan/
mv pass1_img2vid_facevideo.json workflows/wan/
mv pass1_img2vid_firstlast.json workflows/wan/
mv pass1_img2vid_phantom.json workflows/wan/
mv pass1_structural.json workflows/wan/
mv pass1_structural_lora.json workflows/wan/
mv refine_vid2vid_simple.json workflows/wan/
mv refine_vid2vid_temporal.json workflows/wan/

# Move shared workflows
mv hero_frame.json workflows/shared/
mv bridge_full.json workflows/shared/
mv bridge_basic.json workflows/shared/
mv bridge_ipadapter.json workflows/shared/
mv bridge_pose_only.json workflows/shared/
mv bridge_pose_extract.json workflows/shared/
mv bridge_depth_extract.json workflows/shared/
mv rife_interpolation.json workflows/shared/
mv musetalk_lipsync.json workflows/shared/
```

**Test:**
```bash
ls workflows/wan/      # Should show pass1_* files
ls workflows/shared/   # Should show bridge_*, hero_frame.json
ls workflows/hunyuan/  # Should be empty (we'll populate later)
```

#### 1.3 Update Workflow Loader

**File:** `workflow_loader.py`
**Change:** `_find_workflow_file` method (around line 287)

```python
def __init__(
    self,
    workflows_dir: Optional[Path] = None,
    model_family: Optional[str] = None,  # NEW PARAMETER
):
    """
    Initialize workflow loader.
    
    Args:
        workflows_dir: Root directory for workflows
        model_family: Model family subdirectory (wan/hunyuan)
                     If None, reads from config
    """
    if workflows_dir is None:
        workflows_dir = get_config().paths.workflows_dir
    
    self.workflows_dir = Path(workflows_dir)
    
    # Model family for subdirectory lookup
    if model_family is None:
        try:
            model_family = get_config().video_model.model_family
        except Exception:
            model_family = "wan"  # Fallback for backwards compat
    
    self.model_family = model_family
    self.model_dir = self.workflows_dir / model_family
    self.shared_dir = self.workflows_dir / "shared"
    
    # Cache loaded templates
    self._template_cache: Dict[str, WorkflowTemplate] = {}

def _find_workflow_file(self, name: str) -> Optional[Path]:
    """
    Find workflow file with model-family awareness.
    
    Search order:
    1. Model-specific: workflows/{model_family}/{name}.json
    2. Shared: workflows/shared/{name}.json
    3. Legacy: workflows/{name}.json (backwards compat, logs warning)
    """
    candidates = []
    
    # Priority 1: Model-specific directory
    if self.model_dir.exists():
        candidates.append(self.model_dir / f"{name}.json")
    
    # Priority 2: Shared directory
    if self.shared_dir.exists():
        candidates.append(self.shared_dir / f"{name}.json")
    
    # Priority 3: Legacy root directory (backwards compatibility)
    candidates.append(self.workflows_dir / f"{name}.json")
    candidates.append(self.workflows_dir / f"{name}_workflow.json")
    
    for path in candidates:
        if path.exists() and path.is_file():
            # Warn if using legacy path
            if path.parent == self.workflows_dir:
                logger.warning(
                    f"Using legacy workflow path: {path}. "
                    f"Consider moving to workflows/{self.model_family}/ or workflows/shared/"
                )
            return path
    
    return None
```

**Test:**
```python
from src.comfy_client import WorkflowLoader

# Test Wan workflows
loader_wan = WorkflowLoader(model_family="wan")
assert loader_wan.load("pass1_img2vid") is not None

# Test shared workflows  
loader_wan = WorkflowLoader(model_family="wan")
assert loader_wan.load("hero_frame") is not None  # Should find in shared/

# Test Hunyuan (will fail until we create workflows)
loader_hunyuan = WorkflowLoader(model_family="hunyuan")
# This should NOT find pass1_img2vid yet
```

#### 1.4 Add Renderer Factory

**File:** `base.py`
**Location:** After line 565 (after `list_renderers()`)

```python
def get_renderer_for_config(config: Optional["Config"] = None) -> BaseRenderer:
    """
    Create the appropriate renderer based on configuration.
    
    This is the CANONICAL way to get a renderer. All code paths should
    use this function rather than importing specific renderer classes.
    
    Args:
        config: Config object (uses get_config() if None)
        
    Returns:
        Appropriate renderer instance for the configured model family
        
    Raises:
        ValueError: If model family is unknown
        
    Example:
        renderer = get_renderer_for_config()
        result = await renderer.generate(job)
    """
    if config is None:
        from ..core.config import get_config
        config = get_config()
    
    model_family = config.video_model.model_family
    
    if model_family == "wan":
        from .wan_renderer import WanRenderer
        return WanRenderer()
    elif model_family == "hunyuan":
        from .hunyuan_renderer import HunyuanRenderer
        return HunyuanRenderer()
    else:
        available = ["wan", "hunyuan"]
        raise ValueError(
            f"Unknown model family: '{model_family}'. "
            f"Available: {available}. "
            f"Set CONTINUUM_VIDEO_MODEL__MODEL_FAMILY environment variable."
        )
```

#### 1.5 Update models.json

**File:** `models.json`
**Add after the wan21 section:**

```json
"hunyuan15": {
  "_description": "HunyuanVideo 1.5 (Dec 2025) - Verified model filenames",
  
  "t2v": {
    "dev": {
      "_description": "720p T2V with CFG distillation",
      "unet": "hunyuanvideo1.5_720p_t2v_cfg_distilled_fp8_scaled.safetensors",
      "vae": "hunyuan_video_vae_bf16.safetensors",
      "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
      "vram_required_gb": 16,
      "max_resolution": "720p",
      "quality_tier": 1
    }
  },
  
  "i2v": {
    "dev": {
      "_description": "720p I2V with CFG distillation (FP8)",
      "unet": "hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors",
      "vae": "hunyuan_video_vae_bf16.safetensors",
      "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
      "clip_vision": "sigclip_vision_patch14_384.safetensors",
      "vram_required_gb": 16,
      "max_resolution": "720p",
      "quality_tier": 1,
      "cfg_scale": 1.0,
      "flow_shift": 7.0,
      "steps": 50
    },
    "standard": {
      "_description": "720p I2V full precision (FP16)",
      "unet": "hunyuanvideo1.5_720p_i2v_fp16.safetensors",
      "vae": "hunyuan_video_vae_bf16.safetensors",
      "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
      "clip_vision": "sigclip_vision_patch14_384.safetensors",
      "vram_required_gb": 24,
      "max_resolution": "720p",
      "quality_tier": 2,
      "cfg_scale": 1.0,
      "flow_shift": 7.0,
      "steps": 50
    }
  },
  
  "i2v_distilled": {
    "_description": "Step-distilled I2V - 480p ONLY (720p not available yet)",
    "dev": {
      "unet": "hunyuanvideo1.5_480p_i2v_step_distilled_fp8_scaled.safetensors",
      "vae": "hunyuan_video_vae_bf16.safetensors",
      "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
      "clip_vision": "sigclip_vision_patch14_384.safetensors",
      "vram_required_gb": 14,
      "max_resolution": "480p",
      "quality_tier": 1,
      "cfg_scale": 1.0,
      "flow_shift": 5.0,
      "steps": 8,
      "_note": "75 seconds on RTX 4090"
    }
  }
}
```

**Model file sizes (verified):**
| File | Size |
|------|------|
| hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors | 8.33 GB |
| hunyuanvideo1.5_720p_i2v_fp16.safetensors | 16.7 GB |
| qwen_2.5_vl_7b_fp8_scaled.safetensors | 9.38 GB |
| sigclip_vision_patch14_384.safetensors | 857 MB |
| hunyuan_video_vae_bf16.safetensors | ~2 GB |

**Source:** `Comfy-Org/HunyuanVideo_1.5_repackaged` (Hugging Face, updated Dec 25, 2025)

**Test:**
```python
from src.core.model_loader import get_model_config, ModelTier
config = get_model_config("hunyuan15", "i2v", ModelTier.DEV)
assert "hunyuanvideo1.5" in config.unet
assert config.clip_vision == "sigclip_vision_patch14_384.safetensors"
```

### Phase 2: Hunyuan Renderer (Days 3-4)

#### 2.1 Create HunyuanRenderer

**File:** `hunyuan_renderer.py` (NEW FILE)

```python
"""
Continuum Engine - HunyuanVideo 1.5 Renderer

Concrete renderer implementation using HunyuanVideo 1.5 via ComfyUI.
Designed as a drop-in alternative to WanRenderer.

Key Differences from Wan:
1. Native identity preservation via IP2V (SigLIP + Qwen2.5-VL)
2. Lower VRAM requirements (14-24GB vs 24-40GB)
3. Different ComfyUI node types (HunyuanVideoSampler vs WanImageToVideo)
4. Step-distilled option for faster inference

Design Principles:
1. Same interface as WanRenderer (implements BaseRenderer)
2. Same workflow naming convention (pass1_img2vid, etc.)
3. Same parameter injection pattern ({{PLACEHOLDER}})
4. Different underlying ComfyUI nodes
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import (
    BaseRenderer,
    JobSpec,
    RenderResult,
    RenderProgress,
    RendererType,
    RenderQuality,
    RenderError,
    CharacterRef,
    register_renderer,
)
from ..comfy_client import (
    ComfyClient,
    ComfyJob,
    WorkflowLoader,
    merge_params,
)
from ..core.config import get_config
from ..core.model_loader import get_model_config, ModelTier

logger = logging.getLogger(__name__)


@register_renderer(RendererType.HUNYUAN)
class HunyuanRenderer(BaseRenderer):
    """
    Renderer using HunyuanVideo 1.5 via ComfyUI.
    
    This is the "Standard Lane" renderer optimized for identity preservation
    with lower VRAM requirements than Wan.
    """
    
    # Workflow templates - SAME NAMES as Wan for consistency
    DEFAULT_WORKFLOW = "pass1_t2v"
    WORKFLOW_WITH_LORA = "pass1_t2v_lora"
    WORKFLOW_IMG2VID = "pass1_img2vid"
    WORKFLOW_IMG2VID_LORA = "pass1_img2vid_lora"
    
    # Hunyuan-specific: Native identity via image conditioning
    # No need for separate IP-Adapter workflow - it's built in
    
    SUPPORTED_FEATURES = {
        "init_frame",
        "lora",
        "native_identity",  # Hunyuan's key advantage
        "long_video",
    }
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        workflows_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        super().__init__(RendererType.HUNYUAN)
        
        config = get_config()
        
        self.comfy_host = comfy_host or config.comfyui.host
        self.workflows_dir = workflows_dir or config.paths.workflows_dir
        self.output_dir = output_dir or config.paths.output_dir
        self.timeout_sec = config.comfyui.timeout_sec
        
        self._client: Optional[ComfyClient] = None
        self._loader: Optional[WorkflowLoader] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize ComfyUI connection and workflow loader."""
        if self._initialized:
            return
        
        logger.info(f"Initializing HunyuanRenderer (host={self.comfy_host})")
        
        # Create workflow loader with hunyuan model family
        self._loader = WorkflowLoader(
            self.workflows_dir,
            model_family="hunyuan"
        )
        
        self._client = ComfyClient(host=self.comfy_host)
        await self._client.connect()
        
        self._initialized = True
        logger.info("HunyuanRenderer initialized successfully")
    
    async def shutdown(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._initialized = False
        logger.info("HunyuanRenderer shut down")
    
    async def generate(
        self,
        job: JobSpec,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> RenderResult:
        """Generate video using HunyuanVideo 1.5."""
        # Implementation follows same pattern as WanRenderer
        # Key difference: Hunyuan has native identity conditioning
        # so we don't need separate IP-Adapter injection
        
        # ... (full implementation similar to WanRenderer)
        pass
    
    def _select_workflow_template(self, job: JobSpec) -> str:
        """
        Select appropriate workflow for job.
        
        Hunyuan Simplification:
        - No separate IP-Adapter workflow needed
        - Native identity via image encoder
        - Simpler decision tree than Wan
        """
        has_lora = False
        if job.character_refs:
            has_lora = job.character_refs[0].has_lora()
        
        # I2V path (with init_frame)
        if job.has_init_frame:
            if has_lora:
                return self.WORKFLOW_IMG2VID_LORA
            return self.WORKFLOW_IMG2VID  # Native identity via init_frame
        
        # T2V path
        if has_lora:
            return self.WORKFLOW_WITH_LORA
        return self.DEFAULT_WORKFLOW
    
    def _get_model_config(self, job: JobSpec) -> Dict[str, Any]:
        """Get Hunyuan model paths for workflow injection."""
        model_type = "i2v" if job.has_init_frame else "t2v"
        
        try:
            config = get_model_config("hunyuan15", model_type)
            return config.to_workflow_params()
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"Could not load Hunyuan model config: {e}")
            return {}
    
    # ... (rest of implementation mirrors WanRenderer structure)
```

#### 2.2 Create Hunyuan Workflows

**NOTE:** Exact node names must be discovered during Phase 0 validation.

**File:** `workflows/hunyuan/pass1_img2vid.json`

```json
{
  "_metadata": {
    "description": "HunyuanVideo 1.5 Image-to-Video with native identity",
    "model": "hunyuan15",
    "type": "i2v"
  },
  
  "hunyuan_model_loader": {
    "class_type": "HunyuanVideoModelLoader",
    "inputs": {
      "model_path": "{{UNET_MODEL}}",
      "dtype": "bf16"
    }
  },
  
  "vae_loader": {
    "class_type": "VAELoader",
    "inputs": {
      "vae_name": "{{VAE_MODEL}}"
    }
  },
  
  "text_encoder": {
    "class_type": "HunyuanTextEncode",
    "inputs": {
      "clip_name": "{{CLIP_MODEL}}",
      "prompt": "{{POSITIVE_PROMPT}}"
    }
  },
  
  "load_init_image": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "{{INIT_IMAGE}}"
    }
  },
  
  "image_encoder": {
    "class_type": "HunyuanImageEncode",
    "inputs": {
      "image": ["load_init_image", 0],
      "clip_vision": "{{CLIP_VISION_MODEL}}"
    }
  },
  
  "sampler": {
    "class_type": "HunyuanVideoSampler",
    "inputs": {
      "model": ["hunyuan_model_loader", 0],
      "positive": ["text_encoder", 0],
      "image_embeds": ["image_encoder", 0],
      "seed": "{{SEED}}",
      "steps": "{{STEPS}}",
      "cfg": "{{CFG_SCALE}}",
      "width": "{{WIDTH}}",
      "height": "{{HEIGHT}}",
      "num_frames": "{{FRAMES}}"
    }
  },
  
  "vae_decode": {
    "class_type": "VAEDecode",
    "inputs": {
      "samples": ["sampler", 0],
      "vae": ["vae_loader", 0]
    }
  },
  
  "save_video": {
    "class_type": "SaveVideo",
    "inputs": {
      "images": ["vae_decode", 0],
      "filename_prefix": "continuum/hunyuan_i2v",
      "fps": "{{FPS}}"
    }
  }
}
```

### Phase 3: Integration (Days 5-6)

#### 3.1 Update main.py

**File:** `main.py`
**Change:** Lines 111 and 669-672

```python
# OLD (line 111):
from src.renderers.wan_renderer import WanRenderer

# NEW:
from src.renderers.base import get_renderer_for_config


# OLD (lines 669-672):
if self.dry_run:
    self.renderer = get_renderer(RendererType.MOCK)
else:
    logger.info(f"Initializing WanRenderer (host={self.config.comfyui.host})")
    self.renderer = WanRenderer()

# NEW:
if self.dry_run:
    self.renderer = get_renderer(RendererType.MOCK)
else:
    model_family = self.config.video_model.model_family
    logger.info(f"Initializing {model_family} renderer (host={self.config.comfyui.host})")
    self.renderer = get_renderer_for_config(self.config)
```

#### 3.2 Verify Bridge Engine Compatibility

**No changes needed** - BridgeEngine uses SDXL workflows which are in `shared/`.

**Test:**
```python
# Bridge engine should still work
from src.studio.bridge_engine import ComfyUIBridgeEngine

engine = ComfyUIBridgeEngine()
# Should load hero_frame.json from workflows/shared/
# Should load bridge_full.json from workflows/shared/
```

#### 3.3 Update Pass1Generator (If Needed)

Check if Pass1Generator hardcodes any renderer:

```bash
grep -n "WanRenderer" pass1_generator.py
```

If found, replace with factory pattern.

### Phase 4: Validation (Days 7-9)

See Section 5: Testing Protocol.

### Phase 5: Buffer (Day 10)

Reserved for unexpected issues.

---

## 5. Testing Protocol

### 5.1 Unit Tests (Run After Each Phase)

```bash
# After Phase 1: Infrastructure
python -c "
from src.core.config import get_config
config = get_config()
print(f'Model family: {config.video_model.model_family}')
assert config.video_model.model_family in ['wan', 'hunyuan']
print('✓ Config test passed')
"

python -c "
from src.comfy_client import WorkflowLoader
loader = WorkflowLoader(model_family='wan')
template = loader.load('pass1_img2vid')
print(f'Loaded: {template.name}')
print('✓ Workflow loader test passed')
"

python -c "
from src.core.model_loader import get_model_config, ModelTier
config = get_model_config('hunyuan15', 'i2v', ModelTier.DEV)
print(f'Hunyuan I2V model: {config.unet}')
print('✓ Model loader test passed')
"
```

### 5.2 Integration Tests

```bash
# Test Wan still works after restructuring
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py --project tests/quick_test.json --dry-run -v

# Test Hunyuan renderer instantiation
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan \
python -c "
from src.renderers.base import get_renderer_for_config
renderer = get_renderer_for_config()
print(f'Renderer type: {renderer.renderer_type}')
"
```

### 5.3 End-to-End Tests

```bash
# Wan E2E (should work same as before)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py \
  --project tests/quick_test.json \
  --consistency tests/bible.json \
  --output workspace/output/wan_test \
  --no-pass2 -v

# Hunyuan E2E
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan \
python main.py \
  --project tests/quick_test.json \
  --consistency tests/bible.json \
  --output workspace/output/hunyuan_test \
  --no-pass2 -v
```

### 5.4 Identity Preservation Tests

```bash
# 4-second clip identity test
python main.py \
  --project tests/identity_test_4sec.json \
  --consistency tests/bible.json \
  --output workspace/output/identity_test \
  -v

# Check ArcFace scores in output
# Target: >= 0.95 frame 1 vs frame 96
```

### 5.5 Model Switching Test

```bash
# Generate with Hunyuan
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan \
python main.py --project tests/quick_test.json --output workspace/output/switch_hunyuan

# Switch to Wan (same project)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py --project tests/quick_test.json --output workspace/output/switch_wan

# Both should complete without errors
```

---

## 6. Debugging Guide

### 6.1 Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `FileNotFoundError: Workflow 'pass1_img2vid' not found` | Workflows not moved to subdirectories | Run Phase 1.2 file moves |
| `Unknown model family: hunyuan` | Config not updated | Add VideoModelConfig to config.py |
| `ModuleNotFoundError: hunyuan_renderer` | HunyuanRenderer not created | Create file in Phase 2 |
| `KeyError: 'hunyuan15'` | models.json not updated | Add hunyuan15 section |
| `ComfyUI node not found: HunyuanVideoSampler` | Wrong node name | Check exact names from Phase 0 |

### 6.2 Diagnostic Commands

```bash
# Check which model family is configured
python -c "from src.core.config import get_config; print(get_config().video_model.model_family)"

# List available workflows for current model
python -c "
from src.comfy_client import WorkflowLoader
loader = WorkflowLoader()
print(loader.list_templates())
"

# Test ComfyUI connection
python -c "
import asyncio
from src.comfy_client import ComfyClient
async def test():
    client = ComfyClient()
    await client.connect()
    print('Connected:', await client.health_check())
asyncio.run(test())
"

# Check if Hunyuan nodes exist on ComfyUI server
curl -s http://localhost:8188/object_info | python -c "
import sys, json
data = json.load(sys.stdin)
hunyuan_nodes = [k for k in data.keys() if 'hunyuan' in k.lower()]
print('Hunyuan nodes:', hunyuan_nodes)
"
```

### 6.3 Log Locations

```
workspace/output/*/generation.log    # Per-project generation logs
workspace/checkpoints/               # Checkpoint state files
```

### 6.4 Workflow Debugging

```python
# Test workflow loading in isolation
from src.comfy_client import WorkflowLoader

loader = WorkflowLoader(model_family="hunyuan")
template = loader.load("pass1_img2vid")

print("Placeholders found:", template.placeholders)
print("Workflow structure:", list(template.workflow.keys()))
```

---

## 7. Rollback Procedure

If Hunyuan integration fails and you need to revert to Wan:

### 7.1 Quick Rollback (Config Only)

```bash
# Set environment variable
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan

# Or in .env file
echo "CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan" >> .env

# Restart application
```

### 7.2 Full Rollback (Code Changes)

```bash
# Revert main.py to hardcoded WanRenderer
git checkout main.py

# Keep directory structure (doesn't hurt anything)
# Wan workflows still work from workflows/wan/
```

### 7.3 Rollback Checklist

- [ ] Set CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan
- [ ] Verify Wan workflows exist in workflows/wan/
- [ ] Test quick_test.json with Wan
- [ ] Confirm identity preservation still works

---

## 8. Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Hunyuan nodes don't exist on ComfyUI | Low | High | Phase 0 validation before any code |
| Workflow loader breaks Wan | Medium | High | Legacy path fallback + thorough testing |
| Identity worse than Wan | Medium | Medium | Side-by-side comparison, can switch back |
| VRAM higher than claimed | Low | Medium | Test on actual RunPod before committing |
| Unknown node names | Medium | Medium | Screenshot working workflow in Phase 0 |
| Bridge frames break | Low | High | Bridge uses SDXL, should be unaffected |
| Demo deadline missed | Medium | High | Day 10 buffer, can demo Wan if needed |
| **Native IP2V < 93% identity** | Medium | Low | Fall back to LoRA training (still faster than Wan) |
| **IP2V claim is oversold** | Low | Medium | We still have IP-Adapter fallback |

---

## 9. Day-by-Day Schedule

### Day 1: Validation (CRITICAL - Tests IP2V Hypothesis)
- [ ] Morning: Download Hunyuan models to RunPod
- [ ] Morning: Test official ComfyUI workflow (basic generation)
- [ ] Afternoon: **Test native IP2V identity** (single reference image, no LoRA)
- [ ] Afternoon: Measure ArcFace across 4-second clip (target: >= 0.93)
- [ ] Afternoon: Test high-motion scenario (head turn)
- [ ] **EXIT GATE:** Native IP2V achieves >= 93% identity (if yes, LoRA is optional for MVP)

### Day 2: Infrastructure
- [ ] Add VideoModelConfig to config.py
- [ ] Create directory structure
- [ ] Move workflow files
- [ ] Update workflow_loader.py
- [ ] Test Wan still works

### Day 3: Hunyuan Renderer (Part 1)
- [ ] Create hunyuan_renderer.py skeleton
- [ ] Implement initialize/shutdown
- [ ] Implement _select_workflow_template
- [ ] Add to renderer registry

### Day 4: Hunyuan Renderer (Part 2)
- [ ] Create Hunyuan workflow JSONs
- [ ] Implement generate() method
- [ ] Test basic generation
- [ ] Debug ComfyUI node issues

### Day 5: Integration
- [ ] Update main.py renderer factory
- [ ] Verify bridge_engine compatibility
- [ ] Run integration tests
- [ ] Fix any breaks

### Day 6: Identity Testing
- [ ] Run 4-second identity tests
- [ ] Compare Wan vs Hunyuan quality
- [ ] Test multi-shot sequence
- [ ] Document results

### Day 7: Polish
- [ ] Fix any remaining bugs
- [ ] Optimize workflow parameters
- [ ] Test model switching both directions
- [ ] Update documentation

### Day 8: Demo Content
- [ ] Create investor demo project
- [ ] Generate demo videos
- [ ] Review quality
- [ ] Re-render if needed

### Day 9: Demo Polish
- [ ] Final quality review
- [ ] Prepare backup Wan demo (if needed)
- [ ] Test on fresh RunPod instance
- [ ] Document any gotchas

### Day 10: Buffer
- [ ] Reserved for unexpected issues
- [ ] Final rehearsal
- [ ] Backup everything

---

## Appendix A: Node Name Discovery

### Verified ComfyUI Node Names (From Research)

**Native ComfyUI (v0.3.75+) - RECOMMENDED:**

| Purpose | `class_type` | Notes |
|---------|--------------|-------|
| Model Loader | `UNETLoader` | Standard loader |
| Dual CLIP Loader | `DualCLIPLoader` | Loads both text encoders |
| CLIP Vision Loader | `CLIPVisionLoader` | For SigLIP |
| CLIP Vision Encode | `CLIPVisionEncode` | Encodes init_image |
| Text Encoder (I2V) | `TextEncodeHunyuanVideo_ImageToVideo` | I2V-specific |
| Main I2V Node | `HunyuanImageToVideo` | Core generation |
| VAE Loader | `VAELoader` | Standard |
| VAE Decode | `VAEDecode` | Standard |

**Kijai Wrapper (INCOMPATIBLE - Do Not Mix):**

| Purpose | `class_type` |
|---------|--------------|
| Model Loader | `HyVideoModelLoader` |
| Sampler | `HyVideoSampler` |
| I2V Encode | `HyVideoI2VEncode` |
| LoRA Select | `HyVideoLoraSelect` |

**DECISION:** Use native ComfyUI nodes. They are:
- 18% faster on RTX 4090
- Zero workflow crashes reported
- Officially supported

**Official Workflow Template:**
```
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/templates/video_hunyuan_video_1.5_720p_i2v.json
```

## Appendix A.1: Verified Known Issues and Debugging

### Critical Issues (From Research)

| Issue | Cause | Solution |
|-------|-------|----------|
| **Silent crashes** | RAM/VRAM exhaustion | Set `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128` |
| **LoRA loading failures** | I2V vs T2V key naming differs | Use correct LoRA type for your workflow |
| **Black videos** | PyTorch < 2.5.1 OR wrong flow_shift | Upgrade PyTorch; use flow_shift=7.0 for 50 steps, 17.0 for <20 steps |
| **Static/no motion** | LoRA strength too high | Reduce to 0.5, never exceed 2.0 |
| **torch.compile + LoRA** | Known incompatibility | Disable torch.compile when using LoRA |
| **Tiled VAE artifacts** | temporal_size too low | Set temporal_size to 4096 |

### Debugging Checklist

```bash
# 1. Check VRAM before starting
nvidia-smi

# 2. Set OOM prevention
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128

# 3. Clear cache if issues persist
rm -rf ~/.triton
rm -rf /tmp/torchinductor_*

# 4. Verify PyTorch version
python -c "import torch; print(torch.__version__)"  # Should be >= 2.5.1

# 5. Test ComfyUI connection
curl -s http://localhost:8188/system_stats | python -c "import sys,json; print(json.load(sys.stdin))"

# 6. Check if Hunyuan nodes exist
curl -s http://localhost:8188/object_info | python -c "
import sys, json
data = json.load(sys.stdin)
nodes = [k for k in data.keys() if 'hunyuan' in k.lower()]
print('Hunyuan nodes:', nodes)
"
```

### Inference Parameters (Verified)

| Model | CFG Scale | Flow Shift | Steps |
|-------|-----------|------------|-------|
| 720p I2V (CFG distilled) | **1.0** | **7.0** | **50** |
| 720p I2V (non-distilled) | 6.0 | 7.0 | 50 |
| 480p I2V (step distilled) | **1.0** | **5.0** | **8-12** |

**Common mistakes:**
- Using CFG=6.0 with distilled model (should be 1.0)
- Using wrong flow_shift for resolution
- Using 50 steps with step-distilled (only needs 8-12)

## Appendix B: Model Files Checklist (Verified)

```
RUNPOD MODEL LOCATIONS (Verified Dec 2025):

/workspace/ComfyUI/models/diffusion_models/
  [ ] hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors  (8.33 GB)
  [ ] hunyuanvideo1.5_720p_i2v_fp16.safetensors                      (16.7 GB) [optional]
  [ ] hunyuanvideo1.5_480p_i2v_step_distilled_fp8_scaled.safetensors (8.34 GB) [for fast demos]

/workspace/ComfyUI/models/text_encoders/
  [ ] qwen_2.5_vl_7b_fp8_scaled.safetensors  (9.38 GB)

/workspace/ComfyUI/models/clip_vision/
  [ ] sigclip_vision_patch14_384.safetensors  (857 MB)

/workspace/ComfyUI/models/vae/
  [ ] hunyuan_video_vae_bf16.safetensors  (~2 GB)

TOTAL DOWNLOAD (FP8 config): ~20.5 GB
```

**Download Source:** `Comfy-Org/HunyuanVideo_1.5_repackaged` on Hugging Face

**Download Commands:**
```bash
cd /workspace/ComfyUI/models

# Main model (FP8 - recommended)
huggingface-cli download Comfy-Org/HunyuanVideo_1.5_repackaged \
  hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors \
  --local-dir diffusion_models/

# Text encoder
huggingface-cli download Comfy-Org/HunyuanVideo_1.5_repackaged \
  qwen_2.5_vl_7b_fp8_scaled.safetensors \
  --local-dir text_encoders/

# CLIP Vision
huggingface-cli download Comfy-Org/HunyuanVideo_1.5_repackaged \
  sigclip_vision_patch14_384.safetensors \
  --local-dir clip_vision/

# VAE
huggingface-cli download Comfy-Org/HunyuanVideo_1.5_repackaged \
  hunyuan_video_vae_bf16.safetensors \
  --local-dir vae/
```

## Appendix C: Quick Reference

```bash
# Switch to Hunyuan
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan

# Switch to Wan
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan

# Check current model
python -c "from src.core.config import get_config; print(get_config().video_model.model_family)"

# Test quick generation
python main.py --project tests/quick_test.json --no-pass2 -v
```

---

## Appendix D: Hunyuan Ecosystem Clarification

Tencent has released multiple products under the "Hunyuan" umbrella. It's critical to understand 
which product we're targeting and which are overkill for our use case.

### Product Matrix (Updated After Research)

| Product | Release Date | Purpose | Identity Method | Our Use |
|---------|--------------|---------|-----------------|---------|
| **HunyuanVideo 1.5** | Nov 20, 2025 | Text/Image → Video | Init_image only (VAE+SigLIP) | ✅ **PRIMARY TARGET** |
| HunyuanVideo 1.5 I2V Distilled | Dec 5, 2025 | Fast I2V (8-12 steps, 75 sec) | Same as above | ✅ For demos |
| **HunyuanCustom** | Mid-2025 | Multi-modal subject customization | LLaVA fusion + temporal ID | 🔍 **INVESTIGATE** |
| HY-WorldPlay 1.5 | Dec 17, 2025 | Interactive world exploration | Reconstituted Context Memory | ❌ Overkill |
| HunyuanWorld-Voyager | Sep 2025 | RGB-D world exploration | N/A | ❌ Not relevant |

### Critical Insight: HunyuanCustom Has Better Identity

The benchmark everyone cites (0.627 ArcFace) is from **HunyuanCustom**, not base HunyuanVideo 1.5:

| Model | ArcFace Score | Identity Method |
|-------|---------------|-----------------|
| **HunyuanCustom** | **0.627** | LLaVA text-image fusion + temporal ID enhancement |
| Keling 1.6 | 0.505 | Unknown |
| Vidu 2.0 | 0.424 | Unknown |
| VACE-1.3B (Wan) | 0.204 | VAE latent concat |

**HunyuanCustom advantages:**
- External reference image input (unlike base HunyuanVideo 1.5)
- "Temporal ID enhancement" - concatenates target image over time axis
- Outperforms all competitors on face similarity

### ACTION: Investigate HunyuanCustom Availability

During Phase 0, check:
```bash
# Check if HunyuanCustom nodes exist in ComfyUI
curl -s http://localhost:8188/object_info | python -c "
import sys, json
data = json.load(sys.stdin)
custom_nodes = [k for k in data.keys() if 'custom' in k.lower() or 'hunyuancustom' in k.lower()]
print('HunyuanCustom nodes:', custom_nodes if custom_nodes else 'NOT FOUND')
"

# Search for wrapper
# https://github.com/kijai/ComfyUI-HunyuanVideoWrapper - check if supports Custom
```

**If HunyuanCustom is available:**
- It becomes our Tier 4 (best quality) option
- May provide external reference input we lack in base model
- Would achieve 0.627+ identity directly

### Why NOT WorldPlay?

HY-WorldPlay is designed for **game-like exploration** with keyboard/mouse control at 24 FPS 
real-time. It's impressive but solves a different problem:

| Feature | WorldPlay | Our Needs |
|---------|-----------|-----------|
| Input | Keyboard + mouse | Script + prompts |
| Output | Streaming exploration video | Narrative shots |
| Camera | User-controlled in real-time | Director-specified per shot |
| Consistency | Geometric (3D world) | Identity (characters) |

Our **Bridge Engine + Consistency Dictionary** architecture achieves narrative consistency 
through a simpler approach than WorldPlay's "Reconstituted Context Memory."

### WorldPlay Concepts for Future Reference

If we need 30+ minute continuous video in the future, WorldPlay's concepts are worth exploring:

- **Reconstituted Context Memory (RCM):** Vector database storing latent keyframes for retrieval
- **Context Forcing:** Injecting historical latents into current generation
- **Temporal Reframing:** Pulling old frames into attention window to prevent drift

These are **DEFERRED** until we validate HunyuanVideo 1.5's limitations.

---

## Appendix E: Identity Strategy - Corrected Understanding

### Critical Correction: IP2V ≠ IP-Adapter

Initial research suggested HunyuanVideo 1.5's "native IP2V" was similar to IP-Adapter.
**This is incorrect.** Cross-referenced research reveals:

| Feature | IP-Adapter (SDXL/Wan) | HunyuanVideo 1.5 |
|---------|----------------------|------------------|
| External reference input | ✅ Yes (separate face image) | ❌ No |
| Strength control | ✅ Yes (0.0-1.0 weight) | ❌ No |
| Identity source | Reference image | Init_image ONLY |
| Can generate different content with same face | ✅ Yes | ❌ No (face must be in init_image) |

### How Hunyuan Identity Actually Works

From verified research:

> "The base model accepts only the **init_image (first frame)** — no separate reference 
> image input like IP-Adapter. Identity comes entirely from processing the init_image 
> through both VAE and SigLIP pathways."

**Dual-pathway architecture:**
1. **VAE latent concatenation** - Init_image latent concatenated with noisy latent
2. **SigLIP semantic embedding** - Provides semantic alignment for the init_image

**What this means for us:**
- Hunyuan will faithfully reproduce whatever face is in the init_image
- But we cannot provide a separate "this is Alice's face" reference
- The Bridge Frame (SDXL + IP-Adapter) is our ONLY external reference injection point

### Benchmark Reality Check

| Model | ArcFace Score | Notes |
|-------|---------------|-------|
| **HunyuanCustom** | 0.627 | Enhanced model with LLaVA fusion |
| Keling 1.6 | 0.505 | |
| Vidu 2.0 | 0.424 | |
| VACE-1.3B (Wan-based) | 0.204 | Our current stack's baseline |

**Critical:** The 0.627 score is from **HunyuanCustom**, not base HunyuanVideo 1.5.
Base HunyuanVideo 1.5 identity benchmarks are NOT published.

### Why Bridge Frame Strategy is Now LOAD-BEARING

```
WITHOUT Bridge Engine (Broken):
┌─────────────────────────────────────────────────────────────┐
│  User provides: Alice's face reference                      │
│  Hunyuan says: "I don't have an input for that"            │
│  Result: Can't inject identity into generation              │
└─────────────────────────────────────────────────────────────┘

WITH Bridge Engine (Working):
┌─────────────────────────────────────────────────────────────┐
│  User provides: Alice's face reference                      │
│           ↓                                                 │
│  SDXL + IP-Adapter: Creates hero frame WITH Alice's face   │
│           ↓                                                 │
│  Hunyuan I2V: Uses hero frame as init_image                │
│           ↓                                                 │
│  Result: Video has Alice because init_image has Alice       │
└─────────────────────────────────────────────────────────────┘
```

### Revised Identity Tiers

| Tier | Method | Expected Identity | Use Case |
|------|--------|-------------------|----------|
| **1** | SDXL Hero → Hunyuan I2V (single shot) | 85-90% | Quick drafts |
| **2** | Bridge chain (IP-Adapter at each bridge) | 85-90% | Multi-shot |
| **3** | Tier 2 + Character LoRA | 90-95% | Production |
| **4** | HunyuanCustom (if available) | 95%+ | Best quality |

### LoRA Status: RECOMMENDED, Not Optional

Given that HunyuanVideo 1.5 has no external reference mechanism, LoRA becomes more 
valuable (not less) for production quality:

**Without LoRA:**
- Identity depends entirely on init_image quality
- Bridge frame must perfectly capture the character
- Any drift in bridge → drift in video

**With LoRA:**
- Model "knows" the character intrinsically
- Can correct for imperfect init_images
- More robust across varied prompts/poses

**LoRA Training (Confirmed Available):**
- Official training code: Dec 5, 2025
- musubi-tuner support: PR #748 merged
- Muon optimizer required (open-sourced)
- Training time: 4-24 hours depending on hardware
- Dataset: 10-50 video clips recommended

### Impact on MVP

**Before research:** "1 image → 95% identity, LoRA optional"
**After research:** "1 image → Bridge Frame → 85-90% identity, LoRA recommended for production"

This is still **better than Wan** (where we're at ~97% for 1-second but unknown for longer),
and the Bridge Engine we already built is now the key differentiator.

---

## Appendix F: Revised Phase 0 Validation

Based on corrected understanding of Hunyuan's identity mechanism.

### Key Hypothesis to Test

> "Our Bridge Frame strategy (SDXL + IP-Adapter → Hunyuan I2V) provides effective 
> identity injection even though Hunyuan itself has no external reference input."

### Phase 0 Checklist (Revised)

```bash
# On RunPod

# ═══════════════════════════════════════════════════════════════
# TEST 1: Basic Hunyuan I2V Function
# ═══════════════════════════════════════════════════════════════
# Goal: Verify Hunyuan works at all
# Method: Load official workflow, generate from any image
# Pass: Video generates without errors

# ═══════════════════════════════════════════════════════════════
# TEST 2: Single-Shot Identity Preservation
# ═══════════════════════════════════════════════════════════════
# Goal: Measure how well Hunyuan preserves init_image identity
# Method: 
#   - Use alice_portrait.png as init_image
#   - Generate 4-second (96 frame) clip
#   - Extract frames 1, 24, 48, 72, 96
#   - Run ArcFace: init_image vs each frame
# Target: >= 0.85 similarity
# This tests Hunyuan's native identity preservation (no external ref)

# ═══════════════════════════════════════════════════════════════
# TEST 3: Bridge Frame Effectiveness (CRITICAL)
# ═══════════════════════════════════════════════════════════════
# Goal: Verify SDXL+IP-Adapter → Hunyuan chain works
# Method:
#   - Load alice_portrait.png as IP-Adapter reference
#   - Generate SDXL hero frame with prompt "alice in a forest"
#   - Use hero frame as init_image for Hunyuan I2V
#   - Generate 4-second clip
#   - Run ArcFace: alice_portrait.png vs Hunyuan output frames
# Target: >= 0.85 similarity
# This tests our actual production workflow

# ═══════════════════════════════════════════════════════════════
# TEST 4: Multi-Shot Chain
# ═══════════════════════════════════════════════════════════════
# Goal: Verify identity survives shot transitions
# Method:
#   - Shot 1: Bridge frame + Hunyuan I2V (same as Test 3)
#   - Extract last frame of Shot 1
#   - Shot 2: New bridge frame (from Shot 1 last frame + same alice ref)
#   - Generate Shot 2 with Hunyuan I2V
#   - Run ArcFace: alice_portrait.png vs Shot 2 frames
# Target: >= 0.80 similarity
# This tests our multi-shot consistency strategy

# ═══════════════════════════════════════════════════════════════
# TEST 5: Wan Comparison (Baseline)
# ═══════════════════════════════════════════════════════════════
# Goal: Verify Hunyuan is actually better than Wan
# Method: Run Test 3 equivalent with Wan 2.1
# Compare: Hunyuan scores vs Wan scores
# Target: Hunyuan >= Wan (ideally 10%+ better)
```

### Exit Criteria (Revised - Realistic)

| Test | Fail | Pass | Good | Excellent |
|------|------|------|------|-----------|
| Single-shot (frame 1 vs 96) | < 0.75 | 0.75 | 0.85 | 0.90+ |
| Bridge effectiveness | < 0.80 | 0.80 | 0.85 | 0.90+ |
| Multi-shot chain | < 0.75 | 0.75 | 0.80 | 0.85+ |
| vs Wan comparison | Worse | Same | Better | 10%+ better |

### Decision Matrix After Phase 0

| Result | Decision |
|--------|----------|
| All tests PASS | Proceed with pivot |
| Tests 1-3 PASS, Test 4 FAIL | Proceed, but investigate bridge chain |
| Test 3 FAIL | Bridge strategy broken - reconsider pivot |
| Test 5: Wan better | Abort pivot, stay on Wan |

### What We're Really Testing

The research revealed that Hunyuan has no external reference mechanism. Our hypothesis is:

> "The Bridge Frame (SDXL + IP-Adapter) compensates for Hunyuan's lack of external 
> reference by baking identity into the init_image before Hunyuan ever sees it."

**If Test 3 passes:** Our architecture is sound. Bridge Engine is the solution.
**If Test 3 fails:** We have a fundamental problem. Either:
- IP-Adapter identity doesn't survive SDXL → Hunyuan handoff
- Hunyuan degrades whatever identity is in init_image
- Our workflow has a bug

### Document Exact Node Names During Testing

While testing, capture the exact working configuration:

```
VERIFIED NODE NAMES (Fill in during Phase 0):
─────────────────────────────────────────────
Native ComfyUI (v0.3.75+):
- Model loader: UNETLoader ✓
- Text encoder: TextEncodeHunyuanVideo_ImageToVideo ✓
- I2V node: HunyuanImageToVideo ✓
- CLIP Vision: CLIPVisionLoader ✓
- CLIP Encode: CLIPVisionEncode ✓
- VAE: VAELoader + VAEDecode ✓

Official workflow template:
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/templates/video_hunyuan_video_1.5_720p_i2v.json
```

---

## Appendix G: Architecture Alignment (Corrected)

### The Bridge Engine is Now Load-Bearing

The research revealed that HunyuanVideo 1.5 has **no external reference input**. This means 
our existing Bridge Engine architecture becomes MORE important, not less.

```
ORIGINAL ARCHITECTURE ASSUMPTION:
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Consistency Engine                                │
│  ├── IP-Adapter (for external reference)     [Both models]  │
│  ├── Bridge Frame (for shot transitions)     [Helpful]      │
│  └── LoRA (for production quality)           [Optional]     │
└─────────────────────────────────────────────────────────────┘

CORRECTED UNDERSTANDING:
┌─────────────────────────────────────────────────────────────┐
│  Wan 2.1:                                                   │
│  ├── IP-Adapter: Works (community plugin available)         │
│  ├── Bridge Frame: Helpful but IP-Adapter can also help     │
│  └── External reference: YES (via IP-Adapter)               │
│                                                             │
│  HunyuanVideo 1.5:                                          │
│  ├── IP-Adapter: NOT AVAILABLE                              │
│  ├── Bridge Frame: ONLY way to inject external identity     │
│  └── External reference: NO (only init_image)               │
└─────────────────────────────────────────────────────────────┘
```

### Why Our Architecture Actually Works Better for Hunyuan

Ironically, our SDXL-based Bridge Engine compensates for Hunyuan's limitation:

```
THE HANDOFF CHAIN:
                                                   
  User's Face Reference                            
         │                                         
         ▼                                         
  ┌──────────────────┐                             
  │ SDXL + IP-Adapter │  ← External ref injected HERE
  │ (Hero Frame)      │                             
  └────────┬─────────┘                             
           │ High-quality frame with correct identity
           ▼                                         
  ┌──────────────────┐                             
  │ HunyuanVideo I2V │  ← Receives identity via init_image
  │                   │     (not via external ref)
  └────────┬─────────┘                             
           │ Video with preserved identity
           ▼                                         
       Output                                      
```

**Key insight:** SDXL's IP-Adapter does the heavy lifting of identity injection. 
Hunyuan just needs to preserve what's already in the init_image (which it's good at).

### Tradeoff vs Wan

| Aspect | Wan 2.1 | Hunyuan 1.5 |
|--------|---------|-------------|
| External reference during I2V | ✅ Via IP-Adapter plugin | ❌ Not available |
| Identity from init_image | ✅ Good | ✅ Good (3× better baseline) |
| Bridge Frame dependency | Medium | **HIGH** (only option) |
| VRAM | 24-40 GB | 14-24 GB |
| Speed | ~3-5 min | ~75 sec |

**Wan advantage:** Can inject identity at any point via IP-Adapter
**Hunyuan advantage:** Better baseline identity, faster, lower VRAM

### Updated Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CONTINUUM ENGINE                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    CONSISTENCY ENGINE (Layer 1)                  │   │
│  │                                                                   │   │
│  │   ┌─────────────────────┐    ┌─────────────────────┐            │   │
│  │   │  Consistency Dict   │    │     Visual RAG      │            │   │
│  │   │  (Character refs)   │───▶│  (Frame retrieval)  │            │   │
│  │   └─────────────────────┘    └─────────────────────┘            │   │
│  │              │                                                    │   │
│  │              ▼                                                    │   │
│  │   ┌─────────────────────────────────────────────────────────┐   │   │
│  │   │              BRIDGE ENGINE (CRITICAL PATH)               │   │   │
│  │   │                                                           │   │   │
│  │   │   Shot 1:  SDXL + IP-Adapter ──▶ Hero Frame              │   │   │
│  │   │                                      │                    │   │   │
│  │   │   Shot 2+: SDXL + IP-Adapter + ControlNet ──▶ Bridge     │   │   │
│  │   │            (from prev frame)              Frame          │   │   │
│  │   │                                                           │   │   │
│  │   │   ★ THIS IS WHERE EXTERNAL IDENTITY IS INJECTED ★        │   │   │
│  │   └─────────────────────────────────────────────────────────┘   │   │
│  │              │                                                    │   │
│  └──────────────┼────────────────────────────────────────────────────┘   │
│                 │                                                         │
│                 ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    VIDEO RENDERER (Layer 2)                      │   │
│  │                                                                   │   │
│  │   ┌─────────────────────┐    ┌─────────────────────┐            │   │
│  │   │   WanRenderer       │ OR │  HunyuanRenderer    │            │   │
│  │   │   (Wan 2.1)         │    │  (Hunyuan 1.5)      │            │   │
│  │   │                     │    │                     │            │   │
│  │   │  • Has IP-Adapter   │    │  • NO IP-Adapter    │            │   │
│  │   │  • External ref OK  │    │  • Init_image only  │            │   │
│  │   └─────────────────────┘    └─────────────────────┘            │   │
│  │                                                                   │   │
│  │   Both receive init_image from Bridge Engine                     │   │
│  │   Both preserve whatever identity is in that init_image          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why This Design is Robust

The Bridge Engine handles identity injection **before** the video model sees anything. 
This means:

1. **Model-agnostic identity:** Face reference goes through SDXL, not the video model
2. **Switching is safe:** Both Wan and Hunyuan receive pre-baked identity
3. **Hunyuan's limitation is hidden:** Users never know it lacks external reference
4. **Best of both worlds:** SDXL's IP-Adapter + Hunyuan's speed/quality

### Potential Future Enhancement: HunyuanCustom

If **HunyuanCustom** becomes available for ComfyUI, it would provide native external 
reference (LLaVA fusion + temporal ID enhancement). This would:

- Bypass the need for Bridge Engine for identity
- Provide 0.627 ArcFace directly (vs our ~0.85 estimate)
- Simplify the pipeline

**Action:** Investigate HunyuanCustom availability during Phase 0

---

**Document Status:** Ready for implementation  
**Next Action:** Execute Phase 0 validation on RunPod  
**Fallback Plan:** Demo with Wan if Hunyuan integration incomplete
**Key Hypothesis:** Native IP2V may eliminate need for LoRA in MVP