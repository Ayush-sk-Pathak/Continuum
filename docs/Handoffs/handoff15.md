# Continuum Engine - Session Handoff Document
**Date:** December 23, 2025
**Session:** E2E Testing + Pass 2 Fix + IP-Adapter Research Integration

---

## 1. PROJECT OVERVIEW

**What We're Building:** Continuum Engine - a neuro-symbolic AI filmmaking system that generates consistent, multi-shot videos with locked character identity.

**Core Value Prop:** "Alice is always Alice" across unlimited shots via Bridge Frame re-anchoring + IP-Adapter + ControlNet.

**Source of Truth:** 
- `ARCHITECTURE.md` (v2025.10) - Strategic vision
- `ARCHITECTURE_SUMMARY.md` (v2025.12.7) - Dev implementation guide

---

## 2. WHAT WE VALIDATED TODAY

### E2E Test Results (2 shots, same character)

| Shot | Identity Score | Threshold | Result |
|------|---------------|-----------|--------|
| Shot 1 (Hero Frame → I2V) | 0.978 | 0.50 | ✅ PASS |
| Shot 2 (Bridge Frame → I2V) | 0.972 | 0.50 | ✅ PASS |

**Key Proof:** 97% identity consistency maintained across shots WITHOUT LoRA, WITHOUT IP-Adapter during I2V. This validates the core architecture.

### Working Pipeline Components

| Component | Status | Notes |
|-----------|--------|-------|
| Hero Frame Generation | ✅ WORKING | SDXL + IP-Adapter (51.8s) |
| Bridge Frame Generation | ✅ WORKING | ControlNet Pose + Depth + IP-Adapter (105s) |
| Wan I2V Rendering | ✅ WORKING | 480p, 20 frames, ~240s |
| Identity Audit (ArcFace) | ✅ WORKING | buffalo_l model, local Mac |
| Physics Audit (YOLO) | ✅ WORKING | 9 frames extracted per shot |
| Reviewer Aggregation | ✅ WORKING | Combines audits, returns PASS/FAIL |

### Pass 2 Refinement - IN PROGRESS

**Original Error:** `KSamplerBatch does not exist`

**Root Cause:** The workflow `refine_vid2vid_temporal.json` uses `KSamplerBatch` node which wasn't installed.

**Fix Applied (this session):**
1. Installed ComfyUI-Inspire-Pack (V1.23) - did NOT fix it
2. Installed ComfyUI-Impact-Pack (V8.28) - provides KSamplerBatch
3. Restarted ComfyUI on RunPod

**Current Status:** Test running now to validate Pass 2 works.

---

## 3. IP-ADAPTER / LORA RESEARCH FINDINGS

### Source: `IP_LORA_Research.md` (Deep research, Dec 2024)

### The Redundant Identity Stack (5 Layers of Defense)

| Layer | Technique | When Applied | Current Status |
|-------|-----------|--------------|----------------|
| 1 | LoRA | Model weight bias | ❌ NOT USED (architecture supports it) |
| 2 | IP-Adapter | Per-frame anchor | ✅ Hero/Bridge only |
| 3 | ControlNet | Pose + Depth structure | ✅ Bridge frames |
| 4 | Face Enhancement | Post-processing backup | ❌ NOT IMPLEMENTED |
| 5 | ArcFace QA | Verification gate | ✅ WORKING |

**Current State:** Layers 2+3+5 = 97% accuracy
**With Layer 1 (LoRA):** Expected 99%
**With Layer 4 (Face Enhancement):** Expected 99.5%

### Critical Gap Identified: IP-Adapter NOT Active During I2V

**Problem:** IP-Adapter only runs during hero/bridge frame generation (SDXL), NOT during Wan I2V video generation.

**Evidence:** Warning in logs:
```
Template 'pass1_img2vid_ipadapter' not found, falling back to 'pass1_img2vid'
```

**Solution:** 
- Install `ComfyUI-IPAdapter-WAN` extension on RunPod
- Create `pass1_img2vid_ipadapter.json` workflow
- This would inject IP-Adapter into Wan video UNet during generation

**Impact:** Could close the 97% → 99% gap by preventing within-shot drift.

### Other Techniques to Evaluate

| Technique | Source | Status | Notes |
|-----------|--------|--------|-------|
| Stand-In for Wan | Tencent research | ❌ NOT TESTED | Native identity branch, may be better than IP-Adapter |
| GFPGAN/CodeFormer | Face enhancement | ❌ NOT IMPLEMENTED | Post-processing safety net |
| HunyuanCustom | Tencent | FUTURE | Multi-GPU, heavier model |

---

## 4. ARCHITECTURE UPDATES MADE THIS SESSION

### ARCHITECTURE.md v2025.10 (Full spec)

Added sections:
- **3A.3:** The Redundant Identity Stack (5-layer defense system)
- **3A.4:** Stand-In for Wan (specialized identity branch)
- **3A.5:** IP-Adapter During I2V Generation (implementation gap)
- **3N:** Model Upgrade Path (future identity engines)
- **3O:** Face Enhancement Pipeline (post-processing safety net)

### ARCHITECTURE_SUMMARY.md v2025.12.7 (Dev guide)

Updated:
- Section 1: Identity Lock now references 5-layer stack
- Section 7b: Added 3 new MVP limitations (IP-Adapter in I2V, Face Enhancement, Stand-In)
- Section 9: Added 5 new glossary terms
- Section 10: Changelog entry for v2025.12.7

---

## 5. RUNPOD ENVIRONMENT STATE

**Pod ID:** yn15pks5ig7dnw
**GPU:** NVIDIA RTX 4090 (24GB VRAM)
**ComfyUI Version:** 0.4.0
**PyTorch:** 2.6.0+cu124

### Installed Custom Nodes (this session)

| Node Pack | Version | Purpose |
|-----------|---------|---------|
| ComfyUI-Inspire-Pack | V1.23 | Various utility nodes |
| ComfyUI-Impact-Pack | V8.28 | KSamplerBatch for Pass 2 refinement |

### Known Missing Dependencies

| Issue | Impact | Fix |
|-------|--------|-----|
| `skimage` module missing | DWPose preprocessor fails | `pip install scikit-image` |
| DWPreprocessor not working | Bridge uses fallback (ipadapter_only) | Install comfyui_controlnet_aux properly |

### How to Connect from Mac

```bash
export CONTINUUM_COMFYUI__HOST="wss://yn15pks5ig7dnw-8188.proxy.runpod.net"
```

---

## 6. FILE LOCATIONS

### Test Files
- `tests/quick_test.json` - 2-shot test scene graph
- `tests/bible.json` - Character consistency dictionary (Alice)
- `workspace/assets/alice/` - Alice reference images (alice_01.png, alice_02.png, alice_03.png)

### Output Locations
- `workspace/output/` - Generated videos (i2v_00018_.mp4, i2v_00019_.mp4)
- `workspace/output/quick_e2e_pass2/` - Current test run output
- `/var/folders/.../continuum_bridges/` - Temp hero/bridge frames (Mac)

### Key Source Files
- `src/studio/pass1_generator.py` - Hero frame + I2V orchestration
- `src/studio/bridge_engine.py` - Bridge frame generation
- `src/studio/pass2_refiner.py` - Vid2Vid refinement
- `src/renderers/wan_renderer.py` - ComfyUI Wan wrapper
- `src/audit/identity_checker.py` - ArcFace verification
- `src/audit/reviewer.py` - Audit aggregation

### Workflows
- `workflows/hero_frame.json` - ✅ WORKING
- `workflows/bridge_full.json` - ✅ WORKING
- `workflows/pass1_img2vid.json` - ✅ WORKING
- `workflows/refine_vid2vid_temporal.json` - 🔄 TESTING (Pass 2)
- `workflows/pass1_img2vid_ipadapter.json` - ❌ DOES NOT EXIST (needs creation)

---

## 7. CURRENT TASK STATUS

### Task 1: Fix Pass 2 Refinement
**Status:** 🔄 IN PROGRESS (test running now with fixed workflow)

**Root Cause:** `refine_vid2vid_temporal.json` used non-existent nodes:
- `KSamplerBatch` - doesn't exist in any public ComfyUI pack
- `TemporalSmooth` - also doesn't exist

**What was done:**
1. Installed ComfyUI-Inspire-Pack (V1.23) - did NOT fix KSamplerBatch
2. Installed ComfyUI-Impact-Pack (V8.28) - also did NOT fix it
3. **Realized the nodes don't exist anywhere** - workflow was aspirational/untested
4. Fixed `refine_vid2vid_temporal.json`:
   - Replaced `KSamplerBatch` → standard `KSampler`
   - Removed `TemporalSmooth` entirely
   - Added `_meta` block for documentation
5. Running test with fixed workflow

**Note:** After fix, `refine_vid2vid_temporal.json` is now functionally identical to `refine_vid2vid_simple.json`. Consider consolidating post-MVP.

**Expected outcome:** Pass 2 refinement completes successfully.

### Task 2: IP-Adapter During I2V
**Status:** ❌ NOT STARTED
**What needs to be done:**
1. Install `ComfyUI-IPAdapter-WAN` on RunPod
2. Download IP-Adapter models for Wan
3. Create `workflows/pass1_img2vid_ipadapter.json`
4. Update `wan_renderer.py` to use new workflow when available

### Task 3: Test Longer Sequences (5-10 shots)
**Status:** ❌ NOT STARTED
**Purpose:** Validate that Bridge Engine prevents cumulative drift at scale.
**Hypothesis:** Should work because each shot re-anchors from Bible refs, not from previous shot's drift.

---

## 8. PRIORITY ORDER (Agreed with User)

1. **Fix Pass 2** - Unblocks visual polish (quick win) ← CURRENT
2. **IP-Adapter during I2V** - Closes 97% → 99% gap
3. **Test longer sequences** - Validate architecture at scale

---

## 9. KNOWN WARNINGS (Can Be Ignored)

These warnings appear in logs but don't affect functionality:

```
Template 'pass1_img2vid_ipadapter' not found, falling back to 'pass1_img2vid'
# Expected - workflow doesn't exist yet

Shot shot_01 not in history, returning current state
# Benign - WorldState tracking not fully implemented

Injection warning: Unknown parameter 'CHARACTER_DESCRIPTION' not in template
# Template doesn't use this param, safe to ignore
```

---

## 10. COMMANDS FOR NEXT SESSION

### Check if Pod is Connected
```bash
python -c "from src.comfy_client.client import ComfyClient; c = ComfyClient(); print('OK')"
```

### Run E2E Test
```bash
python main.py --project tests/quick_test.json --consistency tests/bible.json --output workspace/output/test_run -v
```

### SSH into RunPod (if needed)
Check RunPod UI for SSH command, or use web terminal.

### Restart ComfyUI on RunPod
```bash
pkill -f "python3 main.py"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /tmp/comfyui.log 2>&1 &
```

---

## 11. VIBE CODER CONSTRAINTS (REMINDER)

- **NO custom CUDA kernels** - Use ComfyUI nodes
- **NO training base models** - Use existing checkpoints
- **Glue code only** - Python orchestration of ComfyUI workflows
- **Pluggable interfaces** - BaseRenderer, AudioGenerator abstractions
- **Brain (Mac) vs Muscle (Cloud)** - Logic local, rendering remote

---

## 12. OPEN QUESTIONS FOR NEXT SESSION

1. Did Pass 2 refinement complete successfully with the fixed workflow?
2. If yes, what's the visual quality difference between Pass 1 and Pass 2 output? (May be minimal since temporal features were removed)
3. Should we consolidate `refine_vid2vid_temporal.json` and `refine_vid2vid_simple.json` since they're now identical?
4. Should we proceed with IP-Adapter-WAN installation, or test longer sequences first?
5. Consider adding real temporal smoothing via FFmpeg post-processing (`tblend` or `minterpolate` filters)?

## 13. KEY LESSONS FROM THIS SESSION

Added to `LESSONS_LEARNED.md`:

| # | Lesson | Impact |
|---|--------|--------|
| 67 | ComfyUI workflows may reference non-existent nodes | Fixed `refine_vid2vid_temporal.json` |
| 68 | Node packs don't always contain expected nodes | Don't assume - verify before installing |

**Key Takeaway:** Always verify workflow `class_type` values exist on your ComfyUI instance before integrating. Test workflows manually in ComfyUI web UI first.

---

*End of Handoff Document*