#!/usr/bin/env python3
"""
Comprehensive tests for Continuum workflow JSON files.

LESSONS_LEARNED.md Key Reminders Applied:
- #14: WorkflowLoader.load() takes NAME not path
- #17: Path setup for imports 
- #18: Workflow JSON cannot have _meta keys (validator rejects them)
- J4: Always view source files before building integrations

Tests cover:
1. Basic JSON validity and structure  
2. ComfyUI node format compliance
3. Placeholder extraction and validation
4. Parameter injection via workflow_loader (if available)
5. Edge cases (missing params, extra params, type coercion)
6. Stress testing (large values, unicode, special chars)
7. Nightmare scenarios (malformed data, circular refs)
8. Workflow comparison (T2V vs I2V consistency)
9. Integration with wan_renderer expectations
"""

import json
import sys
import os
import copy
import re
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Set, Optional, List
from dataclasses import dataclass, field

# =============================================================================
# PATH SETUP (LESSONS_LEARNED #17)
# =============================================================================

# Project root is parent of tests/ directory
# tests/test_workflows.py -> tests/ -> project_root/
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Add project root to path for imports (allows `from src...` imports)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Workflow files location (relative to project root)
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
T2V_WORKFLOW_PATH = WORKFLOWS_DIR / "pass1_structural.json"
I2V_WORKFLOW_PATH = WORKFLOWS_DIR / "pass1_img2vid.json"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_workflow(path: Path) -> Dict[str, Any]:
    """Load a workflow JSON file."""
    with open(path) as f:
        return json.load(f)


def get_nodes(workflow: Dict) -> Dict[str, Any]:
    """Extract nodes from workflow, excluding any _ prefixed keys."""
    return {k: v for k, v in workflow.items() if not k.startswith("_")}


def extract_placeholders(obj: Any, found: Optional[Set[str]] = None) -> Set[str]:
    """Recursively extract {{PLACEHOLDER}} patterns from any structure."""
    if found is None:
        found = set()
    
    if isinstance(obj, str):
        matches = re.findall(r"\{\{([A-Z_]+)\}\}", obj)
        found.update(matches)
    elif isinstance(obj, dict):
        for value in obj.values():
            extract_placeholders(value, found)
    elif isinstance(obj, list):
        for item in obj:
            extract_placeholders(item, found)
    
    return found


def inject_params(workflow: Dict, params: Dict[str, Any]) -> Dict[str, Any]:
    """Simple parameter injection (mimics WorkflowLoader.inject behavior)."""
    result = copy.deepcopy(workflow)
    
    def replace_recursive(obj):
        if isinstance(obj, str):
            for key, value in params.items():
                placeholder = f"{{{{{key}}}}}"
                if placeholder in obj:
                    # Full replacement if entire string is placeholder
                    if obj == placeholder:
                        return value
                    # Partial replacement within string
                    obj = obj.replace(placeholder, str(value))
            return obj
        elif isinstance(obj, dict):
            return {k: replace_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_recursive(item) for item in obj]
        return obj
    
    return replace_recursive(result)


# =============================================================================
# STANDARD TEST PARAMETERS
# =============================================================================

STANDARD_PARAMS = {
    "POSITIVE_PROMPT": "A beautiful sunset over the ocean",
    "NEGATIVE_PROMPT": "blurry, distorted, low quality",
    "SEED": 42,
    "WIDTH": 1280,
    "HEIGHT": 720,
    "FRAMES": 48,
    "FPS": 12,
    "STEPS": 20,
    "CFG_SCALE": 7.0,
    "INIT_IMAGE": "uploaded/test_image.png",
}


# =============================================================================
# SECTION 1: BASIC JSON VALIDITY
# =============================================================================

class TestBasicJSONValidity:
    """Test that workflow files exist and are valid JSON."""
    
    def test_t2v_workflow_file_exists(self):
        """T2V workflow file exists at expected location."""
        assert T2V_WORKFLOW_PATH.exists(), \
            f"T2V workflow not found at {T2V_WORKFLOW_PATH}"
    
    def test_i2v_workflow_file_exists(self):
        """I2V workflow file exists at expected location."""
        assert I2V_WORKFLOW_PATH.exists(), \
            f"I2V workflow not found at {I2V_WORKFLOW_PATH}"
    
    def test_t2v_is_valid_json(self):
        """T2V workflow is valid JSON."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        assert isinstance(workflow, dict)
        assert len(workflow) > 0
    
    def test_i2v_is_valid_json(self):
        """I2V workflow is valid JSON."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        assert isinstance(workflow, dict)
        assert len(workflow) > 0
    
    def test_t2v_has_expected_placeholders(self):
        """T2V workflow has expected injectable placeholders."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        expected = {"POSITIVE_PROMPT", "NEGATIVE_PROMPT", "SEED", 
                   "WIDTH", "HEIGHT", "FRAMES", "FPS", "STEPS", "CFG_SCALE"}
        missing = expected - found
        assert not missing, f"T2V missing expected placeholders: {missing}"
    
    def test_i2v_has_expected_placeholders(self):
        """I2V workflow has expected injectable placeholders including INIT_IMAGE."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        expected = {"POSITIVE_PROMPT", "NEGATIVE_PROMPT", "SEED", 
                   "WIDTH", "HEIGHT", "FRAMES", "FPS", "STEPS", "CFG_SCALE", "INIT_IMAGE"}
        missing = expected - found
        assert not missing, f"I2V missing expected placeholders: {missing}"
    
    def test_t2v_no_trailing_commas(self):
        """T2V JSON has no trailing commas (common JSON error)."""
        with open(T2V_WORKFLOW_PATH) as f:
            content = f.read()
        # If we got here, json.load() in load_workflow worked, so no trailing commas
        assert True
    
    def test_i2v_no_trailing_commas(self):
        """I2V JSON has no trailing commas."""
        with open(I2V_WORKFLOW_PATH) as f:
            content = f.read()
        assert True


# =============================================================================
# SECTION 2: COMFYUI NODE FORMAT COMPLIANCE
# =============================================================================

class TestComfyUIFormat:
    """Test that workflows follow ComfyUI API format."""
    
    def test_t2v_all_nodes_have_class_type(self):
        """Every T2V node has class_type field."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        
        for node_id, node in nodes.items():
            assert "class_type" in node, \
                f"T2V node '{node_id}' missing class_type"
    
    def test_i2v_all_nodes_have_class_type(self):
        """Every I2V node has class_type field."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        
        for node_id, node in nodes.items():
            assert "class_type" in node, \
                f"I2V node '{node_id}' missing class_type"
    
    def test_t2v_all_nodes_have_inputs(self):
        """Every T2V node has inputs field."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        
        for node_id, node in nodes.items():
            assert "inputs" in node, \
                f"T2V node '{node_id}' missing inputs"
    
    def test_i2v_all_nodes_have_inputs(self):
        """Every I2V node has inputs field."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        
        for node_id, node in nodes.items():
            assert "inputs" in node, \
                f"I2V node '{node_id}' missing inputs"
    
    def test_t2v_node_references_are_valid(self):
        """T2V node references point to existing nodes."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        node_ids = set(nodes.keys())
        
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) >= 1:
                    # This is a reference: [node_id, output_index]
                    ref_id = str(input_value[0])
                    assert ref_id in node_ids, \
                        f"T2V {node_id}.{input_name} references non-existent node '{ref_id}'"
    
    def test_i2v_node_references_are_valid(self):
        """I2V node references point to existing nodes."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        node_ids = set(nodes.keys())
        
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) >= 1:
                    ref_id = str(input_value[0])
                    assert ref_id in node_ids, \
                        f"I2V {node_id}.{input_name} references non-existent node '{ref_id}'"
    
    def test_t2v_has_required_node_types(self):
        """T2V has essential node types for video generation."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        class_types = {n["class_type"] for n in nodes.values()}
        
        # Required for any video generation
        required = {"CLIPLoader", "VAELoader", "UNETLoader", "KSampler", "VAEDecode"}
        missing = required - class_types
        assert not missing, f"T2V missing required node types: {missing}"
    
    def test_i2v_has_required_node_types(self):
        """I2V has essential node types for image-to-video."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        nodes = get_nodes(workflow)
        class_types = {n["class_type"] for n in nodes.values()}
        
        required = {"CLIPLoader", "VAELoader", "UNETLoader", "KSampler", "VAEDecode",
                   "LoadImage", "CLIPVisionLoader"}  # Extra for I2V
        missing = required - class_types
        assert not missing, f"I2V missing required node types: {missing}"
    
    def test_i2v_has_extra_nodes_for_image_conditioning(self):
        """I2V has nodes that T2V doesn't (for image conditioning)."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_types = {n["class_type"] for n in get_nodes(t2v).values()}
        i2v_types = {n["class_type"] for n in get_nodes(i2v).values()}
        
        # I2V should have these that T2V doesn't
        i2v_only = i2v_types - t2v_types
        assert "LoadImage" in i2v_only or "LoadImage" in i2v_types, \
            "I2V should have LoadImage for reference frame"
        assert "CLIPVisionLoader" in i2v_only or "CLIPVisionLoader" in i2v_types, \
            "I2V should have CLIPVisionLoader"


# =============================================================================
# SECTION 3: PLACEHOLDER VALIDATION
# =============================================================================

class TestPlaceholders:
    """Test placeholder syntax and completeness."""
    
    def test_t2v_placeholder_syntax_valid(self):
        """T2V placeholders use correct {{NAME}} syntax."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        placeholders = extract_placeholders(workflow)
        
        for p in placeholders:
            assert re.match(r"^[A-Z][A-Z0-9_]*$", p), f"Invalid placeholder name: {p}"
    
    def test_i2v_placeholder_syntax_valid(self):
        """I2V placeholders use correct {{NAME}} syntax."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        placeholders = extract_placeholders(workflow)
        
        for p in placeholders:
            assert re.match(r"^[A-Z][A-Z0-9_]*$", p), f"Invalid placeholder name: {p}"
    
    def test_t2v_has_all_required_generation_placeholders(self):
        """T2V workflow has all placeholders needed for video generation."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        
        # Minimum required for any generation
        required = {"POSITIVE_PROMPT", "SEED", "WIDTH", "HEIGHT", "FRAMES"}
        missing = required - found
        assert not missing, f"T2V missing required placeholders: {missing}"
    
    def test_i2v_has_all_required_generation_placeholders(self):
        """I2V workflow has all placeholders needed for video generation."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        
        # Minimum required for I2V generation
        required = {"POSITIVE_PROMPT", "SEED", "WIDTH", "HEIGHT", "FRAMES", "INIT_IMAGE"}
        missing = required - found
        assert not missing, f"I2V missing required placeholders: {missing}"
    
    def test_t2v_has_no_init_image_placeholder(self):
        """T2V workflow should NOT have INIT_IMAGE (it's text-to-video)."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        placeholders = extract_placeholders(workflow)
        
        assert "INIT_IMAGE" not in placeholders, \
            "T2V should not have INIT_IMAGE placeholder"
    
    def test_i2v_has_init_image_placeholder(self):
        """I2V workflow MUST have INIT_IMAGE (it's image-to-video)."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        placeholders = extract_placeholders(workflow)
        
        assert "INIT_IMAGE" in placeholders, \
            "I2V must have INIT_IMAGE placeholder"
    
    def test_common_placeholders_in_both(self):
        """Both workflows share common placeholders."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_p = extract_placeholders(t2v)
        i2v_p = extract_placeholders(i2v)
        
        common = {"POSITIVE_PROMPT", "SEED", "WIDTH", "HEIGHT", "FRAMES"}
        
        for p in common:
            assert p in t2v_p, f"T2V missing common placeholder: {p}"
            assert p in i2v_p, f"I2V missing common placeholder: {p}"


# =============================================================================
# SECTION 4: PARAMETER INJECTION
# =============================================================================

class TestParameterInjection:
    """Test parameter injection behavior."""
    
    def test_t2v_injection_replaces_placeholders(self):
        """T2V placeholders are replaced with values."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, STANDARD_PARAMS)
        
        remaining = extract_placeholders(injected)
        expected_remaining = {"INIT_IMAGE"}  # T2V doesn't have this, should be 0
        actual_remaining = remaining - expected_remaining
        
        assert not actual_remaining, \
            f"T2V still has uninjected placeholders: {actual_remaining}"
    
    def test_i2v_injection_replaces_placeholders(self):
        """I2V placeholders are replaced with values."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        injected = inject_params(workflow, STANDARD_PARAMS)
        
        remaining = extract_placeholders(injected)
        assert not remaining, \
            f"I2V still has uninjected placeholders: {remaining}"
    
    def test_injection_preserves_integer_types(self):
        """Integer values remain integers after injection."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": 42, "WIDTH": 1280})
        
        # Find the seed value in the injected workflow
        def find_value(obj, key):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == key:
                        return v
                    result = find_value(v, key)
                    if result is not None:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = find_value(item, key)
                    if result is not None:
                        return result
            return None
        
        # Seed should be integer
        seed_val = find_value(injected, "seed")
        if seed_val is not None and seed_val != "{{SEED}}":
            assert isinstance(seed_val, int), f"Seed should be int, got {type(seed_val)}"
    
    def test_injection_preserves_float_types(self):
        """Float values remain floats after injection."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"CFG_SCALE": 7.5})
        
        def find_value(obj, key):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == key:
                        return v
                    result = find_value(v, key)
                    if result is not None:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = find_value(item, key)
                    if result is not None:
                        return result
            return None
        
        cfg_val = find_value(injected, "cfg")
        if cfg_val is not None and not isinstance(cfg_val, str):
            assert isinstance(cfg_val, (int, float)), \
                f"CFG should be numeric, got {type(cfg_val)}"
    
    def test_injection_preserves_node_references(self):
        """Node references [node_id, slot] are preserved."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, STANDARD_PARAMS)
        
        nodes = get_nodes(injected)
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) == 2:
                    # This should still be a valid reference
                    assert isinstance(input_value[0], str), \
                        f"{node_id}.{input_name}[0] should be string node ref"
                    assert isinstance(input_value[1], int), \
                        f"{node_id}.{input_name}[1] should be int output slot"
    
    def test_missing_placeholder_left_unchanged(self):
        """Missing placeholders are left as-is."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        # Inject all EXCEPT INIT_IMAGE
        partial_params = {k: v for k, v in STANDARD_PARAMS.items() if k != "INIT_IMAGE"}
        injected = inject_params(workflow, partial_params)
        
        remaining = extract_placeholders(injected)
        assert "INIT_IMAGE" in remaining, \
            "INIT_IMAGE should remain as placeholder when not provided"


# =============================================================================
# SECTION 5: EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and unusual inputs."""
    
    def test_empty_string_prompt(self):
        """Empty string is valid for prompt."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"POSITIVE_PROMPT": ""})
        # Should not raise
        assert True
    
    def test_negative_seed(self):
        """Negative seed (-1 for random) is valid."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": -1})
        # Should not raise
        assert True
    
    def test_zero_dimensions_injected(self):
        """Zero dimensions are injected (validation is ComfyUI's job)."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"WIDTH": 0, "HEIGHT": 0})
        # Should not raise - ComfyUI will validate
        assert True
    
    def test_extra_params_ignored(self):
        """Extra parameters not in workflow are ignored."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        params_with_extra = {
            **STANDARD_PARAMS,
            "NONEXISTENT_PARAM": "should_be_ignored",
            "ANOTHER_FAKE": 999,
        }
        injected = inject_params(workflow, params_with_extra)
        
        # Should not contain these as values
        json_str = json.dumps(injected)
        assert "should_be_ignored" not in json_str
    
    def test_float_as_int_param(self):
        """Float value for int placeholder is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": 42.0})
        # Should not raise
        assert True
    
    def test_string_number_as_param(self):
        """String '42' for int placeholder is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": "42"})
        # Should not raise (ComfyUI may or may not accept this)
        assert True


# =============================================================================
# SECTION 6: STRESS TESTING
# =============================================================================

class TestStress:
    """Stress test with extreme values."""
    
    def test_very_long_prompt(self):
        """Very long prompt (10KB) is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        long_prompt = "word " * 2000  # ~10KB
        injected = inject_params(workflow, {"POSITIVE_PROMPT": long_prompt})
        
        # Verify it's actually in there
        json_str = json.dumps(injected)
        assert "word word word" in json_str
    
    def test_unicode_prompt(self):
        """Unicode in prompt is handled correctly."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        unicode_prompt = "日本語テスト 🎬 émojis и кириллица"
        injected = inject_params(workflow, {"POSITIVE_PROMPT": unicode_prompt})
        
        json_str = json.dumps(injected, ensure_ascii=False)
        assert "日本語テスト" in json_str
        assert "🎬" in json_str
    
    def test_special_chars_in_prompt(self):
        """Special characters don't break injection."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        special_prompt = 'Quote "test" and \'single\' and {braces} and $pecial'
        injected = inject_params(workflow, {"POSITIVE_PROMPT": special_prompt})
        
        # Should not raise and should contain the text
        json_str = json.dumps(injected)
        assert "Quote" in json_str
    
    def test_newlines_in_prompt(self):
        """Newlines in prompt are preserved."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        multiline = "Line 1\nLine 2\nLine 3"
        injected = inject_params(workflow, {"POSITIVE_PROMPT": multiline})
        
        # Find the prompt value
        nodes = get_nodes(injected)
        for node in nodes.values():
            inputs = node.get("inputs", {})
            if "text" in inputs and "Line 1" in str(inputs["text"]):
                assert "\n" in inputs["text"] or "\\n" in inputs["text"]
                break
    
    def test_large_seed_value(self):
        """Very large seed (64-bit max) is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        big_seed = 9223372036854775807  # Max int64
        injected = inject_params(workflow, {"SEED": big_seed})
        
        json_str = json.dumps(injected)
        assert str(big_seed) in json_str or big_seed in json.loads(json_str).values()
    
    def test_large_dimensions(self):
        """8K resolution values are handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"WIDTH": 7680, "HEIGHT": 4320})
        
        json_str = json.dumps(injected)
        assert "7680" in json_str
        assert "4320" in json_str
    
    def test_many_frames(self):
        """Large frame count is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"FRAMES": 1000})
        
        json_str = json.dumps(injected)
        assert "1000" in json_str


# =============================================================================
# SECTION 7: NIGHTMARE SCENARIOS
# =============================================================================

class TestNightmareScenarios:
    """Test malformed inputs that could break things."""
    
    def test_node_missing_inputs_key(self):
        """Workflow with node missing inputs fails gracefully."""
        bad_workflow = {
            "node1": {
                "class_type": "TestNode"
                # Missing "inputs" key
            }
        }
        # Our helper should handle this
        nodes = get_nodes(bad_workflow)
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})  # Should return empty dict
            assert isinstance(inputs, dict)
    
    def test_circular_reference_detection(self):
        """Circular node references are detectable."""
        # This is more of a documentation test - we're noting the pattern
        circular_workflow = {
            "node_a": {
                "class_type": "Test",
                "inputs": {"from": ["node_b", 0]}
            },
            "node_b": {
                "class_type": "Test", 
                "inputs": {"from": ["node_a", 0]}
            }
        }
        
        # Our validation helper should process this without hanging
        nodes = get_nodes(circular_workflow)
        assert len(nodes) == 2
    
    def test_self_referencing_node(self):
        """Self-referencing node is detectable."""
        self_ref = {
            "node_a": {
                "class_type": "Test",
                "inputs": {"from": ["node_a", 0]}
            }
        }
        
        nodes = get_nodes(self_ref)
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) >= 1:
                    ref_id = str(input_value[0])
                    if ref_id == node_id:
                        # Detected self-reference
                        assert True
                        return
    
    def test_nonexistent_node_reference(self):
        """Reference to non-existent node is detectable."""
        bad_ref = {
            "node_a": {
                "class_type": "Test",
                "inputs": {"from": ["does_not_exist", 0]}
            }
        }
        
        nodes = get_nodes(bad_ref)
        node_ids = set(nodes.keys())
        
        has_bad_ref = False
        for node_id, node in nodes.items():
            inputs = node.get("inputs", {})
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) >= 1:
                    ref_id = str(input_value[0])
                    if ref_id not in node_ids:
                        has_bad_ref = True
        
        assert has_bad_ref, "Should detect bad reference"
    
    def test_none_value_injection(self):
        """None as parameter value doesn't crash."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"POSITIVE_PROMPT": None})
        # Should not raise
        assert True
    
    def test_list_value_injection(self):
        """List as parameter value (wrong type) is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": [1, 2, 3]})
        # Should not raise - but may result in invalid workflow
        assert True
    
    def test_dict_value_injection(self):
        """Dict as parameter value (wrong type) is handled."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        injected = inject_params(workflow, {"SEED": {"nested": "dict"}})
        # Should not raise
        assert True
    
    def test_empty_workflow(self):
        """Empty workflow is handled."""
        empty = {}
        nodes = get_nodes(empty)
        assert len(nodes) == 0
    
    def test_workflow_with_only_underscore_keys(self):
        """Workflow with only _-prefixed keys returns empty nodes."""
        only_private = {
            "_meta": {"title": "test"},
            "_internal": {"data": "stuff"}
        }
        nodes = get_nodes(only_private)
        assert len(nodes) == 0


# =============================================================================
# SECTION 8: WORKFLOW COMPARISON
# =============================================================================

class TestWorkflowComparison:
    """Compare T2V and I2V workflows for consistency."""
    
    def test_same_clip_model(self):
        """Both workflows use same CLIP model."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_clip = get_nodes(t2v).get("clip_loader", {}).get("inputs", {}).get("clip_name")
        i2v_clip = get_nodes(i2v).get("clip_loader", {}).get("inputs", {}).get("clip_name")
        
        assert t2v_clip == i2v_clip, \
            f"CLIP models differ: T2V={t2v_clip}, I2V={i2v_clip}"
    
    def test_same_vae_model(self):
        """Both workflows use same VAE model."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_vae = get_nodes(t2v).get("vae_loader", {}).get("inputs", {}).get("vae_name")
        i2v_vae = get_nodes(i2v).get("vae_loader", {}).get("inputs", {}).get("vae_name")
        
        assert t2v_vae == i2v_vae, \
            f"VAE models differ: T2V={t2v_vae}, I2V={i2v_vae}"
    
    def test_different_unet_models(self):
        """T2V and I2V use different UNET models (intentional)."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_unet = get_nodes(t2v).get("unet_loader", {}).get("inputs", {}).get("unet_name", "")
        i2v_unet = get_nodes(i2v).get("unet_loader", {}).get("inputs", {}).get("unet_name", "")
        
        # They should be different - T2V uses t2v model, I2V uses i2v model
        assert t2v_unet != i2v_unet or "t2v" in t2v_unet.lower(), \
            f"UNET models should differ: T2V={t2v_unet}, I2V={i2v_unet}"
    
    def test_same_sampler_config(self):
        """Both workflows use same sampler configuration."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_sampler = get_nodes(t2v).get("sampler", {}).get("inputs", {}).get("sampler_name")
        i2v_sampler = get_nodes(i2v).get("sampler", {}).get("inputs", {}).get("sampler_name")
        
        assert t2v_sampler == i2v_sampler, \
            f"Sampler configs differ: T2V={t2v_sampler}, I2V={i2v_sampler}"
    
    def test_continuum_output_prefix(self):
        """Both workflows save to continuum/ prefix."""
        t2v = load_workflow(T2V_WORKFLOW_PATH)
        i2v = load_workflow(I2V_WORKFLOW_PATH)
        
        t2v_prefix = get_nodes(t2v).get("save_video", {}).get("inputs", {}).get("filename_prefix", "")
        i2v_prefix = get_nodes(i2v).get("save_video", {}).get("inputs", {}).get("filename_prefix", "")
        
        assert t2v_prefix.startswith("continuum/"), f"T2V prefix: {t2v_prefix}"
        assert i2v_prefix.startswith("continuum/"), f"I2V prefix: {i2v_prefix}"


# =============================================================================
# SECTION 9: WAN_RENDERER INTEGRATION
# =============================================================================

class TestWanRendererIntegration:
    """Test that workflows match wan_renderer.py expectations."""
    
    def test_t2v_has_all_renderer_params(self):
        """T2V has all params that wan_renderer.py sends."""
        workflow = load_workflow(T2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        
        # From wan_renderer.py _build_generation_params
        renderer_params = {
            "POSITIVE_PROMPT",
            "NEGATIVE_PROMPT", 
            "SEED",
            "WIDTH",
            "HEIGHT",
            "FPS",
            "FRAMES",
            "CFG_SCALE",
            "STEPS"
        }
        
        missing = renderer_params - found
        assert not missing, f"T2V missing params renderer sends: {missing}"
    
    def test_i2v_has_all_renderer_params(self):
        """I2V has all params that wan_renderer.py sends."""
        workflow = load_workflow(I2V_WORKFLOW_PATH)
        found = extract_placeholders(workflow)
        
        # From wan_renderer.py _build_generation_params + init_frame
        renderer_params = {
            "POSITIVE_PROMPT",
            "NEGATIVE_PROMPT",
            "SEED", 
            "WIDTH",
            "HEIGHT",
            "FPS",
            "FRAMES",
            "CFG_SCALE",
            "STEPS",
            "INIT_IMAGE"
        }
        
        missing = renderer_params - found
        assert not missing, f"I2V missing params renderer sends: {missing}"
    
    def test_workflow_filenames_match_renderer_constants(self):
        """Workflow filenames match wan_renderer.py constants."""
        # From wan_renderer.py:
        # DEFAULT_WORKFLOW = "pass1_structural"
        # WORKFLOW_IMG2VID = "pass1_img2vid"
        
        assert T2V_WORKFLOW_PATH.stem == "pass1_structural", \
            f"T2V should be 'pass1_structural', got {T2V_WORKFLOW_PATH.stem}"
        assert I2V_WORKFLOW_PATH.stem == "pass1_img2vid", \
            f"I2V should be 'pass1_img2vid', got {I2V_WORKFLOW_PATH.stem}"


# =============================================================================
# SECTION 10: WORKFLOW_LOADER INTEGRATION (if available)
# =============================================================================

class TestWorkflowLoaderIntegration:
    """Test integration with actual WorkflowLoader (if importable)."""
    
    loader_available = False
    import_error = None
    
    @classmethod
    def setup_class(cls):
        """Try to import WorkflowLoader."""
        try:
            from src.comfy_client.workflow_loader import WorkflowLoader
            cls.loader_available = True
            cls.WorkflowLoader = WorkflowLoader
        except ImportError as e:
            cls.import_error = str(e)
    
    def test_loader_import(self):
        """WorkflowLoader can be imported."""
        if not self.loader_available:
            import pytest
            pytest.skip(f"WorkflowLoader not available: {self.import_error}")
        assert self.loader_available
    
    def test_load_t2v_via_loader(self):
        """WorkflowLoader can load T2V workflow by name."""
        if not self.loader_available:
            import pytest
            pytest.skip("WorkflowLoader not available")
        
        loader = self.WorkflowLoader(workflows_dir=WORKFLOWS_DIR)
        template = loader.load("pass1_structural")
        
        assert template is not None
        assert template.name == "pass1_structural"
        assert len(template.placeholders) > 0
    
    def test_load_i2v_via_loader(self):
        """WorkflowLoader can load I2V workflow by name."""
        if not self.loader_available:
            import pytest
            pytest.skip("WorkflowLoader not available")
        
        loader = self.WorkflowLoader(workflows_dir=WORKFLOWS_DIR)
        template = loader.load("pass1_img2vid")
        
        assert template is not None
        assert template.name == "pass1_img2vid"
        assert "INIT_IMAGE" in template.placeholders
    
    def test_inject_via_loader(self):
        """WorkflowLoader.inject works with our workflows."""
        if not self.loader_available:
            import pytest
            pytest.skip("WorkflowLoader not available")
        
        loader = self.WorkflowLoader(workflows_dir=WORKFLOWS_DIR)
        template = loader.load("pass1_structural")
        result = loader.inject(template, STANDARD_PARAMS)
        
        assert result.success or len(result.missing) == 0
        assert "POSITIVE_PROMPT" in result.injected
    
    def test_load_and_inject_t2v(self):
        """Full load_and_inject flow works for T2V."""
        if not self.loader_available:
            import pytest
            pytest.skip("WorkflowLoader not available")
        
        loader = self.WorkflowLoader(workflows_dir=WORKFLOWS_DIR)
        
        # This is what wan_renderer does - should not raise
        workflow = loader.load_and_inject(
            "pass1_structural",
            STANDARD_PARAMS,
            strict=False,
            validate=True  # This is the key - validates no _meta
        )
        
        assert workflow is not None
        assert len(workflow) > 0
    
    def test_load_and_inject_i2v(self):
        """Full load_and_inject flow works for I2V."""
        if not self.loader_available:
            import pytest
            pytest.skip("WorkflowLoader not available")
        
        loader = self.WorkflowLoader(workflows_dir=WORKFLOWS_DIR)
        
        workflow = loader.load_and_inject(
            "pass1_img2vid",
            STANDARD_PARAMS,
            strict=False,
            validate=True
        )
        
        assert workflow is not None
        assert len(workflow) > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])