AI Consistent Character Engine -- MASTER STRATEGY & PRODUCT BLUEPRINT (v2025.9)
The "Pixar-on-Demand" Engine
================================================================================
0. EXECUTIVE SUMMARY
================================================================================
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

Goal: Pixel-stable character identity ("Alice is always Alice"). Technology: LoRA (Low-Rank Adaptation) and/or textual inversion. Tools: Kohya_ss, ComfyUI LoRA loaders, IP-Adapter for faces.
System Fit:
Train or configure one LoRA per hero character.
Inject LoRA into the base video model in all relevant shots.
Store LoRA configs + reference images in Visual RAG with stable IDs.
Progressive Identity Lock (Hybrid IP-Adapter + Auto-LoRA):
The goal is zero-wait UX with progressive quality enhancement.
Tier 1 -- Instant Start (IP-Adapter):
User uploads 3-5 reference images of character
System extracts CLIP embeddings immediately
User can START CREATING within seconds
Quality: ~80% identity consistency (good for drafts/previews)
Tier 2 -- Background Enhancement (Auto-LoRA):
System generates 15-20 augmented images using Gemini Imagen 3 (Nano Banana Pro)
ArcFace filters generated images (keep only >0.7 similarity to originals)
Auto-trains LoRA on combined dataset (original + augmented)
Training time: 30-45 min on A100
Training cost: ~$0.71 per character
Quality: ~95% identity consistency
UX Flow:
Upload images -> IP-Adapter ready instantly -> "Draft Mode" available
Background job: augment images -> train LoRA -> validate with ArcFace
Notification: "Enhanced Mode Ready" -> user can re-render with LoRA
Fallback: If LoRA training fails, IP-Adapter remains available
Why this matters:
No "training wall" blocking creators from starting
Progressive enhancement feels like magic
Always have a working fallback

3B. The Bridge Engine (The Handshake Layer)

Goal: Ensure that if we do cut (either for style or to save consistency), the physics and emotions carry over 100%.
The Problem: Video models often "reset" motion or emotion at the start of a new generation. The Solution: We generate Frame 0 of the new shot before generating the video.
System Fit:
Capture: Director grabs the last valid frame of Shot A.
Transform: Uses ControlNet (OpenPose) + IP-Adapter to generate a single high-fidelity Bridge Frame from the new camera angle.
Inject: This frame is fed into the Video Model as the init_image, forcing the new shot to start exactly where the story left off.
Phase 1 Testing Note: MVP starts with single Bridge Frame injection. If testing reveals "motion freeze" (character holds pose unnaturally at start of new shot), upgrade to 3-5 frame sequence:
Use RIFE to interpolate between last frame of Shot A and Bridge Frame
Inject sequence as init_latent instead of single frame
Trade-off: ~3x GPU cost per cut, but ensures smooth motion handoff Decision: Test with real content in Phase 1; upgrade only if users report visible issues.

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

3E. The World Engine (Environment Lock)

Goal: The kitchen/forest/city stays visually consistent across time and scenes. Technology: IP-Adapter, reference image injection, environment keyframes. Tools: ComfyUI IPAdapter Plus, panorama refs.
System Fit:
Pre-generate location panoramas / key views (front / side / wide).
Store them as canonical environment assets.
For each shot in that location:
Feed the correct environment ref into IP-Adapter / conditioning.
This "locks" walls, windows, big objects.

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

| Check Type        | Method                   | Threshold/Trigger    | Speed       | Action on Fail    |
|-------------------|--------------------------|----------------------|-------------|-------------------|
| Identity Drift    | ArcFace embedding        | < 0.70 similarity    | ~10ms/frame | Auto re-roll      |
| (vs Bible)        | cosine similarity        |                      |             | (max 3 attempts)  |
| Shot Drift        | ArcFace first vs last    | < 0.70 similarity    | ~10ms/frame | Auto re-roll      |
| Object Permanence | YOLOv8 + ByteTrack       | Missing >3 frames    | ~30ms/frame | Auto re-roll      |
| Flicker           | RAFT optical flow        | >5% frame affected   | ~50ms/pair  | Auto re-roll      |
| Gravity Violation | Y-position heuristic     | No downward motion   | ~1ms/frame  | Auto re-roll      |
| Passthrough       | Bbox overlap >50%        | Solid objects only   | ~1ms/frame  | Auto re-roll      |
| Scene Consistency | CLIP embedding           | < 0.85 similarity    | ~20ms/frame | Flag for review   |
| Prop Presence     | VideoLLM prompt (V2)     | Pass/Fail            | ~5s/clip    | Flag for review   |

**Tech Stack (All Open-Source, Zero-Shot):**

| Component         | Tool                        | Source                          |
|-------------------|-----------------------------|---------------------------------|
| Object Detection  | YOLOv8                      | ultralytics/ultralytics (GitHub)|
| Object Tracking   | ByteTrack                   | ifzhang/ByteTrack (GitHub)      |
| Optical Flow      | RAFT                        | princeton-vl/RAFT (GitHub)      |
| Pose Estimation   | MediaPipe                   | Google (pip install mediapipe)  |
| Action Recognition| SlowFast (V2)               | facebookresearch/SlowFast       |
| Video QA (V2)     | Vidi2                       | ByteDance (HuggingFace)         |

**Real-Time Drift Detection: DEFERRED to Phase 2**

Rationale: 
* Current models (Wan 2.1, HunyuanVideo) stable for 12-15 seconds
* Cinematic Pacer cuts at 12s (within stable window)
* Post-render CV checks are fast enough (<30s per 10s clip)
* Phase 2 upgrade: Vidi2 grounding for advanced physics/spatial checks

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
  |      CLOUD_GPU / COMFYUI_SERVER                         |
  |                                                         |
  |      +---------------------------------------------+    |
  |      | PASS 1: STRUCTURAL LONG-FORM VIDEO         |    |
  |      | - Base model (Wan / Hunyuan / Mochi)       |    |
  |      | - LoRA (identity) + IP-Adapter (world)     |    |
  |      | - ControlNet / Layout (physics)            |    |
  |      | - Bridge Frame Injection (seamless cuts)   |    |
  |      | - StreamingT2V Chunking                    |    |
  |      +---------------------------------------------+    |
  |            |                                            |
  |            v                                            |
  |      [REVIEWER_AGENT] (Visual & Physics Audit)          |
  |        -> Checks Identity, Props, & Gravity             |
  |        -> FAIL: Trigger Re-Roll of Chunk                |
  |        -> PASS: Proceed to Pass 2                       |
  |            |                                            |
  |            v                                            |
  |      +---------------------------------------------+    |
  |      | PASS 2: REFINEMENT & LIPS                  |    |
  |      | - Vid2Vid / FreeLong++ (flicker reduction) |    |
  |      | - Lip Sync (Musetalk) using Audio Track    |    |
  |      | - RIFE Interpolation (12 -> 24 FPS)        |    |
  |      +---------------------------------------------+    |
  |            |                                            |
  |            v                                            |
  |      RAW_VIDEO_SEGMENTS                                 |
  |                                                         |
  +---> [TRACK B: SONIC PIPELINE] --------------------------+
         CLOUD_AUDIO_SERVER                                  
                                                             
         +---------------------------------------------+     
         | THE SONIC ENGINE                            |     
         | - Layer 1: Ambience (AudioLDM-2)            |     
         | - Layer 2: Foley (Event-Triggered SFX)      |     
         | - Layer 3: Score (MusicGen with Leitmotifs) |     
         | - Layer 4: Dialogue (TTS Generation)        |     
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
END OF DOCUMENT
================================================================================
