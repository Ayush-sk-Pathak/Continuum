# CONTINUUM ENGINE - SESSION HANDOFF
**Date:** December 19, 2025  
**Session Focus:** Bridge Frame Mechanism Testing  
**Status:** Test In Progress - Awaiting Terminal Results

---

## 🎯 CURRENT OBJECTIVE

**Prove the Bridge Frame mechanism works end-to-end.**

The Bridge Frame is the CORE VALUE PROPOSITION of Continuum (see `ARCHITECTURE_SUMMARY.md` lines 80-148). Without it, we're just another "random clip generator."

### What We're Testing
```
Shot 1 (T2V) → Extract Last Frame → Bridge Frame (SDXL + ControlNet + IP-Adapter) → Shot 2 (I2V)
```

### Success Criteria
Look for this line in terminal output:
```
INFO | Selected bridge method: controlnet_pose   ← SUCCESS
```

**NOT this:**
```
INFO | Selected bridge method: prompt_only   ← FAILURE (fallback)
```

---

## 📊 CURRENT STATE

### What's Working ✅
| Component | Status | Evidence |
|-----------|--------|----------|
| ComfyUI connection | ✅ Working | Jobs submit and complete |
| Wan T2V generation | ✅ Working | Shot 1 generates successfully |
| Wan I2V workflow selection | ✅ Working | `Using I2V models` appears in logs |
| Bridge frame download | ✅ Working | `bridge_engine.py` fix applied |
| Frame extraction (FFmpeg) | ✅ Working | Source frame extracted for bridge |
| Workflow loader | ✅ Working | Templates load with placeholders |

### What's Broken/Pending ❌
| Component | Issue | Fix Status |
|-----------|-------|------------|
| Pose extraction workflow | `DWPreprocessor` node missing on RunPod | **NEEDS INSTALL** |
| Depth extraction workflow | Had `_meta` node causing validation error | ✅ Fixed in files |
| Bridge falls back to `prompt_only` | Due to above issues | Blocked by node install |
| I2V timeout | 14B model exceeds 300s default | Set `TIMEOUT_SEC=600` |
| Audit error | `'dict' object has no attribute 'shot_id'` | Low priority (doesn't block test) |

### Files Changed This Session
| File | Change | Location |
|------|--------|----------|
| `bridge_engine.py` | Fixed job completion handling | `src/studio/` |
| `bridge_pose_extract.json` | Removed `_meta` node, uses `DWPreprocessor` | `workflows/` |
| `bridge_depth_extract.json` | Removed `_meta` node | `workflows/` |
| `bridge_quick_test.json` | Created 1-second shot test project | `tests/` |

---

## 🔧 RUNPOD SETUP REQUIRED

**The pose extraction node is NOT installed on RunPod.** This is blocking the test.

### Install Command (Run on RunPod)
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
pip install -r comfyui_controlnet_aux/requirements.txt
# Then restart ComfyUI or the pod
```

### Models Already Installed on RunPod
| Model | Path | Size |
|-------|------|------|
| SDXL Base 1.0 | `models/checkpoints/sd_xl_base_1.0.safetensors` | ~6.5GB |
| CLIP Vision H | `models/clip_vision/clip_vision_h.safetensors` | ~3.7GB |
| ControlNet OpenPose SDXL | `models/controlnet/controlnet-openpose-sdxl-1.0.safetensors` | 4.7GB |
| IP-Adapter Face SDXL | `models/ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors` | 809MB |
| Wan 2.1 T2V | `models/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors` | - |
| Wan 2.1 I2V | `models/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors` | - |

### RunPod Instance
- **Host:** `wss://oy2xe5owdngtcu-8188.proxy.runpod.net`
- **GPU:** NVIDIA RTX 4090 (24GB VRAM)
- **Path:** `/workspace/runpod-slim/ComfyUI/`

---

## 🧪 TEST COMMAND

```bash
cd ~/Projects/Continuum

# Set environment
export CONTINUUM_COMFYUI__HOST="wss://oy2xe5owdngtcu-8188.proxy.runpod.net"
export CONTINUUM_COMFYUI__TIMEOUT_SEC=600

# Run quick test (1-second shots)
python main.py --project tests/bridge_quick_test.json --no-resume --no-audio --no-post --verbose 2>&1
```

---

## 📋 WHAT TO LOOK FOR IN TERMINAL OUTPUT

### Phase 1: Shot 1 (T2V) - Should Work
```
INFO | Using T2V models (tier=480p)
INFO | Loaded workflow template: pass1_structural
INFO | Job xxx completed successfully
INFO | Render complete: workspace/output/t2v_xxxxx_.mp4
```

### Phase 2: Bridge Frame Generation - THE KEY TEST
**Success:**
```
INFO | Loaded workflow template: bridge_pose_extract
INFO | Pose extraction succeeded   ← LOOK FOR THIS
INFO | Selected bridge method: controlnet_pose   ← THIS IS SUCCESS
INFO | Bridge frame generated via controlnet_pose
```

**Failure (current state before RunPod fix):**
```
WARNING | Pose extraction failed: "Cannot execute because node DWPreprocessor does not exist"
INFO | Selected bridge method: prompt_only   ← FALLBACK, NOT WHAT WE WANT
```

### Phase 3: Shot 2 (I2V) - Should Use Bridge Frame
```
DEBUG | Uploading init frame: .../bridge_xxx.png
DEBUG | Using I2V models (tier=480p)   ← NOT T2V!
INFO | Loaded workflow template: pass1_img2vid   ← NOT pass1_structural!
INFO | Job xxx completed successfully
```

---

## 🗺️ NEXT STEPS (Per ARCHITECTURE_SUMMARY.md)

### Immediate (This Test)
1. ✅ Fix `bridge_engine.py` job handling - DONE
2. ✅ Fix workflow `_meta` validation errors - DONE  
3. ⏳ Install `comfyui_controlnet_aux` on RunPod - PENDING
4. ⏳ Re-run test, verify `controlnet_pose` method used - PENDING
5. ⏳ Verify Shot 2 uses I2V (not T2V) - PENDING

### After Bridge Proven (Phase 1 Complete)
Per `ARCHITECTURE_SUMMARY.md` line 679, priority order is:
```
Bridge Frame > Identity Audit > Director Agent > Sonic Engine
```

**Phase 2: Identity Audit**
- Wire real ArcFace in `identity_checker.py` (currently stubbed)
- Measure similarity scores: Bible → Shot 1 → Bridge → Shot 2
- Target: Bridge frame ≥ 0.93 vs Bible

**Phase 3: Director Agent**
- LLM parses script → Scene Graph JSON automatically
- Currently requires manual JSON creation

**Phase 4: Sonic Engine**
- TTS + Lip Sync + Ambience
- Currently stubbed interfaces

---

## 📁 PROJECT FILE LOCATIONS

### Core Files
```
/src/studio/bridge_engine.py      # Bridge frame generation (FIXED)
/src/studio/pass1_generator.py    # Orchestrates T2V/I2V selection
/src/renderers/wan_renderer.py    # ComfyUI job submission
/src/comfy_client/client.py       # WebSocket client
/src/comfy_client/workflow_loader.py  # JSON template loading
```

### Workflow Files
```
/workflows/bridge_pose_extract.json   # Pose extraction (FIXED)
/workflows/bridge_depth_extract.json  # Depth extraction (FIXED)
/workflows/bridge_full.json           # Full bridge (Pose + Depth + IP-Adapter)
/workflows/bridge_pose_only.json      # Tier 2 bridge (Pose + IP-Adapter)
/workflows/bridge_basic.json          # Tier 4 fallback (BROKEN - don't use)
/workflows/pass1_structural.json      # T2V generation
/workflows/pass1_img2vid.json         # I2V generation
```

### Test Files
```
/tests/bridge_quick_test.json         # 1-second shots (CREATED)
/tests/sample_project_2shot.json      # 4-second shots (original)
```

---

## ⚠️ KNOWN ISSUES (Non-Blocking)

### 1. Audit Error
```
ERROR | Audit error: 'dict' object has no attribute 'shot_id'
```
**Impact:** None - audit runs but fails gracefully, generation continues.  
**Fix:** Low priority, in `pass1_generator.py` `_audit_chunk` method.

### 2. I2V Model Slow
The I2V model is 14B parameters (vs T2V 1.3B). Takes ~15-20 min for 4-second video.
**Mitigation:** Use 1-second shots for testing, extended timeout (600s).

### 3. World State Warnings
```
WARNING | Shot shot_02 not in history, returning current state
```
**Impact:** None - World State is stubbed, warnings are expected.

---

## 🔑 KEY ARCHITECTURE CONCEPTS

### Bridge Frame (Why It Matters)
Without bridge frames, identity drifts:
```
Shot 1: Alice (0.95 match to Bible)
Shot 2: Alice? (0.82 match) ← drift started
Shot 3: Who? (0.71 match) ← drift compounding
Shot 4: Stranger (0.58 match) ← FAIL
```

With bridge frames (re-anchored each cut):
```
Shot 1: Alice (0.95 match)
Bridge: Re-anchor to Bible (0.98 match)
Shot 2: Alice (0.93 match) ← reset!
Bridge: Re-anchor to Bible (0.98 match)
Shot 3: Alice (0.92 match) ← stable!
```

### Degradation Ladder
| Tier | Method | Workflow | Quality |
|------|--------|----------|---------|
| 1 | ControlNet Pose + Depth + IP-Adapter | `bridge_full.json` | Best |
| 2 | ControlNet Pose + IP-Adapter | `bridge_pose_only.json` | Good |
| 3 | IP-Adapter only | `bridge_ipadapter.json` | Acceptable |
| 4 | Prompt only (BROKEN) | `bridge_basic.json` | ❌ Drift |

**Current test targets Tier 2** (Pose + IP-Adapter) since Depth ControlNet not installed.

---

## 📝 SESSION TRANSCRIPT

Full conversation history available at:
```
/mnt/transcripts/2025-12-19-09-14-37-bridge-frame-setup-failed-test.txt
```

---

## ✅ CHECKLIST FOR NEXT SESSION

- [ ] Confirm `comfyui_controlnet_aux` installed on RunPod
- [ ] Run quick test with `bridge_quick_test.json`
- [ ] Verify `Selected bridge method: controlnet_pose` in logs
- [ ] Verify Shot 2 uses `pass1_img2vid` (I2V) not `pass1_structural` (T2V)
- [ ] If success: Proceed to wire real ArcFace identity checker
- [ ] If failure: Debug based on specific error message

---

*Last updated: Dec 19, 2025 03:45 UTC*