AI Consistent Character Engine -- MASTER STRATEGY & PRODUCT BLUEPRINT (v2025.10)
The "Pixar-on-Demand" Engine
================================================================================
0. EXECUTIVE SUMMARY
================================================================================
CHANGELOG v2026.01 (Jan 2026):
- **ANIME PIVOT**: Switched from realistic human characters to anime for VC demo
  - Identity checking: CLIP similarity (0.85 threshold) instead of ArcFace for anime style
  - Reference images + IP-Adapter for identity anchoring
  - StyleType enum in config.py: REALISTIC, ANIME, WEBTOON
- **Testing vs Production Identity Strategy**:
  - TESTING (current): Well-known characters (Goku, Naruto) - no LoRA needed, base model recognizes them
  - PRODUCTION (future): Original characters WILL require custom LoRA training
  - LoRA training pipeline remains essential for: custom anime characters, brand mascots, original IP
  - The Wan 2.1 LoRA training workflow (see Lesson #87) applies to anime style too
- Updated `test_demo_matrix_zero.py` for anime workflow (video-only, no audio)
- Updated `projects/matrix_zero/project.json` with anime characters and scenes
- See LESSONS_LEARNED.md #90 for full pivot details

CHANGELOG v2025.11 (Jan 2025):
- Added Section 15: USER EXPERIENCE (UX) STRATEGY
  - 15A: MVP Features (Script Approval Workflow, Character Onboarding, Dashboard)
  - 15B: Future Features (Text-Based Video Editing, Collaboration, Voice Direction)
  - 15C: UX Principles (Design guidelines)
- Added Section 16: MULTI-FORMAT OUTPUT STRATEGY
  - 16A-B: Output Format Spectrum & Shared Architecture
  - 16C: Visual Novel Pipeline (easiest, ~30s/frame)
  - 16D: Manga/Webtoon Pipeline (medium, ~2min/page)
  - 16E: Animated Video Pipeline (hardest, current implementation)
  - 16F: API Strategy (Nano Banana Pro recommended for images)
  - 16G: Product Rollout Strategy (Video → Manga/VN → Webtoon → Realistic)
  - 16H: Unified Product Positioning
- Added Section 18: DATA STRATEGY & MOAT (brief reference)
  - Full details in separate document: DATA_STRATEGY.md
- Updated Final One-Liner (reflects multi-format + consistency vision)
- Updated Section 16: Final One-Liner (reflects UX philosophy)

CHANGELOG v2025.10 (Dec 2024):
- Added Section 3A.3: Redundant Identity Stack (defense in depth)
- Added Section 3A.4: Stand-In for Wan (Tencent research integration)
- Added Section 3A.5: IP-Adapter During I2V (implementation gap)
- Added Section 3N: Model Upgrade Path (future engines)
- Added Section 3O: Face Enhancement Pipeline (post-processing safety net)
- Updated Section 3B.1: Clarified IP-Adapter availability for Wan via extension
- Source: IP_LORA_Research.md deep research (Dec 2024)
--------------------------------------------------------------------------------
The Problem: AI filmmaking currently fails at World Consistency (locations morphing), Long-Form Continuity (characters drifting over 2-5+ minutes), and Sensory Immersion (silent or disjointed audio). Most solutions rely purely on giant diffusion models that forget context and treat each clip as an isolated lucky roll.
Our Approach: We are not just generating video; we are directing a fully immersive world over time.
A Neuro-Symbolic Director Agent (LLM via cloud API) orchestrated from the user's MacBook Air M4.
Heavy rendering happens on cloud GPUs using composable ComfyUI workflows and open-source video/audio models.
The "Continuum" Strategy: We enforce consistency with a "Max-Duration + Smart-Cut" Strategy:
Layer 1 (The Consistency Engine): A Visual RAG + StreamingT2V stack designed to push single-shot coherence to its limit (aiming for 30-60s+ of continuous identity stability).
Layer 2 (The Pacing Safety Net): If the Director Agent detects imminent drift--or if cinematic pacing demands it--we trigger a "Smart Cut" to a new angle before quality degrades.
Layer 3 (The Bridge Frame): We generate a synthetic "Bridge Frame" (a mathematically perfect first frame for the next shot) to ensure the narrative flows seamlessly across these cuts without "resetting" the emotion or physics.
A Multi-Stage "Digital Studio" Pipeline:
Pass 1 (Structure & Sound): Structural video generation (StreamingT2V + Bridge Frames) runs in parallel with The Sonic Engine (Ambience/SFX/Score) to ensure the audio world is as consistent as the visual world.
Pass 2 (Refinement): Visual flicker reduction and detail enhancement using vid2vid / FreeLong++-style methods.
Pass 3 (Post-Production): The Post-Production Engine applies Auto-Color Normalization (matching shots to a master histogram) and Smart Audio Ducking to deliver a cohesive, broadcast-ready final cut.
The Result: This hybrid "state-aware" system gives us film-like continuity at a fraction of the cost of closed APIs like Veo/Sora, with more control and programmability.
Hybrid Capability: Capable of ingesting footage from Veo/Sora and 'consistency-locking' it using our proprietary post-processing engine to give high quality cinematics (for pro users).

Implementation References:
- `docs/ARCHITECTURE_SUMMARY.md` -- Working dev summary (wins for implementation details)
- `docs/MODEL_CONFIGURATION.md` -- Model tier switching (dev/standard/beast)
- `docs/LESSONS_LEARNED.md` -- Debugging history and gotchas
================================================================================
1. VISION: The "Infinite Shot" Engine
================================================================================
Build the world's first Consistent AI Character & World Engine that enables writers to become "AI Story Filmmakers," not prompt gamblers.
Core Promise: Create 2-5 minute cinematic stories (Phase 2 target: 10-30 min*) where:
The kitchen in Minute 1 is exactly the same kitchen in Minute 5.
The character "Alice" looks and moves like the same person across multiple scenes and shots.
Props (like a specific red mug) keep their identity across cuts.
*Note: 10-30 minute videos require careful scene segmentation and are a stretch goal. MVP focuses on 5-minute maximum with high consistency confidence.
The Moat: The Context Loop
Unlike standard tools that spit out random unconnected clips, our engine uses a "Look-Back + Visual Bible" memory system:
Every new scene and chunk is anchored in:
Canonical character assets (LoRAs, face embeddings, keyframes).
Canonical environment references (location panoramas).
A structured Scene Graph + Consistency Dictionary managed by the Director Agent.
We are not fighting for "prettier pixels" -- we are winning on programmable continuity.
================================================================================
2. THE TECH STACK: HYBRID ARCHITECTURE
================================================================================
We separate the Brain from the Body to leverage the MacBook Air M4 for orchestration and rented cloud GPUs for muscle.

2A. The Brain (MacBook Air M4 -> Cloud API)

Model: GPT-4o-mini or Claude 3.5 Haiku (via API) Role: The Director Agent. Runs: API calls dispatched from local MacBook M4 orchestrator. Cost: ~$0.02 per 5-minute film (negligible vs. video generation costs). Offline Fallback: Ollama + Llama 3.1 8B for privacy-sensitive or offline use cases.
Development Note: The MacBook M4 handles all orchestration code, job dispatch, and UI -- but model inference (both LLM and video) runs on cloud resources.
Responsibilities:
Parse scripts into a Scene Graph:
Scenes, shots, characters, props, locations, camera notes.
Maintain a Consistency Dictionary:
Alice -> canonical asset IDs (LoRA, reference images, keyframes).
Kitchen -> canonical environment assets.
Red Mug -> prop identity.
Validate continuity:
"Is Alice still wearing the right outfit?"
"Is the sword still in her hand in Scene 3 if she picked it up in Scene 2?"
Orchestrate calls to:
Visual RAG
ComfyUI workflows
Cloud render jobs
Physics sanity review (post-render): The Director runs a lightweight Physics Reviewer on each generated chunk (5-15 seconds). Budget: <30 seconds processing per 10-second clip on GPU.
**MVP Implementation (CV-Based, <30s per 10s clip):**
1. Object Permanence Check (YOLOv8 + ByteTrack): - Detect characters/props in each frame - Track identities across frames - FLAG: Object disappears for >3 frames without exiting frame - FLAG: Object appears mid-scene with no entry point
2. Flicker Detection (RAFT optical flow): - Compute frame-to-frame motion - FLAG: High pixel change with low motion flow (texture popping) - FLAG: Motion magnitude spikes without contact/force
3. Gravity Heuristic: - Track vertical position of unsupported objects - FLAG: Object above ground that doesn't move downward over time - Exception: Script/prompt indicates magic/flying
4. Collision Check: - Monitor bounding box overlaps - FLAG: Two solid objects overlap >50% (passthrough) - FLAG: Collision occurs but no reaction (no bounce, no movement)
5. (Optional) Pose Physics (MediaPipe): - Track character skeleton joints - FLAG: Foot slides across ground during weight-bearing - FLAG: Anatomically impossible joint angles

Thresholds & Tolerance:** -
Require object missing for 3+ consecutive frames before flagging (avoid occlusion false positives)
 Only flag flicker if affects >5% of frame area
 Allow brief physics violations if followed by correction (e.g., object wobbles then falls)

**Context Awareness:** -
If prompt contains "magic", "dream", "flying" -> relax gravity checks
If prompt contains "ghost", "spirit" -> relax collision checks
 Parse script for intentional physics violations
* V2 Upgrade (VideoLLM-Assisted):** -
Add cause-effect reasoning: "Did every motion have a visible cause?"
Add VideoLLM confirmation for borderline flags
 Add action recognition (SlowFast) for collision/fall event verification
The Stability Monitor (The Pacer): Goal: Maximize shot duration while staying within model stability window. Strategy: Rather than real-time drift detection (complex, error-prone), we use a simpler approach:
Pre-set Max_Duration per shot (default: 12 seconds, within proven model stability)
Post-render QA: ArcFace similarity check (first frame vs last frame, threshold 0.7)
If QA fails: auto re-roll with different seed (max 3 attempts) Trigger: Shot ends at Max_Duration OR pacing logic dictates a camera change. Bridge Architect: Extracts the "End State" (expression, prop position) of the completed shot and orders a Bridge Frame to anchor the start of the next shot.
Dynamic World State Tracker (The Stage Manager): Maintains a lightweight "Low-Poly" coordinate system (JSON or Python script) for every scene. Pre-Shot: Places objects in 3D space (Alice @ 0,0,0; Mug @ Table_Left). Post-Shot Update: If an "Event" occurred (e.g., "Mug Thrown"), it analyzes the final frame of the previous shot, calculates the new rough position of the object (Mug @ Floor), and updates the coordinate system for the next shot.

2B. The Guide (Retrieval & Control Layer)

This is the memory spine of the system.
Memory:
Visual RAG (Pinecone or equivalent) for semantic assets:
Character sheets, location panoramas, keyframes.
LoRA metadata (paths, configs).
Consistency Memory Store (e.g. object storage + metadata DB):
Canonical latent descriptors or keyframes for each entity/location per scene.
Control:
Layout / Blockout Generator:
Director Agent produces layouts (bounding boxes, roles per region).
These layouts drive ControlNet / region prompts / IP-Adapter in ComfyUI.
Output of this layer: A fully specified shot request with:
Scene/shot metadata
Which characters appear, with which assets
Which environment is used
Where everyone stands (layout)
Which ComfyUI workflow template to call

2C. The Muscle (Cloud -- GPUs)

Infrastructure: RunPod / Lambda Labs / other GPU rental. Typical hardware: A10 / A100 / H100 depending on budget and scale.
Model lane (Open Source):
Base video model: Wan 2.x / HunyuanVideo / Mochi (pluggable).
Model Tier System: Supports dev (1.3B, 8GB VRAM), standard (14B bf16, 24GB), and beast (14B fp16, 40GB) tiers for quality/speed tradeoffs. Configured via CONTINUUM_MODEL_TIER env var and models.json registry.
Wired via ComfyUI custom nodes:
StreamingT2V-style chunking
LoRA
IP-Adapter
ControlNet
CoNo at chunk boundaries.
Optional Premium lane:
Veo 3.1 / Sora / Runway Gen-4 / other APIs behind a uniform "Renderer" interface.
Veo 3.1 Features (Dec 2025):
"Ingredients to Video" -- multi-reference image control (up to 14 refs)
"Frames to Video" -- first/last frame control (aligns with Bridge Frame concept)
"Extend" -- scene continuity up to 1+ minute
Native audio generation (can supplement Sonic Engine)
The Director on Mac sends job specs to this Muscle layer, which only focuses on deterministic, reproducible rendering -- not planning.
================================================================================
3. THE "SYSTEMS" TECH STACK (DETAIL)
================================================================================
We use a two-pass pipeline and a modular hierarchy:
LoRA/IP-Adapter for identity
ControlNet/layout for physics & staging
StreamingT2V + CoNo for long-form structure
Vid2Vid / FreeLong++-style for refinement
RIFE for frame-rate and smoothness

3A. The Hero Engine (Identity Lock)

Goal: Pixel-stable character identity ("Alice is always Alice"). Technology: LoRA (Low-Rank Adaptation) and/or textual inversion. Tools: Kohya_ss (musubi-tuner for Wan), ComfyUI LoRA loaders, IP-Adapter for faces, InstantID/PuLID for zero-shot.
System Fit:
Train or configure one LoRA per hero character.
Inject LoRA into the base video model in all relevant shots.
Store LoRA configs + reference images in Visual RAG with stable IDs.

--------------------------------------------------------------------------------
3A.1 PROGRESSIVE IDENTITY SYSTEM (Single-Image Onboarding)
--------------------------------------------------------------------------------

Users can start generating videos with just 1 image. Quality improves as they
provide MORE REAL reference images. This enables instant gratification while
incentivizing users to invest more for better results.

THE CORE INSIGHT:
  - Zero-shot methods (InstantID/PuLID) work instantly with 1 image (~85% match)
  - LoRA quality depends on REAL image count, not training duration
  - More real images = cleaner training signal = better identity lock

IDENTITY TIERS (by Real Image Count):

| Tier     | Images | Method              | Identity | Wait Time | Pricing   |
|----------|--------|---------------------|----------|-----------|-----------|
| Instant  | 1      | InstantID/PuLID     | ~85%     | 0 sec     | Free      |
| Quick    | 1-4    | LoRA (epoch 10-15)  | ~88-90%  | 15 min    | $5/video  |
| Standard | 5-10   | LoRA (epoch 30)     | ~92-94%  | 45 min    | $10/video |
| Premium  | 15-20  | LoRA (epoch 50)     | ~95%+    | 90 min    | $20/video |

CRITICAL: DO NOT AUGMENT SINGLE IMAGES

Previous strategy suggested augmenting 1 image into 15-20 variations using
image generation. This is WRONG because drift compounds:

  WRONG APPROACH (causes drift):
  1 Real Image â†’ Augment to 20 "Fake" Images â†’ LoRA Training
       100%            ~95% each                 compounds to ~85%
  
  CORRECT APPROACH (clean signal):
  4 Real Images â†’ LoRA Training Directly
       100% each            ~90% identity match

Rule: Quality cannot be faked. More REAL images = better LoRA.

USER EXPERIENCE FLOW:

  User uploads 1 photo
      â”‚
      â”œâ”€â–º INSTANT: InstantID generates preview in seconds
      â”‚   â””â”€â–º User can start creating immediately (85% quality)
      â”‚
      â”œâ”€â–º PROMPT: "Upload 3 more photos to unlock Standard quality"
      â”‚
      â”œâ”€â–º User uploads 3 more â†’ Queue Quick LoRA (background)
      â”‚
      â””â”€â–º NOTIFICATION: "Your avatar quality has improved!" (when ready)
          â””â”€â–º System auto-switches to better model

BACKGROUND TRAINING QUEUE:

When user uploads photos, system queues LoRA training in background:

```python
async def onboard_user(user_id: str, photos: List[Path]):
    # Always available immediately via InstantID
    await cache_instantid_embedding(user_id, photos[0])
    
    # Queue LoRA training based on image count
    if len(photos) >= 4:
        await training_queue.add(
            user_id=user_id,
            photos=photos,
            epochs=15 if len(photos) < 10 else 30 if len(photos) < 15 else 50,
            on_complete=lambda: upgrade_user_tier(user_id),
        )
```

BUSINESS MODEL ALIGNMENT:

Users self-select quality tier by effort invested:
  - Casual user (1 photo): Free preview, may convert to paid
  - Engaged user (4 photos): Willing to pay for better quality
  - Power user (20 photos): Wants premium, willing to pay premium price

This creates natural upsell path without aggressive sales tactics.

IMPLEMENTATION STATUS:
  - InstantID/PuLID integration: NOT YET IMPLEMENTED (Phase 2)
  - LoRA training pipeline: VALIDATED (musubi-tuner on RunPod)
  - Background queue system: NOT YET IMPLEMENTED
  - Tier auto-switching: NOT YET IMPLEMENTED

3A.3 THE REDUNDANT IDENTITY STACK (Defense in Depth)

Research (Dec 2024) shows that combining multiple identity methods provides
stronger consistency than any single method alone. This is our "defense in
depth" strategy for identity preservation.

LAYER 1 - Model Bias (LoRA):
  - Weights biased toward character during training
  - Active during ALL denoising steps of video generation
  - Provides "gravitational pull" toward learned identity
  - Quality contribution: ~15% improvement over baseline
  - Status: Supported but optional (requires pre-training)

LAYER 2 - Per-Frame Anchoring (IP-Adapter):
  - Injects reference image embeddings into attention layers
  - Active during: Hero Frame, Bridge Frame, AND I2V generation
  - Provides "hard lock" forcing output toward reference
  - Quality contribution: ~25% improvement over baseline
  - Status: ACTIVE in current pipeline (hero/bridge frames)
  - Gap: NOT YET active during I2V generation (see 3A.5)

LAYER 3 - Structural Preservation (ControlNet):
  - Pose and depth conditioning from previous frame
  - Preserves body position, scene layout, spatial relationships
  - Prevents identity drift via pose/position changes
  - Quality contribution: ~10% improvement for continuity
  - Status: ACTIVE in Bridge Engine (pose + depth extraction)

LAYER 4 - Post-Processing Backup (Face Enhancement):
  - GFPGAN or CodeFormer as safety net
  - Corrects residual drift not caught by Layers 1-3
  - Runs after video generation, before final output
  - Quality contribution: ~3-5% recovery of drifted frames
  - Status: NOT YET IMPLEMENTED (Phase 2)

LAYER 5 - QA Verification (ArcFace):
  - Embedding comparison against Bible references
  - Catches any failures from Layers 1-4
  - Triggers re-roll if similarity threshold not met
  - Threshold: 0.70 (production), 0.50 (development)
  - Status: ACTIVE in current pipeline

COMBINED EFFECT:
  - Layers 2+3+5 alone (current): ~97% identity consistency
  - Adding Layer 1 (LoRA): Expected ~99% consistency
  - Adding Layer 4 (face enhancement): Expected ~99.5% consistency

IMPLEMENTATION PRIORITY:
  - MVP (Current): Layers 2, 3, 5 --> 97% accuracy (VALIDATED)
  - Post-MVP: Add Layer 1 (LoRA during I2V) --> 99% target
  - Production: Add Layer 4 (face enhancement) --> 99.5% target

--------------------------------------------------------------------------------
3A.4 STAND-IN FOR WAN (Specialized Identity Branch)
--------------------------------------------------------------------------------

Stand-In is a Tencent/WeChat research project (paper: Aug 2025) that adds
identity preservation directly to Wan video models with minimal overhead.

Technical Approach:
  - Plug-in identity branch (~1% additional parameters)
  - Conditional image encoder for reference face
  - Restricted self-attention to merge reference without full fine-tune
  - Native integration with Wan 2.1/2.2 architecture

Advantages over IP-Adapter:
  - Native integration (not adapter bolted on after the fact)
  - Lower VRAM overhead (~1% vs ~10% for full IP-Adapter)
  - SOTA face similarity in academic benchmarks
  - Designed specifically for video, not adapted from image models

ComfyUI Support:
  - Custom node: "Stand-In Preprocessor" for Wan
  - Repository: github.com (search "Stand-In ComfyUI")
  - Status: In development, early previews available

Integration Plan:
  - Phase 1: Install and test alongside IP-Adapter (compare quality)
  - Phase 2: If superior, replace IP-Adapter in Wan-specific workflows
  - Phase 3: Keep IP-Adapter for non-Wan models (Hunyuan, Mochi, SDXL)

Decision Criteria for Switching:
  - Stand-In must achieve >= 0.95 ArcFace similarity (vs IP-Adapter ~0.97)
  - VRAM usage must be <= IP-Adapter
  - Generation speed must be >= IP-Adapter
  - Must work with existing Bridge Engine workflow pattern

--------------------------------------------------------------------------------
3A.5 IP-ADAPTER DURING I2V GENERATION (Implementation Gap)
--------------------------------------------------------------------------------

CURRENT STATE (Gap Identified Dec 2024):
  - IP-Adapter is used in Hero Frame generation (SDXL) --> WORKING
  - IP-Adapter is used in Bridge Frame generation (SDXL) --> WORKING
  - IP-Adapter is NOT used during Wan I2V video generation --> GAP

WHY THIS MATTERS:
  Research shows that IP-Adapter injection into the video model's UNet
  provides per-frame identity anchoring during video generation, not just
  at the init_frame. Without this, identity can drift DURING the shot.

  Current flow (suboptimal):
    Hero/Bridge Frame (IP-Adapter locked) --> Wan I2V (NO IP-Adapter)
    Frame 1: 100% identity match
    Frame 12: ~97% identity match (slight drift within shot)

  Optimal flow:
    Hero/Bridge Frame (IP-Adapter locked) --> Wan I2V (WITH IP-Adapter)
    Frame 1: 100% identity match
    Frame 12: ~99% identity match (IP-Adapter prevents drift)

TECHNICAL SOLUTION:
  The ComfyUI-IPAdapter-WAN extension enables IP-Adapter injection into
  Wan's video UNet attention layers. This is NOT the same as SDXL IP-Adapter.

  Required workflow: pass1_img2vid_ipadapter.json
    - Loads Wan I2V model
    - Loads IP-Adapter-WAN extension
    - Injects face reference embeddings during video denoising
    - Weight: 0.5-0.7 (balance identity lock vs prompt adherence)

IMPLEMENTATION CHECKLIST:
  [ ] Install ComfyUI-IPAdapter-WAN on RunPod
  [ ] Create pass1_img2vid_ipadapter.json workflow
  [ ] Update pass1_generator.py to prefer this workflow when available
  [ ] Add fallback to pass1_img2vid.json if extension unavailable
  [ ] Validate with ArcFace: target >= 0.99 within-shot consistency

3B. The Bridge Engine (The Handshake Layer)

================================================================================
 CRITICAL SYSTEM COMPONENT - DO NOT BYPASS
================================================================================

The Bridge Engine is the CORE VALUE PROPOSITION of Continuum. It is what separates
us from "random clip generators." Without it, we have no product. This section
documents in detail what it is, when it's needed, why it's needed, and why it
must NEVER be bypassed or simplified away.

--------------------------------------------------------------------------------
3B.1 WHAT IS A BRIDGE FRAME?
--------------------------------------------------------------------------------

A Bridge Frame is a synthetically generated image that serves as the "perfect
first frame" for any new video generation. It is created BEFORE the video model
runs, and is injected as the `init_image` to force the video to start from a
known, identity-locked state.

Technical Definition:
- Input: Last frame of previous video segment (captures pose, expression, scene state)
- Process: ControlNet (OpenPose) extracts pose + IP-Adapter re-injects canonical identity
- Output: Single high-fidelity frame with BOTH pose continuity AND identity lock
- Usage: Fed to Wan I2V as init_image, video continues from this frame

The Bridge Frame is generated using SDXL (Stable Diffusion XL) because:
1. SDXL has mature, battle-tested ControlNet + IP-Adapter support
2. Wan 2.1 is a VIDEO model without native IP-Adapter for single images
   NOTE: The ComfyUI-IPAdapter-WAN extension DOES enable IP-Adapter injection
   into Wan's video UNet for multi-frame generation (see Section 3A.5).
   However, for single-frame Bridge generation, SDXL remains preferred.
3. One frame of SDXL "style" is immediately overwritten by Wan's video generation
4. The identity lock is what matters, not the style of that single frame

Workflow: `bridge_full.json` (ControlNet Pose + ControlNet Depth + IP-Adapter)

--------------------------------------------------------------------------------
3B.2 WHEN IS A BRIDGE FRAME NEEDED?
--------------------------------------------------------------------------------

A Bridge Frame is required for EVERY video generation restart. Not just camera
angle changes. Not just shot boundaries. EVERY restart.

 SCENARIO  BRIDGE NEEDED?  WHY 
 Shot A --> Shot B (camera change)  [OK] YES  New generation 
 Chunk 1 --> Chunk 2 (same shot)  [OK] YES  12s max, restart 
 Repair/patch a bad frame  [OK] YES  New generation 
 Focus change (Person A --> B)  [OK] YES  Different subject 
 Scene transition  [OK] YES  New generation 
 Re-roll after audit failure  [OK] YES  New generation 
 Continue from checkpoint  [OK] YES  New generation 
 Within a single 12s chunk  [X] NO  Continuous gen 
 Frame interpolation (RIFE)  [X] NO  Not generation 
 Pass 2 refinement (vid2vid)  [X] NO  Existing video 

Rule of Thumb: If you are calling the video model to generate NEW frames,
you need a Bridge Frame (unless it's the very first shot of the film).

--------------------------------------------------------------------------------
3B.3 WHY IS THE BRIDGE FRAME NEEDED? (THE DRIFT PROBLEM)
--------------------------------------------------------------------------------

Video models have NO MEMORY between generation calls. Each call starts fresh.
Without intervention, identity drifts with each restart:

WITHOUT BRIDGE FRAMES (drift accumulates exponentially):
 Shot 1 --> Shot 2 --> Shot 3 --> Shot 4 --> Shot 5 
 100% 98% 94% 88% 80% 
 Alice Alice? Alice?? Who??? Different 
 person 

Each generation "forgets" the previous one. Small errors compound:
- 2% drift per shot x 5 shots = 10% total drift (optimistic)
- In practice, drift is non-linear and accelerates
- By shot 5, the character is unrecognizable

WITH BRIDGE FRAMES (identity re-anchored every cut):
 Shot 1 --> BRIDGE --> Shot 2 --> BRIDGE --> Shot 3 --> BRIDGE --> Shot 4 --> ... 
 100% ^100% 100% ^100% 100% ^100% 100% 
 Alice  Alice  Alice  Alice 
    
 Re-anchor from Re-anchor from Re-anchor from 
 Bible refs Bible refs Bible refs 

The Bridge Frame re-injects the CANONICAL identity from the Consistency Dictionary
(the "Bible" references) at every cut. Drift is reset to 0% each time.

This is why Continuum can generate 5-minute films with consistent characters,
while competitors can only generate 4-second clips and pray.

--------------------------------------------------------------------------------
3B.4 WHY THE BRIDGE FRAME MUST NEVER BE BYPASSED
--------------------------------------------------------------------------------

 HISTORICAL NOTE: During development, there were multiple attempts to
"simplify" the pipeline by bypassing the Bridge Engine and passing raw frames
directly to Wan I2V. This is ALWAYS wrong. Here's why:

BYPASS ATTEMPT 1: "Raw frame is good enough"
- Reasoning: "The last frame has the right pose, just use it directly"
- Why it fails: Wan I2V continues the VIDEO, not the IDENTITY. Each generation
 drifts slightly from the input. Without IP-Adapter re-anchoring, errors compound.

BYPASS ATTEMPT 2: "LoRA handles identity"
- Reasoning: "We have character LoRAs, they'll maintain identity"
- Why it fails: LoRA biases the generation but doesn't LOCK it. The model can
 still drift within the LoRA's influence range. IP-Adapter provides hard anchor.

BYPASS ATTEMPT 3: "Bridge adds latency, skip for speed"
- Reasoning: "SDXL adds 5-10 seconds per cut, skip it for faster iteration"
- Why it fails: You're iterating on a BROKEN pipeline. Fast garbage is still garbage.
 Identity drift will appear in any multi-shot test.

BYPASS ATTEMPT 4: "Same model family is better"
- Reasoning: "SDXL is different from Wan, style mismatch will occur"
- Why it fails: The Bridge Frame is ONE frame. Wan immediately overwrites the style
 in frame 2+. The identity lock survives, the style doesn't matter.

THE RULE: If you're tempted to bypass the Bridge Engine, you're solving the
wrong problem. Fix whatever is making you want to bypass it instead.

--------------------------------------------------------------------------------
3B.5 TECHNICAL IMPLEMENTATION
--------------------------------------------------------------------------------

Current Implementation (MVP - Single Frame):

Step 1 - CAPTURE: Extract last frame from previous video segment
  Tool: FFmpeg (extract_last_frame)
  Output: PNG image with pose, expression, scene state

Step 2 - EXTRACT POSE: Run OpenPose on captured frame
  Tool: ComfyUI ControlNet Preprocessor
  Output: Pose keypoints image

Step 3 - EXTRACT DEPTH (optional): Run depth estimation
  Tool: ComfyUI Depth Anything / MiDaS
  Output: Depth map image

Step 4 - GENERATE BRIDGE FRAME: SDXL with conditioning
  Workflow: bridge_full.json
  Inputs:
 - ControlNet Pose: Preserves body position, expression
 - ControlNet Depth: Preserves spatial relationships (optional)
 - IP-Adapter: Re-injects canonical identity from Bible refs
 - LoRA: Character-specific identity boost (if available)
 - Prompt: Target shot description
  Output: Identity-locked first frame for next shot

Step 5 - INJECT: Pass bridge frame to Wan I2V as init_image
  Workflow: pass1_img2vid.json or pass1_img2vid_lora.json
  Result: Video continues from identity-locked starting point

Workflow Files:
- bridge_full.json: ControlNet Pose + Depth + IP-Adapter (RECOMMENDED)
- bridge_pose_only.json: ControlNet Pose + IP-Adapter (fallback)
- bridge_ipadapter.json: IP-Adapter only (minimal fallback)
- bridge_basic.json: [X] BROKEN - Do not use (no ControlNet, no IP-Adapter)

--------------------------------------------------------------------------------
3B.6 FUTURE ENHANCEMENT: MULTI-FRAME BRIDGE SEQUENCE
--------------------------------------------------------------------------------

Status: NOT YET IMPLEMENTED (Phase 2+)

Problem: Single Bridge Frame can cause "motion freeze" artifact
- Character mid-stride in Shot A's last frame
- Bridge Frame captures same pose
- Shot B starts with character frozen in that pose
- Looks unnatural for 0.5-1 second before motion resumes

Solution: Generate 3-5 frame bridge SEQUENCE instead of single frame

Proposed Implementation:
1. Generate Bridge Frame (identity-locked target)
2. Use RIFE to interpolate 3-5 frames between:
 - Last frame of Shot A (source pose)
 - Bridge Frame (target pose with locked identity)
3. Inject frame sequence as init_latent to Wan I2V
4. Video starts with smooth motion transition

Trade-offs:
- GPU Cost: ~3x per cut (RIFE interpolation + more init frames)
- Quality: Significantly smoother motion handoff
- Complexity: Requires init_latent injection (not just init_image)

Decision: Test single-frame MVP with real content first. Upgrade to multi-frame
only if users report visible "motion freeze" issues. Do not pre-optimize.

--------------------------------------------------------------------------------
3B.7 DEGRADATION LADDER
--------------------------------------------------------------------------------

If components fail, the Bridge Engine degrades gracefully:

TIER 1 (Best Quality):
- ControlNet Pose + ControlNet Depth + IP-Adapter + LoRA
- Workflow: bridge_full.json
- Result: Perfect pose AND identity lock

TIER 2 (Good Quality):
- ControlNet Pose + IP-Adapter + LoRA
- Workflow: bridge_pose_only.json
- Result: Pose preserved, identity locked, no depth

TIER 3 (Acceptable Quality):
- IP-Adapter + LoRA only
- Workflow: bridge_ipadapter.json
- Result: Identity locked, pose may shift slightly

TIER 4 (Emergency Fallback):
- Raw last frame --> Wan I2V
- Workflow: pass1_img2vid.json (no bridge)
- Result: DRIFT WILL OCCUR - Use only if bridge completely unavailable
- MUST log warning: "Bridge unavailable - identity drift expected"

NEVER silently fall back to Tier 4. Always warn loudly.

================================================================================
END OF BRIDGE ENGINE SPECIFICATION
================================================================================

3C. The Physics & Layout Engine (World Logic Lock)

Goal: Prevent hallucinations and physically impossible layouts. Technology: ControlNet (Depth / OpenPose / Layout), region prompts. Tools: ControlNet, ComfyUI layout nodes, VideoDirectorGPT-style layouts.
System Fit:
Step 1: The "Cardboard Fort" (Pre-Viz):
Before rendering pixels, the Director Agent runs a simple Python script (Blender API or similar) to place primitive shapes (capsules, cubes) in a 3D void representing the scene.
It positions a "Virtual Camera" matching the Director's shot request (e.g., "High Angle").
It renders a "Depth Map" or "Canny Edge Map" of this ugly blockout.
Step 2: The ControlNet Anchor:
This Depth Map is fed into ControlNet alongside the prompt.
Result: The Video Model is forced to paint "Alice" exactly where the capsule is and "The Mug" exactly where the cylinder is.
Step 3: Event-Driven State Updates (The Shatter Logic):
Dynamic Events: If the script calls for an action (e.g., "Shatter Mirror"), the Director temporarily lowers ControlNet strength to allow the model's physics training to take over for the animation.
State Commit: After the shot, the Director flags the object "Mirror" as State: Broken in the Scene Graph.
Future Consistency: For all future shots in this scene, the 3D Blockout will render the mirror as "shards on the floor" (or simply remove the 'mirror' object and add 'debris' objects), ensuring the mess persists even if the camera looks away and comes back.

3D. The Multi-Hero Engine (Multi-Character Scenes)

Goal: Multiple characters in one shot without identity merging. Technology: Regional prompting / attention masking / segmented conditioning. Tools: ComfyUI Regional Prompter, segmentation nodes, masks.
System Fit:
Director defines regions:
Region A (Left): Alice
Region B (Right): Bob
ComfyUI workflow:
Applies Alice LoRA only in Region A
Bob LoRA only in Region B
Avoids identity bleed and blob fusion.

3E-1. The World Engine (Environment Lock)

Goal: The kitchen/forest/city stays visually consistent across time and scenes. Technology: IP-Adapter, reference image injection, environment keyframes. Tools: ComfyUI IPAdapter Plus, panorama refs.
System Fit:
Pre-generate location panoramas / key views (front / side / wide).
Store them as canonical environment assets.
For each shot in that location:
Feed the correct environment ref into IP-Adapter / conditioning.
This "locks" walls, windows, big objects.

Section 3E-2 (World Engine) Addition:
markdownProgressive Location Lock (Hybrid IP-Adapter + Auto-LoRA):

Similar to character identity lock (Section 3A), locations can be progressively
enhanced:

Tier 1 -- Instant Start (IP-Adapter):
 - Generate 3-5 reference views of location (panorama, key angles)
 - System uses these as IP-Adapter conditioning
 - Quality: ~70% location consistency (good for drafts)
 - Limitation: Works best when camera angle matches reference

Tier 2 -- Background Enhancement (Auto-LoRA):
 - System generates 15-25 augmented views from initial references
 - Auto-trains LoRA on location image set
 - Training time: 30-45 min on A100
 - Quality: ~90% location consistency from ANY angle

LoRA Stacking:
 - Character LoRA (weight 0.7) + Location LoRA (weight 0.5) = combined consistency
 - Both can be active simultaneously without conflict
 - Total weight should stay under ~1.2 for quality

3F. Two-Pass Rendering Pipeline (Structure -> Refinement)

This is the critical change to avoid integration hell.
Pass 1 - Structural Long-Form Generation (Consistency Maximization)
Goal: Produce a 2-5 minute narrative by maximizing the length of every continuous shot using StreamingT2V, while employing "Smart Cuts" as a fail-safe to ensure identity never drifts.
Technologies:
Base model: Wan 2.x / HunyuanVideo / Mochi (pluggable).
StreamingT2V-style chunking: Overlapping windows, sliding context for maximum duration.
CoNo (Consistency Noise): Applied at chunk boundaries to smoothen transitions within the shot.
The Bridge Engine (New): Generates synthetic "First Frames" when a cinematic cut is required.
Implementation: As a ComfyUI workflow:
Nodes: model -> LoRA -> IP-Adapter -> ControlNet -> StreamingT2V -> CoNo.
Director Logic (The Pacer):
Step 1 (The Push): Calls the workflow to generate the shot, aiming for maximum duration (30s+).
Step 2 (The Monitor): Monitors for "Drift Points." If drift is detected (or pacing requires it), it halts generation
Step 3 (The State Audit): Before generating the next shot, the Director compares the End State of the current shot against the Expected State.
Example: "Did the toothbrush fall?" -> Yes. -> Update Scene Graph coordinates for 'Toothbrush'.
Why: This ensures that when we generate the "Bridge Frame" for the next shot, we are seeding it with the correct "New Truth" (toothbrush on floor), preventing the object from teleporting back to the counter.
Step 4 (The Bridge): It generates a Bridge Frame (preserving the end-state emotion/props) and triggers the next shot using this frame as the init_image to restart with 100% fidelity.
Result: A video that flows continuously for minutes, composed of high-fidelity segments stitched seamlessly by audio and narrative logic.
Pass 2 -- Refinement & Flicker Reduction
Goal: Take the structural pass video and improve visual quality & temporal stability without breaking continuity.
Technologies:
Vid2vid / FreeLong++-style temporal consistency enhancements.
Optional temporal super-resolution / denoisers.
Optional advanced stuff (TiARA-like attention tweaks) for later versions.
Implementation: As a separate ComfyUI workflow:
Input: video from Pass 1.
Nodes: vid2vid model / FreeLong++ plugin / temporal denoiser.
Output: a cleaner, more stable, sharper version of the same video.
We do not stack StreamingT2V + FreeLong++ + TiARA + CoNo in one infer loop. We run a cascaded 2-pass system to stay sane and debuggable.

3G. The Frame-Rate & Cost Optimizer (RIFE Layer)

Goal: Save GPU cost while delivering a cinematic 24-30 fps video. Technology: Frame interpolation via RIFE (Real-Time Intermediate Flow Estimation) or similar.
System Fit:
Render main pipeline at 12 fps.
Use RIFE in a final pass to:
Interpolate to 24 fps (or 30).
Smooth out small jitters.
This halves direct generation cost while maintaining perceived smoothness.
Pragmatic Note (CoNo / FreeLong++ Availability):
CoNo and FreeLong++ are new research. They may not exist as "ready-made" ComfyUI nodes or stable plug-ins at any given moment. The architecture treats them as pluggable upgrades, not hard dependencies.
If CoNo is unavailable:
Use standard latent blending / crossfade at chunk boundaries in ComfyUI (blend the last latent/frame of Chunk A with the first of Chunk B).
This covers ~80% of what CoNo is trying to do: smoothing seams and avoiding hard visual jumps.
If FreeLong++-style refinement is unavailable:
Use a simpler vid2vid temporal denoiser or generic temporal super-resolution pass in Pass 2.
The system is designed so that advanced temporal methods (CoNo, FreeLong++, TiARA-like attention tweaks) are optional upgrades. The core remains: StreamingT2V + overlap + latent blending for structure, then a separate refinement pass.
This makes it clear you're not hard-wiring your product to research code that may not be usable yet.

3H. The Voice Engine (Audio & Lip Sync)

Goal: Avoid making a "silent film engine." Generate dialogue + lip-synced faces so characters actually talk.
Inputs: Script dialogue from the Director Agent:
Per scene / shot
Per character
With rough timing (e.g. which lines belong in which shot/chunk).
Generation (Voices): TTS Providers:
ElevenLabs, OpenAI TTS, or similar high-quality, emotional TTS.
System Fit: Director Agent outputs a Dialogue Map:
[(character, line, shot_id, chunk_range, target_voice_id, audio_path)]
Voice Engine:
Generates per-line audio files (e.g. WAV/OGG).
Stores them with stable IDs for each shot/chunk.
Lip Sync (Mouth Animation): Technologies:
Musetalk, Wav2Lip, or equivalent audio-driven lip-sync.
Prefer ComfyUI nodes if available, otherwise run as a separate Python tool.
Pipeline Placement: Run after Pass 2 (Refinement) and before RIFE:
Structural video (Pass 1)
Refinement (Pass 2)
Lip Sync pass: take refined video segments + dialogue audio and adjust mouths/faces.
RIFE interpolation to final fps.
System Fit: For each speaking shot:
Align shot video with the correct audio clip(s).
Run lip-sync model to modify the face region.
Output a new "speech-corrected" video segment.
Why this order (after Pass 2, before RIFE):
Lip-sync needs the final visual face details (from refinement) to work well.
RIFE's interpolation then smooths any minor frame-level inconsistencies introduced by lip-sync.
Result: Your engine is not just visually consistent -- it's a talking world. Characters have stable faces, stable environments, and mouths that match what they say.

3I. The Sonic Engine (Atmosphere & SFX)

Goal: Transform "Silent Movies" into immersive cinema. Ensure the audio environment (room tone, foley, score) is as consistent as the visual world. Technology: AudioLDM-2 / Stable Audio Open (for ambience), MusicGen (for score), CLAP (for audio-text alignment). Tools: ComfyUI Audio nodes, custom Python wrapper for timestamp injection.
System Fit:
The Sonic RAG (Consistency Layer): Just as we lock visual assets, we lock audio assets.
Ambience Lock: The Director Agent assigns a specific "Room Tone Seed" to every location in the Scene Graph.
Result: The "Cyberpunk Kitchen" has the exact same refrigerator hum and neon buzz in Minute 1 and Minute 10, regardless of the camera angle.
Score Theme Lock: We generate a "Leitmotif" (musical theme) for key characters and store the seed/prompt in the Consistency Dictionary.
The Layered Generation Pipeline:
Layer 1: The Bed (Ambience):
Director sends location tags ("Rain, Night, City Traffic") to the Cloud Audio Model.
Generates a looping 30-60s "bed" track that runs underneath the entire scene.
Layer 2: The Foley (Event-Driven SFX):
The Director Agent parses the script for Action Events.
Input: "Alice drops the red mug." -> Timestamp: 00:04.
Action: Triggers a short discrete audio generation ("Ceramic smash on tile") and layers it at the exact timestamp in the composition.
Layer 3: The Score (Dynamic Pacing):
Synced to the Stability Monitor (The Pacer). When the visual mood shifts or a scene transition occurs, the music prompt evolves (e.g., from "Tension" to "Release") without a hard cut.
Brain vs. Muscle Implementation:
MacBook Brain: Generates the Audio Manifest JSON (listing timestamps, prompts, and seeds). It never touches the heavy .wav files.
Cloud Muscle: Renders the audio tracks in parallel with the video pixels, adding negligible time to the job since audio inference is computationally cheap compared to video diffusion.
Phased Sonic Engine Rollout:
MVP (Phase 1) -- Essential for VC Demo:
TTS Dialogue: [YES] ElevenLabs / OpenAI TTS API
Lip Sync: [YES] Wav2Lip or Musetalk
Basic Ambience: [YES] One looping bed track per scene (AudioLDM-2)
Audio Ducking: [YES] Simple -12dB attenuation during dialogue
Music: Manual (user uploads or selects from stock library)
Phase 2 -- Enhanced Audio:
Per-shot ambience generation with location-locked seeds
Basic foley triggers (footsteps, doors, impacts)
MusicGen integration for generated score
Phase 3 -- Full Sonic Engine:
Leitmotif system (character-specific musical themes)
Advanced spatial audio (panning, depth)
Full foley library with event-driven triggers
Rationale: Audio is non-negotiable for VC funding ("silent films don't demo well"), but full Sonic Engine is complex. MVP scope delivers talking characters in immersive audio without over-engineering.

3J. The Consistency Audit Engine (VideoLLM Layer)

Role: The "Continuity Supervisor." Instead of relying on simple frame sampling, this engine watches generated clips to verify character identity, prop existence, and physics consistency before the user ever sees them.
Technology (The "Stunt Double" Strategy): We use a modular backend that allows us to start with available open-source tools today and hot-swap to state-of-the-art models tomorrow without rewriting the pipeline.
Phase 1 (Immediate): VideoLLaMA 2 (7B / 13B)
Status: Open Source & Available Now.
Capability: Strong Visual QA. It can answer "Is Alice holding the red mug?" or "Did the scene change from day to night?"
Limit: Can identify what is happening, but struggles with exact pixel-level grounding (bounding boxes).
Phase 2 (Target Upgrade): Vidi2 (ByteDance)
Status: Architecture public; Weights "Coming Soon."
Capability: Spatio-Temporal Grounding. It can draw a bounding box around the "Red Mug" for the entire clip.
Trigger: We swap to this engine immediately upon weight release to enable "physics teleportation" checks (e.g., verifying an object didn't jump 500 pixels in one frame).
System Fit: Input: 1. The generated MP4 chunk (e.g., shot_03.mp4). 2. The Scene Graph Context (JSON) from the Director Agent.
Process (The Audit Loop):

**MVP Checks (Phase 1) -- Hybrid CV + Embedding:**

Identity Layer (ArcFace):
* Compare first frame embedding vs Bible reference: threshold < 0.70 = FAIL
* Compare first frame vs last frame of shot: threshold < 0.70 = FAIL

Physics Layer (CV-Based):
* Object Permanence: YOLOv8 + ByteTrack tracking
 - FLAG: Object missing >3 frames without exit
* Flicker Detection: RAFT optical flow analysis
 - FLAG: High pixel change with low motion (>5% frame area)
* Gravity Check: Vertical position heuristic
 - FLAG: Unsupported object not falling
* Collision Check: Bounding box overlap analysis
 - FLAG: Solid objects overlapping >50%

Visual Consistency (CLIP):
* Compare first vs last frame embedding: threshold < 0.85 = FLAG for review

**Phase 2 Checks (VideoLLM + Advanced CV):**
* Cause-effect verification via Vidi2/VideoLLaMA
* Action recognition (SlowFast) for event detection
* Pose physics (MediaPipe) for character biomechanics
* Advanced grounding via spatio-temporal bounding boxes

Action:
Pass: Chunk approved -> sent to Stitcher
Fail: Chunk rejected -> log failure reason -> auto re-roll (max 3 attempts)
Max Failures Exceeded: Surface to user with failure reason and options
Why this matters:
Automated Quality Control: We catch "hallucinations" (disappearing objects, morphing faces) before the user pays for the final render.
Systems Moat: Most competitors return whatever the model spits out. We differentiate by guaranteeing narrative consistency through this automated audit layer.
Future-Proof: The "Stunt Double" abstraction (VideoAuditor class) means our codebase remains stable even as underlying VideoLLMs evolve rapidly.

3K. The Post-Production Engine (Auto-Edit & Color)

Goal: Deliver a "Final Cut" ready for distribution, not a "Rough Cut" that requires Adobe Premiere. Eliminate the "Assembly Gap" where raw diffusion clips look disjointed. Technology: FFmpeg scripting, OpenCV (Histogram Matching), PyDub (Audio Mixing). Role: The "Editor" and "Colorist" Agents working in tandem.
System Fit:
Auto-Color Normalization (The Colorist):
The Problem: Raw diffusion clips often suffer from "Color Drift" (Shot A is cool blue, Shot B is warm yellow) even with consistent prompts.
The Fix: We implement a Global Histogram Match before stitching.
Logic: The engine analyzes the "Master Shot" (defined by the Director Agent) and mathematically forces the color palettes of all subsequent clips in that scene to align with the Master histogram. This eliminates the "checkerboard" effect of AI video.
Smart Audio Mixing (The Sound Engineer):
The Problem: Generated music often drowns out generated dialogue.
The Fix: Automated Audio Ducking.
Logic: The system reads the Dialogue Map (from Section 3H) to identify exactly when characters speak. It automatically attenuates (lowers) the volume of the Score & Ambience (from Section 3I) by -15dB during those timestamps, ensuring clear vocals without manual fader riding.
The Project State (The Software Moat):
Definition: We do not just export a "dumb" MP4; we maintain a non-destructive Project State File.
Value: If the user swaps "Shot 3" for a new angle, the system automatically re-calculates the Color Grading and Audio Ducking for the new clip in seconds.

3L. Error Recovery & Graceful Degradation (NEW)

Goal: Ensure the system fails gracefully and never enters infinite loops or loses work.
Max Re-Roll Policy:
Per Chunk: Maximum 3 re-roll attempts with varied seeds/CFG
Per Shot: Maximum 5 total chunk failures before escalating
On Max Failures:
Surface error to user with failure reason
Offer options: skip chunk, manual override, adjust constraints
Never silently retry indefinitely
Job Checkpointing:
Save state after each chunk completes successfully
Checkpoint data: chunk_id, rendered_path, metadata, timestamp, QA_result
On crash/disconnect: Resume from last checkpoint, not from start
Storage: Local JSON + S3 backup for redundancy
RAG Fallback:
Primary: Pinecone for Visual RAG
Fallback: Local JSON asset registry (pre-synced)
Trigger: If Pinecone unavailable for >30 seconds, switch to local
Graceful Degradation Ladder:
Missing LoRA -> Fall back to IP-Adapter (80% quality vs 95%)
Missing environment ref -> Use prompt-only generation (less consistent)
Audio API failure -> Continue with silent video, flag for retry
LLM API failure -> Use cached scene graph if available, or pause job
Always: Log degradation events for debugging and user notification
Why this matters:
Production systems must handle failures gracefully
Users should never lose hours of render work to a crash
Degraded output is better than no output (user can decide to retry)

3M. Quality Assurance Pipeline (NEW)

**Post-Render QA Checks:**

| Check Type | Method | Threshold/Trigger | Speed | Action on Fail |
|-------------------|--------------------------|----------------------|-------------|-------------------|
| Identity Drift | ArcFace embedding | < 0.70 similarity | ~10ms/frame | Auto re-roll |
| (vs Bible) | cosine similarity | | | (max 3 attempts) |
| Shot Drift | ArcFace first vs last | < 0.70 similarity | ~10ms/frame | Auto re-roll |
| Object Permanence | YOLOv8 + ByteTrack | Missing >3 frames | ~30ms/frame | Auto re-roll |
| Flicker | RAFT optical flow | >5% frame affected | ~50ms/pair | Auto re-roll |
| Gravity Violation | Y-position heuristic | No downward motion | ~1ms/frame | Auto re-roll |
| Passthrough | Bbox overlap >50% | Solid objects only | ~1ms/frame | Auto re-roll |
| Scene Consistency | CLIP embedding | < 0.85 similarity | ~20ms/frame | Flag for review |
| Prop Presence | VideoLLM prompt (V2) | Pass/Fail | ~5s/clip | Flag for review |

**Tech Stack (All Open-Source, Zero-Shot):**

| Component | Tool | Source |
|-------------------|-----------------------------|---------------------------------|
| Object Detection | YOLOv8 | ultralytics/ultralytics (GitHub)|
| Object Tracking | ByteTrack | ifzhang/ByteTrack (GitHub) |
| Optical Flow | RAFT | princeton-vl/RAFT (GitHub) |
| Pose Estimation | MediaPipe | Google (pip install mediapipe) |
| Action Recognition| SlowFast (V2) | facebookresearch/SlowFast |
| Video QA (V2) | Vidi2 | ByteDance (HuggingFace) |

**Real-Time Drift Detection: DEFERRED to Phase 2**

Rationale:
* Current models (Wan 2.1, HunyuanVideo) stable for 12-15 seconds
* Cinematic Pacer cuts at 12s (within stable window)
* Post-render CV checks are fast enough (<30s per 10s clip)
* Phase 2 upgrade: Vidi2 grounding for advanced physics/spatial checks

3N. Model Upgrade Path (Future Identity Engines)

As video models evolve rapidly, we maintain a pluggable architecture that can
adopt new identity preservation techniques without rewriting orchestration code.

--------------------------------------------------------------------------------
3N.1 CURRENT STATE (Dec 2024 - Validated)
--------------------------------------------------------------------------------

Stack: Wan 2.1 + SDXL Bridge + IP-Adapter + ControlNet
Result: ~97% identity consistency (ArcFace validated)
Limitations:
  - IP-Adapter not active during I2V (only in hero/bridge frames)
  - No LoRA in current test pipeline
  - No face enhancement post-processing

--------------------------------------------------------------------------------
3N.2 NEAR-TERM UPGRADES (Q1 2025)
--------------------------------------------------------------------------------

UPGRADE 1: IP-Adapter During I2V
  - Tool: ComfyUI-IPAdapter-WAN extension
  - Workflow: pass1_img2vid_ipadapter.json
  - Expected improvement: 97% --> 99% identity consistency
  - Effort: Low (workflow creation + node installation)

UPGRADE 2: Stand-In for Wan
  - Tool: Stand-In Preprocessor node (Tencent research)
  - What: Native identity branch for Wan (~1% params)
  - Expected improvement: Comparable or better than IP-Adapter
  - Effort: Medium (testing, validation, workflow updates)
  - Decision: Test head-to-head with IP-Adapter, adopt if superior

UPGRADE 3: Face Enhancement Safety Net
  - Tool: GFPGAN or CodeFormer
  - What: Post-processing face correction
  - Expected improvement: Recover ~3-5% of drifted frames
  - Effort: Low (add pass after video generation)

--------------------------------------------------------------------------------
3N.3 MEDIUM-TERM UPGRADES (Q2-Q3 2025)
--------------------------------------------------------------------------------

UPGRADE 4: HunyuanCustom Integration
  - Source: Tencent open-source (mid-2025)
  - What: Multi-modal subject customization with dedicated identity enhancement
  - Claim: "Outperforms other methods in face-ID consistency"
  - Requirements: High VRAM (multi-GPU recommended)
  - Integration: New HunyuanCustomRenderer class implementing BaseRenderer
  - Decision: Evaluate when weights released, compare vs Wan + IP-Adapter

UPGRADE 5: ConsisID (Tuning-Free DiT Method)
  - Source: PKU research (CVPR 2025)
  - What: Frequency-based identity control for DiT models
  - Advantage: No fine-tuning required, works zero-shot
  - Status: Code released 2025, ComfyUI integration planned
  - Decision: Monitor for ComfyUI node availability

--------------------------------------------------------------------------------
3N.4 MODEL COMPARISON MATRIX
--------------------------------------------------------------------------------

| Model/Method      | Identity | VRAM  | Speed | ComfyUI | Status      |
|-------------------|----------|-------|-------|---------|-------------|
| Wan 2.1 + IP-Adapter | ~97%  | 24GB  | Fast  | Yes     | CURRENT     |
| Wan 2.1 + Stand-In   | ~98%? | 24GB  | Fast  | Partial | TESTING     |
| Wan 2.2 + IP-Adapter | ~97%  | 24GB  | Fast  | Yes     | AVAILABLE   |
| HunyuanVideo 1.5     | ~90%  | 48GB+ | Slow  | Yes     | AVAILABLE   |
| HunyuanCustom        | ~99%? | 48GB+ | Slow  | Yes     | EVALUATE    |
| CogVideoX 1.5        | ~85%  | 40GB  | Med   | Partial | NOT RECOMMENDED |
| Mochi-1 (Genmo)      | ~80%  | 40GB  | Fast  | Yes     | NOT RECOMMENDED |

Recommendation: Stay on Wan 2.1/2.2 + IP-Adapter for MVP. Evaluate HunyuanCustom
for "Pro Lane" when VRAM costs decrease or for premium tier users.

--------------------------------------------------------------------------------
3N.5 INTEGRATION PRINCIPLE
--------------------------------------------------------------------------------

All model upgrades plug into existing abstractions:

  class BaseRenderer(ABC):
      @abstractmethod
      def render(self, spec: RenderSpec) -> RenderResult: ...

New models implement this interface. Orchestration code unchanged.
Director Agent doesn't care if it's Wan, Hunyuan, or future models.

This is the "Vibe Coder" principle: swap engines, keep logic.

3O. Face Enhancement Pipeline (Post-Processing Safety Net)

Goal: Recover identity consistency in frames where Layers 1-3 (LoRA, IP-Adapter,
ControlNet) failed to fully prevent drift. This is the "last line of defense."

--------------------------------------------------------------------------------
3O.1 WHEN TO USE FACE ENHANCEMENT
--------------------------------------------------------------------------------

Face enhancement is NOT applied to every frame. It is triggered only when:

1. ArcFace audit detects drift (similarity < 0.85 but > 0.70)
   - Below 0.70: Re-roll the shot (too damaged to fix)
   - 0.70-0.85: Attempt face enhancement recovery
   - Above 0.85: No enhancement needed

2. User explicitly requests "enhanced identity" mode
   - Higher quality, longer processing time
   - Applies enhancement to all frames regardless of audit

3. Pro Lane output (premium tier)
   - Always apply enhancement for maximum quality
   - Users paying premium expect best possible output

--------------------------------------------------------------------------------
3O.2 TECHNICAL IMPLEMENTATION
--------------------------------------------------------------------------------

Tool Options:
  - GFPGAN: Fast, good for moderate drift (recommended for MVP)
  - CodeFormer: Higher quality, slower, better for severe drift
  - Both available as ComfyUI nodes

Workflow: post_face_enhance.json (NEW - to be created)
  Input: Video frames (extracted from chunk)
  Process:
    1. Detect faces in each frame (RetinaFace or similar)
    2. Extract face regions
    3. Run GFPGAN/CodeFormer with reference image guidance
    4. Blend enhanced face back into original frame
    5. Reassemble video
  Output: Face-corrected video chunk

Reference Guidance:
  - Feed Bible reference image to enhancement model
  - Guides restoration toward canonical identity
  - Without reference: generic face enhancement (less useful for us)

--------------------------------------------------------------------------------
3O.3 PIPELINE PLACEMENT
--------------------------------------------------------------------------------

Face enhancement runs AFTER Pass 1 video generation, BEFORE Pass 2 refinement:

  Pass 1 (Structure) --> Face Enhancement (if needed) --> Pass 2 (Refinement)

Rationale:
  - Pass 1 may introduce drift that needs correction
  - Face enhancement on raw Pass 1 output is easier than post-refinement
  - Pass 2 (vid2vid) can then smooth any artifacts from enhancement

Alternative (if enhancement introduces artifacts):
  Run after Pass 2: Pass 1 --> Pass 2 --> Face Enhancement --> RIFE

Test both approaches, adopt whichever produces better results.

--------------------------------------------------------------------------------
3O.4 IMPLEMENTATION STATUS
--------------------------------------------------------------------------------

  [ ] Install GFPGAN ComfyUI node on RunPod
  [ ] Install CodeFormer ComfyUI node on RunPod
  [ ] Create post_face_enhance.json workflow
  [ ] Add enhancement step to pass1_generator.py (conditional on audit)
  [ ] Validate: enhanced frames must score >= 0.90 ArcFace similarity
  [ ] Benchmark: processing time per frame (target < 500ms)

Priority: Phase 2 (after IP-Adapter during I2V is implemented)

================================================================================
4. SYSTEMS ARCHITECTURE DIAGRAM (PLAINTEXT)
================================================================================
SCRIPT
 |
 v
[TRUST_&_SAFETY_SENTINEL]
 1. Asset Scan: Classify uploaded images for NSFW/Gore.
 2. Script Scan: LLM checks for policy violations.
 -> IF FAIL: Reject Job immediately.
 -> IF PASS: Proceed to Director.
 |
 v
DIRECTOR_AGENT (LLM via Cloud API, orchestrated from Mac)
 - Step 1: Build SCENE_GRAPH (JSON)
 * scenes, shots, characters, locations, dialogue
 - Step 2: Query VISUAL_RAG + CONSISTENCY_MEMORY
 * character LoRAs, face refs, environment panoramas, prop assets, keyframes
 * [NEW] AUDIO_MANIFEST: Ambience seeds, Leitmotif prompts
 - Step 3: Generate LAYOUTS + SHOT_SPECS
 * regions (who stands where), camera notes, chunking plan
 - Step 4: Build DIALOGUE_MAP & SONIC_MAP
 * Dialogue: (character, line, shot_id, time_range)
 * Sonic: (ambience_tag, foley_event, score_mood, timestamp)
 |
 v
JOB_DISPATCHER (Parallel Execution)
 |
 +---> [TRACK A: VISUAL PIPELINE] -------------------------+
 | CLOUD_GPU / COMFYUI_SERVER |
 | |
 | +---------------------------------------------+ |
 | | PASS 1: STRUCTURAL LONG-FORM VIDEO | |
 | | - Base model (Wan / Hunyuan / Mochi) | |
 | | - LoRA (identity) + IP-Adapter (world) | |
 | | - ControlNet / Layout (physics) | |
 | | - Bridge Frame Injection (seamless cuts) | |
 | | - StreamingT2V Chunking | |
 | +---------------------------------------------+ |
 | | |
 | v |
 | [REVIEWER_AGENT] (Visual & Physics Audit) |
 | -> Checks Identity, Props, & Gravity |
 | -> FAIL: Trigger Re-Roll of Chunk |
 | -> PASS: Proceed to Pass 2 |
 | | |
 | v |
 | +---------------------------------------------+ |
 | | PASS 2: REFINEMENT & LIPS | |
 | | - Vid2Vid / FreeLong++ (flicker reduction) | |
 | | - Lip Sync (Musetalk) using Audio Track | |
 | | - RIFE Interpolation (12 -> 24 FPS) | |
 | +---------------------------------------------+ |
 | | |
 | v |
 | RAW_VIDEO_SEGMENTS |
 | |
 +---> [TRACK B: SONIC PIPELINE] --------------------------+
 CLOUD_AUDIO_SERVER

 +---------------------------------------------+
 | THE SONIC ENGINE |
 | - Layer 1: Ambience (AudioLDM-2) |
 | - Layer 2: Foley (Event-Triggered SFX) |
 | - Layer 3: Score (MusicGen with Leitmotifs) |
 | - Layer 4: Dialogue (TTS Generation) |
 +---------------------------------------------+
 |
 v
 RAW_AUDIO_TRACKS

 |
 v
[THE POST-PRODUCTION ENGINE]
 - Auto-Color Normalization (Histogram Match to Master Shot)
 - Smart Audio Ducking (Lower score volume when Dialogue plays)
 - Final Assembly (Stitch Video + Audio)
 |
 v
FINAL_CINEMATIC_VIDEO

Optional: Premium API lane (Veo/Sora/etc.) can plug into "PASS 1: STRUCTURAL VIDEO" box as an alternative renderer, but always behind a uniform Renderer interface.
================================================================================
5a. THE OPERATOR WORKFLOW (UX Strategy)
================================================================================
How the Human User interacts with the "Neuro-Symbolic" Engine.
PHASE I: PRE-PRODUCTION (The "Logic & Blockout" Layer)
Goal: Validate the story and pacing for $0 before spinning up the H100s.
STEP 1: INGESTION & LOGIC CHECK
User Input: Uploads Full Script (PDF) + Asset Library (Voice Audio, Reference Photos).
Director Agent Action: The Director parses the script into a Scene Graph. It cross-references the Visual RAG to flag continuity errors immediately (e.g., "Script Error: Alice lost her sword in Scene 2, but Scene 3 description says she is holding it.").
Output: A validated Shot_Config.json.
STEP 2: THE "BLOCKOUT" PREVIEW
System Action: The Blockout Engine executes the JSON plan using a lightweight local model.
Output: A Grey-Box Depth Map Animation. This shows camera movement, character positioning, and scene pacing in low-poly grey.
User Feedback: The user reviews the blockout to approve the "Directing" (camera angles/timing).
Benefit: Allows infinite iterations on the visual narrative without incurring expensive Cloud GPU costs.
PHASE II: PRODUCTION (The "Streaming" Layer)
Goal: Generate High-Fidelity Pixels using the "Divide and Conquer" strategy.
STEP 3: SCENE-BASED RENDERING
User Action: User approves the Blockout and clicks "Render Scene 1."
Cloud Action: The system spins up the Streaming Generator (Wan 2.1 / StreamingT2V). It does not render the full 10 minutes at once; it renders the designated scene (e.g., 2 minutes).
Consistency Injection:
Identity: Injects Hero LoRA (Alice's Face).
World: Injects IP-Adapter (Kitchen Photo).
Output: A high-fidelity video clip that matches the approved Blockout motion.
PHASE III: POST-PRODUCTION (The "Surgical" Layer)
Goal: Fix specific glitches without breaking the rest of the video.
STEP 4: GRANULAR REGENERATION
User Problem: "Alice's hand glitches at 00:45 - 00:50."
User Action: The user highlights the timeline section and draws a Bounding Box around the hand.
System Action: The Agent initiates a Regional Repair.
Background Lock: Applies TIARA/Attention Masking to freeze all pixels outside the box (Walls, Face, Body) so they do not change.
Anatomy Fix: Uses ControlNet (OpenPose) within the masked area to force the hand into a correct anatomical shape.
Result: A seamless patch update that fixes the glitch while preserving the rest of the approved scene.
================================================================================
6. PRODUCTION PIPELINE: "THE MEMORY LOOP"
================================================================================

Phase 1: Asset Injection (The "Bible" Build)

Before any rendering:
Character Bible: Generate consistent character sheets (front / side / 3/4) using a high-quality image model:
Option A: Flux / SDXL (open source, full control)
Option B: Gemini Imagen 3 "Nano Banana Pro" (Dec 2025)
Upload 3-5 reference images
Generate consistent character views (front/side/3-4 angles)
Built-in character consistency across up to 14 reference images
Cost: ~$0.04-0.20 per image
Ideal for rapid Bible generation with minimal prompt engineering
Train or configure LoRAs / IP-Adapter for key heroes (see Section 3A: Progressive Identity Lock).
Location Bible:
Generate panoramas / key angles for each core location.
Store as canon environment refs (Kitchen, Street, Castle, etc.).
Memory Registration: Store all assets and metadata in:
Visual RAG (semantic search)
Consistency Memory Store (keyframes, latents).
Innovation:
We don't train a giant custom video model for each user.
We pin reality via reference injection and reusable LoRAs.

Phase 2: Streaming Generation (Pass 1 -- 5-Minute Flow)

For a given story:
Director Agent:
Breaks script into scenes -> shots -> chunks.
For each chunk: decides which characters, which location, which layout.
ComfyUI Pass 1:
Uses StreamingT2V to render long sequences chunk-by-chunk with overlap.
Uses CoNo only at chunk boundaries to blend transitions.
Injects:
Character LoRAs
IP-Adapter environment refs
Layout / ControlNet constraints.
Logic Check:
Optional LLM pass or heuristic to inspect output:
Did Alice's outfit change randomly?
Did the kitchen walls morph?
If violation: re-render affected chunk(s) only.
The Logic Check (Visual + Physics):
After each chunk is rendered, the Physics Reviewer runs automated checks:

Visual Consistency (Identity):
 - ArcFace similarity: first frame vs Bible reference (threshold 0.70)
 - ArcFace similarity: first frame vs last frame (threshold 0.70)
 - CLIP embedding: first vs last frame (threshold 0.85)

Physics Consistency (CV-Based):
 - Object Permanence: YOLOv8 + ByteTrack (flag if object missing >3 frames)
 - Flicker Detection: RAFT optical flow (flag if >5% frame area affected)
 - Gravity Check: Y-position tracking (flag if unsupported object doesn't fall)
 - Collision Check: Bounding box overlap (flag if solids overlap >50%)

Tech Stack: YOLOv8, ByteTrack, RAFT, ArcFace, CLIP
Budget: <30 seconds per 10-15 second clip (all tools run at 20-30 FPS)
All tools are open-source, zero-shot (no training required)

If the Reviewer flags a chunk as inconsistent (visual or physics), the system:
Rejects that chunk.
Logs the failure reason (e.g., "Chunk 12: crowd falls with no visible impact").
Auto re-rolls that chunk with adjusted prompts/constraints (max 3 re-rolls per chunk).
If max re-rolls exceeded: surface to user with failure reason and manual override option.
New Module: The Cinematic Pacer
Instead of generating continuous long clips, the Director Agent employs a "Time-to-Cut" heuristic. It preemptively terminates shots before the model's measured Drift Threshold (~12-15s) and triggers a new camera angle request. This resets the diffusion seed and re-anchors the character LoRA, ensuring indefinite consistency through a sequence of high-fidelity short clips.
Revised Workflow Step:
Director: Assigns Max_Duration = 12s.
Planner: Splits "Scene 1 (45s)" into -> [Shot 1A (Mid, 10s), Shot 1B (Close, 8s), Shot 1C (Reverse, 12s), Shot 1D (Wide, 15s)].
Generator: Renders 4 distinct clips, resetting memory for each.
Voice Engine: Generates 1 continuous audio track.
Stitcher: Assembles video cuts over the continuous audio.
This approach is highly feasible, leverages the "Pro Lane" idea (using cuts to hide flaws), and technically simplifies your pipeline by removing the need for exotic "infinite streaming" research tech that is prone to failure.

Phase 3: Refinement & Delivery (Pass 2 + RIFE)

Pass 2 -- Refinement:
Feed the structural video into a vid2vid / FreeLong++-style refinement workflow.
Reduce flicker, enhance detail, optionally upscale resolution.
RIFE Interpolation:
12 fps -> 24 fps for cinematic smoothness.
Export:
Render to target formats: MP4, ProRes, social media presets.
================================================================================
7. Infrastructure & Cost Strategy
================================================================================
Component & Cost Breakdown (Two-Lane Model)
Lane
Component
Hardware / Provider
Cost Model (Est.)
Logic & Planning
Director Agent
Cloud LLM API
~$0.02 per 5-min film
Standard Lane
Video Generation (Pure OSS)
Cloud GPU (A10/A100)
~$0.50 - $0.80 per minute of video
Pro Lane (Hybrid)
Base Gen (Veo/Sora/Gen-3)
External API
~$6.00 - $12.00 per minute
Repair & Refinement
Consistency Fixes (img2img)
Cloud GPU (A10)
~$0.10 - $0.20 per minute
Storage
Asset Bible
S3 / R2
~$0.02 / GB

Why this matters:
The "Repair Dividend": A typical creator might spend $50+ re-rolling prompts on Veo to get one consistent character shot. By using our Repair Lane, they pay for the shot once and use our cheap GPU layer to fix the face/props.
Tiered Pricing: We can offer a "Free/Basic" tier running on pure open source (high margin) and a "Studio Pro" tier that passes through the API costs of Veo/Sora (lower margin, higher volume).

Model Selection Strategy (I2V-First Architecture)
[!] CRITICAL ARCHITECTURAL DECISION: T2V vs I2V-Only Pipeline
This section documents a fundamental architectural choice that directly impacts our
core value proposition of consistency.

7A.1 THE FUNDAMENTAL DIFFERENCE: T2V vs I2V
Both T2V and I2V use the SAME base model (e.g., Wan 2.1). The difference is input:
T2V (Text-to-Video):
Input: Text prompt only
Process: Noise --> Denoise with text conditioning --> Video
Output: Model's interpretation of the prompt
Example: "Alice in kitchen" --> Model imagines what Alice looks like
Result: RANDOM Alice (may not match our references)
I2V (Image-to-Video):
Input: Text prompt + init_image
Process: Image+Noise --> Denoise with text+image conditioning --> Video
Output: Animation starting from the provided image
Example: init_image=Alice_from_IP_Adapter, prompt="walks to window"
Result: OUR Alice animated (identity locked from frame 1)
Key Insight: I2V accepts text prompts for MOTION guidance while using init_image
for VISUAL identity. We get both control AND consistency.

7A.2 WHY T2V FOR SHOT 1 BREAKS CONSISTENCY
THE PROBLEM WITH T2V FIRST:
Current Flow (T2V for Shot 1):
Shot 1: T2V("Alice in kitchen, morning light...")
|
Model imagines: Blonde hair, round face, blue dress
|
Output: Video of MODEL'S Alice (not OUR Alice)
Shot 2: Bridge Frame (IP-Adapter with OUR references)
|
Re-anchored: Brown hair, angular face, red dress
|
I2V from bridge frame
RESULT: Shot 1 has DIFFERENT Alice than Shot 2+
Viewer sees jarring identity change at first cut!
We spend all this effort on Bridge Frames, IP-Adapter, and LoRA... then throw it
away by using T2V for Shot 1. This is architecturally inconsistent.
THE CORRECT FLOW (I2V Only):
Correct Flow (I2V for ALL Shots):
Shot 1: SDXL generates "Hero Frame"
- IP-Adapter (face reference) --> OUR Alice
- Location IP-Adapter or LoRA --> OUR kitchen
- ControlNet Pose (if specific pose needed)
|
I2V animates from hero frame
|
Output: Video of OUR Alice from frame 1
Shot 2: Bridge Frame (same process as hero frame)
|
I2V animates from bridge frame
|
Output: Video of OUR Alice (same as Shot 1)
RESULT: SAME Alice in ALL shots. Perfect consistency.

7A.3 THE UNIFIED PIPELINE: I2V-ONLY ARCHITECTURE
The insight is that Shot 1's "Hero Frame" and Shot 2+'s "Bridge Frame" use the
SAME workflow. The only difference is input source:
UNIFIED I2V-ONLY PIPELINE:
SHOT 1 (Hero Frame):
Source: Director Agent generates composition description
Process: SDXL + IP-Adapter + Location conditioning
Output: Hero Frame --> I2V --> Shot 1 Video
SHOT 2+ (Bridge Frame):
Source: Last frame of previous shot
Process: SDXL + IP-Adapter + ControlNet Pose
Output: Bridge Frame --> I2V --> Shot N Video
SAME WORKFLOW, DIFFERENT INPUT SOURCE
This is actually SIMPLER than T2V+I2V because:

One workflow pattern for all shots (Hero/Bridge --> I2V)
Same code path, just different input source
No special-casing for "first shot"

7A.4 WHEN T2V IS STILL USEFUL
T2V should NOT be in the main consistency pipeline, but it has valid uses:

EXPLORATION MODE
User: "I don't know what Alice should look like yet"
Action: T2V generates 5 variations
Result: User picks one, it becomes the canonical reference
After: All subsequent generation uses I2V with that reference
DEVELOPMENT TESTING
Developer: "I need to test the pipeline quickly"
Action: T2V is faster (no SDXL step)
Result: Quick iteration on non-identity features
After: Must validate with I2V before shipping
STYLE/MOTION EXPERIMENTATION
User: "What kind of motion does this prompt produce?"
Action: T2V tests motion without worrying about identity
Result: Find good motion prompt
After: Apply motion prompt with I2V for actual production
TRAINING DATA GENERATION
System: "Need diverse images to train Alice LoRA"
Action: T2V generates variations
Result: Curate best outputs for training
After: LoRA trained, used with I2V pipeline

INVALID T2V USE (What We Must Stop Doing):
[OK]-- Using T2V for Shot 1 of a consistency-focused film
[OK]-- Mixing T2V and I2V in the same production pipeline
[OK]-- Relying on T2V when identity matters

7A.5 DEVELOPMENT VS MVP: THE TRANSITION PLAN
CURRENT STATE (Development):
T2V is used for fast testing because:

No SDXL step needed --> faster iteration
Tests pipeline mechanics without identity concerns
Good for catching bugs quickly

MVP REQUIREMENT:
The main pipeline MUST switch to I2V-only:

Shot 1 uses Hero Frame (SDXL + IP-Adapter) --> I2V
Shot 2+ uses Bridge Frame (SDXL + IP-Adapter + ControlNet) --> I2V
T2V relegated to "exploration mode" only

IMPLEMENTATION CHECKLIST FOR MVP:
[ ] Create "hero_frame.json" workflow (or reuse bridge_full.json with different params)
[ ] Add Hero Frame generation step before Shot 1 I2V
[ ] Update pass1_generator.py to always use I2V with init_frame
[ ] Add config flag: generation.mode = "production" (I2V-only) vs "exploration" (T2V)
[ ] Update CLI/UI to require character refs OR offer exploration mode
MIGRATION PATH:
Development: T2V for testing --> "Works but identity random"
|
Pre-MVP: Add Hero Frame generation --> "Identity locked from Shot 1"
|
MVP: I2V-only pipeline --> "Consistency guaranteed"
|
Post-MVP: T2V as explicit "exploration" feature

7A.6 SUMMARY: T2V vs I2V DECISION TABLE

| Scenario | Use T2V? | Use I2V? | Why |
|----------|----------|----------|-----|
| Production Shot 1 | NO | YES | Identity must be locked |
| Production Shot 2+ | NO | YES | Bridge Frame continuity |
| Exploration "what if" | YES | NO | No identity constraint |
| Quick dev testing | YES | NO | Speed over identity |
| Final validation | NO | YES | Must test real pipeline |
| LoRA training data | YES | NO | Need variations |
| Customer demo | NO | YES | Identity is the value prop |

7A.7 ORIGINAL I2V-FIRST DETAILS (Preserved)
Our core value proposition is consistency from reference images, not random generation.
I2V-First vs T2V Approach:

| Approach | Shot 1 | Shot 2+ | Best For |
|----------|--------|---------|----------|
| I2V-First (Preferred) | Keyframe --> I2V | Bridge --> I2V | Professional filmmaking, max consistency |
| T2V + I2V (Optional) | T2V | Bridge --> I2V | Exploration mode, "surprise me" users |

Why I2V-First is Preferred:

Consistent quality: No jarring T2V --> I2V quality shift (e.g., 1.3B T2V vs 14B I2V)
Better composition control: User/system defines shot 1's framing via keyframe
Stronger identity from frame 1: Keyframe includes character via IP-Adapter
Bridge Engine pattern extended: Shot 1 keyframe uses same workflow as bridge frames

Keyframe Generation for Shot 1:

User provides keyframe --> Use directly as init_image for I2V
No keyframe provided --> Generate via SDXL + IP-Adapter (same as Bridge Engine workflow)
Exploration mode --> T2V generates multiple options, user picks one, becomes keyframe

Model-Agnostic Design Principle:
The system MUST allow hot-swapping models/APIs without code changes. The BaseRenderer abstraction enables:

WanRenderer (OSS Standard Lane)
VeoRenderer (Premium Pro Lane)
RunwayRenderer (Premium Pro Lane)
SoraRenderer (Premium Pro Lane)

Critical Insight: Even when users choose "shiny" premium APIs (Veo/Runway/Sora), our Bridge Engine provides the consistency they expect. Premium APIs have WORSE native consistency than our OSS pipeline because they lack LoRA/IP-Adapter support. Bridge Engine fills this gap by re-anchoring identity between API calls.
Testing vs Production Model Configuration:

| Mode | Model Choice | Purpose |
|------|--------------|---------|
| Dev/Testing | Fast models (Wan 1.3B) | Rapid iteration, catch bugs fast |
| Validation | Production models (14B) | Verify quality before shipping |
| Production | User-selected tier | Final output |

Warning: Testing on different models than production can hide model-specific bugs. The audit system (ArcFace identity check, physics checks) should catch model-agnostic issues, but periodic big-model validation runs during development are essential before shipping new features.
Future Quality Tiers (Post-MVP):

| Tier | First Shot | Subsequent Shots | Use Case |
|------|------------|------------------|----------|
| Draft | SDXL keyframe --> I2V fast | I2V fast | Quick preview |
| Standard | SDXL keyframe --> I2V 14B | I2V 14B | Normal production |
| Pro | SDXL keyframe --> Veo/etc | Veo/Runway + Bridge | Premium output |

Note: T2V path preserved for exploration/legacy use cases but not promoted as default workflow.

================================================================================
8. EXECUTION ROADMAP & BUDGET (90-DAY PLAN)
================================================================================

PHASE 1 (Days 1-30) -- The "Director + Bible" MVP

Goal: Prove the Director + Bible + manual ComfyUI workflow can produce consistent short clips. Focus: Logic & layout before heavy automation.
Tech Stack:
Brain: GPT-4o-mini / Claude Haiku (API calls from local Mac).
Assets: Flux / SDXL / Gemini Imagen 3 for character/location images.
Memory: Pinecone (Visual RAG) + basic S3 bucket.
ComfyUI: Cloud GPU (RunPod/Lambda) -- Mac handles orchestration only.
Deliverables:
Scene Graph Generator (Director MVP):
Script in -> JSON with scenes, shots, characters, locations.
Bible Folder:
Alice.safetensors / Alice_refs/
Kitchen.jpg / Kitchen_panorama/
Registered in Visual RAG.
Manual ComfyUI Workflow:
PASS 1 only:
StreamingT2V + LoRA + IP-Adapter + ControlNet + CoNo at boundary.
Demonstrate:
Clip A (0-5 sec)
Clip B (5-10 sec) using last frame of Clip A as context
Result: visually continuous movement and identity.
Budget Estimate: ~$150-$200 (GPU time + image generation APIs).

PHASE 2 (Days 31-60) -- The "Streaming Core" Automation

Goal: Automate Pass 1 via Python -> ComfyUI API. Focus: Move from manual clicking to agent-driven job orchestration.
Tech Stack:
Infrastructure: RunPod / Lambda (A10/A100/H100).
Engine: Base model + StreamingT2V + LoRA + IP-Adapter + ControlNet + CoNo in ComfyUI.
Orchestration:
comfy_client.py to:
Load workflow JSON
Fill in prompts, seeds, asset paths
Submit jobs
Poll for completion.
Deliverables:
Shot-to-ComfyUI Bridge:
Input: Scene Graph + Consistency Dictionary.
Output: Sequence of ComfyUI jobs per chunk.
The "Infinite Pan" Demo:
A 2-minute continuous shot of Alice walking through a static city / kitchen.
Identity and environment stay consistent; chunk joins are invisible or minimal.
First Integration with Visual RAG:
Director automatically retrieves correct assets for each shot.
External "Shoot" Integration:
Director Agent capability to send prompts to external APIs (Veo/Runway) to generate Base Clips.
Ingestion pipeline to pull these clips into the ComfyUI "Repair" workflow.
Budget Estimate: ~$200-$250 (GPU time + storage).

PHASE 3 (Days 61-90) -- Refinement, RIFE, and First 5-Minute Film

Goal: 3-5 minute coherent story, full pipeline (Pass 1 + Pass 2 + RIFE).
Tech Stack:
Memory: More robust Visual RAG usage (props, outfits).
Refinement: Vid2Vid / FreeLong++-style workflow for flicker/detail.
Frame-rate: RIFE integrated in the final stage.
Deliverables:
Full Short Film:
3-5 minute coherent story.
Characters, environment, and key prop (e.g. red mug) stay consistent.
Dialogue with lip-sync (using external TTS + lip-sync tools as needed).
Creator Interface (Alpha):
Minimal UI or CLI:
Upload script -> engine produces video.
Shows pass-wise output (Pass 1, Pass 2, final).
Visual RAG for Props:
Engine can track small objects across cuts:
"The mug stays red and on the same table."
Voice & Lip-Sync Integration (CRITICAL FOR VC DEMO):
TTS pipeline (ElevenLabs / OpenAI TTS) wired to the Director's Dialogue Map.
Lip-sync workflow (Musetalk / Wav2Lip) applied on speaking shots after Pass 2 and before RIFE.
Basic ambience layer (one AudioLDM-2 bed track per scene).
Audio ducking (-12dB on music/ambience during dialogue).
Demo Requirement: 3-5 minute short with:
At least one character with synced dialogue
Consistent identity across all shots
Immersive audio (not silent)
Rationale: "Silent films don't demo well" -- audio is non-negotiable for investor presentations.
Consistency Audit Pipeline:
Deploy VideoLLaMA 2 on Cloud GPU as the initial "Reviewer."
Write the VideoAuditor wrapper class to allow hot-swapping models.
Trigger: When Vidi2 weights are released, swap the backend engine to Vidi2 for advanced physics checking.
Budget Estimate: ~$100-$150 (GPU render + refinement passes).

8B. BUDGET SCENARIOS: OPEN SOURCE VS. HYBRID

We operate with two distinct financial models depending on the quality tier. This breakdown estimates the hard costs (Compute + API) to produce one 5-minute high-fidelity short film.
Scenario A: The "Pure Open Source" Budget (Low Cost)
Reliant on Wan 2.x / Hunyuan / Mochi running on rented GPUs.
Cost Item
Unit Cost (Est.)
Usage for 5-Min Film
Total Cost
Pass 1: Base Generation
~$1.30/hr (A100 GPU)
~3 hrs render time
$3.90
Pass 2: Refinement
~$0.75/hr (A10 GPU)
~2 hrs render time
$1.50
Assets (Images/LoRA)
~$0.50/hr (A10 GPU)
~1 hr training/gen
$0.50
Storage
$0.02/GB
~50GB raw assets
$1.00
Total Production

~$6.90

Strategic Note: This is our "gross margin king." We can offer this tier for free/cheap to standard users because the cost to generate a full film is negligible.
Scenario B: The "Hybrid Pro" Budget (High Fidelity)
Reliant on Google Veo 3.1 or Runway Gen-4 for base footage, plus Open Source for repairs.
Cost Item
Unit Cost (Est.)
Usage for 5-Min Film
Total Cost
Pass 1: Base Gen (API)
$0.20 - $0.40 per sec
300 sec + 100% buffer (600s)
$120.00 - $240.00
Pass 2: Repair Audit
$0.00 (Local/Light GPU)
All frames scanned
$0.00
Pass 3: Consistency Repair
~$1.30/hr (A100 GPU)
Repairing ~20% of frames
$1.30
Storage
$0.02/GB
~50GB raw assets
$1.00
Total Production

~$122 - $242

Strategic Note:
High Cost, High Value: While expensive, this replaces a real camera crew. A traditional 5-minute animated short costs $5,000+. We do it for ~$200.
Buffer Factor: The budget assumes we generate 2x the footage we need (600 seconds of raw generation to get 300 seconds of final cut).
Optimization: Using "Veo 3.1 Fast" ($0.10/sec) or Runway Gen-3 Turbo ($0.05/sec) can drop the API cost to ~$30 - $60, making this highly scalable.

Adjusted MVP Runway Budget (90 Days)

This updates the "Total MVP Runway" to account for realistic iteration cycles and audio requirements.
Item
Original Est.
Revised Est.
Notes
GPU Rentals (90 days)
~$600
~$1,200
More test iterations, re-rolls
API Testing (Veo/Runway)
~$400
~$400
Unchanged
LLM APIs (Director Agent)
Not listed
~$50
GPT-4o-mini calls (~$0.02/film)
TTS/Audio APIs
Not listed
~$150
ElevenLabs for MVP demos
Image Gen APIs
Not listed
~$100
Gemini Imagen 3 for Bible
Storage/Hosting
~$100
~$200
RAG + asset storage growth
Contingency (15%)
~$100
~$300
Buffer for unknowns
TOTAL REVISED BUDGET
~$1,100-1,200
~$2,400

Note: Original estimate was optimistic. Revised budget accounts for:
Real-world iteration cycles (expect 3-5x re-renders during testing)
Audio pipeline costs (essential for VC demo)
Cloud LLM costs (minimal but non-zero)
================================================================================
9. GO-TO-MARKET & MARKETING STRATEGY
================================================================================
We sell Consistency as a Service to segments where visual continuity is a genuine bottleneck and people are willing to pay.

9A. Target Market Hierarchy

Tier
Target Audience
Pain Point
Why Us?
PRIMARY
Virtual Influencer Agencies
Need daily consistent content; manual expensive
Our engine auto-produces their "digital actors."
SECONDARY
Comic / Webtoon Publishers
Have strong static IP, lack motion content
We turn panels into motion trailers in their style.
TERTIARY
Ad Agencies (FMCG)
Need consistent product presence in variants
Our Visual RAG keeps product identity perfect.

9B. The "Trojan Horse" Campaign

Don't pitch the tool. Pitch the outcome.
Internal Influencer:
Create our own virtual influencer (e.g. "Koda the Cyberpunk Barista").
Post daily videos for 30 days on Instagram/TikTok.
Show:
Same face
Different outfits, lighting, angles
Consistent personality.
Proof Pitch:
Instead of a deck, send brands Koda's live profile.
Line: "We built this entire account with our engine. We can build one for your brand too."

9C. The "Remix" Campaign

Attack IP holders with unsolicited value.
Identify high-performing Webtoons / comics without anime/animated trailers.
Train an art-style LoRA or use style conditioning.
Generate a 20-30 second "anime opening" trailer.
Post it, tag them, and DM: "I love [Comic Name], so I animated this fan trailer. If you want a whole season of TikTok-friendly shorts like this, we can do it at scale."
Legal Note: Ensure fair use compliance or obtain permission before creating promotional content using third-party IP. Consider reaching out to creators BEFORE posting fan content.

9D. Sales Packaging: "Digital Ambassador Subscription"

We avoid "per second" pricing. We sell persistent characters.
Offer: "Digital Ambassador Package"
Price: $2,000-$5,000 / month
Includes:
1-3 custom characters (LoRAs, voices, personality profiles).
10-20 short videos / month.
Consistent look, voice, and narrative.
Cheaper than:
Hiring actors + studio
Traditional VFX
Ad-hoc AI prompt operators with no continuity.
================================================================================
10. POST-90-DAY ROADMAP (PLATFORM ERA)
================================================================================
Days 90-180: Turn the engine into a platform, not a one-off tool.

10A. Multi-Hero Orchestration

Crowd scenes with 3-10 recurring characters.
Better regional prompting, segmentation, and blocking.

10B. Style Transfer Modules

"Turn this entire 5-minute movie into claymation / anime / watercolor" via:
Style LoRAs
Vid2vid style transfer passes.

10C. Real-Time Director Mode

While rendering, allow commands like:
"Make her smile in this shot."
"Move the camera closer during this line."
Implement as:
Director Agent updates layout/prompt mid-render.
Renders new shot/chunk and reinserts it.
================================================================================
11. HARDWARE STRATEGY (HYBRID)
================================================================================
Optimized for cost, thermals, and future scale.

Local (MacBook Air M4)

Runs:
Development & testing of orchestration code
Director Agent API calls (to cloud LLMs)
Job dispatch to cloud ComfyUI
UI / CLI for creators
Light preview / editing (already-rendered clips)
Does NOT Run:
Video model inference (too heavy -- tested, confirmed)
LoRA training
Any diffusion model inference
Benefits:
Fast iteration on logic/orchestration
Portable development environment
Test workflows before paying for GPU time

Cloud (GPU Rentals -- RunPod / Lambda)

Runs:
ComfyUI server + ALL video model inference
LoRA training (short sessions)
Pass 1 + Pass 2 + RIFE
ArcFace / CLIP embedding extraction for QA
Benefits:
Scale horizontally (more GPUs for more clients)
Swap models as OSS advances
Pay only for what you use
Development Workflow:
Build orchestration code on Mac
Deploy ComfyUI workflows to cloud GPU
Test renders via API calls from Mac
Iterate on logic locally, re-test on cloud
We maintain strict separation:
Brain (orchestration) is local and portable.
Muscle (inference) is cloud-only and scalable.
================================================================================
12. HYBRID PIPELINE STRATEGY: THE "SHOOT & RETOUCH" MODEL
================================================================================
Core Concept: We acknowledge that closed-source models (Veo, Sora, Gen-3) currently excel at physics and motion, while open-source models excel at controllability and consistency. We utilize a Hybrid Lane where we treat the closed model as the "Camera Crew" and our open-source stack as the "VFX Department."

12A. The Workflow: "Modify, Don't Create"

Instead of generating pixels from pure noise, we use img2img (Image-to-Image) and vid2vid (Video-to-Video) techniques to strictly enforce consistency on high-quality base footage.
Base Generation (The "Shoot"):
The Director Agent sends the prompt to a high-end model API (Veo, Sora) or a local high-fidelity model.
Goal: Capture the composition, camera movement, and action.
Acceptance: We accept that the character's face or specific props may be inaccurate in this pass.
The Audit (The "Dailies"):
The system extracts frames and runs the Consistency Reviewer.
It flags frames where:
Character Identity Similarity (ArcFace) < 0.75.
Key Prop (Red Mug) is missing or wrong color.
The Repair (The "Retouch"):
Technique: Low-Denoising img2img Loop.
Input: The "wrong" frame from the Base Gen.
Process:
The frame is encoded to latent space with low noise (Strength ~0.3-0.4).
Conditioning Injection: We inject the Canonical Character LoRA and Reference IP-Adapter.
Prompt: "Same scene, [Character Name], high quality."
Result: The model "collapses" the latent back to the identity defined by the LoRA. The Veo motion remains, but the face snaps to the correct identity.

12B. Strategic Impact

Cost Model: Higher per-minute cost (API + GPU), but guarantees cinematic motion. Offered as the "Pro" lane.
Efficiency: We only "repair" the specific frames or regions (masks) that fail the audit, rather than regenerating the whole video.

12C. The "Bridge Repair" (Pro Lane Upgrade)

When using external APIs (like Veo or Sora) that handle long shots well but lack precise start-frame control:
We treat the external model as the "Camera."
If the external model drifts or hallucinates a cut, we use our Bridge Engine locally to generate 3-5 transition frames (morphs) to smooth the jump.
We then use a Video Interpolation Model (RIFE) to blend these frames, "healing" the cut so the viewer never sees the drift.
================================================================================
13. MARKET POSITIONING: "THE DIGITAL STUDIO"
================================================================================
We are not "yet another AI video app." We are The Digital Studio for Persistent IP. We manufacture consistent digital ambassadors and worlds.
Primary: Virtual influencer agencies
Secondary: Webtoon/IP publishers
Tertiary: Ad agencies with strong brand IP.
Value Prop: "Don't just generate random clips. Build a persistent world and cast your own."
================================================================================
14. FINAL ONE-LINER
================================================================================
"The first AI video engine that remembers. We build consistent characters and worlds so you can direct 5-minute stories, not just gamble on lucky prompts."

================================================================================
15. USER EXPERIENCE (UX) STRATEGY
================================================================================
Our UX philosophy: "Collaborate with an AI Director, don't wrestle with prompts."

Users should feel like they're working with a competent film crew, not debugging 
a machine learning pipeline. The complexity lives under the hood; the surface is 
simple: Write → Approve → Walk Away → Get Notified.

--------------------------------------------------------------------------------
15A. MVP FEATURES (Must-Have for Launch)
--------------------------------------------------------------------------------

15A.1 SCRIPT APPROVAL WORKFLOW ("The Director's Table")
-------------------------------------------------------
The core interaction model that differentiates Continuum from prompt-and-pray tools.

User Flow:
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. USER INPUT                                                               │
│     - User writes story idea, script, or uploads existing screenplay        │
│     - Can be as simple as "30-second ad for coffee shop, warm vibe"         │
│     - Or as detailed as a full scene-by-scene breakdown                     │
│                                                                              │
│  2. DIRECTOR AGENT GENERATES SCENE GRAPH                                     │
│     - Parses input into structured scenes, shots, characters                │
│     - Proposes camera angles, pacing, shot durations                        │
│     - Identifies characters and matches to Consistency Dictionary           │
│     - Estimates render time and cost                                        │
│                                                                              │
│  3. USER REVIEW & APPROVAL ("The Director's Table")                         │
│     - Web UI shows proposed scene breakdown in human-readable format:       │
│       ┌──────────────────────────────────────────────────────────────────┐  │
│       │ SCENE 1: Coffee Shop Interior (Morning)                          │  │
│       │ ├─ Shot 1 (5s): Wide establishing shot, warm sunlight            │  │
│       │ ├─ Shot 2 (3s): Close-up on barista (ALEX) preparing latte       │  │
│       │ └─ Shot 3 (4s): Customer receives drink, smiles                  │  │
│       │                                                                  │  │
│       │ SCENE 2: ...                                                     │  │
│       │ ──────────────────────────────────────────────────────────────── │  │
│       │ Estimated: 30 seconds | ~$0.45 | ~15 min render time             │  │
│       │ [Edit Scene] [Edit Shot] [Regenerate Suggestion] [APPROVE ✓]    │  │
│       └──────────────────────────────────────────────────────────────────┘  │
│     - User can:                                                             │
│       • Edit prompts for any shot                                           │
│       • Adjust durations                                                    │
│       • Reorder shots                                                       │
│       • Ask Director to regenerate specific scenes                          │
│       • Add/remove shots                                                    │
│                                                                              │
│  4. ONE-BUTTON GENERATION                                                    │
│     - User clicks "Generate" → job queued                                   │
│     - User can close browser, walk away                                     │
│     - Background workers handle:                                            │
│       • Hero frame generation                                               │
│       • Bridge frame generation                                             │
│       • I2V rendering                                                       │
│       • Audit checks (identity, physics)                                    │
│       • Automatic rerolls if needed                                         │
│       • Post-processing (color match, stitching)                            │
│                                                                              │
│  5. NOTIFICATION & DELIVERY                                                  │
│     - Push notification / email: "Your video is ready!"                     │
│     - User returns to see:                                                  │
│       • Final stitched video                                                │
│       • Per-shot breakdown (for future editing)                             │
│       • Generation report (identity scores, rerolls, cost)                  │
│       • Download options (MP4, per-shot clips)                              │
└─────────────────────────────────────────────────────────────────────────────┘

Technical Implementation:
- Frontend: Simple React/Next.js web app (or desktop Electron app)
- Backend: FastAPI server on cloud (or local for dev)
- Job Queue: Redis + Celery (or similar) for async job management
- Notifications: 
  • Email via SendGrid/Postmark
  • Push via Firebase Cloud Messaging
  • Webhook for integrations
- Storage: S3-compatible for rendered outputs

Why This Matters:
- Differentiates from "type prompt, get random clip" competitors
- Matches real film workflow (script → shoot → review)
- User feels creative control without technical burden
- Async model = no staring at progress bars for 30+ minutes
- Enables batch processing (queue multiple projects overnight)

15A.2 CHARACTER ONBOARDING ("The Casting Call")
-----------------------------------------------
Simple flow to add a character to the user's "cast."

User Flow:
1. Upload 1-5 reference photos of character
2. System generates:
   - LoRA (background training, ~15-30 min)
   - Face embedding (instant)
   - Character profile (name, description, voice style)
3. Character appears in user's "Cast" library
4. When writing scripts, user can reference: "ALEX enters the room"
   - System automatically links to character's LoRA and face refs

15A.3 PROJECT DASHBOARD ("The Studio Lot")
------------------------------------------
Central hub for all user's projects:
- Active renders (with progress)
- Completed projects (with quick preview)
- Character library ("The Cast")
- Location library ("The Backlot")
- Usage/credits remaining

15A.4 SIMPLE EXPORT OPTIONS
---------------------------
- Download final video (MP4, various resolutions)
- Download per-shot clips (for external editing)
- Direct share to social platforms (stretch goal)

--------------------------------------------------------------------------------
15B. FUTURE FEATURES (Post-MVP Roadmap)
--------------------------------------------------------------------------------

15B.1 TEXT-BASED VIDEO EDITING ("The Editor's Suite")
-----------------------------------------------------
Allow users to modify rendered videos through natural language commands.

Concept:
┌─────────────────────────────────────────────────────────────────────────────┐
│  User views completed video, wants changes:                                  │
│                                                                              │
│  USER: "Make the lighting warmer in shot 3"                                 │
│  USER: "Have Alex wear sunglasses in the outdoor scenes"                    │
│  USER: "Remove the chair from the background in shot 2"                     │
│  USER: "Make shot 4 longer, he should walk slower"                          │
│                                                                              │
│  SYSTEM:                                                                     │
│  1. Director Agent interprets the request                                   │
│  2. Identifies affected shots/frames                                        │
│  3. Generates new scene graph for affected portions                         │
│  4. Shows user what will change:                                            │
│     ┌────────────────────────────────────────────────────────────────────┐  │
│     │ PROPOSED CHANGES:                                                  │  │
│     │ • Shot 3: Re-render with "warm golden hour lighting" prompt        │  │
│     │ • Shot 5: Re-render with "wearing black sunglasses" added          │  │
│     │ • Shot 7: Re-render with "wearing black sunglasses" added          │  │
│     │                                                                    │  │
│     │ Affected: 3 shots | Est. time: 8 min | Est. cost: $0.15            │  │
│     │ [Preview Change] [Approve & Re-render] [Cancel]                    │  │
│     └────────────────────────────────────────────────────────────────────┘  │
│  5. User approves → System re-renders only affected shots                   │
│  6. Bridge Healer ensures transitions remain smooth                         │
│  7. Final video assembled with old + new shots                              │
└─────────────────────────────────────────────────────────────────────────────┘

Technical Challenges:
- Temporal coherence: New shots must match adjacent shots' start/end frames
- Cascading changes: Edits may require re-generating bridge frames
- Semantic understanding: "Make him more confident" → which frames? what changes?
- Surgical rendering: Re-render 5 seconds without touching rest of 30-second video
- Version control: Track edit history, allow undo/redo

Implementation Phases:
Phase 1: Shot-level regeneration ("Regenerate shot 3 with new prompt")
         - Already architecturally supported
         - Just needs UI exposure
         
Phase 2: Trim/extend operations ("Make shot 2 longer")
         - FFmpeg operations, no re-rendering needed
         - Or re-render with more frames
         
Phase 3: Style transfer ("Make everything more cinematic")
         - Vid2Vid pass on final output
         - Color grading presets
         
Phase 4: Selective re-rendering with Bridge Healing
         - Smart detection of affected shots
         - Automatic bridge frame regeneration for transitions
         - Seamless splice back into original
         
Phase 5: Full semantic editing (Future - requires foundation model advances)
         - "Add a dog in the background"
         - "Change the coffee cup to a wine glass"
         - Likely requires video editing models (Sora-level inpainting)

15B.2 REAL-TIME COLLABORATION ("The Writers' Room")
---------------------------------------------------
Multiple users can:
- Edit the same script simultaneously
- Leave comments on specific shots
- Approve/reject shots in review workflow
- Assign roles (Writer, Director, Producer)

15B.3 VOICE DIRECTION ("The Director's Chair")
----------------------------------------------
Voice commands during render preview:
- "Make her smile more in this shot"
- "Zoom in on the product"
- "Add more dramatic lighting"
System queues changes for next render pass.

15B.4 A/B TESTING MODE ("The Focus Group")
------------------------------------------
Generate 2-3 variants of key shots automatically.
User picks preferred versions.
System learns preferences for future generations.

15B.5 TEMPLATE LIBRARY ("The Playbook")
---------------------------------------
Pre-built templates for common formats:
- 30-second product ad
- 60-second explainer
- Instagram Reel format
- YouTube Shorts format
- Cinematic trailer
User selects template → fills in specifics → generates.

--------------------------------------------------------------------------------
15C. UX PRINCIPLES (Design Guidelines)
--------------------------------------------------------------------------------

1. SHOW, DON'T TELL
   - Preview everything before generation
   - Visual scene breakdown, not JSON
   - Thumbnail storyboards, not text lists

2. PROGRESSIVE DISCLOSURE
   - Simple by default, advanced on demand
   - New users see: Write → Generate → Download
   - Power users can access: Shot-by-shot control, custom workflows

3. FAIL GRACEFULLY
   - If a shot fails audit, auto-reroll (don't make user debug)
   - If generation fails, clear error message + "Try Again" button
   - Never show stack traces to users

4. TRANSPARENT COST
   - Always show estimated cost before generation
   - Show actual cost after completion
   - No surprise bills

5. RESPECT TIME
   - Async everything (never make user wait at screen)
   - Accurate time estimates
   - Proactive notifications

6. CREATIVE CONTROL
   - User approves before spending money/time
   - User can edit any parameter if they want
   - But defaults should be good enough for 80% of cases

================================================================================
16. MULTI-FORMAT OUTPUT STRATEGY
================================================================================
Core insight: The Director Agent + Consistency Dictionary is format-agnostic.
The same "story brain" can output video, manga pages, or visual novel frames.

Video is the hardest output format. We lead with easier formats where our 
consistency engine delivers immediate value, then expand to video as models mature.

--------------------------------------------------------------------------------
16A. OUTPUT FORMAT SPECTRUM
--------------------------------------------------------------------------------

┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTINUUM OUTPUT FORMATS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  VISUAL NOVEL          MANGA/WEBTOON           ANIMATED VIDEO               │
│  (Easiest)             (Medium)                (Hardest)                    │
│                                                                              │
│  Static frames         Static panels           Full motion                  │
│  + dialogue            + layout                + temporal consistency       │
│  + choices             + speech bubbles        + physics                    │
│                                                                              │
│  ~30 sec/scene         ~2 min/page             ~15 min/30 sec               │
│  Image API OK          Image API OK            Video models required        │
│  (Nano Banana Pro)     (Nano Banana Pro)       (Wan/Hunyuan/Veo)            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Key Insight: Manga and Visual Novels don't need video generation at all.
They need CONSISTENT IMAGE generation — which is a solved problem.

--------------------------------------------------------------------------------
16B. SHARED ARCHITECTURE (What Stays the Same)
--------------------------------------------------------------------------------

All output formats share the same core:

┌─────────────────────────────────────────────────────────────────────────────┐
│  DIRECTOR AGENT (Shared)                                                     │
│  ├── Script parsing                                                         │
│  ├── Scene/shot breakdown                                                   │
│  ├── Character assignment                                                   │
│  ├── Pose/expression direction                                              │
│  └── Pacing decisions                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  CONSISTENCY DICTIONARY (Shared)                                             │
│  ├── Character definitions (LoRAs, embeddings, descriptions)                │
│  ├── Location definitions (style refs, descriptions)                        │
│  └── Prop definitions                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  WORLD STATE TRACKER (Shared)                                                │
│  ├── Who is in scene                                                        │
│  ├── What they're wearing                                                   │
│  ├── Object positions                                                       │
│  └── Continuity tracking                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
            │ VN Renderer │ │Manga Renderer│ │Video Renderer│
            │  (Images)   │ │  (Panels)   │ │  (Video)    │
            └─────────────┘ └─────────────┘ └─────────────┘

--------------------------------------------------------------------------------
16C. VISUAL NOVEL PIPELINE
--------------------------------------------------------------------------------

Simplest output format. Static character sprites over backgrounds with dialogue.

Input:  Script with dialogue and scene descriptions
Output: Sequence of frames (PNG) + dialogue JSON (for VN engines)

Pipeline:
1. Director Agent parses script into scenes
2. For each scene:
   - Generate background (or retrieve from library)
   - Generate character sprite(s) with expression/pose
   - Character consistency via Nano Banana Pro's subject consistency
   - Or LoRA if using open source (SDXL/Flux)
3. Output: Frame image + dialogue text + speaker ID
4. Export format: Ren'Py compatible, or custom JSON

Technical Stack:
- Image Gen: Nano Banana Pro (recommended), Flux, SDXL, or DALL-E 3
- Character Consistency: 
  • Nano Banana Pro: Native subject consistency (best)
  • Open source: LoRA + IP-Adapter
- Pose Control: ControlNet (open source) or prompt-based (API)
- No video models needed

Time: ~30 seconds per frame
Cost: ~$0.04-0.13 per frame (Nano Banana Pro pricing)

--------------------------------------------------------------------------------
16D. MANGA/WEBTOON PIPELINE  
--------------------------------------------------------------------------------

Medium complexity. Multiple panels per page, speech bubbles, layout.

Input:  Script with panel descriptions
Output: Complete manga pages (PNG/PDF) or webtoon strips (vertical scroll)

Pipeline:
1. Director Agent breaks script into panels
2. Director assigns:
   - Panel composition (close-up, wide, etc.)
   - Character poses and expressions
   - Camera angle
   - Speech bubble content
3. For each panel:
   - Generate image via Nano Banana Pro (recommended)
   - Subject consistency maintains character across all panels
   - Excellent text rendering for sound effects (SFX)
4. Layout Engine:
   - Arrange panels on page (manga) or vertical strip (webtoon)
   - Add speech bubbles
   - Insert text with appropriate fonts
   - Add effects (speed lines, impact frames)
5. Export: PNG per page, or full PDF/EPUB

Technical Stack:
- Image Gen: Nano Banana Pro (SOTA), Flux, SDXL, or DALL-E 3
- Character Consistency: 
  • Nano Banana Pro: Native multi-image subject consistency
  • Open source: LoRA or strong prompt engineering
- Layout: Python + Pillow/Cairo, or HTML/CSS rendering
- Text: Nano Banana Pro renders text natively (huge advantage)
- Speech Bubbles: Template library + dynamic sizing

Time: ~2-3 minutes per page (10 panels)
Cost: ~$0.40-1.30 per page (Nano Banana Pro @ 10 panels)

Why Nano Banana Pro for Manga:
- Text rendering is critical (SFX, signs, labels)
- Character must stay consistent across 10+ panels
- Multi-image fusion helps with reference sheets
- 4K output ideal for print-quality manga

Webtoon-Specific:
- Vertical scroll format (single column)
- Optimized for mobile reading
- Fewer panels per "page" but more total panels
- Color standard (vs manga B&W option)

--------------------------------------------------------------------------------
16E. ANIMATED VIDEO PIPELINE (Current Implementation)
--------------------------------------------------------------------------------

Most complex. Full motion, temporal consistency, physics.
This is what Continuum Engine currently implements.

(See Sections 3-6 for detailed video pipeline architecture)

Summary:
- Hero Frame generation (identity lock)
- Bridge Frame generation (shot transitions)  
- I2V rendering with LoRA (Wan 2.1)
- Audit system (identity + physics checks)
- Post-production (color match, stitching)

Time: ~15 minutes per 30-second video
Cost: ~$0.50-2.00 per 30-second video (GPU rental)

--------------------------------------------------------------------------------
16F. API STRATEGY BY FORMAT
--------------------------------------------------------------------------------

Different formats allow different API choices:

┌─────────────┬──────────────────┬─────────────────────────────────────────────┐
│ Format      │ Open Source      │ Closed API                                  │
├─────────────┼──────────────────┼─────────────────────────────────────────────┤
│ Visual Novel│ SDXL, Flux       │ Nano Banana Pro ★ (SOTA), DALL-E 3, Imagen  │
│ Manga       │ SDXL, Flux       │ Nano Banana Pro ★ (SOTA), DALL-E 3, Imagen  │
│ Anime Video │ Wan 2.1 ✓        │ Veo (limited control)                       │
│ Real Video  │ Wan (weak)       │ Veo, Sora (best quality, less control)      │
└─────────────┴──────────────────┴─────────────────────────────────────────────┘

RECOMMENDED IMAGE API: Nano Banana Pro (Gemini 3 Pro Image)
-----------------------------------------------------------
Google DeepMind's state-of-the-art image generation model (Nov 2025).

Why Nano Banana Pro for Manga/VN:
- Best-in-class character consistency across multiple generations
- Excellent text rendering (speech bubbles, signs, UI elements)
- Multi-image fusion (combine references seamlessly)
- Strong prompt adherence for complex scene descriptions
- Real-world knowledge grounding (accurate details)
- 4K resolution support
- ~$0.04/image (1K) to ~$0.13/image (4K) — cost effective

API Access:
- Model: gemini-3-pro-image-preview
- Via: Google AI Studio, Vertex AI, Gemini API
- Free tier available (with watermark + limits)
- Pro tier: No visible watermark, higher quotas

Key Capability for Continuum:
"Subject consistency allows the same person or item to be recognized 
across revisions" — exactly what our Consistency Dictionary needs.

Fallback Options:
- Nano Banana (Gemini 2.5 Flash Image): Faster, cheaper, slightly lower quality
- Flux 1.1 Pro: Best open-weight alternative
- DALL-E 3: Good quality, different aesthetic
- Imagen 3: Google's diffusion model (different from Nano Banana)

Key Insight: 
- For images (VN, Manga): Nano Banana Pro is the clear winner
- For video: Open source still preferred for LoRA/ControlNet injection
- Hybrid possible: Nano Banana Pro for manga, Wan for anime video

--------------------------------------------------------------------------------
16G. PRODUCT ROLLOUT STRATEGY
--------------------------------------------------------------------------------

Phase 1A - NOW: Anime Video (Current)
- Proving the consistency engine works
- Complex but differentiated
- Matrix Zero demo validates pipeline

Phase 1B - QUICK WIN: Manga/Visual Novel (2-3 weeks)
- Reuse Director Agent + Consistency Dictionary
- Much faster generation (minutes not hours)
- Can use Nano Banana Pro API (SOTA quality)
- Faster user feedback loop
- Lower barrier to first value

Phase 2: Webtoon Platform Integration
- Partner with webtoon platforms
- "Animate your webtoon" upsell to video
- Static → Motion pipeline

Phase 3: Realistic Video
- When open source catches up
- Or Hybrid Lane with Veo + consistency post-processing
- Premium tier offering

--------------------------------------------------------------------------------
16H. UNIFIED PRODUCT POSITIONING
--------------------------------------------------------------------------------

Brand: "Continuum Studio"
Tagline: "Consistent AI Storytelling"

NOT "anime generator" or "manga maker" — those box us in.
The value prop is CONSISTENCY across any format.

User Flow (Unified):
1. Write your story (or upload script)
2. Director Agent creates scene breakdown  
3. User reviews and approves
4. Choose output format:
   ├── Visual Novel → frames in 2 min
   ├── Manga/Webtoon → pages in 5 min  
   └── Animated Video → video in 30 min
5. Get notified when ready

Same story, same characters, multiple outputs.
A webtoon creator could generate:
- Static webtoon (for publishing)
- Animated trailer (for marketing)
- Visual novel (for game adaptation)

All with the SAME character consistency.

================================================================================
17. FINAL ONE-LINER (Updated)
================================================================================
"The first AI storytelling engine that remembers. Consistent characters across 
manga, visual novels, and animated video — same story, any format."

================================================================================
18. DATA STRATEGY & MOAT
================================================================================
See: DATA_STRATEGY.md

Summary: Our moat is proprietary data accumulated through usage — character 
LoRAs, approval/rejection signals, style embeddings, and project patterns. 
This data trains proprietary models (ConsistencyNet, PromptEnhancer) that 
competitors cannot replicate without equivalent user base.

Key lock-in: Character LoRA library (switching cost = re-train everything).
Key milestone: 50K generations → train ConsistencyNet v1.

================================================================================
END OF DOCUMENT
================================================================================