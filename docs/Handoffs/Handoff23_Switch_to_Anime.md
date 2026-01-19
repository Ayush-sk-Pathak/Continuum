# CONTINUUM ENGINE: ANIME PIVOT HANDOFF DOCUMENT
**Date:** January 7, 2025  
**Session Summary:** Architecture expansion + strategic pivot to anime-first approach

---

## PART 1: WHAT WE ACCOMPLISHED THIS SESSION

### 1A. Architecture Documentation Updates

We made significant additions to `ARCHITECTURE.md`:

**Section 15: USER EXPERIENCE (UX) STRATEGY**
- 15A: MVP Features — Script Approval Workflow ("The Director's Table")
  - User writes story → Director Agent generates scene graph → User reviews/edits → One-button generate → Async notification when ready
  - Character Onboarding flow (upload photos → auto LoRA training → cast library)
  - Project Dashboard concept
- 15B: Future Features
  - Text-Based Video Editing ("Make lighting warmer in shot 3" → selective re-render)
  - Real-time collaboration, voice direction, A/B testing
- 15C: UX Principles (show don't tell, progressive disclosure, fail gracefully, transparent cost)

**Section 16: MULTI-FORMAT OUTPUT STRATEGY**
- Core insight: Director Agent + Consistency Dictionary is format-agnostic
- Output spectrum: Visual Novel (easiest) → Manga/Webtoon (medium) → Animated Video (hardest)
- Shared architecture diagram showing same brain powering different renderers
- Visual Novel Pipeline: Static frames + dialogue, ~30s per frame, image API sufficient
- Manga/Webtoon Pipeline: Panels + layout + speech bubbles, ~2min per page
- API Strategy: **Nano Banana Pro** (Gemini 3 Pro Image) recommended as SOTA for image generation
- Product Rollout Strategy: Video (now) → Manga/VN (quick win) → Webtoon partnerships → Realistic
- Unified positioning: "Consistent AI Storytelling" — not boxing ourselves into one format

**Updated One-Liner:**
> "The first AI storytelling engine that remembers. Consistent characters across manga, visual novels, and animated video — same story, any format."

### 1B. Strategic Decisions Made

1. **Feature 1 (Script Approval Workflow)** — Approved for MVP
   - Write → Preview → Approve → Generate → Notify
   - Differentiates from "prompt and pray" competitors

2. **Feature 2 (Text-Based Video Editing)** — Approved for future roadmap
   - Technically challenging but high value
   - Phased approach: shot-level regen → trim/extend → style transfer → selective re-render

3. **Anti-Features Section** — Removed
   - User wanted to keep options open, not program ourselves to never consider features

4. **Manga/Visual Novel as separate product line** — Approved
   - Can use closed APIs (Nano Banana Pro) since no frame injection needed
   - Much faster generation, faster feedback loop
   - Same Director Agent, different renderer

### 1C. Market Research Conducted

**Open Source Image Models (2025):**
- FLUX.1/FLUX.2 — Best overall quality
- Stable Diffusion 3.5 — Largest ecosystem
- HiDream-I1 — Best prompt adherence
- Nano Banana Pro (Gemini 3 Pro Image) — SOTA, recommended for manga/VN pipeline

**Wan 2.1/2.2 for Anime — Community Verdict:**

Strengths:
- Anime I2V works well ("handling of 2D assets is impressive and fluid")
- LoRA ecosystem growing (retro anime styles available)
- Style transfer capable
- Best open source video model overall
- ComfyUI native support, active development

Weaknesses:
- Face morphing is a real issue (needs negative prompts + consistency measures)
- Hands still problematic (~40% artifact rate in motion)
- Motion glitches (~1 in 5 clips need regeneration, improved in 2.6)
- VAE artifacts ("speckles") — community fixes exist
- LoRA training is complex (two-LoRA system has many variables)

**Key Insight:** Continuum's architecture (LoRA + bridge frames + identity checking) directly addresses Wan's biggest weakness (identity drift). The community struggles with this; we have a solution. That's our moat.

---

## PART 2: THE ANIME PIVOT RATIONALE

### 2A. Why Anime Over Realistic (For Now)

| Factor | Anime | Realistic |
|--------|-------|-----------|
| Forgiveness | High — stylized hides artifacts | Low — every flaw visible |
| Uncanny valley | Doesn't exist | Brutal |
| LoRA ecosystem | Massive, mature | Smaller |
| Physics expectations | Flexible (anime physics OK) | Strict |
| Competition | Less funded indie tools | Runway, Pika, Google, OpenAI |
| Open source quality gap | Small — Wan is competitive | Large — Veo/Sora far ahead |

### 2B. Market Opportunity

Target markets for anime/stylized:
- Webtoon → Video adaptation (huge in Asia, 85M+ monthly users on LINE Webtoon alone)
- VTuber content creation
- Indie game cutscenes
- Manga/light novel trailers
- YouTube anime channels
- Gacha game marketing

Underserved users:
- Webtoon publishers wanting animated trailers
- Indie creators who can't afford animation studios ($50-200K per episode)
- VTuber agencies needing consistent character content
- Game devs needing cutscenes without massive budgets

### 2C. Strategic Positioning

**Brand:** Continuum Studio — "Consistent AI Storytelling"

**Not:** "Anime Generator" (too narrow) or "Video Generator" (too competitive)

**Product Structure — Style Lanes:**
- Anime/Webtoon: ★ Ready (lead with this)
- Realistic: Coming Soon (waitlist builds anticipation)

**Key Message:** Same engine, any style. Your story stays consistent.

---

## PART 3: CURRENT SYSTEM STATE (Before Anime Pivot)

### 3A. What's Working (Validated with Matrix Zero Demo)

- Hero frame generation (SDXL + IP-Adapter + face ref)
- Bridge frame generation (ControlNet pose/depth + IP-Adapter)
- I2V + LoRA rendering (Wan 2.1, 12 steps, ~12 min per 5s shot)
- Identity checking (ArcFace, 95-97% scores achieved)
- Physics checking (works but needs content-aware disable for stylized)
- Checkpointing (resume after crashes)
- Shot stitching
- VAE artifact trimming (first 3 frames)

### 3B. Current Configuration

**Workflows (RunPod):**
- `pass1_img2vid_lora.json` — I2V with LoRA (primary)
- `pass1_structural_lora.json` — T2V with LoRA
- Bridge workflows: `bridge_pose_extract.json`, `bridge_depth_extract.json`, `bridge_full.json`
- `hero_frame.json` — SDXL hero generation

**Models Currently Loaded:**
- Wan 2.1 UNET (14B)
- SDXL (for hero/bridge frames) — realistic checkpoint
- Character LoRA (ayush_wan21_i2v_v1.safetensors) — realistic person
- VAE, CLIP, CLIP Vision, ControlNet (pose, depth)

**Performance Baseline:**
- Hero frame: 15-20s
- Bridge frame: 30-75s
- I2V+LoRA (60 frames): ~12 min
- Identity scores: 95-97%

---

## PART 4: STEP-BY-STEP ANIME PIVOT PLAN

### PHASE 1: Configuration Changes (Day 1 — ~2 hours)

**Step 1.1: Obtain Anime Checkpoints**

Download and deploy to RunPod:
- Hero/Bridge frame checkpoint: Animagine XL 3.1 or Pony Diffusion V6 XL
- Location: `/workspace/runpod-slim/ComfyUI/models/checkpoints/`

Recommended options (pick one):
- `animagine-xl-3.1.safetensors` — general anime, good quality
- `ponyDiffusionV6XL.safetensors` — very flexible, good for various anime styles
- `counterfeitxl_v25.safetensors` — high quality anime aesthetic

**Step 1.2: Update Model Configuration**

In `models.json` or equivalent config, add anime style configuration:
- Create a new style profile "anime" alongside existing "realistic"
- Point hero_frame_checkpoint to anime SDXL checkpoint
- Point bridge_frame_checkpoint to same anime checkpoint
- Keep Wan 2.1 UNET unchanged (same model works for both)

**Step 1.3: Create Anime Prompt Templates**

Add to prompt configuration:
- Positive template: Include "anime style, cel shading, vibrant colors, detailed linework"
- Negative template: Include "realistic, photo, 3d render, morphing face, shifting features, extra fingers, poorly drawn hands, bad anatomy, blurry, deformed"
- Style-specific tokens for different anime aesthetics (90s retro, modern, chibi, etc.)

**Step 1.4: Adjust Physics Checker**

Already identified: Physics checker should be disabled or heavily relaxed for anime content.
- Add style-aware toggle in audit configuration
- For anime: disable gravity checks, relax collision checks
- Keep identity checking enabled (but see Phase 2)

---

### PHASE 2: Identity Checker Adaptation (Day 1-2 — ~4 hours)

**The Problem:**
ArcFace (buffalo_l) is trained on real human faces. Anime faces have completely different proportions (huge eyes, tiny nose, stylized features). ArcFace will give unreliable or failing scores on anime characters.

**Step 2.1: Implement Style-Aware Identity Checking**

In `identity_checker.py`:
- Add style parameter to identity check functions
- If style == "anime": use CLIP-based similarity instead of ArcFace
- If style == "realistic": use existing ArcFace path

**Step 2.2: Implement CLIP-Based Identity Checker**

For anime characters:
- Use CLIP image encoder (already available in ecosystem)
- Extract embeddings from character region in frame
- Compare cosine similarity between frames
- Threshold: ~0.85 for "same character" (tune based on testing)

Why CLIP works for anime:
- Trained on diverse image types including illustrations
- Captures semantic similarity, not just facial geometry
- Generalizes across art styles

**Step 2.3: Character Region Extraction**

For more accurate identity checking:
- Use simple bounding box crop around character (prompt-guided or fixed region)
- Or use anime-specific segmentation if needed (lower priority)
- Compare character regions, not full frames

---

### PHASE 3: LoRA Training Pipeline (Day 2-3 — ~8 hours including GPU time)

**Step 3.1: Prepare Training Data**

For a test anime character:
- Collect 10-20 reference images of the character
- Various angles, expressions, poses
- Consistent art style
- Clean backgrounds preferred (can be prompted away)

Or use existing anime character dataset for testing.

**Step 3.2: Train Wan 2.1 Anime Character LoRA**

Use existing LoRA training setup (ai-toolkit, kohya, or musubi-tuner):
- Base model: Wan 2.1 14B
- Training resolution: 480x480 or 400x300 (match generation resolution)
- Rank: 16 (sufficient for Wan's large parameter count)
- Training frames: 33-53 frames per clip minimum
- Include trigger word for character

Key settings from community research:
- Use detailed captions (Gemini or local LLM)
- Include diversity in lighting, angles, concepts
- For I2V, high quality clips are critical

**Step 3.3: Test LoRA Integration**

- Load trained LoRA in existing I2V workflow
- Generate test clips with anime hero frame
- Verify identity consistency across shots
- Tune LoRA strength if needed (start at 0.8)

---

### PHASE 4: End-to-End Testing (Day 3-4 — ~4 hours)

**Step 4.1: Create Anime Test Project**

Create a simple 2-scene, 4-shot test project:
- Scene 1: Indoor (2 shots)
- Scene 2: Outdoor (2 shots)
- Single anime character throughout
- Simple actions (walking, talking, reacting)

**Step 4.2: Run Full Pipeline**

Execute with anime configuration:
1. Hero frame generation (anime checkpoint)
2. I2V + LoRA (Wan 2.1 + anime character LoRA)
3. Bridge frame generation (anime checkpoint)
4. Identity audit (CLIP-based)
5. Stitching

**Step 4.3: Evaluate Results**

Check for:
- Character consistency across shots (visual inspection + CLIP scores)
- Face morphing during shots (known Wan issue)
- Hand artifacts (minimize hand motion in test prompts)
- Style consistency (anime aesthetic maintained)
- Bridge frame quality (smooth transitions)

**Step 4.4: Iterate and Tune**

Based on results:
- Adjust negative prompts for specific artifacts
- Tune CLIP identity threshold
- Adjust LoRA strength
- Modify prompt templates

---

### PHASE 5: Documentation and Productization (Day 4-5)

**Step 5.1: Update Configuration Documentation**

Document:
- How to switch between realistic and anime styles
- Anime checkpoint options and their characteristics
- Anime-specific prompt guidelines
- Identity checker configuration per style

**Step 5.2: Add Style Selection to Project Config**

In project.json schema:
- Add `style` field: "anime" | "realistic" | "webtoon" etc.
- Style determines: checkpoint, prompt templates, audit settings
- Allow per-scene style override if needed (future)

**Step 5.3: Update ARCHITECTURE.md**

Add implementation notes for anime pipeline:
- Which checkpoints validated
- CLIP identity checker details
- Prompt template examples
- Known limitations and workarounds

---

## PART 5: KNOWN ISSUES AND MITIGATIONS

| Issue | Mitigation |
|-------|------------|
| Face morphing | Strong negative prompts + LoRA + bridge frames (our existing architecture helps) |
| Hand artifacts | Minimize hand motion in prompts; keep hands static or out of frame |
| VAE speckles | Consider community VAE fix (spacepxl/Wan2.1-VAE-upscale2x) if severe |
| Identity drift over long shots | Existing bridge frame strategy addresses this |
| ArcFace fails on anime | CLIP-based identity checker (Phase 2) |
| Style inconsistency | Single anime checkpoint for all frames; style LoRA if needed |

---

## PART 6: FUTURE ENHANCEMENTS (Post-Pivot)

### 6A. Short Term (1-2 weeks after pivot)

- Test Wan 2.2 or 2.6 for improved motion quality
- Add 2-3 anime style presets (90s retro, modern, chibi)
- Implement style LoRA stacking (character + style)

### 6B. Medium Term (1-2 months)

- Manga/Visual Novel pipeline using Nano Banana Pro
- Webtoon vertical scroll format support
- Multiple character LoRA support per project

### 6C. Long Term (3+ months)

- Realistic style lane (when open source catches up)
- Custom anime VAE integration
- Anime-specific face detection for better identity checking

---

## PART 7: FILES MODIFIED THIS SESSION

| File | Changes |
|------|---------|
| `ARCHITECTURE.md` | Added Section 15 (UX), Section 16 (Multi-Format), updated one-liner |
| (Changelog updated) | v2025.11 entry added |

---

## PART 8: RESOURCES AND REFERENCES

### Anime Checkpoints (Download Links)
- Animagine XL 3.1: https://huggingface.co/cagliostrolab/animagine-xl-3.1
- Pony Diffusion V6: https://civitai.com/models/257749/pony-diffusion-v6-xl
- Counterfeit XL: https://civitai.com/models/118406/counterfeitxl

### LoRA Training
- Wan 2.1 LoRA Guide: https://civitai.com/articles/14070/wan-21-video-lora-training-guide
- musubi-tuner: https://github.com/kohya-ss/musubi-tuner
- ai-toolkit: https://github.com/ostris/ai-toolkit

### Community Fixes
- VAE Upscale Fix: https://huggingface.co/spacepxl/Wan2.1-VAE-upscale2x
- Skip Layer Guidance (for morphing fix): ComfyUI node

### Nano Banana Pro (for Manga/VN pipeline)
- API Docs: https://ai.google.dev/gemini-api/docs/nanobanana
- Model: gemini-3-pro-image-preview
- Pricing: ~$0.04/image (1K), ~$0.13/image (4K)

---

## PART 9: QUICK START FOR NEXT SESSION

**If continuing anime pivot work:**

1. Read this handoff document fully
2. Check RunPod pod status — restart if needed
3. Start with Phase 1 (configuration changes)
4. Download anime checkpoint first (Animagine XL 3.1 recommended)
5. Test hero frame generation with anime checkpoint before full pipeline

**If debugging existing realistic pipeline:**
- Refer to previous transcript: `/mnt/transcripts/2026-01-07-11-52-36-matrix-zero-i2v-lora-first-success.txt`
- Matrix Zero demo achieved 95-97% identity scores
- 12 steps, uni_pc sampler, ~12 min per shot

**Key files to review:**
- `/mnt/project/ARCHITECTURE.md` — Master blueprint (updated this session)
- `/mnt/project/identity_checker.py` — Will need CLIP addition
- `/mnt/project/models.json` — Model configuration
- `/mnt/project/config.py` — Style configuration

---

**END OF HANDOFF DOCUMENT**