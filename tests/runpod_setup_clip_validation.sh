#!/bin/bash
# RunPod Setup Script for CLIP Threshold Validation
#
# This script automates the setup process on RunPod for validating
# CLIP identity thresholds with anime images.
#
# Usage:
#   chmod +x tests/runpod_setup_clip_validation.sh
#   ./tests/runpod_setup_clip_validation.sh
#
# Prerequisites:
#   - RunPod pod running with this repo cloned
#   - Anime test images uploaded to /workspace/anime_test_images/

set -e  # Exit on error

echo "========================================"
echo "CLIP Validation Setup for RunPod"
echo "========================================"
echo ""

# Check if we're in the right directory
if [ ! -f "tests/validate_clip_threshold.py" ]; then
    echo "❌ Error: Run this script from the Continuum project root"
    echo "   Current directory: $(pwd)"
    exit 1
fi

echo "✓ Running from: $(pwd)"
echo ""

# Step 1: Check Python version
echo "Step 1/4: Checking Python version..."
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "  Python version: $python_version"
if [[ ! "$python_version" =~ ^3\.(8|9|10|11|12) ]]; then
    echo "  ⚠️  Warning: Python 3.8+ recommended"
fi
echo ""

# Step 2: Install dependencies
echo "Step 2/4: Installing dependencies..."
echo "  This may take a few minutes..."

if pip show transformers torch pillow > /dev/null 2>&1; then
    echo "  ✓ Dependencies already installed"
else
    echo "  Installing: transformers, torch, pillow"
    pip install -q transformers torch pillow
    echo "  ✓ Dependencies installed"
fi
echo ""

# Step 3: Check for test images
echo "Step 3/4: Checking for test images..."

DEFAULT_IMAGES_DIR="/workspace/anime_test_images"
if [ -d "$DEFAULT_IMAGES_DIR" ]; then
    image_count=$(find "$DEFAULT_IMAGES_DIR" -type f \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \) | wc -l)
    char_count=$(find "$DEFAULT_IMAGES_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)

    echo "  ✓ Found test images directory: $DEFAULT_IMAGES_DIR"
    echo "    - Character directories: $char_count"
    echo "    - Total images: $image_count"

    if [ "$char_count" -lt 2 ]; then
        echo "  ⚠️  Warning: Need at least 2 character directories"
        echo "     See tests/CLIP_THRESHOLD_VALIDATION.md for structure"
    fi

    if [ "$image_count" -lt 6 ]; then
        echo "  ⚠️  Warning: Recommend at least 3 images per character"
    fi
else
    echo "  ⚠️  Test images directory not found: $DEFAULT_IMAGES_DIR"
    echo "     Please create and populate with test images"
    echo "     See tests/CLIP_THRESHOLD_VALIDATION.md for structure"
    echo ""
    echo "     Quick example:"
    echo "       mkdir -p $DEFAULT_IMAGES_DIR/{character1,character2,character3}"
    echo "       # Upload images to each character directory"
fi
echo ""

# Step 4: Verify imports
echo "Step 4/4: Verifying CLIP checker imports..."
python -c "from src.audit.identity_checker import CLIPIdentityChecker; print('  ✓ CLIPIdentityChecker imported successfully')" 2>&1

if [ $? -eq 0 ]; then
    echo ""
else
    echo "  ❌ Failed to import CLIPIdentityChecker"
    echo "     Check that you're in the project root directory"
    exit 1
fi

# Print next steps
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Ensure test images are in: $DEFAULT_IMAGES_DIR"
echo "   Structure:"
echo "     anime_test_images/"
echo "     ├── character1/"
echo "     │   ├── pose1.png"
echo "     │   └── pose2.png"
echo "     ├── character2/"
echo "     │   └── pose1.png"
echo "     └── ..."
echo ""
echo "2. Run validation:"
echo "   python tests/validate_clip_threshold.py \\"
echo "     --images-dir $DEFAULT_IMAGES_DIR \\"
echo "     --threshold 0.85 \\"
echo "     --report clip_report.json"
echo ""
echo "3. Review results and follow recommendations"
echo ""
echo "For detailed documentation, see:"
echo "  tests/CLIP_THRESHOLD_VALIDATION.md"
echo ""
echo "========================================"
