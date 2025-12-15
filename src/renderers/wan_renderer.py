"""
Continuum Engine - Wan 2.x Renderer

Concrete renderer implementation using Wan 2.1 (or compatible models like
HunyuanVideo, Mochi) via ComfyUI on cloud GPUs.

This is the "Standard Lane" renderer â€” OSS, cost-effective, full control.

Design Principles:
1. Translate JobSpec to ComfyUI workflow parameters
2. Handle the full lifecycle: connect â†’ upload â†’ generate â†’ download
3. Support graceful degradation (LoRA â†’ IP-Adapter â†’ prompt-only)
4. Track costs and timing for budget management
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import shutil
import tempfile

from .base import (
    BaseRenderer,
    JobSpec,
    RenderResult,
    RenderProgress,
    RendererType,
    RenderQuality,
    RenderError,
    RenderTimeoutError,
    RenderBackendError,
    RenderConfigError,
    CharacterRef,
    register_renderer,
)
from ..comfy_client import (
    ComfyClient,
    ComfyJob,
    ComfyError,
    ComfyConnectionError,
    ComfyTimeoutError,
    ComfyJobError,
    WorkflowLoader,
    GenerationParams,
    CharacterParams,
    merge_params,
)
from ..core.config import get_config
from ..core.error_recovery import (
    DegradationLadder,
    retry_async,
    RetryConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# COST CONSTANTS
# =============================================================================

# Cost estimates for cloud GPU rendering (USD)
# Based on typical A100 pricing ~$1.50/hr
COST_PER_FRAME_BASE = 0.001  # ~$0.001 per frame base cost
COST_PER_FRAME_HIGH_QUALITY = 0.002  # Higher quality = more steps = more cost
COST_PER_LORA_LOAD = 0.01  # Small overhead for LoRA loading
COST_PER_UPLOAD_MB = 0.0001  # Negligible upload cost

# Time estimates (seconds)
TIME_PER_FRAME_BASE = 0.5  # ~0.5s per frame on A100
TIME_PER_FRAME_DRAFT = 0.25  # Draft quality is faster
TIME_PER_FRAME_HIGH = 1.0  # High quality takes longer
TIME_OVERHEAD_CONNECTION = 5.0  # Connection setup
TIME_OVERHEAD_UPLOAD = 2.0  # File uploads


# =============================================================================
# WAN RENDERER
# =============================================================================

@register_renderer(RendererType.WAN)
class WanRenderer(BaseRenderer):
    """
    Renderer using Wan 2.x (or compatible) via ComfyUI.
    
    This is the primary "Standard Lane" renderer for cost-effective
    video generation with full control over the pipeline.
    
    Usage:
        renderer = WanRenderer()
        await renderer.initialize()
        
        job = JobSpec(
            prompt="A woman walking through a kitchen",
            duration_sec=4.0,
            character_refs=[CharacterRef(entity_id="alice", ...)]
        )
        
        result = await renderer.generate(job)
        print(f"Output: {result.video_path}")
        
        await renderer.shutdown()
    
    Or as context manager:
        async with WanRenderer() as renderer:
            result = await renderer.generate(job)
    """
    
    # Default workflow templates for different scenarios
    DEFAULT_WORKFLOW = "pass1_structural"
    WORKFLOW_WITH_LORA = "pass1_structural_lora"
    WORKFLOW_WITH_IPADAPTER = "pass1_structural_ipadapter"
    WORKFLOW_IMG2VID = "pass1_img2vid"
    
    # Supported features
    SUPPORTED_FEATURES = {
        "init_frame",
        "lora",
        "ip_adapter",
        "controlnet",
        "long_video",  # Via StreamingT2V
    }
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        workflows_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the Wan renderer.
        
        Args:
            comfy_host: ComfyUI WebSocket URL (uses config if not provided)
            workflows_dir: Directory containing workflow JSONs
            output_dir: Where to save downloaded outputs
        """
        super().__init__(RendererType.WAN)
        
        config = get_config()
        
        self.comfy_host = comfy_host or config.comfyui.host
        self.workflows_dir = workflows_dir or config.paths.workflows_dir
        self.output_dir = output_dir or config.paths.output_dir
        self.timeout_sec = config.comfyui.timeout_sec
        
        # Will be initialized in initialize()
        self._client: Optional[ComfyClient] = None
        self._loader: Optional[WorkflowLoader] = None
        self._initialized = False
    
    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------
    
    async def initialize(self) -> None:
        """Initialize ComfyUI connection and workflow loader."""
        if self._initialized:
            return
        
        logger.info(f"Initializing WanRenderer (host={self.comfy_host})")
        
        # Create workflow loader
        self._loader = WorkflowLoader(self.workflows_dir)
        
        # Create and connect ComfyUI client
        self._client = ComfyClient(host=self.comfy_host)
        await self._client.connect()
        
        self._initialized = True
        logger.info("WanRenderer initialized successfully")
    
    async def shutdown(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.disconnect()
            self._client = None
        
        self._initialized = False
        logger.info("WanRenderer shut down")
    
    async def __aenter__(self) -> "WanRenderer":
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.shutdown()
    
    # -------------------------------------------------------------------------
    # ABSTRACT METHOD IMPLEMENTATIONS
    # -------------------------------------------------------------------------
    
    async def generate(
        self,
        job: JobSpec,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> RenderResult:
        """
        Generate video from job specification.
        
        Workflow:
        1. Ensure initialized
        2. Upload any required files (init_frame, refs)
        3. Select appropriate workflow template
        4. Inject parameters
        5. Submit to ComfyUI
        6. Wait for completion
        7. Download output
        8. Return result
        """
        start_time = time.time()
        
        # Ensure we're initialized
        if not self._initialized:
            await self.initialize()
        
        self._progress_callback = progress_callback
        
        try:
            # Stage 1: Preparation
            self._report_progress("preparing", 0.0, "Preparing job...", callback=progress_callback)
            
            # Upload files if needed
            uploaded_files = await self._upload_job_files(job)
            
            # Stage 2: Build workflow
            self._report_progress("building", 0.1, "Building workflow...", callback=progress_callback)
            
            workflow = await self._build_workflow(job, uploaded_files)
            
            # Stage 3: Submit job
            self._report_progress("submitting", 0.2, "Submitting to ComfyUI...", callback=progress_callback)
            
            comfy_job = await self._client.submit_workflow(workflow)
            logger.info(f"Submitted job {comfy_job.prompt_id}")
            
            # Stage 4: Wait for completion
            def comfy_progress_adapter(comfy_progress: Dict):
                """Adapt ComfyUI progress to our format."""
                value = comfy_progress.get("value", 0)
                max_val = comfy_progress.get("max", 100)
                progress = 0.2 + (0.7 * value / max_val) if max_val > 0 else 0.5
                self._report_progress(
                    "generating",
                    progress,
                    f"Generating frames ({value}/{max_val})...",
                    callback=progress_callback
                )
            
            completed_job = await self._client.wait_for_completion(
                comfy_job.prompt_id,
                timeout_sec=self.timeout_sec,
                progress_callback=comfy_progress_adapter
            )
            
            # Stage 5: Download output
            self._report_progress("downloading", 0.9, "Downloading output...", callback=progress_callback)
            
            output_path = await self._download_output(completed_job, job)
            
            # Stage 6: Build result
            self._report_progress("complete", 1.0, "Complete!", callback=progress_callback)
            
            elapsed = time.time() - start_time
            
            result = RenderResult(
                video_path=output_path,
                frame_count=job.frame_count,
                fps=job.fps,
                duration_sec=job.duration_sec,
                resolution=(job.width, job.height),
                renderer_type=self.renderer_type,
                render_time_sec=elapsed,
                cost_estimate=self.estimate_cost(job),
                metadata={
                    "prompt_id": completed_job.prompt_id,
                    "workflow_used": self._select_workflow_template(job),
                    "comfy_outputs": completed_job.outputs,
                }
            )
            
            logger.info(
                f"Render complete: {output_path} "
                f"({result.frame_count} frames, {elapsed:.1f}s, ~${result.cost_estimate:.3f})"
            )
            
            return result
            
        except ComfyTimeoutError as e:
            raise RenderTimeoutError(f"Generation timed out: {e}", job) from e
        except ComfyJobError as e:
            raise RenderBackendError(f"ComfyUI job failed: {e}", job) from e
        except ComfyConnectionError as e:
            raise RenderBackendError(f"ComfyUI connection error: {e}", job) from e
        except ComfyError as e:
            raise RenderError(f"ComfyUI error: {e}", job) from e
    
    async def health_check(self) -> bool:
        """Check if ComfyUI server is reachable."""
        try:
            if self._client and self._initialized:
                return await self._client.health_check()
            
            # Create temporary client for health check
            async with ComfyClient(host=self.comfy_host) as client:
                return await client.health_check()
                
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
    
    def estimate_cost(self, job: JobSpec) -> float:
        """Estimate cost in USD for this job."""
        frames = job.frame_count
        
        # Base frame cost
        if job.quality == RenderQuality.DRAFT:
            cost = frames * COST_PER_FRAME_BASE * 0.5
        elif job.quality == RenderQuality.HIGH:
            cost = frames * COST_PER_FRAME_HIGH_QUALITY
        else:
            cost = frames * COST_PER_FRAME_BASE
        
        # Add LoRA overhead if used
        for char_ref in job.character_refs:
            if char_ref.has_lora():
                cost += COST_PER_LORA_LOAD
        
        # Add upload costs (estimate)
        if job.has_init_frame:
            cost += COST_PER_UPLOAD_MB * 2  # Assume ~2MB image
        
        return round(cost, 4)
    
    def estimate_time(self, job: JobSpec) -> float:
        """Estimate render time in seconds."""
        frames = job.frame_count
        
        # Per-frame time based on quality
        if job.quality == RenderQuality.DRAFT:
            time_per_frame = TIME_PER_FRAME_DRAFT
        elif job.quality == RenderQuality.HIGH:
            time_per_frame = TIME_PER_FRAME_HIGH
        else:
            time_per_frame = TIME_PER_FRAME_BASE
        
        # Total time
        total = (
            TIME_OVERHEAD_CONNECTION +
            TIME_OVERHEAD_UPLOAD +
            (frames * time_per_frame)
        )
        
        return round(total, 1)
    
    def supports_feature(self, feature: str) -> bool:
        """Check if this renderer supports a feature."""
        return feature in self.SUPPORTED_FEATURES
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get detailed capability info."""
        return {
            "renderer_type": self.renderer_type.value,
            "features": list(self.SUPPORTED_FEATURES),
            "max_duration_sec": 60,  # With StreamingT2V
            "max_resolution": (1920, 1080),
            "supported_fps": [8, 12, 16, 24],
            "default_fps": 12,
            "models": ["wan2.1", "hunyuan", "mochi"],
        }
    
    # -------------------------------------------------------------------------
    # INTERNAL METHODS
    # -------------------------------------------------------------------------
    
    async def _upload_job_files(self, job: JobSpec) -> Dict[str, str]:
        """
        Upload any files needed for the job.
        
        Returns dict mapping local path to server filename.
        """
        uploaded = {}
        
        # Upload init frame if provided
        if job.has_init_frame:
            logger.debug(f"Uploading init frame: {job.init_frame}")
            result = await self._client.upload_file(job.init_frame)
            uploaded[str(job.init_frame)] = result["name"]
        
        # Upload face references for characters
        for char_ref in job.character_refs:
            for face_ref in char_ref.face_refs:
                if face_ref.exists():
                    logger.debug(f"Uploading face ref: {face_ref}")
                    result = await self._client.upload_file(face_ref)
                    uploaded[str(face_ref)] = result["name"]
        
        # Upload environment references
        for loc_ref in job.location_refs:
            for ref_img in loc_ref.ref_images:
                if ref_img.exists():
                    logger.debug(f"Uploading location ref: {ref_img}")
                    result = await self._client.upload_file(ref_img)
                    uploaded[str(ref_img)] = result["name"]
        
        return uploaded
    
    def _select_workflow_template(self, job: JobSpec) -> str:
        """Select the appropriate workflow template for this job."""
        # Check for init frame (img2vid)
        if job.has_init_frame:
            return self.WORKFLOW_IMG2VID
        
        # Check for character identity method
        if job.character_refs:
            char = job.character_refs[0]  # Primary character
            if char.has_lora():
                return self.WORKFLOW_WITH_LORA
            elif char.has_face_refs():
                return self.WORKFLOW_WITH_IPADAPTER
        
        # Default workflow
        return self.DEFAULT_WORKFLOW
    
    async def _build_workflow(
        self,
        job: JobSpec,
        uploaded_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Build the ComfyUI workflow from job spec.
        
        Translates JobSpec to workflow parameters and injects them
        into the appropriate template.
        """
        # Select template
        template_name = self._select_workflow_template(job)
        
        # Build base parameters
        params = self._build_generation_params(job)
        
        # Add character parameters
        if job.character_refs:
            char_params = self._build_character_params(job.character_refs[0], uploaded_files)
            params = merge_params(params, char_params)
        
        # Add environment parameters
        if job.location_refs:
            loc = job.location_refs[0]
            params["LOCATION_NAME"] = loc.name
            if loc.ref_images and str(loc.ref_images[0]) in uploaded_files:
                params["ENVIRONMENT_REF"] = uploaded_files[str(loc.ref_images[0])]
        
        # Add init frame if present
        if job.has_init_frame and str(job.init_frame) in uploaded_files:
            params["INIT_IMAGE"] = uploaded_files[str(job.init_frame)]
        
        # Apply quality preset adjustments
        quality_params = self._apply_quality_preset(job)
        params.update({
            "STEPS": quality_params["steps"],
            "CFG_SCALE": quality_params["cfg_scale"],
        })
        
        # Add any renderer-specific overrides
        params.update(job.renderer_config)
        
        # Load template and inject
        try:
            workflow = self._loader.load_and_inject(
                template_name,
                params,
                strict=False,  # Allow missing optional placeholders
                validate=True
            )
        except FileNotFoundError:
            # Fall back to default if specific template not found
            logger.warning(f"Template '{template_name}' not found, using default")
            workflow = self._loader.load_and_inject(
                self.DEFAULT_WORKFLOW,
                params,
                strict=False,
                validate=True
            )
        
        return workflow
    
    def _build_generation_params(self, job: JobSpec) -> Dict[str, Any]:
        """Build generation parameters from JobSpec."""
        return {
            "POSITIVE_PROMPT": job.prompt,
            "NEGATIVE_PROMPT": job.negative_prompt,
            "SEED": job.seed,
            "WIDTH": job.width,
            "HEIGHT": job.height,
            "FPS": job.fps,
            "FRAMES": job.frame_count,
            "CFG_SCALE": job.cfg_scale,
            "STEPS": job.steps,
            "DENOISE": job.denoise,
            "OUTPUT_PREFIX": f"continuum_{int(time.time())}",
        }
    
    def _build_character_params(
        self,
        char_ref: CharacterRef,
        uploaded_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """Build character identity parameters."""
        params = {
            "CHARACTER_NAME": char_ref.name,
        }
        
        # Add LoRA if available
        if char_ref.has_lora():
            params["LORA_PATH"] = str(char_ref.lora_path)
            params["CHARACTER_LORA"] = str(char_ref.lora_path)
            params["LORA_STRENGTH"] = char_ref.lora_strength
        
        # Add face references
        for i, face_ref in enumerate(char_ref.face_refs[:3], 1):
            key = str(face_ref)
            if key in uploaded_files:
                params[f"FACE_REF_{i}"] = uploaded_files[key]
        
        # Add description for prompt enhancement
        if char_ref.description:
            params["CHARACTER_DESCRIPTION"] = char_ref.description
        
        return params
    
    async def _download_output(self, job: ComfyJob, spec: JobSpec) -> Path:
        """
        Download the output video from ComfyUI.
        
        Finds the video output in job results and downloads it.
        """
        # Find video output in job outputs
        video_filename = None
        video_subfolder = ""
        
        for node_id, outputs in job.outputs.items():
            # Look for video outputs (gifs, mp4s, etc.)
            if isinstance(outputs, dict):
                for output_type in ["gifs", "videos", "images"]:
                    if output_type in outputs:
                        items = outputs[output_type]
                        if items and len(items) > 0:
                            video_filename = items[0].get("filename")
                            video_subfolder = items[0].get("subfolder", "")
                            break
            if video_filename:
                break
        
        if not video_filename:
            raise RenderError(f"No output found in job results: {job.outputs}", spec)
        
        # Create output path
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / video_filename
        
        # Download
        await self._client.download_output(
            filename=video_filename,
            subfolder=video_subfolder,
            file_type="output",
            save_path=output_path
        )
        
        if not output_path.exists():
            raise RenderError(f"Download failed, file not found: {output_path}", spec)
        
        return output_path


# =============================================================================
# MOCK RENDERER (FOR TESTING)
# =============================================================================

@register_renderer(RendererType.MOCK)
class MockRenderer(BaseRenderer):
    """
    Mock renderer for testing without GPU.
    
    Returns fake results immediately. Useful for:
    - Unit testing
    - UI development
    - Integration testing
    """
    
    def __init__(self, delay_sec: float = 0.5):
        """
        Initialize mock renderer.
        
        Args:
            delay_sec: Simulated delay per frame
        """
        super().__init__(RendererType.MOCK)
        self.delay_sec = delay_sec
    
    async def generate(
        self,
        job: JobSpec,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> RenderResult:
        """Generate fake output."""
        start = time.time()
        
        # Simulate progress
        total_steps = 10
        for i in range(total_steps):
            if progress_callback:
                progress_callback(RenderProgress(
                    stage="mock_generating",
                    progress=i / total_steps,
                    message=f"Mock step {i+1}/{total_steps}"
                ))
            await asyncio.sleep(self.delay_sec / total_steps)
        
        # Create a dummy output file
        output_dir = get_config().paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / f"mock_{int(time.time())}.mp4"
        output_path.write_text("MOCK VIDEO CONTENT")  # Fake file
        
        return RenderResult(
            video_path=output_path,
            frame_count=job.frame_count,
            fps=job.fps,
            duration_sec=job.duration_sec,
            resolution=(job.width, job.height),
            renderer_type=self.renderer_type,
            render_time_sec=time.time() - start,
            cost_estimate=0.0,
            metadata={"mock": True}
        )
    
    async def health_check(self) -> bool:
        """Always healthy."""
        return True
    
    def estimate_cost(self, job: JobSpec) -> float:
        """Free!"""
        return 0.0
    
    def estimate_time(self, job: JobSpec) -> float:
        """Based on configured delay."""
        return self.delay_sec
    
    def supports_feature(self, feature: str) -> bool:
        """Supports everything (it's mock)."""
        return True