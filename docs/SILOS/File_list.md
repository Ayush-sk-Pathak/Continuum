# Claude Projects - File Lists

## Shared Files (Optional Context)

These files CAN be added to any silo for deeper context, but aren't required because each `SILO_*.md` already contains the interfaces:

| File | When to Include |
|------|-----------------|
| `ARCHITECTURE_SUMMARY.md` | Deep architectural decisions |
| `MODEL_PIVOT.md` | HunyuanCustom-related work (Studio, Core, Audit) |
| `main.py` | Understanding how silos wire together |
| `LESSONS_LEARNED.md` | Debugging weird issues |

**Rule of thumb:** Start without shared files. Add them if Claude needs more context.

---

## Main Project: `continuum-main`

**Purpose:** Program Manager - assigns work, tracks progress

```
REQUIRED:
├── docs/PROJECT_LEAD.md          # Role context
├── docs/HANDOFF_TEMPLATES.md     # Communication protocols
└── docs/ARCHITECTURE_SUMMARY.md  # System overview

OPTIONAL (for deep dives):
├── docs/ARCHITECTURE.md          # Full spec
├── docs/MODEL_PIVOT.md           # If discussing HunyuanCustom
└── main.py                       # If discussing integration
```

---

## Silo 1: `continuum-core`

**Purpose:** Infrastructure - config, ComfyUI client, workflows

```
REQUIRED:
├── docs/SILO_CORE.md
├── src/core/
│   ├── __init__.py
│   ├── config.py
│   ├── checkpointing.py
│   ├── error_recovery.py
│   ├── job_state.py
│   └── model_loader.py
├── src/comfy_client/
│   ├── __init__.py
│   ├── client.py
│   └── workflow_loader.py
├── workflows/
│   ├── hunyuan_custom/*.json
│   ├── wan/*.json
│   └── shared/*.json
└── models.json

OPTIONAL:
├── docs/MODEL_PIVOT.md           # If adding new model support
└── docs/LESSONS_LEARNED.md       # ComfyUI debugging tips
```

**Estimated size:** ~150-200 KB

---

## Silo 2: `continuum-director`

**Purpose:** Brain - script parsing, state management, pacing

```
REQUIRED:
├── docs/SILO_DIRECTOR.md
├── src/director/
│   ├── __init__.py
│   ├── scene_graph.py
│   ├── consistency_dict.py
│   ├── world_state.py
│   ├── shot_event_parser.py
│   └── pacer.py
└── src/memory/
    ├── __init__.py
    ├── asset_store.py
    ├── cache.py
    └── visual_rag.py

OPTIONAL:
├── sample_project.json           # Example project structure
├── bible.json                    # Example character definitions
└── docs/ARCHITECTURE_SUMMARY.md  # If need pipeline context
```

**Estimated size:** ~100-120 KB

---

## Silo 3: `continuum-studio`

**Purpose:** Video Muscle - generation, bridge frames, refinement

```
REQUIRED:
├── docs/SILO_STUDIO.md
├── src/studio/
│   ├── __init__.py
│   ├── bridge_engine.py
│   ├── pass1_generator.py
│   ├── pass2_refiner.py
│   ├── rife_interpolator.py
│   └── workflow_utils.py
└── src/renderers/
    ├── __init__.py
    ├── base.py
    ├── wan_renderer.py
    └── hunyuan_custom_renderer.py

OPTIONAL (but recommended):
├── docs/MODEL_PIVOT.md           # HunyuanCustom is in progress!
├── workflows/hunyuan_custom/*.json  # If editing workflows
└── workflows/shared/*.json       # Bridge/hero workflows
```

**Estimated size:** ~150-180 KB (without workflows)

---

## Silo 4: `continuum-audit`

**Purpose:** Quality Gate - identity and physics checks

```
REQUIRED:
├── docs/SILO_AUDIT.md
└── src/audit/
    ├── __init__.py
    ├── identity_checker.py
    ├── physics_checker.py
    └── reviewer.py

OPTIONAL:
├── docs/MODEL_PIVOT.md           # ArcFace thresholds for HunyuanCustom
└── docs/ARCHITECTURE_SUMMARY.md  # QA requirements
```

**Estimated size:** ~70-90 KB

---

## Silo 5: `continuum-sonic`

**Purpose:** Audio - TTS, ambience, foley, lip sync

```
REQUIRED:
├── docs/SILO_SONIC.md
└── src/sonic/
    ├── __init__.py
    ├── types.py
    ├── tts_engine.py
    ├── ambience.py
    ├── foley.py
    ├── mixer.py
    └── lip_sync.py

OPTIONAL:
├── workflows/shared/musetalk_lipsync.json  # If working on lip sync
└── docs/ARCHITECTURE_SUMMARY.md  # Audio pipeline context
```

**Estimated size:** ~100-120 KB

---

## Silo 6: `continuum-post`

**Purpose:** Final Assembly - color match, ducking, stitch

```
REQUIRED:
├── docs/SILO_POST.md
└── src/post/
    ├── __init__.py
    ├── color_match.py
    ├── audio_ducker.py
    ├── stitcher.py
    └── ffmpeg_wrapper.py

OPTIONAL:
└── docs/ARCHITECTURE_SUMMARY.md  # Post-production pipeline context
```

**Estimated size:** ~70-90 KB

---

## Quick Reference Table

| Project | Required Doc | Required Source | Optional |
|---------|--------------|-----------------|----------|
| **main** | PROJECT_LEAD.md, HANDOFF_TEMPLATES.md, ARCHITECTURE_SUMMARY.md | (none) | MODEL_PIVOT.md, main.py |
| **core** | SILO_CORE.md | src/core/*, src/comfy_client/*, workflows/*, models.json | MODEL_PIVOT.md |
| **director** | SILO_DIRECTOR.md | src/director/*, src/memory/* | sample_project.json |
| **studio** | SILO_STUDIO.md | src/studio/*, src/renderers/* | MODEL_PIVOT.md, workflows/* |
| **audit** | SILO_AUDIT.md | src/audit/* | MODEL_PIVOT.md |
| **sonic** | SILO_SONIC.md | src/sonic/* | workflows/shared/musetalk* |
| **post** | SILO_POST.md | src/post/* | (rarely needed) |

---

## When to Add Shared Files

| Situation | Add This |
|-----------|----------|
| "I don't understand how this fits in the system" | ARCHITECTURE_SUMMARY.md |
| Working on HunyuanCustom anything | MODEL_PIVOT.md |
| "Why was this built this way?" | LESSONS_LEARNED.md |
| "How do silos connect at runtime?" | main.py |
| Need to edit workflow JSON | The specific workflow file |