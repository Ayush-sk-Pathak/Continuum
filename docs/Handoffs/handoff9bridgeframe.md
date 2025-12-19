# CONTINUUM ENGINE - HANDOFF DOCUMENT
**Date:** 2025-12-19  
**Session Focus:** Bridge Frame Architecture Clarification + MVP Planning  
**Status:** Ready for Phase 1 Implementation

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [What Is Continuum Engine](#2-what-is-continuum-engine)
3. [The Bridge Frame — Critical Understanding](#3-the-bridge-frame--critical-understanding)
4. [Current Implementation Status](#4-current-implementation-status)
5. [What Was Done This Session](#5-what-was-done-this-session)
6. [Detailed Plan to MVP](#6-detailed-plan-to-mvp)
7. [Source of Truth Documents](#7-source-of-truth-documents)
8. [Code Patterns & Gotchas](#8-code-patterns--gotchas)
9. [Verification Commands](#9-verification-commands)
10. [For the Next Claude Session](#10-for-the-next-claude-session)

---

## 1. Executive Summary

### One-Liner
Continuum Engine is a "Pixar-on-Demand" AI filmmaking system that generates 2-5 minute videos with **consistent character identity across multiple shots** — the thing every other AI video tool fails at.

### Core Value Proposition
> "Can you generate Shot A, then Shot B, and have them look like the same character in the same world?"

### Current State
- **Infrastructure:** ✅ Working (ComfyUI client, workflows, renderer)
- **Bridge Frame:** ✅ Code wired, ⚠️ NOT YET PROVEN end-to-end
- **Identity Verification:** 🔴 Stubbed (always returns "pass")
- **MVP Status:** Blocked on proving bridge frame actually works

### Critical Insight From This Session
**The Bridge Frame is not "a feature." It IS the product.** Without it, identity drifts and we're just another random clip generator. Everything else (LLM parsing, audio, refinement) is blocked until bridge is proven.

---

## 2. What Is Continuum Engine

### The Problem We Solve
AI video models have **no memory between generation calls**. Each 4-12 second clip starts fresh. Over multiple shots:
- Characters change appearance (drift)
- Props teleport
- Emotions reset
- Locations morph

### Our Solution: The Bridge Frame Strategy
Instead of fighting for longer generation, we embrace cuts and **re-anchor identity at every cut**:

```
Shot 1 → BRIDGE → Shot 2 → BRIDGE → Shot 3 → BRIDGE → Shot 4
100%     ↑100%    100%     ↑100%    100%     ↑100%    100%
Alice    │        Alice    │        Alice    │        Alice
         │                 │                 │
   Re-anchor from    Re-anchor from   Re-anchor from
   Bible refs        Bible refs       Bible refs
```

### Hardware Architecture
| Layer | Hardware | Role |
|-------|----------|------|
| **Brain (Local)** | MacBook M4 | Python orchestration, job dispatch |
| **Brain (Cloud)** | LLM APIs (Claude/GPT) | Director Agent intelligence |
| **Muscle (Cloud)** | RunPod GPUs + ComfyUI | Video generation, bridge frames |

### The Human
- **Role:** Co-founder, Lead Architect
- **Style:** "Vibe Coder" — systems thinker, not low-level engineer
- **Constraints:** No custom CUDA. Python glue code to orchestrate ComfyUI workflows.

---

## 3. The Bridge Frame — Critical Understanding

### ⚠️ THIS SECTION IS MANDATORY READING ⚠️

The Bridge Frame has been misunderstood multiple times during development. This section clarifies once and for all.

### 3.1 What Is a Bridge Frame?

A **synthetically generated image** that serves as the "perfect first frame" for any new video generation.

**Technical Flow:**
```
Last frame of Shot A (pose, expression)
         ↓
    ControlNet extracts pose
         ↓
    IP-Adapter re-injects canonical identity from "Bible refs"
         ↓
    SDXL generates identity-locked frame
         ↓
    Wan I2V continues video from this frame
         ↓
Shot B starts with 100% correct identity
```

### 3.2 Why SDXL (Not Wan)?

| Question | Answer |
|----------|--------|
| Why not use Wan for bridge? | Wan is a VIDEO model. It doesn't have IP-Adapter for single image generation. |
| Won't SDXL cause style mismatch? | The bridge is ONE frame. Wan immediately overwrites the style in frame 2+. Identity survives. |
| Why not just pass raw frame? | Raw frame has no identity re-anchoring. Drift continues from wherever Shot A ended. |

### 3.3 When Is Bridge Frame Needed?

**Rule:** If you're calling the video model to generate NEW frames, you need a Bridge Frame.

| Scenario | Bridge Needed? | Why |
|----------|----------------|-----|
| Shot A → Shot B (camera change) | ✅ YES | New generation |
| Chunk 1 → Chunk 2 (same shot, 12s max) | ✅ YES | Generation restart |
| Re-roll after audit failure | ✅ YES | New generation |
| Repair/patch a bad frame | ✅ YES | New generation |
| First shot of the film | ❌ NO | Nothing to bridge from |
| Within a single 12s chunk | ❌ NO | Continuous generation |
| Pass 2 refinement (vid2vid) | ❌ NO | Existing video, not new gen |

### 3.4 Why Bridge Frame Must NEVER Be Bypassed

**Historical bypass attempts (all failed):**

| Bypass Reasoning | Why It Fails |
|------------------|--------------|
| "Raw frame is good enough" | Wan continues VIDEO, not IDENTITY. Drift compounds. |
| "LoRA handles identity" | LoRA biases but doesn't LOCK. Model can still drift within LoRA range. |
| "Bridge adds latency" | Fast garbage is still garbage. You're iterating on broken pipeline. |
| "Same model family is better" | One SDXL frame doesn't matter. Identity lock is what matters. |

**The Rule:** If you're tempted to bypass bridge, you're solving the wrong problem.

### 3.5 Current Bridge Implementation

**Workflow:** `bridge_full.json`
- ControlNet Pose (preserves body position)
- ControlNet Depth (preserves spatial relationships)
- IP-Adapter (re-injects canonical identity)
- LoRA (character-specific boost, if available)

**Code Location:** 
- `pass1_generator.py` → `_generate_bridge_frame()` (lines 671-808)
- `bridge_engine.py` → `ComfyUIBridgeEngine.generate()`

**Status:** Code is wired. Not yet tested end-to-end with real models.

### 3.6 Future Enhancement: Multi-Frame Bridge

**Problem:** Single frame can cause "motion freeze" (character holds pose unnaturally).

**Solution (Phase 2+):** Generate 3-5 frame sequence using RIFE interpolation.

**Status:** NOT IMPLEMENTED. Test single-frame first. Upgrade only if users report issues.

---

## 4. Current Implementation Status

### Priority Modules (from ARCHITECTURE_SUMMARY.md)

| Priority | Module | Status | Notes |
|----------|--------|--------|-------|
| **P0** | `comfy_client/` | ✅ Working | WebSocket to ComfyUI |
| **P1** | `wan_renderer.py` | ✅ Working | T2V + I2V generation |
| **P2** | `scene_graph.py` | ✅ Working | Manual JSON input |
| **P3a** | I2V workflows | ✅ Created | `pass1_img2vid.json` |
| **P3b** | LoRA workflows | ✅ Created | `pass1_img2vid_lora.json` |
| **P4** | `bridge_engine.py` | ⚠️ Wired, not proven | Needs E2E test |
| **P5** | `identity_checker.py` | 🔴 Stubbed | Always returns "pass" |
| **P6** | TTS + Lip Sync | 🔴 Not wired | Workflows exist |
| **P7** | Pass 2 + RIFE | 🟡 Partial | Workflows exist |
| **P8** | `world_state.py` | 🔴 Stubbed | Phase 2+ |

### Workflow Files (in `/workflows/`)

| Workflow | Purpose | Status |
|----------|---------|--------|
| `pass1_structural.json` | T2V base generation | ✅ Working |
| `pass1_structural_lora.json` | T2V + character LoRA | ✅ Working |
| `pass1_img2vid.json` | I2V base (uses bridge frame) | ✅ Working |
| `pass1_img2vid_lora.json` | I2V + LoRA | ✅ Working |
| `bridge_full.json` | ControlNet + IP-Adapter | ✅ Correct, use this |
| `bridge_pose_only.json` | ControlNet Pose only | 🟡 Fallback |
| `bridge_ipadapter.json` | IP-Adapter only | 🟡 Minimal fallback |
| `bridge_basic.json` | ❌ BROKEN | Do not use |
| `refine_vid2vid_simple.json` | Pass 2 frame-by-frame | ✅ Created |
| `refine_vid2vid_temporal.json` | Pass 2 batched | ✅ Created |
| `musetalk_lipsync.json` | Lip sync | ✅ Created |

### Test Status

| Test File | Tests | Status |
|-----------|-------|--------|
| `test_model_loader.py` | 27 | ✅ Passing |
| `test_workflow_contracts.py` | 59 | ✅ Passing |
| `test_workflow_stress.py` | 37 | ✅ Passing |
| **Total** | **123** | ✅ All passing |

---

## 5. What Was Done This Session

### 5.1 Bridge Frame Code Fix

**File:** `pass1_generator.py`  
**Method:** `_generate_bridge_frame()` (lines 671-808)

**Before (bypassed):**
```python
# Just returned raw last frame — identity drifts
return last_frame_path
```

**After (correct):**
```python
# 1. Extract last frame
# 2. Build BridgeSpec with character refs
# 3. Call bridge_engine.generate() → uses bridge_full.json
# 4. Return identity-locked bridge frame
return bridge_result.frame_path
```

### 5.2 Architecture Documentation

**File:** `ARCHITECTURE.md`  
**Section:** 3B. The Bridge Engine

Added comprehensive 180-line specification covering:
- What is a bridge frame (technical definition)
- When it's needed (decision table)
- Why it's needed (drift problem with diagrams)
- Why it must never be bypassed (4 historical failures documented)
- Technical implementation steps
- Future enhancement (multi-frame)
- Degradation ladder (Tier 1-4)

### 5.3 MVP Plan Revision

Reorganized priorities around proving bridge frame works first:
- **Phase 1:** Prove core value (bridge + identity measurement)
- **Phase 2:** Make it usable (5-shot, LLM parsing, CLI)
- **Phase 3:** Make it watchable (audio)

---

## 6. Detailed Plan to MVP

### PHASE 1: Prove the Core Value ← START HERE

**Goal:** Measurable proof that Shot A → Bridge → Shot B maintains identity.

| Step | Task | Deliverable | Effort |
|------|------|-------------|--------|
| **1.1** | Verify bridge model dependencies on RunPod | Checklist of available models | 1-2 hrs |
| **1.2** | Test `bridge_full.json` standalone in ComfyUI | Confirm workflow executes | 2-4 hrs |
| **1.3** | Wire `identity_checker.py` with real ArcFace | Actual similarity scores | 4-6 hrs |
| **1.4** | Populate `ConsistencyDict` with test character | Alice's Bible refs loaded | 2-3 hrs |
| **1.5** | End-to-end 2-shot test with measurement | **PROOF OF CORE VALUE** | 4-6 hrs |

**Exit Criteria:**
```
Shot 1 (Alice at table):      ArcFace vs Bible = 0.92
Bridge Frame:                 ArcFace vs Bible = 0.95 ← re-anchored!
Shot 2 (Alice walks to door): ArcFace vs Bible = 0.91 ← maintained!
```

**Models Required on RunPod:**
- `sd_xl_base_1.0.safetensors` (SDXL base)
- `controlnet-openpose-sdxl-1.0.safetensors`
- `controlnet-depth-sdxl-1.0.safetensors`
- `ip-adapter-plus-face_sdxl_vit-h.safetensors`
- `clip_vision_h.safetensors`

### PHASE 2: Make It Usable

**Goal:** User can write a script and get a 5-shot film with consistent character.

| Step | Task | Deliverable | Effort |
|------|------|-------------|--------|
| **2.1** | 5-shot test with identity tracking | Prove identity across 5 cuts | 4-6 hrs |
| **2.2** | Create `llm_client.py` abstraction | Claude/GPT/Gemini wrapper | 4-6 hrs |
| **2.3** | Script → Scene Graph via LLM | Automated script parsing | 6-8 hrs |
| **2.4** | Basic CLI runner | `python main.py --script alice.txt` | 4-6 hrs |
| **2.5** | Pass 2 refinement wiring | Flicker reduction | 4-6 hrs |

**Exit Criteria:**
- Plain text script in → 5-shot video out
- Identity similarity > 0.85 across all shots

### PHASE 3: Make It Watchable

**Goal:** Films have audio (dialogue, ambience, music).

| Step | Task | Deliverable | Effort |
|------|------|-------------|--------|
| **3.1** | Wire TTS Engine (ElevenLabs) | Dialogue audio | 4-6 hrs |
| **3.2** | Wire Lip Sync (Musetalk) | Moving lips | 6-8 hrs |
| **3.3** | Wire Ambience (AudioLDM-2) | Background sounds | 4-6 hrs |
| **3.4** | Audio mixing + ducking | Music lowers for dialogue | 2-4 hrs |
| **3.5** | Final stitcher with audio | Complete MP4 | 4-6 hrs |

**Exit Criteria:**
- 5-shot film with consistent character
- Character speaks with lip sync
- Background ambience
- Music ducks during dialogue

---

## 7. Source of Truth Documents

| Document | Purpose | Priority |
|----------|---------|----------|
| `ARCHITECTURE_SUMMARY.md` | Working dev summary — **wins for implementation** | Read first |
| `ARCHITECTURE.md` | Full strategic vision, **Bridge Frame spec in Section 3B** | Read Section 3B |
| `LESSONS_LEARNED.md` | 36 interface gotchas and debugging history | Reference when stuck |
| `LLM_CODING_GUIDELINES.md` | Coding rules for AI assistants | Follow always |
| This document | Current state and next steps | Handoff context |

---

## 8. Code Patterns & Gotchas

### Config Access (Lesson 29)
```python
# WRONG
config.comfyui_host
config.workflows_dir

# CORRECT
config.comfyui.host
config.paths.workflows_dir
```

### Workflow Loading (Lesson 33)
```python
# WRONG
loader.load("path/to/workflow.json")
loader.inject_params(workflow, params)

# CORRECT
loader.load("workflow_name")  # Just name, no path
loader.load_and_inject("workflow_name", params)
```

### Seed Values (Lesson 35)
```python
# WRONG - ComfyUI rejects -1
seed = -1

# CORRECT
seed = random.randint(0, 2**32 - 1)
```

### BridgeSpec Creation (Lesson 31)
```python
# WRONG - passing dict
bridge_engine.generate({"source": path, "prompt": text})

# CORRECT - use factory method
spec = BridgeSpec.from_shots(
    shot_a_last_frame=path,
    shot_b_prompt=text,
    shot_b_characters=character_refs,
)
bridge_engine.generate(spec)
```

### Environment Variables (Lesson 30)
```bash
# WRONG
export COMFYUI_HOST="wss://..."

# CORRECT (double underscore for nested config)
export CONTINUUM_COMFYUI__HOST="wss://..."
```

---

## 9. Verification Commands

### Run Passing Tests
```bash
cd /tmp && python3 -m pytest /mnt/project/test_workflow_contracts.py \
    /mnt/project/test_workflow_stress.py \
    /mnt/project/test_model_loader.py -v
```

### Check Syntax
```bash
cd /tmp && python3 -c "
import ast
with open('/mnt/project/pass1_generator.py', 'r') as f:
    ast.parse(f.read())
print('Syntax OK')
"
```

### Verify Model Tier System
```bash
cd /tmp && python3 -c "
import sys; sys.path.insert(0, '/mnt/project')
from model_loader import get_model_config, ModelTier
config = get_model_config('wan21', 't2v', ModelTier.BEAST)
print(f'UNET: {config.unet}')
print(f'VRAM: {config.vram_required_gb}GB')
"
```

### Check Bridge Workflow Has Required Nodes
```bash
grep -E "controlnet|ipadapter|IPAdapter" /mnt/project/bridge_full.json
```

---

## 10. For the Next Claude Session

### Start With
1. Read `ARCHITECTURE_SUMMARY.md` (implementation truth)
2. Read Section 3B of `ARCHITECTURE.md` (Bridge Frame spec) — **MANDATORY**
3. Read this handoff document
4. Check `LESSONS_LEARNED.md` for interface gotchas

### Immediate Priority
**Phase 1, Step 1.1:** Verify bridge model dependencies on RunPod

Ask the human:
> "Do you have these models on your RunPod instance?
> - sd_xl_base_1.0.safetensors
> - controlnet-openpose-sdxl-1.0.safetensors
> - controlnet-depth-sdxl-1.0.safetensors
> - ip-adapter-plus-face_sdxl_vit-h.safetensors
> - clip_vision_h.safetensors
> 
> If not, I'll create a setup script."

### What NOT To Do

❌ **DO NOT bypass the Bridge Engine** — Read Section 3B.4 of ARCHITECTURE.md  
❌ **DO NOT use `bridge_basic.json`** — It's broken (no ControlNet, no IP-Adapter)  
❌ **DO NOT stub identity_checker** — We need real ArcFace scores to prove bridge works  
❌ **DO NOT move to Phase 2** until Phase 1 exit criteria are met  
❌ **DO NOT optimize for speed** over correctness — Fast garbage is still garbage

### Key Questions to Verify Understanding

Before writing any code, the next Claude should be able to answer:

1. Why does raw frame → Wan I2V cause identity drift?
2. Why is SDXL used for bridge frames instead of Wan?
3. When is a bridge frame needed? (List 5 scenarios)
4. What's the difference between `bridge_full.json` and `bridge_basic.json`?
5. What are the Phase 1 exit criteria?

If unsure about any answer, re-read ARCHITECTURE.md Section 3B.

---

## Appendix: Key File Locations

| Purpose | File | Key Lines/Methods |
|---------|------|-------------------|
| Bridge frame generation | `pass1_generator.py` | `_generate_bridge_frame()` (671-808) |
| Bridge engine | `bridge_engine.py` | `ComfyUIBridgeEngine.generate()` |
| Correct bridge workflow | `bridge_full.json` | Entire file |
| Identity checker (stubbed) | `identity_checker.py` | `BaseIdentityChecker.compare()` |
| Character refs | `consistency_dict.py` | `ConsistencyDict.get_character()` |
| Workflow loading | `workflow_loader.py` | `load_and_inject()` |
| Config | `config.py` | `ContinuumConfig` class |

---

*End of Handoff Document*