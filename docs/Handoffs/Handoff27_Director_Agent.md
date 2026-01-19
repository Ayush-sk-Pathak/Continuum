# Handoff 27: Director Agent (Script Parser)

**Date:** 2026-01-19
**Status:** Complete (MVP)

---

## Summary

Built the LLM-powered Director Agent that transforms screenplays into production-ready `project.json` files. This is the missing "brain" that enables scaling from manual JSON authoring to automated film production.

**Before:** Human manually writes project.json (hours of work)
**After:** Human writes screenplay → Director Agent → project.json (minutes)

---

## What Was Done

### 1. Director Agent Implementation
- Created `src/director/script_parser.py` with full LLM integration
- Multi-stage parsing pipeline:
  1. **Stage 1**: Extract entities (characters, locations, props)
  2. **Stage 2**: Break script into scenes
  3. **Stage 3**: Break scenes into shots with dialogue
  4. **Stage 4**: Generate image/video prompts for each shot
  5. **Stage 5**: Assemble final project.json

### 2. Multi-Provider Support
- **Claude** (Anthropic) - Recommended for quality
- **GPT-4** (OpenAI) - Alternative, tested working
- **Ollama** (Local) - Placeholder for future

### 3. Style Presets
- `DirectorConfig.for_anime()` - Anime-optimized prompts
- `DirectorConfig.for_realistic()` - Photorealistic prompts
- Customizable style suffixes for prompt generation

### 4. Test Script
- Created `tests/test_director_agent.py`
- Includes sample screenplay "The Last Guardian"
- Validates full pipeline from script to project.json

---

## Files Created/Modified

| File | Changes |
|------|---------|
| `src/director/script_parser.py` | **NEW** - Director Agent implementation |
| `src/director/__init__.py` | Added DirectorAgent exports |
| `tests/test_director_agent.py` | **NEW** - Test script with sample screenplay |
| `projects/last_guardian/project.json` | **NEW** - Generated sample project |

---

## Architecture Position

```
User Script (text/PDF)
        ↓
   Director Agent (LLM)
        ↓
   project.json
        ↓
   ComfyUI Pipeline
        ↓
   Final Video
```

Per ARCHITECTURE.md Section 2A:
> "A Neuro-Symbolic Director Agent (LLM via cloud API) orchestrated from the user's MacBook Air M4."

---

## How to Use

### Command Line
```bash
# Parse a screenplay file
python tests/test_director_agent.py path/to/screenplay.txt

# Uses sample screenplay if no file provided
python tests/test_director_agent.py
```

### Programmatic
```python
from src.director import DirectorAgent, DirectorConfig, LLMProvider

# Configure for anime style
config = DirectorConfig.for_anime()
config.provider = LLMProvider.OPENAI  # or CLAUDE
config.model = "gpt-4o-mini"

# Initialize and parse
director = DirectorAgent(config=config)
project = await director.parse_script(
    script_text="FADE IN: ...",
    project_id="my_film",
    title="My Film Title",
)

# Save to file
from src.director import save_project
save_project(project, "projects/my_film/project.json")
```

---

## Sample Output

From "The Last Guardian" screenplay (1437 chars):

| Metric | Value |
|--------|-------|
| Characters | 2 (Aria, Kai) |
| Locations | 2 (Ancient Temple, Crystal Garden) |
| Props | 2 (Crystalline Sword, Heart of Eternity) |
| Scenes | 2 |
| Shots | 11 |
| Dialogue Lines | 6 |

Generated in ~30 seconds using GPT-4o-mini.

---

## Environment Variables Required

```bash
# One of these (Claude preferred for quality)
ANTHROPIC_API_KEY=sk-ant-...   # For Claude
OPENAI_API_KEY=sk-...          # For GPT-4
```

---

## Known Limitations

### 1. No PDF Parsing Yet
- Currently requires plain text input
- PDF screenplay parsing can be added (PyPDF2/pdfplumber)

### 2. No Character Image Generation
- Director Agent creates character descriptions
- `face_refs` are empty - need manual or automated image generation

### 3. No LoRA Training Integration
- Characters have `lora_path: null`
- Separate step needed to train LoRAs from reference images

### 4. Voice Assignment is Generic
- All characters get default voice (ElevenLabs "adam")
- Need voice matching based on character description

### 5. Prompt Quality Varies
- LLM-generated prompts may need human refinement
- Consider adding a "prompt review" stage

---

## Cost Estimate

| Provider | Model | Cost per Script |
|----------|-------|-----------------|
| OpenAI | gpt-4o-mini | ~$0.01-0.05 |
| OpenAI | gpt-4o | ~$0.10-0.30 |
| Anthropic | claude-sonnet | ~$0.05-0.15 |
| Anthropic | claude-opus | ~$0.20-0.50 |

Costs scale with script length. A 5-page screenplay typically costs <$0.10 with gpt-4o-mini.

---

## Next Steps (Priority Order)

### P0: End-to-End Pipeline Test
1. Generate reference images for Aria and Kai
2. Train LoRAs for both characters
3. Run full rendering pipeline on `last_guardian` project
4. Validate identity consistency across 11 shots

### P1: Voice Matching
- Analyze character descriptions
- Auto-assign appropriate ElevenLabs voices
- Consider: age, gender, personality → voice mapping

### P2: PDF Script Support
- Add PDF parsing with PyPDF2 or pdfplumber
- Handle standard screenplay formatting (Fountain, Final Draft)

### P3: Prompt Refinement Stage
- Add human-in-the-loop prompt review
- Or use LLM to self-critique and improve prompts

### P4: Character Image Generation
- Integrate Flux/SDXL to generate face_refs from descriptions
- Auto-populate bible with generated character portraits

### P5: Creator CLI
- Unified command: `continuum create screenplay.txt`
- Full pipeline: Script → Images → LoRAs → Video

---

## Updated MVP Status

| Component | Status | Notes |
|-----------|--------|-------|
| Director Agent (Script→JSON) | ✅ DONE | This handoff |
| Scene Graph Data Structures | ✅ DONE | Pre-existing |
| Consistency Dictionary | ✅ DONE | Pre-existing |
| ComfyUI Orchestration | ✅ DONE | Pre-existing |
| Identity Pipeline (LoRA+I2V) | ✅ DONE | Anime demo |
| TTS + Ambience + Ducking | ✅ DONE | Handoff 26 |
| 3-5 Minute Film | 🔶 IN PROGRESS | Need to run on longer script |
| RIFE Integration | ❓ TODO | Frame interpolation |
| Creator CLI | ❓ TODO | End-to-end UX |

---

## Demo Requirements Check

From ARCHITECTURE.md:
> "3-5 minute short with:
> - At least one character with synced dialogue
> - Consistent identity across all shots
> - Immersive audio (not silent)"

| Requirement | Status |
|-------------|--------|
| Script → Project automation | ✅ Director Agent |
| 3-5 minutes | 🔶 Ready to test with longer script |
| Consistent identity | ✅ Validated in anime demo |
| Immersive audio | ✅ TTS + Ambience + Ducking |
| Synced dialogue | ⏸️ Deferred (audio plays, no lip movement for anime) |

---

## Verification

Test run verified:
```bash
python tests/test_director_agent.py

# Output:
# Project Summary:
#   Title: The Last Guardian
#   Scenes: 2
#   Shots: 11
#   Characters: 2
#   Locations: 2
# Output: projects/last_guardian/project.json
```

---

## Architecture Alignment

Per ARCHITECTURE.md:
- ✅ Director Agent parses scripts into Scene Graph
- ✅ Maintains Consistency Dictionary (bible)
- ✅ Generates prompts for each shot
- ✅ Extracts dialogue with timing
- ✅ Runs from Mac (API calls to cloud LLM)
- ⏸️ Layout/blockout generation (future enhancement)
