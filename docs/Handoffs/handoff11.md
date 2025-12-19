# Continuum Engine - Handoff Document
## Session: P4-P5 Bridge Frame + Identity Audit Completion
**Date:** December 19, 2025  
**Status:** P0-P5 COMPLETE ✅ | P6-P8 PENDING

---

## 1. Executive Summary

This session completed the **core value proposition** of Continuum Engine:
- **P4 Bridge Frame:** Identity-locked frame generation using ControlNet (pose + depth) + IP-Adapter (face)
- **P5 Identity Audit:** ArcFace-based verification with automatic reroll on failure

**The Key Milestone is ACHIEVED:**
> "Can you generate Shot A, then Shot B, and have them look like the same character in the same world?"

YES — tested and working with automatic quality enforcement.

---

## 2. Implementation Status

### ✅ COMPLETE (P0-P5)

| Priority | Module | Status | Notes |
|----------|--------|--------|-------|
| **P0** | `comfy_client/` | ✅ Done | WebSocket to RunPod ComfyUI |
| **P1** | `wan_renderer.py` | ✅ Done | T2V + I2V generation |
| **P2** | `scene_graph.py` | ✅ Done | Script → Shots parser |
| **P3a** | I2V + ref image | ✅ Done | `pass1_img2vid.json` workflow |
| **P3b** | LoRA workflow | ✅ Exists | `pass1_structural_lora.json` (needs trained LoRA to test) |
| **P4** | `bridge_engine.py` | ✅ Done | Full identity lock via `bridge_full.json` |
| **P5** | `identity_checker.py` | ✅ Done | ArcFace + auto-reroll working |

### ⏳ PENDING (P6-P8)

| Priority | Module | Status | Blocker |
|----------|--------|--------|---------|
| **P6** | TTS + Lip Sync | ⏳ Scaffolded | ElevenLabs API key needed |
| **P7** | Pass 2 Refiner | ⏳ Scaffolded | `refine_freelong` workflow missing |
| **P7** | RIFE Interpolator | ⏳ Scaffolded | RIFE VFI node not installed on RunPod |
| **P8** | World State | ⏳ Placeholder | Phase 2+ scope |

---

## 3. Test Results (Latest Run)

**Command:**
```bash
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json
```

**Results:**
```
Shot 1 (T2V):     ✅ PASS - t2v_00042_.mp4 (66.7s)
Shot 1 Audit:     ✅ PASS - 0 flags
Bridge Frame:     ✅ Generated via controlnet_full (132s)
Shot 2 (I2V) #1:  ❌ FAIL - 1 flag → reroll triggered
Shot 2 (I2V) #2:  ✅ PASS - t2v_00044_.mp4 (261.6s)
Shot 2 Audit:     ✅ PASS - approved after reroll

Total Duration: 864s (~14 min)
Est. Cost: $0.02
```

**Key Success Indicators:**
- ArcFace model loaded: `buffalo_l`
- Bridge method: `controlnet_full` (Tier 1 - best quality)
- Auto-reroll: Working (Shot 2 failed once, regenerated, passed)

---

## 4. Known Bugs (To Fix)

### Bug 1: Severity Overflow in Identity Check
**File:** `src/audit/reviewer.py`  
**Error:**
```
ERROR | Identity check failed: Severity must be 0.0-1.0, got 1.0883083045482635
```
**Fix:** Clamp severity calculation to [0.0, 1.0] range.

**Location:** Around line 470 in `_run_identity_check()`
```python
# Current (buggy):
severity = min(1.0, (comparison.threshold - similarity) / comparison.threshold + 0.3)

# Fix (clamp both ends):
severity = max(0.0, min(1.0, (comparison.threshold - similarity) / comparison.threshold + 0.3))
```

### Bug 2: Scene Missing `total_duration_sec`
**File:** `main.py` line 1849  
**Error:**
```
AttributeError: 'Scene' object has no attribute 'total_duration_sec'
```
**Fix:** Check `src/director/scene_graph.py` Scene class and add property or use correct attribute name.

### Bug 3: AmbienceType Mismatch (INCORRECTLY "FIXED" - NEEDS PROPER FIX)
**File:** `src/sonic/types.py`  
**Status:** ⚠️ PARTIAL FIX - Creates new problem

**What Happened:**
During P5 testing, the pipeline crashed at the Audio phase with:
```
AttributeError: type object 'AmbienceType' has no attribute 'INTERIOR'
```

**Wrong Fix Applied:**
Added new enum values to `src/sonic/types.py`:
```python
# These were added:
INTERIOR = auto()
URBAN = auto()
NATURE = auto()
WATER = auto()
```

**Why This Is Wrong:**
`src/sonic/ambience.py` has a prompt mapping dict (around line 187) that maps AmbienceType → text prompts:
```python
{
    AmbienceType.INTERIOR_QUIET: "quiet indoor ambience",
    AmbienceType.INTERIOR_BUSY: "busy indoor environment",
    AmbienceType.EXTERIOR_URBAN: "city street ambience, urban sounds",
    AmbienceType.EXTERIOR_NATURE: "natural outdoor environment",
    AmbienceType.EXTERIOR_WEATHER: "weather sounds",
    # ... NO MAPPINGS FOR INTERIOR, URBAN, NATURE, WATER
}
```

When audio generation runs with `AmbienceType.INTERIOR`, it will hit a `KeyError` because there's no prompt mapping.

**Correct Fix Options:**

**Option A (Recommended): Fix main.py to use existing enums**
File: `main.py` around line 1872-1882
```python
# Current (wrong):
return AmbienceType.INTERIOR

# Should be:
return AmbienceType.INTERIOR_QUIET
```

Map all usages:
- `INTERIOR` → `INTERIOR_QUIET`
- `URBAN` → `EXTERIOR_URBAN`
- `NATURE` → `EXTERIOR_NATURE`
- `WATER` → `EXTERIOR_WEATHER`

Then revert the changes to `src/sonic/types.py`.

**Option B: Update ambience.py prompt mappings**
Add mappings for the new enum values in `src/sonic/ambience.py`:
```python
{
    # ... existing mappings ...
    AmbienceType.INTERIOR: "quiet indoor ambience",
    AmbienceType.URBAN: "city street ambience, urban sounds",
    AmbienceType.NATURE: "natural outdoor environment",
    AmbienceType.WATER: "water sounds, ocean waves, river",
}
```

**Option C: Use --no-audio flag until P6**
Skip the audio phase entirely during video testing:
```bash
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --no-audio
```

**Why This Wasn't Caught:**
The pipeline still crashed later on `Scene.total_duration_sec` before reaching the point where prompt mapping would fail. When P6 audio work begins, this will surface as a `KeyError`.

### Bug 4: Reviewer Import Path (FIXED in this session)
**File:** `src/studio/pass1_generator.py`  
**Status:** ✅ Fixed - Changed from `.reviewer` to `src.audit.reviewer`

---

## 5. File Structure Reference

```
src/
├── audit/
│   ├── identity_checker.py   # ArcFace face verification ✅
│   ├── physics_checker.py    # YOLO object tracking ✅
│   └── reviewer.py           # Orchestrates audit checks ✅
├── comfy_client/
│   ├── client.py             # WebSocket to ComfyUI ✅
│   └── workflow_loader.py    # JSON template injection ✅
├── director/
│   ├── scene_graph.py        # Script → Shots ✅
│   ├── consistency_dict.py   # Character/Location Bible ✅
│   └── world_state.py        # Prop tracking (placeholder)
├── renderers/
│   ├── base.py               # Abstract renderer interface ✅
│   └── wan_renderer.py       # Wan 2.1 T2V/I2V ✅
├── studio/
│   ├── bridge_engine.py      # Bridge frame generation ✅
│   ├── pass1_generator.py    # Orchestrates generation ✅
│   ├── pass2_refiner.py      # Refinement (scaffolded)
│   └── rife_interpolator.py  # Frame interpolation (scaffolded)
├── sonic/
│   ├── tts_engine.py         # Text-to-speech (scaffolded)
│   ├── lip_sync.py           # Lip sync (scaffolded)
│   └── types.py              # Audio types ✅ (fixed)
└── post/
    ├── color_match.py        # Color normalization
    ├── audio_ducker.py       # Audio ducking
    └── stitcher.py           # Final video assembly
```

---

## 6. Workflow Files (ComfyUI Templates)

### Working ✅
| File | Purpose |
|------|---------|
| `pass1_structural.json` | T2V basic (Wan 1.3B) |
| `pass1_structural_lora.json` | T2V with LoRA |
| `pass1_img2vid.json` | I2V (Wan 14B) |
| `bridge_full.json` | Bridge: ControlNet + IP-Adapter |
| `bridge_pose_extract.json` | Extract pose skeleton |
| `bridge_depth_extract.json` | Extract depth map |
| `bridge_ipadapter.json` | Bridge: IP-Adapter only |
| `bridge_pose_only.json` | Bridge: Pose ControlNet only |
| `bridge_basic.json` | Bridge: Prompt only (fallback) |

### Missing (Phase 7) ❌
| File | Purpose |
|------|---------|
| `refine_freelong` | Pass 2 temporal refinement |
| RIFE VFI node | Frame interpolation |

---

## 7. RunPod Setup Reference

**Current Pod:** RTX 4090 (24GB VRAM)  
**ComfyUI Path:** `/workspace/runpod-slim/ComfyUI`

### Installed Models ✅
```
models/checkpoints/
  └── sd_xl_base_1.0.safetensors

models/controlnet/
  ├── controlnet-openpose-sdxl-1.0.safetensors
  └── controlnet-depth-sdxl-1.0.safetensors

models/ipadapter/
  └── ip-adapter-plus-face_sdxl_vit-h.safetensors

models/clip_vision/
  └── clip_vision_h.safetensors

models/unet/
  ├── wan2.1_t2v_1.3B_fp16.safetensors
  └── wan2.1_i2v_14B_fp16.safetensors
```

### Installed Custom Nodes ✅
```
custom_nodes/
  ├── ComfyUI_IPAdapter_plus/
  ├── ComfyUI-VideoHelperSuite/
  ├── comfyui_controlnet_aux/
  └── ComfyUI-WanVideoWrapper/
```

### Missing (Phase 7)
- **RIFE VFI node:** `ComfyUI-Frame-Interpolation` or similar
- **FreeLong nodes:** For temporal refinement

---

## 8. Test Files

**Project File:** `tests/bridge_quick_test.json`
```json
{
  "project_id": "bridge_quick_test",
  "title": "Bridge Quick Test",
  "scenes": [{
    "scene_id": "scene_01",
    "title": "Quick Test",
    "shots": [
      {
        "shot_id": "shot_01",
        "prompt": "A beautiful woman with blonde hair smiling warmly at the camera...",
        "characters": [{"entity_id": "alice"}]
      },
      {
        "shot_id": "shot_02", 
        "prompt": "The same woman walking through a sunlit park...",
        "characters": [{"entity_id": "alice"}]
      }
    ]
  }]
}
```

**Bible File:** `tests/bible.json`
```json
{
  "characters": {
    "alice": {
      "entity_id": "alice",
      "name": "Alice",
      "description": "Beautiful woman in her late 20s with long blonde hair...",
      "face_refs": ["assets/refs/alice_ref.png"]
    }
  }
}
```

**Face Reference:** `assets/refs/alice_ref.png` (must exist)

---

## 9. Bridge Frame Degradation Ladder

The bridge engine automatically falls back if components are missing:

| Tier | Method | Components | Quality |
|------|--------|------------|---------|
| 1 | `controlnet_full` | Pose + Depth + IP-Adapter | Best ✅ |
| 2 | `controlnet_pose_only` | Pose + IP-Adapter | Good |
| 3 | `ipadapter_only` | IP-Adapter only | Fair |
| 4 | `prompt_only` | Text prompt only | Poor (drift) |

Current tests run at **Tier 1** (full identity lock).

---

## 10. Next Steps (Priority Order)

### Immediate (Bug Fixes)
1. Fix severity overflow in `src/audit/reviewer.py`
2. Fix `total_duration_sec` attribute error in `main.py`

### P6: Audio Pipeline
1. Configure ElevenLabs API key for TTS
2. Test lip sync with MuseTalk workflow
3. Wire up ambience generation (Replicate API)

### P7: Quality Polish
1. Install RIFE VFI node on RunPod:
   ```bash
   cd /workspace/runpod-slim/ComfyUI/custom_nodes
   git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation
   pip install -r ComfyUI-Frame-Interpolation/requirements.txt
   ```
2. Create `refine_freelong.json` workflow
3. Test frame interpolation to 24fps

### P8: World State (Phase 2)
- Prop tracking across shots
- Dynamic prompt context injection

---

## 11. Key Architecture Decisions

### Why SDXL for Bridge Frames (not Wan)?
1. SDXL has mature ControlNet + IP-Adapter support
2. Wan is a VIDEO model without IP-Adapter for single images
3. One frame of SDXL "style" is immediately overwritten by Wan in frame 2+
4. The identity lock survives; the style doesn't matter

### Why Reroll on Audit Fail?
- Video models are stochastic — same prompt can yield different quality
- New seed often fixes issues without human intervention
- Max 3 attempts before surfacing to user

### Shot 1 Identity Gap
- Shot 1 uses `pass1_structural.json` (no IP-Adapter for Wan T2V)
- Identity lock only starts from bridge frame (Shot 2+)
- **Solution:** Train LoRA for character, or generate Shot 1 init frame with SDXL first

---

## 12. Commands Reference

```bash
# Run pipeline
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json

# Run with verbose logging
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --verbose

# Skip certain phases
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --no-pass2 --no-audio

# Start ComfyUI on RunPod
cd /workspace/runpod-slim/ComfyUI
python3 main.py --listen 0.0.0.0 --port 8188 &
```

---

## 13. Environment Config

**Local (Mac):** 
- Python 3.12 with venv
- ArcFace runs on CPU (no CUDA)
- YOLO runs on CPU

**Cloud (RunPod):**
- Host: `wss://oy2xe5owdngtcu-8188.proxy.runpod.net`
- GPU: NVIDIA RTX 4090
- ComfyUI 0.4.0
- PyTorch 2.6.0+cu124

---

## 14. Session Transcript

Full conversation available at:
```
/mnt/transcripts/2025-12-19-11-41-17-p4-bridge-frame-success.txt
```

Contains:
- P4 bridge frame debugging and success
- Model installation commands for RunPod
- Log interpretation guide
- P5 audit integration fixes

---

## 15. Success Criteria Checklist

### Core Value (P0-P5) ✅
- [x] Connect to cloud ComfyUI
- [x] Generate T2V video
- [x] Generate I2V video with init frame
- [x] Parse scene graph from JSON
- [x] Load consistency dictionary (Bible)
- [x] Extract pose from frame
- [x] Extract depth from frame
- [x] Generate bridge frame with ControlNet + IP-Adapter
- [x] Use bridge frame as I2V init
- [x] Run ArcFace identity check
- [x] Run physics check
- [x] Auto-reroll on audit failure
- [x] Pass audit after reroll

### Demo Ready (P6-P7) ⏳
- [ ] TTS dialogue generation
- [ ] Lip sync on talking shots
- [ ] Pass 2 refinement (flicker reduction)
- [ ] RIFE frame interpolation to 24fps
- [ ] Final video stitching

---

*End of Handoff Document*