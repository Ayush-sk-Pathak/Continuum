"""
Continuum Engine - Pass 2 Refiner

Takes video from Pass 1 (after Audit approval) and applies refinement:
- Flicker reduction
- Detail enhancement  
- Temporal consistency improvements

The Problem:
    Pass 1 generates structurally correct video, but diffusion models
    introduce frame-to-frame inconsistencies: flickering textures,
    jittering edges, temporal noise.

The Solution:
    Run a second pass through a vid2vid model that:
    1. Takes the full video as context (not frame-by-frame)
    2. Applies temporal smoothing
    3. Enhances details without changing structure

Architecture Note:
    "CoNo and FreeLong++ are new research. They may not exist as 
    ready-made ComfyUI nodes... The architecture treats them as 
    pluggable upgrades, not hard dependencies."
    
    If FreeLong++-style refinement is unavailable, we fall back to
    simpler vid2vid temporal denoising.

Pipeline Position:
    Pass 1 ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Audit ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ **Pass 2 (this)** ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Lip Sync ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ RIFE ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Final

Design Principles:
    1. Workflow-agnostic: Actual ComfyUI workflow is external JSON
    2. Degradation-ready: FreeLong++ ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Vid2Vid ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Passthrough fallback
    3. Async-first: All refinement is async (GPU-bound)
    4. Preserves structure: Should NOT change composition or motion
"""

import asyncio
import logging
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class RefinementMethod(str, Enum):
    """
    Available refinement methods, in order of quality.
    
    The refiner will try methods in order and fall back if unavailable.
    """
    FREELONG_PLUS = "freelong_plus"      # Best: Full temporal attention
    VID2VID_TEMPORAL = "vid2vid_temporal"  # Good: Temporal denoising
    VID2VID_SIMPLE = "vid2vid_simple"    # Basic: Frame-by-frame with context
    PASSTHROUGH = "passthrough"          # None: Just copy (testing/fallback)


class RefinementStatus(str, Enum):
    """Status of a refinement job."""
    PENDING = "pending"
    LOADING = "loading"          # Loading video into GPU
    REFINING = "refining"        # Running refinement model
    SAVING = "saving"            # Writing output
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"          # Passthrough mode


class RefinementQuality(str, Enum):
    """Quality presets for refinement."""
    DRAFT = "draft"              # Fast, minimal refinement
    STANDARD = "standard"        # Balanced (default)
    HIGH = "high"                # Slow, maximum quality


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RefinementSpec:
    """
    Specification for a refinement job.
    
    Attributes:
        input_path: Path to Pass 1 video
        output_path: Where to write refined video
        shot_id: Identifier for tracking
        method: Which refinement method to use (None = auto-select)
        quality: Quality preset
        denoise_strength: How aggressively to denoise (0.0-1.0)
        preserve_motion: Preserve original motion vectors
        temporal_window: Frames of context for temporal models
    """
    input_path: Path
    output_path: Path
    shot_id: str
    method: Optional[RefinementMethod] = None  # None = auto-select best available
    quality: RefinementQuality = RefinementQuality.STANDARD
    denoise_strength: float = 0.5
    preserve_motion: bool = True
    temporal_window: int = 16  # Frames of context
    
    # Optional overrides
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    
    def __post_init__(self):
        if isinstance(self.input_path, str):
            self.input_path = Path(self.input_path)
        if isinstance(self.output_path, str):
            self.output_path = Path(self.output_path)
        
        # Clamp values
        self.denoise_strength = max(0.0, min(1.0, self.denoise_strength))
        self.temporal_window = max(4, min(32, self.temporal_window))


@dataclass
class RefinementResult:
    """
    Result of a refinement operation.
    
    Attributes:
        success: Whether refinement completed
        output_path: Path to refined video
        method_used: Which method was actually used
        status: Final status
        processing_time_sec: How long refinement took
        input_frames: Number of input frames
        output_frames: Number of output frames
        metrics: Quality metrics (if computed)
        error: Error message if failed
        warnings: Non-fatal issues
    """
    success: bool
    output_path: Optional[Path] = None
    method_used: RefinementMethod = RefinementMethod.PASSTHROUGH
    status: RefinementStatus = RefinementStatus.PENDING
    processing_time_sec: float = 0.0
    input_frames: int = 0
    output_frames: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def failed(cls, error: str, method: RefinementMethod = RefinementMethod.PASSTHROUGH) -> "RefinementResult":
        """Factory for a failed result."""
        return cls(
            success=False,
            method_used=method,
            status=RefinementStatus.FAILED,
            error=error,
        )
    
    @classmethod
    def skipped(cls, output_path: Path, reason: str) -> "RefinementResult":
        """Factory for a skipped/passthrough result."""
        return cls(
            success=True,
            output_path=output_path,
            method_used=RefinementMethod.PASSTHROUGH,
            status=RefinementStatus.SKIPPED,
            warnings=[f"Refinement skipped: {reason}"],
        )


@dataclass
class RefinementProgress:
    """Progress update during refinement."""
    stage: str
    progress: float  # 0.0 to 1.0
    message: str = ""
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    
    @property
    def percent(self) -> int:
        return int(self.progress * 100)


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseRefiner(ABC):
    """
    Abstract base class for video refiners.
    
    Implementations can use different backends:
    - ComfyUI-based (FreeLong++, vid2vid workflows)
    - Local models (future)
    - API services (future)
    """
    
    method: RefinementMethod
    
    def __init__(
        self,
        output_dir: Path,
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the refiner.
        
        Args:
            output_dir: Default directory for refined videos
            temp_dir: Directory for temporary files
        """
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir()) / "continuum_refine"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    async def refine(
        self,
        spec: RefinementSpec,
        progress_callback: Optional[Callable[[RefinementProgress], None]] = None,
    ) -> RefinementResult:
        """
        Refine a video.
        
        Args:
            spec: Refinement specification
            progress_callback: Optional callback for progress updates
            
        Returns:
            RefinementResult with path to refined video
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the refiner backend is available.
        
        Returns:
            True if ready to process
        """
        pass
    
    @abstractmethod
    def estimate_time(self, spec: RefinementSpec) -> float:
        """
        Estimate processing time in seconds.
        
        Args:
            spec: The refinement spec
            
        Returns:
            Estimated time in seconds
        """
        pass
    
    def estimate_cost(self, spec: RefinementSpec) -> float:
        """
        Estimate cost in USD.
        
        Default implementation based on GPU time.
        Override for specific pricing models.
        """
        # Rough estimate: $0.50/hr GPU, refinement is ~0.5x realtime
        time_sec = self.estimate_time(spec)
        hourly_rate = 0.50
        return (time_sec / 3600) * hourly_rate
    
    async def shutdown(self) -> None:
        """
        Release resources held by the refiner.
        
        Default implementation does nothing. Override in subclasses
        that hold resources like ComfyClient connections.
        
        Called by main.py during pipeline shutdown.
        """
        pass  # No-op by default; subclasses override if needed


# =============================================================================
# COMFYUI-BASED REFINER
# =============================================================================

class ComfyRefiner(BaseRefiner):
    """
    Refiner using ComfyUI vid2vid workflows.
    
    This is the primary implementation for cloud GPU refinement.
    It loads a vid2vid workflow, injects the input video, and
    retrieves the refined output.
    
    Workflow Requirements:
        The ComfyUI workflow must have:
        - A video input node (LoadVideo or similar)
        - A vid2vid/temporal model
        - A video output node (SaveVideo or similar)
    
    Attributes:
        client: ComfyClient for GPU communication
        workflow_name: Name of the refinement workflow (without .json)
        method: Which refinement method this uses
    """
    
    def __init__(
        self,
        comfy_host: str,
        workflow_name: str,
        method: RefinementMethod = RefinementMethod.VID2VID_TEMPORAL,
        output_dir: Path = Path("./workspace/video/refined"),
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the ComfyUI-based refiner.
        
        Args:
            comfy_host: ComfyUI server URL (e.g., "http://localhost:8188")
            workflow_name: Name of the vid2vid workflow (e.g., "refine_vid2vid")
            method: Which refinement method this workflow implements
            output_dir: Where to save refined videos
            temp_dir: Temporary file directory
        """
        super().__init__(output_dir, temp_dir)
        
        self.comfy_host = comfy_host
        self.workflow_name = workflow_name
        self.method = method
        self._client = None
        self._loader = None
        self._template = None
    
    async def _get_client(self):
        """Lazy-initialize ComfyUI client."""
        if self._client is None:
            try:
                from ..comfy_client.client import ComfyClient
                self._client = ComfyClient(self.comfy_host)
                await self._client.connect()
            except ImportError:
                raise RuntimeError(
                    "ComfyClient not available. "
                    "Ensure src/comfy_client module exists."
                )
        return self._client
    
    async def _ensure_connected(self):
        """Ensure client is connected, reconnecting if necessary."""
        client = await self._get_client()
        
        # Quick health check - if it fails, reconnect
        try:
            if not await client.health_check():
                raise ConnectionError("Health check failed")
        except Exception as e:
            logger.info(f"ComfyUI connection stale ({e}), reconnecting...")
            try:
                await client.connect()
            except Exception as reconnect_error:
                # Connection failed, try fresh client
                logger.warning(f"Reconnection failed ({reconnect_error}), creating new client...")
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                self._client = None
                client = await self._get_client()
        
        return client
    
    async def _load_workflow(self):
        """Load the refinement workflow template."""
        if self._template is None:
            try:
                from ..comfy_client.workflow_loader import WorkflowLoader
                if self._loader is None:
                    self._loader = WorkflowLoader()
                self._template = self._loader.load(self.workflow_name)
            except Exception as e:
                raise RuntimeError(f"Failed to load workflow '{self.workflow_name}': {e}")
        return self._template
    
    async def refine(
        self,
        spec: RefinementSpec,
        progress_callback: Optional[Callable[[RefinementProgress], None]] = None,
    ) -> RefinementResult:
        """Refine video using ComfyUI workflow."""
        start_time = time.time()
        
        def report_progress(stage: str, progress: float, message: str = ""):
            if progress_callback:
                progress_callback(RefinementProgress(
                    stage=stage,
                    progress=progress,
                    message=message,
                    elapsed_sec=time.time() - start_time,
                ))
        
        try:
            # Validate input
            if not spec.input_path.exists():
                return RefinementResult.failed(f"Input video not found: {spec.input_path}")
            
            report_progress("loading", 0.1, "Connecting to ComfyUI...")
            
            client = await self._ensure_connected()
            
            report_progress("loading", 0.2, "Preparing workflow...")
            
            # Load workflow template and inject parameters
            template = await self._load_workflow()
            params = self._build_workflow_params(spec)
            
            # Note: inject() returns InjectResult with .workflow attribute
            # This is a simplified version - actual impl depends on WorkflowLoader API
            inject_result = self._loader.inject(template, params)
            
            # Upload input video
            report_progress("loading", 0.3, "Uploading video to GPU...")
            
            # Note: Actual upload mechanism depends on ComfyUI setup
            # This is a simplified version
            input_filename = await self._upload_video(client, spec.input_path)
            
            # Get the workflow dict and set input video
            workflow = inject_result.workflow if hasattr(inject_result, 'workflow') else inject_result
            workflow = self._set_input_video(workflow, input_filename)
            
            report_progress("refining", 0.4, "Running refinement model...")
            
            # Submit job and wait for completion
            job = await client.submit(workflow)
            
            # Poll for completion with progress updates
            while not job.is_complete:
                await asyncio.sleep(1.0)
                if job.progress:
                    report_progress(
                        "refining",
                        0.4 + (job.progress * 0.5),  # 40-90%
                        f"Processing frames..."
                    )
            
            if job.failed:
                return RefinementResult.failed(
                    f"ComfyUI job failed: {job.error}",
                    self.method
                )
            
            report_progress("saving", 0.9, "Downloading refined video...")
            
            # Download output
            output_path = spec.output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await self._download_output(client, job, output_path)
            
            report_progress("completed", 1.0, "Refinement complete")
            
            processing_time = time.time() - start_time
            
            return RefinementResult(
                success=True,
                output_path=output_path,
                method_used=self.method,
                status=RefinementStatus.COMPLETED,
                processing_time_sec=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Refinement failed: {e}")
            return RefinementResult.failed(str(e), self.method)
    
    async def health_check(self) -> bool:
        """Check if ComfyUI is accessible."""
        try:
            client = await self._get_client()
            return await client.health_check()
        except Exception as e:
            logger.error(f"ComfyUI health check failed: {e}")
            return False
    
    async def shutdown(self) -> None:
        """
        Disconnect from ComfyUI and release resources.
        
        This ensures the aiohttp session is properly closed,
        preventing "Unclosed client session" warnings.
        """
        if self._client is not None:
            try:
                await self._client.disconnect()
                logger.debug(f"ComfyUIRefiner disconnected from {self.comfy_host}")
            except Exception as e:
                logger.warning(f"Error during ComfyUIRefiner shutdown: {e}")
            finally:
                self._client = None
    
    def estimate_time(self, spec: RefinementSpec) -> float:
        """Estimate refinement time based on video length and quality."""
        # Rough estimates: refinement is typically 0.5-2x realtime
        # depending on model and GPU
        
        # Get video duration (would need ffprobe in real implementation)
        # For now, estimate based on typical shot length
        estimated_duration = 12.0  # seconds (typical shot)
        
        quality_multipliers = {
            RefinementQuality.DRAFT: 0.5,
            RefinementQuality.STANDARD: 1.0,
            RefinementQuality.HIGH: 2.0,
        }
        
        method_multipliers = {
            RefinementMethod.FREELONG_PLUS: 1.5,
            RefinementMethod.VID2VID_TEMPORAL: 1.0,
            RefinementMethod.VID2VID_SIMPLE: 0.7,
            RefinementMethod.PASSTHROUGH: 0.1,
        }
        
        base_time = estimated_duration  # 1x realtime baseline
        quality_mult = quality_multipliers.get(spec.quality, 1.0)
        method_mult = method_multipliers.get(self.method, 1.0)
        
        return base_time * quality_mult * method_mult
    
    def _build_workflow_params(self, spec: RefinementSpec) -> Dict[str, Any]:
        """Build parameters to inject into workflow."""
        quality_settings = {
            RefinementQuality.DRAFT: {"steps": 10, "cfg_scale": 4.0},
            RefinementQuality.STANDARD: {"steps": 20, "cfg_scale": 6.0},
            RefinementQuality.HIGH: {"steps": 35, "cfg_scale": 7.0},
        }
        
        settings = quality_settings.get(spec.quality, quality_settings[RefinementQuality.STANDARD])
        
        return {
            # Core refinement params (UPPERCASE to match workflow placeholders)
            "DENOISE_STRENGTH": spec.denoise_strength,
            "STEPS": spec.steps or settings["steps"],
            "CFG_SCALE": spec.cfg_scale or settings["cfg_scale"],
            "TEMPORAL_WINDOW": spec.temporal_window,
            
            # Video I/O
            "INPUT_VIDEO": str(spec.input_path.name),  # Filename only, not full path
            "FPS": 12,  # Match Pass 1 output
            
            # Generation params
            "SEED": -1,  # Random seed for refinement
            "POSITIVE_PROMPT": "high quality, detailed, sharp, consistent lighting",
            "NEGATIVE_PROMPT": "blurry, flickering, low quality, jittery, frame inconsistency",
        }
    
    def _set_input_video(self, workflow: Dict, filename: str) -> Dict:
        """Set the input video filename in workflow."""
        # Find video loader node and set filename
        workflow = workflow.copy()
        # Node modification would happen here
        return workflow
    
    async def _upload_video(self, client, video_path: Path) -> str:
        """Upload video to ComfyUI server, return filename."""
        # Simplified - actual implementation depends on ComfyUI setup
        return video_path.name
    
    async def _download_output(self, client, job, output_path: Path) -> None:
        """Download output video from ComfyUI."""
        # Simplified - actual implementation depends on ComfyUI output handling
        pass


# =============================================================================
# PASSTHROUGH REFINER (FOR TESTING/FALLBACK)
# =============================================================================

class PassthroughRefiner(BaseRefiner):
    """
    No-op refiner that just copies input to output.
    
    Used when:
    - Testing pipeline without GPU
    - Refinement is disabled
    - All refinement methods fail
    """
    
    method = RefinementMethod.PASSTHROUGH
    
    async def refine(
        self,
        spec: RefinementSpec,
        progress_callback: Optional[Callable[[RefinementProgress], None]] = None,
    ) -> RefinementResult:
        """Just copy the input to output."""
        start_time = time.time()
        
        try:
            if not spec.input_path.exists():
                return RefinementResult.failed(f"Input not found: {spec.input_path}")
            
            spec.output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(spec.input_path, spec.output_path)
            
            return RefinementResult(
                success=True,
                output_path=spec.output_path,
                method_used=RefinementMethod.PASSTHROUGH,
                status=RefinementStatus.SKIPPED,
                processing_time_sec=time.time() - start_time,
                warnings=["Used passthrough (no refinement applied)"],
            )
            
        except Exception as e:
            return RefinementResult.failed(str(e))
    
    async def health_check(self) -> bool:
        """Passthrough is always healthy."""
        return True
    
    def estimate_time(self, spec: RefinementSpec) -> float:
        """Passthrough is essentially instant."""
        return 0.5  # Just file copy time


# =============================================================================
# REFINER FACTORY
# =============================================================================

class RefinerFactory:
    """
    Factory for creating refiners with automatic fallback.
    
    Tries refinement methods in order of quality and falls back
    if the preferred method isn't available.
    
    Usage:
        factory = RefinerFactory(comfy_host="http://localhost:8188")
        refiner = await factory.get_refiner()
        result = await refiner.refine(spec)
    """
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        output_dir: Path = Path("./workspace/video/refined"),
        preferred_method: Optional[RefinementMethod] = None,
    ):
        """
        Initialize the factory.
        
        Args:
            comfy_host: ComfyUI server URL (None = passthrough only)
            output_dir: Where to save refined videos
            preferred_method: Preferred method (None = best available)
        """
        self.comfy_host = comfy_host
        self.output_dir = Path(output_dir)
        self.preferred_method = preferred_method
        
        # Workflow name mapping (without .json extension)
        # Note: FREELONG_PLUS uses vid2vid_temporal as the underlying workflow
        # (true FreeLong++ would need custom ComfyUI nodes - this is a semantic alias)
        self._workflow_names = {
            RefinementMethod.FREELONG_PLUS: "refine_vid2vid_temporal",  # Best available
            RefinementMethod.VID2VID_TEMPORAL: "refine_vid2vid_temporal",
            RefinementMethod.VID2VID_SIMPLE: "refine_vid2vid_simple",
        }
        
        self._refiner_cache: Dict[RefinementMethod, BaseRefiner] = {}
    
    async def get_refiner(
        self,
        method: Optional[RefinementMethod] = None,
    ) -> BaseRefiner:
        """
        Get a refiner, with automatic fallback.
        
        Args:
            method: Specific method to use (None = best available)
            
        Returns:
            A refiner instance ready to use
        """
        target_method = method or self.preferred_method
        
        # Try methods in order of preference
        methods_to_try = self._get_method_priority(target_method)
        
        for m in methods_to_try:
            refiner = await self._try_get_refiner(m)
            if refiner and await refiner.health_check():
                logger.info(f"Using refinement method: {m.value}")
                return refiner
        
        # Fall back to passthrough
        logger.warning("No refinement methods available, using passthrough")
        return PassthroughRefiner(self.output_dir)
    
    def _get_method_priority(self, preferred: Optional[RefinementMethod]) -> List[RefinementMethod]:
        """Get methods to try in priority order."""
        all_methods = [
            RefinementMethod.FREELONG_PLUS,
            RefinementMethod.VID2VID_TEMPORAL,
            RefinementMethod.VID2VID_SIMPLE,
            RefinementMethod.PASSTHROUGH,
        ]
        
        if preferred and preferred != RefinementMethod.PASSTHROUGH:
            # Put preferred first, then others
            methods = [preferred]
            methods.extend(m for m in all_methods if m != preferred)
            return methods
        
        return all_methods
    
    async def _try_get_refiner(self, method: RefinementMethod) -> Optional[BaseRefiner]:
        """Try to create a refiner for a method."""
        if method in self._refiner_cache:
            return self._refiner_cache[method]
        
        if method == RefinementMethod.PASSTHROUGH:
            refiner = PassthroughRefiner(self.output_dir)
            self._refiner_cache[method] = refiner
            return refiner
        
        # Check if we have ComfyUI configured
        if not self.comfy_host:
            return None
        
        workflow_name = self._workflow_names.get(method)
        if not workflow_name:
            return None
        
        try:
            refiner = ComfyRefiner(
                comfy_host=self.comfy_host,
                workflow_name=workflow_name,
                method=method,
                output_dir=self.output_dir,
            )
            self._refiner_cache[method] = refiner
            return refiner
        except Exception as e:
            logger.debug(f"Failed to create {method.value} refiner: {e}")
            return None
    
    async def list_available_methods(self) -> List[RefinementMethod]:
        """List all methods that are currently available."""
        available = []
        
        for method in RefinementMethod:
            refiner = await self._try_get_refiner(method)
            if refiner and await refiner.health_check():
                available.append(method)
        
        return available


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def refine_video(
    input_path: Path,
    output_path: Path,
    shot_id: str = "unknown",
    comfy_host: Optional[str] = None,
    method: Optional[RefinementMethod] = None,
    quality: RefinementQuality = RefinementQuality.STANDARD,
    denoise_strength: float = 0.5,
) -> RefinementResult:
    """
    Convenience function to refine a video.
    
    Args:
        input_path: Path to input video
        output_path: Where to save refined video
        shot_id: Shot identifier for logging
        comfy_host: ComfyUI server (None = passthrough)
        method: Refinement method (None = auto)
        quality: Quality preset
        denoise_strength: Denoising strength (0-1)
        
    Returns:
        RefinementResult with path to refined video
    """
    factory = RefinerFactory(comfy_host=comfy_host)
    refiner = await factory.get_refiner(method)
    
    spec = RefinementSpec(
        input_path=input_path,
        output_path=output_path,
        shot_id=shot_id,
        method=method,
        quality=quality,
        denoise_strength=denoise_strength,
    )
    
    return await refiner.refine(spec)


# =============================================================================
# BATCH PROCESSING
# =============================================================================

async def refine_batch(
    specs: List[RefinementSpec],
    comfy_host: Optional[str] = None,
    max_concurrent: int = 2,
    progress_callback: Optional[Callable[[str, RefinementProgress], None]] = None,
) -> Dict[str, RefinementResult]:
    """
    Refine multiple videos with controlled concurrency.
    
    Args:
        specs: List of refinement specifications
        comfy_host: ComfyUI server URL
        max_concurrent: Maximum concurrent refinements
        progress_callback: Callback receiving (shot_id, progress)
        
    Returns:
        Dict mapping shot_id to RefinementResult
    """
    factory = RefinerFactory(comfy_host=comfy_host)
    refiner = await factory.get_refiner()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def refine_one(spec: RefinementSpec) -> tuple[str, RefinementResult]:
        async with semaphore:
            def shot_progress(p: RefinementProgress):
                if progress_callback:
                    progress_callback(spec.shot_id, p)
            
            result = await refiner.refine(spec, shot_progress)
            return spec.shot_id, result
    
    tasks = [refine_one(spec) for spec in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for i, result in enumerate(results):
        shot_id = specs[i].shot_id
        if isinstance(result, Exception):
            output[shot_id] = RefinementResult.failed(str(result))
        else:
            output[result[0]] = result[1]
    
    return output