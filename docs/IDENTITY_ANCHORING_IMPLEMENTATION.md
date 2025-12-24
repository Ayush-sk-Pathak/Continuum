# Identity Anchoring During I2V Generation

## Summary

Implemented native Wan identity anchoring using `WanAnimateToVideo` node. This provides per-frame identity consistency during video generation, addressing the ~3% identity drift within shots.

## Problem Solved

**Before (pass1_img2vid.json):**
```
Bridge Frame → WanImageToVideo → Video
              (no identity reference)
              
Frame 1:  100% identity match
Frame 12: ~97% identity match (3% drift)
```

**After (pass1_img2vid_ipadapter.json):**
```
Bridge Frame + Face Ref → WanAnimateToVideo → Video
                         (identity anchored)
                         
Frame 1:  100% identity match
Frame 12: ~99%+ identity match (expected)
```

## Files Changed

### 1. NEW: `pass1_img2vid_ipadapter.json`
- Uses `WanAnimateToVideo` instead of `WanImageToVideo`
- Adds `reference_image` input for identity anchoring
- `clip_vision_output` provides I2V behavior from bridge frame
- `FACE_REF_1` placeholder receives face reference from Bible

### 2. MODIFIED: `wan_renderer.py`
- Updated error handling to catch `ValueError` (validation failures)
- Falls back gracefully to `pass1_img2vid.json` if identity workflow fails
- Updated constant comment to indicate implementation status

## Architectural Tradeoff

`WanAnimateToVideo` differs from `WanImageToVideo`:

| Feature | WanImageToVideo | WanAnimateToVideo |
|---------|-----------------|-------------------|
| `start_image` | ✅ Frame 1 = this image exactly | ❌ Not available |
| `clip_vision_output` | ✅ Semantic guidance | ✅ Semantic guidance |
| `reference_image` | ❌ Not available | ✅ Identity anchor |

**The tradeoff:** Frame 1 may not match the bridge frame pixel-perfectly, but identity will be consistent throughout the video. This favors identity consistency over exact first-frame matching.

## How It Works

```
Bible (face_refs) ─────────────────────────┐
                                           │ reference_image
Bridge Frame ──→ CLIPVisionEncode ─────────┼─→ WanAnimateToVideo ──→ Video
                                           │ clip_vision_output
Text Prompt ──→ CLIPTextEncode ────────────┘
```

1. **Bridge frame** encoded via CLIP Vision → provides scene structure
2. **Face reference** from Bible → provides identity anchor
3. **WanAnimateToVideo** → combines both for identity-consistent generation
4. **KSampler** → generates frames with identity anchored throughout

## Deployment Steps

### Step 1: Add Workflow File
Copy `pass1_img2vid_ipadapter.json` to your project's workflow directory:
```bash
cp pass1_img2vid_ipadapter.json /path/to/Continuum/
```

### Step 2: Update wan_renderer.py
Replace your existing `wan_renderer.py` with the updated version, OR apply these changes manually:

**File:** `src/renderers/wan_renderer.py`

**Change 1:** Line ~119
```python
# OLD:
WORKFLOW_IMG2VID_IPADAPTER = "pass1_img2vid_ipadapter"  # Future

# NEW:
WORKFLOW_IMG2VID_IPADAPTER = "pass1_img2vid_ipadapter"  # Uses WanAnimateToVideo for identity anchoring
```

**Change 2:** Lines ~500-531 - Update error handling:
```python
# OLD:
except FileNotFoundError:

# NEW:
except (FileNotFoundError, ValueError) as e:
```

And update the warning messages to include `{type(e).__name__}: {e}`.

### Step 3: Verify on RunPod
Ensure `WanAnimateToVideo` node exists:
```bash
curl -s http://localhost:8188/object_info/WanAnimateToVideo | python3 -c "import sys,json; print('Found' if json.load(sys.stdin) else 'Missing')"
```

### Step 4: Test
Run with a character that has face refs:
```bash
python main.py --project quick_test.json --consistency bible.json --output workspace/output/identity_test -v
```

Look for log messages:
- ✅ `Using template: pass1_img2vid_ipadapter` → New workflow active
- ⚠️ `Template 'pass1_img2vid_ipadapter' failed... falling back` → Fallback triggered

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Identity consistency (Frame 1 vs Frame 12) | ~97% | ~99%+ |
| Identity consistency (Shot 1 vs Shot 5) | ~90% | ~95%+ |
| ArcFace scores | 0.97 | 0.99+ |

## Fallback Behavior

The system gracefully degrades:
1. If `FACE_REF_1` not available → Falls back to `pass1_img2vid.json`
2. If `WanAnimateToVideo` node missing → Falls back to `pass1_img2vid.json`
3. If validation fails → Falls back to `pass1_img2vid.json`

**Critical:** Fallback NEVER crosses from I2V to T2V mode - bridge frame is always preserved.

## Node Experimental Status

`WanAnimateToVideo` is marked `"experimental": true` in ComfyUI. This means:
- It works but may have edge cases
- It's official ComfyUI code (`comfy_extras.nodes_wan`)
- Not a third-party extension

## Future Enhancements

1. **Multi-character support:** Add `FACE_REF_2`, `FACE_REF_3` for scenes with multiple characters
2. **Strength control:** Add `{{IDENTITY_STRENGTH}}` placeholder for tunable identity influence
3. **Face video support:** Use `face_video` input for expression/mouth movement guidance
4. **Continue motion:** Use `continue_motion` for multi-chunk continuity

## Related Files

- `ARCHITECTURE.md` Section 3A.3 - Identity Consistency Stack
- `IP_LORA_Research.md` - Research on identity preservation
- `LESSONS_LEARNED.md` - Error patterns to avoid