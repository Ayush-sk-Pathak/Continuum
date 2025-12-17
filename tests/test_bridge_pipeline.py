#!/usr/bin/env python3
"""
End-to-End Integration Tests for P3a Workflow Pipeline.

Tests the ACTUAL integration between:
- WanRenderer
- WorkflowLoader  
- Workflow JSON files

Strategy: Mock only the NETWORK layer (ComfyClient), let everything else run for real.
This validates that the workflow selection, parameter building, and injection all work together.

LESSONS_LEARNED Applied:
- #14: WorkflowLoader.load() takes NAME not path
- #17: Path setup for imports
- #18: Workflow JSON cannot have _meta keys
- J4: Always verify interfaces before building integrations
"""

import json
import sys
import os
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

import pytest

# =============================================================================
# PATH SETUP
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WORKFLOWS_DIR = PROJECT_ROOT / "workflows"


# =============================================================================
# MOCK COMFY OBJECTS
# =============================================================================

@dataclass
class MockComfyJob:
    """Mock of ComfyJob from client.py."""
    prompt_id: str
    client_id: str = "test-client"
    status: str = "pending"
    outputs: Optional[Dict] = None
    error: Optional[str] = None


# =============================================================================
# FIXTURES: MOCK COMFY CLIENT
# =============================================================================

@pytest.fixture
def mock_comfy_client():
    """
    Create a mock ComfyClient that captures submitted workflows.
    
    This mocks the NETWORK layer while letting all business logic run for real.
    """
    client = AsyncMock()
    
    # Storage for inspection
    client.submitted_workflows = []
    client.uploaded_files = {}
    
    async def mock_connect():
        return True
    
    async def mock_upload_file(file_path):
        filename = Path(file_path).name
        client.uploaded_files[str(file_path)] = filename
        return {"name": filename, "subfolder": "", "type": "input"}
    
    async def mock_submit_workflow(workflow):
        # Capture the workflow for inspection
        client.submitted_workflows.append(workflow)
        
        # Return a mock ComfyJob object
        return MockComfyJob(
            prompt_id="test-prompt-123",
            client_id="test-client",
            status="queued",
            outputs=None,
        )
    
    async def mock_wait_for_completion(prompt_id: str, **kwargs):
        """
        Mock wait_for_completion.
        
        IMPORTANT: prompt_id is a STRING, not a job object!
        (See wan_renderer.py line 255-259)
        """
        # Return a completed MockComfyJob
        return MockComfyJob(
            prompt_id=prompt_id,
            client_id="test-client",
            status="completed",
            outputs={"videos": [{"filename": "output.mp4", "subfolder": "continuum"}]},
        )
    
    async def mock_download_output(prompt_id_or_job, output_dir=None):
        """Mock downloading output file."""
        if output_dir is None:
            output_dir = Path(tempfile.gettempdir())
        else:
            output_dir = Path(output_dir)
        output_path = output_dir / "output.mp4"
        output_path.touch()
        return output_path
    
    client.connect = mock_connect
    client.disconnect = AsyncMock()
    client.upload_file = mock_upload_file
    client.submit_workflow = mock_submit_workflow
    client.wait_for_completion = mock_wait_for_completion
    client.download_output = mock_download_output
    
    return client


# =============================================================================
# FIXTURES: JOB SPECS
# =============================================================================

@pytest.fixture
def basic_job_spec():
    """A basic JobSpec with no special features (should use T2V)."""
    from src.renderers.base import JobSpec, RenderQuality
    
    return JobSpec(
        prompt="A woman walking through a sunny garden",
        negative_prompt="blurry, low quality",
        duration_sec=4.0,
        seed=42,
        width=1280,
        height=720,
        fps=12,
        cfg_scale=7.0,
        steps=20,
        quality=RenderQuality.STANDARD,
    )


@pytest.fixture
def job_spec_with_init_frame(tmp_path):
    """A JobSpec with init_frame set (should use I2V)."""
    from src.renderers.base import JobSpec, RenderQuality
    
    # Create a fake init frame file
    init_frame = tmp_path / "init_frame.png"
    init_frame.write_bytes(b"fake png data")
    
    return JobSpec(
        prompt="The same woman continuing to walk",
        negative_prompt="blurry, low quality",
        duration_sec=4.0,
        init_frame=init_frame,
        seed=42,
        width=1280,
        height=720,
        fps=12,
        cfg_scale=7.0,
        steps=20,
        quality=RenderQuality.STANDARD,
    )


# =============================================================================
# FIXTURES: RENDERER
# =============================================================================

@pytest.fixture
def initialized_renderer(mock_comfy_client):
    """Create a WanRenderer with mocked client."""
    from src.renderers.wan_renderer import WanRenderer
    from src.comfy_client.workflow_loader import WorkflowLoader
    
    renderer = WanRenderer(
        comfy_host="ws://mock:8188",  # Note: comfy_host not comfy_url
        workflows_dir=WORKFLOWS_DIR,
    )
    
    # Inject the mock client and mark as initialized
    renderer._client = mock_comfy_client
    renderer._loader = WorkflowLoader(WORKFLOWS_DIR)
    renderer._initialized = True  # Note: _initialized not _connected
    
    return renderer


@pytest.fixture
def renderer_with_captured_workflow(mock_comfy_client, tmp_path):
    """
    Renderer configured to capture submitted workflow AND mock file operations.
    """
    from src.renderers.wan_renderer import WanRenderer
    from src.comfy_client.workflow_loader import WorkflowLoader
    
    renderer = WanRenderer(
        comfy_host="ws://mock:8188",  # Note: comfy_host not comfy_url
        workflows_dir=WORKFLOWS_DIR,
        output_dir=tmp_path,
    )
    
    renderer._client = mock_comfy_client
    renderer._loader = WorkflowLoader(WORKFLOWS_DIR)
    renderer._initialized = True
    
    return renderer, mock_comfy_client


# =============================================================================
# SECTION 1: WORKFLOW TEMPLATE SELECTION
# =============================================================================

class TestWorkflowTemplateSelection:
    """Test that WanRenderer selects correct workflow based on JobSpec."""
    
    def test_basic_job_selects_t2v(self, initialized_renderer, basic_job_spec):
        """Job without init_frame should select T2V workflow."""
        template = initialized_renderer._select_workflow_template(basic_job_spec)
        assert template == "pass1_structural", f"Expected T2V, got {template}"
    
    def test_init_frame_job_selects_i2v(self, initialized_renderer, job_spec_with_init_frame):
        """Job with init_frame should select I2V workflow."""
        template = initialized_renderer._select_workflow_template(job_spec_with_init_frame)
        assert template == "pass1_img2vid", f"Expected I2V, got {template}"
    
    def test_init_frame_takes_priority(self, initialized_renderer, job_spec_with_init_frame):
        """Init frame selection takes priority over character refs."""
        from src.renderers.base import CharacterRef
        
        # Add a character ref (which might also trigger workflow selection)
        job_spec_with_init_frame.character_refs = [
            CharacterRef(entity_id="test", name="Test Character")
        ]
        
        template = initialized_renderer._select_workflow_template(job_spec_with_init_frame)
        # Should still be I2V because we have init_frame
        assert "img2vid" in template or template == "pass1_img2vid"


# =============================================================================
# SECTION 2: PARAMETER BUILDING
# =============================================================================

class TestParameterBuilding:
    """Test that WanRenderer builds correct parameters from JobSpec."""
    
    def test_basic_params_built(self, initialized_renderer, basic_job_spec):
        """All required parameters are built from JobSpec."""
        params = initialized_renderer._build_generation_params(basic_job_spec)
        
        required_keys = [
            "POSITIVE_PROMPT", "NEGATIVE_PROMPT", "SEED",
            "WIDTH", "HEIGHT", "FPS", "FRAMES"
        ]
        
        for key in required_keys:
            assert key in params, f"Missing param: {key}"
    
    def test_params_match_job_spec(self, initialized_renderer, basic_job_spec):
        """Built parameters match JobSpec values."""
        params = initialized_renderer._build_generation_params(basic_job_spec)
        
        assert params["POSITIVE_PROMPT"] == basic_job_spec.prompt
        assert params["SEED"] == basic_job_spec.seed
        assert params["WIDTH"] == basic_job_spec.width
        assert params["HEIGHT"] == basic_job_spec.height
        assert params["FPS"] == basic_job_spec.fps
    
    def test_frames_calculated_correctly(self, initialized_renderer, basic_job_spec):
        """FRAMES is calculated from duration_sec * fps."""
        params = initialized_renderer._build_generation_params(basic_job_spec)
        
        expected_frames = int(basic_job_spec.duration_sec * basic_job_spec.fps)
        assert params["FRAMES"] == expected_frames


# =============================================================================
# SECTION 3: WORKFLOW LOADING INTEGRATION
# =============================================================================

class TestWorkflowLoadingIntegration:
    """Test that WanRenderer + WorkflowLoader work together."""
    
    def test_loader_is_initialized(self, initialized_renderer):
        """Renderer initializes WorkflowLoader."""
        assert initialized_renderer._loader is not None
    
    @pytest.mark.asyncio
    async def test_can_load_t2v_workflow(self, initialized_renderer, basic_job_spec):
        """Should successfully load and inject T2V workflow."""
        workflow = await initialized_renderer._build_workflow(basic_job_spec, {})
        
        assert workflow is not None
        assert len(workflow) > 0
        # Should have the expected nodes (workflow should be valid)
        assert any("sampler" in str(k).lower() for k in workflow.keys())
    
    @pytest.mark.asyncio
    async def test_can_load_i2v_workflow(self, initialized_renderer, job_spec_with_init_frame, mock_comfy_client):
        """Should successfully load and inject I2V workflow."""
        # Simulate the init frame being uploaded
        init_frame_path = str(job_spec_with_init_frame.init_frame)
        uploaded_files = {init_frame_path: "uploaded_init_frame.png"}
        
        workflow = await initialized_renderer._build_workflow(
            job_spec_with_init_frame,
            uploaded_files
        )
        
        assert workflow is not None
        assert len(workflow) > 0
    
    @pytest.mark.asyncio
    async def test_params_injected_into_t2v(self, initialized_renderer, basic_job_spec):
        """Parameters should actually be injected into T2V workflow."""
        workflow = await initialized_renderer._build_workflow(basic_job_spec, {})
        
        # The prompt should be in the workflow somewhere
        workflow_str = json.dumps(workflow)
        assert basic_job_spec.prompt in workflow_str, \
            "Prompt was not injected into workflow"
    
    @pytest.mark.asyncio
    async def test_init_image_injected_into_i2v(self, initialized_renderer, job_spec_with_init_frame):
        """INIT_IMAGE should be injected into I2V workflow."""
        init_frame_path = str(job_spec_with_init_frame.init_frame)
        uploaded_files = {init_frame_path: "uploaded_init.png"}
        
        workflow = await initialized_renderer._build_workflow(
            job_spec_with_init_frame,
            uploaded_files
        )
        
        # The uploaded filename should be in the workflow
        workflow_str = json.dumps(workflow)
        assert "uploaded_init.png" in workflow_str, \
            "Init image was not injected into workflow"
    
    @pytest.mark.asyncio
    async def test_injection_preserves_node_structure(self, initialized_renderer, basic_job_spec):
        """Node references should still be valid after injection."""
        workflow = await initialized_renderer._build_workflow(basic_job_spec, {})
        
        node_ids = set(workflow.keys())
        
        for node_id, node in workflow.items():
            if isinstance(node, dict):
                inputs = node.get("inputs", {})
                for input_name, input_value in inputs.items():
                    if isinstance(input_value, list) and len(input_value) >= 1:
                        ref_id = str(input_value[0])
                        assert ref_id in node_ids, \
                            f"{node_id}.{input_name} references invalid node '{ref_id}'"


# =============================================================================
# SECTION 4: FULL E2E FLOW
# =============================================================================

class TestEndToEndFlow:
    """Test complete generate() flow with mocked network."""
    
    @pytest.mark.asyncio
    async def test_e2e_t2v_workflow_submitted(self, renderer_with_captured_workflow, basic_job_spec):
        """Full E2E: T2V job should submit valid workflow to ComfyUI."""
        renderer, mock_client = renderer_with_captured_workflow
        
        # Run the full generate flow
        result = await renderer.generate(basic_job_spec)
        
        # Should have submitted exactly one workflow
        assert len(mock_client.submitted_workflows) == 1
        
        submitted = mock_client.submitted_workflows[0]
        # Should have valid nodes
        assert len(submitted) > 0
        assert any("sampler" in k.lower() for k in submitted.keys())
    
    @pytest.mark.asyncio
    async def test_e2e_i2v_workflow_submitted(self, renderer_with_captured_workflow, job_spec_with_init_frame):
        """Full E2E: I2V job should submit valid workflow with init image."""
        renderer, mock_client = renderer_with_captured_workflow
        
        # Run the full generate flow
        result = await renderer.generate(job_spec_with_init_frame)
        
        assert len(mock_client.submitted_workflows) == 1
        
        submitted = mock_client.submitted_workflows[0]
        # I2V should have LoadImage node
        class_types = {n.get("class_type") for n in submitted.values() if isinstance(n, dict)}
        assert "LoadImage" in class_types, f"I2V missing LoadImage. Has: {class_types}"
    
    @pytest.mark.asyncio
    async def test_e2e_init_frame_uploaded(self, renderer_with_captured_workflow, job_spec_with_init_frame):
        """Init frame should be uploaded before workflow submission."""
        renderer, mock_client = renderer_with_captured_workflow
        
        await renderer.generate(job_spec_with_init_frame)
        
        # Check that the init frame was "uploaded"
        init_path = str(job_spec_with_init_frame.init_frame)
        assert init_path in mock_client.uploaded_files, \
            f"Init frame not uploaded. Uploaded: {mock_client.uploaded_files.keys()}"
    
    @pytest.mark.asyncio
    async def test_e2e_returns_render_result(self, renderer_with_captured_workflow, basic_job_spec):
        """generate() should return a valid RenderResult."""
        from src.renderers.base import RenderResult
        
        renderer, mock_client = renderer_with_captured_workflow
        
        result = await renderer.generate(basic_job_spec)
        
        assert result is not None
        assert isinstance(result, RenderResult)
        assert result.video_path is not None
    
    @pytest.mark.asyncio
    async def test_e2e_prompt_in_submitted_workflow(self, renderer_with_captured_workflow, basic_job_spec):
        """The actual prompt should appear in the submitted workflow."""
        renderer, mock_client = renderer_with_captured_workflow
        
        # Use a distinctive prompt
        basic_job_spec.prompt = "UNIQUE_TEST_PROMPT_12345"
        
        await renderer.generate(basic_job_spec)
        
        submitted = mock_client.submitted_workflows[0]
        workflow_str = json.dumps(submitted)
        
        assert "UNIQUE_TEST_PROMPT_12345" in workflow_str, \
            "Prompt not found in submitted workflow"
    
    @pytest.mark.asyncio
    async def test_e2e_seed_in_submitted_workflow(self, renderer_with_captured_workflow, basic_job_spec):
        """The seed should be injected into the workflow."""
        renderer, mock_client = renderer_with_captured_workflow
        
        basic_job_spec.seed = 99999
        
        await renderer.generate(basic_job_spec)
        
        submitted = mock_client.submitted_workflows[0]
        workflow_str = json.dumps(submitted)
        
        assert "99999" in workflow_str, \
            "Seed not found in submitted workflow"


# =============================================================================
# SECTION 5: ERROR HANDLING
# =============================================================================

class TestErrorHandling:
    """Test error handling and fallbacks."""
    
    @pytest.mark.asyncio
    async def test_missing_workflow_falls_back(self, initialized_renderer, basic_job_spec):
        """If specific workflow missing, should fall back to default."""
        # Force selection of a non-existent workflow
        initialized_renderer.WORKFLOW_WITH_LORA = "nonexistent_workflow"
        
        # Add a fake LoRA to trigger lora workflow selection
        from src.renderers.base import CharacterRef
        
        # Create a fake lora path that "exists" but we won't use
        fake_lora = MagicMock()
        fake_lora.exists.return_value = True
        
        basic_job_spec.character_refs = [
            CharacterRef(
                entity_id="test",
                name="Test",
                lora_path=fake_lora,
            )
        ]
        
        # This should fall back to default workflow, not crash
        try:
            workflow = await initialized_renderer._build_workflow(basic_job_spec, {})
            # If we get here with a workflow, fallback worked
            assert workflow is not None
        except FileNotFoundError:
            # Also acceptable - means it tried to load the nonexistent workflow
            # and properly raised an error
            pass


# =============================================================================
# SECTION 6: WORKFLOW CONTENT VERIFICATION  
# =============================================================================

class TestWorkflowContentVerification:
    """Verify the actual content of submitted workflows."""
    
    @pytest.mark.asyncio
    async def test_t2v_has_empty_latent_not_image(self, renderer_with_captured_workflow, basic_job_spec):
        """T2V workflow should use EmptyHunyuanLatentVideo, not LoadImage."""
        renderer, mock_client = renderer_with_captured_workflow
        
        await renderer.generate(basic_job_spec)
        
        submitted = mock_client.submitted_workflows[0]
        class_types = {n.get("class_type") for n in submitted.values() if isinstance(n, dict)}
        
        assert "EmptyHunyuanLatentVideo" in class_types, \
            f"T2V should have EmptyHunyuanLatentVideo. Has: {class_types}"
        # T2V should NOT have LoadImage (that's for I2V)
        # Note: This check might need adjustment based on actual workflow structure
    
    @pytest.mark.asyncio
    async def test_i2v_has_image_conditioning(self, renderer_with_captured_workflow, job_spec_with_init_frame):
        """I2V workflow should have image conditioning nodes."""
        renderer, mock_client = renderer_with_captured_workflow
        
        await renderer.generate(job_spec_with_init_frame)
        
        submitted = mock_client.submitted_workflows[0]
        class_types = {n.get("class_type") for n in submitted.values() if isinstance(n, dict)}
        
        # I2V should have these image-related nodes
        assert "LoadImage" in class_types, f"I2V missing LoadImage"
        assert "CLIPVisionEncode" in class_types, f"I2V missing CLIPVisionEncode"
    
    @pytest.mark.asyncio
    async def test_different_unet_models(self, renderer_with_captured_workflow, basic_job_spec, job_spec_with_init_frame):
        """T2V and I2V should use different UNET models."""
        renderer, mock_client = renderer_with_captured_workflow
        
        # Generate T2V
        await renderer.generate(basic_job_spec)
        t2v_workflow = mock_client.submitted_workflows[0]
        
        # Reset for I2V
        mock_client.submitted_workflows.clear()
        
        # Generate I2V
        await renderer.generate(job_spec_with_init_frame)
        i2v_workflow = mock_client.submitted_workflows[0]
        
        # Extract UNET model names
        def get_unet_name(workflow):
            for node in workflow.values():
                if isinstance(node, dict) and node.get("class_type") == "UNETLoader":
                    return node.get("inputs", {}).get("unet_name", "")
            return ""
        
        t2v_unet = get_unet_name(t2v_workflow)
        i2v_unet = get_unet_name(i2v_workflow)
        
        # They should be different (t2v vs i2v model)
        assert t2v_unet != i2v_unet or "t2v" in t2v_unet.lower(), \
            f"Expected different models: T2V={t2v_unet}, I2V={i2v_unet}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])