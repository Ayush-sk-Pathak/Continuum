# Continuum Architecture (Compact Reference)
*Condensed from architecture.md - all content preserved, optimized for token efficiency*

## CHANGELOG
**v2026.01**: ANIME PIVOT - CLIP similarity (0.85) for anime, StyleType enum, well-known characters (Goku/Naruto) for testing, custom LoRA for production original characters.
**v2025.11**: Added UX Strategy (Section 15), Multi-Format Output (Section 16), Data Strategy reference (Section 18).
**v2025.10**: Redundant Identity Stack, Stand-In for Wan, IP-Adapter during I2V gap, Model Upgrade Path, Face Enhancement Pipeline.

---

## 1. EXECUTIVE SUMMARY

**Problem**: AI filmmaking fails at World Consistency, Long-Form Continuity, and Sensory Immersion.

**Solution**: Neuro-Symbolic Director Agent + Cloud GPUs + "Continuum" 3-Layer Strategy:
- **Layer 1 (Consistency Engine)**: Visual RAG + StreamingT2V for 30-60s+ coherence
- **Layer 2 (Pacing Safety Net)**: "Smart Cut" before drift occurs
- **Layer 3 (Bridge Frame)**: Synthetic first frame for seamless shot transitions

**Pipeline**:
- Pass 1: Structure + Audio (StreamingT2V + Bridge Frames + Sonic Engine)
- Pass 2: Refinement (vid2vid/FreeLong++ + flicker reduction)
- Pass 3: Post-Production (color normalization + audio ducking)

**Key Docs**: `ARCHITECTURE_SUMMARY.md`, `MODEL_CONFIGURATION.md`, `LESSONS_LEARNED.md`

---

## 2. VISION: The "Infinite Shot" Engine

**Core Promise**: 2-5 minute cinematic stories (Phase 2: 10-30 min) with:
- Same kitchen in Minute 1 and Minute 5
- "Alice" consistent across scenes
- Props (red mug) maintain identity across cuts

**Moat**: Context Loop with Visual RAG + Consistency Dictionary + Scene Graph.

---

## 3. TECH STACK

### 3A. The Brain (Mac M4 -> Cloud API)
- **Model**: GPT-4o-mini/Claude Haiku (~$0.02/5-min film), Ollama fallback
- **Responsibilities**: Parse scripts -> Scene Graph, Consistency Dictionary, orchestrate ComfyUI/RAG calls
- **Physics Reviewer** (<30s per 10s clip): YOLOv8+ByteTrack (object permanence), RAFT (flicker), gravity/collision heuristics
- **Stability Monitor**: Max_Duration=12s per shot, ArcFace QA (threshold 0.7), auto re-roll (max 3)
- **World State Tracker**: JSON coordinate system for object positions

### 3B. The Guide (Retrieval & Control)
- **Visual RAG**: Pinecone for character sheets, location panoramas, LoRA metadata
- **Layout Generator**: Director produces bounding boxes -> ControlNet/region prompts

### 3C. The Muscle (Cloud GPUs)
- **Hardware**: RunPod/Lambda (A10/A100/H100)
- **Model Tiers**: dev (1.3B/8GB), standard (14B bf16/24GB), beast (14B fp16/40GB)
- **ComfyUI Nodes**: StreamingT2V, LoRA, IP-Adapter, ControlNet, CoNo
- **Premium Lane**: Veo 3.1/Sora/Runway behind uniform Renderer interface

---

## 4. SYSTEMS DETAIL

### 4A. Hero Engine (Identity Lock)
- **Tech**: LoRA (Kohya/musubi-tuner), IP-Adapter, InstantID/PuLID
- **Progressive Identity**: 1 img=InstantID(85%), 4+=LoRA(90%), 15+=Premium(95%+)
- **CRITICAL**: Don't augment single images; more REAL images = better LoRA

**Redundant Identity Stack** (Defense in Depth):
| Layer | Method | Quality | Status |
|-------|--------|---------|--------|
| 1 | LoRA | +15% | Optional |
| 2 | IP-Adapter | +25% | ACTIVE (hero/bridge) |
| 3 | ControlNet | +10% | ACTIVE |
| 4 | Face Enhancement | +3-5% | NOT IMPLEMENTED |
| 5 | ArcFace QA | Catch failures | ACTIVE |

**Stand-In for Wan**: Tencent identity branch (~1% params), native to Wan, may replace IP-Adapter.

**IP-Adapter During I2V Gap**: Currently not active in Wan I2V, causes drift from 100%->97% within shot. Fix: ComfyUI-IPAdapter-WAN extension.

### 4B. Bridge Engine (CRITICAL - DO NOT BYPASS)

**What**: Synthetic "perfect first frame" using SDXL + ControlNet Pose + IP-Adapter.

**When Needed**: EVERY video generation restart (shot changes, chunks, repairs, re-rolls). NOT needed within continuous 12s chunk.

**Why**: Video models have NO MEMORY. Without bridge frames: Shot1(100%) -> Shot2(98%) -> Shot3(94%) -> Shot5(80%). WITH bridge frames: 100% at every cut.

**Bypass Attempts (ALL WRONG)**:
1. "Raw frame is good enough" - Model drifts without IP-Adapter re-anchor
2. "LoRA handles identity" - LoRA biases but doesn't LOCK
3. "Skip for speed" - Fast garbage is still garbage
4. "SDXL style mismatch" - One frame style irrelevant, identity lock survives

**Implementation**:
1. Capture: FFmpeg extract last frame
2. Extract Pose: ComfyUI ControlNet Preprocessor
3. Extract Depth: Depth Anything/MiDaS (optional)
4. Generate: SDXL + ControlNet Pose/Depth + IP-Adapter + LoRA
5. Inject: Pass to Wan I2V as init_image

**Workflows**: `bridge_full.json` (best), `bridge_pose_only.json`, `bridge_ipadapter.json`. Never use `bridge_basic.json`.

**Degradation Ladder**: Tier1(full)->Tier2(no depth)->Tier3(IP-Adapter only)->Tier4(raw frame - WARN LOUDLY)

### 4C. Physics & Layout Engine
- ControlNet (Depth/Pose/Layout) prevents hallucinations
- "Cardboard Fort" pre-viz: 3D blockout -> Depth Map -> ControlNet anchor
- Dynamic events: Lower ControlNet strength for action, commit state changes

### 4D. Multi-Hero Engine
- Regional prompting + attention masking
- Apply Alice LoRA in Region A, Bob LoRA in Region B

### 4E. World Engine (Environment Lock)
- IP-Adapter + environment keyframes (panoramas)
- Progressive: Tier1 IP-Adapter (~70%), Tier2 Auto-LoRA (~90%)
- LoRA stacking: Character(0.7) + Location(0.5), total <1.2

### 4F. Two-Pass Rendering

**Pass 1 (Structure)**:
- Wan/Hunyuan/Mochi + StreamingT2V + LoRA + IP-Adapter + ControlNet + CoNo
- Director Logic: Generate shot -> Monitor drift -> State Audit -> Bridge Frame -> Next shot

**Pass 2 (Refinement)**:
- Vid2vid/FreeLong++ for flicker reduction
- Lip sync (after refinement, before RIFE)
- RIFE: 12fps -> 24fps

### 4G. Voice Engine
- TTS: ElevenLabs/OpenAI
- Lip Sync: Musetalk/Wav2Lip (after Pass 2, before RIFE)
- Dialogue Map: [(character, line, shot_id, chunk_range, voice_id, audio_path)]

### 4H. Sonic Engine
- Ambience: AudioLDM-2 (location-locked seeds)
- Foley: Event-triggered SFX
- Score: MusicGen with Leitmotifs
- MVP: TTS + Lip Sync + Basic Ambience + Audio Ducking (-12dB)

### 4I. Consistency Audit Engine
- Phase 1: ArcFace (<0.70=FAIL), YOLOv8+ByteTrack, RAFT, CLIP (<0.85=FLAG)
- Phase 2: VideoLLaMA 2 -> Vidi2 (when available) for spatio-temporal grounding

### 4J. Post-Production Engine
- Auto-Color: Histogram match to Master Shot
- Audio Ducking: -15dB during dialogue
- Project State: Non-destructive, re-calculates on shot swap

### 4K. Error Recovery
- Max re-rolls: 3/chunk, 5/shot
- Checkpointing: Save after each chunk, resume on crash
- Graceful degradation: Missing LoRA->IP-Adapter, missing env ref->prompt-only

### 4L. Model Upgrade Path

| Model | Identity | VRAM | Speed | Status |
|-------|----------|------|-------|--------|
| Wan 2.1 + IP-Adapter | ~97% | 24GB | Fast | CURRENT |
| Wan 2.1 + Stand-In | ~98%? | 24GB | Fast | TESTING |
| HunyuanCustom | ~99%? | 48GB+ | Slow | EVALUATE |

**Integration Principle**: All models implement `BaseRenderer.render(spec) -> result`.

### 4M. Face Enhancement Pipeline
- Tools: GFPGAN (fast), CodeFormer (higher quality)
- Trigger: ArcFace 0.70-0.85 = try enhancement, <0.70 = re-roll
- Placement: After Pass 1, before Pass 2

---

## 5. ARCHITECTURE DIAGRAM (Simplified)

```
SCRIPT -> TRUST_SAFETY -> DIRECTOR_AGENT
                              |
           +------------------+------------------+
           |                                     |
    [TRACK A: VISUAL]                    [TRACK B: SONIC]
           |                                     |
    Pass 1: Structure                    Ambience/Foley/Score/TTS
    (Wan+LoRA+IP-Adapter+Bridge)                 |
           |                                     |
    REVIEWER_AGENT (ArcFace/Physics)             |
           |                                     |
    Pass 2: Refinement+LipSync+RIFE             |
           |                                     |
           +------------------+------------------+
                              |
                    POST-PRODUCTION
                    (Color+Audio Ducking)
                              |
                      FINAL VIDEO
```

---

## 6. I2V-FIRST ARCHITECTURE

**CRITICAL**: T2V for Shot 1 BREAKS consistency. Use I2V for ALL shots.

**Correct Flow**:
- Shot 1: SDXL Hero Frame (IP-Adapter) -> I2V
- Shot 2+: SDXL Bridge Frame (IP-Adapter + ControlNet) -> I2V

**T2V Valid Uses**: Exploration mode, dev testing, LoRA training data. NEVER for production.

| Scenario | T2V | I2V | Why |
|----------|-----|-----|-----|
| Production Shot 1 | NO | YES | Identity must be locked |
| Exploration | YES | NO | No identity constraint |
| Customer demo | NO | YES | Identity is value prop |

---

## 7. INFRASTRUCTURE & COST

**Lane Costs (5-min film)**:
- Pure OSS: ~$6.90 (Pass1 $3.90, Pass2 $1.50, Assets $0.50, Storage $1)
- Hybrid Pro: ~$122-242 (Veo API + OSS repair)

**90-Day Budget**: ~$2,400 (GPU $1200, TTS $150, Image APIs $100, LLM $50, contingency $300)

---

## 8. ROADMAP (90 Days)

**Phase 1 (Days 1-30)**: Director + Bible MVP
- Scene Graph Generator, Bible Folder, Manual ComfyUI workflow
- Budget: ~$150-200

**Phase 2 (Days 31-60)**: Streaming Automation
- Python -> ComfyUI API, "Infinite Pan" demo, Visual RAG integration
- Budget: ~$200-250

**Phase 3 (Days 61-90)**: 5-Minute Film
- Full pipeline (Pass1+2+RIFE), Voice+LipSync, Consistency Audit
- Demo: 3-5 min with synced dialogue, consistent identity, immersive audio
- Budget: ~$100-150

---

## 9. GO-TO-MARKET

**Target Markets**:
1. PRIMARY: Virtual Influencer Agencies
2. SECONDARY: Webtoon Publishers
3. TERTIARY: Ad Agencies (FMCG)

**Strategy**: "Trojan Horse" - Create internal influencer "Koda", pitch via live profile.

**Pricing**: "Digital Ambassador Package" $2-5K/month (1-3 characters, 10-20 videos/month)

---

## 10. UX STRATEGY

**Core Flow**: Write -> Approve -> Walk Away -> Get Notified

**MVP Features**:
1. **Script Approval Workflow** ("Director's Table"): Script -> Scene Graph -> User Review -> One-Button Generate -> Notification
2. **Character Onboarding**: Upload refs -> LoRA training (background) -> Character in Cast library
3. **Project Dashboard**: Active renders, completed projects, Cast/Backlot libraries

**Future**: Text-based video editing, collaboration, voice direction, A/B testing, templates

**Principles**: Show don't tell, progressive disclosure, fail gracefully, transparent cost, respect time, creative control

---

## 11. MULTI-FORMAT OUTPUT

**Formats** (easiest to hardest):
| Format | Time | Cost | Tech |
|--------|------|------|------|
| Visual Novel | ~30s/scene | $0.04-0.13/frame | Nano Banana Pro/SDXL |
| Manga/Webtoon | ~2min/page | $0.40-1.30/page | Nano Banana Pro/SDXL |
| Animated Video | ~15min/30s | $0.50-2.00 | Wan/Hunyuan |

**Shared Architecture**: Director Agent + Consistency Dictionary + World State Tracker -> Format-specific Renderer

**Recommended Image API**: Nano Banana Pro (Gemini 3 Pro Image) - best character consistency, excellent text rendering, $0.04-0.13/image

**Rollout**:
1. Phase 1A (NOW): Anime Video
2. Phase 1B (2-3 weeks): Manga/Visual Novel
3. Phase 2: Webtoon Platform Integration
4. Phase 3: Realistic Video

---

## 12. DATA STRATEGY

See `DATA_STRATEGY.md`. Moat = proprietary data (LoRAs, approval signals, style embeddings). Key milestone: 50K generations -> train ConsistencyNet v1.

---

## ONE-LINER

"The first AI storytelling engine that remembers. Consistent characters across manga, visual novels, and animated video - same story, any format."
