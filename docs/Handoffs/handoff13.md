# Continuum Engine - Development Handoff
**Date:** December 22, 2025  
**Session Focus:** T2V vs I2V Pipeline Analysis, Bridge Engine Testing, Architecture Documentation

---

# PART A: PROJECT CONTEXT (For New Readers)

## What is Continuum?

**Continuum Engine** is a neuro-symbolic AI filmmaking system that turns writers into filmmakers. Unlike random clip generators, we enforce **consistency** - the same character looks the same across a 5-minute film, props don't teleport, and the world obeys physics.

### The Vision
- **Input:** A script + character/location references
- **Output:** A 2-5 minute consistent narrative video with dialogue, music, and sound effects
- **Target:** "Pixar-on-Demand" for indie creators

### Core Philosophy
> "We do not generate random clips. We enforce consistency via Max-Duration + Smart-Cut strategy."

---

## Architecture Overview (Brain vs Muscle)

```
┌─────────────────────────────────────────────────────────────────┐
│                        CONTINUUM ENGINE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  LOCAL (MacBook M4) ─────────────────────────────────────────── │
│  ├── Python Orchestrator (main.py)                              │
│  ├── Director Agent (LLM API calls)                             │
│  ├── Scene Graph Parser                                         │
│  └── Job Dispatch & Monitoring                                  │
│                                                                  │
│  CLOUD (RunPod GPU) ─────────────────────────────────────────── │
│  ├── ComfyUI Server                                             │
│  ├── Video Models (Wan 2.1 T2V/I2V)                             │
│  ├── SDXL + ControlNet + IP-Adapter (Bridge Engine)             │
│  ├── LoRA Training (character/location)                         │
│  └── Audio Models (TTS, Ambience, Foley)                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### The Consistency Stack

| Layer | Purpose | Implementation |
|-------|---------|----------------|
| **Identity Lock** | Same character throughout | IP-Adapter (instant) + LoRA (enhanced) + ArcFace (audit) |
| **World Consistency** | Same locations/props | Visual RAG + Location IP-Adapter |
| **Narrative Flow** | Seamless transitions | Bridge Frames + Smart Cuts |
| **Temporal Coherence** | No drift over time | Max 12s chunks + re-anchoring |

### The Bridge Frame (Core Innovation)

The **Bridge Engine** is our secret sauce. Before each new video chunk:
1. Extract **pose** from last frame (ControlNet)
2. Inject **canonical identity** from references (IP-Adapter)
3. Generate **perfect first frame** for next chunk (SDXL)
4. Feed to video model as `init_image`

This prevents the "drift problem" where characters slowly morph over long generations.

---

## What We've Built ✅

### Infrastructure
- [x] ComfyUI client with WebSocket job tracking
- [x] Workflow loader with parameter injection
- [x] Multi-tier model configuration (dev/standard/beast)
- [x] Checkpoint system for crash recovery
- [x] Progress reporting with callbacks

### Video Pipeline (Pass 1)
- [x] T2V generation via Wan 2.1
- [x] I2V generation via Wan 2.1
- [x] Bridge Engine with 4-tier fallback:
  - Tier 1: Full (ControlNet Pose + Depth + IP-Adapter)
  - Tier 2: Pose only (ControlNet + IP-Adapter)
  - Tier 3: IP-Adapter only
  - Tier 4: Raw frame passthrough
- [x] Automatic retry with seed variation
- [x] Shot chunking (max 12s per chunk)

### Video Pipeline (Pass 2)
- [x] Vid2Vid refinement workflow
- [x] RIFE frame interpolation (12fps → 24fps)
- [x] Lip sync integration (MuseTalk via ComfyUI)

### Audio Pipeline (Stubbed)
- [x] TTS engine interface (ElevenLabs)
- [x] Ambience generator interface (AudioLDM2)
- [x] Foley engine interface (Freesound)
- [x] Audio mixer with ducking

### Post-Production
- [x] Color matching across shots
- [x] FFmpeg stitcher
- [x] Audio ducking during dialogue

### Director Agent (Partial)
- [x] Scene graph data structures
- [x] Consistency dictionary (character → assets)
- [x] World state tracking (object positions)
- [x] Shot event parser
- [ ] LLM script parsing (manual JSON for now)

---

## What's Remaining ❌

### Critical for MVP

| Feature | Status | Blocker |
|---------|--------|---------|
| **Hero Frame (Shot 1 Identity)** | ❌ Not started | T2V doesn't use refs → first shot has wrong character |
| **Real Identity Audit** | ❌ Stubbed | ArcFace check always passes |
| **Director Agent LLM** | ❌ Manual | Must hand-write scene graph JSON |
| **DWPreprocessor on RunPod** | ⚠️ Workaround | Pose extraction was failing, now fixed |

### Important for Quality

| Feature | Status | Notes |
|---------|--------|-------|
| **Pass 2 Refinement** | ⚠️ Untested | Connection fix added, needs verification |
| **Location LoRA** | ❌ Not in arch | IP-Adapter only works at matching angles |
| **Physics Checker** | ❌ Stubbed | Objects can teleport |
| **Flicker Detection** | ❌ Stubbed | No temporal QA |

### Nice to Have (Post-MVP)

- [ ] Pro Lane (Runway/Veo/Sora integration)
- [ ] Multi-character scenes with interaction
- [ ] Camera motion (dolly, pan, zoom)
- [ ] Real-time preview
- [ ] Web UI

---

## The Two-Lane Model

| Lane | Tech Stack | Cost | Use Case |
|------|------------|------|----------|
| **Standard** | Pure OSS (Wan/SDXL) | ~$0.50/min | Development, budget projects |
| **Pro** | Premium APIs + OSS repair | ~$6-12/min | Client demos, high-fidelity |

Currently only Standard Lane is implemented.

---

## Key Metrics (Current)

| Metric | Value | Target |
|--------|-------|--------|
| Max consistent duration | ~24s (2 chunks) | 5 minutes |
| Generation time per chunk | ~90s (T2V), ~430s (I2V) | <60s |
| Identity consistency | ~70% (no audit) | >95% |
| Cost per minute of video | ~$0.50 | <$1.00 |

---

## File Structure

```
Continuum/
├── main.py                 # Orchestrator entry point
├── src/
│   ├── audit/              # Quality assurance
│   │   ├── identity_checker.py   # ArcFace similarity
│   │   ├── physics_checker.py    # Object tracking
│   │   └── reviewer.py           # Audit orchestrator
│   ├── comfy_client/       # ComfyUI integration
│   │   ├── client.py             # WebSocket connection
│   │   └── workflow_loader.py    # JSON workflow injection
│   ├── core/               # Shared infrastructure
│   │   ├── checkpointing.py      # Crash recovery
│   │   ├── config.py             # Pydantic settings
│   │   ├── error_recovery.py     # Retry logic
│   │   ├── job_state.py          # Job tracking
│   │   └── model_loader.py       # Model tier management
│   ├── director/           # Scene understanding
│   │   ├── consistency_dict.py   # Character → asset mapping
│   │   ├── pacer.py              # Shot timing decisions
│   │   ├── scene_graph.py        # Script → structured data
│   │   ├── shot_event_parser.py  # Action extraction
│   │   └── world_state.py        # Object positions
│   ├── memory/             # Persistence & retrieval
│   │   ├── asset_store.py        # File management
│   │   ├── cache.py              # Generation cache
│   │   └── visual_rag.py         # Image similarity search
│   ├── post/               # Post-production
│   │   ├── audio_ducker.py       # Music ducking
│   │   ├── color_match.py        # Shot color consistency
│   │   ├── ffmpeg_wrapper.py     # FFmpeg utilities
│   │   └── stitcher.py           # Video concatenation
│   ├── renderers/          # Video generation backends
│   │   ├── base.py               # Abstract interface
│   │   └── wan_renderer.py       # Wan 2.1 implementation
│   ├── sonic/              # Audio pipeline
│   │   ├── ambience.py           # Background audio
│   │   ├── foley.py              # Sound effects
│   │   ├── lip_sync.py           # MuseTalk integration
│   │   ├── mixer.py              # Audio mixing
│   │   ├── tts_engine.py         # Text-to-speech
│   │   └── types.py              # Audio data types
│   └── studio/             # Video pipeline
│       ├── bridge_engine.py      # Identity re-anchoring
│       ├── pass1_generator.py    # Structure generation
│       ├── pass2_refiner.py      # Quality enhancement
│       ├── rife_interpolator.py  # Frame interpolation
│       └── workflow_utils.py     # Workflow helpers
├── tests/                  # Test projects and bibles
├── workflows/              # ComfyUI workflow JSONs
├── workspace/              # Output directory
├── ARCHITECTURE.md         # Full specification
└── ARCHITECTURE_SUMMARY.md # Dev-facing summary
```

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `ARCHITECTURE.md` | Master blueprint (1900+ lines) |
| `ARCHITECTURE_SUMMARY.md` | Implementation guide |
| `LESSONS_LEARNED.md` | Debugging history |
| `LLM_CODING_GUIDELINES.md` | Rules for AI coding assistants |
| `Runpod.md` | GPU setup instructions |

---

# PART B: CURRENT SESSION DETAILS

---

## 1. CURRENT STATE SUMMARY

### What's Working ✅

| Component | Status | Notes |
|-----------|--------|-------|
| **ComfyUI Connection** | ✅ Working | RunPod RTX 4090, wss:// connection stable |
| **T2V Generation (Shot 1)** | ✅ Working | ~86s for 12 frames, uses `pass1_structural.json` |
| **Bridge Frame Generation** | ✅ Working | `controlnet_full` method, ~350s (pose + depth + SDXL) |
| **I2V Generation (Shot 2+)** | ✅ Working | ~430s for 12 frames, uses `pass1_img2vid.json` |
| **Pose Extraction** | ✅ Working | After installing `scikit-image` on RunPod |
| **Depth Extraction** | ✅ Working | Used for bridge method selection |
| **Timeout Configuration** | ✅ Fixed | Env var is `CONTINUUM_COMFYUI__TIMEOUT_SEC` (not `TIMEOUT`) |

### What's Broken/Incomplete ❌

| Component | Status | Issue |
|-----------|--------|-------|
| **Shot 1 Identity** | ❌ Broken by Design | T2V doesn't use reference images → random character |
| **Pass 2 Refinement** | ⚠️ Fixed (untested) | Was "Not connected" error, added `_ensure_connected()` |
| **RIFE Interpolation** | ❓ Unknown | Ran but not verified output |
| **Audio Pipeline** | 🔇 Stubbed | No API keys configured |
| **Director Agent** | 📝 Manual | Scene graph is hand-written JSON |

---

## 2. THE CRITICAL INSIGHT: T2V vs I2V

### The Problem We Discovered

**Shot 1 uses T2V (text-to-video)** which does NOT use reference images:
```
Shot 1: T2V("woman in kitchen") → Model imagines random woman
Shot 2: Bridge re-anchors to YOUR refs → Different woman
Result: Jarring identity change between shots
```

**Visual proof from test run:**
- Shot 1: Straight blonde hair, young face, forward pose
- Shot 2: Wavy blonde hair, angular face, angled pose
- These are TWO DIFFERENT PEOPLE

### Why Bridge Doesn't Fix This

Bridge frame is designed to **RE-ANCHOR to canonical references**, not preserve the previous frame's identity:

```
Bridge Frame Process:
├── ControlNet: Extracts POSE from last frame
├── IP-Adapter: Injects identity from BIBLE REFERENCES (not last frame)
└── Output: YOUR character in the extracted pose
```

This is **correct behavior** - Bridge fixes drift. But it exposes that T2V never used references in the first place.

### The Solution: I2V-Only Pipeline (Hero Frame)

**Documented in ARCHITECTURE.md Section 7A** (we added this today):

```
OLD (Current - Broken):
  Shot 1: T2V ────────────────→ Random Alice
  Shot 2: Bridge → I2V ───────→ Your Alice (jarring cut!)

NEW (MVP Requirement):  
  Shot 1: Hero Frame (SDXL+IPA) → I2V → Your Alice
  Shot 2: Bridge Frame → I2V ─────────→ Your Alice (consistent!)
```

**Hero Frame = Bridge Frame for Shot 1** (same workflow, different trigger)

---

## 3. ARCHITECTURE DOCUMENTATION UPDATES

### Changes Made Today

| File | Section | Change |
|------|---------|--------|
| `ARCHITECTURE.md` | Section 7A (new) | Comprehensive T2V vs I2V documentation |
| `ARCHITECTURE.md` | 7A.1 | Fundamental difference (same model, different input) |
| `ARCHITECTURE.md` | 7A.2 | Why T2V for Shot 1 breaks consistency |
| `ARCHITECTURE.md` | 7A.3 | Unified I2V-only pipeline design |
| `ARCHITECTURE.md` | 7A.4 | Valid T2V use cases (exploration, training data) |
| `ARCHITECTURE.md` | 7A.5 | Development vs MVP transition plan |
| `ARCHITECTURE.md` | 7A.6 | Decision table |
| `ARCHITECTURE_SUMMARY.md` | After line 120 | T2V vs I2V transition plan |
| `ARCHITECTURE_SUMMARY.md` | MVP Limitations | Added "Shot 1 Pipeline" as first priority |

### MVP Limitations Table (Updated Priority)

```
Shot 1 Pipeline > Bridge Frame > DWPreprocessor > Identity Threshold > Identity Audit > Director Agent > Sonic Engine
```

---

## 4. CODE CHANGES MADE

### 4.1 Bridge Frame Caching (pass1_generator.py)

**Problem:** Bridge regenerated on every retry (wasted ~150-200s per timeout)

**Fix:** Moved bridge generation OUTSIDE retry loop

**Location:** `/mnt/project/pass1_generator.py`, function `_generate_chunk`

```python
# Bridge now generated ONCE before retry loop
cached_bridge_frame_path = None
if self.config.enable_bridge:
    cached_bridge_frame_path = await self._generate_bridge_frame(...)

while attempt < self.config.max_reroll_attempts:
    bridge_frame_path = cached_bridge_frame_path  # Reuse cached
    ...
```

### 4.2 Pass 2 Refiner Reconnection (pass2_refiner.py)

**Problem:** "Not connected to ComfyUI" error after long video generation

**Fix:** Added `_ensure_connected()` method with health check and auto-reconnect

**Location:** `/mnt/project/pass2_refiner.py`

```python
async def _ensure_connected(self):
    """Ensure client is connected, reconnecting if necessary."""
    client = await self._get_client()
    try:
        if not await client.health_check():
            raise ConnectionError("Health check failed")
    except Exception as e:
        logger.info(f"ComfyUI connection stale ({e}), reconnecting...")
        # ... reconnection logic
    return client
```

**Usage:** `refine()` now calls `_ensure_connected()` instead of `_get_client()`

---

## 5. CONFIGURATION NOTES

### Environment Variables

```bash
# Correct format (note TIMEOUT_SEC not TIMEOUT)
export CONTINUUM_COMFYUI__HOST="wss://your-runpod:8188"
export CONTINUUM_COMFYUI__TIMEOUT_SEC=600

# Test command
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --no-audit
```

### RunPod Setup Required

```bash
# Must install on RunPod for pose extraction
pip install scikit-image
```

---

## 6. TIMING BENCHMARKS (RTX 4090)

| Operation | Time | Notes |
|-----------|------|-------|
| T2V (12 frames) | ~86s | Fast, but wrong identity |
| Bridge Frame (full) | ~350s | Pose extract + Depth + SDXL |
| I2V (12 frames) | ~430s | Slower than T2V (image encoding) |
| Bridge (ipadapter_only) | ~150s | Fallback when pose fails |

**Total for 2-shot test:** ~15 minutes (including queue time)

---

## 7. NEXT STEPS (PRIORITIZED)

### P0: Hero Frame Implementation (Blocks MVP)

**Goal:** Shot 1 uses I2V with identity-locked first frame

**Tasks:**
1. Create `hero_frame.json` workflow (or reuse `bridge_full.json`)
2. Modify `pass1_generator.py` to detect "first shot" condition
3. Generate Hero Frame before Shot 1's I2V (same as Bridge but without pose extraction)
4. Add config flag: `generation.mode = "production"` vs `"exploration"`

**Acceptance:** Shot 1 and Shot 2 show the SAME character

### P1: Verify Pass 2 Refinement

**Goal:** Confirm the reconnection fix works

**Tasks:**
1. Run full test with Pass 2 enabled
2. Verify vid2vid refinement completes
3. Check output quality

### P2: Test RIFE Interpolation

**Goal:** Verify 12fps → 24fps upscaling works

**Tasks:**
1. Check `workspace/output/bridge_quick_test/interpolated/`
2. Verify frame count doubled
3. Check for artifacts

### P3: Location LoRA (Architecture Gap)

**Discussion from this session:**
- IP-Adapter for locations only works at matching angles
- Location LoRA would provide angle-independent scene consistency
- Same bootstrap process as character LoRA
- Should be added to Section 3E of ARCHITECTURE.md

**Not implemented yet - documented for future**

---

## 8. KNOWN ISSUES & TECHNICAL DEBT

### Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| T2V for Shot 1 | 🔴 High | Core identity problem, blocks MVP |
| I2V slower than T2V | 🟡 Medium | ~5x slower, acceptable for now |
| Bridge takes 350s | 🟡 Medium | Full method is slow but quality is better |
| Pass 2 untested after fix | 🟡 Medium | Reconnection logic added but not verified |

### Technical Debt

| Item | Location | Notes |
|------|----------|-------|
| Template fallback warnings | `wan_renderer.py` | `pass1_structural_ipadapter` and `pass1_img2vid_ipadapter` not found |
| CHARACTER_DESCRIPTION unused | `workflow_loader.py` | Injection warning for unknown parameter |
| World State warnings | `world_state.py` | "Shot not in history" for every shot |
| Progress percentage > 100% | `main.py` | Refinement shows 105%, 110%, etc. |

---

## 9. FILE LOCATIONS REFERENCE

### Key Files Modified Today

```
/mnt/project/ARCHITECTURE.md          # Added Section 7A (T2V vs I2V)
/mnt/project/ARCHITECTURE_SUMMARY.md  # Added transition plan + MVP limitation
/mnt/project/pass1_generator.py       # Bridge caching outside retry loop
/mnt/project/pass2_refiner.py         # Added _ensure_connected() method
```

### Key Test Files

```
tests/bridge_quick_test.json          # 2-shot test project
tests/bible.json                      # Character references
workspace/output/bridge_quick_test/   # Test outputs
```

### Workflow Files

```
workflows/pass1_structural.json       # T2V workflow
workflows/pass1_img2vid.json          # I2V workflow  
workflows/bridge_full.json            # Full bridge (ControlNet + IPA)
workflows/bridge_pose_extract.json    # Pose extraction
workflows/bridge_depth_extract.json   # Depth extraction
workflows/bridge_ipadapter.json       # IPA-only fallback
```

---

## 10. CONVERSATION TRANSCRIPT

Full conversation saved at:
```
/mnt/transcripts/2025-12-22-07-16-16-t2v-vs-i2v-pipeline-optimization.txt
```

Previous related transcript:
```
/mnt/transcripts/2025-12-22-07-15-18-background-scene-consistency-dual-ipadapter.txt
```

---

## 11. QUICK START FOR NEXT SESSION

```bash
# 1. Set environment
export CONTINUUM_COMFYUI__HOST="wss://YOUR-RUNPOD:8188"
export CONTINUUM_COMFYUI__TIMEOUT_SEC=600

# 2. Verify RunPod has scikit-image
ssh runpod "pip list | grep scikit"

# 3. Run test
cd ~/path/to/Continuum
python main.py --project tests/bridge_quick_test.json \
               --consistency tests/bible.json \
               --no-audit

# 4. Check outputs
open workspace/output/bridge_quick_test/pass1/*.mp4
```

---

## 12. KEY QUESTIONS FOR NEXT SESSION

1. **Hero Frame Implementation:** Should it be a separate workflow or reuse `bridge_full.json` with modified inputs?

2. **I2V Speed:** Can we optimize the 430s I2V time? Is the model loading on every call?

3. **Bridge Speed:** 350s is slow. Can we skip depth extraction and use pose-only?

4. **Pass 2 Testing:** Does the reconnection fix work? What's the refinement quality?

5. **Location LoRA:** When should this be prioritized? Is IP-Adapter sufficient for MVP?

---

*End of Handoff Document*