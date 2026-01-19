# CLIP Threshold Validation for Anime Identity Checking

## Overview

This guide explains how to validate that the CLIP identity checker threshold (currently **0.85**) is appropriate for anime/stylized content in the Continuum Engine.

**Architecture Reference:** ARCHITECTURE.md Section 16G (Multi-Format Output Strategy)

## Why This Matters

The Continuum Engine uses different identity checkers for different styles:
- **Realistic**: ArcFace (threshold 0.50) - uses facial geometry
- **Anime/Webtoon**: CLIP (threshold 0.85) - uses semantic similarity

CLIP works for anime because it captures the concept of "same character" semantically, rather than relying on real human facial proportions. However, the threshold needs validation with real anime images to ensure:
1. Same character → similarity > 0.85 (identity preserved)
2. Different characters → similarity < 0.70 (clear separation)

## Prerequisites

### On RunPod

1. **Install dependencies:**
   ```bash
   pip install transformers torch pillow
   ```

2. **Prepare test images:**
   - Collect anime character images (PNG/JPG)
   - Organize by character (see structure below)
   - Upload to RunPod at `/workspace/anime_test_images/`

### On Local Machine

1. **Dependencies already installed** (if you can import from src.audit)
2. **Prepare test images locally**

## Image Directory Structure

### Option 1: Auto-Discovery (Recommended)

Organize images by character name. The script will automatically generate test pairs.

```
anime_test_images/
├── luffy/
│   ├── front_view.png          # Same character, different poses
│   ├── side_profile.png
│   ├── action_pose.png
│   └── close_up.png
├── naruto/
│   ├── standing.png             # Different character
│   ├── running.png
│   └── face_detail.png
├── goku/
│   ├── normal.png               # Another different character
│   └── super_saiyan.png
└── mikasa/
    ├── pose1.png
    └── pose2.png
```

**Test Cases Generated:**
- **Same character pairs** (within each folder):
  - `luffy/front_view.png` vs `luffy/side_profile.png` → expect similarity > 0.85
  - `luffy/front_view.png` vs `luffy/action_pose.png` → expect similarity > 0.85
  - etc. (all pairwise combinations)

- **Different character pairs** (across folders):
  - `luffy/front_view.png` vs `naruto/standing.png` → expect similarity < 0.70
  - `luffy/front_view.png` vs `goku/normal.png` → expect similarity < 0.70
  - etc. (representative pairs between characters)

### Option 2: Manual Configuration

Create `test_cases.json` for explicit control:

```json
{
  "test_cases": [
    {
      "name": "luffy_front_vs_side",
      "source": "luffy/front.png",
      "target": "luffy/side.png",
      "expected": "same_character",
      "category": "same_pose_variation"
    },
    {
      "name": "luffy_vs_naruto",
      "source": "luffy/front.png",
      "target": "naruto/standing.png",
      "expected": "different_character",
      "category": "different_character"
    },
    {
      "name": "occluded_test",
      "source": "luffy/full_face.png",
      "target": "luffy/partially_occluded.png",
      "expected": "same_character",
      "category": "edge_case"
    }
  ]
}
```

Then run with `--manual-config` flag.

## Running the Validation

### Basic Usage (Auto-Discovery)

```bash
# On RunPod
python tests/validate_clip_threshold.py --images-dir /workspace/anime_test_images

# On local machine
python tests/validate_clip_threshold.py --images-dir ./anime_test_images
```

### With Custom Threshold

Test a different threshold:

```bash
python tests/validate_clip_threshold.py \
    --images-dir /workspace/anime_test_images \
    --threshold 0.82
```

### Generate Detailed Report

Save JSON report for further analysis:

```bash
python tests/validate_clip_threshold.py \
    --images-dir /workspace/anime_test_images \
    --report clip_validation_report.json
```

### With Manual Test Cases

```bash
python tests/validate_clip_threshold.py \
    --images-dir /workspace/anime_test_images \
    --manual-config
```

### Verbose Logging

```bash
python tests/validate_clip_threshold.py \
    --images-dir /workspace/anime_test_images \
    --verbose
```

## Interpreting Results

### Console Output

The script prints a detailed report:

```
================================================================================
CLIP THRESHOLD VALIDATION REPORT
================================================================================

Threshold Tested: 0.85
Total Test Cases: 24
Accuracy: 95.8%
  ✓ Correct: 23
  ✗ False Positives: 0
  ✗ False Negatives: 1

--------------------------------------------------------------------------------
SIMILARITY STATISTICS
--------------------------------------------------------------------------------

Same Character Pairs:
  Average: 0.8923
  Range: 0.8412 - 0.9534

Different Character Pairs:
  Average: 0.6234
  Range: 0.5821 - 0.7012

Separation Margin: 0.2689

--------------------------------------------------------------------------------
RECOMMENDATIONS
--------------------------------------------------------------------------------

✅ Threshold 0.85 performs well (balanced errors)
✅ Good separation: 0.269 gap between same/different averages
💡 Optimal threshold estimate: 0.79 (midpoint between max different and min same)

--------------------------------------------------------------------------------
DETAILED TEST RESULTS
--------------------------------------------------------------------------------

SAME POSE VARIATION:
  ✓ luffy_pose1_vs_pose2: 0.8923
  ✓ luffy_pose1_vs_pose3: 0.9012
  ✗ luffy_pose2_vs_pose3: 0.8412  ← False negative (below threshold)
  ...

DIFFERENT CHARACTER:
  ✓ luffy_vs_naruto: 0.6234
  ✓ luffy_vs_goku: 0.5982
  ...
```

### What to Look For

1. **Accuracy**: Should be >95% for confidence
   - <85%: Threshold needs adjustment or CLIP may not be suitable
   - 85-95%: Marginal, consider gathering more diverse test cases
   - >95%: Good, threshold is appropriate

2. **False Positives vs False Negatives**:
   - **False Positives** (different characters marked as same): More dangerous, could cause identity drift
   - **False Negatives** (same character marked as different): Less dangerous, just triggers re-roll
   - **Balance**: Slightly favor false negatives over false positives

3. **Separation Margin**:
   - >0.15: Excellent separation
   - 0.08-0.15: Moderate, workable
   - <0.08: Poor, may need different approach or better test cases

4. **Score Ranges**:
   - Same character min should be > 0.80
   - Different character max should be < 0.75
   - **No overlap** between ranges is ideal

### Recommendations

The script automatically suggests:
- ✅ **Keep current threshold** if accuracy is high and errors balanced
- ❌ **Lower threshold** (-0.02) if too many false negatives
- ❌ **Raise threshold** (+0.02) if too many false positives
- 💡 **Optimal threshold** based on mathematical midpoint

## Example Workflow

### Step 1: Collect Test Images

Gather 3-5 images per character from your target anime style:
- Different poses (front, side, action)
- Different expressions (neutral, smiling, angry)
- Different scales (close-up, medium shot)
- Include 3-5 different characters

**Minimum recommended**: 3 characters × 3 poses each = 9 images total

### Step 2: Upload to RunPod

```bash
# On local machine
scp -r anime_test_images/ root@runpod-instance:/workspace/

# Or use RunPod's web upload
```

### Step 3: Run Validation

```bash
# SSH into RunPod
ssh root@runpod-instance

# Install dependencies (if not already installed)
pip install transformers torch pillow

# Run validation
cd /workspace/Continuum
python tests/validate_clip_threshold.py \
    --images-dir /workspace/anime_test_images \
    --report validation_report.json
```

### Step 4: Analyze Results

1. Check accuracy (target: >95%)
2. Review false positives/negatives
3. Look at score distributions
4. Follow recommendations

### Step 5: Adjust Configuration (If Needed)

If validation suggests a different threshold:

**File**: `src/core/config.py` (line 88)

```python
clip_identity_threshold: float = Field(
    default=0.82,  # Adjusted from 0.85 based on validation
    ge=0.0,
    le=1.0,
    description="CLIP similarity threshold for anime/stylized styles"
)
```

**File**: `workflows/models.json` (line 253)

```json
"anime": {
    "identity_checker": "clip",
    "identity_threshold": 0.82,  // Adjusted
    ...
}
```

## Troubleshooting

### "No test cases found"

- **Cause**: Images not organized correctly or no images found
- **Fix**: Check directory structure, ensure PNG/JPG files exist

### "Failed to load CLIP model"

- **Cause**: Missing dependencies
- **Fix**: `pip install transformers torch pillow`

### "CUDA out of memory"

- **Cause**: GPU memory full
- **Fix**: Use smaller CLIP model or run on CPU:
  ```python
  # In validate_clip_threshold.py, modify CLIPIdentityChecker initialization:
  checker = CLIPIdentityChecker(threshold=threshold, device="cpu")
  ```

### "All scores are very similar"

- **Cause**: Test images may be too similar or from same art style
- **Fix**: Use more diverse characters/styles in test set

### "Poor separation (<0.08 margin)"

- **Cause**: CLIP may not distinguish well between these specific characters
- **Fix**:
  1. Try different test images
  2. Consider if characters are visually very similar by design
  3. May need fine-tuned CLIP model for this specific art style

## Integration with CI/CD

Once you have a validated test set, you can run this in CI:

```yaml
# .github/workflows/validate_clip.yml
name: CLIP Threshold Validation

on:
  pull_request:
    paths:
      - 'src/audit/identity_checker.py'
      - 'src/core/config.py'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: pip install transformers torch pillow
      - name: Download test images
        run: aws s3 sync s3://continuum-test-images/anime ./test_images
      - name: Run validation
        run: |
          python tests/validate_clip_threshold.py \
            --images-dir ./test_images \
            --threshold 0.85 \
            --report validation_report.json
      - name: Upload report
        uses: actions/upload-artifact@v2
        with:
          name: clip-validation-report
          path: validation_report.json
```

## Architecture Alignment

This validation script aligns with:

- **ARCHITECTURE.md Section 16G**: Multi-Format Output Strategy (anime-first approach)
- **ARCHITECTURE.md Section 3A.3**: Redundant Identity Stack (Layer 5 - QA Verification)
- **Handoff24Anime2.md**: Style-Aware Identity Checking implementation

The script:
✅ Uses production code (`CLIPIdentityChecker` from `src.audit.identity_checker`)
✅ Tests threshold from `src.core.config.AuditConfig.clip_identity_threshold`
✅ Validates backward compatibility (defaults to realistic if style unspecified)
✅ Provides actionable recommendations for threshold tuning
✅ Generates machine-readable report for tracking over time

## Next Steps After Validation

1. **Threshold Confirmed** (>95% accuracy):
   - Document validated threshold in ARCHITECTURE.md
   - Update project.json for Matrix Zero: `"style": "anime"`
   - Run end-to-end anime pipeline test

2. **Threshold Needs Adjustment**:
   - Update `src/core/config.py` and `workflows/models.json`
   - Re-run validation
   - Update documentation

3. **Poor Results** (<85% accuracy):
   - Collect more diverse test cases
   - Consider fine-tuning CLIP on anime data (Phase 2)
   - Evaluate alternative models (e.g., CLIP-ViT-L, specialized anime CLIP)

## Support

For questions or issues with threshold validation:
1. Check this guide's Troubleshooting section
2. Review ARCHITECTURE.md Section 16 for design rationale
3. Examine Handoff24Anime2.md for implementation context
4. Open GitHub issue with validation report attached
