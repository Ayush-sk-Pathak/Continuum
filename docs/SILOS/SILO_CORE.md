# CORE + INFRA SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Core + Infrastructure** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos with synchronized audio.

This silo provides the **foundation layer**: configuration, checkpointing, error recovery, job state management, and the ComfyUI client that talks to cloud GPUs.

## System Architecture (Bird's Eye)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              main.py                                     │
│                         (Orchestrator)                                   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────────────┐
        ▼                        ▼                                ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌─────────┐
│   Director   │    │      Studio      │    │    Sonic     │    │  Post   │
│   (Brain)    │    │  (Video Muscle)  │    │   (Audio)    │    │ (Final) │
└──────┬───────┘    └────────┬─────────┘    └──────┬───────┘    └────┬────┘
       │                     │                     │                  │
       └─────────────────────┴─────────────────────┴──────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
        ╔══════════════════════╗            ┌──────────────────┐
        ║   CORE (this silo)   ║            │      Memory      │
        ║  config, checkpoint  ║            │  (asset_store)   │
        ║  job_state, errors   ║            └──────────────────┘
        ╚══════════╦═══════════╝
                   ║
                   ▼
        ╔══════════════════════╗
        ║  COMFY_CLIENT        ║
        ║  (this silo)         ║
        ║  WebSocket to GPUs   ║
        ╚══════════════════════╝
                   │
                   ▼
            ┌──────────────┐
            │   RunPod     │
            │  Cloud GPUs  │
            │  (ComfyUI)   │
            └──────────────┘
```

**This silo is the FOUNDATION. Every other silo depends on it.**

## This Silo's Role

### Core (`src/core/`)
| Responsibility | Description |
|----------------|-------------|
| **Configuration** | Load/validate settings from YAML/env vars |
| **Job State** | Track job status (PENDING → RENDERING → AUDITING → APPROVED) |
| **Checkpointing** | Save/restore pipeline state for crash recovery |
| **Error Recovery** | Degradation ladder (retry → fallback → skip) |
| **Model Loading** | Registry of available models (Wan, HunyuanCustom) by tier |

### ComfyUI Client (`src/comfy_client/`)
| Responsibility | Description |
|----------------|-------------|
| **WebSocket Client** | Async connection to ComfyUI server on RunPod |
| **Workflow Loading** | Load JSON workflows, substitute placeholders |
| **Job Submission** | Submit workflows, poll for completion, download results |

### Workflows (`workflows/`)
| Directory | Contents |
|-----------|----------|
| `hunyuan_custom/` | HunyuanCustom-specific workflows (pass1_img2vid.json) |
| `wan/` | Wan-specific workflows (pass1_img2vid.json, etc.) |
| `shared/` | Model-agnostic workflows (bridge, hero_frame, rife, musetalk) |
| `reference/` | Documentation examples |

## Key Files

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `core/config.py` | Configuration management | `Config`, `get_config()` |
| `core/job_state.py` | Job/audit status tracking | `JobStatus`, `AuditStatus`, `AuditResult` |
| `core/checkpointing.py` | Pipeline state persistence | `CheckpointManager` |
| `core/error_recovery.py` | Failure handling | `DegradationLadder` |
| `core/model_loader.py` | Model registry | `get_model_config()`, `ModelTier` |
| `comfy_client/client.py` | ComfyUI WebSocket client | `ComfyUIClient` |
| `comfy_client/workflow_loader.py` | Workflow JSON handling | `WorkflowLoader` |
| `models.json` | Model path registry | JSON config |

## Interfaces This Silo EXPOSES

These are used by ALL other silos:

```python
# From core/config.py
@dataclass
class Config:
    comfyui_host: str
    output_dir: Path
    max_reroll_attempts: int
    identity_threshold: float
    # ... etc

def get_config() -> Config: ...

# From core/job_state.py
class JobStatus(Enum):
    PENDING = auto()
    RENDERING = auto()
    AUDITING = auto()
    APPROVED = auto()
    FAILED = auto()
    REROLLING = auto()

class AuditStatus(Enum):
    PENDING = auto()
    PASSED = auto()
    FAILED = auto()
    SKIPPED = auto()

@dataclass
class AuditResult:
    status: AuditStatus
    identity_score: Optional[float]
    physics_issues: List[str]
    recommendation: str

# From core/checkpointing.py
class CheckpointManager:
    def save(self, job_id: str, state: dict) -> None: ...
    def load(self, job_id: str) -> Optional[dict]: ...
    def exists(self, job_id: str) -> bool: ...

# From core/error_recovery.py
class DegradationLadder:
    def should_retry(self, error: Exception, attempt: int) -> bool: ...
    def get_fallback(self, operation: str) -> Optional[str]: ...

# From comfy_client/client.py
class ComfyUIClient:
    async def connect(self) -> None: ...
    async def submit_workflow(self, workflow: dict) -> str: ...
    async def wait_for_completion(self, job_id: str) -> dict: ...
    async def download_output(self, job_id: str, output_dir: Path) -> Path: ...
```

## Interfaces This Silo CONSUMES

**None** - This is the foundation layer. It only uses standard library and external packages (websockets, aiohttp, pyyaml).

## Common Tasks

### Adding a new config option
```python
# 1. Add to Config dataclass in config.py
@dataclass
class Config:
    new_option: str = "default_value"

# 2. Add to default.yaml
generation:
  new_option: "value"

# 3. Use in other silos
config = get_config()
print(config.new_option)
```

### Adding a new model family
```python
# 1. Add to models.json
{
  "new_model": {
    "dev": { "model_path": "...", "vae_path": "..." },
    "standard": { ... },
    "beast": { ... }
  }
}

# 2. Add to model_loader.py ModelFamily enum
class ModelFamily(Enum):
    WAN = "wan"
    HUNYUAN_CUSTOM = "hunyuan_custom"
    NEW_MODEL = "new_model"  # Add this
```

### Creating a new workflow
```python
# 1. Create JSON in appropriate directory
workflows/wan/my_new_workflow.json

# 2. Use placeholders for dynamic values
{
  "sampler": {
    "inputs": {
      "seed": "{{SEED}}",
      "steps": "{{STEPS}}"
    }
  }
}

# 3. Load and substitute in renderer
loader = WorkflowLoader()
workflow = loader.load("wan/my_new_workflow", {
    "SEED": 12345,
    "STEPS": 30
})
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| Config | ✅ Working | |
| Job State | ✅ Working | |
| Checkpointing | ✅ Working | |
| Error Recovery | ✅ Working | |
| Model Loader | ✅ Working | HunyuanCustom added |
| ComfyUI Client | ✅ Working | |
| Workflow Loader | ✅ Working | Model-family subdirs supported |
| HunyuanCustom workflows | 🟡 In Progress | See MODEL_PIVOT.md |

## Related Documentation

- `docs/ARCHITECTURE_SUMMARY.md` - Section 8 (Configuration)
- `docs/MODEL_PIVOT.md` - Section 4 (File Inventory)
- `docs/LESSONS_LEARNED.md` - ComfyUI debugging tips