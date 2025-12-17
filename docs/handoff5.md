# HANDOFF PROMPT - Continuum Engine Development

## Context
You are picking up development of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos. The human is the co-founder (a "vibe coder" - systems thinker, not low-level engineer).

**Source of Truth:** `ARCHITECTURE_SUMMARY.md` in the project

---

## What Has Been Built (Prior Sessions)

### Session 1-2: Core Workflows Created
Created 11 ComfyUI workflow JSON files in `workflows/`:

| Workflow | Purpose | Status |
|----------|---------|--------|
| `pass1_structural.json` | T2V base generation | ✅ Complete |
| `pass1_structural_lora.json` | T2V + character LoRA | ✅ Complete |
| `pass1_img2vid.json` | I2V base generation | ✅ Complete |
| `pass1_img2vid_lora.json` | I2V + character LoRA | ✅ Complete |
| `bridge_basic.json` | Frame transition (prompt only) | ✅ Complete |
| `bridge_ipadapter.json` | + face reference | ✅ Complete |
| `bridge_pose_only.json` | + pose ControlNet | ✅ Complete |
| `bridge_full.json` | + pose + depth ControlNets | ✅ Complete |
| `refine_vid2vid_simple.json` | Pass 2 frame-by-frame | ✅ Complete |
| `refine_vid2vid_temporal.json` | Pass 2 batched temporal | ✅ Complete |
| `musetalk_lipsync.json` | Lip sync via Musetalk | ✅ Complete |

### Session 2: Test Suite Created
Created comprehensive test coverage in `tests/`:

| Test File | Tests | Purpose |
|-----------|-------|---------|
| `test_workflow_contracts.py` | 59 tests | Validates workflow structure, placeholders, connections |
| `test_workflow_stress.py` | 37 tests | Edge cases, value ranges, injection simulation |

**Total: 96 workflow tests - ALL PASSING**

### Session 3 (This Session): Model Tier System

**Problem Solved:** Workflows had hardcoded model paths. Needed ability to switch between dev/standard/beast quality tiers.

**Files Created:**

1. **`workflows/models.json`** - Model registry with tiers:
   - `dev`: 1.3B model, 8GB VRAM, fast iteration
   - `standard`: 14B bf16, 24GB VRAM, production
   - `beast`: 14B fp16, 40GB VRAM, VC demos

2. **`src/core/model_loader.py`** - Reads models.json, returns config based on `CONTINUUM_MODEL_TIER` env var

3. **`tests/test_model_loader.py`** - 27 tests for model loader

**Files Modified:**

1. **`workflows/pass1_*.json`** (all 4 files) - Replaced hardcoded model paths with placeholders:
   - `{{UNET_MODEL}}`
   - `{{VAE_MODEL}}`
   - `{{CLIP_MODEL}}`
   - `{{CLIP_VISION_MODEL}}` (I2V only)

2. **`src/studio/wan_renderer.py`** - Added integration to use model_loader:
   - Added import: `from ..core.model_loader import get_model_config, ModelTier`
   - Added method: `_get_model_config(self, job)` 
   - Modified: `_build_generation_params()` to include model params

3. **`test_workflow_contracts.py`** & **`test_workflow_stress.py`** - Updated to:
   - Exclude `models.json` from workflow validation
   - Accept model placeholders OR hardcoded values
   - Added `UNET_MODEL`, `VAE_MODEL`, `CLIP_MODEL`, `CLIP_VISION_MODEL` to MOCK_VALUES

4. **`docs/MODEL_CONFIGURATION.md`** - Documentation for tier system

5. **`main.py`** - Fixed broken imports:
   - `Pass2Refiner` → `BaseRefiner`
   - (Partial fix - see known issues)

---

## Current Test Status

```bash
pytest tests/test_model_loader.py tests/test_workflow_contracts.py tests/test_workflow_stress.py -v
# Result: 123 passed
```

**Known Issue:** `tests/test_main_orchestrator.py` has import errors (pre-existing, not caused by our changes):
```
# Workaround:
pytest tests/ -v --ignore=tests/test_main_orchestrator.py
```

---

## Known Issues (TODO)

### main.py Import Mismatches
```markdown
| Line | Current Import | Should Be |
|------|----------------|-----------|
| ~129 | `Pass2Refiner` | `BaseRefiner, ComfyRefiner, RefinerFactory` |
| ~131 | `RIFEInterpolator` | `BaseInterpolator, ComfyRIFEInterpolator, InterpolatorFactory` |

Type hints to update:
- `Optional[Pass2Refiner]` → `Optional[BaseRefiner]` (DONE)
- `Optional[RIFEInterpolator]` → `Optional[BaseInterpolator]` (NOT DONE)
```

---

## Architecture Status (vs ARCHITECTURE_SUMMARY.md)

### Priority Modules Status

| Priority | Module | Status | Notes |
|----------|--------|--------|-------|
| **P0** | `client.py` | ✅ EXISTS | ComfyUI WebSocket connection |
| **P1** | `wan_renderer.py` | ✅ EXISTS + UPDATED | Now uses model_loader for tier switching |
| **P2** | `scene_graph.py` | ✅ EXISTS | Script → shots parser |
| **P3a** | I2V workflows | ✅ CREATED | `pass1_img2vid.json` with placeholders |
| **P3b** | LoRA workflows | ✅ CREATED | `pass1_*_lora.json` files |
| **P4** | `bridge_engine.py` | ✅ EXISTS | References our `bridge_*.json` workflows |
| **P5** | `identity_checker.py` | ✅ EXISTS | ArcFace verification |
| **P6** | `tts_engine.py` + `lip_sync.py` | ✅ EXISTS | `musetalk_lipsync.json` created |
| **P7** | `pass2_refiner.py` + `rife_interpolator.py` | ✅ EXISTS | `refine_vid2vid_*.json` created |

### What's Complete
- All workflow JSONs for the visual pipeline
- Model tier system (dev/standard/beast switching)
- Comprehensive test coverage (123 tests passing)
- Documentation

### What's NOT Done Yet
- End-to-end integration testing with real ComfyUI
- Sonic engine workflows (ambience, foley, score)
- RIFE interpolation workflow
- Color matching / post-production workflows

---

## File Structure (Current)

```
~/Projects/Continuum/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ARCHITECTURE_SUMMARY.md
│   ├── LESSONS_LEARNED.md
│   ├── MODEL_CONFIGURATION.md      ← NEW
│   └── LLM_CODING_GUIDELINES.md
├── workflows/
│   ├── models.json                  ← NEW (tier registry)
│   ├── pass1_structural.json        ← UPDATED (placeholders)
│   ├── pass1_structural_lora.json   ← UPDATED (placeholders)
│   ├── pass1_img2vid.json           ← UPDATED (placeholders)
│   ├── pass1_img2vid_lora.json      ← UPDATED (placeholders)
│   ├── bridge_basic.json
│   ├── bridge_ipadapter.json
│   ├── bridge_pose_only.json
│   ├── bridge_full.json
│   ├── refine_vid2vid_simple.json
│   ├── refine_vid2vid_temporal.json
│   └── musetalk_lipsync.json
├── src/
│   ├── core/
│   │   ├── model_loader.py          ← NEW
│   │   ├── config.py
│   │   └── ...
│   ├── studio/
│   │   ├── wan_renderer.py          ← UPDATED (uses model_loader)
│   │   ├── bridge_engine.py
│   │   ├── pass2_refiner.py
│   │   └── ...
│   └── ...
├── tests/
│   ├── test_model_loader.py         ← NEW (27 tests)
│   ├── test_workflow_contracts.py   ← UPDATED (59 tests)
│   ├── test_workflow_stress.py      ← UPDATED (37 tests)
│   └── ...
└── main.py                          ← PARTIALLY FIXED
```

---

## How to Verify Current State

```bash
cd ~/Projects/Continuum

# 1. Run core tests (should pass)
pytest tests/test_model_loader.py tests/test_workflow_contracts.py tests/test_workflow_stress.py -v

# 2. Check tier switching works
python -c "
from src.core.model_loader import get_model_config, ModelTier
config = get_model_config('wan21', 't2v', ModelTier.BEAST)
print(f'Beast UNET: {config.unet}')
print(f'VRAM Required: {config.vram_required_gb}GB')
"

# 3. Check model placeholders in workflows
grep "UNET_MODEL" workflows/pass1_structural.json
```

---

## Suggested Next Steps

Based on architecture priority, options include:

1. **Fix main.py imports** (quick win, unblocks full test suite)

2. **Create RIFE interpolation workflow** (`rife_interpolate.json`)
   - Goes after Pass 2, before final stitch
   - Upscales 12fps → 24fps

3. **Integration testing** 
   - Test wan_renderer → ComfyUI with mock/real connection
   - Verify model tier actually affects generation

4. **Sonic engine workflows**
   - `ambience.json` - AudioLDM2 based
   - `foley.json` - Event-triggered sounds

5. **Update other renderers** (bridge_engine, pass2_refiner) to use model_loader pattern

---

## Important Constraints (From System Prompt)

1. **Vibe Coder Constraint:** No custom CUDA kernels. Python glue code only.
2. **Pluggable Engines:** Use abstract interfaces (`BaseRenderer`, etc.)
3. **ComfyUI Workflows:** Complex diffusion logic in JSON, Python orchestrates
4. **Test-First:** Update tests when changing contracts
5. **UPPERCASE Placeholders:** All workflow placeholders use `{{UPPERCASE}}`

---

## How to Continue

Ask the human what they want to tackle next. Refer to ARCHITECTURE_SUMMARY.md for the priority order. Always:

1. Read relevant files before making changes
2. Create/update tests alongside code
3. Verify with `pytest` after changes
4. Explain architectural reasoning