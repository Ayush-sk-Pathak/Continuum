"""
Continuum Engine - HunyuanCustom Renderer

Concrete renderer implementation using HunyuanCustom (13B params, LLaVA fusion)
via ComfyUI on cloud GPUs (4x RTX 4090 or H100).

This renderer specializes in IDENTITY PRESERVATION with 0.627 ArcFace score
(3x better than Wan VACE benchmark).

Key Differences from WanRenderer:
1. Uses <image> token in prompt for native identity injection (no IP-Adapter)
2. Uses LLaVA 8B as text encoder (not CLIP)
3. Higher VRAM requirement (80GB across 4x GPUs)
4. Different ComfyUI nodes (HyVideoSampler, HyVideoTextImageEncode, etc.)

Design Principles:
1. Mirror WanRenderer structure for maintainability
2. Leverage native identity without workarounds
3. Support multi-subject (up to 2 characters with <image> tokens)
4. Fail fast with clear error messages

Architecture Reference:
- MODEL_PIVOT.md: Migration strategy and rationale
- models.json: Model paths (hunyuan_custom section)
- workflows/hunyuan_custom/: Workflow templates
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import re

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
    merge_params,
)
from ..core.config import get_config
from ..core.model_loader import get_model_config, ModelTier

logger = logging.getLogger(__name__)


# =============================================================================
# COST CONSTANTS (HunyuanCustom on 4x RTX 4090)
# =============================================================================

# Cost estimates based on RunPod 4x RTX 4090 @ ~$2.00/hr
COST_PER_FRAME_BASE = 0.003  # ~$0.003 per frame (higher than Wan due to 4x GPU)
COST_PER_FRAME_HIGH_QUALITY = 0.005
COST_PER_UPLOAD_MB = 0.0001

# Time estimates (seconds) - HunyuanCustom is slower due to 13B params
TIME_PER_FRAME_BASE = 1.0  # ~1s per frame on 4x RTX 4090
TIME_PER_FRAME_DRAFT = 0.7
TIME_PER_FRAME_HIGH = 1.5
TIME_OVERHEAD_CONNECTION = 5.0
TIME_OVERHEAD_UPLOAD = 3.0


# =============================================================================
# HUNYUAN CUSTOM RENDERER
# =============================================================================

@register_renderer(RendererType.HUNYUAN_CUSTOM)
class HunyuanCustomRenderer(BaseRenderer):
    """
    Renderer using HunyuanCustom via ComfyUI for identity-preserving video.
    
    HunyuanCustom achieves 0.627 ArcFace score through native identity
    injection via the <image> token system, eliminating the need for
    IP-Adapter workarounds.
    
    Usage:
        renderer = HunyuanCustomRenderer()
        await renderer.initialize()
        
        job = JobSpec(
            prompt="A woman walking through a kitchen",
            duration_sec=5.0,
            character_refs=[CharacterRef(entity_id="alice", face_refs=[...])]
        )
        
        result = await renderer.generate(job)
        print(f"Output: {result.video_path}")
        
        await renderer.shutdown()
    
    Or as context manager:
        async with HunyuanCustomRenderer() as renderer:
            result = await renderer.generate(job)
    """
    
    # Workflow templates for HunyuanCustom
    # All use native <image> token for identity - no IP-Adapter variants needed
    WORKFLOW_IMG2VID = "pass1_img2vid"  # Primary I2V workflow
    WORKFLOW_T2V = "pass1_t2v"  # Text-to-video (no identity)
    
    # Supported features
    SUPPORTED_FEATURES = {
        "init_frame",
        "native_identity",  # <image> token system
        "multi_subject",    # Up to 2 characters
    }
    
    # HunyuanCustom-specific defaults (from paper/benchmarks)
    DEFAULT_CFG_SCALE = 7.5
    DEFAULT_FLOW_SHIFT = 13.0
    DEFAULT_STEPS = 30
    DEFAULT_FPS = 25
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        workflows_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the HunyuanCustom renderer.
        
        Args:
            comfy_host: ComfyUI WebSocket URL (uses config if not provided)
            workflows_dir: Directory containing workflow JSONs
            output_dir: Where to save downloaded outputs
        """
        super().__init__(RendererType.HUNYUAN_CUSTOM)
        
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
        
        logger.info(f"Initializing HunyuanCustomRenderer (host={self.comfy_host})")
        
        # Create workflow loader with hunyuan_custom model family
        # This ensures workflows are loaded from workflows/hunyuan_custom/
        self._loader = WorkflowLoader(
            workflows_dir=self.workflows_dir,
            model_family="hunyuan_custom"
        )
        
        # Create and connect ComfyUI client
        self._client = ComfyClient(host=self.comfy_host)
        await self._client.connect()
        
        self._initialized = True
        logger.info("HunyuanCustomRenderer initialized successfully")
    
    async def shutdown(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.disconnect()
            self._client = None
        
        self._initialized = False
        logger.info("HunyuanCustomRenderer shut down")
    
    async def _ensure_connected(self) -> None:
        """Ensure client is connected, reconnecting if necessary."""
        if self._client is None:
            await self.initialize()
            return
        
        try:
            if not await self._client.health_check():
                raise ConnectionError("Health check failed")
        except Exception as e:
            logger.info(f"ComfyUI connection stale ({e}), reconnecting...")
            try:
                await self._client.connect()
            except Exception as reconnect_error:
                logger.warning(f"Reconnection failed ({reconnect_error}), creating new client...")
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = ComfyClient(host=self.comfy_host)
                await self._client.connect()
    
    async def __aenter__(self) -> "HunyuanCustomRenderer":
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
        Generate video from job specification using HunyuanCustom.
        
        Workflow:
        1. Ensure initialized
        2. Upload face reference and init frame
        3. Format prompt with <image> token
        4. Build and submit workflow
        5. Wait for completion
        6. Download output
        7. Return result
        """
        start_time = time.time()
        
        if not self._initialized:
            await self.initialize()
        
        self._progress_callback = progress_callback
        
        try:
            # Stage 1: Preparation
            self._report_progress("preparing", 0.0, "Preparing job...", callback=progress_callback)
            
            uploaded_files = await self._upload_job_files(job)
            
            # Stage 2: Build workflow
            self._report_progress("building", 0.1, "Building workflow...", callback=progress_callback)
            
            workflow = await self._build_workflow(job, uploaded_files)
            
            # Stage 3: Submit job
            self._report_progress("submitting", 0.2, "Submitting to ComfyUI...", callback=progress_callback)
            
            await self._ensure_connected()
            
            comfy_job = await self._client.submit_workflow(workflow)
            logger.info(f"Submitted HunyuanCustom job {comfy_job.prompt_id}")
            
            # Stage 4: Wait for completion
            def comfy_progress_adapter(comfy_progress: Dict):
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
                    "model": "hunyuan_custom",
                }
            )
            
            logger.info(
                f"HunyuanCustom render complete: {output_path} "
                f"({result.frame_count} frames, {elapsed:.1f}s, ~${result.cost_estimate:.3f})"
            )
            
            return result
            
        except ComfyTimeoutError as e:
            raise RenderTimeoutError(f"HunyuanCustom generation timed out: {e}", job) from e
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
            
            async with ComfyClient(host=self.comfy_host) as client:
                return await client.health_check()
                
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
    
    def estimate_cost(self, job: JobSpec) -> float:
        """Estimate cost in USD for this job (4x RTX 4090 pricing)."""
        frames = job.frame_count
        
        if job.quality == RenderQuality.DRAFT:
            cost = frames * COST_PER_FRAME_BASE * 0.7
        elif job.quality == RenderQuality.HIGH:
            cost = frames * COST_PER_FRAME_HIGH_QUALITY
        else:
            cost = frames * COST_PER_FRAME_BASE
        
        # Add upload costs
        if job.has_init_frame:
            cost += COST_PER_UPLOAD_MB * 2
        for char_ref in job.character_refs:
            cost += COST_PER_UPLOAD_MB * len(char_ref.face_refs)
        
        return round(cost, 4)
    
    def estimate_time(self, job: JobSpec) -> float:
        """Estimate render time in seconds."""
        frames = job.frame_count
        
        if job.quality == RenderQuality.DRAFT:
            time_per_frame = TIME_PER_FRAME_DRAFT
        elif job.quality == RenderQuality.HIGH:
            time_per_frame = TIME_PER_FRAME_HIGH
        else:
            time_per_frame = TIME_PER_FRAME_BASE
        
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
            "max_duration_sec": 30,  # HunyuanCustom typical limit
            "max_resolution": (1280, 720),  # 720p optimized
            "supported_fps": [24, 25, 30],
            "default_fps": self.DEFAULT_FPS,
            "models": ["hunyuan_custom"],
            "identity_method": "native_image_token",
            "identity_score": 0.627,  # ArcFace benchmark
            "vram_required_gb": 80,
            "gpu_config": "4x RTX 4090 or 1x H100",
        }
    
    # -------------------------------------------------------------------------
    # INTERNAL METHODS
    # -------------------------------------------------------------------------
    
    async def _upload_job_files(self, job: JobSpec) -> Dict[str, str]:
        """
        Upload files needed for the job.
        
        Returns dict mapping local path to server filename.
        """
        uploaded = {}
        
        # Upload init frame if provided
        if job.has_init_frame:
            logger.debug(f"Uploading init frame: {job.init_frame}")
            result = await self._client.upload_file(job.init_frame)
            uploaded[str(job.init_frame)] = result["name"]
        
        # Upload face references for characters
        # HunyuanCustom uses these as <image> token inputs
        for char_ref in job.character_refs:
            for face_ref in char_ref.face_refs:
                if face_ref.exists():
                    logger.debug(f"Uploading face ref for identity: {face_ref}")
                    result = await self._client.upload_file(face_ref)
                    uploaded[str(face_ref)] = result["name"]
        
        return uploaded
    
    def _select_workflow_template(self, job: JobSpec) -> str:
        """
        Select the appropriate workflow template.
        
        HunyuanCustom is simpler than Wan:
        - I2V (with init frame): pass1_img2vid
        - T2V (no init frame): pass1_t2v
        
        Identity is handled via <image> token, not workflow variants.
        """
        if job.has_init_frame:
            return self.WORKFLOW_IMG2VID
        return self.WORKFLOW_T2V
    
    async def _build_workflow(
        self,
        job: JobSpec,
        uploaded_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Build the ComfyUI workflow from job spec.
        """
        template_name = self._select_workflow_template(job)
        
        # Build parameters
        params = self._build_generation_params(job, uploaded_files)
        
        # Load template and inject
        try:
            workflow = self._loader.load_and_inject(
                template_name,
                params,
                strict=False,
                validate=True
            )
        except FileNotFoundError as e:
            raise RenderConfigError(
                f"HunyuanCustom workflow '{template_name}' not found. "
                f"Ensure workflows/hunyuan_custom/{template_name}.json exists.",
                job
            ) from e
        
        return workflow
    
    def _build_generation_params(
        self,
        job: JobSpec,
        uploaded_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Build workflow parameters for HunyuanCustom generation.
        """
        # Format prompt with <image> token if character refs exist
        formatted_prompt = self._format_prompt_with_image_token(job)
        
        params = {
            "PROMPT": formatted_prompt,
            "POSITIVE_PROMPT": formatted_prompt,  # Alias for compatibility
            "NEGATIVE_PROMPT": job.negative_prompt,
            "SEED": job.seed,
            "WIDTH": job.width,
            "HEIGHT": job.height,
            "FPS": job.fps or self.DEFAULT_FPS,
            "FRAMES": job.frame_count,
            "OUTPUT_PREFIX": f"hunyuan_{int(time.time())}",
        }
        
        # Get model config and HunyuanCustom-specific params
        model_params = self._get_model_config(job)
        params.update(model_params)
        
        # Use model config values or job overrides or defaults
        params["CFG_SCALE"] = job.cfg_scale if job.cfg_scale != 7.0 else (
            model_params.get("CFG_SCALE") or self.DEFAULT_CFG_SCALE
        )
        params["STEPS"] = job.steps if job.steps != 30 else (
            model_params.get("STEPS") or self.DEFAULT_STEPS
        )
        params["FLOW_SHIFT"] = model_params.get("FLOW_SHIFT") or self.DEFAULT_FLOW_SHIFT
        
        # Add init frame if present
        if job.has_init_frame and str(job.init_frame) in uploaded_files:
            params["INIT_IMAGE"] = uploaded_files[str(job.init_frame)]
        
        # Add face reference for identity injection
        # HunyuanCustom uses this with <image> token
        if job.character_refs:
            char_ref = job.character_refs[0]
            if char_ref.face_refs:
                face_path = str(char_ref.face_refs[0])
                if face_path in uploaded_files:
                    params["FACE_REF_IMAGE"] = uploaded_files[face_path]
                    params["FACE_REF_PATH"] = uploaded_files[face_path]
            
            # Support second character if present
            if len(job.character_refs) > 1:
                char_ref_2 = job.character_refs[1]
                if char_ref_2.face_refs:
                    face_path_2 = str(char_ref_2.face_refs[0])
                    if face_path_2 in uploaded_files:
                        params["FACE_REF_IMAGE_2"] = uploaded_files[face_path_2]
        
        # Add any renderer-specific overrides
        params.update(job.renderer_config)
        
        return params
    
    def _format_prompt_with_image_token(self, job: JobSpec) -> str:
        """
        Format prompt with <image> token for HunyuanCustom identity injection.
        
        HunyuanCustom uses the <image> token to inject face identity:
        - Single subject: "A portrait of <image> walking in a park"
        - Multi-subject: "<image> (Alice) talking to <image> (Bob)"
        
        If the prompt doesn't contain <image> but character refs exist,
        we prepend the identity phrase.
        """
        prompt = job.prompt
        
        # Check if prompt already has <image> token
        if "<image>" in prompt:
            return prompt
        
        # No character refs = no identity injection needed
        if not job.character_refs:
            return prompt
        
        # Single character: prepend identity phrase
        if len(job.character_refs) == 1:
            char = job.character_refs[0]
            # Use character name if available, otherwise generic
            if char.name:
                return f"A portrait of <image> ({char.name}), {prompt}"
            else:
                return f"A portrait of <image>, {prompt}"
        
        # Multiple characters: construct multi-subject prompt
        # Format: "<image> (Name1) and <image> (Name2) doing..."
        char_tokens = []
        for char in job.character_refs[:2]:  # Max 2 for HunyuanCustom
            if char.name:
                char_tokens.append(f"<image> ({char.name})")
            else:
                char_tokens.append("<image>")
        
        subject_phrase = " and ".join(char_tokens)
        return f"{subject_phrase}, {prompt}"
    
    def _get_model_config(self, job: JobSpec) -> Dict[str, Any]:
        """
        Get model paths based on current tier.
        
        HunyuanCustom only supports I2V (identity-focused).
        """
        # Get tier from environment, not hardcoded
        tier = ModelTier.from_env()
        
        try:
            config = get_model_config("hunyuan_custom", "i2v", tier)
            model_params = config.to_workflow_params()
            
            logger.debug(
                f"Using HunyuanCustom I2V models (tier={tier.value}): "
                f"unet={config.unet}, llava={config.llava}"
            )
            return model_params
            
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                f"Could not load HunyuanCustom model config: {e}. "
                f"Workflow will use its defaults."
            )
            return {}
    
    async def _download_output(self, job: ComfyJob, spec: JobSpec) -> Path:
        """
        Download the output video from ComfyUI.
        """
        video_filename = None
        video_subfolder = ""
        
        for node_id, outputs in job.outputs.items():
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
            raise RenderBackendError(
                f"No video output found in HunyuanCustom job results: {job.outputs}",
                spec
            )
        
        # Download the file
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / video_filename
        
        await self._client.download_file(
            video_filename,
            output_path,
            subfolder=video_subfolder
        )
        
        logger.debug(f"Downloaded HunyuanCustom output to {output_path}")
        return output_path