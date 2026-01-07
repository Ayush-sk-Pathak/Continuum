"""
Continuum Engine - Base Renderer Interface

Defines the abstract interface that ALL renderers must implement.
This enables hot-swapping between rendering backends (Wan, Runway, Veo)
without changing any orchestration code.

Design Principles:
1. Interface segregation: Only define what ALL renderers need
2. Dependency inversion: Director depends on abstraction, not concrete renderers
3. Rich result types: Return structured data, not just paths
4. Async-first: Video generation is inherently async (long-running)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime


# =============================================================================
# REMOTE PATH HELPERS
# =============================================================================

def _is_remote_path(path: Optional[Path]) -> bool:
    """
    Check if a path exists on the remote ComfyUI server (not locally).
    
    Per Architecture: Mac orchestrates, RunPod renders. Paths starting with
    /workspace/ exist on RunPod but not on Mac.
    """
    if path is None:
        return False
    path_str = str(path)
    remote_prefixes = ("/workspace/", "/comfyui/", "/models/", "/root/")
    return any(path_str.startswith(prefix) for prefix in remote_prefixes)


def _path_exists_or_remote(path: Optional[Path]) -> bool:
    """Check if path exists locally OR is a remote path (assumed to exist)."""
    if path is None:
        return False
    return _is_remote_path(path) or path.exists()


# =============================================================================
# ENUMS
# =============================================================================

class RendererType(str, Enum):
    """Identifies the renderer backend."""
    WAN = "wan"              # Wan 2.x via ComfyUI (OSS)
    HUNYUAN = "hunyuan"      # HunyuanVideo via ComfyUI (OSS)
    HUNYUAN_CUSTOM = "hunyuan_custom"  # HunyuanCustom - identity-preserving (OSS)
    MOCHI = "mochi"          # Mochi via ComfyUI (OSS)
    RUNWAY = "runway"        # Runway Gen-4 API (Pro Lane)
    VEO = "veo"              # Google Veo API (Pro Lane)
    SORA = "sora"            # OpenAI Sora API (Pro Lane)
    MOCK = "mock"            # Mock renderer for testing


class RenderQuality(str, Enum):
    """Quality presets affecting speed/quality tradeoff."""
    DRAFT = "draft"          # Fast, low quality (for previews)
    STANDARD = "standard"    # Balanced (default)
    HIGH = "high"            # Slow, high quality (final renders)


# =============================================================================
# INPUT DATA STRUCTURES
# =============================================================================

@dataclass
class CharacterRef:
    """
    Reference assets for a character's identity.
    
    Attributes:
        entity_id: Unique identifier (e.g., "alice", "hero_001")
        name: Human-readable name
        lora_path: Path to trained LoRA (highest quality)
        face_refs: List of face reference images (for IP-Adapter fallback)
        description: Text description (for prompt-only fallback)
    """
    entity_id: str
    name: str
    lora_path: Optional[Path] = None
    face_refs: List[Path] = field(default_factory=list)
    description: str = ""
    lora_strength: float = 0.8
    
    def has_lora(self) -> bool:
        """Check if LoRA is available (locally or on remote ComfyUI)."""
        return self.lora_path is not None and _path_exists_or_remote(self.lora_path)
    
    def has_face_refs(self) -> bool:
        """Check if face references are available (locally or on remote ComfyUI)."""
        return len(self.face_refs) > 0 and all(_path_exists_or_remote(p) for p in self.face_refs)
    
    def best_available_method(self) -> str:
        """Return the best identity method available."""
        if self.has_lora():
            return "lora"
        elif self.has_face_refs():
            return "ip_adapter"
        else:
            return "prompt"


@dataclass
class LocationRef:
    """
    Reference assets for an environment/location.
    
    Attributes:
        entity_id: Unique identifier (e.g., "kitchen_001")
        name: Human-readable name
        ref_images: Reference images for the location
        description: Text description
    """
    entity_id: str
    name: str
    ref_images: List[Path] = field(default_factory=list)
    description: str = ""
    
    def has_refs(self) -> bool:
        """Check if reference images are available."""
        return len(self.ref_images) > 0 and all(p.exists() for p in self.ref_images)


@dataclass
class LayoutRegion:
    """
    A region in the frame for regional prompting.
    
    Used for multi-character scenes to prevent identity bleeding.
    
    Attributes:
        entity_id: Which entity occupies this region
        bbox: Bounding box as (x, y, width, height) normalized 0-1
        prompt_override: Optional prompt specific to this region
    """
    entity_id: str
    bbox: tuple[float, float, float, float]  # (x, y, w, h) normalized
    prompt_override: Optional[str] = None


@dataclass
class JobSpec:
    """
    Complete specification for a render job.
    
    This is the "contract" between the Director and any Renderer.
    All renderers receive the same JobSpec; they interpret it according
    to their capabilities.
    
    Attributes:
        prompt: Main positive prompt
        negative_prompt: What to avoid
        duration_sec: Target duration in seconds
        init_frame: Starting frame (for shot continuity)
        character_refs: Characters appearing in this shot
        location_refs: Location/environment references
        layout: Regional prompting layout (for multi-character)
        seed: Random seed (-1 for random)
        quality: Quality preset
        width: Output width in pixels
        height: Output height in pixels
        fps: Frames per second
        cfg_scale: Classifier-free guidance scale
        steps: Diffusion steps
        renderer_config: Renderer-specific overrides
    """
    # Required
    prompt: str
    
    # Timing
    duration_sec: float = 4.0
    
    # Identity & environment
    character_refs: List[CharacterRef] = field(default_factory=list)
    location_refs: List[LocationRef] = field(default_factory=list)
    
    # Continuity
    init_frame: Optional[Path] = None
    
    # Layout (for multi-character)
    layout: Optional[List[LayoutRegion]] = None
    
    # Generation params
    negative_prompt: str = "blurry, low quality, distorted, disfigured"
    seed: int = -1
    quality: RenderQuality = RenderQuality.STANDARD
    
    # Dimensions
    width: int = 1280
    height: int = 720
    fps: int = 12
    
    # Model params
    cfg_scale: float = 7.0
    steps: int = 12
    denoise: float = 1.0
    
    # Renderer-specific (passed through without interpretation)
    renderer_config: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def frame_count(self) -> int:
        """Calculate total frames from duration and fps."""
        return int(self.duration_sec * self.fps)
    
    @property
    def has_init_frame(self) -> bool:
        """Check if init frame is provided and exists."""
        return self.init_frame is not None and self.init_frame.exists()
    
    @property
    def is_multi_character(self) -> bool:
        """Check if this is a multi-character scene."""
        return len(self.character_refs) > 1


# =============================================================================
# OUTPUT DATA STRUCTURES
# =============================================================================

@dataclass
class RenderResult:
    """
    Result of a successful render.
    
    Attributes:
        video_path: Path to the output video file
        frame_count: Number of frames generated
        fps: Frames per second of output
        duration_sec: Actual duration in seconds
        resolution: (width, height) tuple
        renderer_type: Which renderer produced this
        metadata: Additional renderer-specific info
        render_time_sec: How long rendering took
        cost_estimate: Estimated cost in USD (for tracking)
    """
    video_path: Path
    frame_count: int
    fps: float
    duration_sec: float
    resolution: tuple[int, int]
    renderer_type: RendererType
    metadata: Dict[str, Any] = field(default_factory=dict)
    render_time_sec: float = 0.0
    cost_estimate: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def exists(self) -> bool:
        """Check if the output file exists."""
        return self.video_path.exists()


@dataclass
class RenderProgress:
    """
    Progress update during rendering.
    
    Attributes:
        stage: Current stage name
        progress: Progress within stage (0.0 to 1.0)
        message: Human-readable status
        elapsed_sec: Time elapsed so far
        eta_sec: Estimated time remaining (None if unknown)
    """
    stage: str
    progress: float
    message: str = ""
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    
    @property
    def percent(self) -> int:
        """Progress as percentage (0-100)."""
        return int(self.progress * 100)


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseRenderer(ABC):
    """
    Abstract base class for all video renderers.
    
    To implement a new renderer:
    1. Inherit from BaseRenderer
    2. Implement all @abstractmethod methods
    3. Set renderer_type in __init__
    
    Example:
        class MyRenderer(BaseRenderer):
            def __init__(self):
                super().__init__(RendererType.WAN)
            
            async def generate(self, job: JobSpec) -> RenderResult:
                # ... implementation ...
    
    Usage:
        renderer = WanRenderer()
        if await renderer.health_check():
            result = await renderer.generate(job_spec)
    """
    
    def __init__(self, renderer_type: RendererType):
        """
        Initialize the renderer.
        
        Args:
            renderer_type: Identifies this renderer backend
        """
        self.renderer_type = renderer_type
        self._progress_callback: Optional[Callable[[RenderProgress], None]] = None
    
    # -------------------------------------------------------------------------
    # ABSTRACT METHODS (Must be implemented by subclasses)
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def generate(
        self,
        job: JobSpec,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> RenderResult:
        """
        Generate video from a job specification.
        
        This is the core method. Implementations should:
        1. Translate JobSpec to their native format
        2. Submit to their backend
        3. Wait for completion
        4. Return RenderResult with output path
        
        Args:
            job: The job specification
            progress_callback: Optional callback for progress updates
            
        Returns:
            RenderResult with path to generated video
            
        Raises:
            RenderError: If generation fails
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the renderer backend is available and healthy.
        
        Returns:
            True if renderer is ready to accept jobs
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, job: JobSpec) -> float:
        """
        Estimate the cost of a job in USD.
        
        Used for:
        - Budget tracking
        - Choosing between Standard/Pro lane
        - User feedback
        
        Args:
            job: The job to estimate
            
        Returns:
            Estimated cost in USD
        """
        pass
    
    @abstractmethod
    def estimate_time(self, job: JobSpec) -> float:
        """
        Estimate render time in seconds.
        
        Used for:
        - Progress estimation
        - Timeout configuration
        - User feedback
        
        Args:
            job: The job to estimate
            
        Returns:
            Estimated time in seconds
        """
        pass
    
    # -------------------------------------------------------------------------
    # OPTIONAL METHODS (Override if needed)
    # -------------------------------------------------------------------------
    
    async def initialize(self) -> None:
        """
        Perform any async initialization.
        
        Called once before first generate(). Override if your renderer
        needs to establish connections, warm up caches, etc.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Clean up resources.
        
        Called when renderer is no longer needed. Override if your
        renderer holds connections or resources that need cleanup.
        """
        pass
    
    def supports_feature(self, feature: str) -> bool:
        """
        Check if this renderer supports a specific feature.
        
        Known features:
        - "init_frame": Can use init_frame for continuity
        - "lora": Can use LoRA for identity
        - "ip_adapter": Can use IP-Adapter for identity
        - "regional_prompt": Can do regional prompting
        - "controlnet": Can use ControlNet
        - "long_video": Can generate >30 seconds natively
        
        Override to declare your renderer's capabilities.
        
        Args:
            feature: Feature name to check
            
        Returns:
            True if feature is supported
        """
        return False
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get a dict of all renderer capabilities.
        
        Override to provide detailed capability info.
        
        Returns:
            Dict with capability details
        """
        return {
            "renderer_type": self.renderer_type.value,
            "features": [],
            "max_duration_sec": 10,
            "max_resolution": (1280, 720),
            "supported_fps": [12, 24],
        }
    
    # -------------------------------------------------------------------------
    # HELPER METHODS (Available to all subclasses)
    # -------------------------------------------------------------------------
    
    def _report_progress(
        self,
        stage: str,
        progress: float,
        message: str = "",
        elapsed_sec: float = 0.0,
        eta_sec: Optional[float] = None,
        callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> None:
        """
        Report progress to callback if provided.
        
        Args:
            stage: Current stage name
            progress: Progress 0.0-1.0
            message: Human-readable message
            elapsed_sec: Time elapsed
            eta_sec: Estimated time remaining
            callback: Progress callback (uses stored callback if None)
        """
        cb = callback or self._progress_callback
        if cb:
            cb(RenderProgress(
                stage=stage,
                progress=progress,
                message=message,
                elapsed_sec=elapsed_sec,
                eta_sec=eta_sec
            ))
    
    def _apply_quality_preset(self, job: JobSpec) -> Dict[str, Any]:
        """
        Get generation params adjusted for quality preset.
        
        Returns dict with steps, cfg_scale, etc. adjusted for quality.
        """
        presets = {
            RenderQuality.DRAFT: {
                "steps": max(10, job.steps // 2),
                "cfg_scale": job.cfg_scale,
            },
            RenderQuality.STANDARD: {
                "steps": job.steps,
                "cfg_scale": job.cfg_scale,
            },
            RenderQuality.HIGH: {
                "steps": min(50, int(job.steps * 1.5)),
                "cfg_scale": job.cfg_scale + 1.0,
            },
        }
        return presets.get(job.quality, presets[RenderQuality.STANDARD])


# =============================================================================
# EXCEPTIONS
# =============================================================================

class RenderError(Exception):
    """Base exception for render errors."""
    def __init__(self, message: str, job: Optional[JobSpec] = None):
        super().__init__(message)
        self.job = job


class RenderTimeoutError(RenderError):
    """Render took too long."""
    pass


class RenderConfigError(RenderError):
    """Invalid job configuration."""
    pass


class RenderBackendError(RenderError):
    """Backend system error (ComfyUI, API, etc.)."""
    pass


# =============================================================================
# RENDERER REGISTRY
# =============================================================================

# Global registry of available renderers
_renderer_registry: Dict[RendererType, type] = {}


def register_renderer(renderer_type: RendererType):
    """
    Decorator to register a renderer class.
    
    Usage:
        @register_renderer(RendererType.WAN)
        class WanRenderer(BaseRenderer):
            ...
    """
    def decorator(cls):
        _renderer_registry[renderer_type] = cls
        return cls
    return decorator


def get_renderer(renderer_type: RendererType, **kwargs) -> BaseRenderer:
    """
    Get a renderer instance by type.
    
    Args:
        renderer_type: Which renderer to get
        **kwargs: Passed to renderer constructor
        
    Returns:
        Instantiated renderer
        
    Raises:
        ValueError: If renderer type not registered
    """
    if renderer_type not in _renderer_registry:
        available = list(_renderer_registry.keys())
        raise ValueError(
            f"Renderer '{renderer_type}' not registered. Available: {available}"
        )
    
    return _renderer_registry[renderer_type](**kwargs)


def list_renderers() -> List[RendererType]:
    """List all registered renderer types."""
    return list(_renderer_registry.keys())


def get_renderer_for_config(config: Optional[Any] = None, **kwargs) -> BaseRenderer:
    """
    Get the appropriate renderer based on config's video_model.model_family.
    
    This is the PRIMARY way to get a renderer in production code.
    It reads the model_family from config and returns the matching renderer.
    
    Args:
        config: Config object (if None, loads from get_config())
        **kwargs: Passed to renderer constructor
        
    Returns:
        Instantiated renderer matching the configured model family
        
    Raises:
        ValueError: If model_family has no registered renderer
        
    Usage:
        # In main.py or orchestration code:
        renderer = get_renderer_for_config()
        
        # With explicit config:
        renderer = get_renderer_for_config(my_config)
        
    Architecture Note:
        This factory is the single source of truth for mapping
        config.video_model.model_family -> RendererType -> Renderer instance.
        Adding a new model family requires:
        1. Add enum value to RendererType
        2. Create renderer class with @register_renderer decorator
        3. Add mapping in _MODEL_FAMILY_TO_RENDERER below
    """
    # Import here to avoid circular import (config imports from various places)
    if config is None:
        from ..core.config import get_config
        config = get_config()
    
    # Get model family from config
    model_family = config.video_model.model_family
    
    # Map model family string to RendererType
    # This is the single source of truth for family -> renderer mapping
    family_to_renderer: Dict[str, RendererType] = {
        "wan": RendererType.WAN,
        "hunyuan_custom": RendererType.HUNYUAN_CUSTOM,
        "hunyuan": RendererType.HUNYUAN,
        "mochi": RendererType.MOCHI,
    }
    
    if model_family not in family_to_renderer:
        available = list(family_to_renderer.keys())
        raise ValueError(
            f"No renderer registered for model_family='{model_family}'. "
            f"Available families: {available}. "
            f"Check CONTINUUM_VIDEO_MODEL__MODEL_FAMILY environment variable."
        )
    
    renderer_type = family_to_renderer[model_family]
    
    # Check if renderer is actually registered
    if renderer_type not in _renderer_registry:
        raise ValueError(
            f"RendererType.{renderer_type.name} is mapped but not registered. "
            f"Ensure the renderer class uses @register_renderer({renderer_type.name}) decorator "
            f"and is imported before calling get_renderer_for_config()."
        )
    
    return get_renderer(renderer_type, **kwargs)