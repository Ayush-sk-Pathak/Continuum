Project: Consistent Character Engine â€“ LLM Coding Guidelines
You are helping build a long-form AI video system (5â€“30 min) with strong character and world consistency. Your job is to write code and designs that stay maintainable as the system grows, not just â€œmake it work onceâ€.
1. Mindset: Augmented Coding, Not Freeform Vibe Coding
Work like a senior engineer paired with a human, not an end-to-end magician.
Prefer small, concrete changes over huge rewrites.
When asked for big features, first propose a step-by-step plan, then implement one step at a time.
2. Modularity & Structure (Critical for Large Codebases)
Keep code modular, isolated, and testable:
One clear responsibility per module/file.
Avoid giant god-files; if a file goes beyond ~700â€“800 lines of logic, consider splitting.
Use clear folder structure (names may vary, but roles must be obvious), e.g.:
director_agent/, asset_manager/, video_pipeline/, memory/, comfy_client/, voice_engine/, tests/.
Use descriptive names for files, classes, and functions so future LLM calls can â€œfindâ€ the right place.
3. Context Discipline
Do not assume you see the whole system.
Always ask: â€œWhat is the minimum code/context I need to see to do this change safely?â€
When editing:
Focus on one module or function at a time.
Donâ€™t rewrite unrelated parts â€œbecause they look badâ€ unless explicitly asked.
When the user shares a big file or many files:
Identify and work only on the relevant subset.
4. Tests & Feedback Loops
Prefer test-first or test-alongside development:
If thereâ€™s no test, propose a small unit or integration test before or together with the implementation.
Every time you change behavior:
Suggest which tests to run (e.g., pytest tests/test_video_pipeline.py::test_chunk_stitching).
Design code so it is naturally testable:
Pure-ish functions, clear inputs/outputs, minimal hidden global state.
Assume tests are the source of truth:
If behavior is unclear, infer from existing tests or propose new ones.
5. Obey the Architecture and Modules (Two-Pass, ComfyUI-First)
Always map your work to these logical modules. Names may differ, but roles must not.
Director Agent
LLM planning logic: builds Scene Graph, Consistency Dictionary, Dialogue Map, and shot/chunk specs.
Asset Manager / Visual RAG
Manages assets and references:
Character LoRAs, face refs
Environment panoramas / keyframes
Prop images / keyframes
Provides lookup APIs used by the Director and video pipeline.
Video Pipeline (Orchestrator)
Takes Scene Graph + Consistency Dictionary + Dialogue Map.
Breaks work into:
Pass 1 â€“ Structural Long-Form Video (StreamingT2V-style + CoNo or latent blending at chunk boundaries).
Pass 2 â€“ Refinement (vid2vid / FreeLong++-style temporal cleanup / upscaling).
Voice Engine â€“ TTS + lip sync.
RIFE â€“ frame interpolation.
Calls actual renderers (ComfyUI, premium APIs) via a Renderer interface.
ComfyUI Client / Renderer (Open-Source Backend)
ComfyUI-first: complex diffusion/video logic belongs in workflows, not in raw Python.
Python side:
Loads workflow JSON.
Updates prompts, seeds, asset paths, config knobs.
Submits jobs to ComfyUI HTTP/WebSocket API.
Pass 1 and Pass 2 are typically implemented as separate ComfyUI workflows.
Voice Engine
Uses the Dialogue Map from the Director.
Generates speech (e.g., ElevenLabs / OpenAI TTS; must be pluggable).
Runs lip-sync (e.g., Musetalk / Wav2Lip) on refined video segments (after Pass 2, before RIFE).
RIFE / Frame Interpolator
Converts ~12 fps renders into 24â€“30 fps for smooth video.
Sits at the very end of the pipeline.
Optional Premium Renderer
Veo/Sora/Runway/etc. behind the same Renderer interface as the ComfyUI backend.
The Director, Asset Manager, Voice Engine, and RIFE must not care which renderer is underneath.
If you design new modules, attach them clearly to this ecosystem.
Do not invent a parallel architecture or a separate, conflicting pipeline.
6. Pluggability, Not Hard-Coding
Do not hard-code specific models, endpoints, or file paths deep inside logic.
Use configuration/parameters for:
Base model name
Provider (open-source vs premium)
Model paths / workflow IDs
API keys / URLs
Design interfaces so that swapping:
Wan â†’ Hunyuan, or
Local ComfyUI â†’ remote ComfyUI / API renderer
does not require rewriting the whole pipeline.
7. Logging, Errors, and Debuggability
Add clear logging around key operations:
Which scene/shot/chunk is being processed.
Which backend/model/config is being used.
Paths of generated outputs.
Error messages should include:
Which module failed (Director, Asset Manager, Video Pipeline, Comfy Client, Voice Engine, etc.).
Enough context (IDs, filenames, parameters) for a future LLM or human to trace the issue.
8. Guardrails on â€œFixingâ€
When the user reports a bug:
Identify one primary root cause.
Propose a small, contained fix.
Suggest tests to confirm.
Avoid chain reactions:
Do not refactor multiple subsystems in one go unless explicitly asked.
Do not â€œclean upâ€ unrelated code in the same change; call it out as a separate, optional refactor.
9. Explanation Style
For every non-trivial change:
Plain-language summary
Start with:
â€œThis fixes X by doing Y.â€
Technical systems view
Which module(s) it affects.
How it interacts with the rest of the architecture (especially the two-pass pipeline + ComfyUI).
Any implications for tests, performance, or future extensibility.
The goal is that future LLM sessions and humans can quickly understand what was done, why it was done, and where to hook in next.

10. Naming Consistency & Schema Changes (Critical)
When you encounter a name mismatch between files, DO NOT immediately "fix" it. First determine:

**Step 1: Is This a Typo or a Schema Issue?**

```
Scenario A: TYPO (one file wrong)
─────────────────────────────────
scene_graph.py:  class Scene:
                     def duration_sec(self): ...   ← Source of truth

main.py:         scene.total_duration_sec          ← TYPO (should be duration_sec)

FIX: Change main.py (the caller), NOT scene_graph.py (the schema)
```

```
Scenario B: SCHEMA CHANGE NEEDED (external requirement)
───────────────────────────────────────────────────────
ComfyUI requires:  "start_image" parameter
Our code uses:     "init_image" everywhere

FIX: Change OUR code everywhere to match external requirement
     (grep -rn "init_image" and update all occurrences)
```

**Step 2: Before Changing ANY Name, Run This Checklist**

1. **Find the source of truth:**
   ```bash
   grep -rn "def property_name\|property_name:" src/  # Find definition
   ```

2. **Count usages:**
   ```bash
   grep -rn "\.property_name" src/ | wc -l  # How many callers?
   ```

3. **Determine scope:**
   - 1 file uses wrong name → Fix that 1 file (typo)
   - 10+ files use a name → That's the canonical name (change the outlier)
   - External tool requires specific name → Change our code to match

4. **If changing a "global" name, update ALL of:**
   - [ ] The dataclass/class definition
   - [ ] All callers (grep thoroughly)
   - [ ] All JSON schemas that serialize it
   - [ ] All tests
   - [ ] LESSONS_LEARNED.md (document the rename)

**Step 3: Naming Hierarchy in This Codebase**

| Level | Convention | Example |
|-------|-----------|---------|
| Single item's property | `thing_sec`, `thing_id` | `shot.duration_sec` |
| Container's aggregate | `total_thing_sec` | `scene_graph.total_duration_sec` |
| ComfyUI params | SCREAMING_SNAKE | `INIT_IMAGE`, `LORA_PATH` |
| Config env vars | PREFIX__SECTION__FIELD | `CONTINUUM_COMFYUI__HOST` |

**Step 4: When In Doubt**

Ask yourself: "If I change this name, how many files break?"
- 0-1 files → Safe to change (it's the outlier)
- 5+ files → DON'T change it; find the real bug

**Anti-pattern to Avoid:**
```python
# DON'T add aliases "just to be safe"
class Scene:
    @property
    def duration_sec(self): ...
    
    @property  
    def total_duration_sec(self):  # NO! Creates confusion
        return self.duration_sec
```

Aliases hide bugs and create ambiguity about which name is canonical.