📋 HANDOFF DOCUMENT: Bridge Engine - Complete Session Summary
Context
Debugging and fixing ComfyUIBridgeEngine for shot-to-shot visual continuity in the Continuum Engine.

✅ Code Fixes Completed This Session
All these changes have been made to src/studio/bridge_engine.py:
LineIssueFix Applied31Missing importAdded import random473config.comfyui_host doesn't existChanged to config.comfyui.host474port param doesn't exist in ComfyClientRemoved port parameter entirely477config.workflows_dir doesn't existChanged to config.paths.workflows_dir580-581inject_params() method doesn't existChanged to load_and_inject()649-651Dead code creating unused GenerationParamsRemoved entirely650-653Pose extraction using wrong methodChanged to load_and_inject()667-670Depth extraction using wrong methodChanged to load_and_inject()716Seed value -1 rejected by KSamplerChanged to random.randint(0, 2**32-1)
Previous Session Fix (in client.py):

Added upload_image() alias method
Added submit() alias method


❌ Remaining Issue: Wrong Bridge Architecture
Current (Broken) Approach
bridge_basic.json uses SDXL img2img:
Shot 1 last frame → SDXL img2img → Single bridge image → ???
Problems:

SDXL generates a static image, not video
Different model family than Wan (style mismatch)
Requires extra 6.5GB model download
Bridge image isn't actually used to seed Shot 2's generation
It's a dead-end - the generated image goes nowhere

Correct Approach
Use Wan I2V (Image-to-Video) for Shot 2 instead of T2V:
Shot 1 last frame → Wan I2V (pass1_img2vid) → Shot 2 video
Benefits:

Models already installed on RunPod
Same model family = visual consistency
Actual video output, not static frame
Native ComfyUI workflow exists (pass1_img2vid.json)


🔧 Required Implementation Changes
The Core Logic Change
When generating Shot 2+, the system should:

Extract last frame from previous shot ✅ (already works via FFmpeg)
Pass that frame as init_image to WanRenderer
WanRenderer should select pass1_img2vid workflow instead of pass1_structural

Files to Modify
1. src/studio/pass1_generator.py
Currently calls bridge engine, then renders with T2V regardless. Should:

If bridge frame exists, pass it to renderer as init_image
Renderer decides T2V vs I2V based on presence of init_image

2. src/renderers/wan_renderer.py
Already has I2V logic! Check _select_workflow() method:
python# Look for existing logic like:
if params.init_image:
    return "pass1_img2vid"  # or pass1_img2vid_lora
else:
    return "pass1_structural"  # T2V
```

#### 3. `src/studio/bridge_engine.py`
Simplify significantly:
- Remove SDXL workflow submission entirely
- Just extract frame and return path
- Let WanRenderer handle the I2V generation

### Simplified Bridge Flow

**Before (complex, broken):**
```
bridge_engine.generate() 
  → extract frame 
  → upload to ComfyUI 
  → run SDXL workflow 
  → download result 
  → ??? (unused)
```

**After (simple, correct):**
```
bridge_engine.generate()
  → extract frame
  → return frame path

pass1_generator
  → receives frame path
  → passes to wan_renderer as init_image

wan_renderer
  → sees init_image
  → uses pass1_img2vid workflow
  → generates Shot 2 with visual continuity
```

---

## Key Code Locations

### Bridge Engine
```
File: src/studio/bridge_engine.py
Method: generate() around line 540-630
Method: _extract_last_frame() around line 630-690
```

### Pass 1 Generator  
```
File: src/studio/pass1_generator.py
Method: _generate_chunk() - where bridge result should feed into render call
```

### Wan Renderer
```
File: src/renderers/wan_renderer.py
Method: render() - check if init_image param exists
Method: _select_workflow() - logic for T2V vs I2V selection
```

### Workflow Files
```
workflows/pass1_structural.json     - T2V (current)
workflows/pass1_img2vid.json        - I2V (needed for bridge)
workflows/pass1_img2vid_lora.json   - I2V with LoRA

Config Structure Reference
pythonconfig.comfyui.host              # Full WebSocket URL
config.comfyui.timeout_sec       # Job timeout
config.paths.workflows_dir       # Workflow JSON location
config.paths.output_dir          # Output directory

Test Command
bashpython main.py --project tests/sample_project_2shot.json --no-resume --no-audio --no-post --verbose 2>&1
```

**What to look for after fix:**
```
Shot 1: Using T2V models (pass1_structural)
Shot 2: Using I2V models (pass1_img2vid)  ← This means bridge worked

Other Known Issues (Lower Priority)
IssueLocationImpact'dict' object has no attribute 'shot_id'Audit systemMinor, doesn't crashMissing refine_freelong workflowPass 2 refinerRefinement skippedMissing VHS_LoadVideo nodeRIFE interpolatorInterpolation skippedUnclosed aiohttp sessionsShutdownCosmetic errors in logs

Transcript Locations

Current session: /mnt/transcripts/2025-12-17-22-30-45-bridge-config-fixes.txt
Previous session: /mnt/transcripts/2025-12-17-21-59-21-bridge-shot-to-shot-comfyclient-aliases.txt


Summary
Done: All bridge_engine code bugs fixed.
TODO: Refactor to use Wan I2V instead of SDXL for bridge. The SDXL approach was a flawed design. The fix is to simplify bridge_engine to just extract frames, then let WanRenderer use I2V workflow when an init_image is provided.