# Session Handoff: Identity Preservation → LoRA Integration

**Date:** 2024-12-24
**From:** Claude session investigating identity preservation approaches
**To:** Next Claude session for LoRA MVP integration

---

## Current Architecture Status

**Working Pipeline:**
```
Shot 1:
  face_refs + prompt → Hero Frame (SDXL + IP-Adapter) → WanImageToVideo
  
Shot 2+:
  Last frame of Shot N-1 → Bridge Frame (ControlNet + IP-Adapter) → WanImageToVideo
                                ↑
                           face_refs re-injected for identity re-anchoring
```

**Bridge Frames ARE ACTIVE** - This is the multi-shot identity consistency mechanism:
- Extracts pose from previous shot's last frame (ControlNet)
- Re-injects identity from face_refs (IP-Adapter)
- Uses degradation ladder: full → ipadapter → pose_only → basic

**Key Files:**
- `src/renderers/wan_renderer.py` - Workflow selection logic
- `src/studio/pass1_generator.py` - Hero frame + bridge frame generation
- `src/studio/bridge_engine.py` - Bridge frame workflow execution
- `workflows/pass1_img2vid.json` - Standard I2V workflow (CURRENT DEFAULT)
- `workflows/hero_frame.json` - SDXL + IP-Adapter for Shot 1
- `workflows/bridge_full.json` - ControlNet + IP-Adapter for Shot 2+

---

## What We Tried (Identity + Expression Problem)

### The Problem
Preserve character identity (same person) while allowing natural expressions (smiles, blinks, talking).

### Approaches Tested

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| **face_video per-frame** | 98% identity, FROZEN expression | Pixel-level conditioning locks everything |
| **WanFirstLastFrameToVideo** | Artifacts, dark halos | Designed for A→B interpolation, not same-frame |
| **WanPhantomSubjectToVideo** | 70% identity, poor quality | Only 1.3B model available, too small |
| **Standard I2V + hero frame** | **97% identity, natural expression** | ✅ CURRENT WINNER |

### Current Solution
```python
# wan_renderer.py line ~483
elif has_ipadapter:
    # Lesson #78: face_video/firstlast/phantom all have issues.
    # Standard I2V + hero frame gives 97% identity + natural expressions.
    return self.WORKFLOW_IMG2VID
```

### ⚠️ CRITICAL CAVEAT
**The 97% identity is validated on 1-SECOND clips only.**

For longer clips, identity WILL drift. This is why LoRA is needed for MVP.

---

## Bridge Frame System (ACTIVE)

**Purpose:** Re-anchor identity at each shot cut to prevent drift.

**Workflows (Degradation Ladder):**
| Workflow | Components | When Used |
|----------|------------|-----------|
| `bridge_full.json` | ControlNet + IP-Adapter | Tier 1 (best) |
| `bridge_ipadapter.json` | IP-Adapter only | Tier 2 fallback |
| `bridge_pose_only.json` | ControlNet only | Tier 3 fallback |
| `bridge_basic.json` | Pass-through | Tier 4 fallback (drift warning) |

**Key Insight:** Bridge frames help with CROSS-SHOT consistency but NOT within-shot drift. For a 4-second shot, frames 1-81 only have hero frame as anchor at frame 0. LoRA would help maintain identity throughout.

---

## Why LoRA is Needed Now

1. **Hero frame can only anchor frame 0** - subsequent frames drift
2. **No working per-frame identity conditioning** - all approaches failed
3. **LoRA bakes identity INTO the model weights** - every frame "knows" the character
4. **Multi-shot consistency** - same LoRA across shots = same character

---

## LoRA Integration Requirements

### What Exists
- `WORKFLOW_IMG2VID_LORA = "pass1_img2vid_lora"` constant exists
- `workflows/pass1_img2vid_lora.json` exists
- `CharacterEntity.lora_path` field exists in consistency dict
- Workflow selection already checks `has_lora` first

### What's Needed

1. **LoRA Training Pipeline** (External)
   - Input: 10-20 images of character
   - Output: `character_name.safetensors` LoRA file
   - Tools: Kohya, SimpleTuner, or cloud service

2. **LoRA File Management**
   - Where to store: `workspace/loras/` or RunPod `/workspace/ComfyUI/models/loras/`
   - How to reference in bible.json

3. **Workflow Verification**
   - Verify `pass1_img2vid_lora.json` actually works
   - Check LoRA loader node configuration
   - Test with a sample LoRA

4. **Integration Points**
   ```python
   # bible.json character definition
   {
     "alice": {
       "lora_path": "alice_v1.safetensors",
       "lora_strength": 0.8,
       "face_refs": ["alice_01.png", ...]  # Still used for hero frame
     }
   }
   ```

### Workflow Selection Logic (Already Correct)
```python
if job.has_init_frame:
    if has_lora:
        return self.WORKFLOW_IMG2VID_LORA  # ← This path exists
    elif has_ipadapter:
        return self.WORKFLOW_IMG2VID
    return self.WORKFLOW_IMG2VID
```

---

## Files Modified This Session

1. **`src/renderers/wan_renderer.py`**
   - Changed `elif has_ipadapter:` to return `WORKFLOW_IMG2VID` instead of `WORKFLOW_IMG2VID_FACEVIDEO`

2. **`LESSONS_LEARNED.md`**
   - Added Lesson #78: Comprehensive identity preservation experiments

3. **Created but NOT integrated:**
   - `workflows/pass1_img2vid_firstlast.json` (failed - artifacts)
   - `workflows/pass1_img2vid_phantom.json` (failed - poor quality with 1.3B)

---

## RunPod Environment Notes

**Available Models:**
```
/workspace/runpod-slim/ComfyUI/models/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors
/workspace/runpod-slim/ComfyUI/models/unet/wan2.1_t2v_1.3B_fp16.safetensors
/workspace/runpod-slim/ComfyUI/models/vae/wan_2.1_vae.safetensors
/workspace/runpod-slim/ComfyUI/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
```

**LoRA Directory (verify exists):**
```
/workspace/runpod-slim/ComfyUI/models/loras/
```

**WebSocket URL:**
```
wss://yrc3u8h2t6of5l-8188.proxy.runpod.net
```

---

## Immediate Next Steps

1. **Verify LoRA workflow** - Check `pass1_img2vid_lora.json` has correct node configuration
2. **Get/train a test LoRA** - Need a sample character LoRA to test with
3. **Upload to RunPod** - Place in correct loras directory
4. **Test end-to-end** - Run with `has_lora=True` character
5. **Validate identity over longer clips** - Test 4+ second videos

---

## Key Lessons Reference

- **Lesson #73:** WanAnimateToVideo is NOT an I2V node (22% identity failure)
- **Lesson #74:** face_video provides per-frame identity (98% identity)
- **Lesson #76:** face_video freezes expressions (unusable)
- **Lesson #77:** Identity vs Expression research summary
- **Lesson #78:** Comprehensive experiments - hero frame + I2V is best without LoRA

---

## Quick Test Command

```bash
python main.py \
  --project tests/quick_firstlast_test.json \
  --consistency tests/bible.json \
  --output workspace/output/test \
  --no-pass2 -v
```

This runs a 1-second, 416x240 test. Modify `duration_sec` for longer tests.

---

**Bottom Line:** Current pipeline works for short clips. LoRA integration is the path to persistent identity across longer videos and multiple shots. The infrastructure exists, just needs verification and a test LoRA.