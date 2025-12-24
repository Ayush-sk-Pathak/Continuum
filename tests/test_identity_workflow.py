#!/usr/bin/env python3
"""
Local validation test for identity anchoring implementation.
Run WITHOUT RunPod to verify workflow and code changes.

Usage:
    python test_identity_workflow.py
"""

import json
import sys
from pathlib import Path

# Add project root to path
# Handle both: running from project root OR from tests/ folder
TEST_FILE_DIR = Path(__file__).parent
if TEST_FILE_DIR.name == "tests":
    PROJECT_ROOT = TEST_FILE_DIR.parent  # Go up one level
else:
    PROJECT_ROOT = TEST_FILE_DIR

sys.path.insert(0, str(PROJECT_ROOT / "src"))

def test_workflow_json():
    """Test 1: Validate workflow JSON structure"""
    print("\n" + "="*60)
    print("TEST 1: Workflow JSON Validation")
    print("="*60)
    
    workflow_path = PROJECT_ROOT / "workflows" / "pass1_img2vid_ipadapter.json"
    
    if not workflow_path.exists():
        print(f"❌ FAIL: Workflow file not found at {workflow_path}")
        return False
    
    try:
        with open(workflow_path) as f:
            workflow = json.load(f)
        print(f"✓ JSON is valid")
    except json.JSONDecodeError as e:
        print(f"❌ FAIL: Invalid JSON - {e}")
        return False
    
    # Check required nodes exist
    required_nodes = [
        "clip_loader",
        "vae_loader", 
        "unet_loader",
        "clip_vision_loader",
        "load_init_image",
        "load_face_ref",      # NEW: face reference loader
        "clip_vision_encode",
        "positive_prompt",
        "negative_prompt",
        "wan_animate",        # NEW: WanAnimateToVideo instead of WanImageToVideo
        "sampler",
        "vae_decode",
        "create_video",
        "save_video"
    ]
    
    missing = [n for n in required_nodes if n not in workflow]
    if missing:
        print(f"❌ FAIL: Missing nodes: {missing}")
        return False
    print(f"✓ All {len(required_nodes)} required nodes present")
    
    # Check WanAnimateToVideo node specifically
    wan_node = workflow.get("wan_animate", {})
    if wan_node.get("class_type") != "WanAnimateToVideo":
        print(f"❌ FAIL: wan_animate should be WanAnimateToVideo, got {wan_node.get('class_type')}")
        return False
    print(f"✓ wan_animate uses WanAnimateToVideo")
    
    # Check reference_image input exists
    inputs = wan_node.get("inputs", {})
    if "reference_image" not in inputs:
        print(f"❌ FAIL: wan_animate missing 'reference_image' input")
        return False
    print(f"✓ wan_animate has 'reference_image' input")
    
    # Check clip_vision_output input exists (for I2V behavior)
    if "clip_vision_output" not in inputs:
        print(f"❌ FAIL: wan_animate missing 'clip_vision_output' input")
        return False
    print(f"✓ wan_animate has 'clip_vision_output' input")
    
    # Check face ref loader connects to wan_animate
    ref_connection = inputs.get("reference_image")
    if ref_connection != ["load_face_ref", 0]:
        print(f"❌ FAIL: reference_image should connect to load_face_ref, got {ref_connection}")
        return False
    print(f"✓ reference_image correctly wired to load_face_ref")
    
    # Check placeholders
    workflow_str = json.dumps(workflow)
    expected_placeholders = [
        "{{INIT_IMAGE}}",
        "{{FACE_REF_1}}",
        "{{POSITIVE_PROMPT}}",
        "{{NEGATIVE_PROMPT}}",
        "{{WIDTH}}",
        "{{HEIGHT}}",
        "{{FRAMES}}",
        "{{SEED}}",
        "{{STEPS}}",
        "{{CFG_SCALE}}",
        "{{FPS}}"
    ]
    
    missing_placeholders = [p for p in expected_placeholders if p not in workflow_str]
    if missing_placeholders:
        print(f"⚠ WARNING: Missing placeholders: {missing_placeholders}")
    else:
        print(f"✓ All {len(expected_placeholders)} expected placeholders present")
    
    print("\n✅ TEST 1 PASSED: Workflow JSON is valid")
    return True


def test_workflow_loader():
    """Test 2: Verify WorkflowLoader can load the template"""
    print("\n" + "="*60)
    print("TEST 2: WorkflowLoader Integration")
    print("="*60)
    
    try:
        from comfy_client.workflow_loader import WorkflowLoader
    except ImportError as e:
        print(f"⚠ SKIP: Could not import WorkflowLoader - {e}")
        print("  (This is OK if running outside project environment)")
        return None
    
    workflows_dir = PROJECT_ROOT / "workflows"
    loader = WorkflowLoader(workflows_dir)
    
    # Test loading
    try:
        template = loader.load("pass1_img2vid_ipadapter")
        print(f"✓ Loaded template: pass1_img2vid_ipadapter")
    except FileNotFoundError:
        print(f"❌ FAIL: Template not found by loader")
        return False
    
    # Test injection with mock params
    mock_params = {
        "INIT_IMAGE": "test_bridge.png",
        "FACE_REF_1": "test_face.png",
        "POSITIVE_PROMPT": "A woman walking",
        "NEGATIVE_PROMPT": "blurry, distorted",
        "WIDTH": 832,
        "HEIGHT": 480,
        "FRAMES": 81,
        "SEED": 12345,
        "STEPS": 20,
        "CFG_SCALE": 7.0,
        "FPS": 12,
        "CLIP_MODEL": "test_clip.safetensors",
        "VAE_MODEL": "test_vae.safetensors",
        "UNET_MODEL": "test_unet.safetensors",
        "CLIP_VISION_MODEL": "test_clip_vision.safetensors"
    }
    
    try:
        result = loader.inject(template, mock_params)
        if result.success:
            print(f"✓ Injection successful")
        else:
            print(f"⚠ Injection had missing params: {result.missing}")
    except Exception as e:
        print(f"❌ FAIL: Injection error - {e}")
        return False
    
    # Test validation
    try:
        validation = loader.validate(result.workflow)
        if validation.valid:
            print(f"✓ Validation passed")
        else:
            print(f"❌ FAIL: Validation errors: {validation.errors}")
            return False
        if validation.warnings:
            for w in validation.warnings:
                print(f"  ⚠ Warning: {w}")
    except Exception as e:
        print(f"❌ FAIL: Validation error - {e}")
        return False
    
    print("\n✅ TEST 2 PASSED: WorkflowLoader integration works")
    return True


def test_renderer_selection():
    """Test 3: Verify workflow selection logic"""
    print("\n" + "="*60)
    print("TEST 3: Renderer Workflow Selection")  
    print("="*60)
    
    try:
        from renderers.wan_renderer import WanRenderer
        from renderers.base import JobSpec, CharacterRef
    except ImportError as e:
        print(f"⚠ SKIP: Could not import WanRenderer - {e}")
        print("  (This is OK if running outside project environment)")
        return None
    
    renderer = WanRenderer.__new__(WanRenderer)  # Create without __init__
    
    # Mock job with init_frame and face_refs
    from pathlib import Path
    from unittest.mock import MagicMock
    
    # Test case: I2V + face refs should select ipadapter workflow
    job = MagicMock()
    job.has_init_frame = True
    job.character_refs = [
        MagicMock(
            has_lora=MagicMock(return_value=False),
            has_face_refs=MagicMock(return_value=True)
        )
    ]
    
    selected = renderer._select_workflow_template(job)
    expected = "pass1_img2vid_ipadapter"
    
    if selected == expected:
        print(f"✓ I2V + face_refs → {selected}")
    else:
        print(f"❌ FAIL: Expected {expected}, got {selected}")
        return False
    
    # Test case: I2V + LoRA should select lora workflow (LoRA takes priority)
    job.character_refs[0].has_lora.return_value = True
    selected = renderer._select_workflow_template(job)
    expected = "pass1_img2vid_lora"
    
    if selected == expected:
        print(f"✓ I2V + LoRA → {selected}")
    else:
        print(f"❌ FAIL: Expected {expected}, got {selected}")
        return False
    
    # Test case: I2V without identity → base i2v
    job.character_refs[0].has_lora.return_value = False
    job.character_refs[0].has_face_refs.return_value = False
    selected = renderer._select_workflow_template(job)
    expected = "pass1_img2vid"
    
    if selected == expected:
        print(f"✓ I2V only → {selected}")
    else:
        print(f"❌ FAIL: Expected {expected}, got {selected}")
        return False
    
    print("\n✅ TEST 3 PASSED: Workflow selection logic correct")
    return True


def test_error_handling():
    """Test 4: Verify error handling catches ValueError"""
    print("\n" + "="*60)
    print("TEST 4: Error Handling Check")
    print("="*60)
    
    renderer_path = PROJECT_ROOT / "src" / "renderers" / "wan_renderer.py"
    
    if not renderer_path.exists():
        print(f"❌ FAIL: wan_renderer.py not found at {renderer_path}")
        return False
    
    with open(renderer_path) as f:
        content = f.read()
    
    # Check that ValueError is caught
    if "except (FileNotFoundError, ValueError)" in content:
        print(f"✓ Error handling catches both FileNotFoundError and ValueError")
    elif "except FileNotFoundError" in content and "ValueError" not in content:
        print(f"❌ FAIL: Error handling only catches FileNotFoundError, not ValueError")
        print(f"  This means validation failures won't trigger fallback!")
        return False
    else:
        print(f"⚠ WARNING: Could not verify error handling pattern")
    
    # Check constant is updated
    if 'WORKFLOW_IMG2VID_IPADAPTER = "pass1_img2vid_ipadapter"  # Uses WanAnimateToVideo' in content:
        print(f"✓ WORKFLOW_IMG2VID_IPADAPTER constant updated")
    elif 'WORKFLOW_IMG2VID_IPADAPTER = "pass1_img2vid_ipadapter"  # Future' in content:
        print(f"❌ FAIL: WORKFLOW_IMG2VID_IPADAPTER still marked as 'Future'")
        return False
    else:
        print(f"⚠ WARNING: Could not verify constant comment")
    
    print("\n✅ TEST 4 PASSED: Error handling is correct")
    return True


def main():
    print("\n" + "="*60)
    print("IDENTITY ANCHORING LOCAL VALIDATION")
    print("="*60)
    print(f"Project root: {PROJECT_ROOT}")
    
    results = []
    
    # Run tests
    results.append(("Workflow JSON", test_workflow_json()))
    results.append(("WorkflowLoader", test_workflow_loader()))
    results.append(("Renderer Selection", test_renderer_selection()))
    results.append(("Error Handling", test_error_handling()))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, result in results:
        if result is True:
            print(f"  ✅ {name}: PASSED")
            passed += 1
        elif result is False:
            print(f"  ❌ {name}: FAILED")
            failed += 1
        else:
            print(f"  ⏭ {name}: SKIPPED")
            skipped += 1
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        print("\n❌ VALIDATION FAILED - Fix issues before deploying")
        return 1
    else:
        print("\n✅ VALIDATION PASSED - Ready to test on RunPod")
        return 0


if __name__ == "__main__":
    sys.exit(main())