# Lessons Learned: Interface Mismatches & Wrong Assumptions

> **Purpose:** A living document tracking assumptions that caused errors, their corrections, and how to avoid repeating them. Update this whenever a new mismatch is discovered.
>
> **Last Updated:** 2025-12-16 (Added Claude judgment errors J1-J4)

---

## Quick Reference: Source of Truth Files

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

## Error Log

### 1. Scene.__init__() Missing `title` Argument

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: Scene.__init__() missing 1 required positional argument: 'title'` |
| **Wrong Assumption** | `Scene` only needs `scene_id`, `index`, `description` |
| **Correct Interface** | `Scene` requires `title` as a required positional argument |
| **Source of Truth** | `src/director/scene_graph.py` lines 420-445 |

**Wrong:**
```python
scene = Scene(scene_id="s1", index=0, description="Test")
```

**Correct:**
```python
scene = Scene(scene_id="s1", index=0, title="Test Title", description="Test")
```

**Prevention:** Always check dataclass field order. Required fields without defaults must be provided.

---

### 2. RenderResult Missing Required Fields

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `RenderResult.__init__() missing 3 required positional arguments: 'duration_sec', 'resolution', and 'renderer_type'` |
| **Wrong Assumption** | `RenderResult` only needs `video_path`, `frame_count`, `fps`, `metadata` |
| **Correct Interface** | `RenderResult` requires 6 fields before optional ones |
| **Source of Truth** | `src/renderers/base.py` lines 200-230 |

**Wrong:**
```python
RenderResult(
    video_path=output_path,
    frame_count=120,
    fps=12.0,
    metadata={"mock": True},
)
```

**Correct:**
```python
RenderResult(
    video_path=output_path,
    frame_count=120,
    fps=12.0,
    duration_sec=10.0,
    resolution=(1280, 720),
    renderer_type=RendererType.MOCK,
    metadata={"mock": True},
)
```

**Prevention:** When mocking a dataclass, check ALL fields. Dataclass field order matters ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â required fields come before optional ones with defaults.

---

### 3. BaseRenderer Missing Abstract Methods

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: Can't instantiate abstract class MockRenderer without an implementation for abstract methods 'estimate_cost', 'estimate_time'` |
| **Wrong Assumption** | `BaseRenderer` only requires `generate()`, `initialize()`, `shutdown()` |
| **Correct Interface** | Also requires `estimate_cost(job) -> float` and `estimate_time(job) -> float` |
| **Source of Truth** | `src/renderers/base.py` lines 340-375 |

**Wrong:**
```python
class MockRenderer(BaseRenderer):
    async def generate(self, job, callback=None): ...
    async def initialize(self): ...
    async def shutdown(self): ...
```

**Correct:**
```python
class MockRenderer(BaseRenderer):
    async def generate(self, job, callback=None): ...
    async def initialize(self): ...
    async def shutdown(self): ...
    def estimate_cost(self, job: JobSpec) -> float: return 0.01
    def estimate_time(self, job: JobSpec) -> float: return 10.0
```

**Prevention:** When subclassing an ABC, grep for `@abstractmethod` to find ALL required methods:
```bash
grep -n "@abstractmethod" src/renderers/base.py
```

---

### 4. Wrong Method Name: `compare_to_reference` vs `compare`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `'MockIdentityChecker' object has no attribute 'compare_to_reference'` |
| **Wrong Assumption** | Identity checker has a `compare_to_reference(reference_path, target_path)` method |
| **Correct Interface** | Method is `compare(source_frame, target_frame, character_hint=None)` |
| **Source of Truth** | `src/audit/identity_checker.py` lines 302-321 |
| **Impact** | **This was a real bug in main.py, not just a test issue** |

**Wrong (in main.py):**
```python
comparison = await self.identity_checker.compare_to_reference(
    reference_path=ref_path,
    target_path=render_result.video_path,
)
```

**Correct:**
```python
comparison = await self.identity_checker.compare(
    source_frame=ref_path,
    target_frame=render_result.video_path,
)
```

**Prevention:** Before calling any method, verify it exists:
```bash
grep -n "def compare" src/audit/identity_checker.py
```

---

### 5. Wrong Class Name: `ComfyBridgeEngine` vs `ComfyUIBridgeEngine`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `"ComfyBridgeEngine" is not defined` |
| **Wrong Assumption** | Class is named `ComfyBridgeEngine` |
| **Correct Interface** | Class is named `ComfyUIBridgeEngine` (with "UI") |
| **Source of Truth** | `src/studio/bridge_engine.py` line 434 |

**Wrong:**
```python
from src.studio.bridge_engine import ComfyBridgeEngine
self.bridge_engine = ComfyBridgeEngine()
```

**Correct:**
```python
from src.studio.bridge_engine import ComfyUIBridgeEngine
self.bridge_engine = ComfyUIBridgeEngine()
```

**Prevention:** Use grep or IDE autocomplete to verify exact class names:
```bash
grep -n "^class.*BridgeEngine" src/studio/bridge_engine.py
```

---

### 6. Wrong Parameter Name: `base_delay` vs `base_delay_sec`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: RetryConfig.__init__() got an unexpected keyword argument 'base_delay'` |
| **Wrong Assumption** | Parameter is named `base_delay` |
| **Correct Interface** | Parameter is named `base_delay_sec` (with `_sec` suffix) |
| **Source of Truth** | `src/core/error_recovery.py` line 155 |

**Wrong:**
```python
@retry_async(RetryConfig(max_attempts=3, base_delay=1.0))
```

**Correct:**
```python
@retry_async(RetryConfig(max_attempts=3, base_delay_sec=1.0))
```

**Prevention:** The codebase uses `_sec` suffix for time durations. Always check parameter names before using.

---

## Naming Conventions Discovered

| Pattern | Convention | Examples |
|---------|------------|----------|
| Time durations | `_sec` suffix | `base_delay_sec`, `duration_sec`, `timeout_sec` |
| ComfyUI classes | Include "UI" | `ComfyUIBridgeEngine`, `ComfyUIConfig` |
| Entity references | `EntityRef.type()` factory | `EntityRef.character("id")`, `EntityRef.location("id")` |
| Async methods | `async def` prefix | All cloud/IO operations are async |
| Abstract methods | Must implement all | Check with `grep "@abstractmethod"` |

---

## Verification Commands

Run these before assuming an interface:

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

## Process Improvements

### Before Writing New Code
1. **Check source of truth file** for the interface you're using
2. **Grep for class/method names** to verify exact spelling
3. **Check ALL required fields** in dataclasses (fields without `= default` are required)
4. **Check ALL abstract methods** when subclassing ABCs

### Before Running Tests
1. Run import check: `python -c "from module import Class; print('OK')"`
2. Run collection only: `pytest tests/file.py --collect-only`
3. Then run full tests: `pytest tests/file.py -v`

### When Tests Fail
1. Read the **exact error message** ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â it usually names the missing field/method
2. Check the **source of truth file** for correct interface
3. Fix the **actual bug** (might be in test mock OR in production code)
4. **Update this document** with the lesson learned

---

## Template for New Entries

```markdown
### N. [Brief Error Description]

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Error** | `exact error message` |
| **Wrong Assumption** | What we thought |
| **Correct Interface** | What it actually is |
| **Source of Truth** | `file path` line numbers |
| **Impact** | Test issue / Real bug in production code |

**Wrong:**
\`\`\`python
# bad code
\`\`\`

**Correct:**
\`\`\`python
# good code
\`\`\`

**Prevention:** How to avoid this in future
```

---

---

### 7. ComfyUI Workflow Format: UI vs API

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `{"error": {"type": "invalid_prompt", "message": "Cannot execute because a node is missing the class_type property."}}` |
| **Wrong Assumption** | Workflow JSON files work directly with `/prompt` endpoint |
| **Correct Interface** | ComfyUI has TWO formats: UI format (`{"nodes": [...]}`) and API format (`{"node_id": {"class_type": ...}}`) |
| **Source of Truth** | ComfyUI API docs |

**Wrong:**
```python
# Submitting UI-format workflow (has "nodes" array)
workflow = json.load(open("workflow.json"))  # UI format
client.submit_workflow(workflow)  # FAILS
```

**Correct:**
```python
# Must use API format (node IDs as keys)
# Export from ComfyUI with "Save (API Format)" or convert
```

**Prevention:** Check if workflow has `"nodes"` key ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â if yes, it's UI format and needs conversion.

---

### 8. WorkflowLoader Returns Object, Not Dict

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: object of type 'WorkflowTemplate' has no len()` |
| **Wrong Assumption** | `loader.load()` returns a dict |
| **Correct Interface** | Returns `WorkflowTemplate` object with `.workflow` attribute |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
workflow = loader.load("t2v_wan21.json")
print(len(workflow))  # FAILS
```

**Correct:**
```python
template = loader.load("t2v_wan21.json")
workflow = template.workflow  # Get the actual dict
print(len(workflow))  # Works
```

---

### 9. ComfyClient Requires Explicit connect()

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ComfyConnectionError: Not connected to ComfyUI` |
| **Wrong Assumption** | Client connects automatically on first request |
| **Correct Interface** | Must call `await client.connect()` before submitting |
| **Source of Truth** | `src/comfy_client/client.py` |

**Wrong:**
```python
client = ComfyClient(host=url)
await client.submit_workflow(workflow)  # FAILS
```

**Correct:**
```python
client = ComfyClient(host=url)
await client.connect()  # REQUIRED
await client.submit_workflow(workflow)
```

---

### 10. ComfyClient Method Names

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: 'ComfyClient' object has no attribute 'queue_prompt'` |
| **Wrong Assumption** | Method names match ComfyUI API names |
| **Correct Interface** | Our wrapper uses different names |
| **Source of Truth** | `src/comfy_client/client.py` |

| Wrong | Correct |
|-------|---------|
| `ComfyUIClient` | `ComfyClient` |
| `queue_prompt()` | `submit_workflow()` |
| `get_status()` | `get_history()` |
| `load_workflow()` | `load()` |

**Prevention:** Always check: `print([m for m in dir(ComfyClient) if not m.startswith('_')])`

---

### 11. Sonic Module: AmbienceSpec Uses `type` Not `ambience_type`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: AmbienceSpec.__init__() got an unexpected keyword argument 'ambience_type'` |
| **Wrong Assumption** | Field is named `ambience_type` for clarity |
| **Correct Interface** | Field is simply `type` (matches enum name) |
| **Source of Truth** | `src/sonic/types.py` line 216 |

**Wrong:**
```python
AmbienceSpec(ambience_id="amb_001", ambience_type=AmbienceType.INTERIOR_QUIET, ...)
```

**Correct:**
```python
AmbienceSpec(ambience_id="amb_001", type=AmbienceType.INTERIOR_QUIET, ...)
```

**Prevention:** Check dataclass field names with: `grep -A 10 "class AmbienceSpec" src/sonic/types.py`

---

### 12. Sonic Module: SonicManifest Uses `manifest_id` Not `job_id`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: SonicManifest.__init__() got an unexpected keyword argument 'job_id'` |
| **Wrong Assumption** | Uses `job_id` like other job-related classes |
| **Correct Interface** | Uses `manifest_id` and `project_id` |
| **Source of Truth** | `src/sonic/types.py` lines 358-364 |

**Wrong:**
```python
SonicManifest(job_id="job_001", shot_plans=[...])
```

**Correct:**
```python
SonicManifest(manifest_id="manifest_001", project_id="proj_001", shot_plans=[...])
```

---

### 13. Sonic Module: VoiceConfig Uses `speaking_rate` Not `speed`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: 'VoiceConfig' object has no attribute 'speed'` |
| **Wrong Assumption** | Simple names: `speed`, `pitch` |
| **Correct Interface** | Explicit names: `speaking_rate`, `pitch_shift` |
| **Source of Truth** | `src/sonic/types.py` lines 101-107 |

**Wrong:**
```python
config.speed  # FAILS
config.pitch  # FAILS
```

**Correct:**
```python
config.speaking_rate  # 0.5 to 2.0
config.pitch_shift    # -12 to +12 semitones
```

---

### 14. WorkflowLoader.load() Takes NAME, Not Path

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | Workflow not found or wrong type |
| **Wrong Assumption** | `load()` takes a `Path` object |
| **Correct Interface** | `load()` takes workflow NAME as string (no extension, no path) |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
loader.load(Path("workflows/refine_freelong.json"))
loader.load("workflows/refine_freelong.json")
```

**Correct:**
```python
loader.load("refine_freelong")  # Just the name, loader finds the file
```

**Prevention:** WorkflowLoader manages its own workflow directory internally.

---

### 15. Cross-Module Imports Use `..` for Parent Directory

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ModuleNotFoundError: No module named 'client'` |
| **Wrong Assumption** | Can use `.client` for any sibling module |
| **Correct Interface** | Use `..module_name.file` for different parent directories |
| **Source of Truth** | Python relative import rules |

**Wrong (in src/studio/pass2_refiner.py):**
```python
from .client import ComfyClient  # FAILS - client.py is in comfy_client/, not studio/
```

**Correct:**
```python
from ..comfy_client.client import ComfyClient  # Go up to src/, then into comfy_client/
```

**Pattern:**
- `.module` = same directory
- `..module` = parent's sibling directory
- `...module` = grandparent's sibling (avoid if possible)

---

### 16. TTSProvider Has No MOCK Value

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: type object 'TTSProvider' has no attribute 'MOCK'` |
| **Wrong Assumption** | All provider enums have a MOCK variant |
| **Correct Interface** | `TTSProvider` only has `ELEVENLABS`, `OPENAI`, `LOCAL` |
| **Source of Truth** | `src/sonic/types.py` lines 26-30 |

**Wrong:**
```python
engine = get_tts_engine(TTSProvider.MOCK, ...)  # FAILS
```

**Correct:**
```python
# Create your own mock class for testing
class MockTTSEngine:
    provider = TTSProvider.ELEVENLABS  # Pretend to be real provider
    async def synthesize(self, line, config): ...
```

**Note:** `AmbienceProvider` and `FoleyProvider` DO have `.MOCK` variants. TTSProvider doesn't.

---

### 17. tests/conftest.py Needs Path Setup for `src` Imports

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ModuleNotFoundError: No module named 'src'` |
| **Wrong Assumption** | pytest automatically finds `src/` |
| **Correct Interface** | Must add project root to `sys.path` in conftest.py |
| **Source of Truth** | Python import system |

**Required in tests/conftest.py:**
```python
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent  # tests/ -> project root
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

**Note:** This worked in Claude's sandbox because `python -m pytest` adds current dir to path. Direct `pytest` command doesn't always do this.

---

## Claude Judgment Errors (Likely to Repeat)

> **Purpose:** Patterns where Claude's instincts lead to suboptimal decisions. These are likely to recur as the codebase grows more complex. Review before major sessions.

### J1. Hiding Warnings Instead of Questioning Them

**Error:** When IDE showed "Import 'clip' could not be resolved", immediately reached for `# type: ignore` to suppress warning.

**Better Approach:** Ask "Are these warnings useful?" - in this case, warnings served as documentation that optional dependencies aren't installed.

**Pattern to Watch:** Claude defaults to "fix the red squiggles" rather than evaluating whether warnings provide value.

---

### J2. Putting Annotations on Wrong Lines

**Error:** Added `# type: ignore` to the fallback `= None` lines instead of the actual `import` lines causing warnings.

```python
# WRONG - comment on fallback line doesn't help
except ImportError:
    clip_module = None  # type: ignore  <- This line isn't the problem

# RIGHT - comment on import line
try:
    import clip  # type: ignore[import-not-found]  <- This is what triggers warning
```

**Pattern to Watch:** When unfamiliar with syntax/tooling, Claude may place annotations mechanically without verifying they're in the correct location.

---

### J3. Over-Engineering Before Questioning Necessity

**Error:** Built elaborate optional dependency handling (module-level flags, fallback patterns, mock implementations) before asking "should we just install these dependencies?"

**Better Approach:** Ask user's intent first. Sometimes `pip install Pillow` is the right answer, not 50 lines of fallback code.

**Pattern to Watch:** Claude tends toward comprehensive solutions when simple ones suffice. As codebase grows, this creates unnecessary complexity.

---

### J4. Assuming Previous Code is Correct

**Error:** When building `pass1_generator.py`, initially trusted that existing interfaces in other files were complete and correct without verification.

**Better Approach:** Always `view` the actual source files before building integrations. Interfaces evolve and documentation may lag.

**Pattern to Watch:** As file count grows, Claude may rely on memory of files from earlier in conversation rather than re-checking current state.

---

### J5. Assuming Module Paths Match Logical Grouping

**Error:** Wrote `from src.studio.lip_sync import ...` but file is in `src/sonic/`. Same with `src.types` → `src/sonic/types`.

**Why:** Lip sync feels like "video" but lives in `sonic/` because it's audio-driven (syncing to dialogue).

**Prevention:** Check file tree before imports. Don't assume location from conceptual grouping.

---

### J6. Conditional Import Type Aliases Fail in Type Hints

**Error:** 
```python
except ImportError:
    ColorMatcher = Any  # Runtime variable, NOT a type alias

self.x: Optional[ColorMatcher] = None  # Pylance error: "Variable not allowed in type expression"
```

**Fix:** Use `Optional[Any]` directly with a comment noting the intended type.

---

*Add new judgment errors above this line as they're discovered.*

---

## Sonic Module Quick Reference

| Class | Required Fields | Common Mistakes |
|-------|-----------------|-----------------|
| `DialogueLine` | `line_id`, `character_id`, `text`, `start_time_sec` | `emotion` default is `None`, not `NEUTRAL` |
| `VoiceConfig` | `character_id` | `speaking_rate` not `speed`, `pitch_shift` not `pitch` |
| `AmbienceSpec` | `ambience_id`, `type`, `description`, `duration_sec` | `type` not `ambience_type` |
| `SonicManifest` | `manifest_id`, `project_id` | Not `job_id` |
| `ShotAudioPlan` | `shot_id`, `scene_id`, `duration_sec` | No `.validate()` method (it's on `SonicManifest`) |


### 18. Edge case- Workflow JSON doesn't accept `_meta` Keys

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ValueError: Workflow validation failed: ["Node _meta: missing 'class_type'"]` |
| **Wrong Assumption** | Workflow JSONs can have `_meta` key for documentation |
| **Correct Interface** | `validate()` treats ALL keys as ComfyUI nodes |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` lines 486-493 |

**Note:** Loader skips `_` prefixed FILES but NOT `_` prefixed KEYS in workflow dict.

**Prevention:** Don't add metadata keys to workflow JSONs. Document in README or code comments.

---
###19
# ASSUMPTION: LoRAs trained on wan2.1_t2v work with wan2.1_i2v
# Both share UNet architecture. Verify if upgrading to Wan 3.x.
```

---

## Role in Architecture (Systems Thinking)

### The Bridge Frame Problem
```
Shot A (ends)                    Shot B (starts)
     â”‚                                â”‚
     â–¼                                â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚Frame 144â”‚ â”€â”€â”€â”€ BRIDGE â”€â”€â”€â”€â–¶ â”‚Frame 1  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
     â”‚                                â”‚
     â”‚ Extract last frame             â”‚ Must match:
     â”‚                                â”‚  - Visual continuity (I2V)
     â–¼                                â”‚  - Character identity (LoRA)
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚           pass1_img2vid_lora.json  â—€â”€â”€ THIS FILE    â”‚
â”‚                                                      â”‚
â”‚  Inputs:                                             â”‚
â”‚    - INIT_IMAGE: last frame of Shot A               â”‚
â”‚    - LORA_PATH: alice_v1.safetensors                â”‚
â”‚    - PROMPT: "Alice walks to the door"              â”‚
â”‚                                                      â”‚
â”‚  Guarantees:                                         â”‚
â”‚    - Frame 1 of Shot B visually matches Frame 144   â”‚
â”‚    - Alice's face remains consistent                 â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜


### 20. Early Return Hides Subsequent Logic Paths

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | I2V workflows never used LoRA even when character had trained LoRA |
| **Wrong Assumption** | Sequential condition checks are safe |
| **Correct Interface** | Extract ALL state first, then make compound decision |
| **Source of Truth** | `src/renderers/wan_renderer.py` `_select_workflow_template()` |

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
    # ... etc
```

**Prevention:** When function has multiple independent dimensions (I2V vs T2V, LoRA vs no-LoRA), extract state into booleans first, then use decision matrix.

---

### 21. Orphan Nodes Waste VRAM - Stress Tests Catch What Contract Tests Miss

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `bridge_ipadapter.json` had orphan node `encode_face_ref` that nothing used |
| **Wrong Assumption** | If JSON is valid and nodes exist, workflow is correct |
| **Correct Interface** | Every node must contribute to output path |
| **Detection** | Stress test with BFS from output nodes backwards |

**The Bug:**
```json
"encode_face_ref": { ... },  // Created but never referenced
"apply_ipadapter": {
    "image": ["prep_face_ref", 0]  // Uses prep, not encode!
}
```

**Why Contract Tests Missed It:**
- JSON valid âœ“
- Node has class_type âœ“
- Node connections valid âœ“
- No dangling references âœ“

**Why Stress Test Caught It:**
- Traced backwards from SaveImage
- Found `encode_face_ref` unreachable
- Flagged as orphan (wastes VRAM)

**Prevention:** Run orphan detection on all workflows. Orphans indicate copy-paste errors or misunderstanding of node requirements.

---

*Add new entries above this line as they're discovered.*