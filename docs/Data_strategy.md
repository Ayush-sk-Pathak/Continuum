DATA STRATEGY & MOAT
================================================================================
Continuum Studios — Proprietary Data as Competitive Advantage
Version: 2025.11 (January 2025)
================================================================================

EXECUTIVE SUMMARY
================================================================================
The workflow can be copied. The code can be reverse-engineered. The APIs are 
available to everyone. Our moat is PROPRIETARY DATA accumulated through usage.

This document defines what data we collect, how we store it, and how we convert
it into defensible competitive advantage.

Related: ARCHITECTURE.md (technical implementation)

================================================================================
1. WHY DATA IS THE ONLY REAL MOAT
================================================================================

What's NOT Defensible (Can Be Copied):
┌─────────────────────────────────────────────────────────────────────────────┐
│ Asset                      │ Time to Copy    │ Why Not a Moat              │
├────────────────────────────┼─────────────────┼─────────────────────────────┤
│ Director Agent prompts     │ 1-2 weeks       │ LLM prompts leak/reverse    │
│ ComfyUI workflows          │ Days            │ Open source, visible        │
│ UX flow                    │ 2-4 weeks       │ UI patterns are obvious     │
│ Architecture patterns      │ 1 month         │ Docs could leak             │
│ API integrations           │ Days            │ Same APIs available to all  │
└─────────────────────────────────────────────────────────────────────────────┘

What IS Defensible (Requires Time + Usage):
┌─────────────────────────────────────────────────────────────────────────────┐
│ Asset                      │ Time to Build   │ Why It's a Moat             │
├────────────────────────────┼─────────────────┼─────────────────────────────┤
│ Character LoRA library     │ Months of users │ Switching cost = re-train   │
│ Consistency scoring model  │ 50K+ generations│ Trained on YOUR user prefs  │
│ Prompt enhancement model   │ 100K+ edits     │ Learns what users MEANT     │
│ Style embeddings database  │ 10K+ projects   │ Network effect              │
│ Story structure patterns   │ 5K+ projects    │ "What works" knowledge      │
│ Approval/rejection dataset │ 100K+ signals   │ RLHF gold mine              │
└─────────────────────────────────────────────────────────────────────────────┘

================================================================================
2. THE DATA FLYWHEEL
================================================================================

┌─────────────────────────────────────────────────────────────────────────────┐
│                         THE CONTINUUM FLYWHEEL                              │
│                                                                             │
│    ┌──────────────┐                                                        │
│    │  More Users  │                                                        │
│    └──────┬───────┘                                                        │
│           │                                                                │
│           ▼                                                                │
│    ┌──────────────┐      ┌─────────────────────────────────────┐          │
│    │More Projects │──────│ Proprietary Data Accumulates:       │          │
│    └──────┬───────┘      │ • Character LoRAs (lock-in)         │          │
│           │              │ • Style embeddings (network effect)  │          │
│           │              │ • Approval/rejection signals (RLHF)  │          │
│           │              │ • Prompt→output pairs (training)     │          │
│           │              │ • Project bibles (story structure)   │          │
│           │              └─────────────────────────────────────┘          │
│           ▼                              │                                 │
│    ┌──────────────┐                      │                                 │
│    │Better Models │◄─────────────────────┘                                 │
│    │(trained on   │      Fine-tune:                                        │
│    │ your data)   │      • ConsistencyNet (quality scoring)                │
│    └──────┬───────┘      • PromptEnhancer (auto-improve prompts)           │
│           │              • StoryDirector (scene suggestions)               │
│           │              • StyleMatcher (find similar aesthetics)          │
│           ▼                                                                │
│    ┌──────────────┐                                                        │
│    │Higher Quality│                                                        │
│    │   Output     │                                                        │
│    └──────┬───────┘                                                        │
│           │                                                                │
│           ▼                                                                │
│    ┌──────────────┐                                                        │
│    │  More Users  │ ◄─── Word of mouth, "Continuum just works"            │
│    └──────────────┘                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

The flywheel only spins with DATA. Every user interaction feeds it.

================================================================================
3. DATA COLLECTION REQUIREMENTS
================================================================================

3A. GENERATION LOG (Every Single Generation)
--------------------------------------------------------------------------------
Log EVERYTHING. Storage is cheap. Training data is priceless.

Schema:
```python
generation_log = {
    # === IDENTIFIERS ===
    "generation_id": "uuid",
    "project_id": "uuid",
    "user_id": "uuid",
    "timestamp": "2025-01-04T12:00:00Z",
    
    # === INPUT DATA ===
    "prompt": "A young warrior stands on cliff edge, wind in hair...",
    "negative_prompt": "blurry, low quality...",
    "character_refs": ["char_uuid_1", "char_uuid_2"],
    "location_ref": "loc_uuid_1",
    "style_preset": "anime_shonen",
    "output_format": "video",  # or "manga", "visual_novel"
    
    # === GENERATION PARAMS ===
    "model_used": "wan_2.1_i2v",
    "lora_used": ["ayush_v1.safetensors"],
    "steps": 12,
    "cfg_scale": 7.5,
    "seed": 12345,
    "resolution": "1280x720",
    "duration_sec": 5.0,
    "frames": 81,
    
    # === OUTPUT DATA ===
    "output_path": "s3://outputs/gen_uuid.mp4",
    "output_thumbnail": "s3://thumbs/gen_uuid.png",
    "generation_time_sec": 145.3,
    "cost_usd": 0.07,
    
    # === AUDIT SCORES (Automated) ===
    "identity_score": 0.94,
    "physics_score": 0.87,
    "audit_passed": True,
    "audit_flags": [],
    "reroll_attempt": 1,  # which attempt this was
    "reroll_reason": None,  # or "identity_drift", "physics_violation"
    
    # === USER SIGNALS (Most Valuable) ===
    "user_approved": True,
    "user_rejected": False,
    "time_to_decision_sec": 12.5,
    "user_edited_after": False,
    "user_feedback": "thumbs_up",  # or "thumbs_down", None
    "user_comment": None,  # optional free text
    
    # === CONTEXT ===
    "shot_number": 3,
    "scene_id": "scene_office",
    "is_hero_frame": False,
    "is_bridge_frame": True,
    "previous_shot_id": "gen_uuid_prev",
}
```

3B. USER EDIT LOG (Every Edit/Revision)
--------------------------------------------------------------------------------
When user modifies anything, capture before/after:

```python
edit_log = {
    "edit_id": "uuid",
    "user_id": "uuid",
    "project_id": "uuid",
    "timestamp": "...",
    
    # What was edited
    "edit_type": "prompt_change",  # or "shot_reorder", "duration_change", etc.
    "target_id": "shot_03",
    
    # Before/After
    "before_value": "warrior stands on cliff",
    "after_value": "warrior stands confidently on cliff, smirking",
    
    # Context
    "edit_reason": None,  # optional user explanation
    "generation_before": "gen_uuid_1",
    "generation_after": "gen_uuid_2",  # if they regenerated
}
```

This teaches us: "When users write X, they actually want Y"

3C. CHARACTER DATA (The Lock-In)
--------------------------------------------------------------------------------
```python
character_record = {
    "character_id": "uuid",
    "user_id": "uuid",
    "created_at": "...",
    
    # Identity
    "name": "Ayush",
    "description": "Young Indian man, short black hair, confident...",
    
    # Training data (user uploaded)
    "reference_images": ["s3://refs/img1.png", "s3://refs/img2.png"],
    "reference_count": 5,
    
    # Generated assets (our IP in a sense)
    "lora_path": "s3://loras/char_uuid.safetensors",
    "lora_version": "v1",
    "lora_base_model": "wan_2.1",
    "face_embedding": [0.123, 0.456, ...],  # ArcFace vector
    "style_embedding": [0.789, ...],  # CLIP or custom
    
    # Usage stats
    "times_used": 47,
    "projects_used_in": ["proj_1", "proj_2", ...],
    "avg_identity_score": 0.92,
    
    # Quality signals
    "user_satisfaction": 0.89,  # computed from approvals
    "common_issues": ["side_profile_weak"],
}
```

Switching cost: User with 20 characters = 10+ hours of training invested.

3D. PROJECT BIBLE (Story Structure Data)
--------------------------------------------------------------------------------
```python
project_record = {
    "project_id": "uuid",
    "user_id": "uuid",
    "created_at": "...",
    "completed_at": "...",
    
    # Metadata
    "title": "Matrix Zero",
    "genre": "sci-fi_action",
    "style": "anime_cinematic",
    "output_format": "video",
    "total_duration_sec": 180,
    
    # Structure (anonymized for training)
    "scene_count": 3,
    "shot_count": 12,
    "scene_graph_structure": {...},  # anonymized
    
    # Quality signals
    "overall_satisfaction": 0.91,
    "completion_rate": 1.0,  # finished vs abandoned
    "total_generations": 18,
    "total_rerolls": 4,
    "total_edits": 7,
    
    # Timing
    "time_to_first_approval_sec": 300,
    "total_session_time_sec": 3600,
}
```

After 10K projects: "What story structures lead to highest satisfaction?"

3E. STYLE EMBEDDINGS (Network Effect)
--------------------------------------------------------------------------------
```python
style_record = {
    "style_id": "uuid",
    "name": "cyberpunk_noir",
    "created_by": "user_uuid",  # or "system" for presets
    
    # Embedding
    "clip_embedding": [...],
    "reference_images": ["s3://..."],
    
    # Usage
    "times_used": 234,
    "users_using": 47,
    "avg_satisfaction": 0.88,
    
    # Similar styles (computed)
    "similar_styles": ["style_uuid_2", "style_uuid_3"],
}
```

Network effect: "Creators like you also used these styles"

================================================================================
4. STORAGE ARCHITECTURE
================================================================================

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA STORAGE LAYERS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  HOT STORAGE (Fast Access)                                                  │
│  ├── PostgreSQL: User accounts, projects, characters metadata              │
│  ├── Redis: Active sessions, job queues, rate limits                       │
│  └── Pinecone/Milvus: Vector embeddings (face, style, semantic)            │
│                                                                             │
│  WARM STORAGE (Frequent Access)                                             │
│  ├── S3 Standard: Recent outputs (last 30 days)                            │
│  ├── S3 Standard: Active LoRAs                                             │
│  └── S3 Standard: Reference images                                         │
│                                                                             │
│  COLD STORAGE (Training Data Archive)                                       │
│  ├── S3 Glacier: Old outputs (sampled for training)                        │
│  ├── S3 Glacier: Generation logs (all)                                     │
│  └── BigQuery/Snowflake: Analytics warehouse                               │
│                                                                             │
│  ML TRAINING STORAGE                                                        │
│  ├── S3 + DVC: Versioned training datasets                                 │
│  ├── W&B/MLflow: Experiment tracking                                       │
│  └── Model Registry: Trained model versions                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

Estimated Storage Costs (at scale):
- 10K users, 100K generations/month
- ~500GB new data/month
- ~$500/month storage (S3 + Glacier tiering)
- Vector DB: ~$200/month (Pinecone starter)

================================================================================
5. PROPRIETARY MODELS TO TRAIN
================================================================================

As data accumulates, train these models in sequence:

5A. CONSISTENCYNET (Quality Scoring) — Train at 50K generations
--------------------------------------------------------------------------------
Purpose: Predict "will this output satisfy the user?" better than ArcFace.

Training data:
- Input: Generated frame/video + prompt + character refs
- Label: User approved (1) or rejected (0)

Architecture: Fine-tuned CLIP or custom CNN
Why better than ArcFace: Learns YOUR users' preferences, not generic similarity.

Deployment: Replace/augment ArcFace in audit pipeline
Benefit: Fewer re-rolls, higher first-try approval rate

5B. PROMPTENHANCER (Auto-Improve Prompts) — Train at 100K edits
--------------------------------------------------------------------------------
Purpose: Automatically improve user prompts before generation.

Training data:
- Input: Original user prompt
- Output: Edited prompt (what user changed it to)

Architecture: Fine-tuned LLM (Llama 3 8B or similar)
Example:
  User writes: "warrior on cliff"
  Model outputs: "young warrior standing confidently on cliff edge, 
                  wind flowing through hair, dramatic lighting, 
                  anime style, detailed"

Deployment: Auto-suggest prompt improvements in UI
Benefit: Better results with less user effort

5C. STORYDIRECTOR (Scene Suggestions) — Train at 5K projects
--------------------------------------------------------------------------------
Purpose: Suggest optimal scene breakdowns for a given story.

Training data:
- Input: Story synopsis / script
- Output: Scene graph structure (from successful projects)

Architecture: Fine-tuned LLM
Example:
  User writes: "30-second ad for coffee shop"
  Model suggests: 
    Scene 1: Wide establishing (3s)
    Scene 2: Close-up barista (4s)
    Scene 3: Pour shot (3s)
    ...

Deployment: Power the "Director Agent" suggestions
Benefit: Better defaults, less user editing needed

5D. STYLEMATCHER (Find Similar Aesthetics) — Train at 10K styles
--------------------------------------------------------------------------------
Purpose: Match user's desired style to proven successful styles.

Training data:
- Style embeddings from all projects
- Satisfaction scores per style

Architecture: Contrastive learning on style embeddings
Example:
  User uploads reference image
  System: "Your style is similar to 'cyberpunk_noir' which has 
           92% satisfaction. Use this preset?"

Deployment: Style recommendation in project setup
Benefit: Network effect, users benefit from collective knowledge

5E. LORAQUALITYPREDICTOR — Train at 1K characters
--------------------------------------------------------------------------------
Purpose: Predict LoRA quality before expensive training.

Training data:
- Reference images uploaded
- Resulting LoRA quality scores

Architecture: CNN analyzing reference image quality/diversity
Example:
  User uploads 3 blurry photos
  System: "These refs may produce a weak LoRA. Add 2 more 
           clear front-facing images for best results."

Deployment: Pre-flight check before LoRA training
Benefit: Fewer failed LoRAs, better user experience

================================================================================
6. TRAINING TIMELINE & MILESTONES
================================================================================

┌───────────┬──────────────────┬─────────────────────────────────────────────┐
│ Milestone │ Data Required    │ What We Can Train                           │
├───────────┼──────────────────┼─────────────────────────────────────────────┤
│ Month 2   │ 1K generations   │ Nothing yet — just collect                  │
│ Month 4   │ 10K generations  │ Basic analytics, identify patterns          │
│ Month 6   │ 50K generations  │ ConsistencyNet v1 (quality scoring)         │
│ Month 9   │ 100K generations │ PromptEnhancer v1, ConsistencyNet v2        │
│ Month 12  │ 500K generations │ Full model suite, measurable quality edge   │
│ Month 18  │ 2M generations   │ Strong moat, competitors can't catch up     │
│ Month 24  │ 5M+ generations  │ Industry-leading quality from data alone    │
└───────────┴──────────────────┴─────────────────────────────────────────────┘

Key insight: The moat doesn't exist on day 1. It's built through usage.
Your job is to get users generating content and LOG EVERYTHING.

================================================================================
7. LOCK-IN MECHANISMS
================================================================================

7A. CHARACTER LIBRARY LOCK-IN (Strongest)
--------------------------------------------------------------------------------
User's "cast" lives on Continuum:
- 20 characters = 10+ hours of LoRA training invested
- Moving to competitor = re-train everything from scratch
- LoRAs tied to specific base model versions
- Face embeddings in our vector DB

Switching cost: HIGH (hours of work + quality uncertainty)

7B. PROJECT HISTORY LOCK-IN
--------------------------------------------------------------------------------
All their projects, assets, outputs stored with us:
- Export gives them videos, not the production files
- "Project Bible" (scene graphs, prompts) not easily portable
- Revision history, versions only accessible in platform

Switching cost: MEDIUM (lose workflow, keep outputs)

7C. LEARNED PREFERENCES LOCK-IN
--------------------------------------------------------------------------------
Over time, system learns user's preferences:
- Preferred styles
- Common prompt patterns
- Quality thresholds
- Typical project structures

New platform = cold start, no personalization

Switching cost: MEDIUM (lose "the system knows me")

7D. NETWORK EFFECTS LOCK-IN
--------------------------------------------------------------------------------
As platform grows:
- "Creators like you used these styles"
- Community templates and presets
- Shared character libraries (for teams)
- Collaboration features tied to platform

Switching cost: GROWS WITH PLATFORM SIZE

================================================================================
8. PRIVACY & COMPLIANCE
================================================================================

8A. DATA OWNERSHIP
--------------------------------------------------------------------------------
Clear terms:
- User OWNS their reference images and outputs
- User OWNS their character concepts
- Continuum OWNS trained LoRAs (created by our compute)
- Continuum has LICENSE to use anonymized data for training

User rights:
- Export all outputs (videos, images)
- Delete account = delete all personal data
- Opt-out of training data contribution (premium feature?)

8B. ANONYMIZATION FOR TRAINING
--------------------------------------------------------------------------------
Before using data for model training:
- Strip user IDs, project names
- Anonymize prompts (remove names, identifying info)
- Aggregate statistics only for public reporting
- No individual outputs in training without consent

8C. COMPLIANCE REQUIREMENTS
--------------------------------------------------------------------------------
GDPR (EU Users):
- Right to deletion
- Right to export (data portability)
- Consent for training data usage
- Data processing documentation

CCPA (California):
- Similar to GDPR
- Opt-out of data sale (we don't sell, but document this)

Content Moderation:
- No CSAM (illegal, zero tolerance)
- No deepfakes of real people without consent
- Terms of service enforcement
- Automated + human review for flagged content

8D. DATA SECURITY
--------------------------------------------------------------------------------
- Encryption at rest (S3, databases)
- Encryption in transit (TLS everywhere)
- Access logging (who accessed what)
- Regular security audits
- SOC 2 compliance (target for enterprise sales)

================================================================================
9. MONETIZATION TIED TO DATA
================================================================================

Free tier exists to COLLECT DATA, not as charity:

┌─────────────┬─────────────────────────────────────────────────────────────┐
│ Tier        │ Data Strategy                                               │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ FREE        │ • Limited characters (3)                                    │
│             │ • Watermarked outputs                                       │
│             │ • Data used for training (with consent)                     │
│             │ • Full logging enabled                                      │
│             │ → We get training data, they get free tool                  │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ PRO         │ • Unlimited characters                                      │
│ $20/mo      │ • No watermark                                              │
│             │ • Data used for training (default, can opt-out)             │
│             │ • Priority generation queue                                 │
│             │ → Better experience, still contributing data                │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ STUDIO      │ • Team collaboration                                        │
│ $100/mo     │ • Custom style training                                     │
│             │ • Can opt-out of training contribution                      │
│             │ • API access                                                │
│             │ → Power users, may keep data private                        │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ ENTERPRISE  │ • Dedicated infrastructure                                  │
│ Custom      │ • Data isolation (not used for training)                    │
│             │ • Custom model fine-tuning on THEIR data                    │
│             │ • On-prem deployment option                                 │
│             │ → Premium for data-sensitive clients                        │
└─────────────┴─────────────────────────────────────────────────────────────┘

Key insight: Free users are not freeloaders — they're data contributors.
The more free users, the better our models become, the more Pro users convert.

================================================================================
10. IMPLEMENTATION PRIORITY
================================================================================

DAY 1 (MVP Launch):
├── Basic generation logging (all fields in Section 3A)
├── User edit logging (Section 3B)
├── Character storage (Section 3C)
└── PostgreSQL + S3 setup

MONTH 1:
├── Project bible logging (Section 3D)
├── Analytics dashboard (internal)
└── Data export for users (GDPR compliance)

MONTH 3:
├── Vector DB for embeddings (face, style)
├── Style similarity search
└── Basic recommendation engine

MONTH 6:
├── First model training (ConsistencyNet)
├── A/B test against ArcFace baseline
└── Data warehouse for analytics

MONTH 12:
├── Full model suite deployed
├── Measurable quality advantage
└── Moat established

================================================================================
END OF DOCUMENT
================================================================================