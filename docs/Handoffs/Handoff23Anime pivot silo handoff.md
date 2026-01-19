# ANIME PIVOT SILO - HANDOFF FOR CLAUDE

## ⚠️ CONTEXT: THIS IS A SILOED TASK

You are working on a **focused modification** to the Continuum Engine. You do NOT need to understand or modify the entire codebase. This document gives you everything you need.

**Your task:** Add anime style support by modifying the identity checker to use CLIP instead of ArcFace for anime characters.

---

## 🛑 CRITICAL GUARDRAILS (READ FIRST)

### Golden Rule
**The architecture does NOT change for your updates. Your updates ALIGN with the architecture.**

### Non-Negotiable Constraints

1. **BACKWARD COMPATIBLE — No Breaking Changes**
   - Existing realistic pipeline MUST work exactly as before
   - Default behavior = current behavior
   - `style="anime"` is opt-in, not default
   - All existing tests must still pass
   - If someone runs the system without specifying style, nothing changes

2. **ADDITIVE ONLY — Extend, Don't Replace**
   - Add new CLIP checker alongside ArcFace, don't remove ArcFace
   - Add new config fields, don't rename existing ones
   - Add new functions, don't change signatures of existing ones
   - Think: "AND" not "OR"

3. **MATCH EXISTING PATTERNS — Don't Invent New Ones**
   - Look at how ArcFace checker is structured → CLIP checker follows same pattern
   - Look at how config loads values → style field loads the same way
   - Look at how reviewer calls checkers → style dispatch follows same pattern
   - Copy the code style, error handling, logging patterns

4. **INTERFACE CONTRACTS — Don't Change Function Signatures**
   ```python
   # ❌ WRONG - Changes existing signature
   def check_identity(frame1, frame2, style):  # Added required param
   
   # ✅ RIGHT - Backward compatible
   def check_identity(frame1, frame2, style=None):  # Optional, defaults to existing behavior
   ```

5. **FAIL SAFE — When In Doubt, Use Existing Path**
   ```python
   # If style detection fails, fall back to realistic/ArcFace
   if style is None or style not in ["anime", "webtoon"]:
       return arcface_check(frame1, frame2)  # Safe default
   ```

6. **NO CORE ARCHITECTURE CHANGES**
   - Don't modify the pipeline flow
   - Don't change how Director Agent works
   - Don't change how renderers are called
   - Don't change data structures in base.py
   - Don't add new required fields to existing dataclasses

7. **ISOLATED CHANGES — Your Code Lives in a Box**
   ```
   Your changes touch:
   ├── config.py        → Add field (don't restructure)
   ├── identity_checker.py → Add class (don't modify existing class)
   ├── reviewer.py      → Add dispatch logic (don't change review flow)
   └── models.json      → Add section (don't modify existing entries)
   
   Your changes do NOT touch:
   ├── main.py          → READ ONLY
   ├── base.py          → READ ONLY
   ├── bridge_engine.py → READ ONLY
   ├── wan_renderer.py  → READ ONLY
   └── Everything else  → READ ONLY
   ```

### Before You Write Code, Ask:

| Question | If No → STOP |
|----------|--------------|
| Does existing realistic pipeline still work unchanged? | Refactor your approach |
| Is this additive (new code) not modificative (changing code)? | Find additive approach |
| Does this match existing patterns in the codebase? | Study existing code more |
| Will this work if style field is missing/None? | Add fallback to default |
| Can someone ignore this feature entirely and be unaffected? | Make it more isolated |

### Red Flags — If You're Doing These, STOP

- 🚩 Changing function signatures without default values
- 🚩 Renaming existing config fields
- 🚩 Modifying base.py dataclasses
- 🚩 Changing how main.py orchestrates the pipeline
- 🚩 Removing or commenting out existing ArcFace code
- 🚩 Making style a required field anywhere
- 🚩 Importing new dependencies into files that don't need them
- 🚩 Changing existing test files

---

## PROJECT STRUCTURE (For Context Only)

```
CONTINUUM/
├── docs/
│   ├── Handoffs/              # You are here
│   ├── Marketing+Strategy/
│   ├── SILOS/
│   ├── ARCHITECTURE.md        # Master blueprint (READ if confused)
│   ├── ARCHITECTURE_SUMMARY.md
│   ├── LESSONS_LEARNED.md
│   └── ...
│
├── projects/
│   └── matrix_zero/           # Example project
│       ├── consistency.json
│       └── project.json
│
├── src/
│   ├── audit/                 # ★ YOU MODIFY THIS
│   │   ├── identity_checker.py   ← ADD CLIP path
│   │   ├── physics_checker.py
│   │   └── reviewer.py           ← PASS style param
│   │
│   ├── comfy_client/
│   │   ├── client.py
│   │   └── workflow_loader.py
│   │
│   ├── core/                  # ★ YOU MODIFY THIS
│   │   ├── config.py             ← ADD style field
│   │   ├── checkpointing.py
│   │   ├── error_recovery.py
│   │   ├── job_state.py
│   │   └── model_loader.py
│   │
│   ├── director/              # Context only - DO NOT MODIFY
│   │   ├── consistency_dict.py
│   │   ├── pacer.py
│   │   ├── scene_graph.py
│   │   ├── shot_event_parser.py
│   │   └── world_state.py
│   │
│   ├── memory/                # NOT RELEVANT
│   ├── post/                  # NOT RELEVANT
│   ├── renderers/             # Context only
│   │   ├── base.py               ← CharacterRef definition
│   │   └── wan_renderer.py
│   │
│   ├── sonic/                 # NOT RELEVANT (audio)
│   │
│   └── studio/                # Context only
│       ├── bridge_engine.py
│       └── pass1_generator.py
│
├── tests/                     # NOT RELEVANT
│
├── workflows/
│   ├── shared/                # Bridge workflows
│   ├── wan/                   # Wan generation workflows
│   └── models.json            # ★ YOU MODIFY THIS
│
├── main.py                    # Context: see how reviewer is called
└── pytest.ini
```

---

## FILES TO MODIFY (4 files)

### 1. `src/core/config.py`
**Change:** Add `style` field to configuration

**What to add:**
- Style enum or literal: "anime" | "realistic" | "webtoon"
- Default: "realistic" (backward compatible)
- Style should be readable from project.json or global config

### 2. `src/audit/identity_checker.py`
**Change:** Add CLIP-based identity checking for anime

**Current state:**
- Uses ArcFace (buffalo_l) for face similarity
- Works great for realistic human faces
- FAILS on anime faces (different proportions)

**What to add:**
- New function/class for CLIP-based similarity
- Style-aware dispatch: if anime → use CLIP, else → use ArcFace
- CLIP threshold ~0.85 (tune based on testing)

**Why CLIP works for anime:**
- Trained on diverse images including illustrations
- Semantic similarity, not facial geometry
- Generalizes across art styles

### 3. `src/audit/reviewer.py`
**Change:** Pass style parameter to identity checker

**Current state:**
- Calls identity_checker functions
- Doesn't know about style

**What to add:**
- Read style from config or project
- Pass style to identity checker calls
- Style-aware threshold selection if needed

### 4. `workflows/models.json`
**Change:** Add anime checkpoint configurations

**What to add:**
- Anime SDXL checkpoint path (for hero/bridge frames)
- Example: "animagine-xl-3.1.safetensors" or "ponyDiffusionV6XL.safetensors"
- Style-specific model mappings

---

## FILES FOR CONTEXT ONLY (Do Not Modify)

### `main.py`
Read to understand:
- How reviewer is instantiated and called
- How config flows through the system
- Entry point for the pipeline

### `src/renderers/base.py`
Read to understand:
- `CharacterRef` dataclass (character definitions)
- `RenderResult` dataclass (what identity checker validates)
- Data structures used throughout

### `src/director/consistency_dict.py`
Read to understand:
- How characters are defined and tracked
- What data is available for identity checking

---

## THE PROBLEM YOU'RE SOLVING

**ArcFace fails on anime because:**
- Trained on real human faces
- Expects normal eye/nose/mouth proportions
- Anime has: huge eyes, tiny nose, stylized features
- Results: low/random similarity scores on anime

**CLIP works because:**
- Trained on image-text pairs including illustrations
- Captures semantic "same character" concept
- Not dependent on facial geometry
- Works across art styles

---

## IMPLEMENTATION APPROACH

### Step 1: Add Style to Config
```python
# In config.py - conceptual, adapt to existing patterns
class StyleType(str, Enum):
    REALISTIC = "realistic"
    ANIME = "anime"
    WEBTOON = "webtoon"

# Add to existing config class
style: StyleType = StyleType.REALISTIC
```

### Step 2: Add CLIP Identity Checker
```python
# In identity_checker.py - conceptual
# Add alongside existing ArcFace implementation

class CLIPIdentityChecker:
    """CLIP-based identity checker for anime/stylized content."""
    
    def __init__(self):
        # Load CLIP model (ViT-B/32 or similar)
        pass
    
    def get_embedding(self, image) -> np.ndarray:
        # Extract CLIP image embedding
        pass
    
    def compare(self, frame1, frame2) -> float:
        # Cosine similarity of embeddings
        pass
```

### Step 3: Style-Aware Dispatch
```python
# In identity_checker.py or reviewer.py
def check_identity(frame1, frame2, style: str) -> float:
    if style == "anime":
        return clip_checker.compare(frame1, frame2)
    else:
        return arcface_checker.compare(frame1, frame2)
```

### Step 4: Update models.json
```json
{
  "styles": {
    "realistic": {
      "hero_checkpoint": "sd_xl_base_1.0.safetensors",
      "identity_checker": "arcface"
    },
    "anime": {
      "hero_checkpoint": "animagine-xl-3.1.safetensors",
      "identity_checker": "clip"
    }
  }
}
```

---

## TESTING (No GPU Required)

Test CLIP locally on Mac:
1. Load a few anime character images
2. Run CLIP embedding extraction
3. Compare same character vs different character
4. Verify: same character > 0.85, different < 0.70

```python
# Simple test script concept
from PIL import Image

# Load test images
same_char_1 = Image.open("anime_char_a_pose1.png")
same_char_2 = Image.open("anime_char_a_pose2.png")
diff_char = Image.open("anime_char_b.png")

# Should be > 0.85
score_same = clip_checker.compare(same_char_1, same_char_2)

# Should be < 0.70
score_diff = clip_checker.compare(same_char_1, diff_char)
```

---

## DEPENDENCIES TO ADD

```
# For CLIP support
transformers
torch
```

CLIP runs fine on CPU for inference (no GPU needed for testing).

---

## WHAT SUCCESS LOOKS LIKE

After your changes:
1. `config.py` has style field
2. `identity_checker.py` has CLIP path that activates for anime
3. `reviewer.py` passes style to identity checker
4. `models.json` has anime checkpoint config
5. Test script shows CLIP correctly identifies same/different anime characters

---

## WHAT NOT TO DO

- ❌ Don't modify the Director Agent (scene_graph, world_state, etc.)
- ❌ Don't modify the renderers (wan_renderer, bridge_engine)
- ❌ Don't modify sonic/audio modules
- ❌ Don't change the overall pipeline flow
- ❌ Don't remove ArcFace (keep it for realistic style)

---

## REFERENCE: Current Identity Checker Pattern

Look at existing `identity_checker.py` to match patterns:
- How it loads models
- How it extracts embeddings
- How it compares frames
- Error handling style
- Logging patterns

Your CLIP implementation should follow the same patterns.

---

## QUESTIONS TO ASK IF STUCK

1. "Show me the current identity_checker.py" → understand existing pattern
2. "Show me how reviewer.py calls identity_checker" → understand call chain
3. "Show me config.py" → understand config patterns
4. "Show me base.py CharacterRef" → understand data structures

---

## ✅ VALIDATION CHECKLIST (Must Pass Before Done)

### Backward Compatibility Tests
- [ ] Existing realistic project runs without specifying style
- [ ] `style=None` or missing style → uses ArcFace (existing behavior)
- [ ] No new required parameters in any function
- [ ] No changes to existing dataclass fields in base.py

### New Functionality Tests
- [ ] `style="anime"` → uses CLIP checker
- [ ] CLIP checker returns similarity score 0.0-1.0
- [ ] Same anime character images → score > 0.85
- [ ] Different anime characters → score < 0.70

### Code Quality Tests
- [ ] CLIP checker class follows same pattern as ArcFace checker
- [ ] Error handling matches existing patterns
- [ ] Logging matches existing patterns
- [ ] No new imports in files that don't need CLIP

### Integration Tests
- [ ] reviewer.py correctly dispatches based on style
- [ ] config.py style field has sensible default ("realistic")
- [ ] models.json is valid JSON after edits

### Final Sanity Check
```bash
# These should all still work unchanged:
python -c "from src.core.config import get_config; print('Config OK')"
python -c "from src.audit.identity_checker import ArcFaceChecker; print('ArcFace OK')"
python -c "from src.audit.reviewer import Reviewer; print('Reviewer OK')"

# This should now also work:
python -c "from src.audit.identity_checker import CLIPChecker; print('CLIP OK')"
```

---

## DELIVERABLES

When complete, you should have modified exactly:
1. `src/core/config.py` — Added style field with default
2. `src/audit/identity_checker.py` — Added CLIPChecker class
3. `src/audit/reviewer.py` — Added style-aware dispatch
4. `workflows/models.json` — Added anime checkpoint paths

And created (optional):
5. `tests/test_clip_identity.py` — Test for CLIP checker

**Total: 4-5 files. If you're touching more, you're doing it wrong.**

---

**END OF SILO HANDOFF**