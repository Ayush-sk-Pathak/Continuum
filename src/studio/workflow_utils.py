"""
Continuum Engine - ComfyUI Workflow Utilities

Utilities for loading and manipulating ComfyUI workflow JSONs.
These work directly with exported workflow files from ComfyUI.

Node Modification Map (from analyzed workflows):

T2V (t2v_wan21.json):
  - Node 6:  Positive Prompt    → widgets_values[0]
  - Node 7:  Negative Prompt    → widgets_values[0]
  - Node 3:  KSampler          → widgets_values[0]=seed, [2]=steps, [3]=cfg
  - Node 40: EmptyHunyuanLatent → widgets_values[0]=width, [1]=height, [2]=length

I2V (i2v_wan21.json):
  - Node 6:  Positive Prompt    → widgets_values[0]
  - Node 7:  Negative Prompt    → widgets_values[0]
  - Node 52: LoadImage         → widgets_values[0]=image_filename
  - Node 3:  KSampler          → widgets_values[0]=seed, [2]=steps, [3]=cfg
  - Node 50: WanImageToVideo   → widgets_values[0]=width, [1]=height, [2]=length
"""

import json
import copy
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# NODE IDS (from your exported workflows)
# =============================================================================

class T2VNodes:
    """Node IDs for Text-to-Video workflow (t2v_wan21.json)"""
    POSITIVE_PROMPT = "6"
    NEGATIVE_PROMPT = "7"
    KSAMPLER = "3"
    VIDEO_SIZE = "40"  # EmptyHunyuanLatentVideo
    MODEL_LOADER = "37"
    CLIP_LOADER = "38"
    VAE_LOADER = "39"
    SAVE_VIDEO = "50"


class I2VNodes:
    """Node IDs for Image-to-Video workflow (i2v_wan21.json)"""
    POSITIVE_PROMPT = "6"
    NEGATIVE_PROMPT = "7"
    KSAMPLER = "3"
    LOAD_IMAGE = "52"
    WAN_I2V = "50"  # WanImageToVideo
    MODEL_LOADER = "37"
    CLIP_LOADER = "38"
    VAE_LOADER = "39"
    CLIP_VISION_LOADER = "49"
    SAVE_VIDEO = "56"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class T2VParams:
    """Parameters for Text-to-Video generation"""
    positive_prompt: str
    negative_prompt: Optional[str] = None
    seed: int = -1  # -1 = random
    steps: int = 30
    cfg: float = 6.0
    width: int = 832
    height: int = 480
    frames: int = 33  # ~2 seconds at 16fps
    
    # Default negative prompt (translated from Chinese)
    DEFAULT_NEGATIVE = (
        "ugly, blurry, low quality, worst quality, jpeg artifacts, "
        "deformed, mutated, extra limbs, bad hands, bad face, "
        "static, frozen, chaotic background, three legs, too many people"
    )
    
    def __post_init__(self):
        if self.negative_prompt is None:
            self.negative_prompt = self.DEFAULT_NEGATIVE


@dataclass
class I2VParams:
    """Parameters for Image-to-Video generation"""
    positive_prompt: str
    input_image: str  # Filename in ComfyUI input folder
    negative_prompt: Optional[str] = None
    seed: int = -1
    steps: int = 20  # I2V typically needs fewer steps
    cfg: float = 6.0
    width: int = 512
    height: int = 512
    frames: int = 33
    
    DEFAULT_NEGATIVE = (
        "ugly, blurry, low quality, worst quality, jpeg artifacts, "
        "deformed, mutated, extra limbs, bad hands, bad face, "
        "static, frozen, chaotic background, three legs, too many people"
    )
    
    def __post_init__(self):
        if self.negative_prompt is None:
            self.negative_prompt = self.DEFAULT_NEGATIVE


# =============================================================================
# WORKFLOW LOADER
# =============================================================================

class WanWorkflowLoader:
    """
    Loads and modifies Wan 2.1 ComfyUI workflows.
    
    Usage:
        loader = WanWorkflowLoader("./workflows")
        
        # For Text-to-Video
        params = T2VParams(
            positive_prompt="A woman walking in a garden",
            seed=42
        )
        workflow = loader.build_t2v_workflow(params)
        
        # For Image-to-Video  
        params = I2VParams(
            positive_prompt="The woman starts walking",
            input_image="last_frame.png"
        )
        workflow = loader.build_i2v_workflow(params)
    """
    
    def __init__(self, workflows_dir: Union[str, Path]):
        """
        Initialize workflow loader.
        
        Args:
            workflows_dir: Directory containing t2v_wan21.json and i2v_wan21.json
        """
        self.workflows_dir = Path(workflows_dir)
        self._t2v_template: Optional[Dict] = None
        self._i2v_template: Optional[Dict] = None
    
    def _load_template(self, filename: str) -> Dict[str, Any]:
        """Load a workflow template JSON"""
        path = self.workflows_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Workflow template not found: {path}")
        
        with open(path, 'r') as f:
            return json.load(f)
    
    @property
    def t2v_template(self) -> Dict[str, Any]:
        """Lazy-load T2V template"""
        if self._t2v_template is None:
            self._t2v_template = self._load_template("t2v_wan21.json")
            logger.info("Loaded T2V workflow template")
        return self._t2v_template
    
    @property
    def i2v_template(self) -> Dict[str, Any]:
        """Lazy-load I2V template"""
        if self._i2v_template is None:
            self._i2v_template = self._load_template("i2v_wan21.json")
            logger.info("Loaded I2V workflow template")
        return self._i2v_template
    
    def _find_node(self, workflow: Dict, node_id: str) -> Optional[Dict]:
        """Find a node by ID in the workflow"""
        nodes = workflow.get("nodes", [])
        for node in nodes:
            if str(node.get("id")) == str(node_id):
                return node
        return None
    
    def _modify_node_widget(
        self, 
        workflow: Dict, 
        node_id: str, 
        widget_index: int, 
        value: Any
    ) -> None:
        """Modify a widget value in a node"""
        node = self._find_node(workflow, node_id)
        if node is None:
            logger.warning(f"Node {node_id} not found in workflow")
            return
        
        widgets = node.get("widgets_values", [])
        if widget_index < len(widgets):
            widgets[widget_index] = value
            logger.debug(f"Set node {node_id} widget[{widget_index}] = {value}")
        else:
            logger.warning(
                f"Widget index {widget_index} out of range for node {node_id} "
                f"(has {len(widgets)} widgets)"
            )
    
    def build_t2v_workflow(self, params: T2VParams) -> Dict[str, Any]:
        """
        Build a Text-to-Video workflow with the given parameters.
        
        Args:
            params: T2VParams with generation settings
            
        Returns:
            Modified workflow dict ready for ComfyUI API
        """
        # Deep copy template
        workflow = copy.deepcopy(self.t2v_template)
        
        # Modify positive prompt (Node 6, widget 0)
        self._modify_node_widget(
            workflow, T2VNodes.POSITIVE_PROMPT, 0, params.positive_prompt
        )
        
        # Modify negative prompt (Node 7, widget 0)
        self._modify_node_widget(
            workflow, T2VNodes.NEGATIVE_PROMPT, 0, params.negative_prompt
        )
        
        # Modify KSampler (Node 3)
        # widgets_values: [seed, "randomize", steps, cfg, sampler, scheduler, denoise]
        if params.seed != -1:
            self._modify_node_widget(workflow, T2VNodes.KSAMPLER, 0, params.seed)
            self._modify_node_widget(workflow, T2VNodes.KSAMPLER, 1, "fixed")
        self._modify_node_widget(workflow, T2VNodes.KSAMPLER, 2, params.steps)
        self._modify_node_widget(workflow, T2VNodes.KSAMPLER, 3, params.cfg)
        
        # Modify video size (Node 40)
        # widgets_values: [width, height, length, batch_size]
        self._modify_node_widget(workflow, T2VNodes.VIDEO_SIZE, 0, params.width)
        self._modify_node_widget(workflow, T2VNodes.VIDEO_SIZE, 1, params.height)
        self._modify_node_widget(workflow, T2VNodes.VIDEO_SIZE, 2, params.frames)
        
        logger.info(
            f"Built T2V workflow: prompt='{params.positive_prompt[:50]}...', "
            f"size={params.width}x{params.height}, frames={params.frames}"
        )
        
        return workflow
    
    def build_i2v_workflow(self, params: I2VParams) -> Dict[str, Any]:
        """
        Build an Image-to-Video workflow with the given parameters.
        
        Args:
            params: I2VParams with generation settings
            
        Returns:
            Modified workflow dict ready for ComfyUI API
        """
        # Deep copy template
        workflow = copy.deepcopy(self.i2v_template)
        
        # Modify positive prompt (Node 6, widget 0)
        self._modify_node_widget(
            workflow, I2VNodes.POSITIVE_PROMPT, 0, params.positive_prompt
        )
        
        # Modify negative prompt (Node 7, widget 0)
        self._modify_node_widget(
            workflow, I2VNodes.NEGATIVE_PROMPT, 0, params.negative_prompt
        )
        
        # Modify input image (Node 52, widget 0)
        self._modify_node_widget(
            workflow, I2VNodes.LOAD_IMAGE, 0, params.input_image
        )
        
        # Modify KSampler (Node 3)
        if params.seed != -1:
            self._modify_node_widget(workflow, I2VNodes.KSAMPLER, 0, params.seed)
            self._modify_node_widget(workflow, I2VNodes.KSAMPLER, 1, "fixed")
        self._modify_node_widget(workflow, I2VNodes.KSAMPLER, 2, params.steps)
        self._modify_node_widget(workflow, I2VNodes.KSAMPLER, 3, params.cfg)
        
        # Modify WanImageToVideo (Node 50)
        # widgets_values: [width, height, length, batch_size]
        self._modify_node_widget(workflow, I2VNodes.WAN_I2V, 0, params.width)
        self._modify_node_widget(workflow, I2VNodes.WAN_I2V, 1, params.height)
        self._modify_node_widget(workflow, I2VNodes.WAN_I2V, 2, params.frames)
        
        logger.info(
            f"Built I2V workflow: image='{params.input_image}', "
            f"prompt='{params.positive_prompt[:50]}...', frames={params.frames}"
        )
        
        return workflow
    
    def workflow_to_api_format(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert workflow to ComfyUI API prompt format.
        
        The ComfyUI API expects a different format than the saved workflow.
        This converts from the UI format to the API format.
        
        Args:
            workflow: Workflow in UI format (with nodes list)
            
        Returns:
            Workflow in API format (with node_id: node_data dict)
        """
        api_workflow = {}
        
        for node in workflow.get("nodes", []):
            node_id = str(node["id"])
            
            # Build the API node format
            api_node = {
                "class_type": node["type"],
                "inputs": {}
            }
            
            # Get widget values
            widgets_values = node.get("widgets_values", [])
            
            # Get input definitions from the node
            inputs = node.get("inputs", [])
            
            # Map widget values to input names
            widget_idx = 0
            for inp in inputs:
                input_name = inp.get("name")
                
                # Check if this input has a link (connected to another node)
                link = inp.get("link")
                if link is not None:
                    # Find the source node and output
                    source = self._find_link_source(workflow, link)
                    if source:
                        api_node["inputs"][input_name] = source
                
                # Check if this is a widget input (has widget property)
                elif inp.get("widget") and widget_idx < len(widgets_values):
                    api_node["inputs"][input_name] = widgets_values[widget_idx]
                    widget_idx += 1
            
            # Handle standalone widgets (not in inputs array)
            # These are typically at the end of widgets_values
            
            api_workflow[node_id] = api_node
        
        return api_workflow
    
    def _find_link_source(
        self, 
        workflow: Dict, 
        link_id: int
    ) -> Optional[list]:
        """
        Find the source of a link.
        
        Returns [node_id, output_slot] if found.
        """
        links = workflow.get("links", [])
        for link in links:
            # Link format: [link_id, source_node, source_slot, target_node, target_slot, type]
            if link[0] == link_id:
                return [str(link[1]), link[2]]
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_t2v_workflow(
    workflows_dir: Union[str, Path],
    prompt: str,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
    width: int = 832,
    height: int = 480,
    frames: int = 33,
    steps: int = 30,
    cfg: float = 6.0,
) -> Dict[str, Any]:
    """
    Create a Text-to-Video workflow ready for ComfyUI.
    
    Args:
        workflows_dir: Directory containing t2v_wan21.json
        prompt: What to generate
        negative_prompt: What to avoid (uses default if None)
        seed: Random seed (-1 for random)
        width: Video width
        height: Video height
        frames: Number of frames
        steps: Sampling steps
        cfg: CFG scale
        
    Returns:
        Workflow dict for ComfyUI API
    """
    loader = WanWorkflowLoader(workflows_dir)
    params = T2VParams(
        positive_prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        frames=frames,
        steps=steps,
        cfg=cfg,
    )
    return loader.build_t2v_workflow(params)


def create_i2v_workflow(
    workflows_dir: Union[str, Path],
    prompt: str,
    input_image: str,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
    width: int = 512,
    height: int = 512,
    frames: int = 33,
    steps: int = 20,
    cfg: float = 6.0,
) -> Dict[str, Any]:
    """
    Create an Image-to-Video workflow ready for ComfyUI.
    
    Args:
        workflows_dir: Directory containing i2v_wan21.json
        prompt: Motion/action description
        input_image: Filename of uploaded image in ComfyUI
        negative_prompt: What to avoid (uses default if None)
        seed: Random seed (-1 for random)
        width: Video width
        height: Video height
        frames: Number of frames
        steps: Sampling steps
        cfg: CFG scale
        
    Returns:
        Workflow dict for ComfyUI API
    """
    loader = WanWorkflowLoader(workflows_dir)
    params = I2VParams(
        positive_prompt=prompt,
        input_image=input_image,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        frames=frames,
        steps=steps,
        cfg=cfg,
    )
    return loader.build_i2v_workflow(params)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    # Quick test
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python workflow_utils.py <workflows_dir>")
        sys.exit(1)
    
    workflows_dir = Path(sys.argv[1])
    
    # Test T2V
    print("\n=== Testing T2V Workflow ===")
    try:
        workflow = create_t2v_workflow(
            workflows_dir,
            prompt="A woman walking through a beautiful garden, cinematic",
            seed=42,
        )
        print(f"✓ T2V workflow created with {len(workflow.get('nodes', []))} nodes")
    except Exception as e:
        print(f"✗ T2V failed: {e}")
    
    # Test I2V
    print("\n=== Testing I2V Workflow ===")
    try:
        workflow = create_i2v_workflow(
            workflows_dir,
            prompt="The woman starts walking forward",
            input_image="test_frame.png",
            seed=42,
        )
        print(f"✓ I2V workflow created with {len(workflow.get('nodes', []))} nodes")
    except Exception as e:
        print(f"✗ I2V failed: {e}")