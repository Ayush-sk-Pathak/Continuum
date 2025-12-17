"""
Stress Tests for ComfyUI Workflows

These tests probe for weak points that could cause RUNTIME failures:
- ComfyUI execution gotchas
- Type coercion issues  
- Node execution order problems
- Value range violations
- Model compatibility issues
- Memory/VRAM concerns
- Orphan nodes and dead paths

Run with: pytest tests/test_workflow_stress.py -v

These are more aggressive than contract tests - they simulate
what ComfyUI will actually do when executing the workflow.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from collections import deque

import pytest


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def workflows_dir() -> Path:
    """Path to workflows directory."""
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
def production_workflows(workflows_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load all production workflows as dict."""
    reference_files = {"t2v_wan21.json", "i2v_wan21.json", "t2v_wan21_api.json", "models.json"}
    workflows = {}
    for path in workflows_dir.glob("*.json"):
        if path.name not in reference_files:
            workflows[path.name] = json.loads(path.read_text())
    return workflows


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def extract_all_placeholders_with_context(workflow: Dict) -> List[Tuple[str, str, str, Any]]:
    """
    Extract placeholders with full context.
    Returns: [(placeholder_name, node_id, input_name, full_value), ...]
    """
    results = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if isinstance(value, str):
                for match in PLACEHOLDER_PATTERN.finditer(value):
                    results.append((match.group(1), node_id, input_name, value))
    return results


def get_node_output_count(class_type: str) -> int:
    """
    Estimate how many outputs a node type has.
    ComfyUI nodes have varying output counts.
    """
    # Common node output counts (conservative estimates)
    output_counts = {
        # Loaders typically output 1
        "CheckpointLoaderSimple": 3,  # model, clip, vae
        "UNETLoader": 1,
        "CLIPLoader": 1,
        "VAELoader": 1,
        "ControlNetLoader": 1,
        "CLIPVisionLoader": 1,
        "IPAdapterModelLoader": 1,
        "LoraLoader": 2,  # model, clip
        
        # Encoders
        "CLIPTextEncode": 1,
        "CLIPVisionEncode": 1,
        "VAEEncode": 1,
        
        # Processing
        "KSampler": 1,
        "VAEDecode": 1,
        "ModelSamplingSD3": 1,
        "IPAdapterAdvanced": 1,
        "ControlNetApplyAdvanced": 2,  # positive, negative
        "WanImageToVideo": 3,  # positive, negative, latent
        
        # Image ops
        "LoadImage": 2,  # image, mask
        "ImageScale": 1,
        "PrepImageForClipVision": 1,
        
        # Output
        "SaveImage": 0,
        "SaveVideo": 0,
        "CreateVideo": 1,
        
        # Latent
        "EmptyLatentImage": 1,
        "EmptyHunyuanLatentVideo": 1,
    }
    return output_counts.get(class_type, 1)  # Default to 1 if unknown


def build_dependency_graph(workflow: Dict) -> Dict[str, Set[str]]:
    """Build graph of node dependencies (node -> nodes it depends on)."""
    deps = {node_id: set() for node_id in workflow.keys()}
    
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_value in inputs.values():
            if isinstance(input_value, list) and len(input_value) >= 1:
                source_node = str(input_value[0])
                if source_node in deps:
                    deps[node_id].add(source_node)
    
    return deps


def find_orphan_nodes(workflow: Dict) -> Set[str]:
    """
    Find nodes that don't contribute to any output.
    These waste VRAM and indicate workflow bugs.
    """
    output_types = {"SaveImage", "SaveVideo", "VHS_VideoCombine"}
    
    # Find output nodes
    output_nodes = set()
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") in output_types:
            output_nodes.add(node_id)
    
    if not output_nodes:
        return set(workflow.keys())  # Everything is orphaned if no output
    
    # BFS backwards from outputs to find all contributing nodes
    deps = build_dependency_graph(workflow)
    reverse_deps = {node_id: set() for node_id in workflow.keys()}
    for node_id, sources in deps.items():
        for source in sources:
            reverse_deps[source].add(node_id)
    
    # Walk backwards from outputs
    contributing = set()
    queue = deque(output_nodes)
    while queue:
        node_id = queue.popleft()
        if node_id in contributing:
            continue
        contributing.add(node_id)
        for source in deps.get(node_id, []):
            if source not in contributing:
                queue.append(source)
    
    return set(workflow.keys()) - contributing


def detect_circular_deps(workflow: Dict) -> List[List[str]]:
    """Detect circular dependencies (would cause infinite loop)."""
    deps = build_dependency_graph(workflow)
    cycles = []
    
    visited = set()
    rec_stack = set()
    path = []
    
    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in deps.get(node, []):
            if neighbor not in visited:
                cycle = dfs(neighbor)
                if cycle:
                    return cycle
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]
        
        path.pop()
        rec_stack.remove(node)
        return None
    
    for node in workflow.keys():
        if node not in visited:
            cycle = dfs(node)
            if cycle:
                cycles.append(cycle)
    
    return cycles


# =============================================================================
# SECTION 1: TYPE COERCION STRESS
# =============================================================================

class TestTypeCoercion:
    """Test that placeholder types will work when injected."""
    
    # Inputs that MUST be integers (ComfyUI will fail otherwise)
    INTEGER_INPUTS = {"seed", "steps", "width", "height", "length", "batch_size"}
    
    # Inputs that MUST be floats
    FLOAT_INPUTS = {"cfg", "denoise", "strength", "weight", "shift"}
    
    # Inputs that are file paths (strings)
    PATH_INPUTS = {"image", "ckpt_name", "unet_name", "vae_name", "clip_name", 
                   "control_net_name", "lora_name", "ipadapter_file"}
    
    def test_integer_placeholders_are_full_value(self, production_workflows: Dict):
        """
        Integer inputs with placeholders must be FULL placeholder (not partial).
        "{{SEED}}" is OK, "prefix_{{SEED}}" would fail type coercion.
        """
        for filename, workflow in production_workflows.items():
            for ph, node_id, input_name, value in extract_all_placeholders_with_context(workflow):
                input_lower = input_name.lower()
                
                # Check if this is an integer input
                is_integer_input = any(int_name in input_lower for int_name in self.INTEGER_INPUTS)
                
                if is_integer_input:
                    # Value must be EXACTLY the placeholder, nothing else
                    is_full_placeholder = value.strip() == f"{{{{{ph}}}}}"
                    assert is_full_placeholder, (
                        f"{filename}.{node_id}.{input_name}: integer input has partial "
                        f"placeholder '{value}' - will fail type coercion"
                    )
    
    def test_float_placeholders_are_full_value(self, production_workflows: Dict):
        """Float inputs with placeholders must be FULL placeholder."""
        for filename, workflow in production_workflows.items():
            for ph, node_id, input_name, value in extract_all_placeholders_with_context(workflow):
                input_lower = input_name.lower()
                
                is_float_input = any(float_name in input_lower for float_name in self.FLOAT_INPUTS)
                
                if is_float_input:
                    is_full_placeholder = value.strip() == f"{{{{{ph}}}}}"
                    assert is_full_placeholder, (
                        f"{filename}.{node_id}.{input_name}: float input has partial "
                        f"placeholder '{value}' - will fail type coercion"
                    )


# =============================================================================
# SECTION 2: OUTPUT INDEX BOUNDS
# =============================================================================

class TestOutputIndexBounds:
    """Test that connection output indices are within bounds."""
    
    def test_output_indices_in_bounds(self, production_workflows: Dict):
        """
        Connection [node_id, index] must have index < node's output count.
        Using index 2 on a node with 1 output causes runtime error.
        """
        for filename, workflow in production_workflows.items():
            node_types = {
                node_id: node.get("class_type", "Unknown")
                for node_id, node in workflow.items()
                if isinstance(node, dict)
            }
            
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                inputs = node.get("inputs", {})
                if not isinstance(inputs, dict):
                    continue
                    
                for input_name, value in inputs.items():
                    if isinstance(value, list) and len(value) == 2:
                        source_node, output_index = value[0], value[1]
                        source_type = node_types.get(source_node, "Unknown")
                        max_outputs = get_node_output_count(source_type)
                        
                        assert output_index < max_outputs, (
                            f"{filename}.{node_id}.{input_name}: references "
                            f"{source_node}[{output_index}] but {source_type} "
                            f"only has {max_outputs} output(s)"
                        )


# =============================================================================
# SECTION 3: ORPHAN NODE DETECTION
# =============================================================================

class TestOrphanNodes:
    """Detect nodes that don't contribute to output (waste VRAM)."""
    
    def test_no_orphan_nodes(self, production_workflows: Dict):
        """All nodes should contribute to the final output."""
        for filename, workflow in production_workflows.items():
            orphans = find_orphan_nodes(workflow)
            
            assert len(orphans) == 0, (
                f"{filename}: orphan nodes found (don't contribute to output): {orphans}"
            )
    
    def test_no_circular_dependencies(self, production_workflows: Dict):
        """Workflows must be DAGs (no cycles)."""
        for filename, workflow in production_workflows.items():
            cycles = detect_circular_deps(workflow)
            
            assert len(cycles) == 0, (
                f"{filename}: circular dependencies found: {cycles}"
            )


# =============================================================================
# SECTION 4: VALUE RANGE VALIDATION
# =============================================================================

class TestValueRanges:
    """Test that hardcoded values are within sensible ranges."""
    
    def test_cfg_scale_reasonable(self, production_workflows: Dict):
        """CFG scale should be between 1 and 20 (typical range)."""
        for filename, workflow in production_workflows.items():
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "KSampler":
                    continue
                    
                cfg = node.get("inputs", {}).get("cfg")
                
                # Skip placeholders
                if isinstance(cfg, str) and "{{" in cfg:
                    continue
                    
                if isinstance(cfg, (int, float)):
                    assert 1 <= cfg <= 30, (
                        f"{filename}.{node_id}: CFG {cfg} outside reasonable range [1, 30]"
                    )
    
    def test_denoise_between_0_and_1(self, production_workflows: Dict):
        """Denoise must be between 0 and 1."""
        for filename, workflow in production_workflows.items():
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "KSampler":
                    continue
                    
                denoise = node.get("inputs", {}).get("denoise")
                
                if isinstance(denoise, str) and "{{" in denoise:
                    continue
                    
                if isinstance(denoise, (int, float)):
                    assert 0 <= denoise <= 1, (
                        f"{filename}.{node_id}: denoise {denoise} must be in [0, 1]"
                    )
    
    def test_steps_reasonable(self, production_workflows: Dict):
        """Steps should be between 1 and 150."""
        for filename, workflow in production_workflows.items():
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "KSampler":
                    continue
                    
                steps = node.get("inputs", {}).get("steps")
                
                if isinstance(steps, str) and "{{" in steps:
                    continue
                    
                if isinstance(steps, int):
                    assert 1 <= steps <= 150, (
                        f"{filename}.{node_id}: steps {steps} outside reasonable range [1, 150]"
                    )
    
    def test_controlnet_strength_reasonable(self, production_workflows: Dict):
        """ControlNet strength should be between 0 and 2."""
        for filename, workflow in production_workflows.items():
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if "ControlNet" not in node.get("class_type", ""):
                    continue
                    
                strength = node.get("inputs", {}).get("strength")
                
                if isinstance(strength, str) and "{{" in strength:
                    continue
                    
                if isinstance(strength, (int, float)):
                    assert 0 <= strength <= 2, (
                        f"{filename}.{node_id}: ControlNet strength {strength} "
                        f"outside reasonable range [0, 2]"
                    )
    
    def test_ipadapter_weight_reasonable(self, production_workflows: Dict):
        """IP-Adapter weight should be between 0 and 2."""
        for filename, workflow in production_workflows.items():
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if "IPAdapter" not in node.get("class_type", ""):
                    continue
                    
                weight = node.get("inputs", {}).get("weight")
                
                if isinstance(weight, str) and "{{" in weight:
                    continue
                    
                if isinstance(weight, (int, float)):
                    assert 0 <= weight <= 2, (
                        f"{filename}.{node_id}: IP-Adapter weight {weight} "
                        f"outside reasonable range [0, 2]"
                    )


# =============================================================================
# SECTION 5: MODEL COMPATIBILITY
# =============================================================================

class TestModelCompatibility:
    """Test that models are compatible with each other."""
    
    SDXL_INDICATORS = {"sdxl", "sd_xl", "xl"}
    SD15_INDICATORS = {"sd1", "sd_1", "1.5", "sd15"}
    
    def _is_sdxl_model(self, name: str) -> bool:
        """Check if model name indicates SDXL."""
        name_lower = name.lower()
        return any(ind in name_lower for ind in self.SDXL_INDICATORS)
    
    def _is_sd15_model(self, name: str) -> bool:
        """Check if model name indicates SD 1.5."""
        name_lower = name.lower()
        return any(ind in name_lower for ind in self.SD15_INDICATORS)
    
    def test_controlnet_matches_checkpoint_type(self, production_workflows: Dict):
        """ControlNet model must match checkpoint type (SDXL with SDXL)."""
        for filename, workflow in production_workflows.items():
            # Find checkpoint type
            checkpoint_type = None
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") == "CheckpointLoaderSimple":
                    ckpt_name = node.get("inputs", {}).get("ckpt_name", "")
                    if self._is_sdxl_model(ckpt_name):
                        checkpoint_type = "sdxl"
                    elif self._is_sd15_model(ckpt_name):
                        checkpoint_type = "sd15"
            
            if not checkpoint_type:
                continue  # Can't determine, skip
            
            # Check ControlNet compatibility
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "ControlNetLoader":
                    continue
                    
                cn_name = node.get("inputs", {}).get("control_net_name", "")
                
                if checkpoint_type == "sdxl":
                    assert self._is_sdxl_model(cn_name), (
                        f"{filename}.{node_id}: using SDXL checkpoint but "
                        f"ControlNet '{cn_name}' doesn't appear to be SDXL"
                    )
    
    def test_ipadapter_matches_checkpoint_type(self, production_workflows: Dict):
        """IP-Adapter model must match checkpoint type."""
        for filename, workflow in production_workflows.items():
            # Find checkpoint type
            checkpoint_type = None
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") == "CheckpointLoaderSimple":
                    ckpt_name = node.get("inputs", {}).get("ckpt_name", "")
                    if self._is_sdxl_model(ckpt_name):
                        checkpoint_type = "sdxl"
            
            if not checkpoint_type:
                continue
            
            # Check IP-Adapter compatibility
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "IPAdapterModelLoader":
                    continue
                    
                ipa_name = node.get("inputs", {}).get("ipadapter_file", "")
                
                if checkpoint_type == "sdxl":
                    assert self._is_sdxl_model(ipa_name), (
                        f"{filename}.{node_id}: using SDXL checkpoint but "
                        f"IP-Adapter '{ipa_name}' doesn't appear to be SDXL"
                    )


# =============================================================================
# SECTION 6: BRIDGE-SPECIFIC STRESS
# =============================================================================

class TestBridgeSpecificStress:
    """Stress tests specific to bridge workflows."""
    
    def test_bridge_denoise_less_than_1(self, production_workflows: Dict):
        """
        Bridge workflows use img2img - denoise should be < 1.
        denoise=1 means ignore source completely (defeats purpose).
        """
        for filename, workflow in production_workflows.items():
            if not filename.startswith("bridge_"):
                continue
                
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "KSampler":
                    continue
                    
                denoise = node.get("inputs", {}).get("denoise")
                
                # Skip placeholders (will be set at runtime)
                if isinstance(denoise, str) and "{{" in denoise:
                    continue
                    
                if isinstance(denoise, (int, float)):
                    assert denoise < 1.0, (
                        f"{filename}.{node_id}: bridge workflow has denoise={denoise}, "
                        f"should be < 1 for img2img"
                    )
    
    def test_bridge_loads_source_image(self, production_workflows: Dict):
        """Bridge workflows must load a source image."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("bridge_"):
                continue
            
            has_source = any(
                isinstance(node, dict) and 
                node.get("class_type") == "LoadImage" and
                "SOURCE" in str(node.get("inputs", {}).get("image", "")).upper()
                for node in workflow.values()
            )
            
            assert has_source, (
                f"{filename}: bridge workflow doesn't load SOURCE_IMAGE"
            )
    
    def test_bridge_ipadapter_loads_face_ref(self, production_workflows: Dict):
        """IP-Adapter bridges must load face reference."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("bridge_"):
                continue
            if "ipadapter" not in filename and "pose" not in filename and "full" not in filename:
                continue  # Only check workflows that should have face ref
            
            has_face_ref = any(
                isinstance(node, dict) and 
                node.get("class_type") == "LoadImage" and
                "FACE" in str(node.get("inputs", {}).get("image", "")).upper()
                for node in workflow.values()
            )
            
            assert has_face_ref, (
                f"{filename}: IP-Adapter bridge doesn't load FACE_REF_IMAGE"
            )


# =============================================================================
# SECTION 7: VIDEO-SPECIFIC STRESS
# =============================================================================

class TestVideoSpecificStress:
    """Stress tests specific to video generation workflows."""
    
    def test_video_workflows_have_frame_count(self, production_workflows: Dict):
        """Video workflows must specify frame count."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("pass1_"):
                continue
            
            # Look for frame count in relevant nodes
            has_frames = False
            for node in workflow.values():
                if not isinstance(node, dict):
                    continue
                inputs = node.get("inputs", {})
                
                # Check various ways frames might be specified
                if "length" in inputs or "frames" in inputs:
                    has_frames = True
                    break
            
            assert has_frames, (
                f"{filename}: video workflow doesn't specify frame count"
            )
    
    def test_video_workflows_have_fps(self, production_workflows: Dict):
        """Video workflows must specify FPS."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("pass1_"):
                continue
            
            has_fps = any(
                isinstance(node, dict) and 
                "fps" in node.get("inputs", {})
                for node in workflow.values()
            )
            
            assert has_fps, (
                f"{filename}: video workflow doesn't specify FPS"
            )
    
    def test_video_outputs_video_not_image(self, production_workflows: Dict):
        """Video workflows should output video, not image."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("pass1_"):
                continue
            
            class_types = {
                node.get("class_type") 
                for node in workflow.values() 
                if isinstance(node, dict)
            }
            
            has_video_output = "SaveVideo" in class_types or "VHS_VideoCombine" in class_types
            has_image_only = "SaveImage" in class_types and not has_video_output
            
            assert not has_image_only, (
                f"{filename}: video workflow outputs image instead of video"
            )


# =============================================================================
# SECTION 7B: REFINEMENT-SPECIFIC STRESS
# =============================================================================

class TestRefinementSpecificStress:
    """Stress tests specific to Pass 2 refinement workflows."""
    
    def test_refinement_denoise_should_be_low(self, production_workflows: Dict):
        """
        Refinement workflows should use low denoise (< 0.7).
        High denoise destroys Pass 1 structure.
        """
        for filename, workflow in production_workflows.items():
            if not filename.startswith("refine_"):
                continue
            
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node.get("class_type") != "KSampler":
                    continue
                
                denoise = node.get("inputs", {}).get("denoise")
                
                # Skip placeholders (will be set at runtime)
                if isinstance(denoise, str) and "{{" in denoise:
                    continue
                
                if isinstance(denoise, (int, float)):
                    assert denoise < 0.7, (
                        f"{filename}.{node_id}: refinement denoise={denoise} is too high. "
                        f"Should be < 0.7 to preserve Pass 1 structure"
                    )
    
    def test_refinement_loads_video_not_image(self, production_workflows: Dict):
        """Refinement must load video input, not static image."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("refine_"):
                continue
            
            class_types = set(
                node.get("class_type") 
                for node in workflow.values() 
                if isinstance(node, dict)
            )
            
            # Must have video loading capability
            has_video_loader = "VHS_LoadVideo" in class_types or "LoadVideo" in class_types
            
            assert has_video_loader, (
                f"{filename}: refinement must load video (VHS_LoadVideo), not images"
            )
    
    def test_refinement_outputs_video(self, production_workflows: Dict):
        """Refinement must output video, not images."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("refine_"):
                continue
            
            class_types = set(
                node.get("class_type") 
                for node in workflow.values() 
                if isinstance(node, dict)
            )
            
            has_video_output = "SaveVideo" in class_types or "VHS_VideoCombine" in class_types
            
            assert has_video_output, (
                f"{filename}: refinement must output video, not images"
            )
    
    def test_refinement_has_encode_sample_decode_chain(self, production_workflows: Dict):
        """Refinement must have VAEEncode -> Sampler -> VAEDecode chain."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("refine_"):
                continue
            
            class_types = set(
                node.get("class_type") 
                for node in workflow.values() 
                if isinstance(node, dict)
            )
            
            assert "VAEEncode" in class_types, f"{filename}: missing VAEEncode"
            
            # Accept KSampler or KSamplerBatch (temporal variant uses batch)
            has_sampler = "KSampler" in class_types or "KSamplerBatch" in class_types
            assert has_sampler, f"{filename}: missing KSampler or KSamplerBatch"
            
            assert "VAEDecode" in class_types, f"{filename}: missing VAEDecode"
    
    def test_refinement_sampler_receives_encoded_video(self, production_workflows: Dict):
        """Sampler must receive latent from VAEEncode (vid2vid pattern)."""
        for filename, workflow in production_workflows.items():
            if not filename.startswith("refine_"):
                continue
            
            # Find sampler node (could be "sampler" or "batch_sampler")
            sampler = workflow.get("sampler") or workflow.get("batch_sampler", {})
            if not sampler:
                continue
            
            latent_input = sampler.get("inputs", {}).get("latent_image", [])
            
            if isinstance(latent_input, list) and len(latent_input) >= 1:
                source_node = latent_input[0]
                # Should come from vae_encode, not empty latent
                assert source_node == "vae_encode", (
                    f"{filename}: sampler.latent_image should come from vae_encode "
                    f"(vid2vid pattern), got {source_node}"
                )
    
    def test_temporal_refinement_has_temporal_window(self, production_workflows: Dict):
        """Temporal refinement workflows must use TEMPORAL_WINDOW placeholder."""
        for filename, workflow in production_workflows.items():
            if "temporal" not in filename.lower():
                continue
            if not filename.startswith("refine_"):
                continue
            
            # Extract placeholders
            placeholders = set()
            def find_placeholders(obj):
                if isinstance(obj, str):
                    import re
                    for m in re.finditer(r'\{\{(\w+)\}\}', obj):
                        placeholders.add(m.group(1))
                elif isinstance(obj, dict):
                    for v in obj.values():
                        find_placeholders(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_placeholders(item)
            
            find_placeholders(workflow)
            
            assert "TEMPORAL_WINDOW" in placeholders, (
                f"{filename}: temporal refinement must have TEMPORAL_WINDOW placeholder"
            )
    
    def test_temporal_refinement_has_batch_processing(self, production_workflows: Dict):
        """Temporal refinement should use batch-aware nodes."""
        for filename, workflow in production_workflows.items():
            if "temporal" not in filename.lower():
                continue
            if not filename.startswith("refine_"):
                continue
            
            class_types = set(
                node.get("class_type")
                for node in workflow.values()
                if isinstance(node, dict)
            )
            
            # Should have batch sampler OR temporal coherence node
            has_batch = any("Batch" in ct for ct in class_types)
            has_temporal = any("Temporal" in ct for ct in class_types if ct != "VHS_LoadVideo")
            
            assert has_batch or has_temporal, (
                f"{filename}: temporal refinement should have batch processing or "
                f"temporal nodes, got: {class_types}"
            )
    
    def test_simple_refinement_no_temporal_window(self, production_workflows: Dict):
        """Simple refinement should NOT have TEMPORAL_WINDOW (it's frame-by-frame)."""
        for filename, workflow in production_workflows.items():
            if "simple" not in filename.lower():
                continue
            if not filename.startswith("refine_"):
                continue
            
            # Extract placeholders
            placeholders = set()
            def find_placeholders(obj):
                if isinstance(obj, str):
                    import re
                    for m in re.finditer(r'\{\{(\w+)\}\}', obj):
                        placeholders.add(m.group(1))
                elif isinstance(obj, dict):
                    for v in obj.values():
                        find_placeholders(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_placeholders(item)
            
            find_placeholders(workflow)
            
            assert "TEMPORAL_WINDOW" not in placeholders, (
                f"{filename}: simple refinement should not have TEMPORAL_WINDOW"
            )


# =============================================================================
# SECTION 7C: LIP SYNC-SPECIFIC STRESS
# =============================================================================

class TestLipSyncSpecificStress:
    """Stress tests specific to lip sync workflows."""
    
    def test_lipsync_loads_both_video_and_audio(self, production_workflows: Dict):
        """Lip sync must load both video AND audio inputs."""
        for filename, workflow in production_workflows.items():
            if "lipsync" not in filename.lower():
                continue
            
            class_types = set(
                node.get("class_type")
                for node in workflow.values()
                if isinstance(node, dict)
            )
            
            # Must have video loading
            has_video = "VHS_LoadVideo" in class_types or "LoadVideo" in class_types
            assert has_video, f"{filename}: lip sync must load video"
            
            # Must have audio loading
            has_audio = "LoadAudio" in class_types
            assert has_audio, f"{filename}: lip sync must load audio"
    
    def test_lipsync_outputs_video_not_image(self, production_workflows: Dict):
        """Lip sync must output video (not just processed face images)."""
        for filename, workflow in production_workflows.items():
            if "lipsync" not in filename.lower():
                continue
            
            class_types = set(
                node.get("class_type")
                for node in workflow.values()
                if isinstance(node, dict)
            )
            
            has_video_output = "SaveVideo" in class_types or "VHS_VideoCombine" in class_types
            assert has_video_output, f"{filename}: lip sync must output video"
    
    def test_lipsync_has_face_processing_pipeline(self, production_workflows: Dict):
        """Lip sync must have detect -> process -> composite pipeline."""
        for filename, workflow in production_workflows.items():
            if "lipsync" not in filename.lower():
                continue
            
            class_types = set(
                node.get("class_type")
                for node in workflow.values()
                if isinstance(node, dict)
            )
            
            # Should have face detection
            has_face_detect = any("FaceDetect" in ct or "Face" in ct for ct in class_types)
            assert has_face_detect, f"{filename}: missing face detection"
            
            # Should have composite/blend step
            has_composite = any("Composite" in ct or "Blend" in ct for ct in class_types)
            assert has_composite, f"{filename}: missing composite/blend step"
    
    def test_lipsync_face_threshold_reasonable(self, production_workflows: Dict):
        """Face detection threshold should be between 0.1 and 0.9."""
        for filename, workflow in production_workflows.items():
            if "lipsync" not in filename.lower():
                continue
            
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                
                inputs = node.get("inputs", {})
                threshold = inputs.get("threshold")
                
                # Skip placeholders
                if isinstance(threshold, str) and "{{" in threshold:
                    continue
                
                if isinstance(threshold, (int, float)):
                    assert 0.1 <= threshold <= 0.9, (
                        f"{filename}.{node_id}: face threshold {threshold} "
                        f"outside reasonable range [0.1, 0.9]"
                    )
    
    def test_lipsync_time_params_not_hardcoded(self, production_workflows: Dict):
        """START_TIME and END_TIME should be placeholders, not hardcoded."""
        for filename, workflow in production_workflows.items():
            if "lipsync" not in filename.lower():
                continue
            
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                
                inputs = node.get("inputs", {})
                
                for time_param in ["start_time", "end_time"]:
                    if time_param in inputs:
                        value = inputs[time_param]
                        # Should be placeholder, not hardcoded number
                        is_placeholder = isinstance(value, str) and "{{" in value
                        is_connection = isinstance(value, list)
                        
                        assert is_placeholder or is_connection, (
                            f"{filename}.{node_id}.{time_param}: should be placeholder "
                            f"or connection, got hardcoded: {value}"
                        )


# =============================================================================
# SECTION 8: PLACEHOLDER INJECTION SIMULATION
# =============================================================================

class TestPlaceholderInjectionSimulation:
    """Simulate placeholder injection to catch issues early."""
    
    # Typical values that would be injected
    MOCK_VALUES = {
        # Pass 1 video generation
        "POSITIVE_PROMPT": "A woman walking through a kitchen, cinematic lighting",
        "NEGATIVE_PROMPT": "blurry, low quality",
        "PROMPT": "Character facing camera, medium shot",
        "SEED": 42,
        "WIDTH": 1280,
        "HEIGHT": 720,
        "STEPS": 20,
        "CFG": 7.0,
        "CFG_SCALE": 7.0,
        "DENOISE": 0.65,
        "FPS": 12,
        "FRAMES": 48,
        
        # Model paths (injected from models.json based on tier)
        "UNET_MODEL": "wan2.1_t2v_14B_bf16.safetensors",
        "VAE_MODEL": "wan_2.1_vae.safetensors",
        "CLIP_MODEL": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "CLIP_VISION_MODEL": "clip_vision_h.safetensors",
        
        # I2V and Bridge
        "SOURCE_IMAGE": "source_frame.png",
        "INIT_IMAGE": "init_frame.png",
        "FACE_REF_IMAGE": "face_ref.png",
        "POSE_IMAGE": "pose.png",
        "DEPTH_IMAGE": "depth.png",
        
        # LoRA
        "LORA_PATH": "character_v1.safetensors",
        "LORA_STRENGTH": 0.8,
        
        # IP-Adapter and ControlNet
        "IPADAPTER_STRENGTH": 0.7,
        "CONTROLNET_POSE_STRENGTH": 0.8,
        "CONTROLNET_DEPTH_STRENGTH": 0.5,
        
        # Pass 2 Refinement
        "INPUT_VIDEO": "pass1_output.mp4",
        "DENOISE_STRENGTH": 0.5,
        "TEMPORAL_WINDOW": 16,
        
        # Lip Sync
        "VIDEO_PATH": "refined_video.mp4",
        "AUDIO_PATH": "dialogue.wav",
        "START_TIME": 0.0,
        "END_TIME": 5.0,
        "FACE_THRESHOLD": 0.5,
    }
    
    def _inject_placeholders(self, workflow: Dict) -> Dict:
        """Simulate placeholder injection."""
        import copy
        result = copy.deepcopy(workflow)
        
        def replace(obj):
            if isinstance(obj, str):
                for name, value in self.MOCK_VALUES.items():
                    placeholder = f"{{{{{name}}}}}"
                    if obj == placeholder:
                        return value
                    obj = obj.replace(placeholder, str(value))
                return obj
            elif isinstance(obj, dict):
                return {k: replace(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace(item) for item in obj]
            return obj
        
        return replace(result)
    
    def test_all_placeholders_have_mock_values(self, production_workflows: Dict):
        """All placeholders in workflows should have corresponding mock values."""
        all_placeholders = set()
        for filename, workflow in production_workflows.items():
            for ph, _, _, _ in extract_all_placeholders_with_context(workflow):
                all_placeholders.add(ph)
        
        missing = all_placeholders - set(self.MOCK_VALUES.keys())
        assert len(missing) == 0, (
            f"Placeholders without mock values (add to MOCK_VALUES): {missing}"
        )
    
    def test_injected_workflow_has_no_placeholders(self, production_workflows: Dict):
        """After injection, no placeholders should remain."""
        for filename, workflow in production_workflows.items():
            injected = self._inject_placeholders(workflow)
            
            remaining = []
            for ph, node_id, input_name, _ in extract_all_placeholders_with_context(injected):
                remaining.append(f"{node_id}.{input_name}={ph}")
            
            assert len(remaining) == 0, (
                f"{filename}: placeholders remain after injection: {remaining}"
            )
    
    def test_injected_integers_are_integers(self, production_workflows: Dict):
        """After injection, integer inputs should be int type."""
        integer_inputs = {"seed", "steps", "width", "height", "length", "batch_size"}
        
        for filename, workflow in production_workflows.items():
            injected = self._inject_placeholders(workflow)
            
            for node_id, node in injected.items():
                if not isinstance(node, dict):
                    continue
                inputs = node.get("inputs", {})
                if not isinstance(inputs, dict):
                    continue
                    
                for input_name, value in inputs.items():
                    if input_name.lower() in integer_inputs:
                        # Skip connections
                        if isinstance(value, list):
                            continue
                        assert isinstance(value, int), (
                            f"{filename}.{node_id}.{input_name}: should be int "
                            f"after injection, got {type(value).__name__}: {value}"
                        )


# =============================================================================
# SECTION 9: DUPLICATE DETECTION
# =============================================================================

class TestDuplicateDetection:
    """Detect accidental duplications that indicate copy-paste errors."""
    
    def test_no_duplicate_node_ids_across_workflows(self, production_workflows: Dict):
        """
        This is actually fine - just checking the test runs.
        Node IDs should be unique WITHIN a workflow (JSON enforces this).
        """
        pass  # JSON parsing handles this automatically
    
    def test_no_identical_loaders_in_same_workflow(self, production_workflows: Dict):
        """
        Having two identical loaders wastes VRAM.
        E.g., two LoadImage nodes loading the same placeholder.
        """
        for filename, workflow in production_workflows.items():
            loader_signatures = []
            
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                class_type = node.get("class_type", "")
                
                # Check loaders that take a single file input
                if class_type in {"LoadImage", "CheckpointLoaderSimple", 
                                 "VAELoader", "CLIPLoader", "UNETLoader"}:
                    inputs = node.get("inputs", {})
                    # Create signature from class + key inputs
                    sig = (class_type, json.dumps(inputs, sort_keys=True))
                    
                    if sig in loader_signatures:
                        # Find the duplicate
                        for other_id, other_node in workflow.items():
                            if other_id == node_id:
                                continue
                            if not isinstance(other_node, dict):
                                continue
                            other_sig = (
                                other_node.get("class_type", ""),
                                json.dumps(other_node.get("inputs", {}), sort_keys=True)
                            )
                            if other_sig == sig:
                                pytest.fail(
                                    f"{filename}: duplicate loaders {node_id} and {other_id} "
                                    f"load identical content (wastes VRAM)"
                                )
                    
                    loader_signatures.append(sig)


# =============================================================================
# SECTION 10: EXECUTION ORDER STRESS
# =============================================================================

class TestExecutionOrderStress:
    """Test that execution order will be correct."""
    
    def test_topological_sort_possible(self, production_workflows: Dict):
        """
        ComfyUI executes nodes in topological order.
        This should always be possible (no cycles).
        """
        for filename, workflow in production_workflows.items():
            deps = build_dependency_graph(workflow)
            
            # Kahn's algorithm for topological sort
            in_degree = {node: 0 for node in workflow.keys()}
            for node, sources in deps.items():
                for source in sources:
                    if source in in_degree:
                        in_degree[node] = in_degree.get(node, 0)
            
            # Count dependencies
            for node, sources in deps.items():
                in_degree[node] = len(sources)
            
            # Find nodes with no dependencies
            queue = deque([node for node, degree in in_degree.items() if degree == 0])
            sorted_count = 0
            
            while queue:
                node = queue.popleft()
                sorted_count += 1
                
                # Reduce in-degree for dependent nodes
                for dependent, sources in deps.items():
                    if node in sources:
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0:
                            queue.append(dependent)
            
            assert sorted_count == len(workflow), (
                f"{filename}: cannot topologically sort - likely has cycles"
            )