# MODEL PIVOT DOCUMENT: Wan 2.1 → HunyuanCustom

**Version:** 2.0.0  
**Created:** December 26, 2025  
**Updated:** December 26, 2025 (Post-Research Validation)  
**Status:** VALIDATED - Ready for Phase 0 Testing  
**Timeline:** 10-12 days to investor demo  
**Research Sources:** Claude Research, ChatGPT Deep Research, Community Feedback

---

## Executive Summary

This document provides the complete roadmap for pivoting from Wan 2.1 to **HunyuanCustom** 
as the primary video generation model, while preserving the ability to switch back to Wan.

### Critical Research Correction

**Original target (INCORRECT):** HunyuanVideo 1.5  
**Validated target (CORRECT):** HunyuanCustom

| Aspect | HunyuanVideo 1.5 | HunyuanCustom |
|--------|------------------|---------------|
| Release | Nov 2025 (newer) | May 2025 (older) |
| Base Architecture | 8.3B params | 13B params |
| Purpose | Speed + environments | **Identity preservation** |
| External face reference | ❌ NO | ✅ **YES (LLaVA fusion)** |
| Identity benchmark | Unknown (~0.2-0.6?) | **0.627 ArcFace** |
| Community feedback | "Faces morph weirdly" | "State-of-the-art identity" |
| Audio-driven lip sync | ❌ No | ✅ Yes (CLI only) |
| VRAM | 14-24 GB | 60-80 GB |
| ComfyUI | Native | Kijai wrapper |

**HunyuanVideo 1.5 is optimized for speed and environments, NOT identity preservation.**
Community consensus: "For character-focused work, Wan 2.2 remains better than HunyuanVideo 1.5."

### Why Pivot to HunyuanCustom

| Metric | HunyuanCustom | Wan 2.1 (VACE) | Improvement |
|--------|---------------|----------------|-------------|
| ArcFace Score | **0.627** | 0.204 | **3× better** |
| External face reference | ✅ Native | ❌ Requires IP-Adapter | Simpler |
| Multi-subject | ✅ 2 characters | ❌ No | New capability |
| Bridge Engine needed | **Optional** | Required | Simpler |

### Identity Preservation Benchmarks (Official)

From HunyuanCustom paper (arXiv:2505.04512):

| Model | Face-Sim (ArcFace) | Source |
|-------|-------------------|--------|
| **HunyuanCustom** | **0.627** | Open source |
| Hailuo | 0.526 | Closed |
| Kling 1.6 | 0.505 | Closed |
| Vidu 2.0 | 0.424 | Closed |
| SkyReels-A2 (Wan 2.1) | 0.402 | Open source |
| Pika | 0.363 | Closed |
| **VACE (Wan 2.1)** | **0.204** | Open source |

**HunyuanCustom is #1 in identity preservation among ALL tested models.**

### Design Constraint

Switching between models must be a single config change:
```bash
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom  # or "wan"
```

---

## Table of Contents

1. [Current System Analysis](#1-current-system-analysis)
2. [Target Architecture](#2-target-architecture)
3. [GPU Strategy](#3-gpu-strategy)
4. [File Inventory & Classification](#4-file-inventory--classification)
5. [Implementation Phases](#5-implementation-phases)
6. [Testing Protocol](#6-testing-protocol)
7. [Debugging Guide](#7-debugging-guide)
8. [Rollback Procedure](#8-rollback-procedure)
9. [Risk Matrix](#9-risk-matrix)
10. [Day-by-Day Schedule](#10-day-by-day-schedule)

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
│   Issue:  Need to add HunyuanCustom entries                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Coupling Points (Files That Need Changes)

| File | Current State | Required Change | Risk Level |
|------|---------------|-----------------|------------|
| `config.py` | No video model selector | Add `video_model` config section | LOW |
| `main.py` | Hardcodes `WanRenderer` | Use renderer factory | LOW |
| `wan_renderer.py` | Wan-specific implementation | Keep as-is, create sibling | NONE |
| `workflow_loader.py` | Flat directory lookup | Add model-family subdirectory support | MEDIUM |
| `bridge_engine.py` | Uses SDXL workflows | **May become optional** for HunyuanCustom | LOW |
| `pass1_generator.py` | Uses passed renderer | No change needed | NONE |
| `models.json` | Has wan21 entries | Add hunyuan_custom entries | LOW |
| `base.py` | Has RendererType enum | Add factory function | LOW |

### 1.3 Workflow Classification

**VIDEO MODEL-SPECIFIC (Must be duplicated for HunyuanCustom):**
```
pass1_img2vid.json           # I2V generation
pass1_img2vid_lora.json      # I2V with LoRA
pass1_structural.json        # T2V generation  
pass1_structural_lora.json   # T2V with LoRA
refine_vid2vid_simple.json   # Vid2Vid refinement
refine_vid2vid_temporal.json # Temporal refinement
```

**SHARED SDXL WORKFLOWS (Model-agnostic, may become optional):**
```
hero_frame.json              # SDXL + IP-Adapter for Shot 1
bridge_full.json             # SDXL + ControlNet + IP-Adapter
bridge_pose_only.json        # SDXL + ControlNet
bridge_ipadapter.json        # SDXL + IP-Adapter only
bridge_basic.json            # SDXL basic
bridge_pose_extract.json     # ControlNet preprocessor
bridge_depth_extract.json    # Depth extraction
```

**Note:** With HunyuanCustom's native identity, Bridge Engine becomes **optional** - 
we'll test whether it's still needed during Phase 0.

**UTILITY WORKFLOWS (Model-agnostic):**
```
rife_interpolation.json      # Frame interpolation
musetalk_lipsync.json        # Lip sync (STILL NEEDED - audio-driven not in ComfyUI)
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

### 2.1 Pipeline Comparison

**Current Pipeline (Wan 2.1):**
```
Face Ref → SDXL+IP-Adapter (Hero Frame) → Wan 2.1 I2V → MuseTalk → Output
           ↑                              ↑              ↑
     Identity injection          Identity preservation  Lip sync
     (external workaround)       (limited ~0.204)       (works)
```

**New Pipeline (HunyuanCustom):**
```
Face Ref + Prompt → HunyuanCustom → MuseTalk → Output
                    ↑                ↑
              Identity injection     Lip sync
              + Video generation     (still needed)
              (native 0.627)
```

### 2.2 Key Architectural Difference

| Aspect | Wan 2.1 Pipeline | HunyuanCustom Pipeline |
|--------|------------------|------------------------|
| Identity injection | External (SDXL + IP-Adapter) | **Native (LLaVA fusion)** |
| Steps for one shot | 3 (Hero → I2V → Lip sync) | 2 (Custom → Lip sync) |
| Bridge Engine needed? | Yes (for multi-shot) | **Test needed** (may be optional) |
| Identity preservation | Compound loss (~81-90%) | **Direct (~95%+)** |
| `<image>` token | No | Yes - "A portrait of `<image>` walking" |

### 2.3 Directory Structure

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
├── hunyuan_custom/                   # HunyuanCustom specific (NEW)
│   ├── pass1_img2vid.json            # SAME NAMES, different nodes
│   ├── pass1_img2vid_lora.json
│   ├── pass1_t2v.json
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

### 2.4 Config-Driven Model Selection

```python
# .env or environment
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom
CONTINUUM_VIDEO_MODEL__MODEL_TIER=dev

# Results in:
config.video_model.model_family  # "hunyuan_custom"
config.video_model.model_tier    # "dev"
```

### 2.5 Renderer Factory Pattern

```python
# base.py - NEW FUNCTION
def get_renderer_for_config(config: Optional[Config] = None) -> BaseRenderer:
    """Single source of truth for renderer instantiation."""
    config = config or get_config()
    family = config.video_model.model_family
    
    if family == "wan":
        from .wan_renderer import WanRenderer
        return WanRenderer()
    elif family == "hunyuan_custom":
        from .hunyuan_custom_renderer import HunyuanCustomRenderer
        return HunyuanCustomRenderer()
    else:
        raise ValueError(f"Unknown model family: {family}")
```

---

## 3. GPU Strategy

### 3.1 Recommended: 4x RTX 4090 on RunPod

| Spec | Value |
|------|-------|
| Total VRAM | **96 GB (4 × 24GB distributed)** |
| Price | **$2.00/hr** |
| Availability | High |
| RAM | 164 GB |
| ComfyUI Compatible | ✅ Yes (with MultiGPU extension) |

### 3.2 Why 4x RTX 4090 Over Single H100

| Option | VRAM | Price/hr | Notes |
|--------|------|----------|-------|
| **4x RTX 4090** | 96GB (distributed) | **$2.00** | Best value, requires MultiGPU extension |
| H100 PCIe | 80GB (single) | $2.39 | Simpler setup |
| H100 SXM | 80GB (single) | $2.69 | Fastest single GPU |
| H100 NVL | 94GB (single) | $3.07 | Overkill |
| RTX 4090 (Wan) | 24GB (single) | $0.74 | Our current setup |

**4x RTX 4090 provides more total VRAM at lower cost than H100.**

### 3.3 Multi-GPU Performance

From community testing:
> "Every additional GPU knocks down the render time by 50%"

| Config | Relative Speed |
|--------|----------------|
| 1x GPU | 1× (baseline) |
| 2x GPU | ~2× faster |
| 4x GPU | ~4× faster |

### 3.4 Required ComfyUI Extensions

```bash
# 1. Kijai's HunyuanVideo Wrapper (includes HunyuanCustom)
cd ComfyUI/custom_nodes
git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper

# 2. Multi-GPU Support (REQUIRED for 4x RTX 4090)
git clone https://github.com/pollockjj/ComfyUI-MultiGPU

# 3. KJNodes (dependency)
git clone https://github.com/kijai/ComfyUI-KJNodes

# 4. Video Helper Suite
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
```

### 3.5 Multi-GPU Node Mapping

| Standard Node | Multi-GPU Version |
|---------------|-------------------|
| `HyVideoModelLoader` | `HyVideoModelLoaderDiffSynthMultiGPU` |
| Device selection | New dropdown in loader nodes |

---

## 4. File Inventory & Classification

### 4.1 Files to MODIFY

| File | Change Type | Description |
|------|-------------|-------------|
| `config.py` | ADD | New `VideoModelConfig` class |
| `main.py` | MODIFY | Replace hardcoded WanRenderer with factory |
| `workflow_loader.py` | MODIFY | Add model-family directory support |
| `base.py` | ADD | New `get_renderer_for_config()` function |
| `models.json` | ADD | HunyuanCustom model entries |

### 4.2 Files to CREATE

| File | Purpose |
|------|---------|
| `hunyuan_custom_renderer.py` | HunyuanCustom renderer implementation |
| `workflows/hunyuan_custom/pass1_img2vid.json` | HunyuanCustom I2V workflow |
| `workflows/hunyuan_custom/pass1_img2vid_lora.json` | HunyuanCustom I2V + LoRA workflow |
| `workflows/hunyuan_custom/pass1_t2v.json` | HunyuanCustom T2V workflow |

### 4.3 Files to MOVE (Not Modify)

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

### 4.4 Files to LEAVE ALONE

| File | Reason |
|------|--------|
| `wan_renderer.py` | Keep working, sibling to new hunyuan_custom_renderer.py |
| `bridge_engine.py` | Uses SDXL workflows, may become optional |
| `pass1_generator.py` | Uses renderer interface, model-agnostic |
| `identity_checker.py` | Works on output frames, model-agnostic |
| `physics_checker.py` | Works on output frames, model-agnostic |
| All audio modules | Completely independent of video model |

---

## 5. Implementation Phases

### Phase 0: Pre-Flight Validation (Day 1-2)

**CRITICAL: Do NOT write any integration code until this passes.**

#### Test Environment Setup

```bash
# On RunPod - 4x RTX 4090

# Step 1: Verify GPU setup
python -c "
import torch
print(f'GPUs available: {torch.cuda.device_count()}')
for i in range(torch.cuda.device_count()):
    print(f'  GPU {i}: {torch.cuda.get_device_name(i)}')
    print(f'    Memory: {torch.cuda.get_device_properties(i).total_memory / 1e9:.1f} GB')
"
# Expected: 4 GPUs, each 24GB

# Step 2: Install ComfyUI + extensions
cd /workspace
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
python -m venv venv
source venv/bin/activate
pip install torch==2.5.1+cu124 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

cd custom_nodes
git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper
git clone https://github.com/pollockjj/ComfyUI-MultiGPU
git clone https://github.com/kijai/ComfyUI-KJNodes
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite

pip install sageattention

# Step 3: Download HunyuanCustom models
cd /workspace/ComfyUI/models

# Main model (FP8 - recommended)
mkdir -p diffusion_models
huggingface-cli download Kijai/HunyuanVideo_comfy \
  hunyuan_video_custom_720p_fp8_scaled.safetensors \
  --local-dir diffusion_models/

# VAE
mkdir -p vae
huggingface-cli download tencent/HunyuanVideo \
  hunyuan-video-t2v-720p/vae/pytorch_model.pt \
  --local-dir vae/

# LLaVA (auto-downloads on first use, or manually)
# ~16 GB for llava-llama-3-8b-v1_1

# CLIP Vision
mkdir -p clip_vision
huggingface-cli download openai/clip-vit-large-patch14 \
  --local-dir clip_vision/

# Step 4: Start ComfyUI
cd /workspace/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

#### Test Sequence

**Test 1: Basic Function**
```
Goal: Verify HunyuanCustom runs on 4x RTX 4090 with MultiGPU
Input: Any face image + simple prompt
Output: Video generates without errors
Pass Criteria: Video output exists, no OOM
```

**Test 2: Identity Preservation (Single Shot)**
```
Goal: Measure ArcFace score for single 5-second clip
Input: Face reference + prompt "Person walking in park"
Method:
  - Use HyVideoTextImageEncode with <image> token
  - Use HyVideoModelLoaderDiffSynthMultiGPU for distribution
  - Generate 129 frames (5 sec @ 25fps)
Output: 5-second video
Measure: ArcFace similarity between reference and each frame
Target: ≥ 0.60 (matching published benchmark)
```

**Test 3: Multi-Shot Identity (CRITICAL)**
```
Goal: Test if identity holds across SEPARATE generations
Shot 1: Face ref + "Person in cafe"
Shot 2: Face ref + "Person on street" (same face ref, new prompt)
Shot 3: Face ref + "Person in office" (same face ref, new prompt)

Measure: ArcFace similarity across all shots
Target: ≥ 0.55 average (allowing some per-shot variance)
```

**Test 4: Bridge Engine Comparison**
```
Goal: Determine if Bridge Engine is still needed
Method A: HunyuanCustom only (same face ref each shot)
Method B: HunyuanCustom + Bridge Engine (last frame → next first frame)

Compare: Which has better identity consistency?
Decision: If A ≥ B, Bridge Engine becomes optional
```

**Test 5: vs Wan Baseline**
```
Goal: Confirm HunyuanCustom beats your 97% Wan score
Method: Same test conditions as your original Wan test
  - 1 second duration
  - Low resolution
  - Init frames method

Compare: HunyuanCustom vs Wan 2.1
Target: HunyuanCustom ≥ Wan
```

#### Exit Criteria

| Test | Fail | Pass | Good | Excellent |
|------|------|------|------|-----------|
| Basic function | Crashes | Runs | Fast | Very fast |
| Single-shot identity | < 0.50 | ≥ 0.55 | ≥ 0.60 | ≥ 0.65 |
| Multi-shot identity | < 0.45 | ≥ 0.50 | ≥ 0.55 | ≥ 0.60 |
| Bridge comparison | A << B | A ≈ B | A > B | A >> B |
| vs Wan baseline | Worse | Same | Better | Much better |

#### Decision Matrix

| Result | Decision |
|--------|----------|
| All tests PASS | ✅ Proceed with HunyuanCustom pivot |
| Tests 1-3 PASS, Test 4 shows Bridge helps | Proceed, keep Bridge Engine |
| Test 5 FAIL (Wan better) | ⚠️ Reconsider pivot, stay with Wan |
| Test 1 FAIL (won't run on 4x4090) | Try H100 80GB single GPU |
| Test 2 FAIL (identity bad) | ❌ Abort pivot |

### Phase 1: Infrastructure (Days 3-4)

## 5. Implementation Phases

### Implementation Philosophy

**DO NOT** write all code upfront. Each step should be executed as follows:

1. **PRE-FLIGHT CHECK** — Read the actual source file(s) from the project and verify the guidance assumptions are correct
2. **FLAG MISMATCHES** — If the file structure doesn't match what the guide assumes, stop and reconcile before proceeding
3. **Generate/update** ONE file at a time
4. **Test** using the validation command provided
5. **Proceed** only after validation passes

This prevents compounding errors and catches stale/incorrect guidance.

### Pre-Flight Check Template

Before each step, Claude should:

```
PRE-FLIGHT CHECK for Step X.Y:
1. Read: [file path from project files]
2. Verify: [specific assumption from guide]
   - Expected: [what guide assumes]
   - Actual: [what file actually shows]
3. Status: MATCH / MISMATCH
4. If MISMATCH: [describe discrepancy and propose resolution]
```

**If there's a mismatch, do NOT proceed with the guide blindly.** Surface the issue first.

---

### Phase 1: Infrastructure (Days 3-4)

Phase 1 prepares the codebase for multi-model support WITHOUT yet creating the HunyuanCustom renderer.

After Phase 1, the system should:
- Still work with Wan (backwards compatible)
- Have config support for model selection
- Have workflow loader that understands subdirectories
- Have model loader that handles HunyuanCustom's different schema

---

#### Step 1.1: Update Config

**File:** `src/core/config.py`

**Pre-Flight Check:**
```
1. Read: /mnt/project/config.py (or src/core/config.py in actual repo)
2. Verify these assumptions:
   - PostConfig class exists and ends around line 128
   - Config class has a 'paths' field (we add after it)
   - Pydantic v2 style is used (@field_validator, not @validator)
   - Literal type is already imported from typing
3. If any assumption is wrong, flag before proceeding
```

**What:** Add a new `VideoModelConfig` class and include it in the main `Config` class.

**Why:** We need a config-driven way to select which model family to use. Environment variable `CONTINUUM_VIDEO_MODEL__MODEL_FAMILY` should control this.

**Guidance:**
- Model the new class after existing ones like `SonicConfig` or `PostConfig`
- Fields needed: `model_family` (Literal["wan", "hunyuan_custom"]) and `model_tier` (Literal["dev", "standard", "beast"])
- Default `model_family` to `"wan"` for backwards compatibility during transition (can flip to `"hunyuan_custom"` later)
- Add a `@field_validator` for `model_family` to fail fast on invalid values

**Insert Location:** 
- New class: After `PostConfig` class definition
- New field in `Config`: After the `paths` field

**Validation:**
```bash
python -c "
from src.core.config import get_config
c = get_config()
print(f'model_family: {c.video_model.model_family}')
print(f'model_tier: {c.video_model.model_tier}')
"
# Expected: Should print the default values without error
```

---

#### Step 1.2: Reorganize Workflow Directory

**What:** Create subdirectory structure and move workflow files.

**Why:** Wan and HunyuanCustom use different ComfyUI nodes. Same logical workflow (e.g., "pass1_img2vid") needs different JSON per model family. Shared workflows (SDXL bridge, RIFE) work for both.

**Structure:**
```
workflows/
├── wan/                    # Wan-specific (pass1_*, refine_*)
├── hunyuan_custom/         # HunyuanCustom-specific (empty for now)
├── shared/                 # Model-agnostic (bridge_*, hero_frame, rife, musetalk)
└── models.json             # Stays in root
```

**Files to Move:**
- To `wan/`: All `pass1_*.json`, all `refine_*.json`
- To `shared/`: All `bridge_*.json`, `hero_frame.json`, `rife_interpolation.json`, `musetalk_lipsync.json`
- Keep in root: `models.json`

**Validation:**
```bash
ls workflows/wan/pass1_img2vid.json      # Should exist
ls workflows/shared/bridge_full.json      # Should exist
ls workflows/models.json                  # Should exist
```

---

#### Step 1.3: Update Workflow Loader

**File:** `src/comfy_client/workflow_loader.py`

**Pre-Flight Check:**
```
1. Read: /mnt/project/workflow_loader.py (or src/comfy_client/workflow_loader.py)
2. Verify these assumptions:
   - WorkflowLoader class exists
   - __init__ currently takes only workflows_dir parameter
   - _find_workflow_file method exists and returns Optional[Path]
   - Class uses self.workflows_dir to store the base path
   - There's a _template_cache dict
3. Check current _find_workflow_file logic to understand what we're replacing
4. If structure differs significantly, flag before proceeding
```

**What:** Modify `WorkflowLoader` to:
1. Accept optional `model_family` parameter in `__init__`
2. Search for workflows in priority order: model-specific → shared → legacy root

**Why:** Same workflow name should resolve to different files depending on active model family.

**Guidance:**
- Add `model_family: Optional[str] = None` parameter to `__init__`
- If `model_family` is None, try to read from config; if config fails, fall back to `None` (legacy mode)
- **CRITICAL:** Handle `model_family=None` gracefully — don't do `Path / None` (TypeError)
- Store `self.model_dir` (can be None) and `self.shared_dir`
- Update `_find_workflow_file()` to check: model_dir → shared_dir → root (legacy)
- Log a warning when using legacy root path (helps migration)

**Key Edge Case:**
```python
# WRONG - crashes if model_family is None:
self.model_dir = self.workflows_dir / model_family

# RIGHT - handle None:
self.model_dir = self.workflows_dir / model_family if model_family else None
```

**Validation:**
```bash
python -c "
from src.comfy_client.workflow_loader import WorkflowLoader

# Test Wan lookup
loader = WorkflowLoader(model_family='wan')
t = loader.load('pass1_img2vid')
print(f'Wan workflow: {t.source_path}')

# Test shared lookup (bridge should be found via shared/)
t2 = loader.load('bridge_full')
print(f'Shared workflow: {t2.source_path}')

# Test legacy fallback (None model_family)
loader_legacy = WorkflowLoader(model_family=None)
print(f'Legacy mode works: {loader_legacy.model_dir}')
"
```

---

#### Step 1.4: Update Model Loader

**File:** `src/core/model_loader.py`

**Pre-Flight Check:**
```
1. Read: /mnt/project/model_loader.py (or src/core/model_loader.py)
2. Verify these assumptions:
   - ModelConfig is a frozen dataclass
   - Current required fields: unet, vae, clip
   - Current optional fields: clip_vision, vram_required_gb, max_resolution
   - get_model_config() function exists and builds ModelConfig from JSON
   - Function uses tier_config["clip"] (not .get()) - this is what we need to fix
3. Check if there are convenience functions at end (get_wan21_t2v_config, etc.)
4. If ModelConfig already has llava field, the guide is stale - flag it
```

**What:** Extend `ModelConfig` dataclass to support HunyuanCustom's different schema.

**Why:** HunyuanCustom uses `llava` instead of `clip`, and has additional fields (`flow_shift`, `cfg_scale`, `steps`). Current `ModelConfig` requires `clip` and will crash on HunyuanCustom entries.

**Guidance:**
- Make `clip` field Optional (it's required for Wan, not for HunyuanCustom)
- Add new Optional fields: `llava`, `cfg_scale`, `flow_shift`, `steps`, `quality_tier`
- Update `get_model_config()` to use `.get()` for all optional fields
- Update `to_workflow_params()` to include new fields when present

**Key Change:**
```python
# BEFORE (crashes on HunyuanCustom):
clip=tier_config["clip"]

# AFTER (handles missing gracefully):
clip=tier_config.get("clip")
```

**Validation:**
```bash
python -c "
from src.core.model_loader import get_model_config, ModelTier

# Wan should still work
wan = get_model_config('wan21', 'i2v', ModelTier.DEV)
print(f'Wan clip: {wan.clip}')

# This will fail until Step 1.5 adds the JSON, but the loader should be ready
"
```

---

#### Step 1.5: Add HunyuanCustom to models.json

**File:** `workflows/models.json`

**Pre-Flight Check:**
```
1. Read: /mnt/project/models.json (or workflows/models.json)
2. Verify these assumptions:
   - File has wan21 section with t2v and i2v subsections
   - Each tier (dev/standard/beast) has: unet, vae, clip, clip_vision
   - There's a placeholder "hunyuan" section (not hunyuan_custom)
   - JSON structure uses nested objects: family -> type -> tier -> config
3. Check if hunyuan_custom already exists - if so, guide is stale
4. Identify exact location to insert (after wan21, before hunyuan)
```

**What:** Add `hunyuan_custom` section with i2v configurations for dev/standard/beast tiers.

**Why:** Model loader needs to know HunyuanCustom model paths and parameters.

**Guidance:**
- Add after `wan21` section, before `hunyuan` (the generic placeholder)
- Required fields: `unet`, `vae`, `llava`, `clip_vision`, `vram_required_gb`, `max_resolution`, `quality_tier`
- HunyuanCustom-specific: `cfg_scale` (7.5), `flow_shift` (13.0), `steps` (30)
- Note: HunyuanCustom does NOT have `clip` field (uses `llava` instead)

**Key Values:**
- Model file: `hunyuan_video_custom_720p_fp8_scaled.safetensors` (dev)
- VAE: `hunyuan_video_vae_bf16.safetensors`
- LLaVA: `llava-llama-3-8b-v1_1`
- VRAM: 80 GB

**Validation:**
```bash
python -c "
from src.core.model_loader import get_model_config, ModelTier

config = get_model_config('hunyuan_custom', 'i2v', ModelTier.DEV)
print(f'unet: {config.unet}')
print(f'llava: {config.llava}')
print(f'flow_shift: {config.flow_shift}')
assert config.llava is not None
assert config.flow_shift == 13.0
print('✓ HunyuanCustom model config works')
"
```

---

#### Step 1.6: Update Renderer Base

**File:** `src/renderers/base.py`

**Pre-Flight Check:**
```
1. Read: /mnt/project/base.py (or src/renderers/base.py)
2. Verify these assumptions:
   - RendererType enum exists with WAN, HUNYUAN, MOCHI, etc.
   - HUNYUAN_CUSTOM does NOT exist yet (if it does, skip enum addition)
   - get_renderer() function exists and uses _renderer_registry
   - list_renderers() function exists
   - @register_renderer decorator exists
3. Check import structure - we may need TYPE_CHECKING for Config import
4. Verify there's no existing get_renderer_for_config() function
```

**What:** 
1. Add `HUNYUAN_CUSTOM = "hunyuan_custom"` to `RendererType` enum
2. Add `get_renderer_for_config()` factory function

**Why:** 
1. The enum value is needed for `@register_renderer` decorator
2. Factory function is the single source of truth for "which renderer for this config"

**Guidance for Factory Function:**
- Accept optional `Config` parameter (import from `..core.config` inside function to avoid circular import)
- Read `config.video_model.model_family`
- Map family string to `RendererType` enum
- Call existing `get_renderer()` with the mapped type
- Raise clear error if family has no registered renderer

**Insert Location:**
- Enum addition: Add after `HUNYUAN = "hunyuan"` line
- Factory function: After `list_renderers()` at end of file

**Validation:**
```bash
python -c "
from src.renderers.base import RendererType, get_renderer_for_config

# Enum exists
print(f'HUNYUAN_CUSTOM = {RendererType.HUNYUAN_CUSTOM.value}')

# Factory function exists (will fail on call until renderer is registered)
print(f'Factory function: {get_renderer_for_config}')
"
```

---

#### Phase 1 Complete Validation

Run all these after completing Phase 1:

```bash
# 1. Config works
python -c "from src.core.config import get_config; print(get_config().video_model)"

# 2. Workflow loader finds Wan workflows
python -c "from src.comfy_client import WorkflowLoader; print(WorkflowLoader(model_family='wan').load('pass1_img2vid').name)"

# 3. Workflow loader finds shared workflows  
python -c "from src.comfy_client import WorkflowLoader; print(WorkflowLoader(model_family='wan').load('bridge_full').name)"

# 4. Model loader handles HunyuanCustom
python -c "from src.core.model_loader import get_model_config, ModelTier; c=get_model_config('hunyuan_custom','i2v',ModelTier.DEV); print(c.llava)"

# 5. RendererType enum has new value
python -c "from src.renderers.base import RendererType; print(RendererType.HUNYUAN_CUSTOM)"

# 6. Existing Wan pipeline still works (CRITICAL - no regression)
python main.py --project tests/quick_test.json --dry-run -v
```

---

### Phase 2: HunyuanCustom Renderer (Days 5-6)

Phase 2 creates the actual HunyuanCustom renderer implementation.

---

#### Step 2.1: Create HunyuanCustomRenderer

**File:** `src/renderers/hunyuan_custom_renderer.py` (NEW)

**Pre-Flight Check:**
```
1. Read: /mnt/project/wan_renderer.py (or src/renderers/wan_renderer.py)
   - This is our TEMPLATE - understand its structure before creating sibling
2. Verify these patterns in wan_renderer.py:
   - Uses @register_renderer(RendererType.WAN) decorator
   - Inherits from BaseRenderer
   - Has WORKFLOW_* class constants for workflow names
   - Has _select_workflow() method
   - Has _build_params() method
   - Uses WorkflowLoader with model_family parameter (or should after 1.3)
3. Read: /mnt/project/base.py - verify JobSpec, RenderResult, CharacterRef structures
4. Verify RendererType.HUNYUAN_CUSTOM exists (from Step 1.6)
5. Verify get_model_config('hunyuan_custom', 'i2v') works (from Step 1.4-1.5)
```

**What:** Create a new renderer class that implements `BaseRenderer` for HunyuanCustom.

**Why:** HunyuanCustom uses different ComfyUI nodes and has native identity (no IP-Adapter workaround needed).

**Guidance:**
- Use `wan_renderer.py` as a template — same structure, different details
- Decorate with `@register_renderer(RendererType.HUNYUAN_CUSTOM)`
- Key differences from Wan:
  - Uses `<image>` token in prompt for identity injection
  - Different default parameters (`flow_shift=13.0`, `cfg_scale=7.5`, `fps=25`)
  - Uses `llava` from model config instead of `clip`
  - No separate IP-Adapter step needed

**Critical Implementation Details:**
1. **Prompt formatting:** Prepend `"A portrait of <image> "` to prompts without `<image>` token
2. **Model tier:** Use `ModelTier.from_env()`, NOT hardcoded `ModelTier.DEV`
3. **Workflow loader:** Initialize with `model_family="hunyuan_custom"`
4. **Multi-subject:** Support up to 2 `<image>` tokens for 2 characters

**Required Methods:**
- `__init__`, `initialize`, `shutdown` — Lifecycle
- `generate` — Main entry point
- `_select_workflow` — Choose workflow based on job params
- `_build_params` — Build workflow placeholder dict
- `_format_prompt_with_image_token` — HunyuanCustom-specific prompt formatting
- `health_check`, `estimate_cost`, `estimate_time` — BaseRenderer requirements
- `supports_feature`, `get_capabilities` — Feature discovery

**Validation:**
```bash
python -c "
from src.renderers.hunyuan_custom_renderer import HunyuanCustomRenderer
from src.renderers.base import RendererType

r = HunyuanCustomRenderer()
print(f'Type: {r.renderer_type}')
assert r.renderer_type == RendererType.HUNYUAN_CUSTOM
print('✓ Renderer instantiates')
"
```

---

#### Step 2.2: Register Renderer

**File:** `src/renderers/__init__.py`

**Pre-Flight Check:**
```
1. Read: The project's src/renderers/__init__.py (check if it exists)
2. If it exists, verify:
   - Current imports (likely imports from .base and .wan_renderer)
   - Current __all__ list
   - Whether get_renderer_for_config is already exported
3. If it doesn't exist, we need to create it
4. Verify hunyuan_custom_renderer.py exists (from Step 2.1)
```

**What:** Import `HunyuanCustomRenderer` to trigger `@register_renderer` decorator.

**Why:** Python's decorator runs at import time. Without importing the module, the renderer won't be registered.

**Guidance:**
- Add import: `from .hunyuan_custom_renderer import HunyuanCustomRenderer`
- Add to `__all__`: `"HunyuanCustomRenderer"`
- Also export `get_renderer_for_config` from base

**Validation:**
```bash
python -c "
from src.renderers import list_renderers, RendererType
print(f'Registered: {list_renderers()}')
assert RendererType.HUNYUAN_CUSTOM in list_renderers()
print('✓ Renderer registered')
"
```

---

#### Step 2.3: Create HunyuanCustom Workflow

**File:** `workflows/hunyuan_custom/pass1_img2vid.json` (NEW)

**Pre-Flight Check:**
```
1. Read: /mnt/project/pass1_img2vid.json (the Wan version)
   - Understand the structure and placeholder patterns used
2. Verify:
   - Placeholder format is {{NAME}} 
   - Workflow has numbered node IDs as keys
   - Each node has class_type and inputs
3. Read HunyuanCustomRenderer._build_params() (from Step 2.1)
   - Note which placeholders it expects to inject
4. Cross-reference with Kijai's ComfyUI-HunyuanVideoWrapper documentation
   - Verify node names: HyVideoModelLoader, HyVideoSampler, etc.
5. Verify workflows/hunyuan_custom/ directory exists (from Step 1.2)
```

**What:** Create the ComfyUI workflow JSON for HunyuanCustom I2V generation.

**Why:** HunyuanCustom uses different nodes than Wan (HyVideoSampler vs WanImageToVideo).

**Guidance:**
- Use ComfyUI's workflow export as starting point if possible
- Key nodes: `HyVideoModelLoaderDiffSynthMultiGPU` (for 4x GPU), `HyVideoTextImageEncode`, `HyVideoSampler`, `HyVideoDecode`
- Placeholders to include: `{{MODEL_PATH}}`, `{{VAE_PATH}}`, `{{LLAVA_PATH}}`, `{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`, `{{FACE_REF_PATH}}`, `{{STEPS}}`, `{{CFG_SCALE}}`, `{{FLOW_SHIFT}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{FRAMES}}`, `{{FPS}}`

**Note:** This workflow should be validated against actual ComfyUI during Phase 0 testing. The exact node names and connections depend on the Kijai extension version.

**Validation:**
```bash
python -c "
from src.comfy_client import WorkflowLoader
loader = WorkflowLoader(model_family='hunyuan_custom')
t = loader.load('pass1_img2vid')
print(f'Placeholders: {t.placeholders}')
assert 'PROMPT' in t.placeholders
"
```

---

#### Phase 2 Complete Validation

```bash
# 1. Renderer instantiates
python -c "from src.renderers import HunyuanCustomRenderer; print(HunyuanCustomRenderer())"

# 2. Renderer is registered
python -c "from src.renderers import list_renderers, RendererType; assert RendererType.HUNYUAN_CUSTOM in list_renderers()"

# 3. Factory returns correct renderer
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom python -c "
from src.core.config import reload_config
reload_config()
from src.renderers import get_renderer_for_config, RendererType
r = get_renderer_for_config()
assert r.renderer_type == RendererType.HUNYUAN_CUSTOM
print('✓ Factory works')
"

# 4. Workflow loads
python -c "from src.comfy_client import WorkflowLoader; WorkflowLoader(model_family='hunyuan_custom').load('pass1_img2vid')"
```

---

### Phase 3: Integration (Days 7-8)

Phase 3 connects everything to main.py and verifies end-to-end.

---

#### Step 3.1: Update main.py

**File:** `main.py`

**Pre-Flight Check:**
```
1. Read: /mnt/project/main.py
2. Find the WanRenderer import - note exact line and format
3. Find renderer initialization - search for "WanRenderer()"
   - Note the surrounding context (dry_run check, logging, etc.)
   - Note exact line numbers for surgical replacement
4. Verify:
   - get_renderer(RendererType.MOCK) is used for dry_run
   - self.config exists at point of renderer initialization
   - self.renderer is the attribute name used
5. Check if there are other WanRenderer references elsewhere in file
6. Verify get_renderer_for_config is importable from src.renderers
```

**What:** Replace hardcoded `WanRenderer` with config-driven renderer factory.

**Why:** main.py should respect `config.video_model.model_family` to choose renderer.

**Guidance:**
- Find the import of `WanRenderer` and add/replace with `get_renderer_for_config`
- Find the renderer initialization block (look for `WanRenderer()`)
- Replace direct `WanRenderer()` instantiation with `get_renderer_for_config(self.config)`
- Keep the dry-run mock renderer logic unchanged
- Add logging to show which renderer was selected

**Changes Needed:**
1. Import: Add `get_renderer_for_config` from `src.renderers`
2. Initialization: Replace `WanRenderer()` with `get_renderer_for_config(self.config)`

**Validation:**
```bash
# Test with Wan (should work same as before)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan python main.py --project tests/quick_test.json --dry-run -v

# Test with HunyuanCustom (should select HunyuanCustom renderer)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom python main.py --project tests/quick_test.json --dry-run -v
```

---

#### Step 3.2: Verify Bridge Engine Compatibility

**File:** `src/studio/bridge_engine.py` (VERIFY, may not need changes)

**Pre-Flight Check:**
```
1. Read: /mnt/project/bridge_engine.py (or src/studio/bridge_engine.py)
2. Search for WorkflowLoader usage:
   - How is it instantiated? (with or without model_family?)
   - Which workflows does it load? (bridge_full, bridge_pose_only, etc.)
3. Search for hardcoded workflow paths
4. Verify:
   - Bridge workflows are now in workflows/shared/ (from Step 1.2)
   - WorkflowLoader with model_family=None or unset will find them via shared/ search
5. Determine if changes are needed or if existing code will work
```

**What:** Ensure Bridge Engine finds workflows in `shared/` directory.

**Why:** Bridge workflows were moved to `workflows/shared/`. Bridge Engine should still find them.

**Guidance:**
- Check how Bridge Engine creates its `WorkflowLoader`
- If it passes no `model_family`, the updated loader should find workflows in shared/ via the search order
- If it hardcodes paths, update to use `WorkflowLoader(model_family=None)` or rely on shared/ search

**Validation:**
```bash
python -c "
from src.studio.bridge_engine import ComfyUIBridgeEngine
# If this import works without error, the module at least loads
print('Bridge engine module loads')
"

# Full test with dry run
python main.py --project tests/quick_test.json --dry-run -v
# Should complete without 'workflow not found' errors for bridge_*
```

---

#### Phase 3 Complete Validation (Integration Checklist)

| Test | Command | Pass Criteria |
|------|---------|---------------|
| Wan dry run | `CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan python main.py --project tests/quick_test.json --dry-run -v` | Completes without error |
| HunyuanCustom dry run | `CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom python main.py --project tests/quick_test.json --dry-run -v` | Completes without error, logs show "hunyuan_custom renderer" |
| Model switching | See validation script below | Both renderers instantiate correctly |

```bash
# Model switching test
python -c "
import os
from src.core.config import reload_config
from src.renderers import get_renderer_for_config, RendererType

os.environ['CONTINUUM_VIDEO_MODEL__MODEL_FAMILY'] = 'wan'
reload_config()
r1 = get_renderer_for_config()
print(f'Wan: {r1.renderer_type}')
assert r1.renderer_type == RendererType.WAN

os.environ['CONTINUUM_VIDEO_MODEL__MODEL_FAMILY'] = 'hunyuan_custom'  
reload_config()
r2 = get_renderer_for_config()
print(f'HunyuanCustom: {r2.renderer_type}')
assert r2.renderer_type == RendererType.HUNYUAN_CUSTOM

print('✓ Model switching works')
"
```

---

### Execution Order Summary

When implementing, follow this exact order:

```
Phase 1 (Foundation - no new renderer yet)
├── 1.1 config.py — Add VideoModelConfig
├── 1.2 workflows/ — Reorganize directories (bash)
├── 1.3 workflow_loader.py — Add model_family support
├── 1.4 model_loader.py — Extend ModelConfig schema
├── 1.5 models.json — Add hunyuan_custom entries
├── 1.6 base.py — Add enum + factory function
└── [VALIDATE Phase 1 - Wan still works]

Phase 2 (New renderer)
├── 2.1 hunyuan_custom_renderer.py — Create renderer (NEW FILE)
├── 2.2 renderers/__init__.py — Register renderer
├── 2.3 pass1_img2vid.json — Create workflow (NEW FILE)
└── [VALIDATE Phase 2 - Renderer works in isolation]

Phase 3 (Integration)
├── 3.1 main.py — Use factory instead of hardcoded renderer
├── 3.2 bridge_engine.py — Verify compatibility (may be no-op)
└── [VALIDATE Phase 3 - Full pipeline works with both models]
```

**After each step:** Run the validation command. Do not proceed if it fails.

**If validation fails:** Fix the current file before moving on. Do not accumulate errors.

#### 3.2 Verify Bridge Engine Compatibility

Bridge Engine uses SDXL workflows which are in `shared/`. 

**Key Question:** Is Bridge Engine still needed with HunyuanCustom?

| Scenario | With Wan | With HunyuanCustom |
|----------|----------|-------------------|
| Single shot | Hero Frame required | Native face ref |
| Multi-shot | Bridge Frame required | **Test needed** |

**Test during Phase 0:**
- If HunyuanCustom maintains identity across shots with just face ref → Bridge optional
- If identity drifts → Keep Bridge Engine

### Phase 4: Validation (Days 9-10)

See Section 6: Testing Protocol.

### Phase 5: Buffer (Days 11-12)

Reserved for unexpected issues and demo preparation.

---

## 6. Testing Protocol

### 6.1 Unit Tests (Run After Each Phase)

```bash
# After Phase 1: Infrastructure
python -c "
from src.core.config import get_config
config = get_config()
print(f'Model family: {config.video_model.model_family}')
assert config.video_model.model_family in ['wan', 'hunyuan_custom']
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
config = get_model_config('hunyuan_custom', 'i2v', ModelTier.DEV)
print(f'HunyuanCustom I2V model: {config.unet}')
print('✓ Model loader test passed')
"
```

### 6.2 Integration Tests

```bash
# Test Wan still works after restructuring
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py --project tests/quick_test.json --dry-run -v

# Test HunyuanCustom renderer instantiation
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom \
python -c "
from src.renderers.base import get_renderer_for_config
renderer = get_renderer_for_config()
print(f'Renderer type: {renderer.renderer_type}')
"
```

### 6.3 End-to-End Tests

```bash
# Wan E2E (should work same as before)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py \
  --project tests/quick_test.json \
  --consistency tests/bible.json \
  --output workspace/output/wan_test \
  --no-pass2 -v

# HunyuanCustom E2E
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom \
python main.py \
  --project tests/quick_test.json \
  --consistency tests/bible.json \
  --output workspace/output/hunyuan_test \
  --no-pass2 -v
```

### 6.4 Identity Preservation Tests

```bash
# 5-second clip identity test
python main.py \
  --project tests/identity_test_5sec.json \
  --consistency tests/bible.json \
  --output workspace/output/identity_test \
  -v

# Check ArcFace scores in output
# Target: >= 0.60 frame 1 vs frame 129
```

### 6.5 Model Switching Test

```bash
# Generate with HunyuanCustom
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom \
python main.py --project tests/quick_test.json --output workspace/output/switch_hunyuan

# Switch to Wan (same project)
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan \
python main.py --project tests/quick_test.json --output workspace/output/switch_wan

# Both should complete without errors
```

---

## 7. Debugging Guide

### 7.1 Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `FileNotFoundError: Workflow 'pass1_img2vid' not found` | Workflows not moved to subdirectories | Run Phase 1.2 file moves |
| `Unknown model family: hunyuan_custom` | Config not updated | Add VideoModelConfig to config.py |
| `ModuleNotFoundError: hunyuan_custom_renderer` | Renderer not created | Create file in Phase 2 |
| `KeyError: 'hunyuan_custom'` | models.json not updated | Add hunyuan_custom section |
| `ComfyUI node not found: HyVideoSampler` | Kijai wrapper not installed | Install ComfyUI-HunyuanVideoWrapper |
| `CUDA out of memory` | Single GPU insufficient | Use ComfyUI-MultiGPU, distribute across 4x4090 |
| `Black video output` | Wrong flow_shift or CFG | Use flow_shift=13.0, CFG=7.5 |

### 7.2 Diagnostic Commands

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

# Check if HunyuanCustom nodes exist on ComfyUI server
curl -s http://localhost:8188/object_info | python -c "
import sys, json
data = json.load(sys.stdin)
hy_nodes = [k for k in data.keys() if 'HyVideo' in k or 'hunyuan' in k.lower()]
print('HunyuanVideo nodes:', hy_nodes)
"

# Check GPU memory usage
nvidia-smi

# Monitor during generation
watch -n 1 nvidia-smi
```

### 7.3 HunyuanCustom-Specific Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Identity not preserved | Wrong prompt format | Use `<image>` token: "A portrait of <image> walking" |
| Face looks different | ID weight too low | Increase ID_WEIGHT to 1.0 |
| Multi-GPU not working | Wrong loader node | Use `HyVideoModelLoaderDiffSynthMultiGPU` |
| Slow generation | Not using all GPUs | Verify ComfyUI-MultiGPU is installed and configured |
| Audio lip sync broken | Audio-driven not in ComfyUI | Use MuseTalk for now |

### 7.4 Log Locations

```
workspace/output/*/generation.log    # Per-project generation logs
workspace/checkpoints/               # Checkpoint state files
```

---

## 8. Rollback Procedure

If HunyuanCustom integration fails and you need to revert to Wan:

### 8.1 Quick Rollback (Config Only)

```bash
# Set environment variable
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan

# Or in .env file
echo "CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan" >> .env

# Restart application
```

### 8.2 Full Rollback (Code Changes)

```bash
# Revert main.py to hardcoded WanRenderer
git checkout main.py

# Keep directory structure (doesn't hurt anything)
# Wan workflows still work from workflows/wan/
```

### 8.3 Rollback Checklist

- [ ] Set CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan
- [ ] Verify Wan workflows exist in workflows/wan/
- [ ] Test quick_test.json with Wan
- [ ] Confirm identity preservation still works
- [ ] Switch back to RTX 4090 single GPU ($0.74/hr)

---

## 9. Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Multi-GPU extension doesn't work | Low | High | Test early in Phase 0; fallback to H100 |
| Workflow loader breaks Wan | Medium | High | Legacy path fallback + thorough testing |
| Identity worse than benchmark | Medium | Medium | Phase 0 validation before committing |
| VRAM higher than expected | Low | Medium | Have H100 as backup option |
| Kijai wrapper issues | Medium | Medium | Check GitHub issues, community support |
| Bridge Engine breaks | Low | High | Bridge uses SDXL, should be unaffected |
| Demo deadline missed | Medium | High | Day 11-12 buffer, can demo Wan if needed |
| Audio-driven delayed | High | Low | Already planned: Keep MuseTalk |

---

## 10. Day-by-Day Schedule

### Day 1-2: Phase 0 Validation (CRITICAL)
- [ ] Set up 4x RTX 4090 on RunPod
- [ ] Install ComfyUI + extensions (MultiGPU, Kijai wrapper)
- [ ] Download HunyuanCustom models (~32 GB)
- [ ] Run Test 1: Basic function
- [ ] Run Test 2: Single-shot identity (target: ≥0.60)
- [ ] Run Test 3: Multi-shot identity (target: ≥0.55)
- [ ] Run Test 4: Bridge Engine comparison
- [ ] Run Test 5: vs Wan baseline
- [ ] **EXIT GATE:** Make go/no-go decision

### Day 3-4: Phase 1 Infrastructure
- [ ] Add VideoModelConfig to config.py
- [ ] Create directory structure
- [ ] Move workflow files
- [ ] Update workflow_loader.py
- [ ] Update models.json
- [ ] Test Wan still works

### Day 5-6: Phase 2 HunyuanCustom Renderer
- [ ] Create hunyuan_custom_renderer.py skeleton
- [ ] Implement initialize/shutdown
- [ ] Implement _format_prompt_with_image_token
- [ ] Add to renderer registry
- [ ] Create HunyuanCustom workflow JSONs
- [ ] Test basic generation

### Day 7-8: Phase 3 Integration
- [ ] Update main.py renderer factory
- [ ] Verify bridge_engine compatibility (or disable if not needed)
- [ ] Run integration tests
- [ ] Fix any breaks
- [ ] Test multi-shot sequence

### Day 9-10: Phase 4 Validation
- [ ] Run 5-second identity tests
- [ ] Compare HunyuanCustom vs Wan quality
- [ ] Test model switching both directions
- [ ] Document results

### Day 11-12: Buffer + Demo Prep
- [ ] Create investor demo project
- [ ] Generate demo videos
- [ ] Review quality
- [ ] Re-render if needed
- [ ] Prepare backup Wan demo (if needed)
- [ ] Final rehearsal

---

## Appendix A: ComfyUI Node Reference

### Kijai HunyuanVideoWrapper Nodes

| Purpose | `class_type` | Notes |
|---------|--------------|-------|
| Model Loader | `HyVideoModelLoader` | Standard single-GPU |
| Model Loader (Multi-GPU) | `HyVideoModelLoaderDiffSynthMultiGPU` | For 4x4090 setup |
| Sampler | `HyVideoSampler` | Main generation |
| Text+Image Encode | `HyVideoTextImageEncode` | For face reference |
| Custom Prompt | `HyVideoCustomPromptTemplate` | Format `<image>` token |
| VAE Loader | `HyVideoVAELoader` | Load VAE |
| Decode | `HyVideoDecode` | Latent to video |

### Multi-GPU Configuration

```python
# In workflow JSON, use multi-GPU loader:
{
  "model_loader": {
    "class_type": "HyVideoModelLoaderDiffSynthMultiGPU",
    "inputs": {
      "model": "hunyuan_video_custom_720p_fp8_scaled.safetensors",
      "devices": [0, 1, 2, 3]  # All 4 GPUs
    }
  }
}
```

---

## Appendix B: Model Files Checklist

```
RUNPOD MODEL LOCATIONS (4x RTX 4090):

/workspace/ComfyUI/models/diffusion_models/
  [ ] hunyuan_video_custom_720p_fp8_scaled.safetensors  (~13 GB)

/workspace/ComfyUI/models/vae/
  [ ] hunyuan_video_vae_bf16.safetensors  (~2 GB)

/workspace/ComfyUI/models/text_encoders/
  [ ] llava-llama-3-8b-v1_1/  (~16 GB, auto-downloads)

/workspace/ComfyUI/models/clip_vision/
  [ ] clip-vit-large-patch14/  (~400 MB, auto-downloads)

TOTAL DOWNLOAD: ~32 GB
```

### Download Commands

```bash
cd /workspace/ComfyUI/models

# Main model (FP8)
huggingface-cli download Kijai/HunyuanVideo_comfy \
  hunyuan_video_custom_720p_fp8_scaled.safetensors \
  --local-dir diffusion_models/

# VAE
huggingface-cli download tencent/HunyuanVideo \
  hunyuan-video-t2v-720p/vae/pytorch_model.pt \
  --local-dir vae/

# LLaVA and CLIP Vision auto-download on first use
```

---

## Appendix C: Quick Reference

```bash
# Switch to HunyuanCustom
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom

# Switch to Wan
export CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan

# Check current model
python -c "from src.core.config import get_config; print(get_config().video_model.model_family)"

# Test quick generation
python main.py --project tests/quick_test.json --no-pass2 -v
```

---

## Appendix D: Identity Mechanism Comparison

### How Wan 2.1 Identity Works

```
Face Reference → IP-Adapter (external plugin) → SDXL → Hero Frame
                                                          ↓
                                               Wan 2.1 I2V (init_image)
                                                          ↓
                                               Identity from init_image only
                                               (no external reference during I2V)
```

**Wan has NO external reference input during video generation.**
Identity depends entirely on what's in the init_image.

### How HunyuanCustom Identity Works

```
Face Reference → LLaVA 8B VLM → Text-Image Fusion
                                      ↓
                          Temporal ID Enhancement
                          (identity at EVERY frame)
                                      ↓
                            Video Diffusion
                            (native identity)
```

**HunyuanCustom has NATIVE external reference input.**
The `<image>` token allows face reference injection directly into generation.

### The `<image>` Token System

```python
# Single subject
prompt = "A portrait of <image> riding a bicycle in a park"
# The <image> token is replaced by face reference embedding

# Multi-subject (2 images)  
prompt = "<image> (Alice) is talking to <image> (Bob) in a cafe"
# First <image> = first reference image
# Second <image> = second reference image
```

### Why This Changes Everything

| Aspect | Wan Pipeline | HunyuanCustom Pipeline |
|--------|--------------|------------------------|
| Hero Frame | Required | **Optional** |
| Bridge Engine | Required for multi-shot | **Test needed** (may be optional) |
| Identity injection | External (SDXL + IP-Adapter) | **Native** |
| Identity score | 0.204 (VACE benchmark) | **0.627** (3× better) |

---

## Appendix E: Audio-Driven Mode Status

### Current Status

| Feature | ComfyUI | CLI |
|---------|---------|-----|
| Single-subject (face + prompt → video) | ✅ Available | ✅ Available |
| **Audio-driven (face + audio → talking video)** | ❌ **NOT YET** | ✅ Available |
| Video-driven (face swap) | ❌ Not yet | ✅ Available |

### Current Workaround

```
HunyuanCustom (face + prompt → video) → MuseTalk (video + audio → lip sync)
```

This is still 2 steps, but:
- HunyuanCustom provides 3× better identity than Wan
- MuseTalk handles lip sync reliably

### Future (When Audio ComfyUI Released)

```
HunyuanCustom (face + prompt + audio → video with lip sync)
```

One step, built-in lip sync, no MuseTalk needed.

**Timeline:** Unknown. Keep MuseTalk for MVP.

---

## Appendix F: Workflow JSON Template

### HunyuanCustom I2V Workflow (Multi-GPU)

```json
{
  "model_loader": {
    "class_type": "HyVideoModelLoaderDiffSynthMultiGPU",
    "inputs": {
      "model": "{{MODEL_PATH}}",
      "quantization": "fp8_scaled",
      "devices": [0, 1, 2, 3]
    }
  },
  
  "vae_loader": {
    "class_type": "HyVideoVAELoader",
    "inputs": {
      "vae_name": "{{VAE_PATH}}"
    }
  },
  
  "load_face_ref": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "{{FACE_REF_PATH}}"
    }
  },
  
  "text_image_encode": {
    "class_type": "HyVideoTextImageEncode",
    "inputs": {
      "prompt": "{{PROMPT}}",
      "image": ["load_face_ref", 0],
      "id_weight": "{{ID_WEIGHT}}"
    }
  },
  
  "sampler": {
    "class_type": "HyVideoSampler",
    "inputs": {
      "model": ["model_loader", 0],
      "positive": ["text_image_encode", 0],
      "negative": ["text_image_encode", 1],
      "steps": "{{STEPS}}",
      "cfg": "{{CFG_SCALE}}",
      "flow_shift": "{{FLOW_SHIFT}}",
      "seed": "{{SEED}}",
      "width": "{{WIDTH}}",
      "height": "{{HEIGHT}}",
      "frames": "{{FRAMES}}"
    }
  },
  
  "vae_decode": {
    "class_type": "HyVideoDecode",
    "inputs": {
      "samples": ["sampler", 0],
      "vae": ["vae_loader", 0]
    }
  },
  
  "save_video": {
    "class_type": "SaveVideo",
    "inputs": {
      "images": ["vae_decode", 0],
      "filename_prefix": "continuum/hunyuan_custom",
      "fps": "{{FPS}}"
    }
  }
}
```

---

## Summary

### The Pivot

| From | To |
|------|----|
| Wan 2.1 + IP-Adapter + Bridge Engine | HunyuanCustom (native identity) |
| Single RTX 4090 (24GB) @ $0.74/hr | 4x RTX 4090 (96GB) @ $2.00/hr |
| ~0.204 ArcFace (Wan benchmark) | ~0.627 ArcFace (HunyuanCustom benchmark) |
| 3-step identity pipeline | 1-step identity pipeline |

### What We Gain

- **3× better identity preservation** (0.627 vs 0.204)
- **Native face reference** (no SDXL + IP-Adapter workaround)
- **Simpler pipeline** (fewer steps, fewer failure points)
- **Multi-subject support** (2 characters in one video)
- **Future audio-driven** (when ComfyUI support arrives)

### What We Keep

- MuseTalk for lip sync (until audio-driven in ComfyUI)
- Bridge Engine for testing (may become optional)
- Entire audio pipeline (Sonic Engine)
- Post-production pipeline
- Director Agent / planning layer

### What We Lose

- Low-cost single GPU option ($0.74/hr → $2.00/hr)
- Simple single-GPU setup (need MultiGPU extension)

### Bottom Line

**HunyuanCustom provides 3× better identity at 2.7× the GPU cost.**  
For an investor demo where quality matters more than cost, this is the right trade-off.

---

**Document Status:** Ready for Phase 0 Validation  
**Next Action:** Set up 4x RTX 4090 on RunPod, run validation tests  
**Decision Point:** After Test 1-5 results, confirm or abort pivot  
**Fallback Plan:** Demo with Wan if HunyuanCustom integration incomplete