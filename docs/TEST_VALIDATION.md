# Continuum Engine - Test Validation Log

**Purpose:** Track validation tests in dependency order to pinpoint failures at the earliest layer.  
**Source of Truth:** ARCHITECTURE_SUMMARY.md Section 5 (Implementation Priority)

---

## Test Philosophy

Tests are ordered by **dependency** — each layer must pass before testing the next.
If Layer N fails, all layers > N are blocked.

```
P0 → P1 → P2 → P3a → P4 → P5 → P6 → P7 → P8
 │    │    │    │     │    │    │    │    │
 │    │    │    │     │    │    │    │    └── World State (dynamic props)
 │    │    │    │     │    │    │    └── Quality Pass (Pass2 + RIFE)
 │    │    │    │     │    │    └── Audio (TTS + LipSync)
 │    │    │    │     │    └── Identity Verification (ArcFace)
 │    │    │    │     └── BRIDGE ENGINE (CORE VALUE) ⭐
 │    │    │    └── I2V + Identity Lock (Tier 1)
 │    │    └── Scene Graph (script parsing)
 │    └── Single Shot Generation (Pass 1)
 └── ComfyUI Connection (cloud)
```

**Key Milestone:** P0 → P1 → P3a → P4 → P5 = "Alice stays Alice across cuts"

---

## Status Legend
- ✅ PASS — Works as expected
- ❌ FAIL — Broken, needs fix  
- 🔧 FIXED — Was broken, now fixed
- ⏳ PENDING — Not yet tested
- 🔄 IN PROGRESS — Currently testing

---

## P0: ComfyUI Connection (Cloud Infrastructure)

**Dependency:** None (Foundation layer)  
**Blocks:** Everything else

| Test | Status | Date | Command/Evidence |
|------|--------|------|------------------|
| HTTP connectivity | ✅ PASS | 2024-12-17 | `curl /system_stats` → 200 OK |
| GPU detected | ✅ PASS | 2024-12-17 | RTX 4090, 24GB VRAM |
| Models accessible | ✅ PASS | 2024-12-17 | All .safetensors found |
| Job submission (POST /prompt) | ✅ PASS | 2024-12-17 | Returns prompt_id |
| Job polling (GET /history) | ✅ PASS | 2024-12-17 | Returns status + outputs |
| Output download (GET /view) | ✅ PASS | 2024-12-17 | Video file retrieved |

**Environment:**
```
Pod ID: ej1785v8efhkd4
URL: https://ej1785v8efhkd4-8188.proxy.runpod.net
GPU: RTX 4090 (24GB)
ComfyUI: 0.4.0
PyTorch: 2.6.0+cu124
```

---

## P1: Single Shot Generation (Pass 1 - T2V)

**Dependency:** P0  
**Blocks:** P3a, P4

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Workflow loads (pass1_structural.json) | ✅ PASS | 2024-12-17 | No node_errors |
| Parameter injection | ✅ PASS | 2024-12-17 | All {{PLACEHOLDERS}} replaced |
| Generation completes | ✅ PASS | 2024-12-17 | `t2v_00001_.mp4` |
| Video playable | ✅ PASS | 2024-12-17 | 49 frames, motion OK |

**Workflow Template Issues Found:**
| Issue | Status | Fix |
|-------|--------|-----|
| Uses `PROMPT` but should be `POSITIVE_PROMPT` | 🔧 FIXED | Updated test script |

---

## P2: Scene Graph (Script Parsing)

**Dependency:** None (can test in isolation)  
**Blocks:** Full pipeline orchestration

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Script → SceneGraph parsing | ⏳ PENDING | | |
| Shot segmentation | ⏳ PENDING | | |
| Chunk duration enforcement (≤12s) | ⏳ PENDING | | |
| Pacer integration | ⏳ PENDING | | |

**Note:** P2 can be tested in parallel with P1/P3a since it's CPU-only logic.

---

## P3a: I2V + Identity Lock (Tier 1 - Instant)

**Dependency:** P0, P1  
**Blocks:** P4 (Bridge), P5 (Identity Verification)

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Workflow loads (pass1_img2vid.json) | ✅ PASS | 2024-12-17 | After fixes |
| Reference image loads | ✅ PASS | 2024-12-17 | WhatsApp image found |
| Parameter injection | 🔧 FIXED | 2024-12-17 | See fixes below |
| Generation completes | ✅ PASS | 2024-12-17 | `i2v_00001_.mp4` |
| Identity preserved (visual) | 🔄 IN PROGRESS | 2024-12-17 | Testing with correct prompt |
| Identity preserved (ArcFace > 0.70) | ⏳ PENDING | | |

**Workflow Template Issues Found:**
| Issue | Root Cause | Fix | Status |
|-------|------------|-----|--------|
| Missing `batch_size` | WanImageToVideo requires it | Added `batch_size: 1` | 🔧 FIXED |
| Wrong param `image` | Should be `start_image` | Renamed in workflow | 🔧 FIXED |

**Test Files:**
- `tests/test_i2v_identity.py` — Submits I2V job with reference image

---

## P3b: LoRA Integration (Tier 2 - Enhanced)

**Dependency:** P3a  
**Priority:** Lower (Tier 1 sufficient for MVP)

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Workflow loads (pass1_img2vid_lora.json) | ⏳ PENDING | | |
| LoRA injection | ⏳ PENDING | | |
| Quality improvement vs Tier 1 | ⏳ PENDING | | |

---

## P4: Bridge Engine (CORE VALUE) ⭐

**Dependency:** P3a  
**Blocks:** P5, Full Pipeline
**THIS IS THE KEY DIFFERENTIATOR**

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Extract last frame from Shot A | ⏳ PENDING | | |
| bridge_basic.json loads | ⏳ PENDING | | |
| Bridge frame generation | ⏳ PENDING | | |
| Shot B starts from bridge | ⏳ PENDING | | |
| Visual continuity (no jarring cut) | ⏳ PENDING | | |

**Multi-Shot Sequence Test:**
```
Shot A: "A woman sits at a table, smiling" (I2V from ref)
         ↓ extract last frame
Bridge:  Generate transition frame
         ↓ feed as init
Shot B: "The woman stands up and walks away" (I2V from bridge)
```

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| 2-shot sequence generates | ⏳ PENDING | | |
| Same person in both shots | ⏳ PENDING | | ArcFace similarity |
| Same environment | ⏳ PENDING | | |

---

## P5: Identity Verification (ArcFace)

**Dependency:** P4  
**Blocks:** Automated QA loop

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| ArcFace model loads | ⏳ PENDING | | |
| Face detection in video | ⏳ PENDING | | |
| Similarity computation | ⏳ PENDING | | |
| Threshold check (> 0.70) | ⏳ PENDING | | |
| Auto re-roll on FAIL | ⏳ PENDING | | |

**Acceptance Criteria:**
- Same reference → Same character across shots
- ArcFace similarity > 0.70 between Shot A and Shot B faces

---

## P6: Audio Pipeline (TTS + LipSync)

**Dependency:** P1 (video exists to sync to)  
**Can test in parallel with P4/P5**

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| TTS generates audio (ElevenLabs/OpenAI) | ⏳ PENDING | | |
| musetalk_lipsync.json loads | ⏳ PENDING | | |
| Lip sync generation | ⏳ PENDING | | |
| Audio/video alignment | ⏳ PENDING | | |

---

## P7: Quality Pass (Pass 2 + RIFE)

**Dependency:** P1 (raw video exists)  
**Can test in parallel with P4/P5**

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| refine_vid2vid_simple.json loads | ⏳ PENDING | | |
| Vid2Vid refinement | ⏳ PENDING | | |
| rife_interpolation.json loads | ⏳ PENDING | | |
| 12fps → 24fps upscaling | ⏳ PENDING | | |
| Flicker reduction | ⏳ PENDING | | |

---

## P8: World State (Dynamic Props)

**Dependency:** P2, P4  
**Priority:** Phase 2+

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| Object tracking across shots | ⏳ PENDING | | |
| State mutations persist | ⏳ PENDING | | |
| Physics consistency (YOLO) | ⏳ PENDING | | |

---

## Full Pipeline Integration

**Dependency:** All above

| Test | Status | Date | Evidence |
|------|--------|------|----------|
| main.py dry-run (mocked) | ✅ PASS | 2024-12-17 | 115 unit tests pass |
| main.py with real GPU - single shot | ⏳ PENDING | | |
| main.py with real GPU - multi shot | ⏳ PENDING | | |
| Post-production (color match) | ⏳ PENDING | | |
| Post-production (audio duck) | ⏳ PENDING | | |
| Final stitch (FFmpeg) | ⏳ PENDING | | |

---

## Issues & Fixes Log

| Date | Priority | Issue | Root Cause | Fix | Verified |
|------|----------|-------|------------|-----|----------|
| 2024-12-17 | P3a | I2V missing batch_size | Workflow template incomplete | Added `batch_size: 1` to wan_i2v | ✅ |
| 2024-12-17 | P3a | I2V wrong param name | Node expects `start_image` not `image` | Renamed in workflow JSON | ✅ |
| 2024-12-17 | P1 | T2V prompt not injected | Test used `PROMPT`, workflow uses `POSITIVE_PROMPT` | Fixed test script | ✅ |

---

## Next Actions (Priority Order)

1. **[NOW]** Complete P3a I2V identity test with corrected "woman" prompt
2. **[NEXT]** P4 Bridge test — Extract frame from I2V output, generate Shot B
3. **[THEN]** P5 ArcFace — Measure similarity between Shot A and Shot B faces
4. **[PARALLEL]** P6/P7 — Can test audio and refinement once any video exists

---

## Test Commands Reference

```bash
# P0: Test connection
curl "https://ej1785v8efhkd4-8188.proxy.runpod.net/system_stats"

# P1: Submit T2V job
python tests/test_comfy_api_injected.py

# P3a: Submit I2V job
python tests/test_i2v_identity.py

# Check job status
curl -s "https://ej1785v8efhkd4-8188.proxy.runpod.net/history/{prompt_id}" | python -m json.tool

# Download output
curl -o output.mp4 "https://ej1785v8efhkd4-8188.proxy.runpod.net/view?filename={file}&subfolder=continuum&type=output"
```

---

*Last Updated: 2024-12-17*