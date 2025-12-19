"""
Continuum Engine - Bridge Engine (The Handshake Layer)

Generates synthetic "Bridge Frames" that ensure seamless transitions
between shots. This is the CORE VALUE of the Continuum system.

The Problem:
    Video models "reset" at generation start. Shot B doesn't know
    what Shot A looked like. Characters change clothes, props teleport,
    emotions reset.

The Solution:
    Generate Frame 0 of Shot B BEFORE generating the video.
    This frame captures: identity, pose, emotion, prop positions.
    Feed it as init_frame to the video model.

Architecture:
    1. Capture: Extract last valid frame from Shot A
    2. Analyze: Extract pose (OpenPose) and depth from source frame
    3. Transform: Generate new frame from Shot B's camera angle
    4. Inject: Pass to renderer as init_frame

Design Principles:
    1. Workflow-agnostic: Actual ComfyUI workflow is external JSON
    2. Degradation-ready: ControlNet Ã¢â€ â€™ IP-Adapter Ã¢â€ â€™ prompt-only fallback
    3. Async-first: All generation is async
    4. Testable: Mock implementation for local testing
"""

import asyncio
import random
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import shutil
import tempfile

from ..renderers.base import (
    CharacterRef,
    LocationRef,
    JobSpec,
    RenderQuality,
    RenderError,
)
from ..comfy_client import (
    ComfyClient,
    ComfyError,
    WorkflowLoader,
    GenerationParams,
)
from ..core.config import get_config
from ..core.error_recovery import retry_async, RetryConfig

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class BridgeMethod(str, Enum):
    """Methods for generating bridge frames, in order of quality."""
    CONTROLNET_FULL = "controlnet_full"      # Pose + Depth + IP-Adapter (best)
    CONTROLNET_POSE = "controlnet_pose"      # Pose + IP-Adapter
    IPADAPTER_ONLY = "ipadapter_only"        # Just IP-Adapter (no pose)
    PROMPT_ONLY = "prompt_only"              # Text prompt only (fallback)


class CameraTransition(str, Enum):
    """Types of camera angle changes between shots."""
    SAME = "same"                # Same angle (e.g., continuous action)
    REVERSE = "reverse"          # 180Ã‚Â° flip (e.g., conversation)
    SIDE = "side"                # 90Ã‚Â° move (e.g., profile to front)
    AERIAL = "aerial"            # Ground to overhead
    GROUND = "ground"            # Overhead to ground
    CLOSEUP = "closeup"          # Wide to close
    WIDEOUT = "wideout"          # Close to wide
    CUSTOM = "custom"            # Arbitrary angle change


class BridgeStatus(str, Enum):
    """Status of bridge frame generation."""
    PENDING = "pending"
    EXTRACTING = "extracting"    # Extracting pose/depth
    GENERATING = "generating"    # Running generation
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PoseData:
    """
    Extracted pose information from source frame.
    
    Stores OpenPose keypoints and optional depth map for
    ControlNet conditioning.
    """
    keypoints_path: Optional[Path] = None    # OpenPose visualization
    depth_map_path: Optional[Path] = None    # Depth estimation
    pose_json: Optional[Dict[str, Any]] = None  # Raw keypoints data
    confidence: float = 0.0                  # Detection confidence
    character_count: int = 0                 # Number of people detected
    
    @property
    def has_pose(self) -> bool:
        return self.keypoints_path is not None and self.keypoints_path.exists()
    
    @property
    def has_depth(self) -> bool:
        return self.depth_map_path is not None and self.depth_map_path.exists()


@dataclass
class BridgeSpec:
    """
    Specification for generating a bridge frame.
    
    This is the input to the Bridge Engine. It combines:
    - Source information (last frame of Shot A)
    - Target information (what Shot B needs)
    - Transition metadata
    
    Attributes:
        source_frame: Path to last frame of Shot A
        target_prompt: Prompt for Shot B
        characters: Characters that must appear in bridge frame
        location: Location/environment reference
        camera_transition: How camera angle changes
        target_shot_type: Camera framing for Shot B (wide, close, etc.)
        emotion_note: Emotional continuity hint
        pose_data: Pre-extracted pose (optional, will extract if missing)
        seed: Random seed for reproducibility
    """
    # Required
    source_frame: Path
    target_prompt: str
    
    # Identity
    characters: List[CharacterRef] = field(default_factory=list)
    location: Optional[LocationRef] = None
    
    # Camera
    camera_transition: CameraTransition = CameraTransition.SAME
    target_shot_type: str = "medium"  # Maps to ShotType
    camera_notes: str = ""
    
    # Continuity hints
    emotion_note: str = ""           # e.g., "character is now angry"
    prop_positions: Dict[str, Any] = field(default_factory=dict)  # From World State
    
    # Pre-extracted data (optional)
    pose_data: Optional[PoseData] = None
    
    # Generation params
    seed: int = -1
    quality: RenderQuality = RenderQuality.STANDARD
    width: int = 1280
    height: int = 720
    
    # Renderer-specific overrides
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate inputs."""
        if isinstance(self.source_frame, str):
            self.source_frame = Path(self.source_frame)
    
    @property
    def source_exists(self) -> bool:
        """Check if source frame file exists."""
        return self.source_frame.exists()
    
    @property
    def has_characters(self) -> bool:
        """Check if character references provided."""
        return len(self.characters) > 0
    
    @property
    def primary_character(self) -> Optional[CharacterRef]:
        """Get the first/primary character."""
        return self.characters[0] if self.characters else None
    
    @classmethod
    def from_shots(
        cls,
        shot_a_last_frame: Path,
        shot_b_prompt: str,
        shot_b_characters: List[CharacterRef],
        shot_b_type: str = "medium",
        shot_a_type: str = "medium",
        **kwargs
    ) -> "BridgeSpec":
        """
        Factory method to create BridgeSpec from shot information.
        
        Automatically infers camera transition from shot types.
        """
        # Infer camera transition from shot type changes
        transition = cls._infer_transition(shot_a_type, shot_b_type)
        
        return cls(
            source_frame=shot_a_last_frame,
            target_prompt=shot_b_prompt,
            characters=shot_b_characters,
            camera_transition=transition,
            target_shot_type=shot_b_type,
            **kwargs
        )
    
    @staticmethod
    def _infer_transition(from_type: str, to_type: str) -> CameraTransition:
        """Infer camera transition from shot type changes."""
        # Same angle = no transition needed
        if from_type == to_type:
            return CameraTransition.SAME
        
        close_types = {"close", "extreme_close"}
        wide_types = {"wide", "aerial", "group"}
        medium_or_wider = {"wide", "aerial", "group", "medium", "two_shot"}
        
        # Moving closer (wide/medium Ã¢â€ â€™ close)
        if from_type in medium_or_wider and to_type in close_types:
            return CameraTransition.CLOSEUP
        # Moving wider (close Ã¢â€ â€™ wide/medium)  
        if from_type in close_types and to_type in wide_types:
            return CameraTransition.WIDEOUT
        # Aerial transitions
        if to_type == "aerial":
            return CameraTransition.AERIAL
        if from_type == "aerial":
            return CameraTransition.GROUND
        
        return CameraTransition.CUSTOM


@dataclass
class BridgeResult:
    """
    Result of bridge frame generation.
    
    Contains the generated frame and metadata about how it was created.
    """
    # Output
    frame_path: Path
    
    # Method used
    method: BridgeMethod
    
    # Metadata
    generation_time_sec: float = 0.0
    pose_data: Optional[PoseData] = None
    seed_used: int = -1
    
    # Quality metrics (for debugging/tuning)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def exists(self) -> bool:
        """Check if output frame exists."""
        return self.frame_path.exists()


@dataclass
class BridgeProgress:
    """Progress update during bridge generation."""
    stage: str
    progress: float
    message: str = ""
    elapsed_sec: float = 0.0


# =============================================================================
# EXCEPTIONS
# =============================================================================

class BridgeError(Exception):
    """Base exception for bridge generation errors."""
    def __init__(self, message: str, spec: Optional[BridgeSpec] = None):
        super().__init__(message)
        self.spec = spec


class BridgeSourceError(BridgeError):
    """Source frame invalid or missing."""
    pass


class BridgePoseError(BridgeError):
    """Pose extraction failed."""
    pass


class BridgeGenerationError(BridgeError):
    """Frame generation failed."""
    pass


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseBridgeEngine(ABC):
    """
    Abstract base class for bridge frame generation.
    
    Defines the interface that all bridge engines must implement.
    This allows hot-swapping between implementations (ComfyUI, API, mock).
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize bridge engine.
        
        Args:
            output_dir: Directory for generated frames
        """
        self.output_dir = output_dir or Path(tempfile.gettempdir()) / "continuum_bridges"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._progress_callback: Optional[Callable[[BridgeProgress], None]] = None
    
    @abstractmethod
    async def generate(
        self,
        spec: BridgeSpec,
        progress_callback: Optional[Callable[[BridgeProgress], None]] = None
    ) -> BridgeResult:
        """
        Generate a bridge frame from specification.
        
        Args:
            spec: Bridge specification
            progress_callback: Optional callback for progress updates
            
        Returns:
            BridgeResult with path to generated frame
            
        Raises:
            BridgeError: If generation fails
        """
        pass
    
    @abstractmethod
    async def extract_pose(self, frame_path: Path) -> PoseData:
        """
        Extract pose and depth from a frame.
        
        Used to pre-compute pose data for ControlNet conditioning.
        
        Args:
            frame_path: Path to source frame
            
        Returns:
            PoseData with extracted information
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the bridge engine backend is available.
        
        Returns:
            True if engine is ready
        """
        pass
    
    def select_method(self, spec: BridgeSpec) -> BridgeMethod:
        """
        Select best available bridge method based on spec.
        
        Implements degradation ladder:
        1. Full ControlNet (pose + depth + identity) if pose available
        2. Pose-only ControlNet if depth unavailable
        3. IP-Adapter only if pose unavailable but face refs exist
        4. Prompt-only as last resort
        
        Args:
            spec: Bridge specification
            
        Returns:
            Best available method
        """
        has_pose = spec.pose_data and spec.pose_data.has_pose
        has_depth = spec.pose_data and spec.pose_data.has_depth
        has_face_refs = any(c.has_face_refs() for c in spec.characters)
        has_lora = any(c.has_lora() for c in spec.characters)
        
        # Best case: full conditioning
        if has_pose and has_depth and (has_face_refs or has_lora):
            return BridgeMethod.CONTROLNET_FULL
        
        # Good case: pose + identity
        if has_pose and (has_face_refs or has_lora):
            return BridgeMethod.CONTROLNET_POSE
        
        # Fallback: identity only
        if has_face_refs or has_lora:
            return BridgeMethod.IPADAPTER_ONLY
        
        # Last resort: prompt only
        return BridgeMethod.PROMPT_ONLY
    
    def _report_progress(
        self,
        stage: str,
        progress: float,
        message: str = "",
        elapsed_sec: float = 0.0,
        callback: Optional[Callable[[BridgeProgress], None]] = None
    ) -> None:
        """Report progress to callback if provided."""
        cb = callback or self._progress_callback
        if cb:
            cb(BridgeProgress(
                stage=stage,
                progress=progress,
                message=message,
                elapsed_sec=elapsed_sec
            ))


# =============================================================================
# COMFYUI BRIDGE ENGINE (Production)
# =============================================================================

class ComfyUIBridgeEngine(BaseBridgeEngine):
    """
    Bridge engine using ComfyUI for generation.
    
    This is the production implementation. It:
    1. Extracts pose/depth via ComfyUI nodes
    2. Generates bridge frame with ControlNet + IP-Adapter
    3. Downloads result
    
    Workflow templates are loaded from external JSON files,
    keeping the logic here workflow-agnostic.
    """
    
    # Workflow template names
    WORKFLOW_POSE_EXTRACT = "bridge_pose_extract"
    WORKFLOW_DEPTH_EXTRACT = "bridge_depth_extract"
    WORKFLOW_FULL = "bridge_full"             # Pose + Depth + IP-Adapter
    WORKFLOW_POSE_ONLY = "bridge_pose_only"   # Pose + IP-Adapter
    WORKFLOW_IPADAPTER = "bridge_ipadapter"   # IP-Adapter only
    WORKFLOW_BASIC = "bridge_basic"           # Prompt only
    
    def __init__(
        self,
        comfy_client: Optional[ComfyClient] = None,
        workflow_loader: Optional[WorkflowLoader] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize ComfyUI bridge engine.
        
        Args:
            comfy_client: ComfyUI client (creates default if None)
            workflow_loader: Workflow loader (creates default if None)
            output_dir: Output directory for generated frames
        """
        super().__init__(output_dir)
        
        config = get_config()
        self.client = comfy_client or ComfyClient(
            host=config.comfyui.host,
        )
        self.workflow_loader = workflow_loader or WorkflowLoader(
            workflows_dir=Path(config.paths.workflows_dir)
        )
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize connection to ComfyUI."""
        if not self._initialized:
            await self.client.connect()
            self._initialized = True
    
    async def shutdown(self) -> None:
        """Close ComfyUI connection."""
        if self._initialized:
            await self.client.disconnect()
            self._initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
    
    async def health_check(self) -> bool:
        """Check ComfyUI connection."""
        try:
            if not self._initialized:
                await self.initialize()
            return await self.client.health_check()
        except Exception as e:
            logger.error(f"Bridge engine health check failed: {e}")
            return False
    
    @retry_async(RetryConfig(max_attempts=3, base_delay_sec=1.0))
    async def generate(
        self,
        spec: BridgeSpec,
        progress_callback: Optional[Callable[[BridgeProgress], None]] = None
    ) -> BridgeResult:
        """
        Generate bridge frame via ComfyUI.
        
        Workflow:
        1. Validate source frame exists
        2. Extract pose/depth if not provided
        3. Select best generation method
        4. Load and configure workflow
        5. Submit and wait for result
        6. Download generated frame
        """
        import time
        start_time = time.time()
        self._progress_callback = progress_callback
        
        # Validate source
        if not spec.source_exists:
            raise BridgeSourceError(
                f"Source frame not found: {spec.source_frame}",
                spec
            )
        
        self._report_progress("validating", 0.1, "Validating source frame")
        
        # Ensure initialized
        if not self._initialized:
            await self.initialize()
        
        # Extract pose/depth if not provided
        if spec.pose_data is None:
            self._report_progress("extracting", 0.2, "Extracting pose and depth")
            spec.pose_data = await self.extract_pose(spec.source_frame)
        
        # Select method based on available data
        method = self.select_method(spec)
        logger.info(f"Selected bridge method: {method.value}")
        
        self._report_progress("generating", 0.4, f"Generating frame ({method.value})")
        
        # Upload source frame
        remote_source = await self.client.upload_image(spec.source_frame)
        
        # Upload pose/depth if available
        remote_pose = None
        remote_depth = None
        if spec.pose_data:
            if spec.pose_data.has_pose:
                remote_pose = await self.client.upload_image(spec.pose_data.keypoints_path)
            if spec.pose_data.has_depth:
                remote_depth = await self.client.upload_image(spec.pose_data.depth_map_path)
        
        # Upload character face refs if available
        remote_face_refs = []
        for char in spec.characters:
            if char.has_face_refs():
                for ref_path in char.face_refs:
                    remote_ref = await self.client.upload_image(ref_path)
                    remote_face_refs.append(remote_ref)
        
        # Build generation params
        params = self._build_generation_params(
            spec, method, remote_source, remote_pose, remote_depth, remote_face_refs
        )
        
        # Load and configure workflow
        workflow_name = self._get_workflow_name(method)
        workflow = self.workflow_loader.load_and_inject(workflow_name, params)
        
        self._report_progress("generating", 0.6, "Running ComfyUI workflow")
        
        # Submit job and wait for completion
        try:
            job = await self.client.submit(workflow)
            
            # Use client's wait_for_completion which handles polling correctly
            def progress_cb(progress_data: Dict[str, Any]) -> None:
                value = progress_data.get("value", 0)
                max_val = progress_data.get("max", 100)
                pct = value / max_val if max_val > 0 else 0
                self._report_progress(
                    "generating",
                    0.6 + (pct * 0.3),
                    f"Rendering: {int(pct * 100)}%"
                )
            
            completed_job = await self.client.wait_for_completion(
                job.prompt_id,
                progress_callback=progress_cb
            )
            
            # Download result - find image in outputs
            self._report_progress("downloading", 0.95, "Downloading result")
            
            output_filename = f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            output_path = self.output_dir / output_filename
            
            # Extract image filename from job outputs (same pattern as WanRenderer)
            image_filename = None
            image_subfolder = ""
            for node_id, outputs in completed_job.outputs.items():
                if "images" in outputs:
                    items = outputs["images"]
                    if items and len(items) > 0:
                        image_filename = items[0].get("filename")
                        image_subfolder = items[0].get("subfolder", "")
                        break
            
            if not image_filename:
                raise BridgeGenerationError(
                    "No output image found in bridge workflow result",
                    spec
                )
            
            await self.client.download_output(
                filename=image_filename,
                subfolder=image_subfolder,
                file_type="output",
                save_path=output_path
            )
            
        except ComfyError as e:
            raise BridgeGenerationError(f"ComfyUI error: {e}", spec) from e
        
        elapsed = time.time() - start_time
        self._report_progress("completed", 1.0, "Bridge frame generated")
        
        return BridgeResult(
            frame_path=output_path,
            method=method,
            generation_time_sec=elapsed,
            pose_data=spec.pose_data,
            seed_used=spec.seed,
            metadata={
                "workflow": workflow_name,
                "source_frame": str(spec.source_frame),
                "camera_transition": spec.camera_transition.value,
            }
        )
    
    async def extract_pose(self, frame_path: Path) -> PoseData:
        """
        Extract pose and depth from frame via ComfyUI.
        
        Uses OpenPose for pose detection and MiDaS/Depth-Anything for depth.
        """
        if not self._initialized:
            await self.initialize()
        
        # Upload frame
        remote_path = await self.client.upload_image(frame_path)
        
        # Run pose extraction workflow
        try:
            pose_workflow = self.workflow_loader.load_and_inject(
                self.WORKFLOW_POSE_EXTRACT, 
                {"SOURCE_IMAGE": remote_path}
            )
            
            pose_job = await self.client.submit(pose_workflow)
            pose_job = await self.client.wait_for_completion(pose_job.prompt_id)
            
            # Download pose result - find image in outputs
            pose_path = self.output_dir / f"pose_{frame_path.stem}.png"
            image_found = False
            for node_id, outputs in pose_job.outputs.items():
                if "images" in outputs:
                    items = outputs["images"]
                    if items and len(items) > 0:
                        await self.client.download_output(
                            filename=items[0].get("filename"),
                            subfolder=items[0].get("subfolder", ""),
                            file_type="output",
                            save_path=pose_path
                        )
                        image_found = True
                        break
            if not image_found:
                pose_path = None
                
        except Exception as e:
            logger.warning(f"Pose extraction failed: {e}")
            pose_path = None
        
        # Run depth extraction workflow
        try:
            depth_workflow = self.workflow_loader.load_and_inject(
                self.WORKFLOW_DEPTH_EXTRACT,
                {"SOURCE_IMAGE": remote_path}
            )
            
            depth_job = await self.client.submit(depth_workflow)
            depth_job = await self.client.wait_for_completion(depth_job.prompt_id)
            
            # Download depth result - find image in outputs
            depth_path = self.output_dir / f"depth_{frame_path.stem}.png"
            image_found = False
            for node_id, outputs in depth_job.outputs.items():
                if "images" in outputs:
                    items = outputs["images"]
                    if items and len(items) > 0:
                        await self.client.download_output(
                            filename=items[0].get("filename"),
                            subfolder=items[0].get("subfolder", ""),
                            file_type="output",
                            save_path=depth_path
                        )
                        image_found = True
                        break
            if not image_found:
                depth_path = None
                
        except Exception as e:
            logger.warning(f"Depth extraction failed: {e}")
            depth_path = None
        
        return PoseData(
            keypoints_path=pose_path,
            depth_map_path=depth_path,
            confidence=0.8 if pose_path else 0.0,
            character_count=1,  # TODO: Parse from pose detection
        )
    
    def _build_generation_params(
        self,
        spec: BridgeSpec,
        method: BridgeMethod,
        remote_source: str,
        remote_pose: Optional[str],
        remote_depth: Optional[str],
        remote_face_refs: List[str],
    ) -> Dict[str, Any]:
        """Build parameter dict for workflow injection."""
        
        # Build prompt with camera transition context
        prompt = self._enhance_prompt(spec)
        
        params = {
            "PROMPT": prompt,
            "NEGATIVE_PROMPT": "blurry, low quality, distorted, disfigured, multiple people" 
                              if len(spec.characters) == 1 else "blurry, low quality, distorted",
            "SOURCE_IMAGE": remote_source,
            "WIDTH": spec.width,
            "HEIGHT": spec.height,
            "SEED": spec.seed if spec.seed >= 0 else random.randint(0, 2**32 - 1),
            "STEPS": 20 if spec.quality == RenderQuality.STANDARD else 30,
            "CFG": 7.0,
            "DENOISE": 0.65,  # Moderate denoise to preserve source
        }
        
        # Add pose/depth conditioning
        if remote_pose and method in (BridgeMethod.CONTROLNET_FULL, BridgeMethod.CONTROLNET_POSE):
            params["POSE_IMAGE"] = remote_pose
            params["CONTROLNET_POSE_STRENGTH"] = 0.8
        
        if remote_depth and method == BridgeMethod.CONTROLNET_FULL:
            params["DEPTH_IMAGE"] = remote_depth
            params["CONTROLNET_DEPTH_STRENGTH"] = 0.5
        
        # Add identity conditioning
        if remote_face_refs:
            params["FACE_REF_IMAGE"] = remote_face_refs[0]  # Primary face ref
            params["IPADAPTER_STRENGTH"] = 0.7
        
        # Add LoRA if available
        if spec.characters and spec.characters[0].has_lora():
            params["LORA_PATH"] = str(spec.characters[0].lora_path)
            params["LORA_STRENGTH"] = spec.characters[0].lora_strength
        
        # Apply any overrides
        params.update(spec.config_overrides)
        
        return params
    
    def _enhance_prompt(self, spec: BridgeSpec) -> str:
        """
        Enhance prompt with camera transition and continuity context.
        """
        prompt_parts = [spec.target_prompt]
        
        # Add shot type context
        shot_type_hints = {
            "wide": "wide shot, full body visible",
            "medium": "medium shot, waist up",
            "close": "close-up shot, face detail",
            "extreme_close": "extreme close-up, detail shot",
            "over_shoulder": "over the shoulder shot",
        }
        if spec.target_shot_type in shot_type_hints:
            prompt_parts.append(shot_type_hints[spec.target_shot_type])
        
        # Add camera notes if provided
        if spec.camera_notes:
            prompt_parts.append(spec.camera_notes)
        
        # Add emotion continuity
        if spec.emotion_note:
            prompt_parts.append(spec.emotion_note)
        
        return ", ".join(prompt_parts)
    
    def _get_workflow_name(self, method: BridgeMethod) -> str:
        """Map method to workflow template name."""
        mapping = {
            BridgeMethod.CONTROLNET_FULL: self.WORKFLOW_FULL,
            BridgeMethod.CONTROLNET_POSE: self.WORKFLOW_POSE_ONLY,
            BridgeMethod.IPADAPTER_ONLY: self.WORKFLOW_IPADAPTER,
            BridgeMethod.PROMPT_ONLY: self.WORKFLOW_BASIC,
        }
        return mapping[method]


# =============================================================================
# MOCK BRIDGE ENGINE (Testing)
# =============================================================================

class MockBridgeEngine(BaseBridgeEngine):
    """
    Mock bridge engine for local testing without GPU.
    
    Copies source frame as "bridge frame" with metadata.
    Allows testing full orchestration flow locally.
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
        simulate_delay: float = 0.5,
        simulate_failure: bool = False,
    ):
        """
        Initialize mock engine.
        
        Args:
            output_dir: Output directory
            simulate_delay: Fake processing delay (seconds)
            simulate_failure: If True, always fail generation
        """
        super().__init__(output_dir)
        self.simulate_delay = simulate_delay
        self.simulate_failure = simulate_failure
        self._call_count = 0
    
    async def health_check(self) -> bool:
        """Mock always healthy (unless simulating failure)."""
        return not self.simulate_failure
    
    async def generate(
        self,
        spec: BridgeSpec,
        progress_callback: Optional[Callable[[BridgeProgress], None]] = None
    ) -> BridgeResult:
        """
        Mock generation - copies source frame.
        
        Useful for testing orchestration without actual GPU work.
        """
        import time
        start_time = time.time()
        self._progress_callback = progress_callback
        self._call_count += 1
        
        # Validate source
        if not spec.source_exists:
            raise BridgeSourceError(
                f"Source frame not found: {spec.source_frame}",
                spec
            )
        
        # Simulate failure if configured
        if self.simulate_failure:
            raise BridgeGenerationError("Simulated failure", spec)
        
        # Simulate processing stages
        self._report_progress("validating", 0.1, "Validating source")
        await asyncio.sleep(self.simulate_delay * 0.2)
        
        self._report_progress("extracting", 0.3, "Extracting pose (mock)")
        await asyncio.sleep(self.simulate_delay * 0.3)
        
        self._report_progress("generating", 0.6, "Generating frame (mock)")
        await asyncio.sleep(self.simulate_delay * 0.4)
        
        # Copy source as mock output
        output_filename = f"mock_bridge_{self._call_count:04d}.png"
        output_path = self.output_dir / output_filename
        shutil.copy2(spec.source_frame, output_path)
        
        self._report_progress("completed", 1.0, "Mock bridge complete")
        
        elapsed = time.time() - start_time
        method = self.select_method(spec)
        
        return BridgeResult(
            frame_path=output_path,
            method=method,
            generation_time_sec=elapsed,
            pose_data=spec.pose_data,
            seed_used=spec.seed,
            metadata={
                "mock": True,
                "call_count": self._call_count,
                "source_frame": str(spec.source_frame),
            }
        )
    
    async def extract_pose(self, frame_path: Path) -> PoseData:
        """Mock pose extraction - returns empty pose data."""
        await asyncio.sleep(self.simulate_delay * 0.2)
        
        return PoseData(
            keypoints_path=None,
            depth_map_path=None,
            confidence=0.0,
            character_count=1,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_bridge_engine(
    use_mock: bool = False,
    **kwargs
) -> BaseBridgeEngine:
    """
    Factory function to get appropriate bridge engine.
    
    Args:
        use_mock: If True, return mock engine for testing
        **kwargs: Passed to engine constructor
        
    Returns:
        Bridge engine instance
    """
    if use_mock:
        return MockBridgeEngine(**kwargs)
    return ComfyUIBridgeEngine(**kwargs)