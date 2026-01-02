# STUDIO SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Studio** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos.

This silo is the **VIDEO MUSCLE**. It handles actual video generation: Pass 1 (structure), Bridge Frames (transitions), Pass 2 (refinement), and RIFE (interpolation). It talks to cloud GPUs via ComfyUI.

**Key principle:** Studio is MODEL-AWARE but abstracted. It uses `BaseRenderer` to support multiple video models (Wan, HunyuanCustom) without changing orchestration code.

## System Architecture (Bird's Eye)

```
        ┌──────────────────────────────────────────┐
        │           Director (provides specs)       │
        └─────────────────────┬────────────────────┘
                              │
                              ▼
        ╔════════════════════════════════════════════════════════════╗
        ║                   STUDIO (this silo)                       ║
        ║                                                            ║
        ║   ┌────────────────────────────────────────────────────┐  ║
        ║   │              Pass1Generator                         │  ║
        ║   │  (orchestrates shot generation)                     │  ║
        ║   └────────────────────┬───────────────────────────────┘  ║
        ║                        │                                   ║
        ║            ┌───────────┼───────────┐                      ║
        ║            ▼           ▼           ▼                      ║
        ║   ┌─────────────┐ ┌─────────┐ ┌─────────────┐            ║
        ║   │   Bridge    │ │Renderer │ │    Pass2    │            ║
        ║   │   Engine    │ │ (Wan/   │ │   Refiner   │            ║
        ║   │(transitions)│ │Hunyuan) │ │ (vid2vid)   │            ║
        ║   └─────────────┘ └─────────┘ └─────────────┘            ║
        ║                        │                                   ║
        ║                        ▼                                   ║
        ║              ┌─────────────────┐                          ║
        ║              │      RIFE       │                          ║
        ║              │ (interpolation) │                          ║
        ║              └─────────────────┘                          ║
        ╚════════════════════════════════════════════════════════════╝
                              │
                              ▼
        ┌──────────────────────────────────────────┐
        │        ComfyUI Client (submits jobs)      │
        └──────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   RunPod GPUs    │
                    └──────────────────┘
```

## This Silo's Role

| Component | Responsibility |
|-----------|----------------|
| **Pass1Generator** | Orchestrate shot generation: hero frame → chunks → bridge |
| **BridgeEngine** | Generate synthetic transition frames (SDXL + ControlNet + IP-Adapter) |
| **Renderers (base.py)** | Abstract interface for video models |
| **WanRenderer** | Wan 2.1 implementation |
| **HunyuanCustomRenderer** | HunyuanCustom implementation |
| **Pass2Refiner** | Vid2Vid refinement for flicker reduction |
| **RIFEInterpolator** | Frame interpolation (12fps → 24fps) |

## Key Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `studio/pass1_generator.py` | Shot orchestration | `Pass1Generator`, `GenerationConfig`, `ShotOutput` |
| `studio/bridge_engine.py` | Transition frames | `BridgeEngine`, `BridgeSpec`, `BridgeResult` |
| `studio/pass2_refiner.py` | Vid2Vid refinement | `Pass2Refiner`, `RefinementSpec` |
| `studio/rife_interpolator.py` | FPS upscaling | `RIFEInterpolator`, `InterpolationSpec` |
| `renderers/base.py` | Renderer interface | `BaseRenderer`, `JobSpec`, `RenderResult` |
| `renderers/wan_renderer.py` | Wan implementation | `WanRenderer` |
| `renderers/hunyuan_custom_renderer.py` | Hunyuan implementation | `HunyuanCustomRenderer` |

## Interfaces This Silo EXPOSES

Used by **main.py**:

```python
# From renderers/base.py
class RendererType(Enum):
    WAN = "wan"
    HUNYUAN_CUSTOM = "hunyuan_custom"

@dataclass
class CharacterRef:
    entity_id: str
    face_ref_path: Path
    lora_path: Optional[Path]

@dataclass
class LocationRef:
    entity_id: str
    reference_path: Path

@dataclass
class JobSpec:
    prompt: str
    duration_sec: float
    width: int
    height: int
    fps: int
    characters: List[CharacterRef]
    location: Optional[LocationRef]
    init_image: Optional[Path]  # For I2V
    seed: Optional[int]

@dataclass
class RenderResult:
    video_path: Path
    duration_sec: float
    frame_count: int
    success: bool
    error: Optional[str]

class BaseRenderer(ABC):
    @abstractmethod
    async def render(self, spec: JobSpec) -> RenderResult: ...
    
    @abstractmethod
    async def render_i2v(self, spec: JobSpec, init_image: Path) -> RenderResult: ...

def get_renderer(renderer_type: RendererType) -> BaseRenderer: ...

# From studio/bridge_engine.py
@dataclass
class BridgeSpec:
    source_frame: Path      # Last frame of previous shot
    target_characters: List[CharacterRef]
    pose_weight: float
    identity_weight: float

@dataclass
class BridgeResult:
    bridge_frame: Path
    success: bool
    error: Optional[str]

class BridgeEngine:
    async def generate_bridge(self, spec: BridgeSpec) -> BridgeResult: ...

# From studio/pass1_generator.py
@dataclass
class GenerationConfig:
    max_reroll_attempts: int
    enable_audit: bool
    enable_bridge: bool
    quality: str

@dataclass
class ChunkOutput:
    chunk_id: str
    video_path: Path
    duration_sec: float

@dataclass
class ShotOutput:
    shot_id: str
    chunks: List[ChunkOutput]
    final_video_path: Path
    bridge_frame_used: Optional[Path]

class Pass1Generator:
    async def generate_shot(self, shot: Shot, config: GenerationConfig) -> ShotOutput: ...
```

## Interfaces This Silo CONSUMES

From **Director** (via dataclasses, not imports):
```python
# These types come FROM Director but we receive them as data, not imports
# In practice, main.py passes Shot objects to Pass1Generator
Shot, Chunk, EntityRef  # From scene_graph
CharacterEntity, LocationEntity  # From consistency_dict
```

From **Core**:
```python
from src.core.config import Config, get_config
from src.core.job_state import JobStatus, AuditResult
from src.core.checkpointing import CheckpointManager
```

From **ComfyClient**:
```python
from src.comfy_client.client import ComfyUIClient
from src.comfy_client.workflow_loader import WorkflowLoader
```

From **Audit** (for quality checks):
```python
from src.audit.reviewer import Reviewer, ReviewRequest, ReviewResult
```

## HunyuanCustom Pivot Notes

**Critical change from MODEL_PIVOT.md:**

| Aspect | Wan Pipeline | HunyuanCustom Pipeline |
|--------|--------------|------------------------|
| Identity injection | External (SDXL + IP-Adapter) | **Native (`<image>` token)** |
| Bridge Engine | Required for multi-shot | **May be optional** |
| Hero Frame | Required (SDXL generates) | **May be optional** |

**In HunyuanCustomRenderer:**
- Face reference passed directly to model via `<image>` token
- No separate hero frame generation step
- Bridge Engine still available but test if needed

```python
# HunyuanCustom prompt format
prompt = f"A portrait of <image> walking through a forest"
# The <image> token gets replaced with identity embedding
```

## Common Tasks

### Adding a new renderer
```python
# 1. Create new file: renderers/new_model_renderer.py
class NewModelRenderer(BaseRenderer):
    async def render(self, spec: JobSpec) -> RenderResult:
        # Implementation
        
    async def render_i2v(self, spec: JobSpec, init_image: Path) -> RenderResult:
        # Implementation

# 2. Add to RendererType enum in base.py
class RendererType(Enum):
    WAN = "wan"
    HUNYUAN_CUSTOM = "hunyuan_custom"
    NEW_MODEL = "new_model"

# 3. Update get_renderer() factory
def get_renderer(renderer_type: RendererType) -> BaseRenderer:
    if renderer_type == RendererType.NEW_MODEL:
        return NewModelRenderer()
```

### Making Bridge Engine optional
```python
# In Pass1Generator.generate_shot():
if config.enable_bridge and self._should_use_bridge(renderer_type):
    bridge_result = await self.bridge_engine.generate_bridge(bridge_spec)
else:
    # Use raw last frame or let model handle continuity
    init_image = self._extract_last_frame(previous_chunk)
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| Pass1Generator | ✅ Working | Orchestrates full pipeline |
| BridgeEngine | ✅ Working | SDXL + ControlNet + IP-Adapter |
| WanRenderer | ✅ Working | Production ready |
| HunyuanCustomRenderer | 🟡 In Progress | See MODEL_PIVOT.md Phase 0-2 |
| Pass2Refiner | ✅ Working | Vid2Vid temporal |
| RIFEInterpolator | ✅ Working | 12fps → 24fps |

**Known Issues:**
- DWPreprocessor missing on RunPod (bridge uses ipadapter_only fallback)
- Identity threshold relaxed to 0.50 (should be 0.70+)

## Related Documentation

- `docs/ARCHITECTURE.md` - Section 3 (Visual Pipeline)
- `docs/ARCHITECTURE_SUMMARY.md` - Section 3 (Pipeline)
- `docs/MODEL_PIVOT.md` - HunyuanCustom integration details
- `workflows/` - All ComfyUI workflow definitions