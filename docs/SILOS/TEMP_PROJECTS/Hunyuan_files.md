# HunyuanCustom Initiative - Complete Project Setup

**Purpose:** Dedicated Claude Project for HunyuanCustom pivot work  
**Why separate:** This is the critical path, touches multiple silos, can't afford context gaps

---

## Project: `continuum-hunyuan`

This project has EVERYTHING needed for HunyuanCustom work. No switching between silo projects.

---

## Required Files (Copy All)

### 1. Context Documents
```
docs/
├── INITIATIVE_HUNYUAN.md       # Quick reference (created earlier)
├── MODEL_PIVOT.md              # FULL spec - the bible for this work
├── ARCHITECTURE_SUMMARY.md     # System context
└── LESSONS_LEARNED.md          # Debugging tips (ComfyUI issues documented here)
```

### 2. Renderers (The Main Work)
```
src/renderers/
├── __init__.py
├── base.py                     # BaseRenderer interface - MUST implement this
├── hunyuan_custom_renderer.py  # PRIMARY FILE - the implementation
└── wan_renderer.py             # REFERENCE - copy patterns from here
```

### 3. Studio (Calls the Renderer)
```
src/studio/
├── __init__.py
├── pass1_generator.py          # Orchestrates generation, calls renderer
├── bridge_engine.py            # May become optional for Hunyuan
├── pass2_refiner.py            # Post-refinement (unchanged but context)
└── workflow_utils.py           # Utility functions
```

### 4. Core Infrastructure
```
src/core/
├── __init__.py
├── config.py                   # Configuration (model selection)
├── model_loader.py             # Model registry - has hunyuan_custom entries
├── job_state.py                # Job status tracking
└── error_recovery.py           # Fallback logic

src/comfy_client/
├── __init__.py
├── client.py                   # WebSocket client to ComfyUI
└── workflow_loader.py          # Loads & substitutes workflow JSON
```

### 5. Workflows (Critical!)
```
workflows/
├── hunyuan_custom/
│   └── pass1_img2vid.json      # PRIMARY - the Hunyuan workflow
│
├── wan/
│   ├── pass1_img2vid.json      # REFERENCE - compare structure
│   └── pass1_img2vid_lora.json # REFERENCE - for LoRA pattern
│
└── shared/
    ├── bridge_full.json        # May need modification
    ├── bridge_ipadapter.json   # Fallback bridge
    ├── hero_frame.json         # May become optional
    └── rife_interpolation.json # Unchanged but context

models.json                     # Model paths registry
```

### 6. Audit (Verify It Works)
```
src/audit/
├── __init__.py
├── identity_checker.py         # ArcFace scoring - validates our work
├── physics_checker.py          # Context only
└── reviewer.py                 # Orchestrates checks
```

### 7. Tests
```
tests/
├── conftest.py                 # Test fixtures
├── test_hero_frame.py          # Hero frame tests (reference)
├── test_i2v_identity.py        # Identity tests (if exists)
└── verify_hunyuan_integration.py  # Hunyuan-specific validation
```

### 8. Entry Point
```
main.py                         # See how everything wires together
```

---

## Complete File List (Copy/Paste Ready)

```
docs/INITIATIVE_HUNYUAN.md
docs/MODEL_PIVOT.md
docs/ARCHITECTURE_SUMMARY.md
docs/LESSONS_LEARNED.md

src/renderers/__init__.py
src/renderers/base.py
src/renderers/hunyuan_custom_renderer.py
src/renderers/wan_renderer.py

src/studio/__init__.py
src/studio/pass1_generator.py
src/studio/bridge_engine.py
src/studio/pass2_refiner.py
src/studio/workflow_utils.py

src/core/__init__.py
src/core/config.py
src/core/model_loader.py
src/core/job_state.py
src/core/error_recovery.py

src/comfy_client/__init__.py
src/comfy_client/client.py
src/comfy_client/workflow_loader.py

workflows/hunyuan_custom/pass1_img2vid.json
workflows/wan/pass1_img2vid.json
workflows/wan/pass1_img2vid_lora.json
workflows/shared/bridge_full.json
workflows/shared/bridge_ipadapter.json
workflows/shared/hero_frame.json
workflows/shared/rife_interpolation.json
models.json

src/audit/__init__.py
src/audit/identity_checker.py
src/audit/physics_checker.py
src/audit/reviewer.py

tests/conftest.py
tests/test_hero_frame.py
tests/verify_hunyuan_integration.py

main.py
```

---

## Estimated Size

| Category | Files | Est. Size |
|----------|-------|-----------|
| Docs | 4 | ~100 KB |
| Renderers | 4 | ~100 KB |
| Studio | 5 | ~150 KB |
| Core | 5 | ~80 KB |
| ComfyClient | 3 | ~50 KB |
| Workflows | 7 | ~25 KB |
| Audit | 4 | ~80 KB |
| Tests | 3 | ~50 KB |
| main.py | 1 | ~100 KB |
| **TOTAL** | **36 files** | **~735 KB** |

This should fit comfortably in Claude Projects.

---

## What Claude Can Do With This

✅ Implement `hunyuan_custom_renderer.py` fully  
✅ Reference `wan_renderer.py` for patterns  
✅ Understand how `pass1_generator.py` calls renderers  
✅ Edit workflows with full context  
✅ Update `model_loader.py` and `models.json`  
✅ Know what `bridge_engine.py` does (to make it optional)  
✅ Understand ArcFace scoring in `identity_checker.py`  
✅ See how `main.py` wires everything together  
✅ Debug ComfyUI issues using `LESSONS_LEARNED.md`  

---

## What's NOT Included (And Why)

| Excluded | Reason |
|----------|--------|
| `src/director/*` | Hunyuan doesn't change Director at all |
| `src/sonic/*` | Audio is separate initiative |
| `src/post/*` | Post-production unchanged |
| `src/memory/*` | Memory/RAG unchanged |
| Full `ARCHITECTURE.md` | Too big, ARCHITECTURE_SUMMARY.md sufficient |
| All test files | Only included Hunyuan-relevant tests |

---

## When Work is Complete

Once HunyuanCustom is working:
1. Archive this project (or keep for maintenance)
2. The code now lives in the regular silos
3. Future Hunyuan bugs → use this project
4. New features → back to silo projects

---

## Quick Start Prompt for This Project

When starting work in this project:

```
You are working on the HunyuanCustom integration for the Continuum Engine.

Key files:
- MODEL_PIVOT.md has the full spec
- hunyuan_custom_renderer.py is the main implementation
- wan_renderer.py is the reference implementation to copy patterns from
- workflows/hunyuan_custom/pass1_img2vid.json is the ComfyUI workflow

Goal: Generate video with native identity preservation (target ArcFace ≥ 0.60)
```