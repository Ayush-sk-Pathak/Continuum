"""
Comprehensive tests for ComfyUI workflow JSON files.

Tests verify:
1. JSON validity and structure
2. ComfyUI node format compliance
3. Placeholder syntax and completeness
4. Node connectivity (no dangling references)
5. Contract alignment with Python code (wan_renderer.py, bridge_engine.py)
6. Workflow family consistency (LoRA variants match base)

Run with: pytest tests/test_workflow_contracts.py -v
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def workflows_dir() -> Path:
    """Path to workflows directory."""
    # Try multiple possible locations
    candidates = [
        Path(__file__).parent.parent / "workflows",
        Path(__file__).parent.parent.parent / "workflows",
        Path("workflows"),
    ]
    for path in candidates:
        if path.exists():
            return path
    pytest.skip("Workflows directory not found")


@pytest.fixture
def all_workflow_files(workflows_dir: Path) -> List[Path]:
    """All JSON files in workflows directory (excluding config files)."""
    excluded = {"models.json", "t2v_wan21.json", "i2v_wan21.json", "t2v_wan21_api.json"}
    return [f for f in workflows_dir.glob("*.json") if f.name not in excluded]


@pytest.fixture
def pass1_structural(workflows_dir: Path) -> Dict[str, Any]:
    """Load pass1_structural.json (T2V base)."""
    path = workflows_dir / "pass1_structural.json"
    if not path.exists():
        pytest.skip("pass1_structural.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def pass1_structural_lora(workflows_dir: Path) -> Dict[str, Any]:
    """Load pass1_structural_lora.json (T2V + LoRA)."""
    path = workflows_dir / "pass1_structural_lora.json"
    if not path.exists():
        pytest.skip("pass1_structural_lora.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def pass1_img2vid(workflows_dir: Path) -> Dict[str, Any]:
    """Load pass1_img2vid.json (I2V base)."""
    path = workflows_dir / "pass1_img2vid.json"
    if not path.exists():
        pytest.skip("pass1_img2vid.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def pass1_img2vid_lora(workflows_dir: Path) -> Dict[str, Any]:
    """Load pass1_img2vid_lora.json (I2V + LoRA)."""
    path = workflows_dir / "pass1_img2vid_lora.json"
    if not path.exists():
        pytest.skip("pass1_img2vid_lora.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def bridge_basic(workflows_dir: Path) -> Dict[str, Any]:
    """Load bridge_basic.json (prompt-only bridge)."""
    path = workflows_dir / "bridge_basic.json"
    if not path.exists():
        pytest.skip("bridge_basic.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def bridge_ipadapter(workflows_dir: Path) -> Dict[str, Any]:
    """Load bridge_ipadapter.json (IP-Adapter identity bridge)."""
    path = workflows_dir / "bridge_ipadapter.json"
    if not path.exists():
        pytest.skip("bridge_ipadapter.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def bridge_pose_only(workflows_dir: Path) -> Dict[str, Any]:
    """Load bridge_pose_only.json (pose ControlNet + IP-Adapter bridge)."""
    path = workflows_dir / "bridge_pose_only.json"
    if not path.exists():
        pytest.skip("bridge_pose_only.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def bridge_full(workflows_dir: Path) -> Dict[str, Any]:
    """Load bridge_full.json (pose + depth ControlNet + IP-Adapter bridge)."""
    path = workflows_dir / "bridge_full.json"
    if not path.exists():
        pytest.skip("bridge_full.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def refine_vid2vid_simple(workflows_dir: Path) -> Dict[str, Any]:
    """Load refine_vid2vid_simple.json (Pass 2 basic refinement)."""
    path = workflows_dir / "refine_vid2vid_simple.json"
    if not path.exists():
        pytest.skip("refine_vid2vid_simple.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def refine_vid2vid_temporal(workflows_dir: Path) -> Dict[str, Any]:
    """Load refine_vid2vid_temporal.json (Pass 2 temporal refinement)."""
    path = workflows_dir / "refine_vid2vid_temporal.json"
    if not path.exists():
        pytest.skip("refine_vid2vid_temporal.json not found")
    return json.loads(path.read_text())


@pytest.fixture
def musetalk_lipsync(workflows_dir: Path) -> Dict[str, Any]:
    """Load musetalk_lipsync.json (Lip sync via Musetalk)."""
    path = workflows_dir / "musetalk_lipsync.json"
    if not path.exists():
        pytest.skip("musetalk_lipsync.json not found")
    return json.loads(path.read_text())


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")

# Reference/example files exported directly from ComfyUI (not production workflows)
# These have different structure (metadata keys, no placeholders) and should be skipped
REFERENCE_FILE_PATTERNS = [
    "t2v_wan21.json",      # Raw ComfyUI export (has 'id', 'config' keys)
    "i2v_wan21.json",      # Raw ComfyUI export (no placeholders)
    "t2v_wan21_api.json",  # API format reference
    "models.json",         # Model registry (not a workflow)
]


def is_reference_file(workflow_file: Path) -> bool:
    """Check if this is a reference/example file (not a production workflow)."""
    return workflow_file.name in REFERENCE_FILE_PATTERNS


def get_production_workflows(all_files: List[Path]) -> List[Path]:
    """Filter to only production workflow files."""
    return [f for f in all_files if not is_reference_file(f)]


def extract_placeholders(workflow: Dict[str, Any]) -> Set[str]:
    """Extract all placeholder names from a workflow."""
    placeholders = set()
    
    def recurse(obj: Any):
        if isinstance(obj, str):
            for match in PLACEHOLDER_PATTERN.finditer(obj):
                placeholders.add(match.group(1))
        elif isinstance(obj, dict):
            for v in obj.values():
                recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
    
    recurse(workflow)
    return placeholders


def get_all_node_ids(workflow: Dict[str, Any]) -> Set[str]:
    """Get all node IDs in a workflow."""
    return set(workflow.keys())


def get_referenced_nodes(workflow: Dict[str, Any]) -> Set[str]:
    """Get all node IDs referenced in connections."""
    referenced = set()
    
    for node_config in workflow.values():
        if not isinstance(node_config, dict):
            continue
        inputs = node_config.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_value in inputs.values():
            if isinstance(input_value, list) and len(input_value) >= 1:
                # Connection format: [source_node_id, output_index]
                referenced.add(str(input_value[0]))
    
    return referenced


def get_node_class_types(workflow: Dict[str, Any]) -> Dict[str, str]:
    """Get mapping of node_id -> class_type."""
    return {
        node_id: node.get("class_type", "MISSING")
        for node_id, node in workflow.items()
        if isinstance(node, dict)
    }


# =============================================================================
# SECTION 1: JSON VALIDITY
# =============================================================================

class TestJSONValidity:
    """Test that all workflow files are valid JSON."""
    
    def test_all_files_parse(self, all_workflow_files: List[Path]):
        """Every JSON file should parse without errors."""
        for workflow_file in all_workflow_files:
            try:
                data = json.loads(workflow_file.read_text())
                assert isinstance(data, dict), f"{workflow_file.name}: root must be dict"
            except json.JSONDecodeError as e:
                pytest.fail(f"{workflow_file.name}: Invalid JSON - {e}")
    
    def test_no_empty_workflows(self, all_workflow_files: List[Path]):
        """No workflow should be empty."""
        for workflow_file in all_workflow_files:
            data = json.loads(workflow_file.read_text())
            assert len(data) > 0, f"{workflow_file.name}: workflow is empty"
    
    def test_no_underscore_keys(self, all_workflow_files: List[Path]):
        """
        Workflow JSONs should not have _meta or other underscore keys.
        (LESSONS_LEARNED #18: validator treats all keys as nodes)
        """
        for workflow_file in all_workflow_files:
            data = json.loads(workflow_file.read_text())
            underscore_keys = [k for k in data.keys() if k.startswith("_")]
            assert len(underscore_keys) == 0, (
                f"{workflow_file.name}: underscore keys not allowed: {underscore_keys}"
            )


# =============================================================================
# SECTION 2: COMFYUI NODE FORMAT
# =============================================================================

class TestComfyUINodeFormat:
    """Test ComfyUI node structure compliance."""
    
    def test_all_nodes_have_class_type(self, all_workflow_files: List[Path]):
        """Every node must have a class_type field."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            for node_id, node in data.items():
                assert isinstance(node, dict), f"{workflow_file.name}.{node_id}: must be dict"
                assert "class_type" in node, f"{workflow_file.name}.{node_id}: missing class_type"
    
    def test_all_nodes_have_inputs(self, all_workflow_files: List[Path]):
        """Every node should have an inputs field (even if empty)."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            for node_id, node in data.items():
                if isinstance(node, dict):
                    assert "inputs" in node, f"{workflow_file.name}.{node_id}: missing inputs"
    
    def test_connections_are_valid_format(self, all_workflow_files: List[Path]):
        """Node connections should be [node_id, output_index] format."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            for node_id, node in data.items():
                if not isinstance(node, dict):
                    continue
                inputs = node.get("inputs", {})
                if not isinstance(inputs, dict):
                    continue
                for input_name, input_value in inputs.items():
                    if isinstance(input_value, list):
                        assert len(input_value) == 2, (
                            f"{workflow_file.name}.{node_id}.{input_name}: "
                            f"connection must be [node_id, index], got {input_value}"
                        )
                        assert isinstance(input_value[1], int), (
                            f"{workflow_file.name}.{node_id}.{input_name}: "
                            f"output index must be int, got {type(input_value[1])}"
                        )


# =============================================================================
# SECTION 3: NODE CONNECTIVITY
# =============================================================================

class TestNodeConnectivity:
    """Test that node connections don't have dangling references."""
    
    def test_no_dangling_references(self, all_workflow_files: List[Path]):
        """All referenced nodes must exist in the workflow."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            node_ids = get_all_node_ids(data)
            referenced = get_referenced_nodes(data)
            
            dangling = referenced - node_ids
            assert len(dangling) == 0, (
                f"{workflow_file.name}: dangling references: {dangling}"
            )
    
    def test_has_output_node(self, all_workflow_files: List[Path]):
        """Each workflow should have at least one output node."""
        output_types = {"SaveImage", "SaveVideo", "VHS_VideoCombine"}
        
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            class_types = set(get_node_class_types(data).values())
            
            has_output = bool(class_types & output_types)
            assert has_output, (
                f"{workflow_file.name}: no output node found. "
                f"Expected one of {output_types}, found {class_types}"
            )


# =============================================================================
# SECTION 4: PLACEHOLDER SYNTAX
# =============================================================================

class TestPlaceholderSyntax:
    """Test placeholder format and naming conventions."""
    
    def test_placeholders_use_double_braces(self, all_workflow_files: List[Path]):
        """Placeholders should use {{NAME}} format, not {NAME} or $NAME."""
        single_brace = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")
        dollar_sign = re.compile(r"\$(\w+)")
        
        for workflow_file in all_workflow_files:
            content = workflow_file.read_text()
            
            single_matches = single_brace.findall(content)
            dollar_matches = dollar_sign.findall(content)
            
            assert len(single_matches) == 0, (
                f"{workflow_file.name}: use {{{{NAME}}}} not {{NAME}}: {single_matches}"
            )
            assert len(dollar_matches) == 0, (
                f"{workflow_file.name}: use {{{{NAME}}}} not $NAME: {dollar_matches}"
            )
    
    def test_placeholders_are_uppercase(self, all_workflow_files: List[Path]):
        """Placeholder names should be UPPER_SNAKE_CASE."""
        for workflow_file in all_workflow_files:
            data = json.loads(workflow_file.read_text())
            placeholders = extract_placeholders(data)
            
            for ph in placeholders:
                assert ph == ph.upper(), (
                    f"{workflow_file.name}: placeholder should be uppercase: {ph}"
                )
                assert re.match(r"^[A-Z][A-Z0-9_]*$", ph), (
                    f"{workflow_file.name}: invalid placeholder name: {ph}"
                )


# =============================================================================
# SECTION 5: WAN RENDERER CONTRACT
# =============================================================================

class TestWanRendererContract:
    """
    Test that Pass 1 workflows accept parameters from WanRenderer.
    
    Source of Truth: wan_renderer.py _build_generation_params()
    """
    
    # Parameters that WanRenderer sends (from _build_generation_params)
    WAN_BASE_PARAMS = {
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
    
    WAN_LORA_PARAMS = {
        "LORA_PATH",
        "LORA_STRENGTH",
    }
    
    WAN_I2V_PARAMS = {
        "INIT_IMAGE",
    }
    
    def test_t2v_base_has_required_placeholders(self, pass1_structural: Dict):
        """pass1_structural.json should have all base T2V placeholders."""
        placeholders = extract_placeholders(pass1_structural)
        missing = self.WAN_BASE_PARAMS - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_t2v_lora_has_required_placeholders(self, pass1_structural_lora: Dict):
        """pass1_structural_lora.json should have base + LoRA placeholders."""
        placeholders = extract_placeholders(pass1_structural_lora)
        required = self.WAN_BASE_PARAMS | self.WAN_LORA_PARAMS
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_i2v_base_has_required_placeholders(self, pass1_img2vid: Dict):
        """pass1_img2vid.json should have base + I2V placeholders."""
        placeholders = extract_placeholders(pass1_img2vid)
        required = self.WAN_BASE_PARAMS | self.WAN_I2V_PARAMS
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_i2v_lora_has_required_placeholders(self, pass1_img2vid_lora: Dict):
        """pass1_img2vid_lora.json should have base + I2V + LoRA placeholders."""
        placeholders = extract_placeholders(pass1_img2vid_lora)
        required = self.WAN_BASE_PARAMS | self.WAN_I2V_PARAMS | self.WAN_LORA_PARAMS
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"


# =============================================================================
# SECTION 6: BRIDGE ENGINE CONTRACT
# =============================================================================

class TestBridgeEngineContract:
    """
    Test that bridge workflows accept parameters from BridgeEngine.
    
    Source of Truth: bridge_engine.py _build_generation_params()
    """
    
    # Parameters that BridgeEngine sends (from _build_generation_params)
    BRIDGE_BASIC_PARAMS = {
        "PROMPT",
        "NEGATIVE_PROMPT",
        "SOURCE_IMAGE",
        "WIDTH",
        "HEIGHT",
        "SEED",
        "STEPS",
        "CFG",
        "DENOISE",
    }
    
    BRIDGE_IPADAPTER_PARAMS = {
        "FACE_REF_IMAGE",
        "IPADAPTER_STRENGTH",
    }
    
    BRIDGE_POSE_PARAMS = {
        "POSE_IMAGE",
        "CONTROLNET_POSE_STRENGTH",
    }
    
    BRIDGE_DEPTH_PARAMS = {
        "DEPTH_IMAGE",
        "CONTROLNET_DEPTH_STRENGTH",
    }
    
    def test_bridge_basic_has_required_placeholders(self, bridge_basic: Dict):
        """bridge_basic.json should have all basic bridge placeholders."""
        placeholders = extract_placeholders(bridge_basic)
        missing = self.BRIDGE_BASIC_PARAMS - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_bridge_ipadapter_has_required_placeholders(self, bridge_ipadapter: Dict):
        """bridge_ipadapter.json should have basic + IP-Adapter placeholders."""
        placeholders = extract_placeholders(bridge_ipadapter)
        required = self.BRIDGE_BASIC_PARAMS | self.BRIDGE_IPADAPTER_PARAMS
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_bridge_pose_only_has_required_placeholders(self, bridge_pose_only: Dict):
        """bridge_pose_only.json should have basic + pose + IP-Adapter placeholders."""
        placeholders = extract_placeholders(bridge_pose_only)
        required = self.BRIDGE_BASIC_PARAMS | self.BRIDGE_IPADAPTER_PARAMS | self.BRIDGE_POSE_PARAMS
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_bridge_full_has_required_placeholders(self, bridge_full: Dict):
        """bridge_full.json should have all bridge placeholders."""
        placeholders = extract_placeholders(bridge_full)
        required = (
            self.BRIDGE_BASIC_PARAMS | 
            self.BRIDGE_IPADAPTER_PARAMS | 
            self.BRIDGE_POSE_PARAMS | 
            self.BRIDGE_DEPTH_PARAMS
        )
        missing = required - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_bridge_basic_uses_img2img_pattern(self, bridge_basic: Dict):
        """Bridge basic should use img2img pattern (encode source, denoise < 1)."""
        class_types = set(get_node_class_types(bridge_basic).values())
        
        # Should have VAEEncode (for img2img)
        assert "VAEEncode" in class_types, "Bridge should VAEEncode source image"
        
        # Should have LoadImage
        assert "LoadImage" in class_types, "Bridge should LoadImage source"
        
        # Should NOT have EmptyLatent (that's txt2img)
        empty_latent_types = {"EmptyLatentImage", "EmptyHunyuanLatentVideo"}
        assert not (class_types & empty_latent_types), (
            f"Bridge should not use empty latent (img2img, not txt2img)"
        )
    
    def test_bridge_basic_outputs_image_not_video(self, bridge_basic: Dict):
        """Bridge frames are images, not videos."""
        class_types = set(get_node_class_types(bridge_basic).values())
        
        assert "SaveImage" in class_types, "Bridge should output image (SaveImage)"
        assert "SaveVideo" not in class_types, "Bridge should not output video"
        assert "CreateVideo" not in class_types, "Bridge should not create video"
    
    def test_bridge_ipadapter_has_ipadapter_nodes(self, bridge_ipadapter: Dict):
        """IP-Adapter bridge should have IP-Adapter nodes."""
        class_types = set(get_node_class_types(bridge_ipadapter).values())
        
        assert "IPAdapterModelLoader" in class_types, "Should load IP-Adapter model"
        assert "IPAdapterAdvanced" in class_types, "Should apply IP-Adapter"
        assert "PrepImageForClipVision" in class_types, "Should prep face ref for CLIP"
    
    def test_bridge_pose_only_has_controlnet(self, bridge_pose_only: Dict):
        """Pose bridge should have ControlNet nodes."""
        class_types = set(get_node_class_types(bridge_pose_only).values())
        
        assert "ControlNetLoader" in class_types, "Should load ControlNet"
        assert "ControlNetApplyAdvanced" in class_types, "Should apply ControlNet"
        assert "IPAdapterAdvanced" in class_types, "Should also have IP-Adapter"
    
    def test_bridge_full_has_two_controlnets(self, bridge_full: Dict):
        """Full bridge should have two ControlNet loaders (pose + depth)."""
        # Count ControlNetLoader nodes
        controlnet_count = sum(
            1 for node in bridge_full.values()
            if isinstance(node, dict) and node.get("class_type") == "ControlNetLoader"
        )
        assert controlnet_count == 2, f"Should have 2 ControlNet loaders, got {controlnet_count}"
        
        # Count ControlNetApplyAdvanced nodes
        apply_count = sum(
            1 for node in bridge_full.values()
            if isinstance(node, dict) and node.get("class_type") == "ControlNetApplyAdvanced"
        )
        assert apply_count == 2, f"Should have 2 ControlNet apply nodes, got {apply_count}"


# =============================================================================
# SECTION 6B: PASS 2 REFINER CONTRACT
# =============================================================================

class TestPass2RefinerContract:
    """
    Test that Pass 2 refinement workflows accept parameters from Pass2Refiner.
    
    Source of Truth: pass2_refiner.py _build_workflow_params()
    
    Note: Different refinement methods need different parameters:
    - vid2vid_simple: Frame-by-frame, no temporal window
    - vid2vid_temporal: Batch processing with temporal context
    - freelong: Full temporal attention
    """
    
    # Base params ALL refinement workflows need
    REFINE_CORE_PARAMS = {
        "DENOISE_STRENGTH",
        "STEPS",
        "CFG_SCALE",
        "INPUT_VIDEO",
        "FPS",
        "SEED",
        "POSITIVE_PROMPT",
        "NEGATIVE_PROMPT",
    }
    
    # Additional params for temporal variants
    TEMPORAL_PARAMS = {
        "TEMPORAL_WINDOW",
    }
    
    def test_refine_vid2vid_simple_has_required_placeholders(self, refine_vid2vid_simple: Dict):
        """refine_vid2vid_simple.json should have core refinement placeholders."""
        placeholders = extract_placeholders(refine_vid2vid_simple)
        missing = self.REFINE_CORE_PARAMS - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_refine_vid2vid_simple_no_temporal_window(self, refine_vid2vid_simple: Dict):
        """Simple variant should NOT have TEMPORAL_WINDOW (it's frame-by-frame)."""
        placeholders = extract_placeholders(refine_vid2vid_simple)
        # TEMPORAL_WINDOW is for temporal variants, not simple
        assert "TEMPORAL_WINDOW" not in placeholders, (
            "vid2vid_simple should not have TEMPORAL_WINDOW - it's frame-by-frame"
        )
    
    def test_refine_vid2vid_simple_loads_video(self, refine_vid2vid_simple: Dict):
        """Refinement should load video input (not image)."""
        class_types = set(get_node_class_types(refine_vid2vid_simple).values())
        
        # Should have VHS_LoadVideo (video input)
        assert "VHS_LoadVideo" in class_types, "Should load video with VHS_LoadVideo"
        
        # Should NOT have LoadImage as primary input
        # (LoadImage might exist for other purposes, but video_loader should use VHS_LoadVideo)
        video_loader = refine_vid2vid_simple.get("video_loader", {})
        assert video_loader.get("class_type") == "VHS_LoadVideo", (
            "video_loader node should be VHS_LoadVideo"
        )
    
    def test_refine_vid2vid_simple_outputs_video(self, refine_vid2vid_simple: Dict):
        """Refinement should output video, not image."""
        class_types = set(get_node_class_types(refine_vid2vid_simple).values())
        
        assert "SaveVideo" in class_types, "Should output video with SaveVideo"
        assert "CreateVideo" in class_types, "Should create video before saving"
    
    def test_refine_vid2vid_simple_uses_img2img_pattern(self, refine_vid2vid_simple: Dict):
        """Refinement uses vid2vid (encode input, denoise, decode)."""
        class_types = set(get_node_class_types(refine_vid2vid_simple).values())
        
        # Must have encode -> sample -> decode pattern
        assert "VAEEncode" in class_types, "Should VAEEncode input video frames"
        assert "KSampler" in class_types, "Should have KSampler for denoising"
        assert "VAEDecode" in class_types, "Should VAEDecode after sampling"
    
    def test_refine_denoise_is_parameterized(self, refine_vid2vid_simple: Dict):
        """Denoise strength must be a placeholder (not hardcoded)."""
        sampler = refine_vid2vid_simple.get("sampler", {})
        denoise = sampler.get("inputs", {}).get("denoise", "")
        
        assert "{{" in str(denoise), (
            f"Denoise should be placeholder, got hardcoded: {denoise}"
        )
    
    def test_refine_uses_sdxl_not_video_model(self, refine_vid2vid_simple: Dict):
        """Refinement uses SDXL (image model) for detail work, not Wan."""
        class_types = set(get_node_class_types(refine_vid2vid_simple).values())
        
        # Should use CheckpointLoaderSimple (SDXL)
        assert "CheckpointLoaderSimple" in class_types, (
            "Refinement should use CheckpointLoaderSimple for SDXL"
        )
        
        # Should NOT have UNETLoader (that's for video models like Wan)
        assert "UNETLoader" not in class_types, (
            "Refinement should not use UNETLoader (that's for video generation)"
        )
    
    # -------------------------------------------------------------------------
    # Temporal Variant Tests
    # -------------------------------------------------------------------------
    
    def test_refine_vid2vid_temporal_has_required_placeholders(self, refine_vid2vid_temporal: Dict):
        """refine_vid2vid_temporal.json should have core + temporal placeholders."""
        placeholders = extract_placeholders(refine_vid2vid_temporal)
        
        # Must have all core params
        missing_core = self.REFINE_CORE_PARAMS - placeholders
        assert len(missing_core) == 0, f"Missing core placeholders: {missing_core}"
        
        # Must also have temporal params
        missing_temporal = self.TEMPORAL_PARAMS - placeholders
        assert len(missing_temporal) == 0, f"Missing temporal placeholders: {missing_temporal}"
    
    def test_refine_vid2vid_temporal_has_temporal_window(self, refine_vid2vid_temporal: Dict):
        """Temporal variant MUST have TEMPORAL_WINDOW placeholder."""
        placeholders = extract_placeholders(refine_vid2vid_temporal)
        assert "TEMPORAL_WINDOW" in placeholders, (
            "vid2vid_temporal must have TEMPORAL_WINDOW for batch processing"
        )
    
    def test_refine_vid2vid_temporal_uses_batch_sampler(self, refine_vid2vid_temporal: Dict):
        """Temporal variant should use batched sampling."""
        class_types = set(get_node_class_types(refine_vid2vid_temporal).values())
        
        # Should have batch-aware sampler
        has_batch_sampler = "KSamplerBatch" in class_types or any(
            "Batch" in ct for ct in class_types
        )
        assert has_batch_sampler, (
            "Temporal variant should use KSamplerBatch or similar batch node"
        )
    
    def test_refine_vid2vid_temporal_has_temporal_smoothing(self, refine_vid2vid_temporal: Dict):
        """Temporal variant should have post-processing smoothing."""
        class_types = set(get_node_class_types(refine_vid2vid_temporal).values())
        
        # Should have temporal smoothing node
        has_smooth = any(
            "Smooth" in ct or "Temporal" in ct 
            for ct in class_types 
            if ct != "VHS_LoadVideo"  # Exclude video loader
        )
        assert has_smooth, (
            "Temporal variant should have TemporalSmooth or similar node"
        )
    
    def test_refine_vid2vid_temporal_loads_video(self, refine_vid2vid_temporal: Dict):
        """Temporal variant should load video input."""
        class_types = set(get_node_class_types(refine_vid2vid_temporal).values())
        assert "VHS_LoadVideo" in class_types, "Should load video with VHS_LoadVideo"
    
    def test_refine_vid2vid_temporal_outputs_video(self, refine_vid2vid_temporal: Dict):
        """Temporal variant should output video."""
        class_types = set(get_node_class_types(refine_vid2vid_temporal).values())
        assert "SaveVideo" in class_types, "Should output video with SaveVideo"


# =============================================================================
# SECTION 6C: LIP SYNC ENGINE CONTRACT
# =============================================================================

class TestLipSyncEngineContract:
    """
    Test that lip sync workflows accept parameters from LipSyncEngine.
    
    Source of Truth: lip_sync.py lines 440-446 (params dict in sync method)
    
    Lip sync takes refined video + dialogue audio and makes mouths move.
    """
    
    # Parameters that LipSyncEngine sends
    LIPSYNC_PARAMS = {
        "VIDEO_PATH",
        "AUDIO_PATH", 
        "START_TIME",
        "END_TIME",
        "FACE_THRESHOLD",
    }
    
    def test_musetalk_has_required_placeholders(self, musetalk_lipsync: Dict):
        """musetalk_lipsync.json should have all lip sync placeholders."""
        placeholders = extract_placeholders(musetalk_lipsync)
        missing = self.LIPSYNC_PARAMS - placeholders
        assert len(missing) == 0, f"Missing placeholders: {missing}"
    
    def test_musetalk_loads_video(self, musetalk_lipsync: Dict):
        """Lip sync must load video input."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        # Should have VHS_LoadVideo
        assert "VHS_LoadVideo" in class_types, "Should load video with VHS_LoadVideo"
        
        # Verify video_loader node specifically
        video_loader = musetalk_lipsync.get("video_loader", {})
        assert video_loader.get("class_type") == "VHS_LoadVideo", (
            "video_loader node should be VHS_LoadVideo"
        )
    
    def test_musetalk_loads_audio(self, musetalk_lipsync: Dict):
        """Lip sync must load audio input."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        assert "LoadAudio" in class_types, "Should load audio with LoadAudio"
        
        # Verify audio_loader uses placeholder
        audio_loader = musetalk_lipsync.get("audio_loader", {})
        audio_input = audio_loader.get("inputs", {}).get("audio", "")
        assert "{{AUDIO_PATH}}" in str(audio_input), (
            f"audio_loader should use AUDIO_PATH placeholder, got {audio_input}"
        )
    
    def test_musetalk_has_face_detection(self, musetalk_lipsync: Dict):
        """Lip sync must detect faces before syncing."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        # Should have face detection
        has_face_detect = any("FaceDetect" in ct for ct in class_types)
        assert has_face_detect, "Should have face detection node"
    
    def test_musetalk_has_lipsync_node(self, musetalk_lipsync: Dict):
        """Lip sync must have the actual lip sync processing node."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        # Should have MuseTalkRun or similar
        has_lipsync = any("MuseTalk" in ct and "Run" in ct for ct in class_types)
        assert has_lipsync, "Should have MuseTalkRun node"
    
    def test_musetalk_has_composite(self, musetalk_lipsync: Dict):
        """Lip sync must composite synced faces back into video."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        # Should have composite node
        has_composite = any("Composite" in ct for ct in class_types)
        assert has_composite, "Should have composite node to blend faces back"
    
    def test_musetalk_outputs_video(self, musetalk_lipsync: Dict):
        """Lip sync must output video, not images."""
        class_types = set(get_node_class_types(musetalk_lipsync).values())
        
        assert "SaveVideo" in class_types, "Should output video with SaveVideo"
        assert "CreateVideo" in class_types, "Should create video before saving"
    
    def test_musetalk_time_params_are_parameterized(self, musetalk_lipsync: Dict):
        """START_TIME and END_TIME must be placeholders (not hardcoded)."""
        lip_sync_node = musetalk_lipsync.get("lip_sync", {})
        inputs = lip_sync_node.get("inputs", {})
        
        start_time = inputs.get("start_time", "")
        end_time = inputs.get("end_time", "")
        
        assert "{{" in str(start_time), (
            f"start_time should be placeholder, got: {start_time}"
        )
        assert "{{" in str(end_time), (
            f"end_time should be placeholder, got: {end_time}"
        )


# =============================================================================
# SECTION 7: WORKFLOW FAMILY CONSISTENCY
# =============================================================================

class TestWorkflowFamilyConsistency:
    """Test that workflow variants are consistent with their base versions."""
    
    def test_lora_adds_lora_loader_node(
        self,
        pass1_structural: Dict,
        pass1_structural_lora: Dict
    ):
        """LoRA variant should add LoraLoader node."""
        base_types = set(get_node_class_types(pass1_structural).values())
        lora_types = set(get_node_class_types(pass1_structural_lora).values())
        
        assert "LoraLoader" not in base_types, "Base should not have LoraLoader"
        assert "LoraLoader" in lora_types, "LoRA variant should have LoraLoader"
    
    def test_lora_routes_through_lora_node(self, pass1_structural_lora: Dict):
        """LoRA variant should route model through LoraLoader."""
        # Find model_sampling node
        model_sampling = pass1_structural_lora.get("model_sampling", {})
        inputs = model_sampling.get("inputs", {})
        model_input = inputs.get("model", [])
        
        # Should reference lora_loader, not unet_loader
        assert model_input[0] == "lora_loader", (
            f"model_sampling.model should reference lora_loader, got {model_input}"
        )
    
    def test_i2v_lora_has_both_patterns(self, pass1_img2vid_lora: Dict):
        """I2V + LoRA should have both I2V and LoRA patterns."""
        class_types = set(get_node_class_types(pass1_img2vid_lora).values())
        
        # I2V pattern
        assert "LoadImage" in class_types, "Should have LoadImage for I2V"
        assert "CLIPVisionEncode" in class_types, "Should have CLIPVisionEncode for I2V"
        assert "WanImageToVideo" in class_types, "Should have WanImageToVideo"
        
        # LoRA pattern
        assert "LoraLoader" in class_types, "Should have LoraLoader"
    
    def test_video_workflows_use_wan_model(
        self,
        pass1_structural: Dict,
        pass1_img2vid: Dict
    ):
        """Video generation workflows should use Wan models (or UNET_MODEL placeholder)."""
        for workflow, name in [
            (pass1_structural, "T2V"),
            (pass1_img2vid, "I2V")
        ]:
            unet_loader = workflow.get("unet_loader", {})
            inputs = unet_loader.get("inputs", {})
            unet_name = inputs.get("unet_name", "")
            
            # Accept either hardcoded Wan model or placeholder
            is_wan = "wan" in unet_name.lower()
            is_placeholder = "{{UNET_MODEL}}" in unet_name
            
            assert is_wan or is_placeholder, (
                f"{name} workflow should use Wan model or UNET_MODEL placeholder, got {unet_name}"
            )
    
    def test_bridge_uses_sdxl_not_wan(self, bridge_basic: Dict):
        """Bridge frames use SDXL (image model), not Wan (video model)."""
        class_types = set(get_node_class_types(bridge_basic).values())
        
        # Should use CheckpointLoaderSimple (SDXL)
        assert "CheckpointLoaderSimple" in class_types, (
            "Bridge should use CheckpointLoaderSimple for SDXL"
        )
        
        # Should NOT have UNETLoader (that's for video models)
        assert "UNETLoader" not in class_types, (
            "Bridge should not use UNETLoader (that's for video)"
        )
    
    def test_bridge_family_all_use_sdxl(
        self,
        bridge_basic: Dict,
        bridge_ipadapter: Dict,
        bridge_pose_only: Dict,
        bridge_full: Dict
    ):
        """All bridge workflows should use SDXL checkpoint."""
        for workflow, name in [
            (bridge_basic, "basic"),
            (bridge_ipadapter, "ipadapter"),
            (bridge_pose_only, "pose_only"),
            (bridge_full, "full"),
        ]:
            checkpoint = workflow.get("checkpoint_loader", {})
            ckpt_name = checkpoint.get("inputs", {}).get("ckpt_name", "")
            assert "sdxl" in ckpt_name.lower() or "sd_xl" in ckpt_name.lower(), (
                f"Bridge {name} should use SDXL, got {ckpt_name}"
            )
    
    def test_bridge_ipadapter_routes_through_ipadapter(self, bridge_ipadapter: Dict):
        """IP-Adapter bridge should route model through apply_ipadapter."""
        sampler = bridge_ipadapter.get("sampler", {})
        model_input = sampler.get("inputs", {}).get("model", [])
        
        assert model_input[0] == "apply_ipadapter", (
            f"Sampler should use IP-Adapter modified model, got {model_input}"
        )
    
    def test_bridge_full_chains_controlnets(self, bridge_full: Dict):
        """Full bridge should chain ControlNets: pose -> depth."""
        # Depth ControlNet should receive conditioning from pose ControlNet
        depth_apply = bridge_full.get("apply_controlnet_depth", {})
        positive_input = depth_apply.get("inputs", {}).get("positive", [])
        
        assert positive_input[0] == "apply_controlnet_pose", (
            f"Depth ControlNet should chain from pose, got {positive_input}"
        )


# =============================================================================
# SECTION 8: MODEL FILE CONSISTENCY
# =============================================================================

class TestModelFileConsistency:
    """Test that workflows reference consistent model files or use placeholders."""
    
    # Expected model files (hardcoded) or placeholders
    EXPECTED_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    EXPECTED_VAE = "wan_2.1_vae.safetensors"
    EXPECTED_T2V_UNET = "wan2.1_t2v_1.3B_fp16.safetensors"
    EXPECTED_I2V_UNET = "wan2.1_i2v_480p_14B_fp16.safetensors"
    EXPECTED_CLIP_VISION = "clip_vision_h.safetensors"
    
    # Accepted placeholders for tier-based model injection
    CLIP_PLACEHOLDER = "{{CLIP_MODEL}}"
    VAE_PLACEHOLDER = "{{VAE_MODEL}}"
    UNET_PLACEHOLDER = "{{UNET_MODEL}}"
    CLIP_VISION_PLACEHOLDER = "{{CLIP_VISION_MODEL}}"
    
    def test_t2v_workflows_use_consistent_models(
        self,
        pass1_structural: Dict,
        pass1_structural_lora: Dict
    ):
        """T2V workflows should use same base models or placeholders."""
        for workflow in [pass1_structural, pass1_structural_lora]:
            # Check CLIP
            clip_loader = workflow.get("clip_loader", {})
            clip_name = clip_loader.get("inputs", {}).get("clip_name", "")
            assert clip_name in [self.EXPECTED_CLIP, self.CLIP_PLACEHOLDER], (
                f"Unexpected CLIP: {clip_name}"
            )
            
            # Check VAE
            vae_loader = workflow.get("vae_loader", {})
            vae_name = vae_loader.get("inputs", {}).get("vae_name", "")
            assert vae_name in [self.EXPECTED_VAE, self.VAE_PLACEHOLDER], (
                f"Unexpected VAE: {vae_name}"
            )
            
            # Check UNET (T2V model)
            unet_loader = workflow.get("unet_loader", {})
            unet_name = unet_loader.get("inputs", {}).get("unet_name", "")
            assert unet_name in [self.EXPECTED_T2V_UNET, self.UNET_PLACEHOLDER], (
                f"Unexpected UNET: {unet_name}"
            )
    
    def test_i2v_workflows_use_i2v_model(
        self,
        pass1_img2vid: Dict,
        pass1_img2vid_lora: Dict
    ):
        """I2V workflows should use I2V model or placeholder."""
        for workflow in [pass1_img2vid, pass1_img2vid_lora]:
            unet_loader = workflow.get("unet_loader", {})
            unet_name = unet_loader.get("inputs", {}).get("unet_name", "")
            assert unet_name in [self.EXPECTED_I2V_UNET, self.UNET_PLACEHOLDER], (
                f"I2V should use I2V model or placeholder, got {unet_name}"
            )
    
    def test_i2v_workflows_have_clip_vision(
        self,
        pass1_img2vid: Dict,
        pass1_img2vid_lora: Dict
    ):
        """I2V workflows should have CLIP Vision encoder or placeholder."""
        for workflow in [pass1_img2vid, pass1_img2vid_lora]:
            clip_vision = workflow.get("clip_vision_loader", {})
            clip_name = clip_vision.get("inputs", {}).get("clip_name", "")
            assert clip_name in [self.EXPECTED_CLIP_VISION, self.CLIP_VISION_PLACEHOLDER], (
                f"Unexpected CLIP Vision: {clip_name}"
            )


# =============================================================================
# SECTION 9: REGRESSION TESTS
# =============================================================================

class TestRegressions:
    """Tests for previously discovered bugs (LESSONS_LEARNED)."""
    
    def test_lesson_18_no_meta_keys(self, all_workflow_files: List[Path]):
        """
        LESSONS_LEARNED #18: Workflow JSONs cannot have _meta keys.
        Validator treats all keys as nodes.
        """
        for workflow_file in all_workflow_files:
            data = json.loads(workflow_file.read_text())
            assert "_meta" not in data, (
                f"{workflow_file.name}: _meta key not allowed (LESSONS_LEARNED #18)"
            )
    
    def test_lesson_19_lora_variant_exists_for_i2v(self, workflows_dir: Path):
        """
        LESSONS_LEARNED #19: Early return hid LoRA logic for I2V.
        Both I2V and I2V+LoRA workflows must exist.
        """
        i2v_base = workflows_dir / "pass1_img2vid.json"
        i2v_lora = workflows_dir / "pass1_img2vid_lora.json"
        
        if i2v_base.exists():
            assert i2v_lora.exists(), (
                "If pass1_img2vid.json exists, pass1_img2vid_lora.json must also exist "
                "(LESSONS_LEARNED #19: early return fix)"
            )


# =============================================================================
# SECTION 10: EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_placeholders_in_nested_strings(self, all_workflow_files: List[Path]):
        """Placeholders should work in nested structures."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            placeholders = extract_placeholders(data)
            
            # Production workflows should have placeholders
            assert len(placeholders) > 0, (
                f"{workflow_file.name}: no placeholders found - is this intentional?"
            )
    
    def test_sampler_has_seed_placeholder(self, all_workflow_files: List[Path]):
        """Sampler nodes should use SEED placeholder for reproducibility."""
        for workflow_file in get_production_workflows(all_workflow_files):
            data = json.loads(workflow_file.read_text())
            
            for node_id, node in data.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") == "KSampler":
                    seed = node.get("inputs", {}).get("seed", "")
                    # Should be placeholder or -1 (random)
                    is_placeholder = isinstance(seed, str) and "{{" in seed
                    is_random = seed == -1
                    
                    assert is_placeholder or is_random, (
                        f"{workflow_file.name}.{node_id}: seed should be "
                        f"placeholder or -1, got {seed}"
                    )