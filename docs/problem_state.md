================================================================================
15. PROBLEM STATUS MATRIX: WHAT'S SOLVED, WHAT'S NOT
This section provides an honest assessment of every consistency problem the engine
must solve, categorized by solution status. Use this to understand:

What problems are handled by following this architecture
What problems need additional research or innovation
What to prioritize for MVP vs later phases


15A. FULLY SOLVED PROBLEMS (Just Implement the Architecture)
These problems have complete solutions specified in this document. Following the
architecture as written will solve them.
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Character Identity Drift ACROSS Shots                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Alice in Shot 1 looks different from Alice in Shot 5            │
│ Cause:      Each video generation "forgets" previous generations            │
│ Solution:   Bridge Frame Engine (Section 3B)                                │
│             - IP-Adapter re-anchors face to canonical reference             │
│             - ControlNet Pose preserves body position                       │
│             - Applied at EVERY shot boundary                                │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Yes - Core value proposition                                    │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Pose/Position Discontinuity Across Cuts                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Character facing left in Shot 1 suddenly facing right in Shot 2 │
│ Cause:      New generation has no knowledge of previous pose                │
│ Solution:   Bridge Frame with ControlNet Pose (Section 3B.5)                │
│             - OpenPose extracts skeleton from last frame                    │
│             - ControlNet forces new frame to match pose                     │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Yes - Part of Bridge Engine                                     │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Color Inconsistency Across Shots                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Shot 1 has warm yellow tones, Shot 2 suddenly cool blue         │
│ Cause:      Each generation produces independent color grading              │
│ Solution:   Post-Production Color Normalization (Section 3K)                │
│             - Histogram matching to Master Shot                             │
│             - Applied during final assembly                                 │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Yes - FFmpeg-based, low complexity                              │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Audio Drowning Dialogue                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Background music too loud, can't hear character speaking        │
│ Cause:      No coordination between audio layers                            │
│ Solution:   Smart Audio Ducking (Section 3K)                                │
│             - Reads Dialogue Map timestamps                                 │
│             - Automatically attenuates music -15dB during speech            │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Yes - PyDub-based, simple implementation                        │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Low Frame Rate / Choppy Motion                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Video looks jerky at 12fps                                      │
│ Cause:      Generating at high FPS is expensive                             │
│ Solution:   RIFE Interpolation (Section 3G)                                 │
│             - Generate at 12fps (saves 50% GPU cost)                        │
│             - Interpolate to 24fps in post                                  │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Yes - Well-tested tool                                          │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Flicker / Temporal Instability Within Shots                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Objects shimmer, textures pop between frames                    │
│ Cause:      Frame-by-frame generation lacks temporal coherence              │
│ Solution:   Pass 2 Refinement (Section 3F) + TiARA (Research.md)            │
│             - Vid2Vid / FreeLong++ for flicker reduction                    │
│             - TiARA attention reweighting (plug-in, no training)            │
│ Status:     ✅ FULLY SOLVED                                                 │
│ MVP:        Pass 2 is MVP; TiARA is Phase 2 enhancement                     │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Chunk Boundary Artifacts (StreamingT2V Seams)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Visible "jump" every 12 seconds where chunks join               │
│ Cause:      Each chunk generated independently                              │
│ Solution:   CoNo - Consistency Noise Injection (Section 3F)                 │
│             - Blends noise at chunk boundaries                              │
│             - Regularizes content transitions                               │
│ Status:     ✅ FULLY SOLVED (when CoNo nodes available)                     │
│ MVP:        Phase 2 - Depends on ComfyUI node availability                  │
└─────────────────────────────────────────────────────────────────────────────┘

15B. PARTIALLY SOLVED PROBLEMS (Solution Exists, Gaps Remain)
These problems have solutions that work in most cases, but edge cases or
quality limitations remain. The architecture addresses them, but expect
some manual intervention or quality tradeoffs.
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Character Identity Drift WITHIN a Single Shot                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Alice looks correct in frame 1, drifts by frame 30              │
│ Cause:      Video models have no persistent identity memory                 │
│                                                                             │
│ Current Solution:                                                           │
│   - Max shot duration 12 seconds (within model stability window)            │
│   - ArcFace audit (first vs last frame, threshold 0.7)                      │
│   - Auto re-roll if drift detected (max 3 attempts)                         │
│                                                                             │
│ What's Missing:                                                             │
│   - LoRA training pipeline (would reduce drift significantly)               │
│   - Real-time drift detection (currently post-render only)                  │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Without LoRA, ~10-15% of shots may need re-roll                 │
│ MVP:        Yes (12s limit + audit). LoRA is Phase 2.                       │
│ Research:   None needed - LoRA training is well-documented                  │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Scene Layout Preservation (Spatial Relationships)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Table was on left, now it's on right                            │
│ Cause:      New generation doesn't know scene geography                     │
│                                                                             │
│ Current Solution:                                                           │
│   - ControlNet Depth in Bridge Frame (Section 3B.5)                         │
│   - Preserves near/far spatial relationships                                │
│                                                                             │
│ What's Missing:                                                             │
│   - Depth map only preserves LAYOUT, not APPEARANCE                         │
│   - Table position preserved, but table STYLE may change                    │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Layout correct, but textures/colors may shift                   │
│ MVP:        Yes - ControlNet Depth is implemented                           │
│ Research:   See "Background Preservation" in UNSOLVED section               │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Facial Expression Preservation Across Cuts                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Character smiling at end of Shot 1, neutral at start of Shot 2  │
│ Cause:      IP-Adapter uses canonical (often neutral) face reference        │
│                                                                             │
│ Current Solution:                                                           │
│   - OpenPose includes face landmarks (eyes, mouth position)                 │
│   - ControlNet Pose partially preserves expression                          │
│                                                                             │
│ What's Missing:                                                             │
│   - Subtle expressions (smile intensity, eye direction) not captured        │
│   - OpenPose face landmarks are coarse                                      │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Major expressions preserved, subtle ones lost                   │
│ MVP:        Accept limitation for MVP                                       │
│ Research:   Face landmark ControlNet or expression embeddings (Phase 3+)    │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Object/Prop Position Tracking (Narrative Continuity)               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Alice picks up sword in Shot 3, but Shot 4 shows sword on table │
│ Cause:      System doesn't track state changes from events                  │
│                                                                             │
│ Current Solution:                                                           │
│   - World State Tracker (Section 2A) maintains object positions             │
│   - Shot Event Parser extracts actions from descriptions                    │
│   - State injected into prompts for next shot                               │
│                                                                             │
│ What's Missing:                                                             │
│   - Prompt-only enforcement is UNRELIABLE                                   │
│   - Model may ignore "sword in hand" instruction                            │
│   - No visual conditioning for prop positions                               │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        System KNOWS correct state, but can't ENFORCE it visually       │
│ MVP:        Yes - World State tracking is implemented                       │
│ Research:   See "Prop Identity" in UNSOLVED section                         │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Physics Violations (Gravity, Collisions, Teleportation)            │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Object floats in mid-air, person walks through wall             │
│ Cause:      Video models don't understand physics                           │
│                                                                             │
│ Current Solution:                                                           │
│   - Physics Reviewer (Section 2A) detects violations                        │
│   - YOLOv8 + ByteTrack for object permanence                                │
│   - RAFT optical flow for flicker/teleportation                             │
│   - Gravity heuristics for floating objects                                 │
│   - Auto re-roll on detection (max 3 attempts)                              │
│                                                                             │
│ What's Missing:                                                             │
│   - Can only DETECT and RE-ROLL, cannot FIX                                 │
│   - Re-roll may produce same violation                                      │
│   - Complex physics (cloth, water) not covered                              │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Detection works, but fixing relies on luck (re-roll)            │
│ MVP:        Detection is MVP; advanced fixes are Phase 3+                   │
│ Research:   Physics-aware generation is active research area                │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Multi-Scene Prompt Transitions                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Jarring change when scene/prompt changes mid-video              │
│ Cause:      Abrupt switch in text conditioning                              │
│                                                                             │
│ Current Solution:                                                           │
│   - Bridge Frame provides visual anchor between scenes                      │
│   - CoNo smooths noise at boundaries                                        │
│                                                                             │
│ What's Missing:                                                             │
│   - PromptBlend (from Research.md) not implemented                          │
│   - Text embedding interpolation would smooth semantic transitions          │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Visual transition smooth, semantic transition can be abrupt     │
│ MVP:        Accept limitation for MVP                                       │
│ Research:   PromptBlend is documented in Research.md, implement Phase 2     │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Multi-Character Identity Bleeding                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Alice and Bob in same shot start looking similar                │
│ Cause:      Model blends identities when multiple subjects present          │
│                                                                             │
│ Current Solution:                                                           │
│   - Regional Prompting (Section 3D)                                         │
│   - Director defines bounding boxes per character                           │
│   - LoRA applied only within character's region                             │
│                                                                             │
│ What's Missing:                                                             │
│   - ComfyUI Regional Prompter integration not complete                      │
│   - Complex interactions (characters crossing paths) still problematic      │
│                                                                             │
│ Status:     ⚠️ PARTIALLY SOLVED                                             │
│ Gap:        Static scenes work, dynamic interactions may bleed              │
│ MVP:        Phase 2 - Requires Regional Prompter node setup                 │
│ Research:   Attention masking techniques available, needs integration       │
└─────────────────────────────────────────────────────────────────────────────┘

15C. UNSOLVED PROBLEMS (Requires Research / Innovation)
These problems do NOT have complete solutions in current research or this
architecture. They require either new techniques, experimental approaches,
or acceptance of limitations.
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Background/Scene Preservation During Bridge Frame                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Shot 1 has yellow kitchen, Bridge Frame produces blue kitchen   │
│ Cause:      High denoise in Bridge Frame regenerates entire image           │
│             IP-Adapter fixes face but destroys background                   │
│                                                                             │
│ Why Current Architecture Doesn't Solve It:                                  │
│   - bridge_full.json regenerates ENTIRE frame                               │
│   - High denoise (0.7+) needed for strong face fix                          │
│   - High denoise destroys background pixels                                 │
│   - ControlNet Depth preserves LAYOUT but not APPEARANCE                    │
│   - "Environment IP-Adapter" mentioned but NOT SPECIFIED how to combine     │
│     with face IP-Adapter (they compete in attention layers)                 │
│                                                                             │
│ Potential Solutions (NEED RESEARCH/TESTING):                                │
│                                                                             │
│   Option A: Face-Only Inpainting                                            │
│   - Detect face bounding box in source frame                                │
│   - Create mask for face region only                                        │
│   - Inpaint face with IP-Adapter, keep rest pixel-perfect                   │
│   - Complexity: Medium (new workflow needed)                                │
│   - This IS mentioned in Section 5 as "Regional Repair" but for glitch      │
│     fixing, not bridge frames. Needs to be adapted for bridge use.          │
│                                                                             │
│   Option B: EbSynth Texture Propagation (from Research.md)                  │
│   - Generate bridge frame (loses background)                                │
│   - Use EbSynth to propagate original background onto new frame             │
│   - Keeps face from bridge, background from source                          │
│   - Complexity: Medium (external tool integration)                          │
│                                                                             │
│   Option C: LoRA + Lower Denoise                                            │
│   - Train LoRA for strong identity lock                                     │
│   - Use low denoise (0.3) in bridge frame                                   │
│   - Face stays correct (LoRA), background survives (low denoise)            │
│   - Complexity: Low (parameter tuning) but requires LoRA training           │
│                                                                             │
│   Option D: ControlNet Tile / Reference                                     │
│   - Add ControlNet Tile to preserve textures from source                    │
│   - Combine with existing Pose + Depth + IP-Adapter                         │
│   - May conflict with other ControlNets (too many constraints)              │
│   - Complexity: Medium (workflow modification)                              │
│                                                                             │
│ Status:     ❌ UNSOLVED                                                     │
│ Impact:     HIGH - Breaks scene continuity, visible to viewers              │
│ MVP:        Accept limitation OR implement Option C (LoRA + low denoise)    │
│ Research:   Test Options A-D, measure quality tradeoffs                     │
│ Priority:   HIGH - Should be addressed in Phase 2                           │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Prop Visual Identity (Red Mug Stays Red Mug)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Red mug in Shot 1 becomes blue vase in Shot 2                   │
│ Cause:      No visual conditioning mechanism for props                      │
│             World State only provides TEXT description to prompt            │
│             Models often ignore or misinterpret prop descriptions           │
│                                                                             │
│ Why Current Architecture Doesn't Solve It:                                  │
│   - World State says "red mug on table" in prompt                           │
│   - Model may generate blue mug, or vase, or nothing                        │
│   - No visual reference for props (IP-Adapter used only for faces)          │
│   - No per-object conditioning mechanism                                    │
│                                                                             │
│ Potential Solutions (NEED RESEARCH/TESTING):                                │
│                                                                             │
│   Option A: Per-Prop IP-Adapter (Multi-Subject)                             │
│   - Use IP-Adapter for mug, not just face                                   │
│   - Problem: IP-Adapter designed for single subject                         │
│   - Multi-IP-Adapter experimental, may cause conflicts                      │
│   - Complexity: High                                                        │
│                                                                             │
│   Option B: Prop LoRA Training                                              │
│   - Train small LoRA for important props ("red_mug_v1")                     │
│   - Invoke LoRA when prop should appear                                     │
│   - Problem: Expensive (training per prop), doesn't control position        │
│   - Complexity: High                                                        │
│                                                                             │
│   Option C: 3D Blockout with Object Masks                                   │
│   - Already in architecture (Section 3C) for positioning                    │
│   - Extend: Use object silhouettes as hard masks                            │
│   - Fill each mask region with prompt for that object                       │
│   - Problem: Complex workflow, regional prompting limitations               │
│   - Complexity: High                                                        │
│                                                                             │
│   Option D: Accept Limitation + Post-Fix                                    │
│   - Let props vary slightly between shots                                   │
│   - Use video editing to manually fix critical props                        │
│   - Problem: Breaks automation promise                                      │
│   - Complexity: Low (no dev work, just workflow adjustment)                 │
│                                                                             │
│ Status:     ❌ UNSOLVED                                                     │
│ Impact:     MEDIUM - Noticeable but less critical than character identity   │
│ MVP:        Accept limitation (Option D) for MVP                            │
│ Research:   Experiment with Multi-IP-Adapter, monitor research advances     │
│ Priority:   MEDIUM - Phase 3+                                               │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Continuous Shots Beyond 12 Seconds                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    User wants 30-second continuous take, we cut at 12s             │
│ Cause:      FUNDAMENTAL MODEL LIMITATION - all current models drift         │
│                                                                             │
│ Why This Cannot Be "Solved":                                                │
│   - Video diffusion models have finite context windows                      │
│   - Identity drift is inherent to autoregressive generation                 │
│   - Even Sora/Veo have this limitation (just longer before drift)           │
│   - This is a PHYSICS of the technology, not a bug                          │
│                                                                             │
│ Architecture Workaround (Not Solution):                                     │
│   - Max 12s shots (within proven stability window)                          │
│   - Bridge Frame resets identity at each cut                                │
│   - Smart Cuts timed to natural edit points (pacing)                        │
│   - Viewer doesn't notice cuts if pacing is cinematic                       │
│                                                                             │
│ Future Possibilities (Research-Dependent):                                  │
│   - Owl-1 World Model (from Research.md) - latent state persistence         │
│   - Context-as-Memory retrieval (inject past frames as conditioning)        │
│   - Better base models (Veo 2, Sora 2) may extend stability window          │
│                                                                             │
│ Status:     ❌ UNSOLVED (Fundamental Limitation)                            │
│ Impact:     LOW - Workaround is acceptable for most use cases               │
│ MVP:        Use 12s limit + Bridge Frame (workaround is MVP)                │
│ Research:   Monitor Owl-1 and similar world-model research                  │
│ Priority:   LOW - Workaround is effective                                   │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Complex Physics Simulation (Cloth, Water, Fire)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Dress doesn't flow naturally, water behaves oddly               │
│ Cause:      Video models learn physics from data, not simulation            │
│                                                                             │
│ Why This Cannot Be Fully Solved:                                            │
│   - Physics understanding is emergent, not guaranteed                       │
│   - Training data has physics biases (most videos are "normal")             │
│   - No mechanism to inject physics rules into generation                    │
│                                                                             │
│ Current Mitigation:                                                         │
│   - Physics Reviewer flags obvious violations                               │
│   - Re-roll and hope for better result                                      │
│   - Use Veo/Sora (Pro Lane) which have better physics training              │
│                                                                             │
│ Status:     ❌ UNSOLVED (Fundamental Limitation)                            │
│ Impact:     MEDIUM - Depends on content type                                │
│ MVP:        Accept limitation, use Pro Lane for physics-heavy content       │
│ Research:   Physics-guided diffusion is active research, years away         │
│ Priority:   LOW - Outside our control                                       │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Precise Camera Control (Exact Movements)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ Symptom:    Prompt says "slow pan left" but camera does something else      │
│ Cause:      Camera control via text prompt is imprecise                     │
│                                                                             │
│ Why Current Architecture Doesn't Fully Solve It:                            │
│   - Camera instructions in prompt are suggestions, not commands             │
│   - Models interpret "pan left" differently                                 │
│   - No frame-level camera trajectory control                                │
│                                                                             │
│ Potential Solutions:                                                        │
│   - ControlNet with camera trajectory (research exists, not mature)         │
│   - Motion LoRA for specific camera movements                               │
│   - 3D-aware generation (NeRF-based, very complex)                          │
│                                                                             │
│ Status:     ❌ UNSOLVED                                                     │
│ Impact:     MEDIUM - Limits cinematic control                               │
│ MVP:        Accept approximate camera control                               │
│ Research:   Monitor CameraCtrl and similar research                         │
│ Priority:   MEDIUM - Phase 3+                                               │
└─────────────────────────────────────────────────────────────────────────────┘

15D. PROBLEM PRIORITY MATRIX FOR DEVELOPMENT
Use this matrix to prioritize development efforts:
┌─────────────────────────────────────────────────────────────────────────────┐
│                        IMPACT vs SOLVABILITY MATRIX                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  HIGH IMPACT    │ Character Drift    │ Background Loss   │ Prop Identity   │
│                 │ (Across Shots)     │ (Bridge Frame)    │ (Red Mug)       │
│                 │ ✅ SOLVED          │ ❌ UNSOLVED       │ ❌ UNSOLVED     │
│                 │ → MVP              │ → Phase 2 (HIGH)  │ → Phase 3       │
│                 │                    │                   │                 │
├─────────────────┼────────────────────┼───────────────────┼─────────────────┤
│                 │                    │                   │                 │
│  MEDIUM IMPACT  │ Pose Continuity   │ Expression Loss   │ Physics Errors  │
│                 │ ✅ SOLVED          │ ⚠️ PARTIAL        │ ⚠️ PARTIAL      │
│                 │ → MVP              │ → Phase 3         │ → Accept        │
│                 │                    │                   │                 │
├─────────────────┼────────────────────┼───────────────────┼─────────────────┤
│                 │                    │                   │                 │
│  LOW IMPACT     │ Color Matching    │ Flicker           │ >12s Shots      │
│                 │ ✅ SOLVED          │ ✅ SOLVED         │ ❌ FUNDAMENTAL  │
│                 │ → MVP              │ → MVP             │ → Accept        │
│                 │                    │                   │                 │
└─────────────────┴────────────────────┴───────────────────┴─────────────────┘
EASY TO SOLVE ←───────────────→ HARD TO SOLVE

15E. MVP SCOPE DEFINITION (Based on Problem Status)
MVP MUST INCLUDE (Problems are Solved):
✅ Character identity consistency across shots (Bridge Frame)
✅ Pose/position continuity (ControlNet Pose)
✅ Basic scene layout preservation (ControlNet Depth)
✅ Color consistency across shots (Histogram matching)
✅ Audio ducking for dialogue (PyDub)
✅ Frame rate smoothing (RIFE interpolation)
✅ Identity drift detection (ArcFace audit)
✅ Basic physics violation detection (YOLOv8 + heuristics)
MVP SHOULD ACCEPT LIMITATIONS:
⚠️ Background may change colors/textures at cuts
⚠️ Props may change appearance between shots
⚠️ Subtle expressions may not preserve
⚠️ Maximum 12-second continuous shots
⚠️ Multi-character scenes may have some identity bleeding
⚠️ Physics violations fixed by re-roll (luck-based)
PHASE 2 PRIORITIES (Address Partially Solved):
→ LoRA training pipeline (reduces within-shot drift)
→ Face-only inpainting for Bridge Frame (preserves background)
→ TiARA integration (improves flicker reduction)
→ PromptBlend integration (smoother scene transitions)
→ Regional Prompter integration (better multi-character)
PHASE 3+ RESEARCH (Address Unsolved):
→ Multi-subject IP-Adapter for props
→ Expression preservation techniques
→ Advanced physics-aware generation
→ Camera trajectory control

15F. DECISION TREE: WHEN TO WORRY ABOUT EACH PROBLEM
Use this to decide if a problem affects your specific use case:
SINGLE CHARACTER, SIMPLE SCENE (e.g., talking head, interview):

Character drift across shots: SOLVED ✅
Background preservation: MINOR ISSUE (consistent background anyway)
Props: N/A
Physics: N/A
→ MVP handles this well

SINGLE CHARACTER, CHANGING SCENES (e.g., character walking through locations):

Character drift across shots: SOLVED ✅
Background preservation: ISSUE (each location may look different)
Props: MINOR ISSUE
→ Phase 2 features help significantly

MULTIPLE CHARACTERS, SINGLE SCENE (e.g., two people talking):

Character drift: SOLVED ✅
Identity bleeding: ISSUE when characters interact
Background: MINOR ISSUE
→ Need Regional Prompter (Phase 2)

PROP-HEAVY NARRATIVE (e.g., character uses specific objects):

Character drift: SOLVED ✅
Prop identity: MAJOR ISSUE
Object permanence: ISSUE
→ Accept limitations or wait for Phase 3+

ACTION/PHYSICS CONTENT (e.g., stunts, effects, water scenes):

Physics violations: MAJOR ISSUE
Complex motion: ISSUE
→ Use Pro Lane (Veo/Sora) or accept re-roll lottery