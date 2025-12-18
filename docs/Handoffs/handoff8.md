# Continuum Engine - Handoff Document
**Date:** 2025-12-18  
**From:** Previous Claude Session  
**To:** Next Claude Session  
**Reference:** `ARCHITECTURE_SUMMARY.md` (v2025.12.4)

---

## 1. Project Context

Continuum Engine is a "Pixar-on-Demand" system that lets writers become AI filmmakers. The core value proposition is **consistent character identity across multiple shots** — something current AI video tools fail at.

**Key Files:**
- `ARCHITECTURE_SUMMARY.md` — Working dev summary (SOURCE OF TRUTH for implementation)
- `ARCHITECTURE.md` — Full strategic vision
- `LESSONS_LEARNED.md` — Debugging history (37 entries)
- `LLM_CODING_GUIDELINES.md` — Coding rules

---

## 2. Current State vs Architecture

### What's Working ✅

| Component | Status | Notes |
|-----------|--------|-------|
| ComfyUI Client | ✅ Working | WebSocket connection to RunPod |
| WanRenderer | ✅ Working | T2V and I2V workflow dispatch |
| Pass1Generator | ✅ Working | Orchestrates shots with continuity frames |
| Workflow System | ✅ Working | JSON loading, parameter injection |
| Config System | ✅ Working | Tiered model configs (dev/standard/beast) |
| FFmpeg Wrapper | ✅ Working | Frame extraction, video probing |

### What's Stubbed/Partial 🟡

| Component | Status | Gap |
|-----------|--------|-----|
| Bridge Engine | 🟡 **INCORRECTLY BYPASSED** | See Section 3 below |
| Director Agent | 🟡 Stubbed | No LLM integration, manual JSON only |
| Identity Audit | 🟡 Stubbed | ArcFace code exists but not wired |
| Sonic Engine | 🟡 Stubbed | TTS/Foley/Ambience interfaces only |
| Pass 2 Refiner | 🟡 Partial | Workflow exists, integration incomplete |
| World State | 🟡 Stubbed | Data structures only |

### What's Not Started ❌

| Component | Notes |
|-----------|-------|
| LLM Client | No Claude/GPT/Gemini integration |
| Script Parser | No screenplay → scene graph conversion |
| Visual RAG | No Pinecone/vector DB |
| Multi-Character Scenes | No regional prompting |
| Layout Generator | No ControlNet depth maps |

---

## 3. ⚠️ CRITICAL: Bridge Frame Mistake (Needs Undoing)

### What The Architecture Intended

From `ARCHITECTURE.md` lines 174-179, the Bridge Frame system was designed to **prevent identity drift**:

```
Last Frame of Shot A
        │
        ▼
┌─────────────────────────────────────────┐
│  bridge_full.json                       │
│                                         │
│  ControlNet (OpenPose) ──► POSE         │
│  IP-Adapter (Bible refs) ► IDENTITY     │──► Bridge Frame
│  LoRA (if available) ────► IDENTITY     │
└─────────────────────────────────────────┘
        │
        ▼
Bridge Frame (pose preserved, identity RE-ANCHORED to canonical refs)
        │
        ▼
Wan I2V → Shot B (starts from corrected identity)
```

**Why this matters:** Video models drift. After 5+ shots, characters look different. The Bridge Frame re-anchors identity to canonical Bible refs EVERY cut, preventing drift accumulation.

### What We Incorrectly Implemented

In `pass1_generator.py`, method `_generate_bridge_frame()` (lines 671-727), we **bypassed** the bridge engine entirely:

```python
# CURRENT (WRONG) - just extracts raw frame, no re-anchoring
async def _generate_bridge_frame(...) -> Optional[Path]:
    await extract_last_frame(previous_video, last_frame_path)
    return last_frame_path  # ← Direct to Wan I2V, NO identity correction
```

**The reasoning at the time:**
- `bridge_basic.json` was broken (vanilla SDXL img2img, no ControlNet/IP-Adapter)
- Raw frame → Wan I2V keeps same model family (no style mismatch)
- "Good enough for 2-shot test"

**Why this is wrong:**
- Drift accumulates: Shot 1 (100%) → Shot 5 (80%) identity match
- The architecture REQUIRES re-anchoring via `bridge_full.json`
- We traded style consistency for identity drift — bad tradeoff

### What Needs To Be Done

**Option A: Wire up `bridge_full.json` properly**

1. Verify `bridge_full.json` has correct nodes:
   - LoadImage (source frame)
   - ControlNet OpenPose (extracts pose)
   - LoadImage (Bible face refs)
   - IP-Adapter (identity injection)
   - LoRA loader (if available)
   - KSampler with SDXL
   - SaveImage

2. Update `bridge_engine.py` to:
   - Select `bridge_full.json` (not `bridge_basic.json`)
   - Upload Bible refs from ConsistencyDict
   - Pass character LoRA if available

3. Revert `pass1_generator._generate_bridge_frame()` to call `bridge_engine.generate()`

4. Fix the property name bug: `bridge_result.frame_path` (not `bridge_frame_path`)

**Option B: Implement identity re-anchoring in Wan I2V directly**

Alternative approach — skip SDXL bridge, but add IP-Adapter identity injection to the Wan I2V workflow itself. This would:
- Keep same model family (Wan throughout)
- Still re-anchor identity via IP-Adapter
- Require new workflow: `pass1_img2vid_ipadapter.json`

**Recommended:** Option A first (uses existing architecture), then evaluate Option B.

### Files Changed In Previous Session

| File | Change | Status |
|------|--------|--------|
| `pass1_generator.py` | Simplified `_generate_bridge_frame()` to skip bridge engine | ⚠️ NEEDS REVERTING |
| `ARCHITECTURE_SUMMARY.md` | Updated to document MVP limitation | ✅ Now correct |
| `LESSONS_LEARNED.md` | Added entry #37 about bridge fix | ✅ Keep but note it was temporary |

---

## 4. Test That Was Running

```bash
python main.py --project tests/sample_project_2shot.json --no-resume --no-audio --no-post --verbose 2>&1
```

**Expected behavior:**
- Shot 1: T2V workflow (`pass1_structural.json`)
- Extract last frame
- Shot 2: I2V workflow (`pass1_img2vid.json`) with last frame as init

**This test validates pipeline connectivity, NOT identity consistency.** For identity consistency, need 5+ shots with ArcFace comparison.

---

## 5. LLM Configuration (Established)

The Director Agent should use **cloud LLM APIs** (not local):

| Provider | Model | Use Case |
|----------|-------|----------|
| Anthropic | Claude Opus 4.5 | Complex reasoning, script parsing |
| OpenAI | GPT-5.2 | Fast structured output |
| Google | Gemini 3 Pro | Long context, multimodal |
| Local (Ollama) | Llama 3.1 8B | **Fallback only** |

Config keys added to `ARCHITECTURE_SUMMARY.md`:
```yaml
CONTINUUM_LLM_PROVIDER: "anthropic"
CONTINUUM_LLM_MODEL: "claude-opus-4-5-20251101"
```

---

## 6. Priority for Production (Updated)

| Priority | Task | Why |
|----------|------|-----|
| **P1** | Fix Bridge Frame (wire `bridge_full.json`) | Prevents drift — CORE VALUE |
| **P2** | Wire Identity Audit (ArcFace) | Catches drift automatically |
| **P3** | Add LLM Client | Enables script parsing |
| **P4** | Script → Scene Graph | Automates pipeline |
| **P5** | Sonic Engine (TTS + Lip Sync) | No more silent films |

---

## 7. Key Lessons From This Session

1. **Bridge Frame is NOT optional** — it's the core drift-correction mechanism
2. **Raw frame I2V causes drift accumulation** — fine for 2-shot tests, breaks at 5+ shots
3. **`bridge_basic.json` is useless** — has no ControlNet or IP-Adapter
4. **`bridge_full.json` is the correct workflow** — needs to be wired up
5. **Style consistency ≠ Identity consistency** — we optimized for wrong thing

---

## 8. Relevant Code Locations

| Purpose | File | Lines/Method |
|---------|------|--------------|
| Bridge frame generation | `pass1_generator.py` | `_generate_bridge_frame()` (671-727) |
| Bridge engine | `bridge_engine.py` | `ComfyUIBridgeEngine.generate()` |
| Bridge workflows | `bridge_*.json` | `bridge_full.json` is correct one |
| Workflow selection | `wan_renderer.py` | `_select_workflow_template()` (416-455) |
| Job spec with init_frame | `base.py` | `JobSpec` dataclass (124-198) |
| Bible refs storage | `consistency_dict.py` | `ConsistencyDict` class |

---

## 9. Questions For Next Session

1. Should we revert `pass1_generator.py` to call bridge engine, or implement Option B (Wan I2V with IP-Adapter)?
2. Is `bridge_full.json` workflow actually complete? Need to verify nodes.
3. How do we get Bible refs into bridge engine? (ConsistencyDict integration)
4. Should bridge run for EVERY shot, or only when drift detected?

---

## 10. How To Verify Understanding

Ask the next Claude to:
1. Explain why raw frame → I2V causes drift
2. Describe what `bridge_full.json` should do (pose + identity)
3. Locate the code that needs reverting (`pass1_generator._generate_bridge_frame`)
4. Explain the difference between `bridge_basic.json` and `bridge_full.json`

If it can't answer these, point it to this document and `ARCHITECTURE_SUMMARY.md`.

---

*End of Handoff*