# DIRECTOR SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Director** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos.

This silo is the **BRAIN** of the system. It handles script parsing, state management, consistency tracking, and pacing decisions. It runs locally on the Mac and dispatches work to cloud GPUs.

**Key principle:** The Director is MODEL-AGNOSTIC. It doesn't know or care whether we're using Wan or HunyuanCustom. It speaks in abstract terms (shots, scenes, characters) and lets the Studio silo handle rendering.

## System Architecture (Bird's Eye)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              main.py                                     │
│                         (Orchestrator)                                   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
        ╔════════════════════════════════════════╗
        ║         DIRECTOR (this silo)           ║
        ║                                        ║
        ║  ┌─────────────┐    ┌──────────────┐  ║
        ║  │ SceneGraph  │    │ Consistency  │  ║
        ║  │  (parser)   │    │    Dict      │  ║
        ║  └─────────────┘    └──────────────┘  ║
        ║                                        ║
        ║  ┌─────────────┐    ┌──────────────┐  ║
        ║  │ WorldState  │    │    Pacer     │  ║
        ║  │ (dynamics)  │    │  (timing)    │  ║
        ║  └─────────────┘    └──────────────┘  ║
        ║                                        ║
        ║  ┌─────────────────────────────────┐  ║
        ║  │     Memory (asset_store,        │  ║
        ║  │     cache, visual_rag)          │  ║
        ║  └─────────────────────────────────┘  ║
        ╚════════════════════════════════════════╝
                                 │
                                 │ Produces: Shot specs, timing, asset refs
                                 ▼
        ┌──────────────────────────────────────────┐
        │              Studio (renders shots)       │
        └──────────────────────────────────────────┘
```

## This Silo's Role

| Component | Responsibility |
|-----------|----------------|
| **SceneGraph** | Parse scripts into structured Scene → Shot → Chunk hierarchy |
| **ConsistencyDict** | Map entity IDs (alice, kitchen) to canonical assets (LoRAs, refs) |
| **WorldState** | Track dynamic object positions and states across shots |
| **Pacer** | Decide shot durations and when to cut |
| **ShotEventParser** | Extract events from shot descriptions (pickup, throw, enter) |
| **Memory (VisualRAG)** | Retrieve relevant reference images for characters/locations |
| **Memory (AssetStore)** | Manage file paths for assets, outputs, checkpoints |
| **Memory (Cache)** | Cache expensive operations (embeddings, thumbnails) |

## Key Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `director/scene_graph.py` | Script structure | `SceneGraph`, `Scene`, `Shot`, `Chunk`, `EntityRef` |
| `director/consistency_dict.py` | Entity → Asset mapping | `ConsistencyDict`, `CharacterEntity`, `LocationEntity` |
| `director/world_state.py` | Dynamic state tracking | `WorldState`, `TrackedObject`, `Position`, `StateEvent` |
| `director/pacer.py` | Timing decisions | `Pacer`, `PacingStyle`, `ShotPacingPlan` |
| `director/shot_event_parser.py` | Event extraction | `ShotEventParser`, `EventType` |
| `memory/visual_rag.py` | Reference image retrieval | `VisualRAG` |
| `memory/asset_store.py` | File path management | `AssetStore` |
| `memory/cache.py` | Operation caching | `Cache` |

## Interfaces This Silo EXPOSES

These are used by **Studio** and **main.py**:

```python
# From director/scene_graph.py
@dataclass
class EntityRef:
    entity_id: str
    entity_type: str  # "character" | "location" | "prop"

@dataclass
class Chunk:
    chunk_id: str
    chunk_index: int
    duration_sec: float
    prompt: str
    status: ChunkStatus

@dataclass  
class Shot:
    shot_id: str
    shot_index: int
    duration_sec: float
    prompt: str
    camera_notes: str
    characters: List[EntityRef]
    location: Optional[EntityRef]
    chunks: List[Chunk]

@dataclass
class Scene:
    scene_id: str
    scene_index: int
    location: EntityRef
    shots: List[Shot]

class SceneGraph:
    scenes: List[Scene]
    
    @classmethod
    def from_project_json(cls, path: Path) -> "SceneGraph": ...
    def get_shot(self, scene_id: str, shot_id: str) -> Shot: ...
    def get_all_shots(self) -> List[Shot]: ...

# From director/consistency_dict.py
@dataclass
class CharacterEntity:
    entity_id: str
    display_name: str
    lora_path: Optional[str]
    face_refs: List[Path]
    voice_id: Optional[str]

@dataclass
class LocationEntity:
    entity_id: str
    display_name: str
    reference_images: List[Path]

class ConsistencyDict:
    def get_character(self, entity_id: str) -> CharacterEntity: ...
    def get_location(self, entity_id: str) -> LocationEntity: ...
    def get_face_ref(self, character_id: str) -> Path: ...

# From director/world_state.py
@dataclass
class Position:
    x: float
    y: float
    z: float

@dataclass
class TrackedObject:
    object_id: str
    position: Position
    state: str  # "held", "on_table", "in_motion"

class WorldState:
    def get_object_position(self, object_id: str) -> Position: ...
    def update_after_event(self, event: StateEvent) -> None: ...

# From director/pacer.py
@dataclass
class ShotPacingPlan:
    shot_id: str
    target_duration_sec: float
    chunk_durations: List[float]
    cut_reason: str  # "duration_limit" | "pacing" | "scene_end"

class Pacer:
    def plan_shot(self, shot: Shot, style: PacingStyle) -> ShotPacingPlan: ...
```

## Interfaces This Silo CONSUMES

From **Core**:
```python
from src.core.config import Config, get_config
from src.core.job_state import JobStatus, AuditStatus
from src.core.checkpointing import CheckpointManager
```

**That's it.** Director does NOT import from Studio, Renderers, Sonic, Post, or Audit.

## Common Tasks

### Adding a new entity type to ConsistencyDict
```python
# 1. Create dataclass
@dataclass
class PropEntity:
    entity_id: str
    display_name: str
    reference_images: List[Path]

# 2. Add to ConsistencyDict
class ConsistencyDict:
    props: Dict[str, PropEntity] = field(default_factory=dict)
    
    def get_prop(self, entity_id: str) -> PropEntity:
        return self.props[entity_id]
```

### Adding a new pacing style
```python
class PacingStyle(Enum):
    SLOW = "slow"      # Long shots, minimal cuts
    NORMAL = "normal"  # Balanced
    FAST = "fast"      # Quick cuts, high energy
    MUSIC_VIDEO = "music_video"  # New style

# In Pacer.plan_shot():
if style == PacingStyle.MUSIC_VIDEO:
    max_duration = 3.0  # Very short shots
```

### Parsing a new script format
```python
# SceneGraph.from_project_json handles the standard format
# For new formats, add a new classmethod:

@classmethod
def from_fountain(cls, script_path: Path) -> "SceneGraph":
    """Parse a Fountain screenplay format."""
    # Implementation
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| SceneGraph | ✅ Working | Parses sample_project.json |
| ConsistencyDict | ✅ Working | Characters + Locations |
| WorldState | 🟡 Stubbed | Data structures exist, logic minimal |
| Pacer | ✅ Working | SLOW/NORMAL/FAST styles |
| ShotEventParser | 🟡 Stubbed | Basic event extraction |
| VisualRAG | 🟡 Stubbed | Returns mock refs |
| AssetStore | ✅ Working | |
| Cache | ✅ Working | |

## Related Documentation

- `docs/ARCHITECTURE.md` - Section 2A (The Brain)
- `docs/ARCHITECTURE_SUMMARY.md` - Section 2 (Director Agent)
- `sample_project.json` - Example project structure
- `bible.json` - Example character/location definitions