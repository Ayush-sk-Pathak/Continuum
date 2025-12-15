INSTRUCTIONS ONLY FOR FOUNDER
These are for how you should work with the LLM so the project doesn’t decay.
1. Never Let It “Freestyle” the Entire System
Always anchor the LLM in:
docs/ARCHITECTURE_SUMMARY.md (short architecture source of truth)
docs/LLM_CODING_GUIDELINES.md (how it should code)
Use the full docs/ARCHITECTURE.md only when doing design/architecture discussions.
Avoid prompts like “refactor the whole repo” or “rewrite the pipeline” unless you’re prepared to manage a massive diff.
Instead, ask for very specific tasks, e.g.:
“Add a function in asset_manager.py to retrieve canonical keyframes by entity + scene.”
“Wire the new consistency_memory helper into video_pipeline.render_shot().”
2. Control the Granularity
For complex features:
Ask the LLM for a step-by-step technical plan (files, functions, interfaces).
Approve/modify the plan.
Execute step-by-step, each with its own prompt.
If a file starts to bloat, you decide to split it and then ask the LLM to help, instead of the LLM randomly splitting things.
3. Use a “Code Review” Cycle with the LLM
After the LLM gives code:
Do a quick sanity scan yourself.
Optionally run a second LLM call:
“Review this diff for architectural / style violations given our project rules.”
Treat this like a junior dev writing code and a senior dev reviewing.
4. Enforce Tests
From the start, demand tests:
“Also add tests in tests/test_video_pipeline.py for this new behavior.”
“Update tests if behavior changed.”
Build a habit: no behavior change without a test (or a very explicit decision to skip tests for a throwaway experiment).
This is your safety net when the codebase gets big and you forget details.
5. Be Ruthless About Context
Don’t paste the entire repo.
Give only:
Relevant files.
Small snippets around where work is happening.
ARCHITECTURE_SUMMARY.md + LLM_CODING_GUIDELINES.md when starting a new session or when you see drift.
Specific excerpts from ARCHITECTURE.md only when discussing architecture, not for every small bugfix.
If you notice it hallucinating or forgetting structure → stop, re-anchor:
“Here’s the architecture summary again. Re-plan your approach in line with this.”
6. Track “Agent Damage”
Whenever an LLM change breaks things in a weird way, note it.
If a file keeps getting corrupted by repeated edits, consider:
Manually refactoring/cleaning that piece once.
Adding more tests around it.
Updating the docs so future LLM sessions understand it better.
Marking sensitive areas in comments (e.g. # DO NOT CHANGE INTERFACE WITHOUT ARCH REVIEW).
7. Use Git Like a Scalpel
Always keep LLM changes in branches and small commits:
One feature/bugfix per branch.
Easy to revert if it goes sideways.
Write commit messages that explain the intent in plain language so future you (and future LLMs) understand context.
8. Containerize Early
Run the system inside a Docker container from early on:
Same environment locally and later in cloud.
Easy to spin up new instances (e.g., parallel agents later).
Include:
Python app
ComfyUI + required custom nodes
Basic GPU/driver assumptions
When you reach the cloud phase, you just:
Deploy the same container.
Attach GPU, storage, and ComfyUI server config around it.
9. Keep Human Authority Over Architecture
Do not let the LLM change:
Top-level module boundaries:
director_agent/, asset_manager/, video_pipeline/, memory/, comfy_client/, voice_engine/, tests/, renderer implementations.
Core data models:
Scene Graph, Consistency Dictionary, Dialogue Map, Shot/Chunk specs.
Core flows:
Director → Asset Manager / Memory → Video Pipeline (Pass 1 + Pass 2) → Voice Engine → RIFE / Renderer.
Core principles:
ComfyUI-first, two-pass rendering, and audio/lip-sync as first-class.
…without you explicitly approving.
If it proposes large structural changes, treat it like an intern’s design doc: push back, ask for alternatives, or say no.
10. Protect the “ComfyUI-First” & Two-Pass Design
If the LLM starts suggesting:
“Let’s rewrite everything in raw Diffusers code instead of ComfyUI,” or
“Let’s skip Pass 2 / Voice Engine / RIFE to simplify,”
treat that as scope creep / architectural drift and reject it unless you consciously decide to pivot.
Your job is to protect:
ComfyUI workflows as the place where complex video graphs live.
Two-pass video (structure → refinement).
The dedicated Voice Engine and lip-sync module.
11. Periodically Re-Anchor with a Fresh Session
As the project grows:
Start a fresh chat every so often.
Feed in:
The latest ARCHITECTURE_SUMMARY.md
The updated module list
A short changelog of recent big changes
Ask:
“Given this, do a high-level diagnostic – where are we fragile / under-tested?”
This resets drift from old chats and keeps the “mental map” clean.


First 7 Days – Execution Plan (Beginner-Friendly)
Goal of these 7 days:
Understand ComfyUI + basic video workflows.
Have one workflow that makes a small consistent video.
Have a minimal comfy_bridge.py that triggers that workflow from Python.
After this week you’ll actually feel the system, not just think about it.
Day 1 – Get ComfyUI Running
Goal: ComfyUI is running and can generate a simple image.
Decide where ComfyUI runs (for now):
If you don’t have an NVIDIA GPU locally, use a GPU cloud template (RunPod, Vast, RunComfy, etc.).
Start ComfyUI and open its UI (usually http://<ip>:8188).
Load a default text-to-image workflow and:
Change the prompt.
Hit Queue.
Confirm an output image is produced.
Success criteria:
You can change a prompt in ComfyUI and see a new image.
Day 2 – First Text-to-Video Workflow
Goal: Make ComfyUI produce a tiny video clip.
Install/enable a simple text-to-video or StreamingT2V workflow in ComfyUI.
Run a test:
Prompt: “a walking robot in a city street, 2 seconds video”.
16–24 frames, low resolution is fine.
Save the workflow:
Use Save (API Format).
Save as workflows/t2v_basic.json in your repo.
Success criteria:
You have workflows/t2v_basic.json that can generate a short video when opened in ComfyUI.
Day 3 – Add Character Consistency (Reference Image)
Goal: Introduce a fixed character via reference image.
Generate an “Alice” reference image with any model.
Save as assets/characters/alice_ref.png.
Modify the video workflow:
Add a “Load Image” node.
Add IP-Adapter / similar image-conditioning node, if available.
Wire it so the video is guided by alice_ref.png.
Test:
Prompt 1: “Alice standing in a kitchen”.
Prompt 2: “Alice walking in a street”.
Confirm she looks mostly like the same person.
Save updated workflow as:
workflows/t2v_alice_ref.json.
Success criteria:
t2v_alice_ref.json uses a reference image so Alice is reasonably consistent between prompts.
Day 4 – Manual Chunking: Clip A → Clip B
Goal: Prove you can manually “continue” a shot.
Generate Clip A (0–5s):
Use t2v_alice_ref.json.
Prompt: “Alice walking down a corridor”.
Save as outputs/alice_clip_a.mp4.
Get the last frame of Clip A:
Extract via video tool or screenshot.
Load this as an image node in ComfyUI (e.g., ControlNet or starting frame).
Generate Clip B (5–10s):
Prompt: “Alice continues walking and turns right”.
Use the last frame of Clip A as conditioning.
Play Clip A then Clip B back-to-back.
Success criteria:
Clip B feels like a continuation of Clip A (even if imperfect), not a hard reset.
Day 5 – Build the Python Bridge (comfy_bridge.py)
Goal: Trigger your ComfyUI workflow from Python instead of clicking buttons.
Create file:
src/comfy_client/comfy_bridge.py.
Implement minimal functions:
Load workflow JSON from disk.
Update:
text prompt
seed
reference image path
Send the job to ComfyUI’s /prompt HTTP API.
Test via CLI that it generates a video using t2v_alice_ref.json.
Prompt to Claude/GPT for Day 5
When you reach Day 5, open a new chat with Claude/GPT and paste this (after pasting ARCHITECTURE_SUMMARY.md + LLM_CODING_GUIDELINES.md for context):
Context:
- This project is the "Consistent Character Engine".
- ComfyUI is the main video engine. Complex graphs live in ComfyUI; Python just drives it.
- I already have a ComfyUI workflow saved in API format at:
  - workflows/t2v_alice_ref.json
- I have an Alice reference image at:
  - assets/characters/alice_ref.png

Goal for this task:
Create a minimal but robust Python bridge to ComfyUI called comfy_bridge.py.

Constraints:
- Do NOT try to recreate the diffusion pipeline in Python.
- Only talk to ComfyUI via its HTTP/WebSocket API.
- Keep it simple and procedural for now (we can refactor into classes later).

Repo structure (relevant parts):
- docs/ARCHITECTURE_SUMMARY.md
- docs/LLM_CODING_GUIDELINES.md
- workflows/t2v_alice_ref.json
- assets/characters/alice_ref.png
- src/comfy_client/   <-- new file should go here

What I want you to implement:

File: src/comfy_client/comfy_bridge.py

1. A function to load a workflow JSON from disk:
   - def load_workflow(path: str) -> dict

2. A function to update the workflow with runtime values:
   - def update_workflow(workflow: dict, prompt: str, seed: int, ref_image_path: str) -> dict
   - It should:
     - Find the CLIP text encoding node(s) and replace the text prompt.
     - Find the seed field used by the sampler and replace it.
     - Find the image input node for the reference image and replace its path.
   - It is OK to:
     - Let ME supply a mapping from "logical names" to node IDs later.
     - Or to search for nodes by a "friendly" label / title / class if present.
   - DO NOT hard-code a specific node ID without explaining clearly where to change it.

3. A function to send the workflow to a running ComfyUI server:
   - def send_to_comfy(workflow: dict, host: str = "127.0.0.1", port: int = 8188) -> dict
   - Use the standard /prompt HTTP endpoint.
   - Return the raw JSON response (job ID etc).

4. A simple CLI entrypoint:
   - When run as a script, e.g.:
       python -m src.comfy_client.comfy_bridge \
         --workflow workflows/t2v_alice_ref.json \
         --prompt "Alice walking in a corridor" \
         --seed 1234 \
         --ref-image assets/characters/alice_ref.png
   - It should:
     - Load workflow
     - Update with the provided values
     - Send to ComfyUI
     - Print:
       - Job ID (or similar handle)
       - Any output file paths if they are in the response, or at least a note saying:
         "Check ComfyUI output directory" if not.

5. Error handling & logging:
   - If ComfyUI is not reachable, print a clear error message and exit gracefully.
   - Log the key steps:
     - "Loaded workflow from ..."
     - "Updated prompt/seed/ref image"
     - "Submitted job to http://host:port/prompt"

Style:
- Follow the LLM_CODING_GUIDELINES from this repo:
  - Small, focused module
  - Clear explanation:
    - Start with "This fixes X by doing Y"
    - Then give the technical details
- Keep dependencies minimal:
  - Use only standard library plus 'requests' and 'argparse'.

Deliverables:
- Full contents of src/comfy_client/comfy_bridge.py
- Brief explanation of:
  - How to call it
  - What assumptions it makes about the workflow JSON (e.g., where to plug in node IDs later).
Success criteria for Day 5:
Running the CLI command generates a video through ComfyUI.
You can change the prompt/seed/ref image purely from the CLI, no UI clicking.
Day 6 – Make the Bridge Less Fragile
Goal: Turn comfy_bridge.py into something reusable.
Add more robust CLI options with argparse:
--workflow
--prompt
--seed
--ref-image
Optional: --host, --port.
Improve error handling:
Clear messages when file paths don’t exist.
Clear message if ComfyUI returns non-200.
Add basic logging:
print/log major steps so future LLMs/humans can trace failures.
Run several different prompts back-to-back to ensure stability.
Success criteria:
comfy_bridge.py feels like a small tool you trust, not a toy script.
Day 7 – Tie It Back to the Architecture & Choose Week-2 Focus
Goal: Align what you built with the architecture and choose the next deepening step.
Update ARCHITECTURE_SUMMARY.md:
Under comfy_client/, note that:
comfy_bridge.py currently drives t2v_alice_ref.json.
Watch all clips you’ve produced (A, B, etc.) and jot down:
3–5 things that look good.
3–5 obvious failure modes (face drift, weird motion, etc.).
Add these under a new section in docs/Research.md → “Week 1 Observations”.
Pick one Week-2 goal:
Automate Clip A → Clip B sequencing in Python using last frame.
Or start a minimal video_pipeline/render_shot() that uses the bridge.
Or experiment with a second character for future multi-hero scenes.
Success criteria:
You have:
A working ComfyUI workflow.
A working Python bridge.
A clear, single next objective for Week 2.