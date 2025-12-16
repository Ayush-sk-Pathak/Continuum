# Lessons Learned: Interface Mismatches & Wrong Assumptions

> **Purpose:** A living document tracking assumptions that caused errors, their corrections, and how to avoid repeating them. Update this whenever a new mismatch is discovered.
>
> **Last Updated:** 2025-12-15

---

## Quick Reference: Source of Truth Files

Before writing code that uses these interfaces, **always check these files first**:

| Interface | Source of Truth | Key Classes |
|-----------|-----------------|-------------|
| Renderer | `src/renderers/base.py` | `BaseRenderer`, `RenderResult`, `JobSpec`, `CharacterRef` |
| Scene Graph | `src/director/scene_graph.py` | `SceneGraph`, `Scene`, `Shot`, `Chunk`, `EntityRef` |
| Consistency Dict | `src/director/consistency_dict.py` | `ConsistencyDict`, `CharacterEntity`, `LocationEntity` |
| Bridge Engine | `src/studio/bridge_engine.py` | `BaseBridgeEngine`, `BridgeSpec`, `BridgeResult` |
| Identity Checker | `src/audit/identity_checker.py` | `BaseIdentityChecker`, `IdentityComparison`, `FrameFaces` |
| Config | `src/core/config.py` | `Config`, `GenerationConfig`, `AuditConfig` |
| Job State | `src/core/job_state.py` | `JobStatus`, `JobCheckpoint`, `AuditResult` |
| Error Recovery | `src/core/error_recovery.py` | `RetryConfig`, `DegradationLadder` |

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

**Prevention:** When mocking a dataclass, check ALL fields. Dataclass field order matters — required fields come before optional ones with defaults.

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
1. Read the **exact error message** — it usually names the missing field/method
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

*Add new entries above this line as they're discovered.*