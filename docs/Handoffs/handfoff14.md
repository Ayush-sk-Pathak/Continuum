# 🔧 CONTINUUM ENGINE - SESSION HANDOFF

**Date:** December 22, 2025  
**Session Summary:** P0 Hero Frame + P1 Identity Audit Health Check Complete  
**Next Session Focus:** E2E GPU Testing on RunPod

---

## 1. Role & Vision

You are the co-founder and Lead Architect of **Continuum Studios**. We are building the **"Continuum Engine"** — a neuro-symbolic system that allows writers to become AI Filmmakers.

**Core Philosophy:** We do not just generate random clips. We enforce consistency via a **"Max-Duration + Smart-Cut"** strategy (StreamingT2V + Bridge Frames).

**Sources of Truth:**
- `ARCHITECTURE.md` — Master Blueprint (strategy, rationale)
- `ARCHITECTURE_SUMMARY.md` — Working dev summary (wins for implementation)
- `LESSONS_LEARNED.md` — Debugging history and interface gotchas

---

## 2. The "Vibe Coder" Constraint (Non-Negotiable)

The human is a **vibe coder**: systems thinker, not a low-level engineer.

| Principle | Meaning |
|-----------|---------|
| **Brain vs Muscle** | Logic (Director Agent) runs Locally (MacBook M4/Cloud LLM APIs). Rendering runs on Cloud GPUs (ComfyUI). |
| **Glue over Ground-Up** | Your job is writing Python glue code to orchestrate ComfyUI workflows. Never suggest writing custom CUDA kernels or training base models. |
| **Pluggable Engines** | Use abstract interfaces (`BaseRenderer`, `BaseBridgeEngine`, `BaseIdentityChecker`) so we can hot-swap models without rewriting logic. |

---

## 3. System Architecture

### 3A. The Director Agent (Local Brain)
- **Planner:** Parses script into Scene Graph (JSON)
- **State Manager:** Maintains Consistency Dictionary (Assets, LoRAs) and World State (prop locations)
- **The Reviewer:** Checks frames for Physics (gravity/teleportation) and Identity drift

### 3B. The Visual Pipeline (Cloud Muscle - Track A)
- **Pass 1 (Structure):** Streaming T2V + Bridge Frame injection (seamless cuts) + CoNo
- **Pass 2 (Refinement):** Vid2Vid / FreeLong++ for flicker reduction
- **Lane Logic:** Supports "Standard Lane" (OSS) and "Pro Lane" (Hybrid/Veo with Repair)

### 3C. The Sonic Engine (Cloud Muscle - Track B)
- Runs in **parallel** with Video
- Generates: Ambience (AudioLDM-2), Foley (Event-triggered), Score (MusicGen), Dialogue (TTS + Lip Sync)

### 3D. Post-Production Engine
- **Colorist:** Auto-Color Normalization (Histogram matching to Master Shot)
- **Mixer:** Smart Audio Ducking (lowers music during dialogue)

---

## 4. Current Implementation Status

### ✅ COMPLETE (P0 + P1)

| Component | File | Status |
|-----------|------|--------|
| Hero Frame Workflow | `hero_frame.json` | ✅ SDXL + IP-Adapter for Shot 1 identity lock |
| Shot1Strategy Enum | `pass1_generator.py` | ✅ HERO_FRAME / EXPLORATION / USER_KEYFRAME |
| `_get_init_frame()` Router | `pass1_generator.py` | ✅ Unified Shot 1 and Shot 2+ init frame paths |
| `_generate_hero_frame()` | `pass1_generator.py` | ✅ Generates identity-locked first frame |
| `HeroFrameSpec` / `HeroFrameResult` | `bridge_engine.py` | ✅ Data structures for hero frame generation |
| `generate_hero_frame()` Abstract | `bridge_engine.py` | ✅ Interface in BaseBridgeEngine |
| `generate_hero_frame()` ComfyUI | `bridge_engine.py` | ✅ ComfyUIBridgeEngine implementation |
| `generate_hero_frame()` Mock | `bridge_engine.py` | ✅ MockBridgeEngine implementation |
| Hero Frame Design Tests | `test_hero_frame.py` | ✅ 11 tests passing |
| **Fail-Fast Health Check** | `main.py` | ✅ **NEW THIS SESSION** - Eager ArcFace initialization |
| Health Check Tests | `test_audit_health_check.py` | ✅ **NEW THIS SESSION** - 15 tests |

### 🔶 INFRASTRUCTURE EXISTS BUT NEEDS VERIFICATION

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| ArcFace Identity Checker | `identity_checker.py` | 🔶 Code complete | Needs `insightface` installed on RunPod |
| Physics Checker | `physics_checker.py` | 🔶 Code complete | Uses YOLO + ByteTrack |
| Reviewer Aggregation | `reviewer.py` | 🔶 Code complete | Orchestrates identity + physics checks |
| Bridge Frame Generation | `bridge_engine.py` | 🔶 Code complete | Uses `bridge_full.json` workflow |
| Pass 2 Refinement | `pass2_refiner.py` | 🔶 Code complete | Uses `refine_vid2vid_temporal.json` |
| RIFE Interpolation | `rife_interpolator.py` | 🔶 Code complete | 12fps → 24fps |

### ❌ NOT YET IMPLEMENTED

| Component | Priority | Notes |
|-----------|----------|-------|
| Director Agent (LLM) | P2 | Manual scene graph JSON for now |
| Sonic Engine (TTS/Ambience/Foley) | P3 | Stubbed interfaces exist |
| World State Tracking | P3 | Data structures exist, logic stubbed |
| DWPreprocessor on RunPod | P1 | Missing from comfyui_controlnet_aux |

---

## 5. What Changed This Session

### 5A. Fail-Fast Health Check (main.py)

**Problem:** Identity checker was lazily initialized. If `insightface` wasn't installed, audits silently passed (open-loop system).

**Solution:** Added eager health check in `ContinuumOrchestrator.setup()`:

```python
# Location: main.py, lines 702-725 (after reviewer creation)
health = await self.reviewer.health_check()

if not health.get("identity", False):
    error_msg = (
        "Identity checker failed to initialize.\n"
        "The audit system cannot verify character consistency.\n\n"
        "To fix:\n"
        "  pip install insightface onnxruntime\n\n"
        "Or disable audit (not recommended for production):\n"
        "  python main.py --project <file> --no-audit"
    )
    logger.error(error_msg)
    raise RuntimeError("Identity checker initialization failed.")
```

**Why This Matters:** The feedback loop is now CLOSED:
- Before: Setup → (insightface missing) → Audits silently pass → No rerolls ever
- After: Setup → health_check() → FAIL FAST with clear error message

### 5B. Health Check Tests (test_audit_health_check.py)

15 tests covering:
- `TestMockIdentityCheckerHealth` (2 tests)
- `TestArcFaceIdentityCheckerHealth` (3 tests)  
- `TestReviewerHealthCheck` (3 tests)
- `TestFailFastInitialization` (2 tests)
- `TestFactoryFunctionHealth` (2 tests)
- `TestThresholdConfiguration` (3 tests)

**Run with:**
```bash
python -m pytest tests/test_audit_health_check.py -v
```

---

## 6. Known Issues & Gotchas

### 6A. Import Path Issue (CRITICAL)

Claude's `/mnt/project/` shows files FLATTENED. Actual project uses nested `src/` structure.

| Claude sees | Actual path | Import statement |
|-------------|-------------|------------------|
| `/mnt/project/identity_checker.py` | `src/audit/identity_checker.py` | `from src.audit.identity_checker import ...` |
| `/mnt/project/pass1_generator.py` | `src/studio/pass1_generator.py` | `from src.studio.pass1_generator import ...` |
| `/mnt/project/reviewer.py` | `src/audit/reviewer.py` | `from src.audit.reviewer import ...` |

**Always use `from src.<package>.<module> import ...`**

### 6B. types.py Shadows stdlib

The project has a `types.py` that conflicts with Python's stdlib `types` module. Running Python from `/mnt/project/` causes import errors. Run from `/tmp/` or project root instead.

### 6C. Identity Threshold Relaxed

Current threshold is **0.50** (in `config.py`), relaxed from architectural target of **0.70**.

**Why:** DWPreprocessor (pose extraction) is missing on RunPod, so bridge frames use `ipadapter_only` fallback which produces lower identity scores.

**Fix:** Install `comfyui_controlnet_aux` properly on RunPod, then tighten threshold.

### 6D. RunPod Dependencies

Required but may be missing:
```bash
pip install insightface onnxruntime scikit-image
```

---

## 7. File Structure (Brain vs Muscle)

```
src/
├── core/           # Infrastructure (config, job_state, checkpointing)
├── director/       # Brain (scene_graph, consistency_dict, world_state, pacer)
├── audit/          # QA (identity_checker, physics_checker, reviewer)
├── studio/         # Video Pipeline (pass1_generator, bridge_engine, pass2_refiner)
├── sonic/          # Audio Pipeline (tts_engine, ambience, foley, mixer, lip_sync)
├── post/           # Post-Production (color_match, audio_ducker, stitcher)
├── renderers/      # Model Abstractions (base, wan_renderer)
├── comfy_client/   # ComfyUI Integration (client, workflow_loader)
└── memory/         # RAG & Caching (visual_rag, cache, asset_store)

workflows/          # ComfyUI JSON workflows
tests/              # Test files
main.py             # Orchestrator entry point
```

---

## 8. Coding Rules

1. **Precise Locations:** Always specify: `File: path/to/file.py`, `Function: name()`, `Insert AFTER: "code_anchor"`
2. **No Line Numbers:** Use context matching (line numbers shift)
3. **Error Handling:** All Cloud/ComfyUI calls must have try/except with logging
4. **Type Hinting:** Mandatory. `def render(scene: SceneData) -> RenderResult:`
5. **Imports:** Always use `from src.<package>.<module> import ...`

---

## 9. Debug Framework

When reporting errors, use this format:

```
ROOT CAUSE: (Technical explanation)
EXACT FIX: (The specific code block to change)
WHY: (ELI5 reason this fixes it and prevents recurrence)
RETEST: (Exact command/script to verify the fix)
```

---

## 10. Next Steps (Priority Order)

### P1: E2E GPU Test on RunPod

**Goal:** Run actual generation to verify Shot 1 = Shot 2 visually.

**Prerequisites:**
1. RunPod instance running with ComfyUI
2. `insightface` installed: `pip install insightface onnxruntime`
3. Test assets (character refs, scene graph)

**Test Command:**
```bash
python main.py --project tests/two_shot_alice.json --consistency tests/bible.json
```

**What to Verify:**
- [ ] Health check passes (identity checker loads)
- [ ] Hero frame generates for Shot 1
- [ ] Bridge frame generates for Shot 2
- [ ] Identity audit runs (real ArcFace, not mock)
- [ ] Visual inspection: Alice looks the same in both shots

### P2: Tighten Identity Threshold

Once DWPreprocessor is working:
1. Change `identity_threshold: 0.50` → `0.70` in `config.py`
2. Run E2E test and verify audit still passes

### P3: Director Agent Integration

Wire up LLM to auto-parse scripts into scene graphs.

---

## 11. Test Commands Reference

```bash
# Hero Frame tests (design verification)
python -m pytest tests/test_hero_frame.py -v

# Health Check tests
python -m pytest tests/test_audit_health_check.py -v

# All tests
python -m pytest tests/ -v

# Dry run (mock implementations, no GPU)
python main.py --project tests/sample.json --dry-run

# Full pipeline (requires RunPod)
python main.py --project tests/two_shot_alice.json --consistency tests/bible.json
```

---

## 12. Key Architecture Decisions

### Why I2V-First (Not T2V)?

```
T2V for Shot 1: Model imagines "Alice" → RANDOM appearance
  Shot 2 uses Bridge → OUR Alice
  RESULT: Shot 1 ≠ Shot 2 (jarring!)

I2V for ALL shots: Hero Frame has OUR Alice → I2V
  Shot 2 Bridge has OUR Alice → I2V
  RESULT: Shot 1 = Shot 2 = Shot N (consistent!)
```

### Why Fail-Fast Health Check?

Without working identity checker, the system is "generating on faith":
- Audits pass regardless of quality
- Reroll logic never triggers
- Drift accumulates undetected

The health check ensures we detect this at startup, not after expensive GPU work.

### Why Bridge Frames (Not Raw Last Frame)?

Raw last frame → I2V causes **drift accumulation** because:
- Model adds its own "interpretation" each cycle
- After 5+ shots, character looks completely different

Bridge Frame (ControlNet + IP-Adapter) → I2V **re-anchors identity** because:
- IP-Adapter injects canonical character embedding
- ControlNet preserves pose from last frame
- Result: Identity locked to bible, pose preserved from story

---

## 13. Session Transcripts

Previous session transcripts are stored in `/mnt/transcripts/`:
- `2025-12-23-05-05-07-hero-frame-implementation-planning.txt`
- `2025-12-23-05-20-03-hero-frame-implementation-complete.txt`
- `2025-12-23-05-45-16-hero-frame-p0-tests-complete.txt`

Current session added:
- Fail-fast health check in `main.py`
- `test_audit_health_check.py` (15 tests)

---

## 14. Questions to Ask Human

Before starting work:
1. "Is RunPod instance running? What's the pod ID?"
2. "Is `insightface` installed on RunPod?"
3. "Do we have test assets (alice refs, scene graph JSON)?"

---

*This handoff document was generated at the end of the P1 Identity Audit session. The feedback loop is now closed — the system will fail fast if identity checking can't work, rather than silently passing all audits.*