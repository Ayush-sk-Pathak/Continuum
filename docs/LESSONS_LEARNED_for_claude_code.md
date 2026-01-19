# Lessons Learned: Interface Mismatches & Wrong Assumptions
*Condensed from LESSONS_LEARNED.md - all context preserved, formatting optimized*

---

## Source of Truth Files

Before writing code that uses these interfaces, **always check these files first**:

| Interface | Source of Truth | Key Classes |
|-----------|-----------------|-------------|
| Renderer | `src/renderers/base.py` | `BaseRenderer`, `RenderResult`, `JobSpec`, `CharacterRef` |
| Scene Graph | `src/director/scene_graph.py` | `SceneGraph`, `Scene`, `Shot`, `Chunk`, `EntityRef` |
| Consistency Dict | `src/director/consistency_dict.py` | `ConsistencyDict`, `CharacterEntity`, `LocationEntity` |
| World State | `src/director/world_state.py` | `WorldState`, `SceneSetup`, `TrackedObject`, `StateEvent` |
| Pacer | `src/director/pacer.py` | `Pacer`, `PacingStyle`, `ShotPacingPlan`, `ChunkTiming` |
| Bridge Engine | `src/studio/bridge_engine.py` | `BaseBridgeEngine`, `BridgeSpec`, `BridgeResult` |
| Pass 1 Generator | `src/studio/pass1_generator.py` | `Pass1Generator`, `GenerationConfig`, `ChunkOutput`, `ShotOutput` |
| Pass 2 Refiner | `src/studio/pass2_refiner.py` | `BaseRefiner`, `RefineSpec`, `RefineResult` |
| RIFE Interpolator | `src/studio/rife_interpolator.py` | `BaseInterpolator`, `InterpolationSpec`, `InterpolationResult` |
| Identity Checker | `src/audit/identity_checker.py` | `BaseIdentityChecker`, `IdentityComparison`, `FrameFaces` |
| Physics Checker | `src/audit/physics_checker.py` | `BasePhysicsChecker`, `PhysicsViolation`, `TrackingResult` |
| Reviewer | `src/audit/reviewer.py` | `Reviewer`, `ReviewRequest`, `ReviewResult`, `ReviewDecision` |
| Sonic Types | `src/sonic/types.py` | `SonicManifest`, `DialogueLine`, `VoiceConfig`, `AmbienceSpec`, `FoleyEvent` |
| TTS Engine | `src/sonic/tts_engine.py` | `BaseTTSEngine`, `SynthesizedDialogue` |
| Ambience | `src/sonic/ambience.py` | `BaseAmbienceEngine`, `SynthesizedAmbience` |
| Foley | `src/sonic/foley.py` | `BaseFoleyEngine`, `SynthesizedFoley`, `FoleyMatch` |
| Mixer | `src/sonic/mixer.py` | `AudioMixer`, `MixSpec`, `MixResult` |
| Lip Sync | `src/sonic/lip_sync.py` | `BaseLipSyncEngine`, `LipSyncSpec`, `DialogueSegment` |
| Visual RAG | `src/memory/visual_rag.py` | `VisualRAG`, `EmbeddingRecord`, `SearchResult`, `SimilarityCheck` |
| Cache | `src/memory/cache.py` | `CacheManager`, `MemoryCache`, `DiskCache`, `CacheEntry` |
| Asset Store | `src/memory/asset_store.py` | `AssetStore`, `AssetMetadata`, `LocalStorageBackend` |
| Config | `src/core/config.py` | `Config`, `GenerationConfig`, `AuditConfig` |
| Job State | `src/core/job_state.py` | `JobStatus`, `JobCheckpoint`, `AuditResult` |
| Error Recovery | `src/core/error_recovery.py` | `RetryConfig`, `DegradationLadder` |
| Workflow Loader | `src/comfy_client/workflow_loader.py` | `WorkflowLoader`, `WorkflowTemplate` (load by NAME, not path) |
| Main Orchestrator | `src/main.py` | `ContinuumOrchestrator`, `PipelineConfig`, `PipelineResult` |

---

## Naming Conventions

| Pattern | Convention | Examples |
|---------|------------|----------|
| Time durations | `_sec` suffix | `base_delay_sec`, `duration_sec`, `timeout_sec` |
| ComfyUI classes | Include "UI" | `ComfyUIBridgeEngine`, `ComfyUIConfig` |
| Entity references | `EntityRef.type()` factory | `EntityRef.character("id")`, `EntityRef.location("id")` |
| Async methods | `async def` prefix | All cloud/IO operations are async |
| Abstract methods | Must implement all | Check with `grep "@abstractmethod"` |

---

## Verification Commands

```bash
# Find all required fields in a dataclass
grep -A 30 "class RenderResult" src/renderers/base.py

# Find all abstract methods in a base class
grep -n "@abstractmethod" src/renderers/base.py

# Find exact class names
grep -n "^class.*Engine" src/studio/bridge_engine.py

# Find method signatures
grep -n "def compare" src/audit/identity_checker.py

# Find parameter names
grep -A 20 "class RetryConfig" src/core/error_recovery.py
```

---

## Error Log

### 1. Scene.__init__() Missing `title` Argument
**Error:** `TypeError: Scene.__init__() missing 1 required positional argument: 'title'`
**Wrong:** `Scene(scene_id="s1", index=0, description="Test")`
**Correct:** `Scene(scene_id="s1", index=0, title="Test Title", description="Test")`
**Why:** Dataclass field order matters - required fields without defaults must be provided.

### 2. RenderResult Missing Required Fields
**Error:** `RenderResult.__init__() missing 3 required positional arguments`
**Required fields (in order):** `video_path`, `frame_count`, `fps`, `duration_sec`, `resolution`, `renderer_type`, then optional `metadata`
**Why:** When mocking a dataclass, check ALL fields. Required fields come before optional ones with defaults.

### 3. BaseRenderer Missing Abstract Methods
**Error:** `TypeError: Can't instantiate abstract class MockRenderer without implementation for abstract methods`
**Required methods:** `generate()`, `initialize()`, `shutdown()`, `estimate_cost(job) -> float`, `estimate_time(job) -> float`
**Prevention:** When subclassing an ABC, grep for `@abstractmethod` to find ALL required methods.

### 4. Wrong Method Name: `compare_to_reference` vs `compare`
**Error:** `'MockIdentityChecker' object has no attribute 'compare_to_reference'`
**Wrong:** `identity_checker.compare_to_reference(reference_path, target_path)`
**Correct:** `identity_checker.compare(source_frame, target_frame)`
**Impact:** This was a real bug in main.py, not just a test issue.

### 5. Wrong Class Name: `ComfyBridgeEngine` vs `ComfyUIBridgeEngine`
**Wrong:** `from src.studio.bridge_engine import ComfyBridgeEngine`
**Correct:** `from src.studio.bridge_engine import ComfyUIBridgeEngine`

### 6. Wrong Parameter Name: `base_delay` vs `base_delay_sec`
**Wrong:** `RetryConfig(max_attempts=3, base_delay=1.0)`
**Correct:** `RetryConfig(max_attempts=3, base_delay_sec=1.0)`
**Why:** The codebase uses `_sec` suffix for time durations consistently.

---

### 7. ComfyUI Workflow Format: UI vs API
**Error:** `{"error": {"type": "invalid_prompt", "message": "Cannot execute because a node is missing the class_type property."}}`

**The Problem:** ComfyUI has TWO formats:
- **UI format:** Has `"nodes": [...]` array - this is what you save from the UI
- **API format:** Has `{"node_id": {"class_type": ...}}` - this is what `/prompt` endpoint needs

**Prevention:** Check if workflow has `"nodes"` key - if yes, it's UI format and needs conversion. Export from ComfyUI with "Save (API Format)" or convert programmatically.

### 8. WorkflowLoader Returns Object, Not Dict
**Error:** `TypeError: object of type 'WorkflowTemplate' has no len()`
**Wrong:** `workflow = loader.load("t2v_wan21.json"); print(len(workflow))`
**Correct:** `template = loader.load("t2v_wan21.json"); workflow = template.workflow`

### 9. ComfyClient Requires Explicit connect()
**Error:** `ComfyConnectionError: Not connected to ComfyUI`
**Wrong:** Client does NOT connect automatically on first request
**Correct:**
```python
client = ComfyClient(host=url)
await client.connect()  # REQUIRED
await client.submit_workflow(workflow)
```

### 10. ComfyClient Method Names
Our wrapper uses different names than ComfyUI API:
| Wrong | Correct |
|-------|---------|
| `ComfyUIClient` | `ComfyClient` |
| `queue_prompt()` | `submit_workflow()` |
| `get_status()` | `get_history()` |
| `load_workflow()` | `load()` |

### 11. AmbienceSpec Uses `type` Not `ambience_type`
**Wrong:** `AmbienceSpec(ambience_id="amb_001", ambience_type=AmbienceType.INTERIOR_QUIET, ...)`
**Correct:** `AmbienceSpec(ambience_id="amb_001", type=AmbienceType.INTERIOR_QUIET, ...)`

### 12. SonicManifest Uses `manifest_id` Not `job_id`
**Wrong:** `SonicManifest(job_id="job_001", shot_plans=[...])`
**Correct:** `SonicManifest(manifest_id="manifest_001", project_id="proj_001", shot_plans=[...])`

### 13. VoiceConfig Uses `speaking_rate` Not `speed`
**Wrong:** `config.speed`, `config.pitch`
**Correct:** `config.speaking_rate` (0.5 to 2.0), `config.pitch_shift` (-12 to +12 semitones)

### 14. WorkflowLoader.load() Takes NAME, Not Path
**Wrong:** `loader.load(Path("workflows/refine_freelong.json"))`
**Correct:** `loader.load("refine_freelong")` - Just the name, loader finds the file
**Why:** WorkflowLoader manages its own workflow directory internally.

### 15. Cross-Module Imports Use `..` for Parent Directory
**Error:** `ModuleNotFoundError: No module named 'client'`
**Wrong (in src/studio/):** `from .client import ComfyClient`
**Correct:** `from ..comfy_client.client import ComfyClient`
**Pattern:** `.module` = same directory, `..module` = parent's sibling directory

### 16. TTSProvider Has No MOCK Value
**Error:** `AttributeError: type object 'TTSProvider' has no attribute 'MOCK'`
`TTSProvider` only has: `ELEVENLABS`, `OPENAI`, `LOCAL`
**Note:** `AmbienceProvider` and `FoleyProvider` DO have `.MOCK` variants. TTSProvider doesn't.

### 17. tests/conftest.py Needs Path Setup
**Error:** `ModuleNotFoundError: No module named 'src'`
**Required in conftest.py:**
```python
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

---

## Claude Judgment Errors (Likely to Repeat)

### J1. Hiding Warnings Instead of Questioning Them
When IDE showed "Import 'clip' could not be resolved", immediately reached for `# type: ignore`. **Better:** Ask "Are these warnings useful?" - warnings served as documentation that optional dependencies aren't installed.

### J2. Putting Annotations on Wrong Lines
Added `# type: ignore` to fallback `= None` lines instead of actual `import` lines.
```python
# WRONG - comment on fallback line doesn't help
except ImportError:
    clip_module = None  # type: ignore

# RIGHT - comment on import line
try:
    import clip  # type: ignore[import-not-found]
```

### J3. Over-Engineering Before Questioning Necessity
Built elaborate optional dependency handling before asking "should we just install these dependencies?" Sometimes `pip install Pillow` is the right answer, not 50 lines of fallback code.

### J4. Assuming Previous Code is Correct
When building `pass1_generator.py`, trusted that existing interfaces were complete without verification. **Better:** Always `view` actual source files before building integrations.

---

## Sonic Module Quick Reference

| Class | Required Fields | Common Mistakes |
|-------|-----------------|-----------------|
| `DialogueLine` | `line_id`, `character_id`, `text`, `start_time_sec` | `emotion` default is `None`, not `NEUTRAL` |
| `VoiceConfig` | `character_id` | `speaking_rate` not `speed`, `pitch_shift` not `pitch` |
| `AmbienceSpec` | `ambience_id`, `type`, `description`, `duration_sec` | `type` not `ambience_type` |
| `SonicManifest` | `manifest_id`, `project_id` | Not `job_id` |
| `ShotAudioPlan` | `shot_id`, `scene_id`, `duration_sec` | No `.validate()` method (it's on `SonicManifest`) |

---

### 18. Workflow JSON Doesn't Accept `_meta` Keys
**Error:** `ValueError: Workflow validation failed: ["Node _meta: missing 'class_type'"]`
**Why:** Loader skips `_` prefixed FILES but NOT `_` prefixed KEYS in workflow dict. All keys are treated as ComfyUI nodes.
**Prevention:** Don't add metadata keys to workflow JSONs. Document in README or code comments.

---

## The Bridge Frame Problem (Architecture)

```
Shot A (ends)                    Shot B (starts)
|                                |
v                                v
+----------+                    +----------+
|Frame 144 | ---- BRIDGE -----> |Frame 1   |
+----------+                    +----------+
|                                |
| Extract last frame             | Must match:
|                                |  - Visual continuity (I2V)
v                                |  - Character identity (LoRA)
+----------------------------------------------------------+
|           pass1_img2vid_lora.json  <-- THIS FILE         |
|                                                          |
|  Inputs:                                                 |
|    - INIT_IMAGE: last frame of Shot A                    |
|    - LORA_PATH: alice_v1.safetensors                     |
|    - PROMPT: "Alice walks to the door"                   |
|                                                          |
|  Guarantees:                                             |
|    - Frame 1 of Shot B visually matches Frame 144        |
|    - Alice face remains consistent                       |
+----------------------------------------------------------+
```

---

### 20. Early Return Hides Subsequent Logic Paths
**Error:** I2V workflows never used LoRA even when character had trained LoRA

**Wrong:**
```python
def _select_workflow_template(self, job):
    if job.has_init_frame:
        return self.WORKFLOW_IMG2VID  # Returns early, never checks LoRA!
    if job.has_lora:
        return self.WORKFLOW_WITH_LORA
```

**Correct:**
```python
def _select_workflow_template(self, job):
    has_lora = job.character_refs and job.character_refs[0].has_lora()
    if job.has_init_frame:
        if has_lora:
            return self.WORKFLOW_IMG2VID_LORA
        return self.WORKFLOW_IMG2VID
```

**Prevention:** When function has multiple independent dimensions (I2V vs T2V, LoRA vs no-LoRA), extract state into booleans first, then use decision matrix.

### 21. Orphan Nodes Waste VRAM
**Error:** `bridge_ipadapter.json` had orphan node `encode_face_ref` that nothing used

**The Bug:**
```json
"encode_face_ref": { ... },  // Created but never referenced
"apply_ipadapter": {
    "image": ["prep_face_ref", 0]  // Uses prep, not encode!
}
```

**Why Contract Tests Missed It:** JSON valid, node has class_type, connections valid, no dangling references - all OK.
**Why Stress Test Caught It:** Traced backwards from SaveImage, found `encode_face_ref` unreachable.
**Prevention:** Run orphan detection on all workflows. Orphans indicate copy-paste errors.

### 22. Enum/Class Defined in Wrong Module
**Error:** `ImportError: cannot import name 'AmbienceProvider' from 'src.sonic.types'`
- `AmbienceProvider` is in `ambience.py`
- `FoleyProvider` is in `foley.py`
- `DialogueLine` IS in `types.py`

**Prevention:** `grep -r "class AmbienceProvider" src/`

### 23. JobStatus Values
**Error:** `AttributeError: type object 'JobStatus' has no attribute 'RUNNING'`
Use `GENERATING` not `RUNNING`.
**Available:** `PENDING`, `GENERATING`, `AUDITING`, `FAILED`, `APPROVED`, `REFINING`, `COMPLETE`

### 24. Mock Implementation Missing Lifecycle Methods
**Error:** `AttributeError: 'MockBridgeEngine' object has no attribute 'shutdown'`
Mocks must implement ALL base class methods including lifecycle: `generate()`, `health_check()`, `shutdown()`

### 25. main.py Calls Methods That Don't Exist
**Error:** `AttributeError: 'CheckpointManager' object has no attribute 'get_completed_scenes'`
main.py was written expecting methods that were never implemented. Fix: Add missing methods to CheckpointManager.

### 26. InterpolationSpec Missing Required `shot_id`
**Error:** `TypeError: InterpolationSpec.__init__() missing 1 required positional argument: 'shot_id'`
Required: `input_path`, `output_path`, `shot_id`, `target_fps`

### 27. EntityRef Requires Objects, Not Strings
**Error:** `TypeError: EntityRef() argument after ** must be a mapping, not str`

**Wrong:**
```json
"characters": ["alice"]
```

**Correct:**
```json
"characters": [{"entity_id": "alice", "entity_type": "character", "display_name": "Alice"}]
```

### 28. I2V Workflow Node Parameter Mismatches
**Errors:** `Required input is missing: batch_size` and `unexpected keyword argument 'image'`
**Fixes:** Add `batch_size = 1`, use `start_image` not `image` for WanImageToVideo

### 29. Nested Config Access
**Error:** `AttributeError: 'Config' object has no attribute 'comfyui_host'`

**Config structure is NESTED:**
```python
# Wrong: config.comfyui_host, config.workflows_dir
# Correct: config.comfyui.host, config.paths.workflows_dir
```

**Nested config classes:** `config.comfyui`, `config.paths`, `config.generation`, `config.audit`, `config.sonic`, `config.post`

### 30. Environment Variable Naming for Nested Pydantic
**Error:** `COMFYUI_URL` env var ignored

**Pattern:** `{PREFIX}_{SECTION}__{FIELD}` (double underscore)
```bash
# Wrong: COMFYUI_HOST="..."
# Correct: CONTINUUM_COMFYUI__HOST="..."
```

### 31. Passing Dict When Function Expects Dataclass
**Error:** `'dict' object has no attribute 'source_exists'`
**Wrong:** `bridge_engine.generate({"source_video": path, ...})`
**Correct:** `bridge_engine.generate(BridgeSpec.from_shots(...))`

### 32. Method Naming Inconsistency
**Error:** `'ComfyClient' object has no attribute 'upload_image'`
**Why:** Different development phases used different naming conventions.
**Fix:** Added alias methods: `upload_image()` -> `upload_file()`, `submit()` -> `submit_workflow()`

### 33. WorkflowLoader Method Name
**Error:** `'WorkflowLoader' object has no attribute 'inject_params'`
**Wrong:** `loader.inject_params(workflow, params)`
**Correct:** `loader.inject(template, params)` or `loader.load_and_inject(name, params)`

### 34. ComfyClient Constructor
**Error:** `TypeError: ComfyClient.__init__() got an unexpected keyword argument 'port'`
**Wrong:** `ComfyClient(host=host, port=port)`
**Correct:** `ComfyClient(host=config.comfyui.host)` - host is full URL with port, or `ComfyClient(config=config.comfyui)`

### 35. ComfyUI KSampler Seed Must Be >= 0
**Error:** `Value -1 smaller than min of 0`
**Wrong:** `seed if seed >= 0 else -1`
**Correct:** `seed if seed >= 0 else random.randint(0, 2**32 - 1)`
ComfyUI nodes validate inputs strictly. Never assume sentinel values like `-1` are accepted.

### 36. Architecture Mismatch: Wrong Model for Bridge Frames
**Issue:** `bridge_basic.json` used SDXL for bridge frame generation

**Why SDXL Bridge Was Wrong:**
1. SDXL generates single static image, not video
2. Different model family = style mismatch risk
3. Requires extra 6.5GB model download
4. Generated bridge image never used by Shot 2

**Correct:** Shot 1 last frame -> Wan I2V -> Shot 2 video
**Prevention:** Use same model family for all shots. Leverage I2V capabilities of primary renderer.

### 37. Workflow JSON `_meta` Nodes Break Validation
Same as #18. Every top-level key must be valid ComfyUI node with `class_type`.

### 38. ComfyJob Uses `prompt_id` Not `job_id`
**Wrong:** `client.wait_for_completion(job.job_id)`
**Correct:** `client.wait_for_completion(job.prompt_id)`

### 39. ComfyJob Outputs Are Nested Dict
**Wrong:** `job.output_images[0]`
**Correct:**
```python
for node_id, outputs in job.outputs.items():
    if "images" in outputs:
        items = outputs["images"]
        if items:
            filename = items[0].get("filename")
```

### 40. SceneGraph Requires Full Schema
**Error:** `KeyError: 'scene_id'`
Each shot must include: `shot_id`, `scene_id`, `index`, `duration_sec`, `prompt`, `shot_type`, `characters`, `props`, `chunks`, `dialogue`

### 41. I2V 14B Models Need Extended Timeout
**Error:** `Job timed out after 300s`
| Model | Params | Typical Gen Time (4s video) |
|-------|--------|----------------------------|
| T2V 1.3B | 1.3 billion | ~2-3 min |
| I2V 14B | 14 billion | ~15-20 min |

**Fix:** `export CONTINUUM_COMFYUI__TIMEOUT_SEC=1200` (20 minutes)

### 42. DWPreprocessor Requires Custom Node
**Error:** `Cannot execute because node DWPreprocessor does not exist`
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
pip install -r comfyui_controlnet_aux/requirements.txt
```

### 43. Relative Import Across Package Boundaries
**Error:** `No module named 'src.studio.reviewer'`
**Wrong (in pass1_generator.py):** `from .reviewer import ReviewRequest`
**Correct:** `from src.audit.reviewer import ReviewRequest`
Relative imports only work within same package. Cross-package requires absolute import.

### 44. Scene Has `duration_sec`, Not `total_duration_sec`
**Wrong:** `scene.total_duration_sec`
**Correct:** `scene.duration_sec` (property that sums shot durations)

### 45. Workflow Names Must Match JSON Files
**Error:** `Workflow template 'refine_freelong' not found`
Workflow names must match actual `.json` files in repository.
**Prevention:** `ls *.json | grep -i refine`

### 46. ArcFace Similarity Can Exceed 1.0
**Error:** `Severity must be 0.0-1.0, got 1.0883`
Floating point precision can cause similarity > 1.0.
**Wrong:** `severity = 1.0 - similarity`
**Correct:** `severity = max(0.0, min(1.0, 1.0 - similarity))`

### 47. Engines with ComfyClient Must shutdown()
**Error:** `ERROR | asyncio | Unclosed client session`
Each engine with `_client: ComfyClient` must implement:
```python
async def shutdown(self) -> None:
    if self._client:
        await self._client.disconnect()
        self._client = None
```

### 48. RIFE VFI Node Installation
**Error:** `Cannot execute because node RIFE VFI does not exist`
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation
pip3 install -r ComfyUI-Frame-Interpolation/requirements-no-cupy.txt
sed -i 's/ops_backend: "cupy"/ops_backend: "taichi"/' ComfyUI-Frame-Interpolation/config.yaml
mkdir -p ComfyUI-Frame-Interpolation/ckpts
wget -O ComfyUI-Frame-Interpolation/ckpts/rife47.pth "https://github.com/styler00dollar/VSGAN-tensorrt-docker/releases/download/models/rife47.pth"
```

### 49. Enum Names Must Match Exactly
**Error:** `AttributeError: 'FoleyCategory' has no attribute 'DOORS'. Did you mean: 'DOOR'?`
Wrong -> Correct: `DOORS`->`DOOR`, `ELECTRONICS`->`ELECTRONIC`, `COMPLETED`->`COMPLETE`

### 50. ComfyUI Needs Files Uploaded First
**Error:** `Invalid video file: workspace/output/video.mp4`
Files must be uploaded to ComfyUI server first:
```python
upload_result = await client.upload_file(path, subfolder="", file_type="input")
params = {"INPUT_VIDEO": upload_result.get("name")}
```

### 51. RIFE VFI Requires `clear_cache_after_n_frames`
**Error:** `Required input is missing: clear_cache_after_n_frames`
Add `"clear_cache_after_n_frames": 10` to RIFE VFI inputs.

### 52. RIFE Result Type Mismatch
**Error:** `unsupported operand type(s) for *: 'dict' * 'float'`
When workflow returns, result may be dict before proper parsing. Extract duration as float first.

### 53. MixResult Has No `.success` Attribute
**Error:** `'MixResult' object has no attribute 'success'`
**Correct:** `if result.output_path and result.output_path.exists():` or `if result.duration_sec > 0:`

### 54. Short Videos Break Frame Extraction
**Error:** `Expected output file not created: sample_04.png`
Short videos (< 1 second) may not have enough frames. Check duration and adjust sample count:
```python
if duration < 2.0:
    effective_samples = max(1, min(2, int(duration * 2)))
```

### 55. KSamplerBatch Node Not Available
**Error:** `Cannot execute because node KSamplerBatch does not exist`
It's from ComfyUI-KJNodes but may not exist. Fallback to `refine_vid2vid_simple.json` with standard KSampler.

### 56. DWPreprocessor Needs Model Download
May need onnxruntime-gpu and DWPose models. Alternative: use OpenPosePreprocessor.

### 57. ComfyJob.progress is Dict, Not Float
**Wrong:** `progress_pct = 0.4 + (job.progress * 0.5)`
**Correct:**
```python
progress_value = job.progress.get("value", 0)
progress_max = job.progress.get("max", 100)
progress_pct = float(progress_value) / float(progress_max)
```

### 58. MixResult Uses `.status`, Not `.success`
**Correct:** `if result.status == AudioGenerationStatus.COMPLETE and result.output_path:`

### 59. Short Videos Break Frame Extraction (Extended)
Videos under 2 seconds may fail at late positions (0.7, 0.9). Wrap in try/except, validate file exists.

---

## Identity Preservation Architecture

### 60. Wan I2V Does NOT Need IP-Adapter
**Wrong Assumption:** Need `pass1_img2vid_ipadapter.json` for identity in I2V
**Correct:** Identity is locked at Bridge Engine stage (SDXL + IP-Adapter), then passed to Wan I2V via CLIP Vision encoding of the bridge frame.

**Why:**
- Wan 2.1 does NOT have native IP-Adapter support in ComfyUI
- Correct flow: Bridge Engine (SDXL+IPAdapter) -> bridge_frame.png -> Wan I2V (CLIP Vision encodes frame)

**Prevention:** Don't try to add IP-Adapter to Wan workflows. Identity anchoring happens BEFORE video generation.

---

## World State Tracking (Architecture Pattern)

### 61. Full Implementation Pattern

**The Problem:** Props "teleport" between shots because system forgets state changes.
- Shot 3: "Alice picks up the sword"
- Shot 4: Alice rendered without sword (system forgot)
- Shot 5: Sword back on table (teleportation)

**The Solution - 4 File Pattern:**

| File | Role | Key Addition |
|------|------|--------------|
| `shot_event_parser.py` | Extracts events from descriptions | Pattern matching + explicit events |
| `scene_graph.py` | Stores explicit events | `Shot.events: List[Dict]` field |
| `main.py` | Wires parser to WorldState | `_update_world_state_from_shot()` |
| `pass1_generator.py` | Injects state into prompts | `_get_world_state_context()` |

**Data Flow:**
```
Shot.description -> ShotEventParser -> List[StateEvent]
Shot.events -> WorldState.apply_event()
Next shot's prompt: "Current scene state: sword: held by alice"
```

**Event Types Supported:**
| Event Type | Example | Result |
|------------|---------|--------|
| `pickup` | "Alice picks up sword" | `sword.position = held_by:alice` |
| `drop` | "She drops mug" | `mug.position = floor` |
| `move` | "Places book on table" | `book.position = table` |
| `state_change` | "Mirror shatters" | `mirror.state = broken` |
| `transfer` | "Hands key to Bob" | `key.holder = bob` |

---

### 62. Claude Project Files Are FLATTENED
**Problem:** Claude's `/mnt/project/` shows all files at root level
**Reality:** Actual VS Code project uses nested `src/` structure

**Mapping:**
| Claude path | Actual path | Import |
|-------------|-------------|--------|
| `/mnt/project/scene_graph.py` | `src/director/scene_graph.py` | `from src.director.scene_graph` |
| `/mnt/project/pass1_generator.py` | `src/studio/pass1_generator.py` | `from src.studio.pass1_generator` |
| `/mnt/project/identity_checker.py` | `src/audit/identity_checker.py` | `from src.audit.identity_checker` |

**Prevention:** Always use `src.` prefix in import statements.

### 63. Entity Classes Use `entity_id`, Not `id`
**Error:** `AttributeError: 'CharacterEntity' object has no attribute 'id'`
All entity classes: `CharacterEntity.entity_id`, `LocationEntity.entity_id`, `PropEntity.entity_id`

### 64. Import Paths Must Be Absolute from `src.`
**Error:** `ModuleNotFoundError: No module named 'world_state'`
**Wrong:** `from world_state import EventType`
**Correct:** `from src.director.world_state import EventType`

### 65. list_characters() Returns Objects, Not IDs
**Error:** `TypeError: unhashable type: 'CharacterEntity'`
**Wrong:** `known.update(self.consistency_dict.list_characters())`
**Correct:** `known.update(c.entity_id for c in self.consistency_dict.list_characters())`

### 66. Pod ID: Watch for `1` vs `l`
**Error:** `WSServerHandshakeError: 404`
**Always copy Pod ID from browser URL, never type manually.** `1` (one) looks like `l` (lowercase L).

### 67. RunPod Template Auto-Starts ComfyUI
**Error:** `OSError: [Errno 98] address already in use`
Check if ComfyUI is already running before starting:
```bash
curl -s http://localhost:8188/system_stats | head -c 100
```

### 68. Workflow Documentation Convention
Keys prefixed with `_` (like `_comment`, `_architecture_ref`) are:
- Preserved in template files
- Skipped during validation
- Stripped before submission to ComfyUI

### 69-70. Workflows May Reference Non-Existent Nodes
`refine_vid2vid_temporal.json` used `KSamplerBatch` and `TemporalSmooth` which don't exist publicly.
**Prevention:** Verify ALL `class_type` values exist: `grep "class_type" workflow.json`

### 71. Use `wait_for_completion()`, Not Manual Loop
**Broken Pattern:**
```python
job = await client.submit(workflow)
while not job.is_terminal():  # Never becomes true!
    await asyncio.sleep(0.5)
```

**Working Pattern:**
```python
comfy_job = await client.submit_workflow(workflow)
completed_job = await client.wait_for_completion(comfy_job.prompt_id, timeout_sec=600)
```

**Why broken fails:** WebSocket messages update tracking inside the client, not the returned object.

### 72. Vid2Vid Without Temporal = Flicker
Plain `KSampler` processes frames independently = flickering faces.
**Workaround:** Use `--no-pass2` flag to skip refinement until proper temporal processing available.

---

## Identity Experiments (73-78)

### 73. WanAnimateToVideo is NOT an I2V Node
**Error:** Identity dropped from 97% to 22%

**Critical Distinction:**
| Node | `start_image` | `clip_vision_output` | Behavior |
|------|--------------|---------------------|----------|
| `WanImageToVideo` | YES | YES | Frame 1 IS start_image (I2V) |
| `WanAnimateToVideo` | NO | YES | Generates FROM SCRATCH (T2V) |

### 74. face_video Input Provides Per-Frame Identity
`WanAnimateToVideo`'s `face_video` accepts repeated face reference as video frames.
```json
"repeat_face_ref": {
  "class_type": "RepeatImageBatch",
  "inputs": {"image": ["load_face_ref", 0], "amount": "{{FRAMES}}"}
},
"wan_animate": {
  "inputs": {"face_video": ["repeat_face_ref", 0]}
}
```
Result: **98.32% identity** - this is the IP-Adapter equivalent for Wan video.

### 77. Identity vs Expression: Core Disentanglement Problem
**Why face_video froze expressions:** Pixel-level conditioning on every frame = "Make every frame look EXACTLY like these pixels"
**Need:** Embedding-level identity (ArcFace) + separate expression control

**Research Solutions:**
- IP-Adapter FaceID at 0.5-0.7 weight (not 1.0)
- Keyframe-only conditioning (first/last, not every frame)
- Multi-reference images with DIFFERENT expressions
- ConsisID/Magic Mirror dual-branch architectures

### 78. Comprehensive Results

| Approach | Identity | Expression | Verdict |
|----------|----------|------------|---------|
| WanImageToVideo + hero frame | 97% | Natural | **CURRENT BEST** |
| face_video per-frame | 98% | Frozen | Reject |
| WanFirstLastFrameToVideo | ~95% | Changes | Artifacts, Reject |
| WanPhantomSubjectToVideo | ~70% | Changes | Poor quality, Reject |

**Key Insight:** Hero frame generation does heavy lifting. SDXL + IP-Adapter creates identity anchor at frame 0. For longer clips, solution is likely LoRA-based.

---

## RunPod Setup Issues

### 79. Blank Page / 502 Fix
**Cause:** Missing scikit-image
**Fix:** `pip3 install scikit-image` (no restart needed)

### 80. HunyuanCustom Text Encoder Downloads
**Correct Sources:**
```bash
# CLIP-L from comfyanonymous
huggingface-cli download comfyanonymous/flux_text_encoders clip_l.safetensors --local-dir ./

# LLaVA-Llama3 from Comfy-Org
huggingface-cli download Comfy-Org/HunyuanVideo_repackaged split_files/text_encoders/llava_llama3_fp16.safetensors --local-dir ./
```

### 81. HunyuanCustom Extensions Required
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper
git clone https://github.com/pollockjj/ComfyUI-MultiGPU
pip3 install -r ComfyUI-HunyuanVideoWrapper/requirements.txt
```

### RunPod HunyuanVideo Starter Pack
**Error:** `Cannot execute because node HyVideoBlockSwap does not exist`
**Root Cause:** Missing diffusers, accelerate
```bash
pip3 install diffusers accelerate
pkill -f "python3.*main.py"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > comfyui.log 2>&1 &
```

---

### 82. HunyuanCustom Identity Failure

**Problem:** Identity scores failing (0.10-0.38) despite validated workflow working in UI.

**Root Cause 1: noise_aug_strength**
```json
// BROKEN: "NOISE_AUG_STRENGTH": 0.025
// WORKING: "NOISE_AUG_STRENGTH": 0
```
0.025 = 2.5% noise corrupts identity signal. 0 = pure image, identity preserved.

**Root Cause 2: Frame Count**
With `noise_aug_strength=0`, need 25+ frames for motion. 13 frames = frozen video.

**Workflow Caching Gotcha:** WorkflowLoader caches templates. Editing JSON requires restarting Python.

### 83. Debugging Strategy: Isolate with Minimal Reproducers
1. Establish ground truth (works in UI)
2. Create bash script submitting exact same workflow
3. If bash works -> bug in Python code
4. Diff the workflows node-by-node

---

## CRITICAL: Bridge Frame Rules

### 84. Bridge Frames MUST Re-Anchor to Canonical Identity

**THE CORE PRINCIPLE (DO NOT FORGET):**
```
WITHOUT bridge re-anchoring (WRONG):
Shot 1: hero -> Wan -> 98%
Shot 2: 98% -> Wan -> 94% (drift compounds!)
Shot 3: 94% -> Wan -> 88%
... identity degrades exponentially

WITH bridge re-anchoring (CORRECT):
Shot 1: hero -> Wan -> 98%
Shot 2: BRIDGE(hero) -> Wan -> 98% (reset!)
Shot 3: BRIDGE(hero) -> Wan -> 98%
... identity stays locked
```

**NEVER suggest:**
- "Skip bridge SDXL and use last_frame directly"
- "Just pass last_frame to next shot"
- "Remove bridge step to avoid artifacts"

If bridge has artifacts, fix SDXL bridge step - don't skip re-anchoring.

### 85. Hero Frame Strategy: Separate Pose from Identity
```python
BridgeSpec:
  source_frame: Path          # Last frame - for pose extraction (ControlNet)
  identity_source_frame: Path # Hero frame - for img2img source
```

**Data Flow:**
```
hero_frame (canonical) -> VAEEncode -> latent source (identity locked)
last_frame (drifted)   -> ControlNet -> pose conditioning (continuity)
-> Bridge output (best of both)
```

### 86. Wan VAE "Overbaked First Frames" Fix
Wan's VAE decoder produces artifacts in first 2-3 frames of I2V.
**Fix:** Request +3 frames, trim first 3 after download.

---

### 87. Wan 2.1 LoRA Training - Complete Requirements

**CORRECT TOOL:** `musubi-tuner` (kohya-ss)
**WRONG TOOLS:** sd-scripts (UNet not DiT), diffusion-pipe (path conflicts), ai-toolkit (dependency issues)

**I2V vs T2V:**
| Requirement | T2V | I2V |
|-------------|-----|-----|
| CLIP model | No | **Required** |
| `--i2v --clip` flags | No | **Required** |

**T5 Format:** Need original `.pth` format, not safetensors repackaged.

**Pre-caching MANDATORY:**
```bash
python3 wan_cache_latents.py --dataset_config dataset.toml --vae ... --clip ... --i2v
python3 wan_cache_text_encoder_outputs.py --dataset_config dataset.toml --t5 ...
```

**VRAM:** 14B on 24GB needs `--blocks_to_swap 35`
**Key Flag:** `--network_module networks.lora_wan` (MUST use for Wan)

---

### 88. Consistency Dict Auto-Discovery

**Architecture:** Scene Graph (project.json) = WHO WHERE. Consistency Dict (bible.json) = WHAT they LOOK LIKE.

**Auto-discovery order:**
1. `{project_stem}_consistency.json`
2. `consistency.json` in same dir
3. `bible.json` in same dir

**Don't embed bible in project JSON - it's ignored.**

### 89. Remote Path Validation
Mac orchestrator can't validate RunPod paths with `path.exists()`.

```python
def _is_remote_path(path):
    remote_prefixes = ("/workspace/", "/comfyui/", "/models/", "/root/")
    return any(str(path).startswith(p) for p in remote_prefixes)

def _path_exists_or_remote(path):
    return _is_remote_path(path) or path.exists()
```

---

### 90. Anime Pivot & Test Demo Audio Gap

**Style Types:**
- `REALISTIC`: ArcFace threshold 0.50
- `ANIME`/`WEBTOON`: CLIP threshold 0.85

**Testing vs Production:**
| Scenario | Characters | LoRA Required? |
|----------|-----------|----------------|
| Testing | Goku, Naruto (well-known) | No - base model knows them |
| Production | Original/custom | **YES** - custom LoRA required |

**test_demo_matrix_zero.py:** Video-only pipeline, tests Hero/Bridge/I2V/FFmpeg. No Sonic Engine = no audio.

---

## Process Checklist

### Before Writing New Code
1. Check source of truth file for interface
2. Grep for class/method names to verify exact spelling
3. Check ALL required fields in dataclasses (no `= default` = required)
4. Check ALL abstract methods when subclassing ABCs

### Before Running Tests
1. Import check: `python -c "from module import Class; print('OK')"`
2. Collection only: `pytest tests/file.py --collect-only`
3. Full tests: `pytest tests/file.py -v`

### When Tests Fail
1. Read exact error message - usually names the missing field/method
2. Check source of truth file
3. Fix actual bug (might be in production code, not test mock)
4. Update this document

---

## Audio Integration Lessons (Session 26)

### 91. Replicate SDK 1.x Returns Iterators
`client.run()` returns an iterator, not direct output. Must collect:
```python
# Wrong - old SDK
output = client.run(model, input={...})

# Right - new SDK 1.x
result_iter = client.run(model, input={...})
outputs = list(result_iter)
output = outputs[-1] if outputs else None
```

For reliable URL output, use predictions API:
```python
prediction = client.predictions.create(version="hash", input={...})
prediction.wait()
output_url = prediction.output  # Returns URL, not raw bytes
```

### 92. ElevenLabs SDK API Changed
Old: `client.generate()` → New: `client.text_to_speech.convert()`
```python
# Old (broken)
audio = await client.generate(text=text, voice=voice)

# New (working)
audio_gen = client.text_to_speech.convert(
    text=text,
    voice_id=voice_id,
    model_id="eleven_monolingual_v1",
    voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.8)
)
audio_bytes = b"".join([chunk async for chunk in audio_gen])
```

### 93. Replicate API Parameter Types Matter
AudioLDM expects `duration` as **string**, not number:
```python
# Wrong
input={"duration": 12.5}  # 422 Error

# Right
input={"duration": "12.5"}  # Works
```

### 94. Wav2Lip Doesn't Work with Anime
Wav2Lip's face detection requires **real human faces**. Anime characters cause:
```
replicate.exceptions.ModelError: list index out of range
```
This means "no face detected." For anime lip-sync, need:
- Musetalk (ComfyUI)
- Anime-specific lip-sync model
- Simple programmatic mouth animation

### 95. Lambda Closures in Async Executors
File handles in lambdas may close before executor runs:
```python
# Wrong - closure captures closed file handles
with open(path, "rb") as f:
    output = await loop.run_in_executor(None, lambda: client.run(input={"file": f}))

# Right - define function that opens files inside
def run_model():
    with open(path, "rb") as f:
        return client.run(input={"file": f})
output = await loop.run_in_executor(None, run_model)
```

### 96. FFmpeg Segment Extraction
When extracting video segments, `-c copy` may fail at non-keyframe boundaries:
```bash
# Fast but may have artifacts at boundaries
ffmpeg -ss START -i input.mp4 -t DURATION -c copy output.mp4

# Slower but clean cuts
ffmpeg -ss START -i input.mp4 -t DURATION -c:v libx264 -preset fast output.mp4
```

### 97. Dialogue Timing Must Not Exceed Video Duration
If dialogue `start_time_sec` exceeds video duration, segment extraction fails silently (creates empty/tiny files). Always validate:
```python
video_duration = get_video_duration(video_path)
for line, abs_time in dialogue_lines:
    if abs_time >= video_duration:
        print(f"WARNING: Dialogue at {abs_time}s exceeds video ({video_duration}s)")
```
