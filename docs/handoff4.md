Continuum Engine - Session Handoff Document
Date: December 16, 2025
Session: P3a Completion - Workflow Files + Integration Tests

🎉 SESSION ACCOMPLISHMENTS
Completed P3a (Workflow Files + I2V Integration):

Created workflows/pass1_structural.json - T2V workflow (9 nodes)
Created workflows/pass1_img2vid.json - I2V workflow (14 nodes)
Created tests/test_workflows.py - 66 comprehensive unit tests
Created tests/test_e2e_integration.py - 21 contract verification tests
87 tests passing in 0.34s

The workflow layer is now complete. WanRenderer can load and inject parameters into real ComfyUI workflows.

Current Project Status
Overall MVP Progress: ~88%
DimensionProgressNotesFiles/Modules~97%34/35 required files existIntegration~85%Workflows now connect WanRenderer to ComfyUITesting~65%87 workflow tests + 42 sonic tests = 129 total
Priority Roadmap Status
PriorityModuleStatusNotesP0comfy_client/✅ CompleteWebSocket + workflow loaderP1renderers/wan_renderer.py✅ CompleteSingle-shot generationP2director/scene_graph.py✅ CompleteScript → Shots parserP3aworkflows/ + I2V integration✅ JUST COMPLETEDT2V + I2V workflows + 87 testsP3bmemory/ + LoRA workflow🔲 NextLoRA injection when availableP4studio/bridge_engine.py✅ File existsNeeds workflow + real testingP5audit/identity_checker.py✅ File existsArcFace integration pendingP6sonic/✅ Complete42 tests passingP7studio/pass2_refiner.py✅ File existsNeeds workflowP8director/world_state.py✅ CompleteDynamic prop tracking

What Was Built This Session
1. pass1_structural.json (T2V Workflow)
Location: workflows/pass1_structural.json (~80 lines)
Purpose: Text-to-Video generation using Wan 2.1. Used when no reference image is available (bottom of degradation ladder).
Node Flow:
CLIPLoader ─────────────────────────────────────┐
                                                │
UNETLoader ─► ModelSamplingSD3 ─────────────────┤
                                                │
CLIPTextEncode (positive) ──────────────────────┤
CLIPTextEncode (negative) ──────────────────────┤
                                                ▼
EmptyHunyuanLatentVideo ─► KSampler ─► VAEDecode ─► CreateVideo ─► SaveVideo
                              ▲
VAELoader ────────────────────┘
Injectable Parameters:

POSITIVE_PROMPT, NEGATIVE_PROMPT, SEED
WIDTH, HEIGHT, FRAMES, FPS
STEPS, CFG_SCALE


2. pass1_img2vid.json (I2V Workflow)
Location: workflows/pass1_img2vid.json (~100 lines)
Purpose: Image-to-Video generation. Used for Bridge Frame continuity and identity conditioning (Tier 1 of Progressive Identity Lock).
Node Flow:
LoadImage ──────────────────────────────────────┐
    │                                           │
    ├─► CLIPVisionEncode ───────────────────────┤
    │         ▲                                 │
CLIPVisionLoader                                │
                                                ▼
CLIPLoader ─► CLIPTextEncode ─► WanImageToVideo ─► KSampler ─► VAEDecode ─► CreateVideo ─► SaveVideo
                                      ▲              ▲
UNETLoader ─► ModelSamplingSD3 ───────┘              │
                                                     │
VAELoader ───────────────────────────────────────────┘
Injectable Parameters:

All T2V params PLUS INIT_IMAGE


3. test_workflows.py (Unit Tests)
Location: tests/test_workflows.py (~900 lines)
66 tests covering:

Basic JSON validity (8 tests)
ComfyUI node format compliance (9 tests)
Placeholder syntax and completeness (7 tests)
Parameter injection behavior (6 tests)
Edge cases (6 tests)
Stress testing - unicode, long prompts, large values (7 tests)
Nightmare scenarios - None values, circular refs (9 tests)
Workflow comparison - T2V vs I2V consistency (5 tests)
WanRenderer integration - params match expectations (3 tests)
WorkflowLoader integration - load_and_inject works (6 tests)


4. test_e2e_integration.py (Contract Tests)
Location: tests/test_e2e_integration.py (~300 lines)
21 tests verifying contracts between components:

Import verification (4 tests)
WanRenderer constants match workflow files (4 tests)
Parameter contract - placeholders match what renderer sends (4 tests)
WorkflowLoader integration (5 tests)
Workflow structure - correct nodes, correct models (4 tests)

Key insight: These tests verify the CONTRACT between components without mocking internals. Much more stable than tests that mock private attributes.

Architecture Alignment
workflows/                 STATUS
├── pass1_structural.json  ✅ CREATED (T2V)
├── pass1_img2vid.json     ✅ CREATED (I2V)
├── pass1_structural_lora.json  🔲 P3b (LoRA injection)
├── bridge_frame.json      🔲 P4 (Bridge frames)
├── pass2_refinement.json  🔲 P7 (FreeLong++)
└── lip_sync.json          🔲 P6 (Musetalk)

Key Technical Decisions This Session
1. No _meta Keys in Workflow JSONs
json// WRONG - validator rejects this
{
  "_meta": { "title": "My Workflow" },
  "sampler": { "class_type": "KSampler", ... }
}

// CORRECT - pure nodes only
{
  "sampler": { "class_type": "KSampler", ... }
}
Why: workflow_loader.py validate() treats ALL keys as ComfyUI nodes. It skips _-prefixed FILES but not _-prefixed KEYS.
2. Named Node IDs for Readability
json"positive_prompt": {
  "class_type": "CLIPTextEncode",
  ...
}
Instead of "6": { ... }. ComfyUI API accepts string keys, and this makes debugging much easier.
3. Placeholder Syntax Matches WanRenderer
python# wan_renderer.py _build_generation_params()
{
    "POSITIVE_PROMPT": job.prompt,
    "SEED": job.seed,
    "FRAMES": job.frame_count,  # Not LENGTH
    "CFG_SCALE": job.cfg_scale,  # Not CFG
}
Workflow placeholders use the exact same names - zero translation layer needed.
4. Minimal E2E Tests > Complex Mocks
Originally tried to mock WanRenderer._client, _loader, _initialized for E2E tests. This was fragile and kept breaking.
Solution: Test the CONTRACT (constants, placeholders, file existence) not the internals. 21 contract tests are stable and fast.

Files Created/Modified This Session
FileLinesStatusworkflows/pass1_structural.json~80Createdworkflows/pass1_img2vid.json~100Createdtests/test_workflows.py~900Createdtests/test_e2e_integration.py~300Created

Test Commands
bashcd ~/Projects/Continuum
source venv/bin/activate

# Run P3a workflow tests (87 tests)
python -m pytest tests/test_workflows.py tests/test_e2e_integration.py -v
# Expected: 87 passed in ~0.34s

# Run sonic tests (42 tests)  
python -m pytest tests/sonic/test_integration.py -v
# Expected: 42 passed

# Verify workflow files load correctly
python -c "
from src.comfy_client.workflow_loader import WorkflowLoader
from pathlib import Path
loader = WorkflowLoader(Path('workflows'))
t2v = loader.load('pass1_structural')
i2v = loader.load('pass1_img2vid')
print(f'T2V placeholders: {t2v.placeholders}')
print(f'I2V placeholders: {i2v.placeholders}')
"
```

---

## Next Steps (Priority Order)

### 1. P3b: LoRA Workflow Integration
Create workflow that injects LoRA for enhanced identity:
```
workflows/pass1_structural_lora.json
```
Add LoraLoader node between UNETLoader and ModelSamplingSD3.

### 2. P4: Bridge Engine Workflow
Create workflow for bridge frame generation:
```
workflows/bridge_frame.json
```
This enables seamless shot-to-shot transitions.

### 3. Real ComfyUI Testing
- Deploy to RunPod with Wan 2.1 models
- Test actual video generation with workflows
- Validate the full WanRenderer → ComfyUI → Video path

### 4. P5: Identity Checker Integration
Wire up ArcFace for actual identity verification in the audit loop.

---

## Lessons Learned This Session

### New Lesson: #18 - Workflow JSON Cannot Have `_meta` Keys

| | |
|---|---|
| **Error** | `ValueError: Workflow validation failed: ["Node _meta: missing 'class_type'"]` |
| **Wrong Assumption** | Workflow JSONs can have `_meta` key for documentation |
| **Correct Interface** | `validate()` treats ALL keys as ComfyUI nodes |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` lines 486-493 |

**Note:** Loader skips `_` prefixed FILES but NOT `_` prefixed KEYS in workflow dict.

### Pattern Reinforced: J4 Violations Caused Most Debugging Time

Made multiple errors by guessing interfaces instead of reading source:
- `comfy_url` vs `comfy_host`
- `_connected` vs `_initialized`
- `wait_for_completion(job)` vs `wait_for_completion(prompt_id: str)`

**J4 exists for a reason. Read the source before building integrations.**

---

## Session Transcript Location

Full conversation transcript available at:
```
/mnt/transcripts/2025-12-16-22-25-20-p3a-workflow-meta-validation-fix.txt
```

Previous session transcripts listed in:
```
/mnt/transcripts/journal.txt

Quick Reference: Workflow Integration
WorkflowWanRenderer ConstantPlaceholderspass1_structural.jsonDEFAULT_WORKFLOWPOSITIVE_PROMPT, NEGATIVE_PROMPT, SEED, WIDTH, HEIGHT, FRAMES, FPS, STEPS, CFG_SCALEpass1_img2vid.jsonWORKFLOW_IMG2VIDAll above + INIT_IMAGEpass1_structural_lora.jsonWORKFLOW_WITH_LORA🔲 To create (P3b)

Summary
What was built this session:

T2V workflow (pass1_structural.json)
I2V workflow (pass1_img2vid.json)
87 comprehensive tests validating workflow structure and integration

What works now:

WanRenderer can select correct workflow based on JobSpec
WorkflowLoader can load, inject parameters, and validate workflows
Full contract verified between WanRenderer ↔ WorkflowLoader ↔ Workflow JSONs

What's next:

P3b: LoRA workflow for enhanced identity
P4: Bridge frame workflow for shot transitions
Real ComfyUI deployment testing

The workflow layer is complete. P3a is done.