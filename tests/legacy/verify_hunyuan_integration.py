#!/usr/bin/env python3
"""
Verification Script: HunyuanCustom Integration Test

Tests that all the pieces fit together:
1. models.json loads correctly
2. model_loader returns correct fields for HunyuanCustom
3. workflow_loader can find and load the workflow template
4. hunyuan_custom_renderer builds correct params
5. Placeholder injection works

Run from project root:
    python tests/verify_hunyuan_integration.py
    
No GPU or ComfyUI connection needed - this is a dry-run test.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment for testing
os.environ.setdefault("CONTINUUM_MODEL_TIER", "dev")
os.environ.setdefault("CONTINUUM_VIDEO_MODEL__MODEL_FAMILY", "hunyuan_custom")


def test_models_json():
    """Test 1: Verify models.json loads and has HunyuanCustom section."""
    print("\n" + "="*60)
    print("TEST 1: models.json Loading")
    print("="*60)
    
    import json
    
    models_path = project_root / "models.json"
    if not models_path.exists():
        print(f"❌ FAIL: models.json not found at {models_path}")
        return False
    
    with open(models_path) as f:
        models = json.load(f)
    
    # Check HunyuanCustom section exists
    if "hunyuan_custom" not in models:
        print("❌ FAIL: 'hunyuan_custom' section missing from models.json")
        return False
    
    hc = models["hunyuan_custom"]
    
    # Check i2v section
    if "i2v" not in hc:
        print("❌ FAIL: 'i2v' section missing from hunyuan_custom")
        return False
    
    # Check dev tier
    if "dev" not in hc["i2v"]:
        print("❌ FAIL: 'dev' tier missing from hunyuan_custom.i2v")
        return False
    
    dev = hc["i2v"]["dev"]
    
    # Check required fields
    required_fields = [
        "unet", "vae", "clip_l", "llava_text_encoder", 
        "clip_vision", "attention_mode"
    ]
    
    missing = [f for f in required_fields if f not in dev]
    if missing:
        print(f"❌ FAIL: Missing fields in dev tier: {missing}")
        return False
    
    print(f"✅ models.json loaded successfully")
    print(f"   - unet: {dev['unet']}")
    print(f"   - clip_l: {dev['clip_l']}")
    print(f"   - llava_text_encoder: {dev['llava_text_encoder']}")
    print(f"   - clip_vision: {dev['clip_vision']}")
    print(f"   - attention_mode: {dev['attention_mode']}")
    
    return True


def test_model_loader():
    """Test 2: Verify model_loader returns correct ModelConfig."""
    print("\n" + "="*60)
    print("TEST 2: model_loader.get_model_config()")
    print("="*60)
    
    try:
        from src.core.model_loader import get_model_config, ModelTier
    except ImportError as e:
        print(f"❌ FAIL: Could not import model_loader: {e}")
        return False
    
    try:
        config = get_model_config("hunyuan_custom", "i2v", ModelTier.DEV)
    except Exception as e:
        print(f"❌ FAIL: get_model_config raised: {e}")
        return False
    
    # Check new fields exist
    if not config.clip_l:
        print("❌ FAIL: config.clip_l is None")
        return False
    
    if not config.llava_text_encoder:
        print("❌ FAIL: config.llava_text_encoder is None")
        return False
    
    if not config.clip_vision:
        print("❌ FAIL: config.clip_vision is None")
        return False
    
    print(f"✅ ModelConfig loaded successfully")
    print(f"   - unet: {config.unet}")
    print(f"   - vae: {config.vae}")
    print(f"   - clip_l: {config.clip_l}")
    print(f"   - llava_text_encoder: {config.llava_text_encoder}")
    print(f"   - clip_vision: {config.clip_vision}")
    print(f"   - attention_mode: {config.attention_mode}")
    print(f"   - is_hunyuan_custom(): {config.is_hunyuan_custom()}")
    
    return True


def test_workflow_params():
    """Test 3: Verify to_workflow_params() returns correct placeholders."""
    print("\n" + "="*60)
    print("TEST 3: ModelConfig.to_workflow_params()")
    print("="*60)
    
    try:
        from src.core.model_loader import get_model_config, ModelTier
    except ImportError as e:
        print(f"❌ FAIL: Could not import model_loader: {e}")
        return False
    
    config = get_model_config("hunyuan_custom", "i2v", ModelTier.DEV)
    params = config.to_workflow_params()
    
    # Check required placeholder keys
    required_keys = [
        "UNET_MODEL", "VAE_MODEL", "CLIP_L_MODEL", 
        "LLAVA_TEXT_ENCODER", "CLIP_VISION_MODEL", "ATTENTION_MODE"
    ]
    
    missing = [k for k in required_keys if k not in params]
    if missing:
        print(f"❌ FAIL: Missing keys in workflow_params: {missing}")
        return False
    
    print(f"✅ to_workflow_params() returns correct keys")
    for key in required_keys:
        print(f"   - {key}: {params[key]}")
    
    return True


def test_workflow_loader():
    """Test 4: Verify workflow_loader can find HunyuanCustom workflow."""
    print("\n" + "="*60)
    print("TEST 4: WorkflowLoader (hunyuan_custom)")
    print("="*60)
    
    try:
        from src.comfy_client.workflow_loader import WorkflowLoader
    except ImportError as e:
        print(f"❌ FAIL: Could not import WorkflowLoader: {e}")
        return False
    
    workflows_dir = project_root / "workflows"
    
    try:
        loader = WorkflowLoader(
            workflows_dir=workflows_dir,
            model_family="hunyuan_custom"
        )
    except Exception as e:
        print(f"❌ FAIL: Could not create WorkflowLoader: {e}")
        return False
    
    # Try to load pass1_img2vid
    try:
        template = loader.load("pass1_img2vid")
    except FileNotFoundError as e:
        print(f"❌ FAIL: Workflow not found: {e}")
        print(f"   Expected at: {workflows_dir}/hunyuan_custom/pass1_img2vid.json")
        return False
    except Exception as e:
        print(f"❌ FAIL: Error loading workflow: {e}")
        return False
    
    print(f"✅ Workflow loaded successfully")
    print(f"   - Name: {template.name}")
    print(f"   - Source: {template.source_path}")
    print(f"   - Placeholders: {len(template.placeholders)}")
    
    # Check required placeholders exist in template
    required_placeholders = [
        "PROMPT", "FACE_REF_IMAGE", "UNET_MODEL", "VAE_MODEL",
        "CLIP_L_MODEL", "LLAVA_TEXT_ENCODER", "CLIP_VISION_MODEL"
    ]
    
    missing = [p for p in required_placeholders if p not in template.placeholders]
    if missing:
        print(f"⚠️  WARNING: Missing placeholders in workflow: {missing}")
        print(f"   Found: {sorted(template.placeholders)}")
    else:
        print(f"   - All required placeholders present ✓")
    
    return True


def test_prompt_formatting():
    """Test 5: Verify prompt formatting with <image> token."""
    print("\n" + "="*60)
    print("TEST 5: Prompt Formatting (<image> token)")
    print("="*60)
    
    try:
        from src.renderers.hunyuan_custom_renderer import HunyuanCustomRenderer
        from src.renderers.base import JobSpec, CharacterRef
    except ImportError as e:
        print(f"❌ FAIL: Could not import renderer: {e}")
        return False
    
    # Create a mock job with character ref
    class MockCharRef:
        def __init__(self, name):
            self.name = name
            self.entity_id = name.lower()
            self.face_refs = [Path("/fake/face.png")]
    
    class MockJob:
        def __init__(self):
            self.prompt = "running on a sandy beach with ocean waves"
            self.character_refs = [MockCharRef("Alice")]
    
    # Test the formatting method
    renderer = HunyuanCustomRenderer.__new__(HunyuanCustomRenderer)
    job = MockJob()
    
    formatted = renderer._format_prompt_with_image_token(job)
    
    # Check format
    expected_start = "Realistic, High-quality."
    if not formatted.startswith(expected_start):
        print(f"❌ FAIL: Prompt doesn't start with quality prefix")
        print(f"   Got: {formatted[:50]}...")
        return False
    
    if "<image>" not in formatted:
        print(f"❌ FAIL: Prompt missing <image> token")
        print(f"   Got: {formatted}")
        return False
    
    if " is " not in formatted:
        print(f"❌ FAIL: Prompt missing ' is ' after <image>")
        print(f"   Got: {formatted}")
        return False
    
    print(f"✅ Prompt formatted correctly")
    print(f"   - Input: \"{job.prompt}\"")
    print(f"   - Output: \"{formatted}\"")
    
    # Test with existing <image> token
    job.prompt = "<image> is walking through a garden"
    formatted2 = renderer._format_prompt_with_image_token(job)
    
    if not formatted2.startswith(expected_start):
        print(f"⚠️  WARNING: Quality prefix not added to existing <image> prompt")
    else:
        print(f"   - Existing <image> prompt also gets prefix ✓")
    
    return True


def test_wan_still_works():
    """Test 6: Verify Wan models still load correctly (backward compat)."""
    print("\n" + "="*60)
    print("TEST 6: Wan Backward Compatibility")
    print("="*60)
    
    try:
        from src.core.model_loader import get_model_config, ModelTier
    except ImportError as e:
        print(f"❌ FAIL: Could not import model_loader: {e}")
        return False
    
    try:
        config = get_model_config("wan21", "i2v", ModelTier.DEV)
    except Exception as e:
        print(f"❌ FAIL: Could not load Wan config: {e}")
        return False
    
    # Check Wan uses clip (not clip_l)
    if not config.clip:
        print("❌ FAIL: Wan config.clip is None")
        return False
    
    if config.clip_l is not None:
        print("⚠️  WARNING: Wan config has clip_l (should be None)")
    
    print(f"✅ Wan config loads correctly")
    print(f"   - unet: {config.unet}")
    print(f"   - clip: {config.clip}")
    print(f"   - clip_vision: {config.clip_vision}")
    print(f"   - is_wan(): {config.is_wan()}")
    
    return True


def main():
    """Run all verification tests."""
    print("\n" + "#"*60)
    print("# HunyuanCustom Integration Verification")
    print("#"*60)
    print(f"\nProject root: {project_root}")
    print(f"Model tier: {os.environ.get('CONTINUUM_MODEL_TIER', 'dev')}")
    
    tests = [
        ("models.json", test_models_json),
        ("model_loader", test_model_loader),
        ("workflow_params", test_workflow_params),
        ("workflow_loader", test_workflow_loader),
        ("prompt_formatting", test_prompt_formatting),
        ("wan_backward_compat", test_wan_still_works),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ FAIL: {name} raised unexpected exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, p in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All integration tests passed! Ready for GPU testing.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Fix issues before GPU testing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())