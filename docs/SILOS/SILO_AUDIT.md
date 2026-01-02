# AUDIT SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Audit** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos.

This silo is the **QUALITY GATE**. It checks generated video for identity drift (does Alice still look like Alice?) and physics violations (did objects teleport?). If checks fail, the system re-rolls generation.

## System Architecture (Bird's Eye)

```
        ┌──────────────────────────────────────────┐
        │     Studio (generates video chunks)       │
        └─────────────────────┬────────────────────┘
                              │
                              │ Generated video
                              ▼
        ╔════════════════════════════════════════════════════════════╗
        ║                    AUDIT (this silo)                       ║
        ║                                                            ║
        ║   ┌────────────────────────────────────────────────────┐  ║
        ║   │                   Reviewer                          │  ║
        ║   │           (orchestrates all checks)                 │  ║
        ║   └────────────────────┬───────────────────────────────┘  ║
        ║                        │                                   ║
        ║            ┌───────────┴───────────┐                      ║
        ║            ▼                       ▼                      ║
        ║   ┌─────────────────┐    ┌─────────────────┐             ║
        ║   │ IdentityChecker │    │ PhysicsChecker  │             ║
        ║   │   (ArcFace)     │    │ (YOLO+ByteTrack)│             ║
        ║   └─────────────────┘    └─────────────────┘             ║
        ╚════════════════════════════════════════════════════════════╝
                              │
                              │ AuditResult (PASSED/FAILED)
                              ▼
        ┌──────────────────────────────────────────┐
        │    Pass1Generator (decides: keep/reroll)  │
        └──────────────────────────────────────────┘
```

## This Silo's Role

| Component | Responsibility |
|-----------|----------------|
| **Reviewer** | Orchestrate identity + physics checks, produce final verdict |
| **IdentityChecker** | Compare faces across frames using ArcFace embeddings |
| **PhysicsChecker** | Detect object permanence issues, teleportation, impossible motion |

## Key Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `audit/reviewer.py` | Orchestration | `Reviewer`, `ReviewRequest`, `ReviewResult` |
| `audit/identity_checker.py` | Face comparison | `IdentityChecker`, `ArcFaceIdentityChecker` |
| `audit/physics_checker.py` | Physics validation | `PhysicsChecker`, `PhysicsIssue` |

## Interfaces This Silo EXPOSES

Used by **Studio** (Pass1Generator):

```python
# From audit/reviewer.py
@dataclass
class ReviewRequest:
    video_path: Path
    reference_faces: List[Path]  # Canonical face refs for characters
    shot_id: str
    check_identity: bool = True
    check_physics: bool = True

@dataclass
class ReviewResult:
    passed: bool
    identity_score: Optional[float]  # 0.0-1.0, higher = more similar
    identity_passed: bool
    physics_passed: bool
    physics_issues: List[str]
    recommendation: str  # "accept" | "reroll" | "accept_with_warning"

class Reviewer:
    async def review(self, request: ReviewRequest) -> ReviewResult: ...

# From audit/identity_checker.py
class BaseIdentityChecker(ABC):
    @abstractmethod
    async def check_identity(
        self, 
        video_path: Path, 
        reference_faces: List[Path]
    ) -> Tuple[float, bool]: ...  # (score, passed)

class ArcFaceIdentityChecker(BaseIdentityChecker): ...
class MockIdentityChecker(BaseIdentityChecker): ...  # For testing

def get_identity_checker(mock: bool = False) -> BaseIdentityChecker: ...

# From audit/physics_checker.py
@dataclass
class PhysicsIssue:
    issue_type: str  # "teleportation" | "object_missing" | "collision"
    frame_range: Tuple[int, int]
    description: str
    severity: str  # "warning" | "error"

class BasePhysicsChecker(ABC):
    @abstractmethod
    async def check_physics(self, video_path: Path) -> List[PhysicsIssue]: ...

def get_physics_checker(mock: bool = False) -> BasePhysicsChecker: ...
```

## Interfaces This Silo CONSUMES

From **Core**:
```python
from src.core.config import get_config  # For thresholds
from src.core.job_state import AuditStatus, AuditResult
```

**External packages:**
- `insightface` - ArcFace face recognition
- `ultralytics` - YOLOv8 object detection
- `opencv-python` - Frame extraction

## Identity Check Logic

```python
# Simplified flow
async def check_identity(video_path: Path, reference_faces: List[Path]) -> float:
    # 1. Extract frames from video (first, middle, last)
    frames = extract_key_frames(video_path)
    
    # 2. Get reference face embedding
    ref_embedding = get_arcface_embedding(reference_faces[0])
    
    # 3. Compare each frame's face to reference
    scores = []
    for frame in frames:
        faces = detect_faces(frame)
        if faces:
            frame_embedding = get_arcface_embedding(faces[0])
            similarity = cosine_similarity(ref_embedding, frame_embedding)
            scores.append(similarity)
    
    # 4. Return average score
    return sum(scores) / len(scores) if scores else 0.0
```

**Thresholds:**
- `identity_threshold: 0.70` - Target for production
- `identity_threshold: 0.50` - Current (relaxed due to DWPreprocessor issues)

## Physics Check Logic

```python
# MVP checks (CV-based, <30s per 10s clip)
async def check_physics(video_path: Path) -> List[PhysicsIssue]:
    issues = []
    
    # 1. Object permanence (YOLO + ByteTrack)
    tracks = track_objects(video_path)
    for track in tracks:
        if track.disappears_suddenly():
            issues.append(PhysicsIssue("object_missing", ...))
    
    # 2. Flicker detection (optical flow)
    if detect_texture_popping(video_path):
        issues.append(PhysicsIssue("flicker", ...))
    
    # 3. Gravity heuristic
    # (object above ground should fall)
    
    # 4. Collision check
    # (objects shouldn't pass through each other)
    
    return issues
```

## Common Tasks

### Adjusting identity threshold
```python
# In config.py or runtime config
audit:
  identity_threshold: 0.70  # Stricter
  identity_threshold: 0.50  # More lenient
```

### Adding a new physics check
```python
# In physics_checker.py
async def check_physics(self, video_path: Path) -> List[PhysicsIssue]:
    issues = []
    
    # Existing checks...
    
    # New check: detect foot sliding
    if self._detect_foot_sliding(video_path):
        issues.append(PhysicsIssue(
            issue_type="foot_sliding",
            description="Character feet slide during walking",
            severity="warning"
        ))
    
    return issues
```

### Bypassing audit for testing
```python
# In GenerationConfig
config = GenerationConfig(
    enable_audit=False,  # Skip all checks
    # ...
)
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| Reviewer | ✅ Working | Orchestrates checks |
| IdentityChecker (ArcFace) | ✅ Working | Returns real scores |
| PhysicsChecker | 🟡 Stubbed | Returns empty list (always passes) |

**Known Issues:**
- Physics checks are stubbed - always pass
- Identity threshold relaxed to 0.50 (should be 0.70)
- No "accept best attempt" logic - fails after 3 rerolls

## Related Documentation

- `docs/ARCHITECTURE.md` - Section 2A (Physics Reviewer details)
- `docs/ARCHITECTURE_SUMMARY.md` - Section 7b (Known MVP Limitations)