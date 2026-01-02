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
    DEFAULT_STEPS = 25
    DEFAULT_FPS = 24
    DEFAULT_DENOISE_STRENGTH = 1.0
    DEFAULT_NOISE_AUG_STRENGTH = 0.0  # Temporal variation from init frame (0=frozen, 0.05+=more motion)
    
    # Frame count constraint (HunyuanVideo 3D VAE architecture requirement)
    # The 3D VAE processes video in 4-frame temporal chunks.
    # Formula: (frames - 1) must be divisible by 4
    # Valid values: 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49...
    # Minimum: 5 frames (~0.2s at 24fps)
    # Recommended: 25-49 frames (1-2s at 24fps) for quality/speed balance
    FRAME_DIVISOR = 4  # (frames - 1) % FRAME_DIVISOR == 0
    MIN_FRAMES = 5
    MAX_FRAMES = 129  # ~5s at 24fps, practical VRAM limit
    
    # Validated negative prompt from Phase 4 testing
    DEFAULT_NEGATIVE_PROMPT = (
        "Aerial view, overexposed, low quality, deformation, bad composition, "
        "bad hands, bad teeth, bad eyes, bad limbs, distortion, blurring, "
        "text, subtitles, static, picture, black border."
    )
    
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
            ## Temporary Addition(as video is not matching)
            import json
            with open("workspace/output/debug_workflow.json", "w") as f:
                json.dump(workflow, f, indent=2)
            logger.info("DEBUG: Dumped workflow to workspace/output/debug_workflow.json")
            
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
        
        Constructs the parameter dict that workflow_loader injects into
        the workflow template's {{PLACEHOLDER}} values.
        
        Architecture Alignment (ARCHITECTURE.md Section 3A):
        - INIT_IMAGE: Hero/Bridge frame â†’ VAE encode â†’ video starting latent
        - FACE_REF_IMAGE: Face reference â†’ CLIP vision â†’ identity via <image> token
        
        These serve DIFFERENT purposes and must be separate.
        """
        # Format prompt with <image> token if character refs exist
        formatted_prompt = self._format_prompt_with_image_token(job)
        
        # Use job's negative prompt or default
        negative_prompt = job.negative_prompt or self.DEFAULT_NEGATIVE_PROMPT
        
        # Validate frame count for HunyuanCustom's 3D VAE constraint
        validated_frames = self._validate_frame_count(job.frame_count)
        
        params = {
            "PROMPT": formatted_prompt,
            "POSITIVE_PROMPT": formatted_prompt,  # Alias for compatibility
            "NEGATIVE_PROMPT": negative_prompt,
            "SEED": job.seed,
            "WIDTH": job.width,
            "HEIGHT": job.height,
            "FPS": job.fps or self.DEFAULT_FPS,
            "FRAMES": validated_frames,
            "OUTPUT_PREFIX": f"hunyuan_{int(time.time())}",
        }
        
        # Get model config (paths + generation params from models.json)
        model_params = self._get_model_config(job)
        params.update(model_params)
        
        # Override with job-specific values if provided (non-default)
        # CFG_SCALE: use job value if not default 7.0, else model config, else class default
        if job.cfg_scale != 7.0:
            params["CFG_SCALE"] = job.cfg_scale
        elif "CFG_SCALE" not in params:
            params["CFG_SCALE"] = self.DEFAULT_CFG_SCALE
            
        # STEPS: use job value if not default 30, else model config, else class default
        if job.steps != 30:
            params["STEPS"] = job.steps
        elif "STEPS" not in params:
            params["STEPS"] = self.DEFAULT_STEPS
            
        # FLOW_SHIFT: always from model config or class default
        if "FLOW_SHIFT" not in params:
            params["FLOW_SHIFT"] = self.DEFAULT_FLOW_SHIFT
            
        # DENOISE_STRENGTH: from model config or class default
        if "DENOISE_STRENGTH" not in params:
            params["DENOISE_STRENGTH"] = self.DEFAULT_DENOISE_STRENGTH
        
        # NOISE_AUG_STRENGTH: Controls temporal variation from init frame
        # 0.0 = frozen (no motion), 0.025 = subtle motion, 0.05+ = more variation
        if "NOISE_AUG_STRENGTH" not in params:
            params["NOISE_AUG_STRENGTH"] = self.DEFAULT_NOISE_AUG_STRENGTH
        
        # INIT_IMAGE: Hero frame (shot 1) or Bridge frame (shot 2+)
        # This is the VIDEO STARTING POINT - separate from FACE_REF_IMAGE (identity)
        # Per ARCHITECTURE.md: "Hero Frame --> I2V --> Video"
        if job.has_init_frame and job.init_frame:
            init_path = str(job.init_frame)
            if init_path in uploaded_files:
                params["INIT_IMAGE"] = uploaded_files[init_path]
                logger.debug(f"Set INIT_IMAGE from hero/bridge frame: {params['INIT_IMAGE']}")
            else:
                logger.warning(f"Init frame {init_path} not found in uploaded files")
        
        # FACE_REF_IMAGE: Face reference for identity injection via <image> token
        # This is SEPARATE from INIT_IMAGE - provides identity embedding only
        if job.character_refs:
            char_ref = job.character_refs[0]
            if char_ref.face_refs:
                face_path = str(char_ref.face_refs[0])
                logger.debug(f"Looking for face_path '{face_path}' in uploaded_files keys: {list(uploaded_files.keys())}")
                if face_path in uploaded_files:
                    params["FACE_REF_IMAGE"] = uploaded_files[face_path]
                    logger.info(f"Set FACE_REF_IMAGE for identity: {params['FACE_REF_IMAGE']}")
                else:
                    logger.error(f"FACE_REF_IMAGE not set! face_path '{face_path}' not in uploaded_files")
            else:
                logger.warning(f"Character '{char_ref.entity_id}' has no face_refs - identity injection disabled")
            
            # Support second character if present (HunyuanCustom supports up to 2)
            if len(job.character_refs) > 1:
                char_ref_2 = job.character_refs[1]
                if char_ref_2.face_refs:
                    face_path_2 = str(char_ref_2.face_refs[0])
                    if face_path_2 in uploaded_files:
                        params["FACE_REF_IMAGE_2"] = uploaded_files[face_path_2]
        else:
            logger.warning("No character_refs in job - FACE_REF_IMAGE not set")
        
        # Log critical params for debugging identity issues
        logger.info(f"HunyuanCustom params: PROMPT='{params.get('PROMPT', '')[:60]}...', "
                   f"FACE_REF_IMAGE={params.get('FACE_REF_IMAGE', 'NOT SET')}, "
                   f"INIT_IMAGE={params.get('INIT_IMAGE', 'NOT SET')}")
        
        # Add any renderer-specific overrides from job
        params.update(job.renderer_config)
        
        return params
    
    def _format_prompt_with_image_token(self, job: JobSpec) -> str:
        """
        Format prompt with <image> token for HunyuanCustom identity injection.
        
        HunyuanCustom uses the <image> token to inject face identity from the
        reference image. The validated format from Phase 4 testing is:
        
            "Realistic, High-quality. <image> is [action/description]."
        
        CRITICAL: The <image> token REPLACES the subject. If the prompt already
        contains a subject description like "A young woman with blonde hair...",
        we must STRIP it before adding <image> to avoid identity confusion.
        
        If the prompt already contains <image>, we prepend quality prefix only.
        If no character refs exist, we return the prompt as-is.
        
        Examples:
            Input:  "running on a beach", character_ref=Alice
            Output: "Realistic, High-quality. <image> is running on a beach."
            
            Input:  "A young woman with blonde hair running on a beach", character_ref=Alice
            Output: "Realistic, High-quality. <image> is running on a beach."
            
            Input:  "<image> is walking", character_ref=Alice  
            Output: "Realistic, High-quality. <image> is walking"
        """
        import re
        
        prompt = job.prompt
        quality_prefix = "Realistic, High-quality."
        
        # Check if prompt already has <image> token
        if "<image>" in prompt:
            # Just add quality prefix if not present
            if not prompt.startswith(quality_prefix):
                return f"{quality_prefix} {prompt}"
            return prompt
        
        # No character refs = no identity injection needed
        if not job.character_refs:
            return prompt
        
        # Strip existing subject descriptions before adding <image>
        # This handles legacy prompts written for Wan that describe the person
        action_prompt = self._strip_subject_from_prompt(prompt)
        
        # Single character: use validated format
        # "Realistic, High-quality. <image> is [action]"
        if len(job.character_refs) == 1:
            final_prompt = f"{quality_prefix} <image> is {action_prompt}"
            logger.info(f"Formatted prompt with <image> token: '{final_prompt[:80]}...'")
            return final_prompt
        
        # Multiple characters: construct multi-subject prompt
        # Format: "<image> (Name1) and <image> (Name2) are [prompt]"
        char_tokens = []
        for char in job.character_refs[:2]:  # Max 2 for HunyuanCustom
            if char.name:
                char_tokens.append(f"<image> ({char.name})")
            else:
                char_tokens.append("<image>")
        
        subject_phrase = " and ".join(char_tokens)
        return f"{quality_prefix} {subject_phrase} are {action_prompt}"
    
    def _strip_subject_from_prompt(self, prompt: str) -> str:
        """
        Strip subject descriptions from prompt to avoid identity confusion.
        
        HunyuanCustom's <image> token IS the subject. If the prompt also
        describes the subject (e.g., "A young woman with blonde hair"), the
        model gets conflicting signals and may ignore the <image> identity.
        
        Strategy: Find where the ACTION starts (verb) and keep from there.
        Common action verbs: turns, walks, runs, smiles, stands, sits, etc.
        
        Examples:
            "A young woman with blonde wavy hair turns her head" 
                -> "turning her head"
            "A man in a suit walking down the street"
                -> "walking down the street"
            "running on a sandy beach" (no subject)
                -> "running on a sandy beach" (unchanged)
        
        Args:
            prompt: Original prompt text
            
        Returns:
            Prompt with subject stripped, ready for <image> token
        """
        import re
        
        # Action verbs that typically follow subject descriptions
        # These are conjugated forms that indicate where the action starts
        action_verbs_pattern = re.compile(
            r'\b(turns?|walks?|runs?|smiles?|stands?|sits?|looks?|'
            r'laughs?|talks?|moves?|dances?|faces?|holds?|reaches?|'
            r'waves?|nods?|shakes?|speaks?|listens?|watches?|'
            r'turning|walking|running|smiling|standing|sitting|looking|'
            r'laughing|talking|moving|dancing|facing|holding|reaching|'
            r'waving|nodding|shaking|speaking|listening|watching)\b',
            re.IGNORECASE
        )
        
        # Check if prompt starts with subject pattern (A/An/The person...)
        starts_with_subject = re.match(
            r'^(?:A|An|The)\s+(?:\w+\s+)*(?:woman|man|person|girl|boy|lady|'
            r'gentleman|female|male|individual|figure|human)\b',
            prompt,
            re.IGNORECASE
        )
        
        if starts_with_subject:
            # Find first action verb in the prompt
            verb_match = action_verbs_pattern.search(prompt)
            if verb_match:
                # Extract from the verb onwards
                action_part = prompt[verb_match.start():].strip()
                
                # Ensure it starts with present participle
                action_part = self._ensure_present_participle(action_part)
                
                logger.debug(
                    f"Stripped subject from prompt: "
                    f"'{prompt[:40]}...' -> '{action_part[:40]}...'"
                )
                return action_part
        
        # No subject pattern found - check if already action-focused
        first_word = prompt.split()[0].lower() if prompt.split() else ""
        
        # Common present participles (already in correct form)
        if first_word.endswith('ing'):
            return prompt
        
        # Try to convert verb at start: "turns" -> "turning"
        return self._ensure_present_participle(prompt)
    
    def _ensure_present_participle(self, text: str) -> str:
        """
        Convert verb at start of text to present participle for grammar.
        
        "<image> is turns her head" is wrong
        "<image> is turning her head" is correct
        
        Common conversions:
        - turns -> turning
        - walks -> walking  
        - smiles -> smiling
        - nods -> nodding
        """
        import re
        
        # Pattern: word at start that looks like a verb (ends in s/es)
        verb_pattern = re.compile(r'^(\w+)(s|es)\s+', re.IGNORECASE)
        match = verb_pattern.match(text)
        
        if match:
            base = match.group(1)
            suffix = match.group(2)
            rest = text[match.end():]
            
            # Simple conversion rules
            if base.endswith('e'):
                # smile -> smiling (drop e, add ing)
                participle = base[:-1] + 'ing'
            elif len(base) > 2 and base[-1] in 'bdgmnprt' and base[-2] in 'aeiou':
                # nod -> nodding, run -> running (double consonant)
                participle = base + base[-1] + 'ing'
            else:
                # turn -> turning, walk -> walking
                participle = base + 'ing'
            
            return f"{participle} {rest}"
        
        return text
    
    def _validate_frame_count(self, requested_frames: int) -> int:
        """
        Validate and adjust frame count for HunyuanCustom's 3D VAE constraint.
        
        HunyuanVideo uses a 3D VAE that processes video in 4-frame temporal chunks.
        The constraint is: (frames - 1) must be divisible by 4.
        
        Args:
            requested_frames: The frame count requested by the job
            
        Returns:
            Adjusted frame count that satisfies the constraint.
            
        Examples:
            12 -> 13 (next valid: 12-1=11, not divisible by 4; 13-1=12 Ã¢Å“â€œ)
            25 -> 25 (already valid: 25-1=24, divisible by 4 Ã¢Å“â€œ)
            3 -> 5 (below minimum, bumped to MIN_FRAMES)
            150 -> 129 (above maximum, capped to MAX_FRAMES)
        """
        # Enforce bounds
        frames = max(requested_frames, self.MIN_FRAMES)
        frames = min(frames, self.MAX_FRAMES)
        
        # Check if already valid
        if (frames - 1) % self.FRAME_DIVISOR == 0:
            if frames != requested_frames:
                logger.debug(f"Frame count clamped: {requested_frames} -> {frames}")
            return frames
        
        # Round up to next valid frame count (4k + 1)
        # Formula: ((n - 1 + 3) // 4) * 4 + 1 gives next valid value
        adjusted = ((frames - 1 + self.FRAME_DIVISOR - 1) // self.FRAME_DIVISOR) * self.FRAME_DIVISOR + 1
        
        # Re-enforce maximum after adjustment
        adjusted = min(adjusted, self.MAX_FRAMES)
        
        logger.info(
            f"Adjusted frame count: {requested_frames} -> {adjusted} "
            f"(HunyuanCustom constraint: (frames-1) must be divisible by {self.FRAME_DIVISOR})"
        )
        return adjusted
    
    def _get_model_config(self, job: JobSpec) -> Dict[str, Any]:
        """
        Get model paths based on current tier.
        
        HunyuanCustom only supports I2V (identity-focused).
        
        Returns dict with workflow placeholders:
        - UNET_MODEL, VAE_MODEL (core)
        - CLIP_L_MODEL, LLAVA_TEXT_ENCODER (dual text encoders)
        - CLIP_VISION_MODEL (vision encoder)
        - ATTENTION_MODE, CFG_SCALE, FLOW_SHIFT, STEPS, DENOISE_STRENGTH (params)
        """
        # Get tier from environment, not hardcoded
        tier = ModelTier.from_env()
        
        try:
            config = get_model_config("hunyuan_custom", "i2v", tier)
            model_params = config.to_workflow_params()
            
            logger.debug(
                f"Using HunyuanCustom I2V models (tier={tier.value}): "
                f"unet={config.unet}, clip_l={config.clip_l}, "
                f"llava_text={config.llava_text_encoder}, clip_vision={config.clip_vision}"
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
        
        await self._client.download_output(
            filename=video_filename,
            subfolder=video_subfolder,
            save_path=output_path
        )
        
        logger.debug(f"Downloaded HunyuanCustom output to {output_path}")
        return output_path