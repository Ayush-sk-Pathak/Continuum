"""
Continuum Engine - RIFE Frame Interpolator

Upscales video frame rate using AI-based frame interpolation.
Primary use: 12fps Ã¢â€ â€™ 24fps to halve GPU generation cost while
maintaining cinematic smoothness.

The Problem:
    Generating video at 24fps costs 2x more GPU time than 12fps.
    But 12fps looks choppy and unprofessional.

The Solution:
    Generate at 12fps, then use RIFE (Real-Time Intermediate Flow
    Estimation) to synthesize the in-between frames. The result
    looks like native 24fps at roughly half the generation cost.

Architecture Position (FINAL STEP):
    Pass 1 (Structure) Ã¢â€ â€™ Audit Ã¢â€ â€™ Pass 2 (Refinement) Ã¢â€ â€™ Lip Sync Ã¢â€ â€™ **RIFE** Ã¢â€ â€™ Final
    
Why RIFE is Last:
    - Lip sync may introduce minor frame-level jitters
    - RIFE smooths these out during interpolation
    - Running RIFE earlier would waste compute (interpolating frames
      that lip sync will modify anyway)

Supported Modes:
    - 2x: 12fps Ã¢â€ â€™ 24fps (default, cinematic)
    - 2.5x: 12fps Ã¢â€ â€™ 30fps (broadcast)
    - 4x: 12fps Ã¢â€ â€™ 48fps (smooth/slow-mo ready)

Design Principles:
    1. Workflow-agnostic: Actual ComfyUI workflow is external JSON
    2. Degradation-ready: RIFE ComfyUI Ã¢â€ â€™ FFmpeg minterpolate Ã¢â€ â€™ Passthrough
    3. Async-first: All interpolation is async (GPU-bound)
    4. Preserves duration: Output duration matches input exactly
"""

import asyncio
import logging
import shutil
import subprocess
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

class InterpolationMethod(str, Enum):
    """
    Available interpolation methods, in order of quality.
    """
    RIFE_COMFY = "rife_comfy"          # Best: RIFE via ComfyUI (GPU)
    RIFE_NCNN = "rife_ncnn"            # Good: RIFE-ncnn standalone (GPU)
    FFMPEG_MINTERPOLATE = "ffmpeg_minterpolate"  # Basic: FFmpeg motion interpolation (CPU)
    PASSTHROUGH = "passthrough"        # None: Just copy (testing/fallback)


class InterpolationStatus(str, Enum):
    """Status of an interpolation job."""
    PENDING = "pending"
    ANALYZING = "analyzing"      # Analyzing motion/optical flow
    INTERPOLATING = "interpolating"  # Generating new frames
    ENCODING = "encoding"        # Encoding output video
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"          # Passthrough mode


class TargetFrameRate(int, Enum):
    """Common target frame rates."""
    FPS_24 = 24    # Cinematic (default)
    FPS_30 = 30    # Broadcast/web
    FPS_48 = 48    # High frame rate / slow-mo ready
    FPS_60 = 60    # Gaming / ultra-smooth


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class InterpolationSpec:
    """
    Specification for a frame interpolation job.
    
    Attributes:
        input_path: Path to input video (e.g., 12fps from lip sync)
        output_path: Where to write interpolated video
        shot_id: Identifier for tracking
        source_fps: Input frame rate (auto-detected if None)
        target_fps: Desired output frame rate
        method: Which interpolation method to use (None = auto-select)
        scene_detect: Enable scene detection to avoid interpolating across cuts
        denoise: Apply light denoising during interpolation
    """
    input_path: Path
    output_path: Path
    shot_id: str
    source_fps: Optional[float] = None  # Auto-detect if not specified
    target_fps: int = 24
    method: Optional[InterpolationMethod] = None  # None = auto-select
    scene_detect: bool = True  # Avoid artifacts at scene boundaries
    denoise: bool = False      # Light temporal denoising
    
    def __post_init__(self):
        if isinstance(self.input_path, str):
            self.input_path = Path(self.input_path)
        if isinstance(self.output_path, str):
            self.output_path = Path(self.output_path)
    
    @property
    def multiplier(self) -> float:
        """Calculate the interpolation multiplier."""
        if self.source_fps and self.source_fps > 0:
            return self.target_fps / self.source_fps
        return 2.0  # Default assumption: 12fps Ã¢â€ â€™ 24fps


@dataclass
class InterpolationResult:
    """
    Result of a frame interpolation operation.
    
    Attributes:
        success: Whether interpolation completed
        output_path: Path to interpolated video
        method_used: Which method was actually used
        status: Final status
        source_fps: Detected source frame rate
        target_fps: Actual output frame rate
        source_frames: Number of input frames
        output_frames: Number of output frames
        processing_time_sec: How long interpolation took
        error: Error message if failed
        warnings: Non-fatal issues
    """
    success: bool
    output_path: Optional[Path] = None
    method_used: InterpolationMethod = InterpolationMethod.PASSTHROUGH
    status: InterpolationStatus = InterpolationStatus.PENDING
    source_fps: float = 0.0
    target_fps: float = 0.0
    source_frames: int = 0
    output_frames: int = 0
    processing_time_sec: float = 0.0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def failed(cls, error: str, method: InterpolationMethod = InterpolationMethod.PASSTHROUGH) -> "InterpolationResult":
        """Factory for a failed result."""
        return cls(
            success=False,
            method_used=method,
            status=InterpolationStatus.FAILED,
            error=error,
        )
    
    @classmethod
    def skipped(cls, output_path: Path, reason: str) -> "InterpolationResult":
        """Factory for a skipped/passthrough result."""
        return cls(
            success=True,
            output_path=output_path,
            method_used=InterpolationMethod.PASSTHROUGH,
            status=InterpolationStatus.SKIPPED,
            warnings=[f"Interpolation skipped: {reason}"],
        )


@dataclass
class InterpolationProgress:
    """Progress update during interpolation."""
    stage: str
    progress: float  # 0.0 to 1.0
    current_frame: int = 0
    total_frames: int = 0
    message: str = ""
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    
    @property
    def percent(self) -> int:
        return int(self.progress * 100)


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseInterpolator(ABC):
    """
    Abstract base class for frame interpolators.
    
    Implementations can use different backends:
    - ComfyUI-based (RIFE nodes)
    - Standalone RIFE-ncnn
    - FFmpeg minterpolate
    """
    
    method: InterpolationMethod
    
    def __init__(
        self,
        output_dir: Path,
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the interpolator.
        
        Args:
            output_dir: Default directory for output videos
            temp_dir: Directory for temporary files
        """
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir()) / "continuum_interp"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    async def interpolate(
        self,
        spec: InterpolationSpec,
        progress_callback: Optional[Callable[[InterpolationProgress], None]] = None,
    ) -> InterpolationResult:
        """
        Interpolate a video to a higher frame rate.
        
        Args:
            spec: Interpolation specification
            progress_callback: Optional callback for progress updates
            
        Returns:
            InterpolationResult with path to interpolated video
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the interpolator backend is available.
        
        Returns:
            True if ready to process
        """
        pass
    
    def estimate_time(self, spec: InterpolationSpec) -> float:
        """
        Estimate processing time in seconds.
        
        RIFE is very fast - typically 50-100+ fps on modern GPUs.
        """
        # Rough estimate: RIFE processes at ~60fps on typical GPU
        # So a 12fps * 10sec = 120 frames video takes ~2 seconds
        estimated_frames = 12 * 10  # Assume 10 second clip at 12fps
        rife_fps = 60  # Conservative estimate
        return estimated_frames / rife_fps
    
    def estimate_cost(self, spec: InterpolationSpec) -> float:
        """
        Estimate cost in USD.
        
        RIFE is cheap because it's fast.
        """
        time_sec = self.estimate_time(spec)
        hourly_rate = 0.50  # GPU cost
        return (time_sec / 3600) * hourly_rate
    
    async def shutdown(self) -> None:
        """
        Release resources held by the interpolator.
        
        Default implementation does nothing. Override in subclasses
        that hold resources like ComfyClient connections.
        
        Called by main.py during pipeline shutdown.
        """
        pass  # No-op by default; subclasses override if needed
    
    async def _detect_fps(self, video_path: Path) -> float:
        """Detect the frame rate of a video using FFprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path)
        ]
        
        try:
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True)
            )
            
            if process.returncode != 0:
                logger.warning(f"FFprobe failed, assuming 12fps: {process.stderr}")
                return 12.0
            
            import json
            data = json.loads(process.stdout)
            
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    # Parse frame rate (e.g., "24000/1001" or "24/1")
                    fps_str = stream.get("r_frame_rate", "12/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        return float(num) / float(den)
                    return float(fps_str)
            
            return 12.0  # Default assumption
            
        except Exception as e:
            logger.warning(f"FPS detection failed, assuming 12fps: {e}")
            return 12.0
    
    async def _count_frames(self, video_path: Path) -> int:
        """Count frames in a video."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-count_frames",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames",
            "-print_format", "csv=p=0",
            str(video_path)
        ]
        
        try:
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True)
            )
            
            if process.returncode == 0 and process.stdout.strip():
                return int(process.stdout.strip())
            return 0
            
        except Exception:
            return 0


# =============================================================================
# COMFYUI RIFE IMPLEMENTATION
# =============================================================================

class ComfyRIFEInterpolator(BaseInterpolator):
    """
    Frame interpolator using RIFE via ComfyUI.
    
    This is the highest quality option, using the RIFE model
    through ComfyUI's VHS or similar video nodes.
    
    Requirements:
        - ComfyUI with RIFE nodes installed
        - rife_interpolation workflow in workflows directory
    """
    
    method = InterpolationMethod.RIFE_COMFY
    
    def __init__(
        self,
        comfy_host: str,
        workflow_name: str = "rife_interpolation",
        output_dir: Path = Path("./workspace/video/interpolated"),
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the ComfyUI RIFE interpolator.
        
        Args:
            comfy_host: ComfyUI server URL
            workflow_name: Name of the RIFE workflow
            output_dir: Where to save interpolated videos
            temp_dir: Temporary file directory
        """
        super().__init__(output_dir, temp_dir)
        
        self.comfy_host = comfy_host
        self.workflow_name = workflow_name
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
    
    async def _load_workflow(self):
        """Load the RIFE workflow template."""
        if self._template is None:
            try:
                from ..comfy_client.workflow_loader import WorkflowLoader
                if self._loader is None:
                    self._loader = WorkflowLoader()
                self._template = self._loader.load(self.workflow_name)
            except Exception as e:
                raise RuntimeError(f"Failed to load workflow '{self.workflow_name}': {e}")
        return self._template
    
    async def _download_output(self, client, job, output_path: Path) -> Path:
        """
        Download the interpolated video from ComfyUI server.
        
        Finds the video output in job results and downloads it to output_path.
        Pattern follows wan_renderer._download_output() which is proven to work.
        
        Args:
            client: Connected ComfyClient instance
            job: Completed ComfyJob with outputs
            output_path: Where to save the downloaded video
            
        Returns:
            Path to the downloaded video
            
        Raises:
            RuntimeError: If no video output found in job results
        """
        # Find video output in job outputs
        # ComfyUI stores outputs as: {node_id: {output_type: [items]}}
        video_filename = None
        video_subfolder = ""
        
        for node_id, outputs in job.outputs.items():
            if isinstance(outputs, dict):
                # Look for video outputs - video_combine outputs to "gifs" typically
                for output_type in ["gifs", "videos", "images"]:
                    if output_type in outputs:
                        items = outputs[output_type]
                        if items and len(items) > 0:
                            video_filename = items[0].get("filename")
                            video_subfolder = items[0].get("subfolder", "")
                            logger.debug(
                                f"Found RIFE output: {video_filename} "
                                f"in {node_id}/{output_type}"
                            )
                            break
            if video_filename:
                break
        
        if not video_filename:
            raise RuntimeError(
                f"No video output found in RIFE job results. "
                f"Available outputs: {job.outputs}"
            )
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download the video
        logger.debug(f"Downloading interpolated video: {video_filename} -> {output_path}")
        
        await client.download_output(
            filename=video_filename,
            subfolder=video_subfolder,
            file_type="output",
            save_path=output_path
        )
        
        # Verify download succeeded
        if not output_path.exists():
            raise RuntimeError(f"Download failed, file not found: {output_path}")
        
        logger.info(f"Downloaded interpolated video: {output_path}")
        return output_path
    
    async def interpolate(
        self,
        spec: InterpolationSpec,
        progress_callback: Optional[Callable[[InterpolationProgress], None]] = None,
    ) -> InterpolationResult:
        """Interpolate video using ComfyUI RIFE."""
        start_time = time.time()
        
        def report_progress(stage: str, progress: float, message: str = ""):
            if progress_callback:
                progress_callback(InterpolationProgress(
                    stage=stage,
                    progress=progress,
                    message=message,
                    elapsed_sec=time.time() - start_time,
                ))
        
        try:
            # Validate input
            if not spec.input_path.exists():
                return InterpolationResult.failed(f"Input video not found: {spec.input_path}")
            
            report_progress("analyzing", 0.1, "Detecting frame rate...")
            
            # Detect source FPS if not specified
            source_fps = spec.source_fps or await self._detect_fps(spec.input_path)
            source_frames = await self._count_frames(spec.input_path)
            
            # Calculate multiplier
            multiplier = spec.target_fps / source_fps
            
            if multiplier <= 1.0:
                return InterpolationResult.skipped(
                    spec.output_path,
                    f"Source FPS ({source_fps}) >= target FPS ({spec.target_fps})"
                )
            
            report_progress("analyzing", 0.2, "Connecting to ComfyUI...")
            
            client = await self._get_client()
            template = await self._load_workflow()
            
            report_progress("interpolating", 0.25, "Uploading video to ComfyUI...")
            
            # Upload video to ComfyUI server (videos need to be uploaded first)
            upload_result = await client.upload_file(spec.input_path, subfolder="", file_type="input")
            remote_video_name = upload_result.get("name", spec.input_path.name)
            
            report_progress("interpolating", 0.3, "Preparing workflow...")
            
            
            # Inject parameters - must match rife_interpolation.json placeholders
            params = {
                "INPUT_VIDEO": remote_video_name,  # Use remote filename, not local path
                "MULTIPLIER": int(multiplier) if multiplier == int(multiplier) else multiplier,
                "TARGET_FPS": spec.target_fps,
            }
            inject_result = self._loader.inject(template, params)
            workflow = inject_result.workflow if hasattr(inject_result, 'workflow') else inject_result
            
            report_progress("interpolating", 0.4, "Running RIFE interpolation...")
            
            # Submit and wait using proper async pattern
            comfy_job = await client.submit_workflow(workflow)
            logger.info(f"Submitted RIFE job {comfy_job.prompt_id}")
            
            # Progress adapter for RIFE
            def rife_progress_adapter(comfy_progress):
                """Adapt ComfyUI progress to interpolation progress."""
                if isinstance(comfy_progress, dict):
                    value = comfy_progress.get("value", 0)
                    max_val = comfy_progress.get("max", 100)
                    progress = 0.4 + (0.5 * value / max_val) if max_val > 0 else 0.6
                    report_progress(
                        "interpolating",
                        progress,
                        f"Generating frames ({value}/{max_val})..."
                    )
            
            # Wait for completion with timeout
            try:
                completed_job = await client.wait_for_completion(
                    comfy_job.prompt_id,
                    timeout_sec=600,  # 10 minute timeout for interpolation
                    progress_callback=rife_progress_adapter
                )
            except Exception as e:
                return InterpolationResult.failed(f"RIFE job failed: {e}")
            
            report_progress("encoding", 0.9, "Downloading result...")
            
            # Download output
            output_path = await self._download_output(client, completed_job, spec.output_path)
            
            report_progress("completed", 1.0, "Interpolation complete")
            
            output_frames = int(source_frames * multiplier)
            
            return InterpolationResult(
                success=True,
                output_path=spec.output_path,
                method_used=self.method,
                status=InterpolationStatus.COMPLETED,
                source_fps=source_fps,
                target_fps=float(spec.target_fps),
                source_frames=source_frames,
                output_frames=output_frames,
                processing_time_sec=time.time() - start_time,
            )
            
        except Exception as e:
            logger.error(f"RIFE interpolation failed: {e}")
            return InterpolationResult.failed(str(e), self.method)
    
    async def health_check(self) -> bool:
        """Check if ComfyUI RIFE is accessible."""
        try:
            client = await self._get_client()
            return await client.health_check()
        except Exception as e:
            logger.error(f"ComfyUI RIFE health check failed: {e}")
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
                logger.debug(f"ComfyRIFEInterpolator disconnected from {self.comfy_host}")
            except Exception as e:
                logger.warning(f"Error during ComfyRIFEInterpolator shutdown: {e}")
            finally:
                self._client = None


# =============================================================================
# FFMPEG MINTERPOLATE IMPLEMENTATION (CPU FALLBACK)
# =============================================================================

class FFmpegInterpolator(BaseInterpolator):
    """
    Frame interpolator using FFmpeg's minterpolate filter.
    
    This is a CPU-based fallback when GPU interpolation isn't available.
    Quality is lower than RIFE but works everywhere FFmpeg is installed.
    
    Note: minterpolate can produce artifacts at scene boundaries.
    """
    
    method = InterpolationMethod.FFMPEG_MINTERPOLATE
    
    async def interpolate(
        self,
        spec: InterpolationSpec,
        progress_callback: Optional[Callable[[InterpolationProgress], None]] = None,
    ) -> InterpolationResult:
        """Interpolate video using FFmpeg minterpolate."""
        start_time = time.time()
        
        def report_progress(stage: str, progress: float, message: str = ""):
            if progress_callback:
                progress_callback(InterpolationProgress(
                    stage=stage,
                    progress=progress,
                    message=message,
                    elapsed_sec=time.time() - start_time,
                ))
        
        try:
            if not spec.input_path.exists():
                return InterpolationResult.failed(f"Input video not found: {spec.input_path}")
            
            report_progress("analyzing", 0.1, "Detecting frame rate...")
            
            source_fps = spec.source_fps or await self._detect_fps(spec.input_path)
            source_frames = await self._count_frames(spec.input_path)
            
            if source_fps >= spec.target_fps:
                return InterpolationResult.skipped(
                    spec.output_path,
                    f"Source FPS ({source_fps}) >= target FPS ({spec.target_fps})"
                )
            
            report_progress("interpolating", 0.2, "Running FFmpeg interpolation...")
            
            spec.output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Build FFmpeg command with minterpolate
            # mi_mode=mci gives best quality, mc_mode=aobmc for bidirectional motion comp
            filter_str = (
                f"minterpolate=fps={spec.target_fps}:mi_mode=mci:mc_mode=aobmc"
                f":me_mode=bidir:vsbmc=1"
            )
            
            # Add scene detection if enabled
            if spec.scene_detect:
                filter_str += ":scd=fdiff:scd_threshold=10"
            
            cmd = [
                "ffmpeg", "-y",
                "-i", str(spec.input_path),
                "-filter:v", filter_str,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "copy",  # Preserve audio
                str(spec.output_path)
            ]
            
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True)
            )
            
            if process.returncode != 0:
                return InterpolationResult.failed(f"FFmpeg failed: {process.stderr}")
            
            report_progress("completed", 1.0, "Interpolation complete")
            
            multiplier = spec.target_fps / source_fps
            output_frames = int(source_frames * multiplier)
            
            return InterpolationResult(
                success=True,
                output_path=spec.output_path,
                method_used=self.method,
                status=InterpolationStatus.COMPLETED,
                source_fps=source_fps,
                target_fps=float(spec.target_fps),
                source_frames=source_frames,
                output_frames=output_frames,
                processing_time_sec=time.time() - start_time,
                warnings=["Used FFmpeg minterpolate (CPU) - quality may be lower than RIFE"],
            )
            
        except Exception as e:
            logger.error(f"FFmpeg interpolation failed: {e}")
            return InterpolationResult.failed(str(e), self.method)
    
    async def health_check(self) -> bool:
        """Check if FFmpeg with minterpolate is available."""
        try:
            process = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ffmpeg", "-filters"],
                    capture_output=True,
                    text=True,
                )
            )
            return process.returncode == 0 and "minterpolate" in process.stdout
        except FileNotFoundError:
            return False


# =============================================================================
# PASSTHROUGH IMPLEMENTATION (FOR TESTING)
# =============================================================================

class PassthroughInterpolator(BaseInterpolator):
    """
    No-op interpolator that just copies input to output.
    
    Used when:
    - Testing pipeline without GPU
    - Interpolation is disabled
    - All interpolation methods fail
    - Source FPS already meets target
    """
    
    method = InterpolationMethod.PASSTHROUGH
    
    async def interpolate(
        self,
        spec: InterpolationSpec,
        progress_callback: Optional[Callable[[InterpolationProgress], None]] = None,
    ) -> InterpolationResult:
        """Just copy the input to output."""
        start_time = time.time()
        
        try:
            if not spec.input_path.exists():
                return InterpolationResult.failed(f"Input not found: {spec.input_path}")
            
            source_fps = spec.source_fps or await self._detect_fps(spec.input_path)
            
            spec.output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(spec.input_path, spec.output_path)
            
            return InterpolationResult(
                success=True,
                output_path=spec.output_path,
                method_used=InterpolationMethod.PASSTHROUGH,
                status=InterpolationStatus.SKIPPED,
                source_fps=source_fps,
                target_fps=source_fps,  # No change
                processing_time_sec=time.time() - start_time,
                warnings=["Used passthrough (no interpolation applied)"],
            )
            
        except Exception as e:
            return InterpolationResult.failed(str(e))
    
    async def health_check(self) -> bool:
        """Passthrough is always healthy."""
        return True


# =============================================================================
# INTERPOLATOR FACTORY
# =============================================================================

class InterpolatorFactory:
    """
    Factory for creating interpolators with automatic fallback.
    
    Tries interpolation methods in order of quality and falls back
    if the preferred method isn't available.
    
    Fallback order: RIFE ComfyUI Ã¢â€ â€™ FFmpeg minterpolate Ã¢â€ â€™ Passthrough
    
    Usage:
        factory = InterpolatorFactory(comfy_host="http://localhost:8188")
        interpolator = await factory.get_interpolator()
        result = await interpolator.interpolate(spec)
    """
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        output_dir: Path = Path("./workspace/video/interpolated"),
        preferred_method: Optional[InterpolationMethod] = None,
    ):
        """
        Initialize the factory.
        
        Args:
            comfy_host: ComfyUI server URL (None = CPU methods only)
            output_dir: Where to save interpolated videos
            preferred_method: Preferred method (None = best available)
        """
        self.comfy_host = comfy_host
        self.output_dir = Path(output_dir)
        self.preferred_method = preferred_method
        
        self._interpolator_cache: Dict[InterpolationMethod, BaseInterpolator] = {}
    
    async def get_interpolator(
        self,
        method: Optional[InterpolationMethod] = None,
    ) -> BaseInterpolator:
        """
        Get an interpolator, with automatic fallback.
        
        Args:
            method: Specific method to use (None = best available)
            
        Returns:
            An interpolator instance ready to use
        """
        target_method = method or self.preferred_method
        
        # Try methods in order of preference
        methods_to_try = self._get_method_priority(target_method)
        
        for m in methods_to_try:
            interpolator = await self._try_get_interpolator(m)
            if interpolator and await interpolator.health_check():
                logger.info(f"Using interpolation method: {m.value}")
                return interpolator
        
        # Fall back to passthrough
        logger.warning("No interpolation methods available, using passthrough")
        return PassthroughInterpolator(self.output_dir)
    
    def _get_method_priority(self, preferred: Optional[InterpolationMethod]) -> List[InterpolationMethod]:
        """Get methods to try in priority order."""
        all_methods = [
            InterpolationMethod.RIFE_COMFY,
            InterpolationMethod.FFMPEG_MINTERPOLATE,
            InterpolationMethod.PASSTHROUGH,
        ]
        
        if preferred and preferred != InterpolationMethod.PASSTHROUGH:
            methods = [preferred]
            methods.extend(m for m in all_methods if m != preferred)
            return methods
        
        return all_methods
    
    async def _try_get_interpolator(self, method: InterpolationMethod) -> Optional[BaseInterpolator]:
        """Try to create an interpolator for a method."""
        if method in self._interpolator_cache:
            return self._interpolator_cache[method]
        
        if method == InterpolationMethod.PASSTHROUGH:
            interp = PassthroughInterpolator(self.output_dir)
            self._interpolator_cache[method] = interp
            return interp
        
        if method == InterpolationMethod.FFMPEG_MINTERPOLATE:
            interp = FFmpegInterpolator(self.output_dir)
            self._interpolator_cache[method] = interp
            return interp
        
        if method == InterpolationMethod.RIFE_COMFY:
            if not self.comfy_host:
                return None
            try:
                interp = ComfyRIFEInterpolator(
                    comfy_host=self.comfy_host,
                    output_dir=self.output_dir,
                )
                self._interpolator_cache[method] = interp
                return interp
            except Exception as e:
                logger.debug(f"Failed to create RIFE ComfyUI interpolator: {e}")
                return None
        
        return None
    
    async def list_available_methods(self) -> List[InterpolationMethod]:
        """List all methods that are currently available."""
        available = []
        
        for method in InterpolationMethod:
            interp = await self._try_get_interpolator(method)
            if interp and await interp.health_check():
                available.append(method)
        
        return available


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def interpolate_video(
    input_path: Path,
    output_path: Path,
    shot_id: str = "unknown",
    target_fps: int = 24,
    comfy_host: Optional[str] = None,
    method: Optional[InterpolationMethod] = None,
) -> InterpolationResult:
    """
    Convenience function to interpolate a video.
    
    Args:
        input_path: Path to input video
        output_path: Where to save interpolated video
        shot_id: Shot identifier for logging
        target_fps: Desired output frame rate
        comfy_host: ComfyUI server (None = use CPU methods)
        method: Interpolation method (None = auto)
        
    Returns:
        InterpolationResult with path to interpolated video
    """
    factory = InterpolatorFactory(comfy_host=comfy_host)
    interpolator = await factory.get_interpolator(method)
    
    spec = InterpolationSpec(
        input_path=input_path,
        output_path=output_path,
        shot_id=shot_id,
        target_fps=target_fps,
        method=method,
    )
    
    return await interpolator.interpolate(spec)


# =============================================================================
# BATCH PROCESSING
# =============================================================================

async def interpolate_batch(
    specs: List[InterpolationSpec],
    comfy_host: Optional[str] = None,
    max_concurrent: int = 2,
    progress_callback: Optional[Callable[[str, InterpolationProgress], None]] = None,
) -> Dict[str, InterpolationResult]:
    """
    Interpolate multiple videos with controlled concurrency.
    
    Args:
        specs: List of interpolation specifications
        comfy_host: ComfyUI server URL
        max_concurrent: Maximum concurrent interpolations
        progress_callback: Callback receiving (shot_id, progress)
        
    Returns:
        Dict mapping shot_id to InterpolationResult
    """
    factory = InterpolatorFactory(comfy_host=comfy_host)
    interpolator = await factory.get_interpolator()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def interpolate_one(spec: InterpolationSpec) -> tuple[str, InterpolationResult]:
        async with semaphore:
            def shot_progress(p: InterpolationProgress):
                if progress_callback:
                    progress_callback(spec.shot_id, p)
            
            result = await interpolator.interpolate(spec, shot_progress)
            return spec.shot_id, result
    
    tasks = [interpolate_one(spec) for spec in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for i, result in enumerate(results):
        shot_id = specs[i].shot_id
        if isinstance(result, Exception):
            output[shot_id] = InterpolationResult.failed(str(result))
        else:
            output[result[0]] = result[1]
    
    return output