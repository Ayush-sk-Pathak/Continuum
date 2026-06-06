# Continuum

**The first AI storytelling engine that remembers.**

Continuum generates multi-shot cinematic video where the *same character*, the *same world*, and the *same props* survive across every cut — manga, visual novels, and animated video from one consistent story.

![Status](https://img.shields.io/badge/status-research%20preview-orange)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Style](https://img.shields.io/badge/lane-anime%20%7C%20realistic-blueviolet)
![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)

> ⚠️ **Research preview.** This is an actively evolving prototype, not a packaged product. The orchestrator runs end-to-end in `--dry-run` mode locally; real rendering requires a cloud GPU running ComfyUI (see [Getting Started](#getting-started)).

---

## The Problem

Today's text-to-video models are brilliant for a single 5-second clip and useless for a 5-minute story. They have **no memory**. Cut to a new shot and your protagonist's face changes, the kitchen rearranges itself, and the red mug becomes a blue one.

Three failures break AI filmmaking:

1. **World Consistency** — the set drifts between shots.
2. **Long-Form Continuity** — a character is not "the same person" in minute 1 and minute 5.
3. **Sensory Immersion** — silent, lifeless output with no dialogue or ambience.

## The Approach

Continuum treats video models as **stateless muscle** and wraps them in a **stateful brain**. A neuro-symbolic Director Agent plans the film, a redundant identity stack locks who/what appears, and every single shot is re-anchored before it renders.

Four ideas do the heavy lifting:

| Principle | What it means |
|---|---|
| 🎬 **I2V-First** | Never text-to-video in production. Every shot starts from a generated *image* so identity is locked before motion begins. |
| 🌉 **Bridge Frame** | Video models have no memory, so before each new shot we synthesize a "perfect first frame" (SDXL + ControlNet Pose + IP-Adapter) that re-establishes the character, then feed it to image-to-video. Identity returns to ~100% at *every* cut instead of decaying shot over shot. |
| 🛡️ **Redundant Identity Stack** | Defense in depth: LoRA + IP-Adapter + ControlNet layered together, with ArcFace / CLIP quality gates that auto-reject and re-roll bad frames. |
| 🎞️ **Multi-Pass Rendering** | Pass 1 = structure + audio · Pass 2 = refinement + lip-sync + RIFE interpolation · Pass 3 = color match + audio ducking. |

The result: **Shot 1 (100%) → Shot 5 (still ~100%)** instead of the usual drift to 80% and beyond.

## How It Works

The system splits across **Brain (your Mac), Guide (retrieval), and Muscle (cloud GPU)**:

```
                          ┌──────────────────────────────┐
  Screenplay (text)  ──►  │   DIRECTOR AGENT  (LLM)       │   "The Brain" — runs locally
                          │  script → scenes → shots →    │
                          │  prompts → project.json       │
                          └───────────────┬──────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │                                           │
            ┌───── TRACK A: VISUAL ─────┐              ┌─── TRACK B: SONIC ───┐
            │  Pass 1: Structure        │              │  TTS / Ambience /     │
            │  (Hero Frame → I2V →      │              │  Foley / Score        │
            │   Bridge Frame → I2V …)   │              └───────────┬───────────┘
            │            │              │                          │
            │  Reviewer (ArcFace /      │                          │
            │  CLIP / Physics gates)    │                          │
            │            │              │                          │
            │  Pass 2: Refine +         │                          │
            │  Lip-sync + RIFE          │                          │
            └────────────┬──────────────┘                          │
                         └──────────────────┬───────────────────────┘
                                            │
                              POST: color match + audio ducking
                                            │
                                      FINAL VIDEO
```

- **Brain** (Mac M4 → cloud LLM): parses scripts into a Scene Graph, maintains the Consistency Dictionary ("the bible"), tracks World State, and orchestrates everything. Light local footprint.
- **Guide** (retrieval): Visual RAG over character sheets, location panoramas, and LoRA metadata.
- **Muscle** (RunPod / Lambda GPUs via **ComfyUI**): Wan 2.1 / HunyuanCustom for I2V, SDXL for bridge frames, IP-Adapter / ControlNet / LoRA nodes.

## What Works Today

This is honest, current status — not a wishlist.

| Capability | Status |
|---|---|
| Director Agent (screenplay → `project.json`, multi-provider LLM) | ✅ Working |
| Scene Graph · Consistency Dictionary · World State · Pacer | ✅ Working |
| Hero Frame → I2V (Shot 1) and Bridge Frame → I2V (Shot 2+) | ✅ Validated end-to-end on RunPod |
| Multi-shot stitching with identity preservation | ✅ Validated (6-shot anime demo) |
| Custom character LoRA training (anime "Aria", realistic "Ayush") | ✅ Trained & validated |
| Sonic Engine — TTS + ambience + audio ducking | ✅ Integrated |
| Quality audit gates (ArcFace / CLIP / YOLOv8 physics) | ✅ Working |
| `--dry-run` full pipeline with mock renderers (no GPU needed) | ✅ Working |
| Lip-sync for anime | ⏸️ Deferred |
| One-command 3–5 minute film, fully automated | 🔶 In progress |
| RIFE frame interpolation wired into orchestrator | 🔶 In progress |

**Current focus:** the anime lane (faster, cheaper, strong identity from base models + custom LoRAs). Realistic and manga/webtoon lanes share the same architecture and are on the roadmap.

## Repository Structure

```
continuum/
├── main.py                 # Orchestrator entry point (wires the whole pipeline)
├── src/
│   ├── core/               # Config, job state, checkpointing, error recovery
│   ├── director/           # "The Brain": script_parser, scene_graph,
│   │                       #   consistency_dict, world_state, pacer
│   ├── renderers/          # Video-model adapters (Wan, HunyuanCustom) behind BaseRenderer
│   ├── studio/             # Pass1 generator, Bridge Engine, Pass2 refiner, RIFE
│   ├── audit/              # Reviewer + identity/physics quality gates
│   ├── sonic/              # TTS, lip-sync, ambience, foley, mixer
│   ├── post/               # Color match, audio ducking, stitching, ffmpeg
│   ├── memory/             # Visual RAG, asset store, cache
│   └── comfy_client/       # ComfyUI API client + workflow loader
├── workflows/              # ComfyUI workflow graphs (wan, hunyuan, bridge, shared)
├── projects/               # Example projects (last_guardian, matrix_zero)
├── tests/                  # Pytest suite + runnable demo/validation scripts
└── docs/                   # Architecture, lessons learned, handoffs (build history)
```

Every renderer implements a single contract — `BaseRenderer.render(spec) -> result` — so swapping Wan for HunyuanCustom (or a premium API like Veo/Runway) doesn't touch the rest of the pipeline.

## Getting Started

### Prerequisites

- **Python 3.10+**
- **A ComfyUI GPU endpoint** for real rendering — typically [RunPod](docs/Runpod.md) or Lambda with an A10/A100/H100. *(You can skip this and use `--dry-run` to exercise the orchestrator with mock renderers.)*
- **API keys** for whichever services you use (LLM for the Director Agent, ElevenLabs for TTS).

### Install

```bash
git clone https://github.com/Ayush-sk-Pathak/Continuum.git
cd Continuum

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Core local (Brain-side) dependencies
pip install \
  pydantic pydantic-settings python-dotenv \
  aiohttp requests numpy scipy \
  opencv-python pillow \
  torch torchvision ultralytics insightface \
  openai elevenlabs
```

> There is no `requirements.txt` checked in yet. The heavy generative models (Wan, SDXL) run **remotely** inside ComfyUI on the GPU host — your local machine only runs the Brain, audit, and post-production steps.

### Configure

Configuration is environment-driven (Pydantic settings, prefix `CONTINUUM_`). Create a `.env` file (already git-ignored):

```bash
# LLM for the Director Agent (pick one)
CONTINUUM_OPENAI_API_KEY=sk-...
CONTINUUM_ANTHROPIC_API_KEY=sk-ant-...

# Voice
CONTINUUM_ELEVENLABS_API_KEY=...

# Cloud GPU (ComfyUI over websocket)
CONTINUUM_COMFYUI__HOST=ws://your-runpod-instance:8188

# Which video model / tier to use
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=wan        # wan | hunyuan_custom
CONTINUUM_VIDEO_MODEL__MODEL_TIER=standard     # dev | standard | beast
```

### Try it (no GPU required)

```bash
# Run the full orchestrator with mock renderers
python main.py --project projects/last_guardian/project.json --dry-run
```

## Usage

### Screenplay → project (Director Agent)

```python
from src.director import DirectorAgent, DirectorConfig, LLMProvider, save_project

config = DirectorConfig.for_anime()
config.provider = LLMProvider.OPENAI
config.model = "gpt-4o-mini"

director = DirectorAgent(config=config)
project = await director.parse_script(
    script_text="FADE IN: ...",
    project_id="my_film",
    title="My Film",
)
save_project(project, "projects/my_film/project.json")
```

A ~1,400-character screenplay parses into a full project (scenes, shots, dialogue, prompts) in ~30s for well under $0.10 with `gpt-4o-mini`.

### Render a project

```bash
# Full pipeline (requires a configured ComfyUI GPU endpoint)
python main.py --project projects/my_film/project.json

# Render one scene or shot
python main.py --project projects/my_film/project.json --scene scene_01
python main.py --project projects/my_film/project.json --shot  shot_03

# Useful flags
python main.py -p projects/my_film/project.json \
  --quality high \      # render quality preset
  --no-audio  \         # skip the Sonic Engine
  --no-pass2  \         # skip refinement pass
  --dry-run             # mock everything (local)
```

The pipeline checkpoints after every chunk and resumes from the last good state on restart (`--no-resume` to start fresh).

### Custom characters (LoRA)

For original characters, train a LoRA from reference images and register it in the project bible. The most recent training run (anime character "Aria", Wan 2.1 I2V 14B) is documented in [docs/Handoffs/Handoff28_Aria_LoRA_Training.md](docs/Handoffs/Handoff28_Aria_LoRA_Training.md), including the full `musubi-tuner` command. Well-known characters (e.g. Goku, Naruto) work without a LoRA for quick testing.

## Tech Stack

- **Orchestration / Brain:** Python, Pydantic, asyncio
- **Director Agent:** OpenAI / Anthropic / (Ollama planned)
- **Video generation:** Wan 2.1 I2V, HunyuanCustom (evaluating) via ComfyUI
- **Identity:** SDXL + IP-Adapter + ControlNet + custom LoRAs (musubi-tuner / Kohya)
- **Audit:** ArcFace (realistic), CLIP (anime), YOLOv8 + ByteTrack (object permanence), RAFT (flicker)
- **Audio:** ElevenLabs / OpenAI TTS, AudioLDM-2 ambience
- **Post:** RIFE interpolation, FFmpeg, histogram color match
- **Infra:** RunPod / Lambda GPUs, Pinecone (Visual RAG), S3-compatible asset storage

## Roadmap

- **Phase 1A — Anime video** *(current)* — one-command 3–5 min anime short with synced dialogue and immersive audio.
- **Phase 1B — Manga / visual novel** — same Director + consistency core, image-only renderers.
- **Phase 2 — Webtoon platform** + realistic-video lane.
- **Phase 3 — Long-form** (10–30 min) and a creator-facing UX ("write → approve → walk away → get notified").

See [docs/architecture_for_claude_code.md](docs/architecture_for_claude_code.md) for the full roadmap and cost model.

## Documentation

| Doc | What's in it |
|---|---|
| [docs/architecture_for_claude_code.md](docs/architecture_for_claude_code.md) | Compact architecture reference (start here) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system architecture |
| [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) | Hard-won knowledge — what not to repeat |
| [docs/Handoffs/](docs/Handoffs/) | Chronological build log (28 handoffs and counting) |

## License

All rights reserved. This repository is public for transparency and showcase purposes; it is **not** licensed for reuse, redistribution, or commercial use without permission. If you'd like to use any part of it, please reach out.

---

*Continuum — same story, any format. Characters that remember who they are.*
