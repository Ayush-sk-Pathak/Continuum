# Handoff Templates

Use these templates when moving between the Main Project and Silos.

---

## Template 1: Assignment (Main → Silo)

Copy this to the silo project when starting work:

```
## ASSIGNMENT FROM PROJECT LEAD

**Silo:** [Core / Director / Studio / Audit / Sonic / Post]
**Date:** [Date]

### Task
[What needs to be done]

### Success Criteria
- [ ] [How to know it's done]
- [ ] [Measurable outcome]

### Files Likely to Change
- `path/to/file.py`
- `path/to/other.py`

### Context
[Any background the silo needs to know]

### Report Back
- What's working
- What's not working
- Test results / scores
- Recommended next steps
```

---

## Template 2: Handoff (Silo → Main)

Copy this back to the main project when work is complete:

```
## HANDOFF TO PROJECT LEAD

**From Silo:** [Core / Director / Studio / Audit / Sonic / Post]
**Date:** [Date]
**Assignment:** [Brief description of what was assigned]

### Completed
- [x] [What was done]
- [x] [Files changed]

### Working
- [What's functioning correctly]
- [Test results, scores, metrics]

### Not Working / Blockers
- [What failed or is incomplete]
- [What's blocking further progress]

### Files Changed
```
src/path/to/file.py - [what changed]
src/path/to/other.py - [what changed]
```

### Recommended Next Steps
1. [What should happen next]
2. [Priority order if multiple items]

### Questions for Project Lead
- [Any decisions needed]
- [Any clarifications required]
```

---

## Template 3: Quick Status Update

For minor updates that don't need a full handoff:

```
## STATUS UPDATE

**Silo:** [Name]
**Task:** [What you're working on]
**Status:** [In Progress / Blocked / Complete]
**Notes:** [Brief update]
```

---

## Example: Full Workflow

### 1. Main Project assigns work:

```
## ASSIGNMENT FROM PROJECT LEAD

**Silo:** Studio
**Date:** Jan 2, 2026

### Task
Implement HunyuanCustomRenderer.render_i2v() method to generate video from face reference + prompt.

### Success Criteria
- [ ] Can generate 5-second video from face ref
- [ ] ArcFace score ≥ 0.60 against reference
- [ ] No crashes on 4x RTX 4090

### Files Likely to Change
- `src/renderers/hunyuan_custom_renderer.py`
- `workflows/hunyuan_custom/pass1_img2vid.json`

### Context
We pivoted from Wan to HunyuanCustom for better identity (0.627 vs 0.204 ArcFace). The model uses `<image>` token for native identity injection. See MODEL_PIVOT.md for full details.

### Report Back
- Does basic generation work?
- What ArcFace score did you get?
- How long does generation take?
- Any issues with the workflow?
```

### 2. Developer works in Studio silo...

### 3. Developer returns with handoff:

```
## HANDOFF TO PROJECT LEAD

**From Silo:** Studio
**Date:** Jan 3, 2026
**Assignment:** Implement HunyuanCustomRenderer.render_i2v()

### Completed
- [x] Basic render_i2v() implementation
- [x] Workflow JSON created and tested
- [x] Face reference injection via <image> token

### Working
- Video generation completes (~4 min on 4x4090)
- Face is recognizable in output
- ArcFace score: 0.58 (slightly below 0.60 target)

### Not Working / Blockers
- Seed parameter not being applied (random each time)
- Multi-GPU utilization unclear (may only use 1 GPU)

### Files Changed
```
src/renderers/hunyuan_custom_renderer.py - Added render_i2v(), _build_workflow()
workflows/hunyuan_custom/pass1_img2vid.json - New workflow file
```

### Recommended Next Steps
1. Fix seed parameter (check workflow placeholder)
2. Increase id_weight from 1.0 to 1.2 to boost identity
3. Test with character LoRA to see if it improves score

### Questions for Project Lead
- Should we proceed with 0.58 score or block until ≥0.60?
- Priority: fix seed or boost identity first?
```

### 4. Main Project updates state and assigns next task...