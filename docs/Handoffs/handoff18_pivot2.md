# Handoff Document: HunyuanCustom Identity Debugging
**Date:** 2026-01-02 (Session ended ~5:00 AM)
**Status:** Shot 1 FIXED, Shot 2+ BROKEN (architectural issue discovered)

---

## Executive Summary

We fixed HunyuanCustom identity preservation for **Shot 1** by setting `noise_aug_strength=0` and ensuring 25+ frames. However, **Shot 2+ fails** due to an architectural mismatch: the workflow now uses ONE image for both identity AND init latent, but multi-shot needs DIFFERENT images (face ref for identity, bridge frame for continuity).

---

## What Was Accomplished

### 1. Root Cause Identified for Shot 1 Identity Failure

**Problem:** Identity scores were 0.10-0.38 (threshold 0.50)

**Root Cause:** Two issues combined:
- `NOISE_AUG_STRENGTH: 0.025` in workflow defaults (should be `0`)
- Only 13 frames generated (need 25+ for motion with noise_aug=0)

**Fix Applied:**
```json
// workflows/hunyuan_custom/pass1_img2vid.json
"_defaults": {
  "NOISE_AUG_STRENGTH": 0,  // Changed from 0.025
}
```

```python
# src/renderers/hunyuan_custom_renderer.py line 134
DEFAULT_NOISE_AUG_STRENGTH = 0.0  # Changed from 0.025
```

```json
// tests/quick_test.json - both shots
"duration_sec": 2.1,  // Changed from 1.0 to get 25 frames (2.1s × 12fps)
```

### 2. Debugging Methodology Established

Created `test_identity.sh` - a minimal bash script that submits the exact validated workflow via curl, bypassing all Python code. This isolates Python bugs from ComfyUI/model issues.

**Key insight:** If bash test works but Python fails → bug is in our code.

### 3. Documentation Updated

- Added Lessons 82-83 to `LESSONS_LEARNED.md`
- Covers noise_aug_strength, frame count, workflow caching, and debugging strategy

---

## Current State

### Shot 1: ✅ WORKING
```
Identity: 0.5868 vs threshold 0.50 → PASS
```
- 25 frames, noise_aug=0, face ref as both identity AND init
- Motion present, identity preserved

### Shot 2: ❌ BROKEN
```
Identity: 0.3780 vs threshold 0.50 → FAIL
```
- Bridge frame workflow runs
- HunyuanCustom generates video
- Identity doesn't match (comparing against bridge frame)

---

## The Architectural Problem (Shot 2+)

### How the Workflow Currently Works

Per the "validated workflow" fix, we removed separate init image nodes (80, 81) and now:

```
LoadImage(42) [FACE_REF_IMAGE]
     ↓
Resize(43)
     ↓
     ├── CLIPVisionEncode(55) → Identity via <image> token
     └── HyVideoEncode(41) → Init latent for video start
```

**ONE image feeds BOTH paths.**

### Why This Breaks Shot 2+

| Shot | Identity Source | Init Source | Problem |
|------|-----------------|-------------|---------|
| Shot 1 | Alice face ref | Alice face ref | ✅ Same image, works |
| Shot 2+ | Alice face ref | Bridge frame | ❌ Need DIFFERENT images! |

For Shot 2, we need:
- **Identity:** Alice's face (`alice_01.png`) → preserve who she is
- **Init:** Bridge frame from Shot 1's last frame → preserve pose/position continuity

But our workflow can only accept ONE image for both purposes.

### Evidence

```
# Shot 2 comparison shows bridge frame vs video frame
Identity compare: bridge_20260102_044751.png vs frame_hunyuan_1767350873_00001_0_...
Identity: 0.3780 → FAIL
```

The video doesn't look like the bridge frame because HunyuanCustom is using Alice's face as init (not the bridge frame), but identity is being checked against the bridge frame.

---

## What Didn't Work / What We Tried

### 1. Original workflow with separate init path (Nodes 80/81)
- Had `INIT_IMAGE` separate from `FACE_REF_IMAGE`
- **Failed:** Identity scores were 0.10-0.38
- **Why:** Even with same filename, separate LoadImage→Resize chains produce different tensors

### 2. noise_aug_strength = 0.025
- **Failed:** Adds noise to init latent, corrupts identity signal
- **Fix:** Changed to 0

### 3. 13 frames (1.0s × 12fps)
- **Failed:** Not enough frames for motion when noise_aug=0
- **Fix:** Increased to 25 frames (2.1s duration)

### 4. attention_mode = sageattn
- **Failed:** sageattention module not installed on RunPod
- **Workaround:** Used sdpa instead (works fine)

---

## Potential Solutions for Shot 2+ (Not Yet Implemented)

### Option A: Restore Dual Image Inputs (Recommended)

Re-add nodes 80/81 but ensure they work correctly:

```
Node 42 (LoadImage) → FACE_REF_IMAGE → Resize(43) → CLIPVisionEncode(55) [identity]
Node 80 (LoadImage) → INIT_IMAGE → Resize(81) → HyVideoEncode(41) [init latent]
```

**Challenge:** This is what we had before and identity failed. Need to investigate WHY separate paths broke identity - maybe:
- Image preprocessing differences
- Need to ensure FACE_REF feeds CLIPVisionEncode directly
- The `<image>` token in prompt should reference the face, not init

### Option B: HunyuanCustom Native Multi-Shot Support

Research if HunyuanCustom has a way to:
- Provide identity reference separately from init image
- Use multiple `<image>` tokens
- Use a different conditioning approach for I2V

### Option C: Skip Bridge Frames for HunyuanCustom

Just use Alice's face ref for every shot:
- **Pro:** Identity preserved
- **Con:** No visual continuity between shots (pose/position jumps)

### Option D: Two-Pass Approach

1. Generate video with bridge frame as init (for continuity)
2. Post-process to restore identity (face swap/refinement)

---

## Files Changed in This Session

### Modified:
1. `workflows/hunyuan_custom/pass1_img2vid.json`
   - `NOISE_AUG_STRENGTH`: 0.025 → 0
   - Previously also changed node structure (removed 80/81, updated 41 to read from 43)

2. `src/renderers/hunyuan_custom_renderer.py`
   - `DEFAULT_NOISE_AUG_STRENGTH`: 0.025 → 0.0
   - Added debug workflow dump (line ~after workflow build)

3. `tests/quick_test.json`
   - `duration_sec`: 1.0 → 2.1 (both shots)
   - `target_fps`: 12 → 24 (note: fps not actually passed to JobSpec - separate bug)

4. `LESSONS_LEARNED.md`
   - Added lessons 82-83

### Created:
1. `tests/test_identity.sh` - Minimal bash test for debugging

---

## Known Bugs (Not Fixed)

### 1. target_fps not passed to JobSpec
```python
# base.py JobSpec
fps: int = 12  # Default, never overridden

# pass1_generator.py _build_job_spec()
job = JobSpec(
    prompt=prompt,
    duration_sec=duration,
    # fps= NOT PASSED
)
```

**Workaround:** Use longer `duration_sec` to get more frames.

### 2. Workflow template caching
Templates cached in memory during Python process. Must restart Python after editing workflow JSON files.

---

## Test Commands

### Run HunyuanCustom test:
```bash
cd ~/Projects/Continuum
export CONTINUUM_COMFYUI__HOST="wss://YOUR-RUNPOD-8188.proxy.runpod.net"
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom python main.py \
  --project tests/quick_test.json \
  --consistency tests/bible.json \
  --output workspace/output/hunyuan_test \
  --no-pass2 -v
```

### Run bash identity test (bypasses Python):
```bash
cd ~/Projects/Continuum/tests
./test_identity.sh YOUR-RUNPOD-HOST.proxy.runpod.net ../workspace/assets/alice/alice_01.png
```

### Compare workflows:
```bash
python3 -c "
import json
with open('workspace/output/debug_workflow.json') as f:
    py = json.load(f)
print('noise_aug:', py['41']['inputs']['noise_aug_strength'])
print('num_frames:', py['62']['inputs']['num_frames'])
print('node41 image:', py['41']['inputs']['image'])
print('node55 image:', py['55']['inputs']['image'])
"
```

---

## RunPod Info

- **Pod ID:** 8gsp074fx2q6p3
- **WebSocket:** wss://8gsp074fx2q6p3-8188.proxy.runpod.net
- **Hardware:** 4x RTX 4090
- **sageattention:** Installed (pip install sageattention)

---

## Key Files to Review

1. **Validated ComfyUI workflow:** Check RunPod ComfyUI for `hyvideo_custom_testing_01_validated`
2. **Our template:** `workflows/hunyuan_custom/pass1_img2vid.json`
3. **Renderer:** `src/renderers/hunyuan_custom_renderer.py`
4. **Bridge engine:** `src/studio/bridge_engine.py`
5. **Pass1 generator:** `src/studio/pass1_generator.py` (especially `_build_job_spec`)

---

## Recommended Next Steps

1. **Understand the exact data flow** for Shot 2:
   - What image is being set as `FACE_REF_IMAGE`?
   - What image is being set as `INIT_IMAGE`?
   - Which one actually goes to HyVideoEncode?

2. **Check the bridge frame** visually:
   - Does `workspace/output/hunyuan_test/bridge/` contain frames that look like Alice?
   - If bridge frame doesn't preserve Alice's identity, that's where to fix

3. **Research HunyuanCustom dual-image support:**
   - Can it accept separate identity ref and init image?
   - Check the ComfyUI-HunyuanVideoWrapper documentation/issues

4. **Consider if bridge frame approach is compatible with HunyuanCustom:**
   - HunyuanCustom's `<image>` token is designed for identity
   - Bridge frames are designed for pose/continuity
   - These may be fundamentally incompatible without a different workflow

---

## Summary for Fresh Start

**The core tension:** HunyuanCustom identity works by using the SAME image for identity (CLIPVisionEncode) AND init latent (HyVideoEncode). But multi-shot continuity requires DIFFERENT images (face ref for identity, bridge frame for init).

**Shot 1 works** because we want the same image for both.

**Shot 2+ breaks** because we need different images but the workflow only accepts one.

**Solution needed:** Either modify the workflow to accept two images again (and figure out why that broke identity before), or find a different approach for multi-shot HunyuanCustom videos.