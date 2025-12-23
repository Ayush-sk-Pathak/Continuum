# Lessons Learned: Interface Mismatches & Wrong Assumptions

> **Purpose:** A living document tracking assumptions that caused errors, their corrections, and how to avoid repeating them. Update this whenever a new mismatch is discovered.
>
> **Last Updated:** 2025-12-17 (Added lessons 33-36: WorkflowLoader methods, ComfyClient constructor, KSampler seed, bridge architecture)

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

**Prevention:** When mocking a dataclass, check ALL fields. Dataclass field order matters ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â required fields come before optional ones with defaults.

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
1. Read the **exact error message** ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â it usually names the missing field/method
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

**Prevention:** Check if workflow has `"nodes"` key ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â if yes, it's UI format and needs conversion.

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

---

## Role in Architecture (Systems Thinking)

### The Bridge Frame Problem
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
- JSON valid [OK]
- Node has class_type [OK]
- Node connections valid [OK]
- No dangling references [OK]

**Why Stress Test Caught It:**
- Traced backwards from SaveImage
- Found `encode_face_ref` unreachable
- Flagged as orphan (wastes VRAM)

**Prevention:** Run orphan detection on all workflows. Orphans indicate copy-paste errors or misunderstanding of node requirements.

---

### 22. Enum/Class Defined in Wrong Module - Import Path Mismatch

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `ImportError: cannot import name 'AmbienceProvider' from 'src.sonic.types'` |
| **Wrong Assumption** | All sonic enums/types are in `types.py` |
| **Correct Interface** | `AmbienceProvider` is in `ambience.py`, `FoleyProvider` is in `foley.py` |
| **Source of Truth** | Check actual file with `grep "class ClassName" src/sonic/*.py` |

**Wrong:**
```python
from src.sonic.types import (
    AmbienceProvider,  # NOT HERE
    FoleyProvider,     # NOT HERE
    DialogueLine,      # This one IS here
)
```

**Correct:**
```python
from src.sonic.ambience import AmbienceProvider
from src.sonic.foley import FoleyProvider
from src.sonic.types import DialogueLine
```

**Prevention:** Before importing, verify location:
```bash
grep -r "class AmbienceProvider" src/
```

---

### 23. Enum Value Doesn't Exist - Using Wrong Status Name

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: type object 'JobStatus' has no attribute 'RUNNING'` |
| **Wrong Assumption** | `JobStatus.RUNNING` exists |
| **Correct Interface** | Use `JobStatus.GENERATING` (the actual enum value) |
| **Source of Truth** | `src/core/job_state.py` |

**Available JobStatus values:**
```python
PENDING = "pending"
GENERATING = "generating"  # NOT "RUNNING"
AUDITING = "auditing"
FAILED = "failed"
APPROVED = "approved"
REFINING = "refining"
COMPLETE = "complete"
```

**Prevention:** Check enum definition before using:
```bash
grep -A 10 "class JobStatus" src/core/job_state.py
```

---

### 24. Mock Implementation Missing Required Interface Methods

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'MockBridgeEngine' object has no attribute 'shutdown'` |
| **Wrong Assumption** | Mocks only need to implement "active" methods |
| **Correct Interface** | Mocks must implement ALL base class methods, including lifecycle |
| **Source of Truth** | Check base class for all abstract/expected methods |

**Wrong:**
```python
class MockBridgeEngine(BaseBridgeEngine):
    async def generate(self, spec): ...
    async def health_check(self): ...
    # Missing: shutdown()
```

**Correct:**
```python
class MockBridgeEngine(BaseBridgeEngine):
    async def generate(self, spec): ...
    async def health_check(self): ...
    async def shutdown(self) -> None:
        """Mock shutdown - no cleanup needed."""
        pass
```

**Prevention:** When creating mocks, grep for all methods in base class:
```bash
grep -n "async def\|def " src/studio/bridge_engine.py | grep -A5 "class Base"
```

---

### 25. main.py Calls Methods That Don't Exist in Implementation

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'CheckpointManager' object has no attribute 'get_completed_scenes'` |
| **Wrong Assumption** | main.py and CheckpointManager are in sync |
| **Correct Interface** | main.py was written expecting methods that were never implemented |
| **Source of Truth** | `src/core/checkpointing.py` |

**Methods main.py expects but didn't exist:**
- `get_completed_scenes()` 
- `mark_scene_complete(scene_id)`

**Fix:** Add missing methods to CheckpointManager:
```python
def get_completed_scenes(self) -> set:
    """Get set of completed scene IDs."""
    completed = set()
    for job in self.get_all_jobs():
        if job.status == JobStatus.COMPLETE and job.scene_id:
            completed.add(job.scene_id)
    return completed

def mark_scene_complete(self, scene_id: str) -> None:
    """Mark a scene as complete."""
    logger.info(f"Scene {scene_id} marked complete")
```

**Prevention:** When main.py calls a method, verify it exists:
```bash
grep -n "def method_name" src/core/checkpointing.py
```

---

### 26. Dataclass Missing Required Argument in Constructor Call

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: InterpolationSpec.__init__() missing 1 required positional argument: 'shot_id'` |
| **Wrong Assumption** | Only path and fps arguments needed |
| **Correct Interface** | `shot_id` is required (no default value) |
| **Source of Truth** | `src/studio/rife_interpolator.py` |

**Wrong:**
```python
spec = InterpolationSpec(
    input_path=video_path,
    output_path=output_path,
    target_fps=target_fps,
)
```

**Correct:**
```python
spec = InterpolationSpec(
    input_path=video_path,
    output_path=output_path,
    shot_id=shot_output.shot_id,  # Required!
    target_fps=target_fps,
)
```

**Prevention:** Check dataclass definition for required fields (those without `= default`):
```bash
grep -A 15 "class InterpolationSpec" src/studio/rife_interpolator.py
```

---

### 27. JSON Schema Mismatch - EntityRef Requires Objects, Not Strings

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: EntityRef() argument after ** must be a mapping, not str` |
| **Wrong Assumption** | Characters can be listed as string IDs: `["alice", "bob"]` |
| **Correct Interface** | Characters must be EntityRef objects with `entity_id`, `entity_type`, `display_name` |
| **Source of Truth** | `src/director/scene_graph.py` - `Shot.from_dict()` |

**Wrong (sample_project.json):**
```json
"characters": ["alice"]
```

**Correct:**
```json
"characters": [
  {
    "entity_id": "alice",
    "entity_type": "character",
    "display_name": "Alice"
  }
]
```

**Prevention:** Always check `from_dict()` method to see expected JSON structure:
```bash
grep -A 20 "def from_dict" src/director/scene_graph.py
```

---

### 28. I2V Workflow Node Parameter Mismatches

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `Required input is missing: batch_size` and `unexpected keyword argument 'image'` |
| **Wrong Assumption** | Workflow template has all required parameters |
| **Correct Interface** | WanImageToVideo node requires `batch_size` and uses `start_image` not `image` |
| **Source of Truth** | ComfyUI node definition / error messages |

**Fixes applied to `pass1_img2vid.json`:**
```python
# Missing parameter
workflow['wan_i2v']['inputs']['batch_size'] = 1

# Wrong parameter name
workflow['wan_i2v']['inputs']['start_image'] = workflow['wan_i2v']['inputs'].pop('image')
```

**Prevention:** Test workflows against actual ComfyUI before committing. Error messages tell you exactly what's wrong.

---

### 29. Nested Config Access - Using Wrong Attribute Path

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'Config' object has no attribute 'comfyui_host'` |
| **Wrong Assumption** | Config fields are flat: `config.comfyui_host` |
| **Correct Interface** | Config is nested: `config.comfyui.host` |
| **Source of Truth** | `src/core/config.py` |

**Config structure is NESTED:**
```python
# Wrong - flat access
config.comfyui_host        # WRONG
config.comfyui_port        # WRONG
config.workflows_dir       # WRONG

# Correct - nested access
config.comfyui.host        # CORRECT
config.comfyui.timeout_sec # CORRECT
config.paths.workflows_dir # CORRECT
```

**Nested config classes:**
-  `config.comfyui` --> `ComfyUIConfig`
-  `config.paths` --> `PathsConfig`
-  `config.generation` --> `GenerationConfig`
-  `config.audit` --> `AuditConfig`
-  `config.sonic` --> `SonicConfig`
-  `config.post` --> `PostConfig`

**Prevention:** Check config.py for nested structure before accessing:
```bash
grep -n "class.*Config" src/core/config.py
```

---

### 30. Environment Variable Naming for Nested Pydantic Settings

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | Environment variable `COMFYUI_URL` ignored, still using localhost |
| **Wrong Assumption** | Env var name matches the field name |
| **Correct Interface** | Use `CONTINUUM_` prefix + double underscore for nesting |
| **Source of Truth** | `src/core/config.py` line 409 |

**Pydantic BaseSettings env var convention:**
```bash
# Pattern: {PREFIX}_{SECTION}__{FIELD}
# Note the DOUBLE underscore between section and field

# Wrong
export COMFYUI_URL="wss://..."           # WRONG - Ignored
export COMFYUI_HOST="wss://..."          # WRONG - Ignored

# Correct  
export CONTINUUM_COMFYUI__HOST="wss://..."    # CORRECT - Works
export CONTINUUM_COMFYUI__TIMEOUT_SEC=600     # CORRECT - Works
export CONTINUUM_PATHS__WORKFLOWS_DIR="/x"    # CORRECT - Works
```

**Key rules:**
1. Prefix is `CONTINUUM_` (from Config class)
2. Double underscore `__` separates nested config sections
3. Field names are uppercase

**Prevention:** Check config.py for `env_prefix` and examples:
```bash
grep -n "CONTINUUM_" src/core/config.py
```


---

### 31. Passing Dict When Function Expects Dataclass

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'dict' object has no attribute 'source_exists'` |
| **Wrong Assumption** | Any dict-like structure works |
| **Correct Interface** | Must pass the actual dataclass type |
| **Source of Truth** | Function signature |

**Pattern:** Function accepts `spec: BridgeSpec` but caller passes a dict:
```python
# Wrong - passing a dict
bridge_request = {
    "source_video": previous_output.video_path,
    "target_shot": shot,
}
result = await bridge_engine.generate(bridge_request)  # WRONG - Fails

# Correct - use the dataclass
spec = BridgeSpec.from_shots(
    shot_a_last_frame=last_frame_path,
    shot_b_prompt=shot.prompt,
    shot_b_characters=[],
)
result = await bridge_engine.generate(spec)  # CORRECT - Works
```

**Prevention:** Always check the function signature and use proper types. Look for factory methods like `Dataclass.from_something()` that make construction easier.

---

### 32. Method Naming Inconsistency Between Components

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'ComfyClient' object has no attribute 'upload_image'` and `'ComfyClient' object has no attribute 'submit'` |
| **Component** | `bridge_engine.py`, `rife_interpolator.py` calling `client.py` |

**Wrong Assumption:** Components calling `ComfyClient` assumed methods named `upload_image` and `submit` existed.

**Reality:** The actual method names were:
-  `upload_file()` -- generic file upload returning dict
-  `submit_workflow()` -- workflow submission

**Why It Happened:** Different developers or different development phases used different naming conventions. Bridge engine was written expecting simpler method names that matched the semantic action (upload_image, submit) while the client used more explicit names (upload_file, submit_workflow).

**Fix:** Added alias methods to ComfyClient:
```python
async def upload_image(self, image_path: Path, subfolder: str = "") -> str:
    """Alias for upload_file that returns just the filename."""
    result = await self.upload_file(image_path, subfolder=subfolder, file_type="input")
    return result.get("name", image_path.name)

async def submit(self, workflow: Dict[str, Any]) -> ComfyJob:
    """Alias for submit_workflow for backward compatibility."""
    return await self.submit_workflow(workflow)
```

**Prevention:** 
1. Define canonical method names in base classes/interfaces
2. When adding new callers, check exact method names in the implementation
3. Add aliases when method naming diverges to maintain backward compatibility

---

### 33. WorkflowLoader Method Name: `inject` not `inject_params`

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'WorkflowLoader' object has no attribute 'inject_params'` |
| **Wrong Assumption** | Method is named `inject_params(workflow, params)` |
| **Correct Interface** | Method is `inject(template, params)` or convenience method `load_and_inject(name, params)` |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
workflow = self.workflow_loader.load(workflow_name)
workflow = self.workflow_loader.inject_params(workflow, params)  # WRONG
```

**Correct:**
```python
# Option 1: Two-step
template = self.workflow_loader.load(workflow_name)
result = self.workflow_loader.inject(template, params)
workflow = result.workflow

# Option 2: One-step (preferred)
workflow = self.workflow_loader.load_and_inject(workflow_name, params)  # CORRECT
```

**Prevention:** Check WorkflowLoader methods:
```bash
grep -n "def inject\|def load_and_inject" src/comfy_client/workflow_loader.py
```

---

### 34. ComfyClient Constructor - Host Contains Full URL, No Port Parameter

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: ComfyClient.__init__() got an unexpected keyword argument 'port'` |
| **Wrong Assumption** | Constructor takes separate `host` and `port` parameters |
| **Correct Interface** | `host` is the full WebSocket URL including port |
| **Source of Truth** | `src/comfy_client/client.py` |

**Wrong:**
```python
ComfyClient(
    host=config.comfyui.host,
    port=config.comfyui.port,  # WRONG - Parameter does not exist
)
```

**Correct:**
```python
ComfyClient(
    host=config.comfyui.host,  # Full URL like "wss://...proxy.runpod.net:8188"
)
# OR
ComfyClient(
    config=config.comfyui,  # Pass entire ComfyUIConfig object
)
```

**Prevention:** The `host` field already contains the full URL with port. Check ComfyUIConfig:
```bash
grep -A 10 "class ComfyUIConfig" src/core/config.py
```

---

### 35. ComfyUI KSampler Seed Must Be >= 0

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `Value -1 smaller than min of 0` for seed parameter |
| **Wrong Assumption** | Seed value `-1` means "random" (like some libraries) |
| **Correct Interface** | KSampler requires seed >= 0, must generate random value explicitly |
| **Source of Truth** | ComfyUI KSampler node validation |

**Wrong:**
```python
params = {
    "SEED": spec.seed if spec.seed >= 0 else -1,  # WRONG - -1 is invalid
}
```

**Correct:**
```python
import random
params = {
    "SEED": spec.seed if spec.seed >= 0 else random.randint(0, 2**32 - 1),  # CORRECT
}
```

**Prevention:** ComfyUI nodes validate inputs strictly. Never assume sentinel values like `-1` are accepted. When in doubt, check ComfyUI node definitions or test with ComfyUI UI.

---

### 36. Architecture Mismatch: Wrong Model Family for Bridge Frames

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Issue** | `bridge_basic.json` uses SDXL for bridge frame generation |
| **Wrong Assumption** | SDXL img2img is suitable for creating continuity between Wan video shots |
| **Correct Approach** | Use Wan I2V (Image-to-Video) to maintain visual consistency |

**Why SDXL Bridge Was Wrong:**
1. SDXL generates a single static image, not video
2. Different model family than Wan = style mismatch risk
3. Requires extra 6.5GB model download
4. Generated bridge image never actually gets used by Shot 2

**Correct Architecture:**
Shot 1 last frame --> Wan I2V (pass1_img2vid) --> Shot 2 video
Instead of:
Shot 1 last frame --> SDXL img2img --> Bridge image --> ??? (dead end)

**Prevention:** When designing cross-shot continuity:
1. Use the same model family for all shots
2. Leverage I2V (image-to-video) capabilities of the primary renderer
3. Don't introduce additional model dependencies without clear benefit

---

### 37. Workflow JSON `_meta` Nodes Break ComfyUI Validation

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Workflow validation failed: ["Node _meta: missing 'class_type'"]` |
| **Wrong Assumption** | Can include `_meta` documentation node in workflow JSON |
| **Correct Interface** | Every top-level key in workflow JSON must be a valid ComfyUI node with `class_type` |

**Wrong:**
```json
{
  "_meta": {
    "title": "My Workflow",
    "version": "1.0.0"
  },
  "load_image": {
    "class_type": "LoadImage",
    ...
  }
}
```

**Correct:**
```json
{
  "load_image": {
    "class_type": "LoadImage",
    ...
  }
}
```

**Prevention:** Don't add metadata nodes to workflow JSON. If documentation is needed, use comments in a separate file or rely on `_description` fields in `models.json`.

---

### 38. ComfyJob Uses `prompt_id` Not `job_id`

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `'ComfyJob' object has no attribute 'job_id'` |
| **Wrong Assumption** | Job identifier is called `job_id` |
| **Correct Interface** | Use `job.prompt_id` for job identification |
| **Source of Truth** | `src/comfy_client/client.py` ComfyJob dataclass |

**Wrong:**
```python
job = await client.submit(workflow)
result = await client.wait_for_completion(job.job_id)  # WRONG
```

**Correct:**
```python
job = await client.submit(workflow)
result = await client.wait_for_completion(job.prompt_id)  # CORRECT
```

**Prevention:** Check ComfyJob dataclass definition before using attributes:
```bash
grep -A 15 "class ComfyJob" src/comfy_client/client.py
```

---

### 39. ComfyJob Outputs Are Nested Dict, Not `output_images` List

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `'ComfyJob' object has no attribute 'output_images'` |
| **Wrong Assumption** | Outputs are in `job.output_images[0]` |
| **Correct Interface** | Outputs are in `job.outputs` dict keyed by node_id |
| **Source of Truth** | WanRenderer._download_output pattern |

**Wrong:**
```python
await client.download_output(job.output_images[0], save_path)  # WRONG
```

**Correct:**
```python
for node_id, outputs in job.outputs.items():
    if "images" in outputs:
        items = outputs["images"]
        if items:
            await client.download_output(
                filename=items[0].get("filename"),
                subfolder=items[0].get("subfolder", ""),
                file_type="output",
                save_path=save_path
            )
            break
```

**Prevention:** Follow existing patterns in WanRenderer. The output structure is:
```python
job.outputs = {
    "node_id": {
        "images": [{"filename": "...", "subfolder": "..."}]
        # OR
        "gifs": [{"filename": "...", "subfolder": "..."}]
    }
}
```

---

### 40. SceneGraph Requires Full Schema - Shots Need `scene_id` Inside Them

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `KeyError: 'scene_id'` when parsing Shot |
| **Wrong Assumption** | Minimal JSON with just `id`, `duration`, `prompt` is sufficient |
| **Correct Interface** | Each shot must include `shot_id`, `scene_id`, `index`, `duration_sec`, etc. |

**Wrong:**
```json
{
  "shots": [
    {"id": "shot_01", "duration": 1.0, "prompt": "..."}
  ]
}
```

**Correct:**
```json
{
  "shots": [
    {
      "shot_id": "shot_01",
      "scene_id": "scene_01",
      "index": 0,
      "duration_sec": 1.0,
      "prompt": "...",
      "shot_type": "medium",
      "characters": [],
      "props": [],
      "chunks": [],
      "dialogue": []
    }
  ]
}
```

**Prevention:** Use existing test files as templates:
```bash
cat tests/sample_project_2shot.json
```

---

### 41. I2V 14B Models Need Extended Timeout (15-20 min, not 5 min)

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Job timed out after 300s` during I2V generation |
| **Wrong Assumption** | 5 minute timeout is sufficient for all Wan models |
| **Correct Interface** | I2V uses 14B model (vs T2V 1.3B), needs 10-20 minute timeout |

| Model | Params | Typical Gen Time (4s video) |
|-------|--------|----------------------------|
| T2V 1.3B | 1.3 billion | ~2-3 min |
| I2V 14B | 14 billion | ~15-20 min |

**Fix:**
```bash
export CONTINUUM_COMFYUI__TIMEOUT_SEC=1200  # 20 minutes
```

**Prevention:** When switching from T2V to I2V, remember the model size difference. There's no smaller I2V variant in Wan 2.1.

---

### 42. DWPreprocessor Requires comfyui_controlnet_aux Custom Node

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Cannot execute because node DWPreprocessor does not exist` |
| **Wrong Assumption** | Pose detection nodes are built into ComfyUI |
| **Correct Interface** | Must install ControlNet Preprocessors custom node pack |

**Installation (RunPod):**
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
pip install -r comfyui_controlnet_aux/requirements.txt
# Restart ComfyUI
```

**Alternative Nodes Available After Install:**
- `DWPreprocessor` (DWPose - recommended)
- `OpenposePreprocessor` (OpenPose)
- `DepthAnythingV2Preprocessor` (Depth estimation)

**Prevention:** Before creating workflows that use preprocessors, verify nodes exist:
```bash
# Check installed custom nodes
ls /workspace/runpod-slim/ComfyUI/custom_nodes/
```

---


### 43. Relative Import Across Package Boundaries

### 43. Relative Import Across Package Boundaries

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `No module named 'src.studio.reviewer'` |
| **Wrong Assumption** | Used `from .reviewer import ReviewRequest` in `pass1_generator.py` |
| **Correct Interface** | Reviewer is in `src/audit/`, not `src/studio/` -- use `from src.audit.reviewer import ReviewRequest` |
| **Source of Truth** | Check import statements in `main.py` to see actual module paths |
| **Prevention** | Relative imports (`.module`) only work within same package. Cross-package requires absolute import. |

---
---

### 44. Scene Has `duration_sec`, Not `total_duration_sec`

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `AttributeError: 'Scene' object has no attribute 'total_duration_sec'` |
| **Wrong Assumption** | Scene property follows `total_` naming pattern |
| **Correct Interface** | Scene uses `duration_sec` (property that sums shot durations) |
| **Source of Truth** | `src/director/scene_graph.py` line 387-389 |

**Wrong:**
```python
duration_sec=scene.total_duration_sec
```

**Correct:**
```python
duration_sec=scene.duration_sec
```

**Prevention:** Check scene_graph.py for exact property names before using. Scene has `duration_sec`, `shot_count`, `chunk_count` â€” none have `total_` prefix.

---

### 45. Workflow Names Must Match Existing JSON Files

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Workflow template 'refine_freelong' not found in workflows` |
| **Wrong Assumption** | Workflow mapping could use planned names before files created |
| **Correct Interface** | Workflow names must match actual `.json` files in repository |
| **Source of Truth** | Files in project root: `ls *.json` |

**Available refine workflows:**
- `refine_vid2vid_simple.json` âœ…
- `refine_vid2vid_temporal.json` âœ…
- `refine_freelong.json` âŒ (doesn't exist)

**Prevention:** Before adding workflow mappings, verify the `.json` file exists:
```bash
ls *.json | grep -i refine
```

---

### 46. ArcFace Similarity Can Exceed 1.0 â€” Clamp Derived Values

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Severity must be 0.0-1.0, got 1.0883083045482635` |
| **Wrong Assumption** | Cosine similarity is always in [0, 1] range |
| **Correct Interface** | Floating point precision can cause similarity > 1.0, so `1.0 - similarity` can be negative |
| **Source of Truth** | AuditFlag in `src/core/job_state.py` validates severity in `__post_init__` |

**Wrong:**
```python
severity=1.0 - (comparison.similarity or 0.0)
```

**Correct:**
```python
severity=max(0.0, min(1.0, 1.0 - (comparison.similarity or 0.0)))
```

**Prevention:** Any value that feeds into a bounded dataclass field must be clamped to that range first.

---

### 47. ComfyClient Connections Require Explicit shutdown() in Engines

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `ERROR | asyncio | Unclosed client session` at pipeline end |
| **Wrong Assumption** | Python garbage collection will clean up aiohttp sessions |
| **Correct Interface** | Each engine with `_client: ComfyClient` must implement `shutdown()` that calls `_client.disconnect()` |
| **Source of Truth** | `src/comfy_client/client.py` â€” `disconnect()` method closes aiohttp session |

**Pattern for Base Classes:**
```python
class BaseEngine(ABC):
    async def shutdown(self) -> None:
        """Default no-op. Override if holding resources."""
        pass  # Subclasses override if needed
```

**Pattern for ComfyUI Implementations:**
```python
class ComfyUIEngine(BaseEngine):
    def __init__(self):
        self._client = None  # Lazy initialized
    
    async def shutdown(self) -> None:
        """Disconnect from ComfyUI and release resources."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error during shutdown: {e}")
            finally:
                self._client = None  # Clear reference even on error
```

**Files Updated with This Pattern:**
- `pass2_refiner.py` â€” `BaseRefiner`, `ComfyUIRefiner`
- `lip_sync.py` â€” `BaseLipSyncEngine`, `MusetalkComfyEngine`
- `rife_interpolator.py` â€” `BaseInterpolator`, `ComfyRIFEInterpolator`

**Prevention:** When creating any new engine that uses `ComfyClient`:
1. Add `_client = None` in `__init__`
2. Use lazy initialization in `_get_client()`
3. Implement `shutdown()` that disconnects and clears `_client`
4. Ensure `main.py` calls `shutdown()` during pipeline teardown

---

### 48. RIFE VFI Node Installation on RunPod

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node RIFE VFI does not exist` |
| **Wrong Assumption** | Frame interpolation nodes are built into ComfyUI |
| **Correct Interface** | Must install ComfyUI-Frame-Interpolation custom node + download model |

**Installation Steps (RunPod):**
```bash
# 1. Clone the node
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation

# 2. Install dependencies (use no-cupy to avoid CUDA detection issues)
pip3 install -r ComfyUI-Frame-Interpolation/requirements-no-cupy.txt

# 3. Set backend to taichi (avoids cupy issues)
sed -i 's/ops_backend: "cupy"/ops_backend: "taichi"/' ComfyUI-Frame-Interpolation/config.yaml

# 4. Download RIFE model
mkdir -p ComfyUI-Frame-Interpolation/ckpts
cd ComfyUI-Frame-Interpolation/ckpts
wget -O rife47.pth "https://github.com/styler00dollar/VSGAN-tensorrt-docker/releases/download/models/rife47.pth"

# 5. Restart ComfyUI
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Verify Installation:**
```bash
# Check node loaded (look for "ComfyUI-Frame-Interpolation" in import times)
tail -50 /workspace/runpod-slim/comfyui.log | grep -i "frame-interp"

# Check server is healthy
curl -s http://localhost:8188/system_stats
```

**Workflow File:** `rife_interpolation.json` â€” uses `RIFE VFI` node with `rife47.pth`

**Note:** This installation is on persistent storage (`/workspace/`) so it survives pod restarts. However, you must restart ComfyUI after a fresh pod start to load the node.

---

### 49. Enum Names Must Match Definition Exactly

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `AttributeError: type object 'FoleyCategory' has no attribute 'DOORS'. Did you mean: 'DOOR'?` |
| **Wrong Assumption** | Enum names can be guessed (pluralized, past tense, etc.) |
| **Correct Interface** | Check actual enum definition in `types.py` |

**Wrong â†’ Correct Mappings:**
```python
FoleyCategory.DOORS       â†’ FoleyCategory.DOOR
FoleyCategory.ELECTRONICS â†’ FoleyCategory.ELECTRONIC
FoleyCategory.HANDLING    â†’ FoleyCategory.OBJECT
AudioGenerationStatus.COMPLETED â†’ AudioGenerationStatus.COMPLETE
```

**Prevention:** Before using any enum, verify the exact values:
```bash
grep -A 15 "class EnumName" src/core/types.py
```

---

### 50. ComfyUI Workflows Need Local Files Uploaded First

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Invalid video file: workspace/output/t2v_00045_.mp4` |
| **Wrong Assumption** | ComfyUI can access local file paths passed in workflow |
| **Correct Interface** | Files must be uploaded to ComfyUI server first via `client.upload_file()` |

**Wrong (local path):**
```python
params = {
    "INPUT_VIDEO": str(spec.input_path),  # âŒ Local path doesn't exist on server
}
```

**Correct (upload first):**
```python
# Upload file to ComfyUI server
upload_result = await client.upload_file(spec.input_path, subfolder="", file_type="input")
remote_name = upload_result.get("name", spec.input_path.name)

params = {
    "INPUT_VIDEO": remote_name,  # âœ… Use remote filename
}
```

**Prevention:** Any workflow that takes file input needs to upload first. Check bridge_engine.py for the pattern.

---

### 51. RIFE VFI Node Requires clear_cache_after_n_frames Parameter

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Required input is missing: clear_cache_after_n_frames` |
| **Wrong Assumption** | Optional parameters have defaults |
| **Correct Interface** | `RIFE VFI` node requires `clear_cache_after_n_frames` explicitly |

**Fix in workflow JSON:**
```json
"rife_interpolate": {
  "class_type": "RIFE VFI",
  "inputs": {
    "ckpt_name": "rife47.pth",
    "clear_cache_after_n_frames": 10,  // â† Required, prevents OOM
    ...
  }
}
```

**Prevention:** Test workflows in ComfyUI UI before committing to JSON. Missing required inputs show immediately in the UI.

---

### 52. RIFE Interpolator - Multiplier Type Must Match Result Type

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `unsupported operand type(s) for *: 'dict' * 'float'` |
| **Wrong Assumption** | `result.duration_sec` is always a float |
| **Correct Interface** | When workflow returns, result may be dict-like before proper parsing |
| **Source of Truth** | `src/studio/rife_interpolator.py` - `interpolate()` method |

**Context:** The RIFE interpolator submits a ComfyUI job, but when calculating the interpolated duration (original_duration * multiplier), the result object hasn't been properly converted to `InterpolationResult` yet.

**Fix needed in `rife_interpolator.py`:**
```python
# Ensure duration is extracted as float before multiplication
original_duration = float(result.get("duration_sec", 0) if isinstance(result, dict) else result.duration_sec)
interpolated_duration = original_duration * spec.multiplier
```

**Prevention:** Always verify the type of intermediate values when chaining operations, especially after async workflows return.

---

### 53. MixResult Object Does Not Have `.success` Attribute

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `'MixResult' object has no attribute 'success'` |
| **Wrong Assumption** | `MixResult` has a boolean `success` field |
| **Correct Interface** | Check `MixResult` dataclass in `src/sonic/mixer.py` for actual fields |
| **Source of Truth** | `src/sonic/mixer.py` - `MixResult` dataclass |

**Wrong (in main.py):**
```python
if mix_result.success:
    # handle success
```

**Correct (check actual fields):**
```python
if mix_result.output_path and mix_result.output_path.exists():
    # handle success
# Or check duration:
if mix_result.duration_sec > 0:
    # handle success
```

**Prevention:** Always verify dataclass fields before accessing:
```bash
grep -A 10 "class MixResult" src/sonic/mixer.py
```

---

### 54. FFmpeg Frame Extraction May Fail on Short Videos

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Expected output file not created: .../color_temp/sample_t2v_00055__04.png` |
| **Wrong Assumption** | FFmpeg will always extract the requested number of frames |
| **Correct Interface** | Short videos (< 1 second) may not have enough frames to sample |
| **Source of Truth** | `src/post/color_match.py` - frame extraction logic |

**Context:** The color matcher tries to extract 5 evenly-spaced frames for histogram analysis. A 0.8-second video at 12fps only has ~10 frames total, and FFmpeg's select filter may skip requested frames.

**Fix needed:** Add frame count check before extraction:
```python
# Get video duration/frame count first
probe = await ffprobe(video_path)
total_frames = int(probe.get("nb_frames", 0))

# Adjust sample count for short videos
sample_count = min(5, total_frames // 2)  # At least 2 frames between samples
```

**Prevention:** Any FFmpeg operation that samples frames should first verify the video has enough frames.

---

### 55. KSamplerBatch Node Not Available in Default ComfyUI

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node KSamplerBatch does not exist` |
| **Wrong Assumption** | KSamplerBatch is a standard ComfyUI node |
| **Correct Interface** | It's from ComfyUI-KJNodes custom node package |
| **Workflow Affected** | `refine_vid2vid_temporal.json` |

**Status:** ComfyUI-KJNodes IS installed on RunPod but node not loading. May need:
1. Restart ComfyUI after fresh pod start
2. Check for dependency conflicts
3. Verify KSamplerBatch still exists in latest KJNodes version

**Workaround:** Use `refine_vid2vid_simple.json` which uses standard KSampler instead:
```python
# In pass2_refiner.py template selection
template_name = "refine_vid2vid_simple"  # Fallback that works
```

**Investigation Commands:**
```bash
grep -r "KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-KJNodes/
# If not found, the node may have been renamed or removed in newer versions
```

---

### 56. DWPreprocessor Node Requires Model Download

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node DWPreprocessor does not exist` |
| **Wrong Assumption** | controlnet_aux nodes are ready to use after installation |
| **Correct Interface** | DWPreprocessor needs DWPose models downloaded separately |
| **Workflow Affected** | `bridge_pose_extract.json` |

**Status:** `comfyui_controlnet_aux` IS installed but DWPreprocessor not loading. Likely cause:
1. DWPose models not downloaded
2. ONNX runtime not installed
3. Dependency conflict

**Current Fallback:** Bridge engine falls back to `ipadapter_only` method when pose extraction fails. This works but produces less consistent results.

**Fix (on RunPod):**
```bash
# Install onnxruntime
pip3 install onnxruntime-gpu

# Download DWPose models
cd /workspace/runpod-slim/ComfyUI/custom_nodes/comfyui_controlnet_aux
python3 -c "from src.controlnet_aux.dwpose import DWposeDetector; DWposeDetector()"

# Restart ComfyUI
```

**Alternative:** Create `bridge_openpose.json` using OpenPosePreprocessor which may be more reliable.


57. ComfyJob.progress is a Dict, Not a Float
Date2025-12-20Errorunsupported operand type(s) for *: 'dict' * 'float'Wrong Assumptionjob.progress is a float representing completion percentageCorrect Interfacejob.progress is a Dict[str, Any] with "value" and "max" keysSource of Truthsrc/comfy_client/client.py lines 63, 644-645
Wrong:
pythonif job.progress:
    progress_pct = 0.4 + (job.progress * 0.5)  # ❌ dict * float
Correct:
pythonif job.progress:
    progress_value = job.progress.get("value", 0)
    progress_max = job.progress.get("max", 100)
    progress_pct = float(progress_value) / float(progress_max) if progress_max > 0 else 0.0
    final_progress = 0.4 + (progress_pct * 0.5)  # ✅
Prevention: Always check the type of ComfyJob fields in client.py before using them. Progress updates from WebSocket are stored as dicts.

58. MixResult Has .status, Not .success
Date2025-12-20Error'MixResult' object has no attribute 'success'Wrong AssumptionMixResult has a .success boolean like other result classesCorrect InterfaceMixResult uses .status (AudioGenerationStatus enum) and .output_pathSource of Truthsrc/sonic/types.py lines 424-455
Wrong:
pythonif result.success:  # ❌ AttributeError
    use(result.output_path)
Correct:
pythonif result.status == AudioGenerationStatus.COMPLETE and result.output_path:  # ✅
    use(result.output_path)
Prevention: Check the actual dataclass definition before assuming field names. Not all *Result classes have the same interface.

59. Short Videos Break Frame Extraction Assumptions
Date2025-12-20ErrorExpected output file not created: sample_t2v_00055__04.pngWrong AssumptionAll videos have enough duration to sample 5 frames at [0.1, 0.3, 0.5, 0.7, 0.9] positionsCorrect InterfaceVideos under 2 seconds may fail frame extraction at late positionsSource of Truthsrc/post/color_match.py _extract_sample_frames()
Wrong:
pythonfor pos in [0.1, 0.3, 0.5, 0.7, 0.9]:  # ❌ Assumes video is long enough
    time_sec = duration * pos
    await extract_frame(video, output, time_sec)
Correct:
python# Adjust sample count for short videos
if duration < 2.0:
    effective_samples = max(1, min(2, int(duration * 2)))
elif duration < 5.0:
    effective_samples = min(3, requested_samples)
# Also: wrap extract_frame in try/except, validate file exists
Prevention: Any time-based sampling must handle edge cases:

Very short videos (< 2s)
Empty/corrupt videos (0 duration)
Extraction failures (missing output file)

60. Wan I2V Does NOT Need IP-Adapter — Identity Comes from Bridge Frame
Date2025-12-21Wrong AssumptionNeed to create pass1_img2vid_ipadapter.json workflow for identity in I2VCorrect ArchitectureIdentity is locked at Bridge Engine stage (SDXL + IP-Adapter), then passed to Wan I2V via CLIP Vision encoding of the bridge frameSource of TruthARCHITECTURE_SUMMARY.md Section 2: "Identity lock survives; the style doesn't matter"
Why this matters:

Wan 2.1 does NOT have native IP-Adapter support in ComfyUI
The WORKFLOW_IMG2VID_IPADAPTER constant in wan_renderer.py is a placeholder that should NOT be implemented
Correct flow: Bridge Engine (SDXL+IPAdapter) → bridge_frame.png → Wan I2V (CLIP Vision encodes frame)

Prevention: Don't try to add IP-Adapter to Wan workflows. Identity anchoring happens BEFORE video generation.

---
---
### 61. World State Tracking — Full Implementation Pattern

| | |
|---|---|
| **Date** | 2025-12-21 |
| **Category** | Architecture Pattern (not a bug) |
| **Problem** | Props "teleport" between shots because system forgets state changes |
| **Solution** | Event-sourced World State with parser integration |
| **Source of Truth** | ARCHITECTURE.md, ARCHITECTURE_SUMMARY.md Section 4 |

**The Problem:**

Without dynamic state tracking, continuity breaks:
- Shot 3: "Alice picks up the sword"
- Shot 4: Alice rendered without sword (system forgot the pickup)
- Shot 5: Sword back on table (teleportation)

**The Solution — 4 File Pattern:**

| File | Role | Key Addition |
|------|------|--------------|
| `shot_event_parser.py` | Extracts events from descriptions | Pattern matching + explicit events |
| `scene_graph.py` | Stores explicit events | `Shot.events: List[Dict]` field |
| `main.py` | Wires parser to WorldState | `_update_world_state_from_shot()` |
| `pass1_generator.py` | Injects state into prompts | `_get_world_state_context()` |

**Data Flow:**
Shot.description ──┐
├── ShotEventParser ──► List[StateEvent]
Shot.events ───────┘                              │
▼
WorldState.apply_event()
│
▼
Next shot's prompt includes:
"Current scene state: sword: held by alice"

**Key Design Decisions:**

1. **Pattern Matching (No LLM):** ShotEventParser uses regex, not AI. Catches ~80% of common actions. Explicit events in scene graph handle the rest.

2. **Explicit Override:** Scene graph can declare events directly:
```json
   {
     "events": [
       {"type": "pickup", "subject": "alice", "object": "sword"}
     ]
   }
```

3. **Focused Context:** Only entities IN THE CURRENT SHOT get their state injected into prompts. Avoids cluttering with irrelevant info.

4. **Config Flag:** `GenerationConfig.enable_world_state` allows disabling for testing.

5. **Fail-Safe:** All world state operations wrapped in try/except. Pipeline continues if tracking fails.

**Event Types Supported:**

| Event Type | Example Description | Result |
|------------|---------------------|--------|
| `pickup` | "Alice picks up the sword" | `sword.position = held_by:alice` |
| `drop` | "She drops the mug" | `mug.position = floor` |
| `move` | "He places the book on the table" | `book.position = table` |
| `state_change` | "The mirror shatters" | `mirror.state = broken` |
| `transfer` | "Alice hands the key to Bob" | `key.holder = bob` |
| `appear` | "A dragon appears" | `dragon.position = scene` |
| `disappear` | "The ghost vanishes" | `ghost.position = offscreen` |

**Prevention Checklist:**

- [ ] New props in scene graph? Add to `initial_objects` in SceneSetup
- [ ] Complex action? Use explicit `events` field, don't rely on pattern matching
- [ ] Testing continuity? Enable verbose logging to see world state updates
- [ ] Debugging teleportation? Check `WorldState.get_events_for_entity()` history

**Architecture Alignment:**

From ARCHITECTURE.md:
> "Step 4 (The Bridge): It generates a Bridge Frame (preserving the end-state emotion/props)"

From ARCHITECTURE_SUMMARY.md:
> "The World State tells us *where* things are and *what happened* to them."

---
---

### 62. Claude Project Files Are FLATTENED — Actual Project Uses Nested `src/`

| | |
|---|---|
| **Date** | 2025-12-21 |
| **Category** | Environment Gotcha (not a code bug) |
| **Problem** | Claude's `/mnt/project/` shows all files at root level |
| **Reality** | Actual VS Code project uses proper nested `src/` structure |
| **Impact** | Wrong import paths if you assume flat structure |

**What Claude Sees:**
/mnt/project/
├── scene_graph.py
├── pass1_generator.py
├── identity_checker.py
├── mixer.py
└── ...

**What Actually Exists (VS Code):**
CONTINUUM/
├── src/
│   ├── audit/
│   │   ├── identity_checker.py
│   │   ├── physics_checker.py
│   │   └── reviewer.py
│   ├── director/
│   │   ├── scene_graph.py
│   │   ├── world_state.py
│   │   └── shot_event_parser.py
│   ├── studio/
│   │   ├── pass1_generator.py
│   │   ├── bridge_engine.py
│   │   └── rife_interpolator.py
│   ├── sonic/
│   │   └── mixer.py
│   └── ...
├── workflows/
├── main.py
└── ...

**Mapping Table:**

| Claude path | Actual path | Import statement |
|-------------|-------------|------------------|
| `/mnt/project/scene_graph.py` | `src/director/scene_graph.py` | `from src.director.scene_graph import ...` |
| `/mnt/project/pass1_generator.py` | `src/studio/pass1_generator.py` | `from src.studio.pass1_generator import ...` |
| `/mnt/project/identity_checker.py` | `src/audit/identity_checker.py` | `from src.audit.identity_checker import ...` |
| `/mnt/project/mixer.py` | `src/sonic/mixer.py` | `from src.sonic.mixer import ...` |
| `/mnt/project/world_state.py` | `src/director/world_state.py` | `from src.director.world_state import ...` |
| `/mnt/project/bridge_engine.py` | `src/studio/bridge_engine.py` | `from src.studio.bridge_engine import ...` |
| `/mnt/project/color_match.py` | `src/post/color_match.py` | `from src.post.color_match import ...` |
| `/mnt/project/client.py` | `src/comfy_client/client.py` | `from src.comfy_client.client import ...` |

**Prevention:**

1. **Always use `src.` prefix** in import statements
2. **Check existing imports** in the file before adding new ones
3. **When creating new files**, ask user which `src/` subfolder it belongs in
4. **Don't trust** Claude's flat view — reference this table

**Why This Happens:**

Claude Projects flatten uploaded files to `/mnt/project/` regardless of original folder structure. The nested `src/` organization is preserved in the actual codebase but not visible in Claude's file view.

<!-- 
  APPEND THIS TO THE END OF LESSONS_LEARNED.md 
  (before the final "Add new entries above this line" comment)
-->

### 63. Entity Classes Use `entity_id`, Not `id`

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `AttributeError: 'CharacterEntity' object has no attribute 'id'` |
| **Wrong Assumption** | Entity dataclasses have an `id` field |
| **Correct Interface** | All entity classes use `entity_id` as the identifier field |
| **Source of Truth** | `src/director/consistency_dict.py` |

**Affected Classes:**
- `CharacterEntity.entity_id`
- `LocationEntity.entity_id`
- `PropEntity.entity_id`

**Wrong:**
```python
known.update(c.id for c in self.consistency_dict.list_characters())
```

**Correct:**
```python
known.update(c.entity_id for c in self.consistency_dict.list_characters())
```

**Prevention:** Check dataclass definitions before accessing fields:
```bash
grep -n "entity_id\|character_id" src/director/consistency_dict.py | head -10
```

---

### 64. Import Paths Must Be Absolute from `src.`

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `ModuleNotFoundError: No module named 'world_state'` |
| **Wrong Assumption** | Can import sibling modules by name alone |
| **Correct Interface** | All imports must use full path from `src.` |
| **Source of Truth** | Project uses absolute imports throughout |

**Wrong (in `src/director/shot_event_parser.py`):**
```python
from world_state import EventType, ObjectState, Position, StateEvent
```

**Correct:**
```python
from src.director.world_state import EventType, ObjectState, Position, StateEvent
```

**Prevention:** Always use `from src.<package>.<module> import ...` pattern. Never bare module names.

---

### 65. RunPod: scikit-image Required for Pose Extraction

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `No module named 'skimage'` during pose extraction |
| **Wrong Assumption** | All OpenPose dependencies are installed |
| **Correct Interface** | Must install scikit-image separately |
| **Workflow Affected** | `bridge_pose_extract.json` (OpenposePreprocessor) |

**Fix (on RunPod):**
```bash
pip3 install scikit-image
```

**Then restart ComfyUI:**
```bash
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Prevention:** See RUNPOD.md Section 3 for required dependencies.

---

### 66. Pod ID: Watch for `1` (one) vs `l` (lowercase L)

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `WSServerHandshakeError: 404, Invalid response status` |
| **Wrong Assumption** | Typed pod ID correctly |
| **Correct Interface** | **Always copy Pod ID from browser URL, never type manually** |

**Example:**
- Wrong: `1yhiozmwkjopf7` (starts with number one)
- Correct: `lyhiozmwkjopf7` (starts with lowercase L)

**Prevention:** 
1. Click ComfyUI link in RunPod dashboard
2. Copy the URL from browser address bar
3. Extract pod ID from URL (everything before `-8188.proxy.runpod.net`)

---

### 65. list_characters() Returns Objects, Not IDs

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `TypeError: unhashable type: 'CharacterEntity'` |
| **Wrong Assumption** | `ConsistencyDict.list_*()` methods return ID strings |
| **Correct Interface** | They return full entity objects (CharacterEntity, LocationEntity, PropEntity) |
| **Source of Truth** | `src/director/consistency_dict.py` lines 364, 399, 429 |

**Wrong:**
```python
known = set()
known.update(self.consistency_dict.list_characters())  # Objects aren't hashable!
```

**Correct:**
```python
known = set()
known.update(c.entity_id for c in self.consistency_dict.list_characters())
```

**Method Return Types:**
- `list_characters()` → `List[CharacterEntity]`
- `list_locations()` → `List[LocationEntity]`
- `list_props()` → `List[PropEntity]`

**Prevention:** Check return type hints before using list methods.

### 67. RunPod Template Auto-Starts ComfyUI — Don't Double-Start

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | `OSError: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8188): address already in use` |
| **Wrong Assumption** | ComfyUI needs to be manually started after pod launch |
| **Correct Interface** | RunPod's template may auto-start ComfyUI on port 8188 |
| **Impact** | Manual start fails; logs show crash but ComfyUI is actually running |

**Symptom:**
```
[1]+  Exit 1   nohup python3 main.py --listen 0.0.0.0 --port 8188
```
But `curl localhost:8188/system_stats` returns valid JSON.

**Root Cause:**
RunPod's ComfyUI template includes auto-start. When you run the manual start command, it conflicts with the already-running instance.

**Correct Startup Procedure:**
```bash
# First, check if ComfyUI is already running
curl -s http://localhost:8188/system_stats | head -c 100

# If it returns JSON → already running, skip to pip install only
# If it fails → then start manually:
pkill -f "python.*main.py.*8188"
sleep 2
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Prevention:** Always check if ComfyUI is running before attempting to start it.
---

## 68. Workflow Documentation Convention

Workflow JSON files can include documentation using keys prefixed with `_`:
```json
{
  "_comment": "What this workflow does",
  "_architecture_ref": "Section X.Y in ARCHITECTURE.md",
  
  "actual_node": {
    "class_type": "...",
    "inputs": {...}
  }
}
```

These keys are:
- Preserved in template files (for developer documentation)
- Skipped during validation
- Stripped before submission to ComfyUI

___

### 69. ComfyUI Workflows May Reference Non-Existent Nodes

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | `Cannot execute because node KSamplerBatch does not exist` then `Cannot execute because node TemporalSmooth does not exist` |
| **Wrong Assumption** | Workflow JSON files were tested and use standard ComfyUI nodes |
| **Correct Interface** | Some workflows were created with aspirational/custom nodes that don't exist publicly |
| **Workflows Affected** | `refine_vid2vid_temporal.json` |

**Non-Existent Nodes Found:**

| Node | What It Was Supposed To Do | Replacement |
|------|---------------------------|-------------|
| `KSamplerBatch` | Batch sampling with `temporal_coherence` param | Standard `KSampler` |
| `TemporalSmooth` | Blend neighboring frames to reduce flicker | Removed (use FFmpeg post-processing instead) |

**Wrong (original workflow):**
```json
{
  "batch_sampler": {
    "class_type": "KSamplerBatch",
    "inputs": {
      "batch_size": "{{TEMPORAL_WINDOW}}",
      "temporal_coherence": true
    }
  },
  "temporal_smooth": {
    "class_type": "TemporalSmooth",
    "inputs": {
      "window_size": 3,
      "strength": 0.3
    }
  }
}
```

**Correct (fixed workflow):**
```json
{
  "sampler": {
    "class_type": "KSampler",
    "inputs": {
      // Standard params only, no temporal_coherence
    }
  }
  // TemporalSmooth removed entirely
}
```

**Prevention:**
1. Before using a workflow, verify ALL `class_type` values exist on your ComfyUI instance
2. Test workflows manually in ComfyUI web UI before integrating
3. Use `grep "class_type" workflow.json` to list all required nodes
4. Check RunPod logs for node loading: `cat /tmp/comfyui.log | grep "Loading:"`

**Note:** After this fix, `refine_vid2vid_temporal.json` is functionally identical to `refine_vid2vid_simple.json`. Consider consolidating them.

---

### 70. ComfyUI Node Packs Don't Always Contain Expected Nodes

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | Installed ComfyUI-Inspire-Pack expecting `KSamplerBatch`, but it wasn't there |
| **Wrong Assumption** | Node names imply which pack provides them |
| **Correct Interface** | Must verify node exists in pack before installing |

**Investigation Steps:**
```bash
# Search ComfyUI-Manager's node database for a node
grep -r "KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-Manager/extension-node-map.json

# Search installed packs for a node class
grep -r "class_type.*KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/
```

**What We Found:**
- `KSamplerBatch` - Does NOT exist in any standard pack
- `CRT_KSamplerBatch` - Different node, different pack
- `quadmoonKSamplerBatched` - Different node, different pack

**Prevention:** Before installing a pack to fix a missing node:
1. Search ComfyUI-Manager's node database for exact node name
2. Verify the pack actually provides that exact `class_type`
3. Consider if the workflow itself is the problem (using non-existent nodes)

---
*Add new entries above this line as they're discovered.*