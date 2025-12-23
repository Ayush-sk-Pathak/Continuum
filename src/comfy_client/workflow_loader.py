"""
Continuum Engine - ComfyUI Workflow Loader

Loads workflow JSON templates and injects runtime parameters (prompts, seeds,
LoRA paths, init images, etc.) before submission to ComfyUI.

Design Principles:
1. Template-based: Workflows are JSON files with placeholder patterns
2. Type-safe injection: Validate parameter types before injection
3. Fail-fast validation: Catch errors before expensive GPU submission
4. Immutable templates: Never modify the original, always return a copy
"""

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from ..core.config import get_config

logger = logging.getLogger(__name__)


# =============================================================================
# PLACEHOLDER PATTERNS
# =============================================================================

# Placeholders in workflow JSON use double-brace syntax: {{PLACEHOLDER_NAME}}
# This avoids conflicts with JSON syntax and is easy to find/replace
PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")

# Common placeholder names (for documentation and validation)
KNOWN_PLACEHOLDERS = {
    # Text inputs
    "POSITIVE_PROMPT",
    "NEGATIVE_PROMPT",
    "PROMPT",
    
    # Generation parameters
    "SEED",
    "CFG_SCALE",
    "CFG",  # Alternative name used in some workflows
    "STEPS",
    "DENOISE",
    "WIDTH",
    "HEIGHT",
    "FPS",
    "FRAMES",
    
    # Model paths (from model_loader.py)
    "UNET_MODEL",
    "VAE_MODEL",
    "CLIP_MODEL",
    "CLIP_VISION_MODEL",  # Required for I2V workflows
    
    # File paths
    "INIT_IMAGE",
    "INIT_VIDEO",
    "INPUT_VIDEO",  # For RIFE/refinement workflows
    "LORA_PATH",
    "LORA_STRENGTH",
    "CHECKPOINT_PATH",
    "CONTROLNET_IMAGE",
    "IP_ADAPTER_IMAGE",
    
    # Character/identity
    "CHARACTER_NAME",
    "CHARACTER_LORA",
    "FACE_REF_1",
    "FACE_REF_2",
    "FACE_REF_3",
    "FACE_REF_IMAGE",  # Bridge workflows
    "IPADAPTER_STRENGTH",  # Bridge IP-Adapter strength
    
    # Bridge frame specific
    "SOURCE_IMAGE",
    "POSE_IMAGE",
    "DEPTH_IMAGE",
    "CONTROLNET_POSE_STRENGTH",
    "CONTROLNET_DEPTH_STRENGTH",
    
    # Environment
    "ENVIRONMENT_REF",
    "LOCATION_NAME",
    
    # RIFE interpolation
    "MULTIPLIER",
    "TARGET_FPS",
    
    # Output
    "OUTPUT_PREFIX",
    "OUTPUT_FORMAT",
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class WorkflowTemplate:
    """
    A loaded workflow template ready for parameter injection.
    
    Attributes:
        name: Template name (usually filename without extension)
        source_path: Original file path (None if created from dict)
        workflow: The raw workflow dict (node_id -> node_config)
        placeholders: Set of placeholder names found in template
        metadata: Optional metadata from template file
    """
    name: str
    workflow: Dict[str, Any]
    placeholders: Set[str] = field(default_factory=set)
    source_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def requires(self, *placeholder_names: str) -> bool:
        """Check if template requires specific placeholders."""
        return all(name in self.placeholders for name in placeholder_names)
    
    def missing_params(self, params: Dict[str, Any]) -> Set[str]:
        """Get placeholders not provided in params."""
        return self.placeholders - set(params.keys())


@dataclass
class InjectionResult:
    """
    Result of parameter injection into a workflow.
    
    Attributes:
        workflow: The workflow dict with parameters injected
        injected: Parameters that were successfully injected
        unused: Parameters provided but not found in template
        missing: Placeholders in template with no value provided
        warnings: Non-fatal issues encountered
    """
    workflow: Dict[str, Any]
    injected: Set[str] = field(default_factory=set)
    unused: Set[str] = field(default_factory=set)
    missing: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        """Check if injection completed without missing required params."""
        return len(self.missing) == 0


@dataclass 
class ValidationResult:
    """
    Result of workflow validation.
    
    Attributes:
        valid: Whether workflow passed all checks
        errors: Fatal issues that prevent execution
        warnings: Non-fatal issues to be aware of
    """
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# WORKFLOW LOADER
# =============================================================================

class WorkflowLoader:
    """
    Loads and manages ComfyUI workflow templates.
    
    Usage:
        loader = WorkflowLoader()
        
        # Load a template
        template = loader.load("pass1_structural")
        
        # Inject parameters
        result = loader.inject(template, {
            "POSITIVE_PROMPT": "A woman walking through a kitchen",
            "SEED": 42,
            "LORA_PATH": "/models/alice.safetensors"
        })
        
        # Validate before submission
        validation = loader.validate(result.workflow)
        if validation.valid:
            job = await client.submit_workflow(result.workflow)
    """
    
    def __init__(self, workflows_dir: Optional[Path] = None):
        """
        Initialize the loader.
        
        Args:
            workflows_dir: Directory containing workflow JSON files.
                          Uses config default if not specified.
        """
        if workflows_dir is None:
            workflows_dir = get_config().paths.workflows_dir
        
        self.workflows_dir = Path(workflows_dir)
        
        # Cache loaded templates
        self._template_cache: Dict[str, WorkflowTemplate] = {}
    
    # -------------------------------------------------------------------------
    # LOADING
    # -------------------------------------------------------------------------
    
    def load(self, name: str, use_cache: bool = True) -> WorkflowTemplate:
        """
        Load a workflow template by name.
        
        Args:
            name: Template name (filename without .json extension)
            use_cache: Whether to use cached template if available
            
        Returns:
            WorkflowTemplate ready for injection
            
        Raises:
            FileNotFoundError: If template file doesn't exist
            json.JSONDecodeError: If file contains invalid JSON
        """
        # Check cache first
        if use_cache and name in self._template_cache:
            logger.debug(f"Using cached template: {name}")
            return self._template_cache[name]
        
        # Find the file
        filepath = self._find_workflow_file(name)
        if filepath is None:
            raise FileNotFoundError(
                f"Workflow template '{name}' not found in {self.workflows_dir}"
            )
        
        # Load and parse
        template = self._load_from_file(filepath)
        
        # Cache it
        if use_cache:
            self._template_cache[name] = template
        
        logger.info(f"Loaded workflow template: {name} ({len(template.placeholders)} placeholders)")
        return template
    
    def load_from_dict(self, workflow: Dict[str, Any], name: str = "inline") -> WorkflowTemplate:
        """
        Create a template from a workflow dict (not from file).
        
        Args:
            workflow: The workflow dict
            name: Name for this template
            
        Returns:
            WorkflowTemplate ready for injection
        """
        placeholders = self._extract_placeholders(workflow)
        
        return WorkflowTemplate(
            name=name,
            workflow=workflow,
            placeholders=placeholders,
            source_path=None
        )
    
    def list_templates(self) -> List[str]:
        """List all available template names in the workflows directory."""
        if not self.workflows_dir.exists():
            return []
        
        return [
            f.stem for f in self.workflows_dir.glob("*.json")
            if not f.name.startswith("_")  # Skip _private files
        ]
    
    def clear_cache(self) -> None:
        """Clear the template cache."""
        self._template_cache.clear()
    
    def _find_workflow_file(self, name: str) -> Optional[Path]:
        """Find workflow file by name, trying common patterns."""
        candidates = [
            self.workflows_dir / f"{name}.json",
            self.workflows_dir / f"{name}_workflow.json",
            self.workflows_dir / name,  # If name includes extension
        ]
        
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        
        return None
    
    def _load_from_file(self, filepath: Path) -> WorkflowTemplate:
        """Load a template from a JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        
        # Support both raw workflow and wrapped format
        # Wrapped: {"metadata": {...}, "workflow": {...}}
        # Raw: {"node_id": {...}, ...}
        if "workflow" in data and isinstance(data.get("workflow"), dict):
            workflow = data["workflow"]
            metadata = data.get("metadata", {})
        else:
            workflow = data
            metadata = {}
        
        placeholders = self._extract_placeholders(workflow)
        
        return WorkflowTemplate(
            name=filepath.stem,
            workflow=workflow,
            placeholders=placeholders,
            source_path=filepath,
            metadata=metadata
        )
    
    def _extract_placeholders(self, obj: Any, found: Optional[Set[str]] = None) -> Set[str]:
        """
        Recursively extract placeholder names from a workflow structure.
        
        Args:
            obj: The object to search (dict, list, or primitive)
            found: Accumulator set (created if not provided)
            
        Returns:
            Set of placeholder names found
        """
        if found is None:
            found = set()
        
        if isinstance(obj, str):
            # Find all {{PLACEHOLDER}} patterns
            matches = PLACEHOLDER_PATTERN.findall(obj)
            found.update(matches)
            
        elif isinstance(obj, dict):
            for value in obj.values():
                self._extract_placeholders(value, found)
                
        elif isinstance(obj, list):
            for item in obj:
                self._extract_placeholders(item, found)
        
        return found
    
    # -------------------------------------------------------------------------
    # INJECTION
    # -------------------------------------------------------------------------
    
    def inject(
        self,
        template: WorkflowTemplate,
        params: Dict[str, Any],
        strict: bool = False
    ) -> InjectionResult:
        """
        Inject parameters into a workflow template.
        
        Args:
            template: The workflow template
            params: Dict of placeholder_name -> value
            strict: If True, raise on missing placeholders
            
        Returns:
            InjectionResult with the modified workflow
            
        Raises:
            ValueError: If strict=True and placeholders are missing
        """
        # Deep copy to avoid modifying original
        workflow = copy.deepcopy(template.workflow)
        
        # Track what we inject
        injected: Set[str] = set()
        warnings: List[str] = []
        
        # Perform injection
        workflow = self._inject_recursive(workflow, params, injected, warnings)
        
        # Calculate unused and missing
        unused = set(params.keys()) - injected
        missing = template.placeholders - injected
        
        # Warn about unused params (might indicate typo)
        for param in unused:
            if param not in KNOWN_PLACEHOLDERS:
                warnings.append(f"Unknown parameter '{param}' not in template")
        
        # Strict mode check
        if strict and missing:
            raise ValueError(
                f"Missing required placeholders: {missing}"
            )
        
        result = InjectionResult(
            workflow=workflow,
            injected=injected,
            unused=unused,
            missing=missing,
            warnings=warnings
        )
        
        if result.warnings:
            for warn in result.warnings:
                logger.warning(f"Injection warning: {warn}")
        
        return result
    
    def _inject_recursive(
        self,
        obj: Any,
        params: Dict[str, Any],
        injected: Set[str],
        warnings: List[str]
    ) -> Any:
        """
        Recursively inject parameters into a structure.
        
        Handles:
        - String replacement: "{{PROMPT}}" -> "actual prompt"
        - Partial replacement: "prefix_{{NAME}}_suffix" -> "prefix_alice_suffix"
        - Type coercion: "{{SEED}}" with int value -> int (not string)
        """
        if isinstance(obj, str):
            # Check for full placeholder (entire string is one placeholder)
            full_match = PLACEHOLDER_PATTERN.fullmatch(obj.strip())
            if full_match:
                placeholder = full_match.group(1)
                if placeholder in params:
                    injected.add(placeholder)
                    # Return the value directly (preserves type)
                    return params[placeholder]
                return obj
            
            # Check for partial placeholders (placeholder within larger string)
            def replace_placeholder(match):
                placeholder = match.group(1)
                if placeholder in params:
                    injected.add(placeholder)
                    return str(params[placeholder])
                return match.group(0)  # Keep original if not in params
            
            return PLACEHOLDER_PATTERN.sub(replace_placeholder, obj)
        
        elif isinstance(obj, dict):
            return {
                key: self._inject_recursive(value, params, injected, warnings)
                for key, value in obj.items()
            }
        
        elif isinstance(obj, list):
            return [
                self._inject_recursive(item, params, injected, warnings)
                for item in obj
            ]
        
        else:
            # Primitive (int, float, bool, None) - return as-is
            return obj
    
    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------
    
    def validate(self, workflow: Dict[str, Any]) -> ValidationResult:
        """
        Validate a workflow before submission.
        
        Checks:
        - Required node types present
        - Node connections are valid
        - No unresolved placeholders remain
        - Known problematic patterns
        
        Args:
            workflow: The workflow dict to validate
            
        Returns:
            ValidationResult with errors and warnings
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        # Check for unresolved placeholders
        remaining = self._extract_placeholders(workflow)
        if remaining:
            errors.append(f"Unresolved placeholders: {remaining}")
        
        # Check workflow structure
        if not isinstance(workflow, dict):
            errors.append("Workflow must be a dict")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        if not workflow:
            errors.append("Workflow is empty")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        
        # Check each node (skip metadata keys starting with _)
        node_ids = set(k for k in workflow.keys() if not k.startswith("_"))
        for node_id, node_config in workflow.items():
            if node_id.startswith("_"):
                continue  # Skip metadata/documentation keys
            node_errors, node_warnings = self._validate_node(
                node_id, node_config, node_ids
            )
            errors.extend(node_errors)
            warnings.extend(node_warnings)
        
        # Check for output node
        has_output = any(
            node.get("class_type", "").lower() in ("saveimage", "savevideo", "vhs_videocombine")
            for node in workflow.values()
            if isinstance(node, dict)
        )
        if not has_output:
            warnings.append("No output node found (SaveImage, SaveVideo, etc.)")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _validate_node(
        self,
        node_id: str,
        node_config: Any,
        all_node_ids: Set[str]
    ) -> tuple[List[str], List[str]]:
        """Validate a single node configuration."""
        errors: List[str] = []
        warnings: List[str] = []
        
        if not isinstance(node_config, dict):
            errors.append(f"Node {node_id}: config must be dict, got {type(node_config)}")
            return errors, warnings
        
        # Check required fields
        if "class_type" not in node_config:
            errors.append(f"Node {node_id}: missing 'class_type'")
        
        # Check input connections reference valid nodes
        inputs = node_config.get("inputs", {})
        if isinstance(inputs, dict):
            for input_name, input_value in inputs.items():
                if isinstance(input_value, list) and len(input_value) >= 1:
                    # This is a connection: [source_node_id, output_index]
                    source_node = str(input_value[0])
                    if source_node not in all_node_ids:
                        errors.append(
                            f"Node {node_id}.{input_name}: references non-existent node '{source_node}'"
                        )
        
        return errors, warnings
    
    # -------------------------------------------------------------------------
    # CONVENIENCE METHODS
    # -------------------------------------------------------------------------
    
    def load_and_inject(
        self,
        name: str,
        params: Dict[str, Any],
        strict: bool = False,
        validate: bool = True
    ) -> Dict[str, Any]:
        """
        Load template, inject params, validate, return workflow.
        
        Convenience method for the common pattern of load -> inject -> validate.
        
        Args:
            name: Template name
            params: Parameters to inject
            strict: Raise on missing placeholders
            validate: Validate after injection
            
        Returns:
            Ready-to-submit workflow dict
            
        Raises:
            FileNotFoundError: Template not found
            ValueError: Injection or validation failed
        """
        template = self.load(name)
        result = self.inject(template, params, strict=strict)
        
        if not result.success:
            logger.warning(f"Missing placeholders: {result.missing}")
        
        if validate:
            validation = self.validate(result.workflow)
            if not validation.valid:
                raise ValueError(
                    f"Workflow validation failed: {validation.errors}"
                )
            for warn in validation.warnings:
                logger.warning(f"Validation warning: {warn}")
        
        return result.workflow


# =============================================================================
# PARAMETER BUILDERS
# =============================================================================

@dataclass
class GenerationParams:
    """
    Standard parameters for video generation.
    
    Use this to build param dicts with proper defaults and validation.
    
    Usage:
        params = GenerationParams(
            positive_prompt="A woman in a kitchen",
            seed=42
        )
        workflow = loader.load_and_inject("pass1", params.to_dict())
    """
    # Required
    positive_prompt: str
    
    # Common optional with sensible defaults
    negative_prompt: str = "blurry, low quality, distorted, disfigured"
    seed: int = -1  # -1 = random
    cfg_scale: float = 7.0
    steps: int = 20
    denoise: float = 1.0
    
    # Dimensions
    width: int = 1280
    height: int = 720
    
    # Video-specific
    fps: int = 12
    frames: int = 49  # ~4 seconds at 12fps
    
    # Identity (optional)
    lora_path: Optional[str] = None
    lora_strength: float = 0.8
    
    # Init image/video (optional)
    init_image: Optional[str] = None
    init_video: Optional[str] = None
    
    # Output
    output_prefix: str = "continuum"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to parameter dict for injection.
        
        Only includes non-None values to avoid overwriting template defaults.
        """
        params = {
            "POSITIVE_PROMPT": self.positive_prompt,
            "NEGATIVE_PROMPT": self.negative_prompt,
            "SEED": self.seed,
            "CFG_SCALE": self.cfg_scale,
            "STEPS": self.steps,
            "DENOISE": self.denoise,
            "WIDTH": self.width,
            "HEIGHT": self.height,
            "FPS": self.fps,
            "FRAMES": self.frames,
            "LORA_STRENGTH": self.lora_strength,
            "OUTPUT_PREFIX": self.output_prefix,
        }
        
        # Add optional params only if set
        if self.lora_path:
            params["LORA_PATH"] = self.lora_path
        if self.init_image:
            params["INIT_IMAGE"] = self.init_image
        if self.init_video:
            params["INIT_VIDEO"] = self.init_video
        
        return params


@dataclass
class CharacterParams:
    """Parameters for character identity injection."""
    name: str
    lora_path: Optional[str] = None
    face_refs: List[str] = field(default_factory=list)
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to parameter dict."""
        params = {
            "CHARACTER_NAME": self.name,
        }
        
        if self.lora_path:
            params["CHARACTER_LORA"] = self.lora_path
            params["LORA_PATH"] = self.lora_path
        
        # Add face refs (up to 3)
        for i, ref in enumerate(self.face_refs[:3], 1):
            params[f"FACE_REF_{i}"] = ref
        
        if self.description:
            params["CHARACTER_DESCRIPTION"] = self.description
        
        return params


@dataclass  
class EnvironmentParams:
    """Parameters for environment/location injection."""
    name: str
    ref_image: Optional[str] = None
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to parameter dict."""
        params = {
            "LOCATION_NAME": self.name,
        }
        
        if self.ref_image:
            params["ENVIRONMENT_REF"] = self.ref_image
        
        if self.description:
            params["LOCATION_DESCRIPTION"] = self.description
        
        return params


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_workflow_loader() -> WorkflowLoader:
    """Get a WorkflowLoader using global config paths."""
    return WorkflowLoader()


def merge_params(*param_sources: Union[Dict[str, Any], GenerationParams, CharacterParams, EnvironmentParams]) -> Dict[str, Any]:
    """
    Merge multiple parameter sources into one dict.
    
    Later sources override earlier ones.
    
    Usage:
        params = merge_params(
            GenerationParams(positive_prompt="...").to_dict(),
            CharacterParams(name="Alice", lora_path="...").to_dict(),
            {"SEED": 42}  # Override
        )
    """
    result = {}
    for source in param_sources:
        if hasattr(source, "to_dict"):
            result.update(source.to_dict())
        elif isinstance(source, dict):
            result.update(source)
    return result