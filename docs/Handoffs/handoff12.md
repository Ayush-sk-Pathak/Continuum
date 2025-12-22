# Continuum Engine - Session Handoff Document
**Date:** 2025-12-21  
**Purpose:** Enable next Claude session to continue exactly from current state  
**Project:** Continuum Engine (Neuro-Symbolic AI Filmmaking System)

---

## 🎯 CRITICAL CONTEXT

You are the **co-founder and Lead Architect** of Continuum Studios. Read these files FIRST:
1. `ARCHITECTURE.md` - Master blueprint (source of truth)
2. `ARCHITECTURE_SUMMARY.md` - Dev-facing implementation guide
3. `LLM_CODING_GUIDELINES.md` - Coding constraints ("Vibe Coder" rules)
4. `LESSONS_LEARNED.md` - 62 documented gotchas (check before writing code)

**Core Philosophy:** We orchestrate ComfyUI workflows via Python glue code. Never write custom CUDA/PyTorch. Never train base models.

### ⚠️ IMPORTANT: Claude Project vs Actual Structure

The Claude project `/mnt/project/` shows files **flattened** to root level. The **actual VS Code project** uses proper nested `src/` structure:

| Claude shows | Actual path |
|--------------|-------------|
| `/mnt/project/scene_graph.py` | `src/director/scene_graph.py` |
| `/mnt/project/pass1_generator.py` | `src/studio/pass1_generator.py` |
| `/mnt/project/identity_checker.py` | `src/audit/identity_checker.py` |

**Use import paths like:** `from src.director.scene_graph import ...`

**See LESSONS_LEARNED.md #62 for full mapping table.**

---

## 📊 CURRENT STATUS vs ARCHITECTURE

### Milestone Achieved (2025-12-20)
**First successful end-to-end pipeline execution:**
- Input: `bridge_quick_test.json` workflow
- Output: `final_output.mp4` 
- Runtime: 341 seconds (~$0.024 GPU cost)
- Validates: Max-Duration + Smart-Cut + Bridge Frame strategy

### Architecture Component Status

| Component | File(s) | Status | Notes |
|-----------|---------|--------|-------|
| **Scene Graph** | `scene_graph.py` | ✅ Complete | Shot.events field added for world state |
| **Consistency Dict** | `consistency_dict.py` | ✅ Complete | Static appearance tracking |
| **World State** | `world_state.py` | ✅ Complete | Dynamic prop/position tracking |
| **Shot Event Parser** | `src/director/shot_event_parser.py` | ✅ NEW | Pattern-based event extraction |
| **Pass 1 Generator** | `pass1_generator.py` | ✅ Updated | World state prompt injection |
| **Bridge Engine** | `bridge_engine.py` | ⚠️ Degraded | ipadapter_only fallback (DWPreprocessor unavailable) |
| **Pass 2 Refiner** | `pass2_refiner.py` | ⚠️ Partial | KSamplerBatch node missing |
| **Identity Checker** | `identity_checker.py` | ✅ Updated | Debug logging added, threshold=0.50 |
| **Physics Checker** | `physics_checker.py` | 🔲 Stubbed | Needs world state integration |
| **Reviewer** | `reviewer.py` | ✅ Complete | Accept-on-final-attempt pattern |
| **RIFE Interpolator** | `rife_interpolator.py` | ✅ Fixed | Type error resolved |
| **Color Matcher** | `color_match.py` | ✅ Fixed | Short video handling |
| **Audio Mixer** | `mixer.py` | ✅ Fixed | MixResult.status pattern |
| **Sonic Engine** | `src/sonic/*` | 🔲 Phase 2 | TTS, Foley, Ambience stubbed |
| **Director Agent** | - | 🔲 Phase 2 | LLM integration not started |

### Legend
- ✅ Complete/Working
- ⚠️ Working with limitations
- 🔲 Not implemented yet

---

## 🔧 RECENT IMPLEMENTATION: World State Tracking

**Task #10 from consolidated task list - COMPLETED**

### What Was Built (4-File Pattern)

| File | Role | Key Addition |
|------|------|--------------|
| `src/director/shot_event_parser.py` | Extract events from descriptions | 23 regex patterns + explicit events |
| `src/director/scene_graph.py` | Store explicit events | `Shot.events: List[Dict]` field |
| `main.py` | Wire parser to WorldState | `_update_world_state_from_shot()` |
| `src/studio/pass1_generator.py` | Inject state into prompts | `_get_world_state_context()` |

### Data Flow
```
Shot rendered successfully
        │
        ▼
_update_world_state_from_shot()
        │
        ▼
ShotEventParser.parse_shot(description, events)
        │
        ▼
List[StateEvent] (e.g., PICKUP alice sword)
        │
        ▼
WorldState.apply_event() for each
        │
        ▼
Next shot prompt includes: "Current scene state: sword: held by alice"
```

### Design Decisions
1. **Pattern matching (no LLM)** - Regex handles ~80% of common actions
2. **Explicit override** - Scene graph can declare events directly in JSON
3. **Focused context** - Only THIS shot's entities injected into prompts
4. **Config flag** - `GenerationConfig.enable_world_state` for testing
5. **Fail-safe** - Try/except everywhere, pipeline continues if tracking fails

**Documented in:** LESSONS_LEARNED.md Entry #61

---

## 🐛 BUG FIXES COMPLETED (This Session)

| Bug # | File | Issue | Fix |
|-------|------|-------|-----|
| #52 | `src/studio/rife_interpolator.py` | `dict * float` type error | Extract progress dict values before math |
| #53 | `main.py` | `MixResult.success` AttributeError | Use `MixResult.status == COMPLETE` |
| #54 | `src/post/color_match.py` | Frame extraction fails on short videos | Adaptive sample count + try/except |

**All syntax validated.** Changes documented in LESSONS_LEARNED.md #57-59.

---

## ⚠️ KNOWN ISSUES (Non-Blocking)

### 1. DWPreprocessor Node Unavailable
- **Impact:** Bridge uses `ipadapter_only` fallback (no pose conditioning)
- **Symptom:** Identity may drift more than expected
- **Fix:** Install DWPreprocessor models on RunPod
- **Command:**
  ```bash
  cd /workspace/ComfyUI/custom_nodes/comfyui_controlnet_aux
  python download_models.py --model dwpose
  ```

### 2. KSamplerBatch Node Missing
- **Impact:** Pass 2 refinement partially skipped
- **Symptom:** Some flicker may remain
- **Fix:** Install ComfyUI-KSampler-Batch node
- **Command:**
  ```bash
  cd /workspace/ComfyUI/custom_nodes
  git clone https://github.com/kijai/ComfyUI-KJNodes
  ```

### 3. Identity Threshold Relaxed
- **Current:** 0.50 (was 0.65)
- **Reason:** Small faces at 480p + ipadapter_only bridge
- **Action:** Re-tighten after DWPreprocessor installed

### 4. Identity Audit Failures
- **Root Causes:**
  - Small faces at 480p resolution
  - ipadapter_only bridge without pose conditioning
  - NOT a resolution issue (512→480 makes minimal difference)
- **Fix:** DWPreprocessor installation, not resolution increase

---

## 🧪 RUNPOD TESTS NEEDED

### Test 1: Verify Bug Fixes
```bash
# On RunPod with updated code
cd /workspace/continuum
python -m pytest tests/ -v -k "test_pipeline"
```

### Test 2: Full Pipeline with World State
```bash
# Create test scene graph with events
python main.py --input test_scene_with_events.json --output /workspace/outputs/
```

### Test 3: DWPreprocessor Installation
```bash
# After installing DWPreprocessor
python -c "from comfyui_controlnet_aux import DWPreprocessor; print('OK')"
```

### Test 4: Bridge Frame Quality Comparison
```bash
# Compare ipadapter_only vs full bridge
python tests/test_bridge_quality.py --mode comparison
```

---

## 📋 CONSOLIDATED TASK TRACKER

### Tier 1: Critical Path (RunPod Required)
| # | Task | Status | Blocker |
|---|------|--------|---------|
| 1 | Install DWPreprocessor models | 🔲 | RunPod access |
| 2 | Test bridge_full.json with pose | 🔲 | Task 1 |
| 3 | Re-tighten identity threshold | 🔲 | Task 2 |
| 4 | Install KSamplerBatch node | 🔲 | RunPod access |

### Tier 2: Quality Improvements (Local Prep Done)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 5 | Accept-on-final-attempt pattern | ✅ | In reviewer.py |
| 6 | Identity debug logging | ✅ | In identity_checker.py |
| 7 | I2V workflow verification | ✅ | In workflow_loader.py |
| 8 | RIFE multiplier fix | ✅ | In rife_interpolator.py |
| 9 | Color matcher short video fix | ✅ | In color_match.py |
| 10 | World State tracking | ✅ | 4 files updated |

### Tier 3: Architecture Completion
| # | Task | Status | Notes |
|---|------|--------|-------|
| 11 | Physics checker world state integration | 🔲 | Validate positions match |
| 12 | Create test scene graph with events | 🔲 | Verify end-to-end |
| 13 | LoRA training pipeline | 🔲 | Phase 2 |
| 14 | Sonic Engine integration | 🔲 | Phase 2 |
| 15 | Director Agent LLM calls | 🔲 | Phase 2 |

### Tier 4: Production Hardening
| # | Task | Status | Notes |
|---|------|--------|-------|
| 16 | Checkpointing for long renders | 🔲 | Resume from failure |
| 17 | Cost tracking per render | 🔲 | Budget alerts |
| 18 | Multi-GPU job distribution | 🔲 | Scale out |
| 19 | Asset caching optimization | 🔲 | Reduce re-downloads |
| 20 | WebUI for job management | 🔲 | User-facing |

---

## 🚀 RECOMMENDED NEXT STEPS

### Immediate (Next Session)
1. **If RunPod available:**
   - Push latest code to pod
   - Run test suite to verify bug fixes
   - Install DWPreprocessor models
   - Test full bridge workflow

2. **If RunPod NOT available:**
   - Create test scene graph JSON with explicit events
   - Integrate Physics Checker with World State (Task #11)
   - Write unit tests for ShotEventParser

### Short-term
1. Re-tighten identity threshold after DWPreprocessor working
2. Complete Pass 2 with KSamplerBatch
3. End-to-end test with multi-shot scene graph

### Medium-term (Phase 2)
1. Director Agent LLM integration
2. Sonic Engine (TTS, Foley, Ambience)
3. LoRA training pipeline

---

## 📁 KEY FILE LOCATIONS

**Actual project structure (from VS Code):**

```
CONTINUUM/
├── docs/
├── src/
│   ├── audit/
│   │   ├── identity_checker.py      # Face verification (ArcFace)
│   │   ├── physics_checker.py       # Object tracking validation
│   │   └── reviewer.py              # Audit orchestration
│   │
│   ├── comfy_client/
│   │   ├── client.py                # ComfyUI WebSocket client
│   │   └── workflow_loader.py       # Load/inject workflow JSON
│   │
│   ├── core/
│   │   ├── checkpointing.py         # Save/resume
│   │   ├── config.py                # Configuration
│   │   ├── error_recovery.py        # Retry logic
│   │   ├── job_state.py             # Job status enums
│   │   └── model_loader.py          # Model tier system
│   │
│   ├── director/
│   │   ├── consistency_dict.py      # Static appearance tracking
│   │   ├── pacer.py                 # Shot timing/chunking
│   │   ├── scene_graph.py           # Scene/Shot/Chunk structures
│   │   ├── shot_event_parser.py     # NEW: Event extraction
│   │   └── world_state.py           # Dynamic state tracking
│   │
│   ├── memory/
│   │   ├── asset_store.py           # Asset storage
│   │   ├── cache.py                 # Caching layer
│   │   └── visual_rag.py            # Visual similarity search
│   │
│   ├── post/
│   │   ├── audio_ducker.py          # Lower music during dialogue
│   │   ├── color_match.py           # Color normalization
│   │   ├── ffmpeg_wrapper.py        # FFmpeg utilities
│   │   └── stitcher.py              # FFmpeg final assembly
│   │
│   ├── renderers/
│   │   ├── base.py                  # BaseRenderer ABC
│   │   └── wan_renderer.py          # ComfyUI Wan renderer
│   │
│   ├── sonic/
│   │   ├── ambience.py              # Background audio
│   │   ├── foley.py                 # Sound effects
│   │   ├── lip_sync.py              # Lip sync (Musetalk)
│   │   ├── mixer.py                 # Audio mixing
│   │   ├── tts_engine.py            # Text-to-speech
│   │   └── types.py                 # Sonic type definitions
│   │
│   └── studio/
│       ├── bridge_engine.py         # Identity re-anchoring
│       ├── pass1_generator.py       # Video generation orchestration
│       ├── pass2_refiner.py         # Flicker reduction
│       ├── rife_interpolator.py     # Frame interpolation
│       └── workflow_utils.py        # Workflow helpers
│
├── tests/
├── workflows/                       # ComfyUI JSON templates
│   ├── bridge_full.json             # ✓ CORRECT: pose + IP-Adapter
│   ├── bridge_ipadapter.json        # Partial: IP-Adapter only
│   ├── pass1_img2vid.json           # I2V generation
│   └── ...
├── main.py                          # Entry point / orchestrator
├── ARCHITECTURE.md                  # Master blueprint
├── ARCHITECTURE_SUMMARY.md          # Dev-facing summary
├── LESSONS_LEARNED.md               # 61 documented gotchas
└── LLM_CODING_GUIDELINES.md         # Coding rules
```

**Note:** The Claude project `/mnt/project/` shows files flattened to root level, but actual project uses proper `src/` nesting. Use import paths like `from src.director.scene_graph import ...`

---

## 🔑 CRITICAL REMINDERS

1. **Always check LESSONS_LEARNED.md** before writing code that touches existing interfaces
2. **Syntax validate** all Python changes: `python3 -c "import ast; ast.parse(open('file.py').read())"`
3. **No line numbers** in code references - use context matching
4. **Try/except** around all ComfyUI/cloud calls
5. **Type hints** mandatory on all functions
6. **Source of truth** hierarchy: ARCHITECTURE.md > ARCHITECTURE_SUMMARY.md > code comments

---

## 🌐 RUNPOD ENVIRONMENT

| Item | Value |
|------|-------|
| Pod ID | `133k18vitib8kn` |
| GPU | RTX 4090 |
| ComfyUI Version | v0.4.0 |
| Working Directory | `/workspace/continuum` |
| Output Directory | `/workspace/outputs` |
| Models Directory | `/workspace/ComfyUI/models` |

---

## 📝 TRANSCRIPT REFERENCES

Full conversation history available at:
- `/mnt/transcripts/2025-12-21-21-30-39-world-state-tracking-implementation.txt` (current session)
- `/mnt/transcripts/journal.txt` (session index)

Use `view` tool to read specific sections if context needed.

---

*End of Handoff Document*