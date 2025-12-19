# Continuum Engine - Architecture Summary (Dev Facing)

**Version:** 2025.12.4  
**Status:** Working Summary for Implementation  
**Project Codename:** "Pixar-on-Demand"

This document is the **short, working summary** of the Continuum Studios Engine.  
The full spec lives in `ARCHITECTURE.md`. If anything here disagrees with that file, **this summary wins for implementation**.

### Related Documentation
- `docs/MODEL_CONFIGURATION.md` - How to switch model tiers (dev/standard/beast)
- `docs/LESSONS_LEARNED.md` - Debugging history and gotchas
- `docs/LLM_CODING_GUIDELINES.md` - Coding rules for AI assistants

---

## 1. Goal of the System

We are building a **neuro-symbolic AI filmmaking engine** (not just a video generator) that:

- **Directs** a fully immersive world over time (2-5 min MVP, 10-30 min Target).
- Enforces **Identity Lock** (Alice is always Alice) via Ref Image Conditioning (instant) + LoRA (enhanced) + ArcFace (verification).
- Enforces **World Consistency** (The kitchen stays the same) via Visual RAG + I2V Ref Image conditioning.
- Enforces **Narrative Flow** using "Smart Cuts" and "Bridge Frames" to prevent drift.
- Delivers **Full Sensory Immersion** (Dialogue, Ambience, Foley, Score).

### Hardware Strategy (Brain vs Muscle)

| Layer | Hardware | Responsibilities |
|-------|----------|------------------|
| **Brain (Local)** | MacBook Air M4 | Python orchestration, job dispatch, UI |
| **Brain (Cloud)** | LLM APIs | Director Agent intelligence (script parsing, planning, reasoning) |
| **Muscle (Cloud)** | RunPod/Lambda GPUs | ComfyUI, Video Inference, LoRA Training, QA Models |

### Director Agent (LLM Configuration)

The Director Agent is the "intelligence" of the system. It runs as **cloud LLM API calls** dispatched from the Mac â€” the Mac runs Python orchestration code, NOT local model inference.

| Mode | Provider | Model | Cost | Use Case |
|------|----------|-------|------|----------|
| **Primary** | Anthropic | Claude Opus 4.5 / Claude Sonnet 4.5 | ~$0.003/1K tokens | Complex reasoning, script parsing |
| **Primary** | OpenAI | GPT-5.2 / GPT-5.2-mini | ~$0.002/1K tokens | Fast structured output |
| **Primary** | Google | Gemini 3 Pro / Flash | ~$0.001/1K tokens | Long context, multimodal |
| **Fallback** | Local (Ollama) | Llama 3.1 8B | Free | Offline/privacy mode only |

**Cost Impact:** ~$0.02-0.10 per 5-minute film (negligible vs. GPU rendering at $5-50/film)

**Director Agent Responsibilities:**
- Parse scripts â†’ Scene Graph JSON
- Maintain Consistency Dictionary (entity â†’ asset mappings)
- Validate continuity ("Does Alice still have the sword?")
- Generate shot compositions and camera decisions
- Enrich prompts with cinematic detail
- Orchestrate render jobs and audit results

### Two-Lane Rendering Model

| Lane | Tech Stack | Cost | Use Case |
|------|------------|------|----------|
| **Standard Lane** | Pure OSS (Wan/Hunyuan/Mochi) | ~$0.50/min | Iteration, testing, budget projects |
| **Pro Lane** | Premium APIs (Runway/Veo) + OSS repair | ~$6-12/min | Customer demos, high-fidelity output |

The architecture supports hot-swapping between lanes via `BaseRenderer` abstraction.

---

## 2. Core Principles (The "Continuum" Strategy)

### Principle 1: Smart-Cut > Infinite Streaming

We do **not** rely on one model to generate 5 minutes continuously.  
We use a **"Max-Duration + Bridge Frame"** strategy:
- Render stable chunks (~12 seconds max)
- Extract the **last frame** from each chunk (captures pose, expression)
- Generate a **Bridge Frame** that re-anchors identity while preserving pose
- Start the next chunk using **Wan I2V** with the Bridge Frame as `init_image`

---

#### ⚠️ BRIDGE FRAME: CRITICAL COMPONENT — DO NOT BYPASS ⚠️

The Bridge Engine is the **CORE VALUE PROPOSITION** of Continuum. It separates us from "random clip generators." Without it, we have no product.

**What is a Bridge Frame?**
A synthetically generated image that serves as the "perfect first frame" for any new video generation. Created BEFORE the video model runs, injected as `init_image`.

- **Input:** Last frame of previous segment (pose, expression, scene state)
- **Process:** ControlNet extracts pose + IP-Adapter re-injects canonical identity
- **Output:** Single frame with BOTH pose continuity AND identity lock
- **Workflow:** `bridge_full.json` (SDXL with ControlNet + IP-Adapter)

**Why SDXL (not Wan)?**
1. SDXL has mature ControlNet + IP-Adapter support
2. Wan is a VIDEO model without IP-Adapter for single images
3. One frame of SDXL "style" is immediately overwritten by Wan in frame 2+
4. The identity lock survives; the style doesn't matter

---

#### When is Bridge Frame Needed?

| Scenario | Bridge Needed? | Why |
|----------|----------------|-----|
| Shot A → Shot B (camera change) | ✅ YES | New generation |
| Chunk 1 → Chunk 2 (same shot, 12s max) | ✅ YES | Generation restart |
| Repair/patch a bad frame | ✅ YES | New generation |
| Focus change (Person A → Person B) | ✅ YES | Different subject |
| Re-roll after audit failure | ✅ YES | New generation |
| Continue from checkpoint | ✅ YES | New generation |
| Within a single 12s chunk | ❌ NO | Continuous generation |
| Frame interpolation (RIFE) | ❌ NO | Not generation |
| Pass 2 refinement (vid2vid) | ❌ NO | Existing video |

**Rule:** If calling the video model to generate NEW frames → need Bridge Frame (unless first shot of film).

---

#### Why Bridge Frame is Needed (The Drift Problem)

Video models have NO MEMORY between calls. Without Bridge, identity drifts:

```
WITHOUT BRIDGE (drift accumulates):
  Shot 1  →  Shot 2  →  Shot 3  →  Shot 4  →  Shot 5
  100%       98%        94%        88%        80%  ← unrecognizable

WITH BRIDGE (re-anchored every cut):
  Shot 1 → BRIDGE → Shot 2 → BRIDGE → Shot 3 → BRIDGE → Shot 4
  100%     ↑100%    100%     ↑100%    100%     ↑100%    100%
           │                 │                 │
     Re-anchor from    Re-anchor from   Re-anchor from
     Bible refs        Bible refs       Bible refs
```

---

#### Why Bridge Frame Must NEVER Be Bypassed

Historical bypass attempts (ALL FAILED):

| Bypass Attempt | Reasoning | Why It Fails |
|----------------|-----------|--------------|
| "Raw frame is good enough" | Last frame has right pose | Wan continues VIDEO not IDENTITY; drift compounds |
| "LoRA handles identity" | Character LoRAs maintain identity | LoRA biases but doesn't LOCK; IP-Adapter provides hard anchor |
| "Bridge adds latency" | Skip for faster iteration | Iterating on BROKEN pipeline; fast garbage is garbage |
| "Same model family better" | SDXL style mismatch | Bridge is ONE frame; Wan overwrites style in frame 2+ |

**THE RULE:** If tempted to bypass Bridge Engine, you're solving the wrong problem. Fix whatever makes you want to bypass it.

---

#### Technical Implementation (MVP)

```
Step 1: CAPTURE     → FFmpeg extract last frame → PNG
Step 2: POSE        → ControlNet preprocessor → pose keypoints  
Step 3: DEPTH       → Depth Anything (optional) → depth map
Step 4: GENERATE    → bridge_full.json (SDXL + ControlNet + IP-Adapter) → bridge frame
Step 5: INJECT      → pass1_img2vid.json (Wan I2V with init_image) → video
```

**Workflow Files:**
| Workflow | Contents | Status |
|----------|----------|--------|
| `bridge_full.json` | ControlNet Pose + Depth + IP-Adapter | ✅ RECOMMENDED |
| `bridge_pose_only.json` | ControlNet Pose + IP-Adapter | 🟡 Fallback |
| `bridge_ipadapter.json` | IP-Adapter only | 🟡 Minimal fallback |
| `bridge_basic.json` | SDXL img2img only | ❌ BROKEN - Do not use |

---

#### Degradation Ladder

| Tier | Components | Workflow | Result |
|------|------------|----------|--------|
| 1 (Best) | ControlNet Pose + Depth + IP-Adapter + LoRA | `bridge_full.json` | Perfect pose + identity |
| 2 (Good) | ControlNet Pose + IP-Adapter + LoRA | `bridge_pose_only.json` | Pose + identity, no depth |
| 3 (Acceptable) | IP-Adapter + LoRA only | `bridge_ipadapter.json` | Identity locked, pose may shift |
| 4 (Emergency) | Raw frame → Wan I2V | `pass1_img2vid.json` | ⚠️ DRIFT WILL OCCUR |

**Tier 4 Rule:** NEVER fall back silently. Always log warning: "Bridge unavailable - identity drift expected"

---

#### Future Enhancement: Multi-Frame Bridge Sequence

**Status:** NOT YET IMPLEMENTED (Phase 2+)

**Problem:** Single frame can cause "motion freeze" (character frozen mid-stride for 0.5s)

**Solution:** Generate 3-5 frame sequence via RIFE interpolation between:
- Last frame of Shot A (source pose)
- Bridge Frame (identity-locked target)

**Trade-off:** ~3x GPU cost per cut, but smoother motion handoff

**Decision:** Test single-frame MVP first. Upgrade only if users report "motion freeze" issues.

---

### Principle 2: Trust but Verify (Automated QA)
Every generated chunk is audited **before** the user sees it:
- **Identity Check:** ArcFace similarity > 0.70
- **Physics Check:** YOLO + ByteTrack for object permanence
- **Flicker Check:** RAFT optical flow analysis
- If FAIL -> Auto re-roll (max 3 attempts)
- If MAX_FAIL -> Surface to user with options

### Principle 3: ComfyUI-First & Modular
- Complex diffusion logic lives in **ComfyUI workflows** (JSON files)
- Python acts as the **remote control**: loading workflows, injecting parameters, dispatching jobs
- No custom CUDA kernels -- we orchestrate, not build models

### Principle 4: Two-Pass Rendering
| Pass | Purpose | Tech |
|------|---------|------|
| **Pass 1 (Structure)** | Composition, motion, identity | Base Model + I2V Conditioning + LoRA (optional) + ControlNet (future) |
| **Pass 2 (Refinement)** | Flicker reduction, detail enhancement | Vid2Vid / FreeLong++ |

### Principle 5: State & Memory (Two Distinct Systems)

| System | Type | What It Tracks | Example |
|--------|------|----------------|---------|
| **Consistency Dictionary** | Static (queried) | Entity -> Asset mappings | `Alice -> identity_refs[], face_refs[], lora_path?` |
| **World State Tracker** | Dynamic (mutated) | Object states & positions | `Mug: {state: "on_floor", pos: [2,0,0]}` |

The Dictionary tells us *what* things look like.  
The World State tells us *where* things are and *what happened* to them.

### Principle 6: Progressive Identity Lock (Zero-Wait UX)

Identity consistency uses a **two-tier system** that lets users start immediately:

| Tier | Technology | Activation | Quality | UX |
|------|------------|------------|---------|-----|
| **Tier 1 (Instant)** | I2V Ref Conditioning | User uploads 3-5 refs -> ready in seconds | ~80% | "Draft Mode" |
| **Tier 2 (Enhanced)** | Auto-LoRA | Background training (30-45 min) | ~95% | "Enhanced Mode Ready" notification |

**Why this matters:**
- No "training wall" blocking creators from starting
- Progressive enhancement feels like magic
- Always have a working fallback

**Degradation Ladder:**
```
LoRA available       -> Use LoRA (95% quality)
LoRA missing         -> Fall back to I2V Ref Conditioning (80% quality)  
Ref image missing    -> Prompt-only T2V generation (inconsistent)
```

**Workflow Node Sequence (Wan 2.1 I2V):**
```
LoadImage -> CLIPVisionEncode -> WanImageToVideo -> KSampler -> VAEDecode -> SaveVideo
                                     
UNETLoader -> ModelSamplingSD3 -------+
```

*Note: LoRA injection adds LoraLoader between UNETLoader and ModelSamplingSD3 when available.*

---

## 3. High-Level Modules

### Folder Structure

```
continuum/
|-- src/
|   |-- core/                    # Shared infrastructure
|   |   |-- job_state.py         # Enums: Pending, Auditing, Failed, Approved
|   |   |-- checkpointing.py     # Save/resume job state
|   |   |-- error_recovery.py    # Retry logic, degradation ladder
|   |   |-- config.py            # Environment, paths, secrets
|   |   +-- model_loader.py      # Model tier system (dev/standard/beast)
|   |
|   |-- director/                # The Brain (LLM-powered)
|   |   |-- llm_client.py        # Cloud LLM interface (Claude/GPT/Gemini)
|   |   |-- scene_graph.py       # Script -> Scenes -> Shots -> Chunks
|   |   |-- consistency_dict.py  # Entity -> Asset mappings (static)
|   |   |-- world_state.py       # Object states & positions (dynamic)
|   |   |-- pacer.py             # Smart-cut timing, Max_Duration logic
|   |   +-- layout_generator.py  # Bounding boxes for ControlNet
|   |
|   |-- memory/                  # Visual RAG + Asset Storage
|   |   |-- visual_rag.py        # Pinecone/vector DB interface
|   |   |-- asset_store.py       # S3/R2 file retrieval
|   |   +-- cache.py             # Local fallback when cloud unavailable
|   |
|   |-- renderers/               # Pluggable generation backends
|   |   |-- base.py              # BaseRenderer ABC (hot-swap interface)
|   |   |-- wan_renderer.py      # OSS via ComfyUI (Day 1)
|   |   |-- runway_renderer.py   # Pro Lane API (Day 60+)
|   |   +-- veo_renderer.py      # Pro Lane API (Day 60+)
|   |
|   |-- studio/                  # Video generation pipeline
|   |   |-- bridge_engine.py     # Generate transition frames
|   |   |-- pass1_generator.py   # Structural video generation
|   |   |-- pass2_refiner.py     # Vid2Vid / FreeLong++ refinement
|   |   +-- rife_interpolator.py # 12fps -> 24fps upscaling
|   |
|   |-- audit/                   # Quality control
|   |   |-- identity_checker.py  # ArcFace face similarity
|   |   |-- physics_checker.py   # YOLO + RAFT + ByteTrack
|   |   +-- reviewer.py          # Orchestrates checks -> PASS/FAIL
|   |
|   |-- sonic/                   # Audio & atmosphere
|   |   |-- tts_engine.py        # ElevenLabs / OpenAI TTS
|   |   |-- lip_sync.py          # Musetalk / Wav2Lip
|   |   |-- ambience.py          # AudioLDM-2 bed tracks
|   |   |-- foley.py             # Event-triggered SFX
|   |   +-- mixer.py             # Combine all audio layers
|   |
|   |-- comfy_client/            # Cloud ComfyUI interface
|   |   |-- client.py            # WebSocket connection management
|   |   |-- workflow_loader.py   # Load JSON, inject parameters
|   |   +-- job_queue.py         # Submit, poll, retry logic
|   |
|   |-- post/                    # Post-production
|   |   |-- color_match.py  # Histogram matching to Master Shot
|   |   |-- audio_ducker.py      # Lower music during dialogue
|   |   |-- stitcher.py          # FFmpeg final assembly
|   |   |-- ffmpeg_wrapper.py          
|   
+-- main.py                  # Entry point / orchestrator
|
|-- workflows/                   # ComfyUI JSON workflows
|   |-- models.json              # Model registry (tier configs)
|   |-- pass1_structural.json    # T2V base (no init_frame)
|   |-- pass1_structural_lora.json  # T2V + LoRA
|   |-- pass1_img2vid.json       # I2V base (uses Bridge Frame as init_image)
|   |-- pass1_img2vid_lora.json  # I2V + LoRA
|   |-- bridge_basic.json        # âŒ BROKEN: SDXL img2img only (no pose/identity)
|   |-- bridge_ipadapter.json    # Partial: IP-Adapter identity only
|   |-- bridge_pose_only.json    # Partial: ControlNet pose only  
|   |-- bridge_full.json         # âœ… CORRECT: ControlNet pose + IP-Adapter identity
|   |-- refine_vid2vid_simple.json   # Frame-by-frame refinement
|   |-- refine_vid2vid_temporal.json # Batched temporal refinement
|   +-- musetalk_lipsync.json    # Lip sync via Musetalk
|
|-- tests/                       # Unit & integration tests
|   |-- test_director.py
|   |-- test_bridge.py
|   |-- test_audit.py
|   +-- ...
|
|-- config/
|   |-- default.yaml             # Default configuration
|   +-- secrets.yaml.example     # Template for API keys
|
+-- README.md
```

### Module Responsibilities

| Module | Role | Key Classes/Functions |
|--------|------|----------------------|
| `core/` | Shared infrastructure | `JobState`, `Checkpoint`, `Config` |
| `director/` | The Brain â€” LLM-powered planning & orchestration | `SceneGraph`, `ConsistencyDict`, `WorldState`, `Pacer`, `LLMClient` |
| `memory/` | Asset storage & retrieval | `VisualRAG`, `AssetStore`, `get_asset(entity_id)` |
| `renderers/` | Pluggable video generation | `BaseRenderer`, `WanRenderer`, `RunwayRenderer` |
| `studio/` | Video pipeline stages | `BridgeEngine`, `Pass1Generator`, `Pass2Refiner`, `RIFE` |
| `audit/` | Quality control | `IdentityChecker`, `PhysicsChecker`, `Reviewer` |
| `sonic/` | Audio generation & mixing | `TTSEngine`, `LipSync`, `Ambience`, `Mixer` |
| `comfy_client/` | Cloud ComfyUI interface | `ComfyClient`, `WorkflowLoader`, `JobQueue` |
| `post/` | Final assembly | `ColorNormalizer`, `AudioDucker`, `Stitcher` |

---

## 4. Data Flow Overview

```
SCRIPT (PDF/Text)
    |
    v
+-----------------------------------------------------------+
|  DIRECTOR_AGENT (MacBook M4)                              |
|  |-- Parse Script -> SCENE_GRAPH                          |
|  |-- Build CONSISTENCY_DICT (entity -> assets)            |
|  |-- Initialize WORLD_STATE (object positions)            |
|  |-- Generate LAYOUTS (bounding boxes)                    |
|  +-- Generate SONIC_MANIFEST (audio plan)                 |
+-----------------------------------------------------------+
    |
    v
+-----------------------------------------------------------+
|  JOB_DISPATCHER (Parallel Execution)                      |
|                                                           |
|  +----------------------+   +----------------------+      |
|  |  TRACK A: VISUAL     |   |  TRACK B: SONIC      |      |
|  |  (Cloud GPU)         |   |  (Cloud/API)         |      |
|  |                      |   |                      |      |
|  |  1. BRIDGE_ENGINE    |   |  1. TTS (Dialogue)   |      |
|  |     +-- Init frame   |   |  2. Ambience gen     |      |
|  |                      |   |  3. Foley triggers   |      |
|  |  2. PASS 1           |   |                      |      |
|  |     +-- Structure    |   +----------------------+      |
|  |                      |            |                    |
|  |  3. AUDIT            |            |                    |
|  |     +-- ArcFace ID   |            |                    |
|  |     +-- YOLO Physics |            |                    |
|  |     |                |            |                    |
|  |     +-- IF PASS:     |            |                    |
|  |     |   CHECKPOINT   |            |                    |
|  |     +-- IF FAIL:     |            |                    |
|  |     |   Re-roll 3x   |            |                    |
|  |     +-- IF MAX_FAIL: |            |                    |
|  |         Surface      |            |                    |
|  |                      |            |                    |
|  |  4. PASS 2           |            |                    |
|  |     +-- Refinement   |            |                    |
|  |                      |            |                    |
|  |  5. LIP_SYNC         |            |                    |
|  |     +-- Musetalk     |            |                    |
|  |                      |            |                    |
|  |  6. RIFE             |            |                    |
|  |     +-- 12->24fps    |            |                    |
|  +----------------------+            |                    |
|            |                         |                    |
|            +-----------+-------------+                    |
|                        |                                  |
|                 WAIT FOR BOTH                             |
+-----------------------------------------------------------+
    |
    v
+-----------------------------------------------------------+
|  POST_PRODUCTION                                          |
|  |-- Auto-Color Match (Histogram -> Master Shot)          |
|  |-- Audio Ducking (-12dB during dialogue)                |
|  +-- Final Stitch (FFmpeg)                                |
+-----------------------------------------------------------+
    |
    v
FINAL_CINEMATIC_VIDEO
```

---

## 5. Implementation Priority

Ordered by **what unblocks the next thing**, not by architectural importance.

| Priority | Module | Deliverable | Why This Order |
|----------|--------|-------------|----------------|
| **P0** | `comfy_client/` | WebSocket connection to cloud ComfyUI | Can't do anything without cloud |
| **P1** | `renderers/wan_renderer.py` | Single-shot generation (Pass 1 only) | Prove we can get frames out |
| **P2** | `director/scene_graph.py` | Script -> Shots parser | Know what to generate |
| **P3a** | `workflows/` + I2V integration | I2V workflow + ref image injection | **Instant identity (Tier 1)** |
| **P3b** | `memory/` + LoRA workflow | LoRA injection when available | Enhanced identity (Tier 2) |
| **P4** | `studio/bridge_engine.py` | Bridge Frame generation (drift correction) | **THIS IS THE CORE VALUE** |
| **P5** | `audit/identity_checker.py` | ArcFace similarity check | Verify bridge maintains identity |
| **P6** | `sonic/tts_engine.py` + `lip_sync.py` | Dialogue with moving lips | Audio for demo |
| **P7** | `studio/pass2_refiner.py` + `rife_interpolator.py` | Polish & frame rate | Quality pass |
| **P8** | `director/world_state.py` | Dynamic prop tracking | Phase 2+ scope |

### Key Milestone (Proof of Core Value)
**Can you generate Shot A, then Shot B, and have them look like the same character in the same world?**

This requires: P0 -> P1 -> P2 -> P3a -> P4 -> P5. Everything else is optimization.

**How P4 Works (Bridge Frame for Drift Correction):**

*Correct Flow (Production):*
```
Shot A video â†’ Extract last frame â†’ bridge_full.json â†’ Bridge Frame â†’ Wan I2V â†’ Shot B
                     â”‚                     â”‚
                     â”‚                     â”œâ”€ ControlNet: extracts POSE
                     â”‚                     â””â”€ IP-Adapter: re-anchors IDENTITY
                     â”‚
                     â””â”€ Captures expression, body position
```

*Current MVP Flow (Temporary):*
```
Shot A video â†’ Extract last frame â†’ (skip bridge) â†’ Wan I2V â†’ Shot B
                                          â”‚
                                          â””â”€ âš ï¸ Drift will accumulate
```

The MVP shortcut works for 2-3 shot tests. Production requires proper bridge integration.

---

## 6. Key Interfaces (Contracts)

### 6.1 BaseRenderer (Pluggable Generation)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

@dataclass
class CharacterRef:
    entity_id: str
    identity_refs: List[Path]        # Tier 1: Ref images for I2V conditioning (required)
    face_refs: List[Path]            # For ArcFace verification
    lora_path: Optional[Path] = None # Tier 2: Enhanced (if trained)

@dataclass 
class LocationRef:
    entity_id: str
    ref_images: List[Path]

@dataclass
class JobSpec:
    prompt: str
    duration_sec: float
    init_frame: Optional[Path]
    character_refs: List[CharacterRef]
    location_refs: List[LocationRef]
    layout: Optional[dict]  # Bounding boxes for ControlNet
    seed: Optional[int] = None
    renderer_config: dict = None  # Renderer-specific overrides

@dataclass
class RenderResult:
    video_path: Path
    frame_count: int
    fps: float
    metadata: dict

class BaseRenderer(ABC):
    |-- Abstract base class " allows hot-swapping renderers.|-- 
    
    @abstractmethod
    def generate(self, job: JobSpec) -> RenderResult:
        """Generate video from job specification."""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if renderer backend is available."""
        pass
```

### 6.2 Audit Result

```python
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional

class AuditStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"  # Borderline, flag for review

@dataclass
class AuditFlag:
    check_type: str      # "identity", "physics", "flicker"
    frame_range: tuple   # (start_frame, end_frame)
    severity: float      # 0.0-1.0
    description: str

@dataclass
class AuditResult:
    status: AuditStatus
    flags: List[AuditFlag]
    identity_score: Optional[float]  # ArcFace similarity
    recommendation: str              # "approve", "reroll", "manual_review"
```

### 6.3 Job State (Checkpointing)

```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

class JobStatus(Enum):
    PENDING = "pending"
    GENERATING = "generating"
    AUDITING = "auditing"
    FAILED = "failed"
    APPROVED = "approved"
    REFINING = "refining"
    COMPLETE = "complete"

@dataclass
class JobCheckpoint:
    job_id: str
    shot_id: str
    status: JobStatus
    attempt: int
    rendered_path: Optional[Path]
    audit_result: Optional[AuditResult]
    timestamp: datetime
    
    def save(self, checkpoint_dir: Path):
        """Persist to disk for crash recovery."""
        pass
    
    @classmethod
    def load(cls, job_id: str, checkpoint_dir: Path) -> "JobCheckpoint":
        """Resume from saved state."""
        pass
```

---

## 7. Code Standards

All new code must follow these rules:

### 7.1 Separation of Concerns
- **Logic on Mac** " Director, planning, orchestration
- **Rendering on Cloud** " ComfyUI, inference, heavy compute
- Never mix them in the same function

### 7.2 Type Hinted
Every function must have type hints:
```python
def render_shot(shot: Shot, renderer: BaseRenderer) -> RenderResult:
    ...
```

### 7.3 Pluggable
Core engines use abstract base classes. Director doesn't care if it's `WanRenderer` or `RunwayRenderer`:
```python
def generate_video(job: JobSpec, renderer: BaseRenderer) -> RenderResult:
    return renderer.generate(job)  # Works with any renderer
```

### 7.4 Error-Handled
All cloud calls wrapped in try/except with logging:
```python
try:
    result = comfy_client.submit(job)
except ComfyConnectionError as e:
    logger.error(f"ComfyUI unreachable: {e}")
    checkpoint.save(job)  # Don't lose work
    raise
```

### 7.5 Stateful & Auditable
Every chunk must have a trackable status:
```python
job.status = JobStatus.GENERATING
# ... generation happens ...
job.status = JobStatus.AUDITING
# ... audit happens ...
job.status = JobStatus.APPROVED  # or FAILED
checkpoint.save(job)
```

### 7.6 Testable Locally
Director logic should run without GPU. Mock the renderer for unit tests:
```python
def test_scene_graph_parsing():
    graph = SceneGraph.from_script("test_script.txt")
    assert len(graph.scenes) == 3
    assert graph.scenes[0].shots[0].duration_sec == 12.0
```

### 7.7 Fail Gracefully
Use the degradation ladder:
1. Missing LoRA -> Fall back to I2V Ref Conditioning
2. Missing environment ref -> Use prompt-only generation
3. Audio API failure -> Continue with silent video, flag for retry
4. LLM API failure -> Use cached scene graph if available

---

## 7b. Known MVP Limitations

**These are intentional shortcuts in the current implementation. They must be fixed for production.**

| Limitation | Current MVP | Production Requirement | Impact |
|------------|-------------|------------------------|--------|
| **Bridge Frame** | Raw last frame â†’ I2V (no re-anchoring) | `bridge_full.json` with ControlNet + IP-Adapter | Drift accumulates over 5+ shots |
| **Director Agent** | Manual scene graph JSON | LLM parses script automatically | No script-to-video pipeline |
| **Identity Audit** | Stubbed (always passes) | Real ArcFace similarity check | Drift not caught automatically |
| **Sonic Engine** | Stubbed interfaces | TTS + Lip Sync + Ambience | Silent films only |
| **Pass 2 Refinement** | Partial (workflow exists) | Full vid2vid flicker reduction | Visual quality not polished |
| **World State** | Stubbed data structures | Actual object position tracking | Props may teleport |

**Priority for Production:** Bridge Frame > Identity Audit > Director Agent > Sonic Engine

---

## 8. Configuration

### Environment Variables (secrets.yaml)
```yaml
# LLM API Keys (Director Agent - choose one or more)
ANTHROPIC_API_KEY: "sk-ant-..."     # Claude (recommended for complex reasoning)
OPENAI_API_KEY: "sk-..."            # GPT-4o (fast structured output)
GOOGLE_API_KEY: "..."               # Gemini (long context, multimodal)

# Audio API Keys
ELEVENLABS_API_KEY: "..."           # TTS for dialogue

# Memory/RAG
PINECONE_API_KEY: "..."             # Visual RAG (optional)

# Cloud Infrastructure  
COMFYUI_HOST: "wss://your-runpod-instance:8188"
S3_BUCKET: "continuum-assets"
AWS_ACCESS_KEY_ID: "..."
AWS_SECRET_ACCESS_KEY: "..."

# Model Tiers (managed by models.json + model_loader.py)
# See docs/MODEL_CONFIGURATION.md for tier switching
CONTINUUM_MODEL_TIER: "dev"  # Options: dev, standard, beast
DEFAULT_LORA_DIR: "/models/loras/"

# Director Agent LLM Selection
CONTINUUM_LLM_PROVIDER: "anthropic"  # Options: anthropic, openai, google, ollama
CONTINUUM_LLM_MODEL: "claude-opus-4-5-20251101"  # Model name for selected provider
```

### Runtime Config (default.yaml)
```yaml
generation:
  max_shot_duration_sec: 12
  default_fps: 12
  output_fps: 24
  max_reroll_attempts: 3

audit:
  identity_threshold: 0.70
  flicker_threshold: 0.05
  physics_missing_frames: 3

sonic:
  tts_provider: "elevenlabs"  # or "openai"
  ducking_db: -12

post:
  color_match_enabled: true
  master_shot_index: 0
```

---

## 9. Glossary

| Term | Definition |
|------|------------|
| **Bridge Frame** | Synthetic image generated via ControlNet (pose) + IP-Adapter (identity) that re-anchors character identity while preserving pose/expression from last frame. Prevents drift accumulation. |
| **Consistency Dictionary** | Static mapping of entity IDs to their canonical assets (LoRAs, refs) |
| **World State** | Dynamic tracking of object positions and states (changes over time) |
| **Smart Cut** | Intentional camera change triggered before model drift occurs |
| **Pass 1** | Structural generation â€” composition, motion, identity |
| **Pass 2** | Refinement â€” flicker reduction, detail enhancement |
| **Pacer** | Logic that decides when to cut (Max_Duration or pacing demand) |
| **Standard Lane** | OSS-only rendering path (~$0.50/min) |
| **Pro Lane** | Premium API + OSS repair path (~$6-12/min) |
| **T2V** | Text-to-Video â€” generates video from text prompt only |
| **I2V** | Image-to-Video â€” generates video starting from an init_image (Bridge Frame) |
| **Bible Refs** | Canonical reference images for a character/location stored in Consistency Dictionary |
| **Drift** | Gradual degradation of character identity over multiple generation cycles |

---

## 10. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 2025.12.5 | Dec 2025 | **Bridge Frame comprehensive documentation:** Added detailed specification covering WHAT (technical definition, why SDXL), WHEN (decision table for all scenarios), WHY (drift problem with diagrams), WHY NEVER BYPASS (4 historical attempts documented), IMPLEMENTATION (5-step MVP), DEGRADATION LADDER (Tier 1-4), and FUTURE ENHANCEMENT (multi-frame sequence via RIFE). Bridge Engine is now fully documented as CRITICAL COMPONENT that must never be bypassed. |
| 2025.12.4 | Dec 2025 | **Bridge strategy correction:** Restored proper Bridge Frame concept (ControlNet pose + IP-Adapter identity re-anchoring). Clarified MVP uses raw frame shortcut (causes drift). Documented that `bridge_full.json` is required for production. |
| 2025.12.3 | Dec 2025 | **LLM clarification:** Added Director Agent LLM configuration section. Cloud APIs (Claude/GPT/Gemini) are primary; local Ollama is fallback only. Updated Hardware Strategy table to separate Brain (Local orchestration) from Brain (Cloud LLM). |
| 2025.12.2 | Dec 2025 | **Bridge strategy update:** Shot continuity now uses raw frame â†’ Wan I2V instead of SDXL bridge. Bridge engine reserved for camera transitions (Phase 2). Updated priority table, glossary, workflow annotations. |
| 2025.12.1 | Dec 2025 | Added model tier system (models.json, model_loader.py). Updated workflow list to match implementation. Added related docs links. |
| 2025.12 | Dec 2025 | Initial working summary. Split State/Memory. Added Two-Lane model. Revised priority order. Added code standards. |

---

*This document is the implementation guide. For strategic vision and detailed rationale, see `ARCHITECTURE.md`.*