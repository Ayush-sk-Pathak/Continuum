#!/usr/bin/env python3
"""
Minimal E2E Integration Tests for P3a Workflow Pipeline.

Tests the CONTRACT between components without mocking internals:
- WanRenderer constants match workflow filenames
- Workflow placeholders match what WanRenderer sends
- WorkflowLoader can load the actual workflow files

These are true integration tests - verifying that separately-built
components will work together correctly.

LESSONS_LEARNED Applied:
- #14: WorkflowLoader.load() takes NAME not path
- #17: Path setup for imports
- #18: Workflow JSON cannot have _meta keys
- J4: Always verify interfaces before building integrations
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Set
import re

import pytest

# =============================================================================
# PATH SETUP
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WORKFLOWS_DIR = PROJECT_ROOT / "workflows"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def extract_placeholders(obj: Any, found: Set[str] = None) -> Set[str]:
    """Recursively extract {{PLACEHOLDER}} patterns from workflow."""
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


def load_workflow_json(name: str) -> Dict[str, Any]:
    """Load workflow JSON directly from file."""
    path = WORKFLOWS_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


# =============================================================================
# SECTION 1: IMPORT VERIFICATION
# =============================================================================

class TestImports:
    """Verify all required modules can be imported."""
    
    def test_import_wan_renderer(self):
        """WanRenderer class can be imported."""
        from src.renderers.wan_renderer import WanRenderer
        assert WanRenderer is not None
    
    def test_import_workflow_loader(self):
        """WorkflowLoader can be imported."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        assert WorkflowLoader is not None
    
    def test_import_job_spec(self):
        """JobSpec can be imported."""
        from src.renderers.base import JobSpec
        assert JobSpec is not None
    
    def test_import_comfy_client(self):
        """ComfyClient can be imported."""
        from src.comfy_client.client import ComfyClient
        assert ComfyClient is not None


# =============================================================================
# SECTION 2: CONSTANT VERIFICATION
# =============================================================================

class TestRendererConstants:
    """Verify WanRenderer constants match actual workflow files."""
    
    def test_default_workflow_exists(self):
        """WanRenderer.DEFAULT_WORKFLOW matches an actual file."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow_path = WORKFLOWS_DIR / f"{WanRenderer.DEFAULT_WORKFLOW}.json"
        assert workflow_path.exists(), \
            f"DEFAULT_WORKFLOW '{WanRenderer.DEFAULT_WORKFLOW}' not found at {workflow_path}"
    
    def test_img2vid_workflow_exists(self):
        """WanRenderer.WORKFLOW_IMG2VID matches an actual file."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow_path = WORKFLOWS_DIR / f"{WanRenderer.WORKFLOW_IMG2VID}.json"
        assert workflow_path.exists(), \
            f"WORKFLOW_IMG2VID '{WanRenderer.WORKFLOW_IMG2VID}' not found at {workflow_path}"
    
    def test_default_workflow_is_t2v(self):
        """DEFAULT_WORKFLOW should be pass1_structural (T2V)."""
        from src.renderers.wan_renderer import WanRenderer
        
        assert WanRenderer.DEFAULT_WORKFLOW == "pass1_structural"
    
    def test_img2vid_workflow_is_i2v(self):
        """WORKFLOW_IMG2VID should be pass1_img2vid."""
        from src.renderers.wan_renderer import WanRenderer
        
        assert WanRenderer.WORKFLOW_IMG2VID == "pass1_img2vid"


# =============================================================================
# SECTION 3: PARAMETER CONTRACT VERIFICATION
# =============================================================================

class TestParameterContract:
    """
    Verify workflow placeholders match what WanRenderer sends.
    
    This is the critical integration test - if these don't match,
    generation will fail with missing placeholders.
    """
    
    # Parameters that _build_generation_params() always sends
    GENERATION_PARAMS = {
        "POSITIVE_PROMPT",
        "NEGATIVE_PROMPT",
        "SEED",
        "WIDTH",
        "HEIGHT",
        "FPS",
        "FRAMES",
        "CFG_SCALE",
        "STEPS",
    }
    
    def test_t2v_accepts_all_generation_params(self):
        """T2V workflow has placeholders for all generation params."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.DEFAULT_WORKFLOW)
        placeholders = extract_placeholders(workflow)
        
        missing = self.GENERATION_PARAMS - placeholders
        assert not missing, \
            f"T2V workflow missing required placeholders: {missing}"
    
    def test_i2v_accepts_all_generation_params(self):
        """I2V workflow has placeholders for all generation params."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.WORKFLOW_IMG2VID)
        placeholders = extract_placeholders(workflow)
        
        missing = self.GENERATION_PARAMS - placeholders
        assert not missing, \
            f"I2V workflow missing required placeholders: {missing}"
    
    def test_i2v_accepts_init_image(self):
        """I2V workflow has INIT_IMAGE placeholder (required for I2V)."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.WORKFLOW_IMG2VID)
        placeholders = extract_placeholders(workflow)
        
        assert "INIT_IMAGE" in placeholders, \
            "I2V workflow must have INIT_IMAGE placeholder"
    
    def test_t2v_does_not_require_init_image(self):
        """T2V workflow does NOT have INIT_IMAGE (it's text-only)."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.DEFAULT_WORKFLOW)
        placeholders = extract_placeholders(workflow)
        
        assert "INIT_IMAGE" not in placeholders, \
            "T2V workflow should not have INIT_IMAGE placeholder"


# =============================================================================
# SECTION 4: WORKFLOW LOADER INTEGRATION
# =============================================================================

class TestWorkflowLoaderIntegration:
    """Test that WorkflowLoader can load and process our workflows."""
    
    def test_loader_finds_t2v(self):
        """WorkflowLoader can find T2V workflow by name."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        from src.renderers.wan_renderer import WanRenderer
        
        loader = WorkflowLoader(WORKFLOWS_DIR)
        template = loader.load(WanRenderer.DEFAULT_WORKFLOW)
        
        assert template is not None
        assert template.name == WanRenderer.DEFAULT_WORKFLOW
    
    def test_loader_finds_i2v(self):
        """WorkflowLoader can find I2V workflow by name."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        from src.renderers.wan_renderer import WanRenderer
        
        loader = WorkflowLoader(WORKFLOWS_DIR)
        template = loader.load(WanRenderer.WORKFLOW_IMG2VID)
        
        assert template is not None
        assert template.name == WanRenderer.WORKFLOW_IMG2VID
    
    def test_loader_extracts_placeholders(self):
        """WorkflowLoader correctly identifies placeholders."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        from src.renderers.wan_renderer import WanRenderer
        
        loader = WorkflowLoader(WORKFLOWS_DIR)
        template = loader.load(WanRenderer.DEFAULT_WORKFLOW)
        
        # Template should have placeholders identified
        assert len(template.placeholders) > 0
        assert "POSITIVE_PROMPT" in template.placeholders
        assert "SEED" in template.placeholders
    
    def test_load_and_inject_validates_workflow(self):
        """load_and_inject with validate=True should pass for our workflows."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        from src.renderers.wan_renderer import WanRenderer
        
        loader = WorkflowLoader(WORKFLOWS_DIR)
        
        params = {
            "POSITIVE_PROMPT": "test prompt",
            "NEGATIVE_PROMPT": "bad quality",
            "SEED": 42,
            "WIDTH": 1280,
            "HEIGHT": 720,
            "FPS": 12,
            "FRAMES": 48,
            "CFG_SCALE": 7.0,
            "STEPS": 20,
        }
        
        # This should NOT raise - if it does, workflow has issues
        workflow = loader.load_and_inject(
            WanRenderer.DEFAULT_WORKFLOW,
            params,
            strict=False,
            validate=True  # Key test - validates node structure
        )
        
        assert workflow is not None
        assert len(workflow) > 0
    
    def test_i2v_load_and_inject_with_init_image(self):
        """I2V workflow can be loaded with INIT_IMAGE param."""
        from src.comfy_client.workflow_loader import WorkflowLoader
        from src.renderers.wan_renderer import WanRenderer
        
        loader = WorkflowLoader(WORKFLOWS_DIR)
        
        params = {
            "POSITIVE_PROMPT": "test prompt",
            "NEGATIVE_PROMPT": "bad quality",
            "SEED": 42,
            "WIDTH": 1280,
            "HEIGHT": 720,
            "FPS": 12,
            "FRAMES": 48,
            "CFG_SCALE": 7.0,
            "STEPS": 20,
            "INIT_IMAGE": "uploaded/test_frame.png",  # I2V specific
        }
        
        workflow = loader.load_and_inject(
            WanRenderer.WORKFLOW_IMG2VID,
            params,
            strict=False,
            validate=True
        )
        
        assert workflow is not None
        
        # Verify INIT_IMAGE was injected
        workflow_str = json.dumps(workflow)
        assert "uploaded/test_frame.png" in workflow_str


# =============================================================================
# SECTION 5: WORKFLOW STRUCTURE VERIFICATION
# =============================================================================

class TestWorkflowStructure:
    """Verify workflow structure is correct for ComfyUI."""
    
    def test_t2v_has_required_nodes(self):
        """T2V workflow has all required node types."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.DEFAULT_WORKFLOW)
        class_types = {n.get("class_type") for n in workflow.values() if isinstance(n, dict)}
        
        required = {"CLIPLoader", "VAELoader", "UNETLoader", "KSampler", "VAEDecode"}
        missing = required - class_types
        
        assert not missing, f"T2V missing required nodes: {missing}"
    
    def test_i2v_has_image_nodes(self):
        """I2V workflow has image conditioning nodes."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.WORKFLOW_IMG2VID)
        class_types = {n.get("class_type") for n in workflow.values() if isinstance(n, dict)}
        
        assert "LoadImage" in class_types, "I2V must have LoadImage node"
        assert "CLIPVisionLoader" in class_types, "I2V must have CLIPVisionLoader"
    
    def test_t2v_uses_t2v_model(self):
        """T2V workflow uses T2V UNET model."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.DEFAULT_WORKFLOW)
        
        # Find UNET loader
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "UNETLoader":
                unet_name = node.get("inputs", {}).get("unet_name", "")
                assert "t2v" in unet_name.lower(), \
                    f"T2V should use t2v model, got: {unet_name}"
                return
        
        pytest.fail("No UNETLoader found in T2V workflow")
    
    def test_i2v_uses_i2v_model(self):
        """I2V workflow uses I2V UNET model."""
        from src.renderers.wan_renderer import WanRenderer
        
        workflow = load_workflow_json(WanRenderer.WORKFLOW_IMG2VID)
        
        # Find UNET loader
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "UNETLoader":
                unet_name = node.get("inputs", {}).get("unet_name", "")
                assert "i2v" in unet_name.lower(), \
                    f"I2V should use i2v model, got: {unet_name}"
                return
        
        pytest.fail("No UNETLoader found in I2V workflow")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])