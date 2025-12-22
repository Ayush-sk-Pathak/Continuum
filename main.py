"""
Continuum Engine - Main Orchestrator (v2)

This is the entry point that wires together the complete AI filmmaking pipeline.

The Continuum Engine generates consistent, multi-shot video by coordinating:
- Director: SceneGraph (structure), ConsistencyDict (identity), WorldState (dynamics), Pacer (timing)
- Studio: Pass1Generator (rendering), BridgeEngine (transitions), Pass2Refiner (enhancement)
- Audit: Reviewer (quality gates), IdentityChecker (faces), PhysicsChecker (objects)
- Sonic: TTS, LipSync, Ambience, Foley, Mixer
- Post: ColorMatch, AudioDucker, Stitcher

Design Principles:
1. Async-first: All cloud ops are async
2. Fail-safe: Checkpoint before every risky operation
3. Observable: Progress callbacks throughout pipeline
4. Testable: --dry-run uses mock implementations
5. Resumable: Checkpoint system enables crash recovery

Usage:
    # Full pipeline (requires cloud GPU)
    python main.py --project my_film.json

    # Dry run (local, mock implementations)
    python main.py --project my_film.json --dry-run

    # Generate specific scene
    python main.py --project my_film.json --scene scene_01

    # Skip audio generation
    python main.py --project my_film.json --no-audio

    # High quality mode
    python main.py --project my_film.json --quality high
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# =============================================================================
# IMPORTS - Core Infrastructure
# =============================================================================

from src.core.config import get_config, Config
from src.core.job_state import JobStatus, AuditStatus, AuditResult
from src.core.checkpointing import CheckpointManager
from src.core.error_recovery import DegradationLadder

# =============================================================================
# IMPORTS - Director (The Brain)
# =============================================================================

from src.director.scene_graph import (
    SceneGraph, 
    Scene, 
    Shot, 
    Chunk, 
    ChunkStatus,
    EntityRef,
)
from src.director.consistency_dict import (
    ConsistencyDict, 
    CharacterEntity,
    LocationEntity,
)
# New modules we built
from src.director.world_state import (
    WorldState,
    SceneSetup,
    TrackedObject,
    Position,
    StateEvent,
    EventType,
    create_world_state,
)
from src.director.shot_event_parser import (
    ShotEventParser,
    get_shot_event_parser,
)
from src.director.pacer import (
    Pacer,
    PacingStyle,
    ShotPacingPlan,
    get_pacer,
)

# =============================================================================
# IMPORTS - Renderers (The Muscle)
# =============================================================================

from src.renderers.base import (
    BaseRenderer, 
    JobSpec, 
    RenderResult, 
    RenderProgress,
    CharacterRef,
    LocationRef,
    RendererType,
    RenderQuality,
    get_renderer,
)
from src.renderers.wan_renderer import WanRenderer

# =============================================================================
# IMPORTS - Studio (Video Pipeline)
# =============================================================================

from src.studio.bridge_engine import (
    BaseBridgeEngine, 
    ComfyUIBridgeEngine,
    MockBridgeEngine,
    BridgeSpec, 
    BridgeResult,
    get_bridge_engine,
)
from src.studio.pass1_generator import (
    Pass1Generator,
    GenerationConfig,
    GenerationProgress,
    ChunkOutput,
    ShotOutput,
    ChunkResult,
    get_pass1_generator,
)
# from src.studio.pass2_refiner import Pass2Refiner
from src.studio.pass2_refiner import (
    RefinerFactory,
    ComfyRefiner,
    BaseRefiner,
    PassthroughRefiner,
    RefinementSpec,
    RefinementResult,
    RefinementMethod,
    RefinementQuality,
    RefinementProgress,
)
from src.studio.rife_interpolator import (
    BaseInterpolator,
    ComfyRIFEInterpolator,
    InterpolatorFactory,
    InterpolationSpec,
    InterpolationResult,
)
from src.sonic.lip_sync import (
    BaseLipSyncEngine,
    LipSyncFactory,
    LipSyncSpec,
    LipSyncResult,
    DialogueSegment,
    PassthroughLipSyncEngine,
)

# =============================================================================
# IMPORTS - Audit (Quality Control)
# =============================================================================

from src.audit.identity_checker import (
    BaseIdentityChecker,
    ArcFaceIdentityChecker,
    MockIdentityChecker,
    get_identity_checker,
)
from src.audit.physics_checker import (
    BasePhysicsChecker,
    get_physics_checker,
)
from src.audit.reviewer import (
    Reviewer,
    ReviewRequest,
    ReviewResult,
    get_reviewer,
)

# =============================================================================
# IMPORTS - Sonic (Audio Engine) - Optional
# =============================================================================

try:
    from src.sonic.mixer import AudioMixer
    from src.sonic.tts_engine import (
        BaseTTSEngine,
        get_tts_engine,
        synthesize_batch,
    )
    from src.sonic.ambience import (
        BaseAmbienceEngine,
        get_ambience_engine,
        MockAmbienceEngine,
    )
    from src.sonic.foley import (
        BaseFoleyEngine,
        get_foley_engine,
        MockFoleyEngine,
    )
    from src.sonic.ambience import AmbienceProvider
    from src.sonic.foley import FoleyProvider
    from src.sonic.types import (
        TTSProvider,
        DialogueLine,
        SynthesizedDialogue,
        VoiceConfig,
        AmbienceSpec,
        AmbienceType,
        SynthesizedAmbience,
        FoleyEvent,
        FoleyCategory,
        SynthesizedFoley,
        AudioGenerationStatus,
    )
    SONIC_AVAILABLE = True
except ImportError:
    SONIC_AVAILABLE = False

# =============================================================================
# IMPORTS - Post-Production - Optional
# =============================================================================

try:
    from src.post.color_match import ColorMatcher, ColorProfile, ColorMatchResult
    from src.post.audio_ducker import AudioDucker, DuckingParams, DuckResult
    from src.post.stitcher import Stitcher
    from src.post import (
        VideoClip,
        AudioTrack,
        AudioTrackType,
        TransitionSpec,
        TransitionType,
        StitchJob,
        StitchResult,
        ColorMatchMethod,
    )
    POST_AVAILABLE = True
except ImportError:
    POST_AVAILABLE = False


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(verbose: bool = False, log_file: Optional[Path] = None) -> None:
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    
    # Rich format with timestamps
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    datefmt = "%H:%M:%S"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Optional file logging
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )
    
    # Quiet noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("ultralytics").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# =============================================================================
# PIPELINE CONFIGURATION
# =============================================================================

class PipelineMode(str, Enum):
    """Pipeline execution modes."""
    FULL = "full"           # Complete pipeline: video + audio + post
    VIDEO_ONLY = "video"    # Video generation only
    AUDIO_ONLY = "audio"    # Audio generation only (requires existing video)
    POST_ONLY = "post"      # Post-production only (requires video + audio)


@dataclass
class PipelineConfig:
    """
    Configuration for pipeline execution.
    
    Centralizes all pipeline options in one place.
    """
    # Execution mode
    mode: PipelineMode = PipelineMode.FULL
    dry_run: bool = False
    
    # Quality settings
    quality: str = "standard"  # draft, standard, high
    pacing_style: PacingStyle = PacingStyle.NORMAL
    
    # Feature toggles
    enable_bridge: bool = True
    enable_audit: bool = True
    enable_audio: bool = True
    enable_post: bool = True
    enable_pass2: bool = True
    enable_lipsync: bool = True
    enable_interpolation: bool = True
    
    # Interpolation settings
    target_fps: int = 24  # 12fps Ã¢â€ â€™ 24fps (multiplier = 2)
    
    # Retry settings
    max_reroll_attempts: int = 3
    
    # Output
    output_dir: Optional[Path] = None
    
    # Resume
    resume_from_checkpoint: bool = True
    
    def to_generation_config(self) -> GenerationConfig:
        """Convert to Pass1Generator config."""
        return GenerationConfig(
            max_reroll_attempts=self.max_reroll_attempts,
            enable_audit=self.enable_audit,
            enable_bridge=self.enable_bridge,
            quality=self.quality,
            output_dir=self.output_dir,
        )


# =============================================================================
# PIPELINE RESULTS
# =============================================================================

@dataclass
class SceneResult:
    """Result of generating a scene."""
    scene_id: str
    status: JobStatus
    shot_outputs: List[ShotOutput] = field(default_factory=list)
    audio_path: Optional[Path] = None
    error: Optional[str] = None
    duration_sec: float = 0.0
    
    @property
    def success(self) -> bool:
        return self.status == JobStatus.COMPLETE
    
    @property
    def video_paths(self) -> List[Path]:
        """All video paths from all shots."""
        paths = []
        for shot in self.shot_outputs:
            paths.extend(shot.video_paths)
        return paths


@dataclass 
class PipelineResult:
    """Result of running the full pipeline."""
    project_id: str
    status: JobStatus
    scenes_attempted: int = 0
    scenes_succeeded: int = 0
    scenes_failed: int = 0
    scene_results: List[SceneResult] = field(default_factory=list)
    final_output_path: Optional[Path] = None
    total_duration_sec: float = 0.0
    total_cost_estimate: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Percentage of scenes that succeeded."""
        if self.scenes_attempted == 0:
            return 0.0
        return 100.0 * self.scenes_succeeded / self.scenes_attempted
    
    @property
    def all_succeeded(self) -> bool:
        """Did all scenes succeed?"""
        return self.scenes_failed == 0 and self.scenes_attempted > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "status": self.status.value,
            "scenes_attempted": self.scenes_attempted,
            "scenes_succeeded": self.scenes_succeeded,
            "scenes_failed": self.scenes_failed,
            "success_rate": self.success_rate,
            "total_duration_sec": self.total_duration_sec,
            "total_cost_estimate": self.total_cost_estimate,
            "final_output_path": str(self.final_output_path) if self.final_output_path else None,
        }


# =============================================================================
# PROGRESS TRACKING
# =============================================================================

@dataclass
class PipelineProgress:
    """Progress update for the full pipeline."""
    stage: str
    progress: float  # 0.0 to 1.0
    message: str
    scene_id: Optional[str] = None
    shot_id: Optional[str] = None
    chunk_id: Optional[str] = None
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None


class ProgressTracker:
    """
    Tracks and reports pipeline progress.
    
    Aggregates progress from multiple stages into unified reporting.
    """
    
    def __init__(self, callback: Optional[Callable[[PipelineProgress], None]] = None):
        self.callback = callback
        self.start_time = time.time()
        self._total_chunks = 0
        self._completed_chunks = 0
    
    def set_total_chunks(self, count: int) -> None:
        """Set total chunks for progress calculation."""
        self._total_chunks = count
    
    def report(
        self,
        stage: str,
        progress: float,
        message: str,
        scene_id: Optional[str] = None,
        shot_id: Optional[str] = None,
        chunk_id: Optional[str] = None,
    ) -> None:
        """Report progress update."""
        elapsed = time.time() - self.start_time
        
        # Estimate ETA
        eta = None
        if progress > 0:
            eta = (elapsed / progress) * (1 - progress)
        
        update = PipelineProgress(
            stage=stage,
            progress=progress,
            message=message,
            scene_id=scene_id,
            shot_id=shot_id,
            chunk_id=chunk_id,
            elapsed_sec=elapsed,
            eta_sec=eta,
        )
        
        # Log
        logger.info(f"[{progress*100:.1f}%] {stage}: {message}")
        
        # Callback
        if self.callback:
            self.callback(update)
    
    def chunk_completed(self) -> None:
        """Mark a chunk as completed."""
        self._completed_chunks += 1
    
    @property
    def overall_progress(self) -> float:
        """Overall progress based on chunks."""
        if self._total_chunks == 0:
            return 0.0
        return self._completed_chunks / self._total_chunks


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class ContinuumOrchestrator:
    """
    The conductor that coordinates all pipeline components.
    
    This is the "main loop" that:
    1. Loads project (SceneGraph, ConsistencyDict, WorldState)
    2. Initializes all pipeline components
    3. Processes scenes/shots/chunks in order
    4. Coordinates video, audio, and post-production
    5. Manages checkpoints for crash recovery
    
    The orchestrator does NOT:
    - Parse scripts (that's a pre-processing step)
    - Generate video directly (that's Pass1Generator + Renderer)
    - Make aesthetic decisions (that's in the prompts/scene graph)
    
    Usage:
        async with ContinuumOrchestrator(config=pipeline_config) as orchestrator:
            await orchestrator.setup(project_path)
            result = await orchestrator.run()
    """
    
    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable[[PipelineProgress], None]] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
        """
        self.pipeline_config = config or PipelineConfig()
        self.config = get_config()  # System config
        
        # Progress tracking
        self.progress = ProgressTracker(progress_callback)
        
        # Director components (planning)
        self.scene_graph: Optional[SceneGraph] = None
        self.consistency_dict: Optional[ConsistencyDict] = None
        self.world_state: Optional[WorldState] = None
        self.pacer: Optional[Pacer] = None
        self.shot_event_parser: Optional[ShotEventParser] = None
        
        # Studio components (generation)
        self.renderer: Optional[BaseRenderer] = None
        self.bridge_engine: Optional[BaseBridgeEngine] = None
        self.pass1_generator: Optional[Pass1Generator] = None
        self.pass2_refiner: Optional[BaseRefiner] = None
        self.lip_sync_engine: Optional[BaseLipSyncEngine] = None
        self.interpolator: Optional[BaseInterpolator] = None
        
        # Audit components (verification)
        self.reviewer: Optional[Reviewer] = None
        
        # Sonic components (audio) - Track B
        self.tts_engine: Optional[BaseTTSEngine] = None
        self.ambience_engine: Optional[BaseAmbienceEngine] = None
        self.foley_engine: Optional[BaseFoleyEngine] = None
        self.audio_mixer: Optional[AudioMixer] = None
        
        # Post components (final assembly)
        # Note: Using Any type hint because these imports are conditional
        self.color_matcher: Optional[Any] = None  # ColorMatcher when available
        self.audio_ducker: Optional[Any] = None   # AudioDucker when available
        self.stitcher: Optional[Any] = None       # Stitcher when available
        
        # Infrastructure
        self.checkpoint_manager: Optional[CheckpointManager] = None
        
        # State
        self._initialized = False
    
    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------
    
    async def setup(
        self,
        project_path: Path,
        consistency_path: Optional[Path] = None,
        world_state_path: Optional[Path] = None,
    ) -> None:
        """
        Initialize all components and load project.
        
        Args:
            project_path: Path to scene graph JSON
            consistency_path: Path to consistency dict JSON (optional)
            world_state_path: Path to world state JSON (optional)
        """
        logger.info("=" * 70)
        logger.info("CONTINUUM ENGINE v2.0 - Setup")
        logger.info("=" * 70)
        
        self.progress.report("setup", 0.0, "Loading project...")
        
        # -----------------------------------------------------------------
        # 1. Load Scene Graph (structure)
        # -----------------------------------------------------------------
        logger.info(f"Loading scene graph: {project_path}")
        self.scene_graph = SceneGraph.load(project_path)
        
        logger.info(f"  Project: {self.scene_graph.title}")
        logger.info(f"  Scenes: {self.scene_graph.scene_count}")
        logger.info(f"  Shots: {self.scene_graph.shot_count}")
        logger.info(f"  Estimated Duration: {self.scene_graph.total_duration_min:.1f} min")
        
        # Calculate total chunks for progress tracking
        total_chunks = sum(
            len(shot.chunks) 
            for shot in self.scene_graph.iter_shots()
        )
        self.progress.set_total_chunks(total_chunks)
        logger.info(f"  Total Chunks: {total_chunks}")
        
        self.progress.report("setup", 0.1, "Loading consistency dictionary...")
        
        # -----------------------------------------------------------------
        # 2. Load Consistency Dictionary (identity)
        # -----------------------------------------------------------------
        if consistency_path and consistency_path.exists():
            logger.info(f"Loading consistency dict: {consistency_path}")
            self.consistency_dict = ConsistencyDict.load(consistency_path)
        else:
            logger.info("Creating empty consistency dict")
            self.consistency_dict = ConsistencyDict()
        
        logger.info(f"  Characters: {len(self.consistency_dict.list_characters())}")
        logger.info(f"  Locations: {len(self.consistency_dict.list_locations())}")
        logger.info(f"  Props: {len(self.consistency_dict.list_props())}")
        
        self.progress.report("setup", 0.15, "Initializing world state...")
        
        # -----------------------------------------------------------------
        # 3. Load or Create World State (dynamics)
        # -----------------------------------------------------------------
        if world_state_path and world_state_path.exists():
            logger.info(f"Loading world state: {world_state_path}")
            self.world_state = WorldState.load(world_state_path)
        else:
            logger.info("Creating new world state")
            self.world_state = create_world_state(
                project_id=self.scene_graph.project_id
            )
        
        logger.info(f"  Tracked Objects: {len(self.world_state.get_all_objects())}")
        logger.info(f"  Events: {len(self.world_state._events)}")
        
        # Initialize shot event parser (extracts state changes from descriptions)
        self.shot_event_parser = get_shot_event_parser(
            enable_pattern_matching=True,
            enable_explicit_events=True,
        )
        logger.info("  Shot Event Parser: Enabled (pattern + explicit)")
        
        self.progress.report("setup", 0.2, "Initializing pacer...")
        
        # -----------------------------------------------------------------
        # 4. Initialize Pacer (timing)
        # -----------------------------------------------------------------
        self.pacer = get_pacer(
            max_chunk_duration_sec=self.config.generation.max_shot_duration_sec,
            pacing_style=self.pipeline_config.pacing_style,
        )
        logger.info(f"  Pacing Style: {self.pipeline_config.pacing_style.value}")
        logger.info(f"  Max Chunk Duration: {self.config.generation.max_shot_duration_sec}s")
        
        self.progress.report("setup", 0.3, "Initializing renderer...")
        
        # -----------------------------------------------------------------
        # 5. Initialize Renderer
        # -----------------------------------------------------------------
        if self.pipeline_config.dry_run:
            logger.info("DRY RUN: Using mock renderer")
            self.renderer = get_renderer(RendererType.MOCK)
        else:
            logger.info(f"Initializing WanRenderer (host={self.config.comfyui.host})")
            self.renderer = WanRenderer()
            await self.renderer.initialize()
        
        self.progress.report("setup", 0.4, "Initializing bridge engine...")
        
        # -----------------------------------------------------------------
        # 6. Initialize Bridge Engine
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_bridge:
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using mock bridge engine")
                self.bridge_engine = MockBridgeEngine()
            else:
                logger.info("Initializing ComfyUI Bridge Engine")
                self.bridge_engine = get_bridge_engine(use_mock=False)
                await self.bridge_engine.initialize()
        
        self.progress.report("setup", 0.5, "Initializing audit system...")
        
        # -----------------------------------------------------------------
        # 7. Initialize Audit System (Reviewer)
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_audit:
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using mock reviewer")
                self.reviewer = get_reviewer(use_mock=True)
            else:
                logger.info("Initializing full audit system")
                self.reviewer = get_reviewer(use_mock=False)
        
        self.progress.report("setup", 0.6, "Initializing Pass 1 generator...")
        
        # -----------------------------------------------------------------
        # 8. Initialize Pass1 Generator (orchestrates rendering)
        # -----------------------------------------------------------------
        gen_config = self.pipeline_config.to_generation_config()
        gen_config.output_dir = (
            self.pipeline_config.output_dir or 
            self.config.paths.output_dir / self.scene_graph.project_id / "pass1"
        )
        gen_config.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.pass1_generator = Pass1Generator(
            renderer=self.renderer,
            bridge_engine=self.bridge_engine,
            reviewer=self.reviewer,
            consistency_dict=self.consistency_dict,
            world_state=self.world_state,
            config=gen_config,
        )
        
        logger.info(f"  Output Dir: {gen_config.output_dir}")
        logger.info(f"  Max Rerolls: {gen_config.max_reroll_attempts}")
        
        self.progress.report("setup", 0.62, "Initializing Pass 2 refiner...")
        
        # -----------------------------------------------------------------
        # 9. Initialize Pass 2 Refiner
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_pass2:
            refine_output = (
                self.pipeline_config.output_dir or
                self.config.paths.output_dir
            ) / self.scene_graph.project_id / "refined"
            refine_output.mkdir(parents=True, exist_ok=True)
            
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using passthrough refiner")
                self.pass2_refiner = PassthroughRefiner(refine_output)
            else:
                logger.info("Initializing Refiner Factory")
                factory = RefinerFactory(
                    comfy_host=self.config.comfyui.host,
                    output_dir=refine_output,
                )
                self.pass2_refiner = await factory.get_refiner()
            
            logger.info(f"  Refinement Output: {refine_output}")
            logger.info(f"  Method: {self.pass2_refiner.method.value if hasattr(self.pass2_refiner, 'method') else 'passthrough'}")
        
        self.progress.report("setup", 0.65, "Initializing lip sync engine...")
        
        # -----------------------------------------------------------------
        # 10. Initialize Lip Sync Engine
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_lipsync:
            lipsync_output = (
                self.pipeline_config.output_dir or
                self.config.paths.output_dir
            ) / self.scene_graph.project_id / "lipsync"
            lipsync_output.mkdir(parents=True, exist_ok=True)
            
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using passthrough lip sync")
                self.lip_sync_engine = PassthroughLipSyncEngine(lipsync_output)
            else:
                logger.info("Initializing Lip Sync Factory")
                factory = LipSyncFactory(
                    comfy_host=self.config.comfyui.host,
                    output_dir=lipsync_output,
                )
                self.lip_sync_engine = await factory.get_engine()
            
            logger.info(f"  Lip Sync Output: {lipsync_output}")
        
        self.progress.report("setup", 0.7, "Initializing frame interpolator...")
        
        # -----------------------------------------------------------------
        # 10. Initialize RIFE Interpolator
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_interpolation:
            interp_output = (
                self.pipeline_config.output_dir or
                self.config.paths.output_dir
            ) / self.scene_graph.project_id / "interpolated"
            interp_output.mkdir(parents=True, exist_ok=True)
            
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using passthrough interpolator")
                from src.studio.rife_interpolator import PassthroughInterpolator
                self.interpolator = PassthroughInterpolator(interp_output)
            else:
                logger.info("Initializing Interpolator Factory")
                factory = InterpolatorFactory(
                    comfy_host=self.config.comfyui.host,
                    output_dir=interp_output,
                )
                self.interpolator = await factory.get_interpolator()
            
            logger.info(f"  Interpolation Output: {interp_output}")
            logger.info(f"  Target FPS: {self.pipeline_config.target_fps}")
        
        self.progress.report("setup", 0.75, "Initializing audio system...")
        
        # -----------------------------------------------------------------
        # 11. Initialize Audio System (Track B - optional)
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_audio and SONIC_AVAILABLE:
            audio_output = (
                self.pipeline_config.output_dir or
                self.config.paths.output_dir
            ) / self.scene_graph.project_id / "audio"
            audio_output.mkdir(parents=True, exist_ok=True)
            
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Using mock audio engines")
                self.ambience_engine = MockAmbienceEngine(audio_output / "ambience")
                self.foley_engine = MockFoleyEngine(audio_output / "foley")
                # TTS is API-only, skip in dry run
            else:
                logger.info("Initializing audio engines")
                
                # TTS Engine (for dialogue synthesis)
                try:
                    self.tts_engine = get_tts_engine(
                        TTSProvider.ELEVENLABS,
                        output_dir=audio_output / "dialogue",
                        api_key=os.environ.get("ELEVENLABS_API_KEY"),
                    )
                    logger.info("  TTS: ElevenLabs")
                except Exception as e:
                    logger.warning(f"  TTS: Failed to initialize ({e}), dialogue disabled")
                
                # Ambience Engine (for background sounds)
                try:
                    self.ambience_engine = get_ambience_engine(
                        AmbienceProvider.REPLICATE,
                        output_dir=audio_output / "ambience",
                        api_token=os.environ.get("REPLICATE_API_TOKEN"),
                    )
                    logger.info("  Ambience: Replicate AudioLDM")
                except Exception as e:
                    logger.warning(f"  Ambience: Failed ({e}), using mock")
                    self.ambience_engine = MockAmbienceEngine(audio_output / "ambience")
                
                # Foley Engine (for sound effects)
                try:
                    self.foley_engine = get_foley_engine(
                        FoleyProvider.FREESOUND,
                        output_dir=audio_output / "foley",
                        api_key=os.environ.get("FREESOUND_API_KEY"),
                    )
                    logger.info("  Foley: Freesound")
                except Exception as e:
                    logger.warning(f"  Foley: Failed ({e}), using mock")
                    self.foley_engine = MockFoleyEngine(audio_output / "foley")
                
                # Audio Mixer (combines all tracks)
                self.audio_mixer = AudioMixer(output_dir=audio_output / "mixed")
                logger.info("  Mixer: FFmpeg-based")
            
            logger.info(f"  Audio Output: {audio_output}")
        elif not SONIC_AVAILABLE:
            logger.info("Audio system not available (missing dependencies)")
        
        self.progress.report("setup", 0.82, "Initializing post-production...")
        
        # -----------------------------------------------------------------
        # 13. Initialize Post-Production Components
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_post and POST_AVAILABLE:
            post_output = (
                self.pipeline_config.output_dir or
                self.config.paths.output_dir
            ) / self.scene_graph.project_id / "post"
            post_output.mkdir(parents=True, exist_ok=True)
            
            # Color Matcher - normalizes colors across shots
            self.color_matcher = ColorMatcher(
                method=ColorMatchMethod.MEAN_STD,  # Fast and good enough
                temp_dir=post_output / "color_temp",
            )
            logger.info("  Color Matcher: Mean/Std method")
            
            # Audio Ducker - lowers music during dialogue
            self.audio_ducker = AudioDucker(
                default_params=DuckingParams.standard(),
            )
            logger.info("  Audio Ducker: Standard preset (-12dB)")
            
            # Stitcher - final video assembly
            self.stitcher = Stitcher(
                temp_dir=post_output / "stitch_temp",
            )
            logger.info("  Stitcher: FFmpeg-based")
            
            logger.info(f"  Post Output: {post_output}")
        elif not POST_AVAILABLE:
            logger.info("Post-production not available (missing dependencies)")
        
        self.progress.report("setup", 0.85, "Initializing checkpoint system...")
        
        # -----------------------------------------------------------------
        # 10. Initialize Checkpoint Manager
        # -----------------------------------------------------------------
        checkpoint_dir = self.config.paths.checkpoint_dir / self.scene_graph.project_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        logger.info(f"  Checkpoint Dir: {checkpoint_dir}")
        
        self._initialized = True
        
        self.progress.report("setup", 1.0, "Setup complete!")
        logger.info("=" * 70)
    
    async def teardown(self) -> None:
        """Clean up all resources."""
        logger.info("Shutting down...")
        
        if self.renderer:
            await self.renderer.shutdown()
        if self.bridge_engine:
            await self.bridge_engine.shutdown()
        if self.pass2_refiner and hasattr(self.pass2_refiner, 'shutdown'):
            await self.pass2_refiner.shutdown()
        if self.lip_sync_engine and hasattr(self.lip_sync_engine, 'shutdown'):
            await self.lip_sync_engine.shutdown()
        if self.interpolator and hasattr(self.interpolator, 'shutdown'):
            await self.interpolator.shutdown()
        if self.reviewer:
            # Reviewer may have async cleanup
            pass
        
        # Save world state for resume
        if self.world_state and self.pipeline_config.output_dir:
            state_path = self.pipeline_config.output_dir / "world_state.json"
            self.world_state.save(state_path)
            logger.info(f"World state saved: {state_path}")
        
        self._initialized = False
        logger.info("Shutdown complete")
    
    async def __aenter__(self) -> "ContinuumOrchestrator":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.teardown()
    
    # -------------------------------------------------------------------------
    # MAIN PIPELINE
    # -------------------------------------------------------------------------
    
    async def run(
        self,
        scene_ids: Optional[List[str]] = None,
        shot_ids: Optional[List[str]] = None,
    ) -> PipelineResult:
        """
        Run the complete generation pipeline.
        
        Args:
            scene_ids: Specific scenes to generate (None = all)
            shot_ids: Specific shots to generate (None = all)
            
        Returns:
            PipelineResult with outcomes
        """
        if not self._initialized:
            raise RuntimeError("Orchestrator not initialized. Call setup() first.")
        
        start_time = time.time()
        
        logger.info("=" * 70)
        logger.info("PIPELINE START")
        logger.info("=" * 70)
        
        result = PipelineResult(
            project_id=self.scene_graph.project_id,
            status=JobStatus.GENERATING,
        )
        
        try:
            # -----------------------------------------------------------------
            # Phase 1: Video Generation (Pass 1)
            # -----------------------------------------------------------------
            if self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.VIDEO_ONLY]:
                self.progress.report("video", 0.0, "Starting video generation...")
                
                scene_results = await self._run_video_generation(
                    scene_ids=scene_ids,
                    shot_ids=shot_ids,
                )
                result.scene_results = scene_results
                result.scenes_attempted = len(scene_results)
                result.scenes_succeeded = sum(1 for s in scene_results if s.success)
                result.scenes_failed = result.scenes_attempted - result.scenes_succeeded
            
            # -----------------------------------------------------------------
            # Phase 2: Pass 2 Refinement (optional)
            # -----------------------------------------------------------------
            if (self.pipeline_config.enable_pass2 and 
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.VIDEO_ONLY]):
                self.progress.report("refine", 0.0, "Running Pass 2 refinement...")
                await self._run_pass2_refinement(result.scene_results)
            
            # -----------------------------------------------------------------
            # Phase 2.4: TTS Dialogue Synthesis (required for Lip Sync)
            # -----------------------------------------------------------------
            # TTS runs BEFORE Lip Sync because lip sync needs dialogue audio
            # to know when/how to animate mouths
            if (self.pipeline_config.enable_audio and
                self.pipeline_config.enable_lipsync and
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.VIDEO_ONLY]):
                self.progress.report("tts", 0.0, "Synthesizing dialogue...")
                await self._run_tts_synthesis(result.scene_results)
            
            # -----------------------------------------------------------------
            # Phase 2.5: Lip Sync (optional)
            # -----------------------------------------------------------------
            if (self.pipeline_config.enable_lipsync and
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.VIDEO_ONLY]):
                self.progress.report("lipsync", 0.0, "Running lip sync...")
                await self._run_lip_sync(result.scene_results)
            
            # -----------------------------------------------------------------
            # Phase 2.6: Frame Interpolation (optional)
            # -----------------------------------------------------------------
            if (self.pipeline_config.enable_interpolation and
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.VIDEO_ONLY]):
                self.progress.report("interpolate", 0.0, "Running RIFE interpolation...")
                await self._run_interpolation(result.scene_results)
            
            # -----------------------------------------------------------------
            # Phase 3: Audio Generation (optional)
            # -----------------------------------------------------------------
            if (self.pipeline_config.enable_audio and 
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.AUDIO_ONLY]):
                self.progress.report("audio", 0.0, "Generating audio...")
                await self._run_audio_generation(result.scene_results)
            
            # -----------------------------------------------------------------
            # Phase 4: Post-Production (optional)
            # -----------------------------------------------------------------
            if (self.pipeline_config.enable_post and 
                self.pipeline_config.mode in [PipelineMode.FULL, PipelineMode.POST_ONLY]):
                self.progress.report("post", 0.0, "Running post-production...")
                final_path = await self._run_post_production(result.scene_results)
                result.final_output_path = final_path
            
            # Set final status
            result.status = JobStatus.COMPLETE if result.all_succeeded else JobStatus.FAILED
            
        except Exception as e:
            logger.exception("Pipeline failed with unexpected error")
            result.status = JobStatus.FAILED
        
        # Calculate totals
        result.total_duration_sec = time.time() - start_time
        result.total_cost_estimate = self._calculate_total_cost(result.scene_results)
        
        # Log summary
        logger.info("=" * 70)
        logger.info("PIPELINE COMPLETE")
        logger.info(f"  Status: {result.status.value}")
        logger.info(f"  Scenes: {result.scenes_succeeded}/{result.scenes_attempted} succeeded")
        logger.info(f"  Duration: {result.total_duration_sec:.1f}s")
        logger.info(f"  Est. Cost: ${result.total_cost_estimate:.2f}")
        if result.final_output_path:
            logger.info(f"  Output: {result.final_output_path}")
        logger.info("=" * 70)
        
        return result
    
    # -------------------------------------------------------------------------
    # VIDEO GENERATION (PHASE 1)
    # -------------------------------------------------------------------------
    
    async def _run_video_generation(
        self,
        scene_ids: Optional[List[str]],
        shot_ids: Optional[List[str]],
    ) -> List[SceneResult]:
        """
        Run Pass 1 video generation for all scenes.
        """
        scene_results = []
        
        # Get scenes to process
        scenes = self._get_scenes_to_process(scene_ids)
        
        logger.info(f"Processing {len(scenes)} scene(s)")
        
        for i, scene in enumerate(scenes):
            scene_start = time.time()
            
            logger.info(f"\n{'='*40}")
            logger.info(f"SCENE {i+1}/{len(scenes)}: {scene.scene_id}")
            logger.info(f"  Title: {scene.title}")
            logger.info(f"  Shots: {len(scene.shots)}")
            logger.info(f"{'='*40}")
            
            # Setup world state for scene
            self._setup_scene_world_state(scene)
            
            # Process shots in scene
            shot_outputs = []
            shots_to_process = self._filter_shots(scene.shots, shot_ids)
            previous_chunk: Optional[ChunkOutput] = None  # Track for shot-to-shot bridge
            
            for j, shot in enumerate(shots_to_process):
                logger.info(f"\n--- Shot {j+1}/{len(shots_to_process)}: {shot.shot_id} ---")
                
                # Calculate progress
                overall_progress = (i + j / len(shots_to_process)) / len(scenes)
                self.progress.report(
                    "video",
                    overall_progress,
                    f"Generating shot {shot.shot_id}",
                    scene_id=scene.scene_id,
                    shot_id=shot.shot_id,
                )
                
                # Generate shot using Pass1Generator
                shot_output = await self.pass1_generator.generate_shot(
                    shot=shot,
                    scene=scene,
                    previous_shot_output=previous_chunk,  # Bridge from previous shot
                    progress_callback=self._create_generation_callback(scene.scene_id),
                )
                
                shot_outputs.append(shot_output)
                # Track last chunk for next shot's bridge frame
                if shot_output.chunk_outputs:
                    previous_chunk = shot_output.chunk_outputs[-1]
                
                # Update world state with any events from this shot
                self._update_world_state_from_shot(shot, shot_output)
                
                # Update progress tracker
                for _ in shot_output.chunk_outputs:
                    self.progress.chunk_completed()
                
                # Log result
                if shot_output.all_success:
                    logger.info(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ Shot {shot.shot_id}: {len(shot_output.chunk_outputs)} chunks")
                else:
                    logger.warning(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬â€ Shot {shot.shot_id} had failures")
            
            # Build scene result
            scene_duration = time.time() - scene_start
            scene_success = all(s.all_success for s in shot_outputs)
            
            scene_result = SceneResult(
                scene_id=scene.scene_id,
                status=JobStatus.COMPLETE if scene_success else JobStatus.FAILED,
                shot_outputs=shot_outputs,
                duration_sec=scene_duration,
            )
            scene_results.append(scene_result)
            
            # Checkpoint scene completion
            if self.checkpoint_manager:
                self.checkpoint_manager.mark_scene_complete(scene.scene_id)
        
        return scene_results
    
    def _get_scenes_to_process(self, scene_ids: Optional[List[str]]) -> List[Scene]:
        """Get scenes to process, filtering by IDs and checkpoints."""
        all_scenes = list(self.scene_graph.iter_scenes())
        
        # Filter by specific scene IDs
        if scene_ids:
            all_scenes = [s for s in all_scenes if s.scene_id in scene_ids]
        
        # Filter out completed scenes if resuming
        if self.pipeline_config.resume_from_checkpoint and self.checkpoint_manager:
            completed = self.checkpoint_manager.get_completed_scenes()
            all_scenes = [s for s in all_scenes if s.scene_id not in completed]
        
        return all_scenes
    
    def _filter_shots(
        self, 
        shots: List[Shot], 
        shot_ids: Optional[List[str]],
    ) -> List[Shot]:
        """Filter shots by IDs."""
        if shot_ids:
            return [s for s in shots if s.shot_id in shot_ids]
        return shots
    
    def _setup_scene_world_state(self, scene: Scene) -> None:
        """Setup world state for a scene."""
        if not self.world_state:
            return
        
        # Check if scene setup already exists
        existing = self.world_state.get_scene_setup(scene.scene_id)
        if existing:
            logger.debug(f"Using existing world state for {scene.scene_id}")
            return
        
        # Create initial object positions from scene metadata
        initial_objects = {}
        
        # Props in scene get default positions
        for shot in scene.shots:
            for prop in shot.props:
                if prop.entity_id not in initial_objects:
                    initial_objects[prop.entity_id] = TrackedObject(
                        entity_id=prop.entity_id,
                        entity_type="prop",
                        position=Position.named("scene_default"),
                    )
        
        setup = SceneSetup(
            scene_id=scene.scene_id,
            location_id=scene.location.entity_id if scene.location else "unknown",
            initial_objects=initial_objects,
        )
        
        self.world_state.setup_scene(setup)
    
    def _update_world_state_from_shot(
        self, 
        shot: Shot, 
        output: ShotOutput,
    ) -> None:
        """
        Update world state based on shot events.
        
        This is called AFTER each shot is rendered successfully.
        It parses the shot description and explicit events to extract
        state changes, then applies them to the world state.
        
        Data flow:
            Shot.description ──┐
                               ├── ShotEventParser ──► List[StateEvent]
            Shot.events ───────┘                              │
                                                              ▼
                                                    WorldState.apply_event()
        
        Why after rendering (not before):
            - Events represent what HAPPENED in the shot
            - The shot was successfully rendered, so the events occurred
            - Next shot's prompt generation uses updated world state
        
        Args:
            shot: The shot that was just rendered
            output: The render output (not currently used, but available
                    for future video analysis integration)
        """
        if not self.world_state:
            return
        
        if not self.shot_event_parser:
            logger.debug(f"World state update for {shot.shot_id} (no parser)")
            return
        
        # Build known entities set from multiple sources
        known_entities = self._collect_known_entities(shot)
        
        # Parse events from shot (description + explicit events)
        try:
            parsed_events = self.shot_event_parser.parse_shot(
                shot_id=shot.shot_id,
                description=shot.description,
                metadata={"events": shot.events} if shot.events else {},
                known_entities=known_entities,
                characters=shot.character_ids,
                props=shot.prop_ids,
            )
        except Exception as e:
            logger.warning(f"Failed to parse events for {shot.shot_id}: {e}")
            return
        
        if not parsed_events:
            logger.debug(f"World state: {shot.shot_id} - no state changes detected")
            return
        
        # Apply each event to world state
        for event in parsed_events:
            try:
                self.world_state.apply_event(event)
                logger.debug(
                    f"World state: {event.event_type.value} {event.entity_id} "
                    f"in {shot.shot_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to apply event {event.event_id} to world state: {e}"
                )
        
        logger.info(
            f"World state updated: {shot.shot_id} - "
            f"{len(parsed_events)} event(s) applied"
        )
    
    def _collect_known_entities(self, shot: Shot) -> set:
        """
        Collect all known entity IDs for event parsing.
        
        Gathers entities from:
        1. Shot participants (characters, props, location)
        2. Consistency dictionary (all registered entities)
        3. Current world state (dynamically tracked objects)
        
        This comprehensive set helps the parser resolve entity names
        from natural language descriptions.
        """
        known = set()
        
        # From shot definition
        known.update(shot.all_entity_ids)
        
        # From consistency dictionary
        if self.consistency_dict:
            known.update(c.entity_id for c in self.consistency_dict.list_characters())
            known.update(loc.entity_id for loc in self.consistency_dict.list_locations())
            known.update(p.entity_id for p in self.consistency_dict.list_props())
        
        # From current world state
        if self.world_state:
            known.update(self.world_state.get_all_objects().keys())
        
        return known
    
    def _create_generation_callback(
        self, 
        scene_id: str,
    ) -> Callable[[GenerationProgress], None]:
        """Create progress callback for generation."""
        def callback(gen_progress: GenerationProgress):
            self.progress.report(
                stage=f"video.{gen_progress.stage.value}",
                progress=gen_progress.progress,
                message=gen_progress.message,
                scene_id=scene_id,
                chunk_id=gen_progress.chunk_id,
            )
        return callback
    
    # -------------------------------------------------------------------------
    # PASS 2 REFINEMENT (PHASE 2)
    # -------------------------------------------------------------------------
    
    async def _run_pass2_refinement(
        self, 
        scene_results: List[SceneResult],
    ) -> None:
        """
        Run Pass 2 vid2vid refinement on all generated videos.
        
        Pass 2 reduces AI "flicker" and improves temporal consistency
        without changing the structure or composition from Pass 1.
        
        Data flow:
            Pass 1 video (12fps, flickery) Ã¢â€ â€™ Pass 2 Ã¢â€ â€™ Refined video (12fps, smooth)
        
        Why this step exists:
            - Diffusion models generate each frame semi-independently
            - This causes frame-to-frame inconsistencies (texture flicker, edge jitter)
            - Vid2vid refinement uses temporal context to smooth these artifacts
            - Low denoise (0.3-0.5) preserves structure while fixing flicker
        
        Architecture note:
            This runs BEFORE Lip Sync because:
            1. Lip sync modifies mouth regions - we want those modifications
               applied to already-smooth video
            2. Flicker in mouth area would make lip sync harder
        """
        if not self.pass2_refiner:
            logger.info("Pass 2 refiner not configured, skipping")
            return
        
        # Count total chunks for progress
        total_chunks = sum(
            len(shot_output.chunk_outputs)
            for scene_result in scene_results
            if scene_result.success
            for shot_output in scene_result.shot_outputs
        )
        
        if total_chunks == 0:
            logger.info("No video chunks to refine")
            return
        
        processed = 0
        succeeded = 0
        failed = 0
        
        logger.info(f"Starting Pass 2 refinement: {total_chunks} chunks")
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            scene = self.scene_graph.get_scene(scene_result.scene_id)
            
            for shot_output in scene_result.shot_outputs:
                shot = self.scene_graph.get_shot(shot_output.shot_id)
                
                for chunk_output in shot_output.chunk_outputs:
                    processed += 1
                    progress = processed / total_chunks
                    
                    # Skip if no video was generated
                    if not chunk_output.video_path or not chunk_output.video_path.exists():
                        logger.debug(f"Skipping {chunk_output.chunk_id}: no video")
                        continue
                    
                    self.progress.report(
                        "refine",
                        progress,
                        f"Refining {chunk_output.chunk_id}",
                        scene_id=scene_result.scene_id,
                        shot_id=shot_output.shot_id,
                    )
                    
                    # Build refinement spec
                    output_path = chunk_output.video_path.parent / f"{chunk_output.video_path.stem}_refined.mp4"
                    
                    # Determine quality based on pipeline config
                    quality = self._map_quality_to_refinement(self.pipeline_config.quality)
                    
                    spec = RefinementSpec(
                        input_path=chunk_output.video_path,
                        output_path=output_path,
                        shot_id=shot_output.shot_id,
                        quality=quality,
                        denoise_strength=0.35,  # Low to preserve structure
                        preserve_motion=True,
                        temporal_window=16,
                    )
                    
                    # Create progress callback
                    def refine_progress(rp: RefinementProgress):
                        self.progress.report(
                            f"refine.{rp.stage}",
                            progress + (rp.progress * (1 / total_chunks)),
                            rp.message,
                        )
                    
                    try:
                        result = await self.pass2_refiner.refine(spec, refine_progress)
                        
                        if result.success:
                            # Store refined path on chunk output
                            chunk_output.refined_video_path = result.output_path
                            succeeded += 1
                            logger.info(
                                f"Ã¢Å“â€œ Refined {chunk_output.chunk_id}: "
                                f"{result.method_used.value} ({result.processing_time_sec:.1f}s)"
                            )
                        else:
                            failed += 1
                            logger.warning(
                                f"Ã¢Å“â€” Refinement failed {chunk_output.chunk_id}: {result.error}"
                            )
                            # Keep using original video if refinement fails
                            
                    except Exception as e:
                        failed += 1
                        logger.error(f"Refinement error {chunk_output.chunk_id}: {e}")
                
                # After refining all chunks, update shot-level refined path
                # Use the last chunk's refined video as the "shot" refined video
                # (In practice, shots are usually single-chunk after stitching)
                refined_paths = [
                    c.refined_video_path 
                    for c in shot_output.chunk_outputs 
                    if hasattr(c, 'refined_video_path') and c.refined_video_path
                ]
                if refined_paths:
                    shot_output.refined_video_path = refined_paths[-1]
        
        logger.info(
            f"Pass 2 refinement complete: "
            f"{succeeded} succeeded, {failed} failed, {total_chunks} total"
        )
    
    def _map_quality_to_refinement(self, quality: str) -> RefinementQuality:
        """Map pipeline quality setting to refinement quality."""
        mapping = {
            "draft": RefinementQuality.DRAFT,
            "standard": RefinementQuality.STANDARD,
            "high": RefinementQuality.HIGH,
        }
        return mapping.get(quality.lower(), RefinementQuality.STANDARD)
    
    # -------------------------------------------------------------------------
    # LIP SYNC (PHASE 2.5)
    # -------------------------------------------------------------------------
    
    async def _run_lip_sync(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """
        Run lip sync on all shots with dialogue.
        
        For each shot that has dialogue, syncs the character's mouth movements
        to the pre-generated TTS audio. Shots without dialogue pass through.
        
        Data flow:
            Pass2 video Ã¢â€ â€™ Lip Sync Ã¢â€ â€™ Video with synced mouths
            
        The lip sync engine:
        1. Detects faces in the video
        2. Matches dialogue audio to mouth shapes
        3. Composites synced face back into video
        """
        if not self.lip_sync_engine:
            logger.info("Lip sync engine not configured, skipping")
            return
        
        total_shots = sum(len(sr.shot_outputs) for sr in scene_results)
        processed = 0
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            for shot_output in scene_result.shot_outputs:
                processed += 1
                progress = processed / max(total_shots, 1)
                
                # Get video path (prefer refined, fall back to pass1)
                video_path = self._get_latest_video_path(shot_output)
                if not video_path:
                    logger.warning(f"No video found for shot {shot_output.shot_id}")
                    continue
                
                # Check if shot has dialogue
                dialogue_segments = self._get_dialogue_segments(shot_output)
                if not dialogue_segments:
                    logger.debug(f"Shot {shot_output.shot_id}: No dialogue, skipping lip sync")
                    continue
                
                self.progress.report(
                    "lipsync", 
                    progress,
                    f"Syncing {shot_output.shot_id}",
                )
                
                # Build lip sync spec
                output_path = video_path.parent / f"{video_path.stem}_lipsync{video_path.suffix}"
                
                spec = LipSyncSpec(
                    input_video=video_path,
                    output_video=output_path,
                    shot_id=shot_output.shot_id,
                    dialogue_segments=dialogue_segments,
                )
                
                try:
                    result = await self.lip_sync_engine.sync(spec)
                    
                    if result.success:
                        # Update shot output with lip-synced video path
                        shot_output.lipsync_video_path = result.output_video
                        logger.info(f"Ã¢Å“â€œ Lip sync {shot_output.shot_id}: {result.output_video}")
                    else:
                        logger.warning(f"Ã¢Å“â€” Lip sync {shot_output.shot_id}: {result.error}")
                        
                except Exception as e:
                    logger.error(f"Lip sync failed for {shot_output.shot_id}: {e}")
        
        logger.info(f"Lip sync complete: processed {processed} shots")
    
    def _get_latest_video_path(self, shot_output: ShotOutput) -> Optional[Path]:
        """
        Get the most recent video path for a shot.
        
        Priority: refined Ã¢â€ â€™ pass1
        """
        # Check for refined video first
        if hasattr(shot_output, 'refined_video_path') and shot_output.refined_video_path:
            return shot_output.refined_video_path
        
        # Fall back to pass1 video
        if shot_output.video_paths:
            return shot_output.video_paths[-1]  # Last chunk is full shot
        
        return None
    
    def _get_dialogue_segments(self, shot_output: ShotOutput) -> List[DialogueSegment]:
        """
        Extract dialogue segments for a shot.
        
        In a full implementation, this would come from:
        1. TTS engine output (synthesized audio files)
        2. Scene graph dialogue lines
        3. Timing from pacer
        
        For now, returns empty list (no dialogue) unless shot has audio.
        """
        # TODO: Wire to TTS engine output and scene graph dialogue
        # This is a placeholder - real implementation needs:
        # - Access to synthesized dialogue from TTS engine
        # - Timing information from scene graph
        
        if hasattr(shot_output, 'dialogue_segments'):
            return shot_output.dialogue_segments
        
        return []
    
    # -------------------------------------------------------------------------
    # FRAME INTERPOLATION (PHASE 2.6)
    # -------------------------------------------------------------------------
    
    async def _run_interpolation(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """
        Run RIFE frame interpolation to upscale 12fps Ã¢â€ â€™ 24fps.
        
        This is the LAST GPU-intensive step. After this, we only do
        CPU-based post-production (color grading, audio mixing, stitching).
        
        Why interpolate:
        - AI video models produce 12fps (compute efficient)
        - Human perception needs 24fps (smooth motion)
        - RIFE is cheaper than generating 2x frames
        
        Data flow:
            Lip-synced video (12fps) Ã¢â€ â€™ RIFE Ã¢â€ â€™ Smooth video (24fps)
        """
        if not self.interpolator:
            logger.info("Interpolator not configured, skipping")
            return
        
        target_fps = self.pipeline_config.target_fps
        
        total_shots = sum(len(sr.shot_outputs) for sr in scene_results)
        processed = 0
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            for shot_output in scene_result.shot_outputs:
                processed += 1
                progress = processed / max(total_shots, 1)
                
                # Get video path (prefer lip-synced, then refined, then pass1)
                video_path = self._get_video_for_interpolation(shot_output)
                if not video_path:
                    logger.warning(f"No video found for shot {shot_output.shot_id}")
                    continue
                
                self.progress.report(
                    "interpolate",
                    progress,
                    f"Interpolating {shot_output.shot_id} to {target_fps}fps",
                )
                
                # Build interpolation spec
                output_path = video_path.parent / f"{video_path.stem}_{target_fps}fps{video_path.suffix}"
                
                spec = InterpolationSpec(
                    input_path=video_path,
                    output_path=output_path,
                    shot_id=shot_output.shot_id,  # ADD THIS LINE
                    target_fps=target_fps,
                    source_fps=12,  # Our pipeline standard
                )
                
                try:
                    result = await self.interpolator.interpolate(spec)
                    
                    if result.success:
                        # Update shot output with interpolated video path
                        shot_output.interpolated_video_path = result.output_path
                        logger.info(
                            f"Ã¢Å“â€œ Interpolated {shot_output.shot_id}: "
                            f"{result.source_fps}fps Ã¢â€ â€™ {result.output_fps}fps"
                        )
                    else:
                        logger.warning(f"Ã¢Å“â€” Interpolation {shot_output.shot_id}: {result.error}")
                        
                except Exception as e:
                    logger.error(f"Interpolation failed for {shot_output.shot_id}: {e}")
        
        logger.info(f"Interpolation complete: processed {processed} shots to {target_fps}fps")
    
    def _get_video_for_interpolation(self, shot_output: ShotOutput) -> Optional[Path]:
        """
        Get the video path to interpolate.
        
        Priority: lipsync Ã¢â€ â€™ refined Ã¢â€ â€™ pass1
        
        This ensures we interpolate the most processed version.
        """
        # Check for lip-synced video first
        if hasattr(shot_output, 'lipsync_video_path') and shot_output.lipsync_video_path:
            return shot_output.lipsync_video_path
        
        # Then refined
        if hasattr(shot_output, 'refined_video_path') and shot_output.refined_video_path:
            return shot_output.refined_video_path
        
        # Fall back to pass1
        if shot_output.video_paths:
            return shot_output.video_paths[-1]
        
        return None
    
    # -------------------------------------------------------------------------
    # TTS SYNTHESIS (PHASE 2.4)
    # -------------------------------------------------------------------------
    
    async def _run_tts_synthesis(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """
        Synthesize dialogue audio from script text.
        
        This runs BEFORE Lip Sync because lip sync needs the audio files
        to determine mouth movements. The dialogue_segments are attached
        to shot_outputs so lip sync can read them.
        
        Data flow:
            SceneGraph.Shot.dialogue Ã¢â€ â€™ TTS Engine Ã¢â€ â€™ DialogueSegment
                                                         Ã¢â€ â€œ
                                           ShotOutput.dialogue_segments
                                                         Ã¢â€ â€œ
                                                    Lip Sync reads this
        """
        if not self.tts_engine:
            logger.info("TTS engine not configured, skipping dialogue synthesis")
            return
        
        total_lines = 0
        synthesized = 0
        failed = 0
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            scene = self.scene_graph.get_scene(scene_result.scene_id)
            if not scene:
                continue
            
            for shot_output in scene_result.shot_outputs:
                shot = self.scene_graph.get_shot(shot_output.shot_id)
                if not shot or not shot.has_dialogue:
                    continue
                
                # Convert shot.dialogue to DialogueLine objects
                dialogue_lines = self._extract_dialogue_lines(shot)
                total_lines += len(dialogue_lines)
                
                # Get voice configs from consistency dict
                voice_configs = self._get_voice_configs(shot)
                
                # Synthesize each line
                dialogue_segments = []
                for line in dialogue_lines:
                    self.progress.report(
                        "tts",
                        synthesized / max(total_lines, 1),
                        f"Synthesizing: {line.character_id}",
                    )
                    
                    voice_config = voice_configs.get(line.character_id)
                    if not voice_config:
                        logger.warning(f"No voice config for {line.character_id}, skipping")
                        continue
                    
                    try:
                        result = await self.tts_engine.synthesize(line, voice_config)
                        
                        if result.status == AudioGenerationStatus.COMPLETE:
                            # Create DialogueSegment for lip sync
                            segment = DialogueSegment(
                                audio_path=result.audio_path,
                                start_time_sec=line.start_time_sec,
                                end_time_sec=line.start_time_sec + result.actual_duration_sec,
                                character_id=line.character_id,
                                line_id=line.line_id,
                            )
                            dialogue_segments.append(segment)
                            synthesized += 1
                            logger.debug(f"Ã¢Å“â€œ TTS {line.line_id}: {result.actual_duration_sec:.1f}s")
                        else:
                            failed += 1
                            logger.warning(f"Ã¢Å“â€” TTS {line.line_id}: {result.error}")
                            
                    except Exception as e:
                        failed += 1
                        logger.error(f"TTS failed for {line.line_id}: {e}")
                
                # Attach dialogue segments to shot output for lip sync to read
                shot_output.dialogue_segments = dialogue_segments
        
        logger.info(f"TTS complete: {synthesized} synthesized, {failed} failed, {total_lines} total")
    
    def _extract_dialogue_lines(self, shot: Shot) -> List[DialogueLine]:
        """
        Convert shot.dialogue dicts to DialogueLine objects.
        
        shot.dialogue is: [{"character": "alice", "line": "Hello"}, ...]
        We need to convert to DialogueLine with timing information.
        """
        lines = []
        current_time = 0.0
        
        for i, d in enumerate(shot.dialogue):
            character_id = d.get("character", "unknown")
            text = d.get("line", "")
            
            if not text:
                continue
            
            line = DialogueLine(
                line_id=f"{shot.shot_id}_line_{i:02d}",
                character_id=character_id,
                text=text,
                start_time_sec=current_time,
                emotion=None,  # Could extract from d.get("emotion")
                direction=d.get("direction"),
                shot_id=shot.shot_id,
                scene_id=shot.scene_id if hasattr(shot, 'scene_id') else "",
            )
            lines.append(line)
            
            # Advance time by estimated duration + small gap
            current_time += line.estimated_duration_sec + 0.3
        
        return lines
    
    def _get_voice_configs(self, shot: Shot) -> Dict[str, VoiceConfig]:
        """
        Get voice configurations for all characters in a shot.
        
        Reads from consistency_dict which stores character voice settings.
        """
        configs = {}
        
        for char in shot.characters:
            char_id = char.entity_id if hasattr(char, 'entity_id') else str(char)
            
            # Try to get voice config from consistency dict
            if self.consistency_dict:
                char_data = self.consistency_dict.get_character(char_id)
                if char_data and char_data.voice_id:
                    configs[char_id] = VoiceConfig(
                        character_id=char_id,
                        voice_id=char_data.voice_id,
                        provider=TTSProvider.ELEVENLABS,
                    )
                    continue
            
            # Default voice config if not in consistency dict
            configs[char_id] = VoiceConfig(
                character_id=char_id,
                voice_id="",  # Use provider default
                provider=TTSProvider.ELEVENLABS,
            )
        
        return configs
    
    # -------------------------------------------------------------------------
    # AUDIO GENERATION (PHASE 3) - Ambience, Foley, Mix
    # -------------------------------------------------------------------------
    
    async def _run_audio_generation(
        self, 
        scene_results: List[SceneResult],
    ) -> None:
        """
        Generate ambient and foley audio, then mix all tracks.
        
        Note: TTS (dialogue) is handled separately in _run_tts_synthesis()
        because it must complete before Lip Sync.
        
        This phase generates:
        1. Ambience - Background soundscapes per scene
        2. Foley - Sound effects for actions
        3. Mix - Combines dialogue + ambience + foley per shot
        """
        # Check dependencies
        if not self.audio_mixer:
            logger.info("Audio mixer not configured, skipping audio generation")
            return
        
        # -----------------------------------------------------------------
        # Step 1: Generate Ambience (per scene)
        # -----------------------------------------------------------------
        if self.ambience_engine:
            await self._generate_scene_ambience(scene_results)
        else:
            logger.info("Ambience engine not configured, skipping")
        
        # -----------------------------------------------------------------
        # Step 2: Generate Foley (per shot action)
        # -----------------------------------------------------------------
        if self.foley_engine:
            await self._generate_shot_foley(scene_results)
        else:
            logger.info("Foley engine not configured, skipping")
        
        # -----------------------------------------------------------------
        # Step 3: Mix all tracks (per shot)
        # -----------------------------------------------------------------
        await self._mix_audio_tracks(scene_results)
        
        logger.info("Audio generation complete")
    
    async def _generate_scene_ambience(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """Generate ambient background audio for each scene."""
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            scene = self.scene_graph.get_scene(scene_result.scene_id)
            if not scene:
                continue
            
            # Build ambience spec from scene location
            location_desc = ""
            if scene.location:
                location_id = scene.location.entity_id if hasattr(scene.location, 'entity_id') else str(scene.location)
                if self.consistency_dict:
                    loc_data = self.consistency_dict.get_location(location_id)
                    if loc_data:
                        location_desc = loc_data.description or loc_data.name
                if not location_desc:
                    location_desc = location_id
            
            # Determine ambience type from location
            ambience_type = self._infer_ambience_type(location_desc)
            
            spec = AmbienceSpec(
                ambience_id=f"{scene.scene_id}_ambience",
                type=ambience_type,
                description=f"ambient background sounds for {location_desc}",
                duration_sec=scene.duration_sec,  # Scene has duration_sec, not total_duration_sec
                intensity=0.5,
                loop=True,
                scene_id=scene.scene_id,
            )
            
            self.progress.report("audio", 0.3, f"Generating ambience for {scene.scene_id}")
            
            try:
                result = await self.ambience_engine.generate(spec)
                if result.status == AudioGenerationStatus.COMPLETE:
                    scene_result.ambience_path = result.audio_path
                    logger.info(f"Ã¢Å“â€œ Ambience {scene.scene_id}: {result.actual_duration_sec:.1f}s")
                else:
                    logger.warning(f"Ã¢Å“â€” Ambience {scene.scene_id}: {result.error}")
            except Exception as e:
                logger.error(f"Ambience generation failed for {scene.scene_id}: {e}")
    
    def _infer_ambience_type(self, location_desc: str) -> AmbienceType:
        """Infer ambience type from location description."""
        desc_lower = location_desc.lower()
        
        if any(x in desc_lower for x in ["forest", "jungle", "woods"]):
            return AmbienceType.NATURE
        elif any(x in desc_lower for x in ["city", "street", "urban"]):
            return AmbienceType.URBAN
        elif any(x in desc_lower for x in ["office", "room", "indoor"]):
            return AmbienceType.INTERIOR
        elif any(x in desc_lower for x in ["ocean", "beach", "water"]):
            return AmbienceType.WATER
        elif any(x in desc_lower for x in ["cafe", "restaurant", "bar"]):
            return AmbienceType.CROWD
        else:
            return AmbienceType.INTERIOR  # Default
    
    async def _generate_shot_foley(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """Generate foley sound effects for shot actions."""
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            for shot_output in scene_result.shot_outputs:
                shot = self.scene_graph.get_shot(shot_output.shot_id)
                if not shot:
                    continue
                
                # Extract foley events from shot description
                foley_events = self._extract_foley_events(shot)
                if not foley_events:
                    continue
                
                shot_foley = []
                for event in foley_events:
                    try:
                        result = await self.foley_engine.retrieve(event)
                        if result.status == AudioGenerationStatus.COMPLETE:
                            shot_foley.append(result)
                            logger.debug(f"Ã¢Å“â€œ Foley {event.event_id}")
                        else:
                            logger.warning(f"Ã¢Å“â€” Foley {event.event_id}: {result.error}")
                    except Exception as e:
                        logger.error(f"Foley failed for {event.event_id}: {e}")
                
                shot_output.foley_tracks = shot_foley
    
    def _extract_foley_events(self, shot: Shot) -> List[FoleyEvent]:
        """
        Extract foley events from shot description.
        
        This is a simplified extraction. A full implementation would
        use NLP to parse action verbs and map to foley categories.
        """
        events = []
        desc_lower = shot.description.lower()
        
        # Simple keyword matching for common foley
        foley_keywords = {
            "walk": (FoleyCategory.FOOTSTEPS, "walking footsteps"),
            "run": (FoleyCategory.FOOTSTEPS, "running footsteps"),
            "door": (FoleyCategory.DOOR, "door opening or closing"),
            "knock": (FoleyCategory.DOOR, "knocking on door"),
            "drink": (FoleyCategory.OBJECT, "drinking from glass"),
            "eat": (FoleyCategory.OBJECT, "eating food sounds"),
            "type": (FoleyCategory.OBJECT, "keyboard typing"),
            "phone": (FoleyCategory.ELECTRONIC, "phone ringing"),
        }
        
        for keyword, (category, description) in foley_keywords.items():
            if keyword in desc_lower:
                event = FoleyEvent(
                    event_id=f"{shot.shot_id}_foley_{keyword}",
                    category=category,
                    description=description,
                    trigger_time_sec=0.5,  # Simplified: mid-shot
                    duration_sec=1.0,
                    shot_id=shot.shot_id,
                )
                events.append(event)
        
        return events
    
    async def _mix_audio_tracks(
        self,
        scene_results: List[SceneResult],
    ) -> None:
        """Mix dialogue, ambience, and foley into final audio per shot."""
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            for shot_output in scene_result.shot_outputs:
                shot = self.scene_graph.get_shot(shot_output.shot_id)
                if not shot:
                    continue
                
                # Gather audio components
                dialogue = getattr(shot_output, 'dialogue_segments', [])
                ambience = getattr(scene_result, 'ambience_path', None)
                foley = getattr(shot_output, 'foley_tracks', [])
                
                if not any([dialogue, ambience, foley]):
                    logger.debug(f"No audio to mix for {shot_output.shot_id}")
                    continue
                
                self.progress.report("audio", 0.8, f"Mixing {shot_output.shot_id}")
                
                try:
                    # Convert dialogue segments to SynthesizedDialogue format
                    synth_dialogue = [
                        SynthesizedDialogue(
                            line_id=seg.line_id,
                            audio_path=seg.audio_path,
                            actual_duration_sec=seg.end_time_sec - seg.start_time_sec,
                            status=AudioGenerationStatus.COMPLETE,
                        )
                        for seg in dialogue
                    ]
                    
                    # Convert ambience path to SynthesizedAmbience
                    synth_ambience = None
                    if ambience:
                        synth_ambience = SynthesizedAmbience(
                            ambience_id=f"{scene_result.scene_id}_ambience",
                            audio_path=ambience,
                            actual_duration_sec=shot.duration_sec,
                            status=AudioGenerationStatus.COMPLETE,
                        )
                    
                    result = await self.audio_mixer.mix_shot(
                        shot_id=shot_output.shot_id,
                        duration_sec=shot.duration_sec,
                        dialogue=synth_dialogue,
                        ambience=synth_ambience,
                        foley=foley,
                    )
                    
                    # MixResult has .status, not .success - check for COMPLETE status
                    if result.status == AudioGenerationStatus.COMPLETE and result.output_path:
                        shot_output.mixed_audio_path = result.output_path
                        logger.info(f"Ã¢Å“â€œ Mixed {shot_output.shot_id}")
                    else:
                        logger.warning(f"Ã¢Å“â€” Mix {shot_output.shot_id}: {result.error}")
                        
                except Exception as e:
                    logger.error(f"Audio mixing failed for {shot_output.shot_id}: {e}")
    
    # -------------------------------------------------------------------------
    # POST-PRODUCTION (PHASE 4)
    # -------------------------------------------------------------------------
    
    async def _run_post_production(
        self, 
        scene_results: List[SceneResult],
    ) -> Optional[Path]:
        """
        Run post-production pipeline and stitch final output.
        
        This is the LAST phase of the pipeline. It takes all the generated
        and processed videos and combines them into a single final output.
        
        Data flow:
            Interpolated videos (24fps) Ã¢â€â‚¬Ã¢â€Â¬Ã¢â€â‚¬Ã¢â€ â€™ Color Match Ã¢â€â‚¬Ã¢â€ â€™ Color-matched videos
                                         Ã¢â€â€š
            Dialogue + Ambience + Music Ã¢â€â‚¬Ã¢â€Â¼Ã¢â€â‚¬Ã¢â€ â€™ Audio Duck Ã¢â€â‚¬Ã¢â€ â€™ Ducked audio mix
                                         Ã¢â€â€š
                                         Ã¢â€â€Ã¢â€â‚¬Ã¢â€ â€™ Stitcher Ã¢â€â‚¬Ã¢â€ â€™ final_output.mp4
        
        Why this order:
            1. Color matching BEFORE stitching - each shot needs normalization
            2. Audio ducking BEFORE stitching - balance tracks first
            3. Stitching LAST - combines everything into final deliverable
        
        Architecture alignment:
            From ARCHITECTURE_SUMMARY.md:
            - Auto-Color Match (Histogram Ã¢â€ â€™ Master Shot)
            - Audio Ducking (-12dB during dialogue)
            - Final Stitch (FFmpeg)
        """
        if not self.stitcher:
            logger.warning("Stitcher not available, skipping post-production")
            return None
        
        # Collect all video paths in scene/shot order
        video_paths = self._collect_final_video_paths(scene_results)
        
        if not video_paths:
            logger.error("No videos to stitch")
            return None
        
        logger.info(f"Starting post-production: {len(video_paths)} videos")
        
        # Determine output path
        output_dir = (
            self.pipeline_config.output_dir or
            self.config.paths.output_dir
        ) / self.scene_graph.project_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        final_output = output_dir / "final_output.mp4"
        
        # -----------------------------------------------------------------
        # Step 1: Color Matching (normalize colors to master shot)
        # -----------------------------------------------------------------
        color_matched_paths = video_paths  # Default: use original if no matcher
        
        if self.color_matcher and len(video_paths) > 1:
            self.progress.report("post", 0.1, "Analyzing master shot for color reference...")
            
            try:
                color_matched_paths = await self._run_color_matching(
                    video_paths, 
                    output_dir / "color_matched"
                )
                logger.info(f"Ã¢Å“â€œ Color matched {len(color_matched_paths)} videos")
            except Exception as e:
                logger.warning(f"Color matching failed: {e}, using original colors")
                color_matched_paths = video_paths
        
        # -----------------------------------------------------------------
        # Step 2: Audio Ducking (lower music during dialogue)
        # -----------------------------------------------------------------
        ducked_audio_path = None
        
        if self.audio_ducker and self.pipeline_config.enable_audio:
            self.progress.report("post", 0.4, "Ducking audio tracks...")
            
            try:
                ducked_audio_path = await self._run_audio_ducking(
                    scene_results,
                    output_dir / "audio_ducked"
                )
                if ducked_audio_path:
                    logger.info(f"Ã¢Å“â€œ Audio ducked: {ducked_audio_path}")
            except Exception as e:
                logger.warning(f"Audio ducking failed: {e}, using unducked audio")
        
        # -----------------------------------------------------------------
        # Step 3: Final Stitch (assemble everything)
        # -----------------------------------------------------------------
        self.progress.report("post", 0.6, "Stitching final video...")
        
        try:
            stitch_result = await self._run_final_stitch(
                video_paths=color_matched_paths,
                audio_path=ducked_audio_path,
                output_path=final_output,
            )
            
            if stitch_result.success:
                logger.info(f"Ã¢Å“â€œ Final output: {final_output}")
                logger.info(f"  Duration: {stitch_result.duration_sec:.1f}s")
                logger.info(f"  Resolution: {stitch_result.resolution}")
                logger.info(f"  Processing time: {stitch_result.processing_time_sec:.1f}s")
                
                self.progress.report("post", 1.0, "Post-production complete!")
                return final_output
            else:
                logger.error(f"Stitching failed: {stitch_result.error}")
                return None
                
        except Exception as e:
            logger.error(f"Post-production failed: {e}")
            return None
    
    def _collect_final_video_paths(
        self, 
        scene_results: List[SceneResult]
    ) -> List[Path]:
        """
        Collect final video paths from all shots in scene order.
        
        Priority: interpolated Ã¢â€ â€™ lipsync Ã¢â€ â€™ refined Ã¢â€ â€™ pass1
        
        This order reflects the pipeline stages:
        - interpolated: After RIFE (24fps, smoothest)
        - lipsync: After lip sync but before RIFE
        - refined: After Pass 2 but before lip sync
        - pass1: Raw Pass 1 output (fallback)
        """
        paths = []
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            for shot_output in scene_result.shot_outputs:
                path = self._get_best_video_path(shot_output)
                if path and path.exists():
                    paths.append(path)
                else:
                    logger.warning(f"No video found for {shot_output.shot_id}")
        
        return paths
    
    def _get_best_video_path(self, shot_output: ShotOutput) -> Optional[Path]:
        """
        Get the best available video path for a shot.
        
        Priority order (highest to lowest quality):
        1. interpolated_video_path - 24fps, fully processed
        2. lipsync_video_path - Has lip sync, 12fps
        3. refined_video_path - Pass 2 refined, 12fps
        4. video_paths[-1] - Last chunk from Pass 1
        """
        # Check in priority order
        if hasattr(shot_output, 'interpolated_video_path') and shot_output.interpolated_video_path:
            return shot_output.interpolated_video_path
        
        if hasattr(shot_output, 'lipsync_video_path') and shot_output.lipsync_video_path:
            return shot_output.lipsync_video_path
        
        if hasattr(shot_output, 'refined_video_path') and shot_output.refined_video_path:
            return shot_output.refined_video_path
        
        # Fall back to last chunk from Pass 1
        if shot_output.video_paths:
            return shot_output.video_paths[-1]
        
        return None
    
    async def _run_color_matching(
        self,
        video_paths: List[Path],
        output_dir: Path,
    ) -> List[Path]:
        """
        Match colors of all videos to the master shot.
        
        The master shot is the first video (index 0). All other videos
        are adjusted to match its color profile.
        
        Why first shot as master:
        - Establishes the "look" of the film
        - Usually the widest/establishing shot
        - Consistent with film industry practice
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if len(video_paths) < 2:
            return video_paths
        
        # Analyze master shot (first video)
        master_path = video_paths[0]
        self.progress.report("post.color", 0.1, f"Analyzing master: {master_path.name}")
        
        reference_profile = await self.color_matcher.analyze_reference(master_path)
        
        # Master shot doesn't need matching - just copy or reference
        matched_paths = [master_path]
        
        # Match all other shots to master
        for i, video_path in enumerate(video_paths[1:], start=1):
            progress = 0.1 + (0.9 * i / len(video_paths))
            self.progress.report(
                "post.color", 
                progress, 
                f"Matching {video_path.name} to master"
            )
            
            output_path = output_dir / f"{video_path.stem}_matched.mp4"
            
            try:
                result = await self.color_matcher.match_clip(
                    clip_path=video_path,
                    reference=reference_profile,
                    output_path=output_path,
                )
                
                if result.success:
                    matched_paths.append(output_path)
                    logger.debug(f"Ã¢Å“â€œ Color matched: {video_path.name}")
                else:
                    logger.warning(f"Color match failed for {video_path.name}: {result.error}")
                    matched_paths.append(video_path)  # Use original
                    
            except Exception as e:
                logger.warning(f"Color match error for {video_path.name}: {e}")
                matched_paths.append(video_path)  # Use original
        
        return matched_paths
    
    async def _run_audio_ducking(
        self,
        scene_results: List[SceneResult],
        output_dir: Path,
    ) -> Optional[Path]:
        """
        Apply ducking to lower music/ambience during dialogue.
        
        This uses dialogue as the "sidechain" - when dialogue is present,
        the music and ambience are automatically lowered.
        
        Returns path to the final mixed and ducked audio, or None if
        no audio tracks are available.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Collect all audio tracks
        dialogue_paths = []
        ambience_paths = []
        music_path = None  # TODO: Wire to score generation
        
        for scene_result in scene_results:
            if not scene_result.success:
                continue
            
            # Collect scene-level ambience
            if hasattr(scene_result, 'ambience_path') and scene_result.ambience_path:
                ambience_paths.append(scene_result.ambience_path)
            
            # Collect shot-level dialogue
            for shot_output in scene_result.shot_outputs:
                if hasattr(shot_output, 'mixed_audio_path') and shot_output.mixed_audio_path:
                    dialogue_paths.append(shot_output.mixed_audio_path)
                elif hasattr(shot_output, 'dialogue_segments'):
                    for seg in shot_output.dialogue_segments:
                        if seg.audio_path and seg.audio_path.exists():
                            dialogue_paths.append(seg.audio_path)
        
        if not dialogue_paths and not ambience_paths:
            logger.info("No audio tracks to duck")
            return None
        
        # If we have both dialogue and background audio, apply ducking
        if dialogue_paths and (ambience_paths or music_path):
            # Concatenate dialogue into single track for ducking reference
            dialogue_concat = output_dir / "dialogue_concat.wav"
            # TODO: Implement audio concatenation with proper timing
            
            # For now, just use the mixed audio from shots
            # Full implementation would use audio_ducker.duck() here
            logger.info("Audio ducking: Using pre-mixed shot audio")
        
        return None  # Return None until full audio concatenation is implemented
    
    async def _run_final_stitch(
        self,
        video_paths: List[Path],
        audio_path: Optional[Path],
        output_path: Path,
    ) -> StitchResult:
        """
        Stitch all videos into final output.
        
        This is the final assembly step. It concatenates all video clips
        and optionally adds a separate audio track.
        
        Uses hard cuts between shots (TransitionType.CUT) by default.
        Dissolves and other transitions can be added via scene graph metadata.
        """
        # Build VideoClip objects for each path
        from src.post.ffmpeg_wrapper import probe_video
        
        clips = []
        for i, path in enumerate(video_paths):
            try:
                info = await probe_video(path)
                clip = VideoClip(
                    path=path,
                    shot_id=f"shot_{i:03d}",
                    duration_sec=info.duration_sec,
                    resolution=info.resolution,
                    fps=info.fps,
                    has_audio=info.has_audio,
                )
                clips.append(clip)
            except Exception as e:
                logger.error(f"Failed to probe {path}: {e}")
                return StitchResult.failed(f"Failed to probe {path}: {e}")
        
        if not clips:
            return StitchResult.failed("No valid clips to stitch")
        
        # Build stitch job
        # Default to hard cuts between all clips
        transitions = [TransitionSpec.cut() for _ in range(len(clips) - 1)]
        
        # Build audio tracks if we have ducked audio
        audio_tracks = []
        if audio_path and audio_path.exists():
            audio_tracks.append(AudioTrack(
                path=audio_path,
                track_type=AudioTrackType.MASTER,
                volume_db=0.0,
            ))
        
        job = StitchJob(
            clips=clips,
            output_path=output_path,
            transitions=transitions,
            target_fps=self.pipeline_config.target_fps,
            audio_tracks=audio_tracks,
            normalize_color=False,  # Already done in color matching step
            normalize_audio=True,
        )
        
        # Execute stitch
        self.progress.report("post.stitch", 0.5, f"Stitching {len(clips)} clips...")
        
        result = await self.stitcher.stitch(job)
        
        return result
    
    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------
    
    def _calculate_total_cost(self, scene_results: List[SceneResult]) -> float:
        """Calculate total estimated cost."""
        total = 0.0
        for scene in scene_results:
            for shot in scene.shot_outputs:
                total += shot.total_cost
        return total


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Continuum Engine - AI Filmmaking Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run full pipeline
    python main.py --project film.json

    # Dry run (no cloud, mock implementations)
    python main.py --project film.json --dry-run

    # Generate specific scene
    python main.py --project film.json --scene scene_01

    # High quality mode
    python main.py --project film.json --quality high

    # Video only (no audio/post)
    python main.py --project film.json --no-audio --no-post

    # Verbose logging with log file
    python main.py --project film.json -v --log-file pipeline.log
        """,
    )
    
    # Required
    parser.add_argument(
        "--project", "-p",
        type=Path,
        required=True,
        help="Path to scene graph JSON file",
    )
    
    # Optional paths
    parser.add_argument(
        "--consistency", "-c",
        type=Path,
        default=None,
        help="Path to consistency dict JSON",
    )
    parser.add_argument(
        "--world-state", "-w",
        type=Path,
        default=None,
        help="Path to world state JSON (for resume)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output directory",
    )
    
    # Filters
    parser.add_argument(
        "--scene",
        nargs="+",
        default=None,
        help="Specific scene ID(s) to generate",
    )
    parser.add_argument(
        "--shot",
        nargs="+",
        default=None,
        help="Specific shot ID(s) to generate",
    )
    
    # Mode flags
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Use mock implementations (no cloud)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh, ignore checkpoints",
    )
    
    # Quality
    parser.add_argument(
        "--quality", "-q",
        choices=["draft", "standard", "high"],
        default="standard",
        help="Render quality preset",
    )
    parser.add_argument(
        "--pacing",
        choices=["fast", "normal", "slow", "documentary"],
        default="normal",
        help="Pacing style",
    )
    
    # Feature toggles
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="Disable bridge frame generation",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Disable quality auditing",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio generation",
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        help="Disable post-production",
    )
    parser.add_argument(
        "--no-pass2",
        action="store_true",
        help="Disable Pass 2 refinement",
    )
    
    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write logs to file",
    )
    
    return parser.parse_args()


def build_pipeline_config(args: argparse.Namespace) -> PipelineConfig:
    """Build pipeline config from CLI args."""
    pacing_map = {
        "fast": PacingStyle.FAST,
        "normal": PacingStyle.NORMAL,
        "slow": PacingStyle.SLOW,
        "documentary": PacingStyle.DOCUMENTARY,
    }
    
    return PipelineConfig(
        mode=PipelineMode.FULL,
        dry_run=args.dry_run,
        quality=args.quality,
        pacing_style=pacing_map.get(args.pacing, PacingStyle.NORMAL),
        enable_bridge=not args.no_bridge,
        enable_audit=not args.no_audit,
        enable_audio=not args.no_audio,
        enable_post=not args.no_post,
        enable_pass2=not args.no_pass2,
        output_dir=args.output,
        resume_from_checkpoint=not args.no_resume,
    )


async def main_async(args: argparse.Namespace) -> int:
    """Async main entry point."""
    setup_logging(args.verbose, args.log_file)
    
    logger.info("=" * 70)
    logger.info("CONTINUUM ENGINE v2.0")
    logger.info("=" * 70)
    logger.info(f"Project: {args.project}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    
    # Validate project exists
    if not args.project.exists():
        logger.error(f"Project file not found: {args.project}")
        return 1
    
    # Build config
    config = build_pipeline_config(args)
    
    # Run pipeline
    async with ContinuumOrchestrator(config=config) as orchestrator:
        await orchestrator.setup(
            project_path=args.project,
            consistency_path=args.consistency,
            world_state_path=args.world_state,
        )
        
        result = await orchestrator.run(
            scene_ids=args.scene,
            shot_ids=args.shot,
        )
    
    # Log final result
    logger.info(f"\nFinal Result: {result.to_dict()}")
    
    # Exit code based on result
    if result.all_succeeded:
        return 0
    elif result.scenes_succeeded > 0:
        return 2  # Partial success
    else:
        return 1  # Complete failure


def main() -> None:
    """Sync entry point."""
    args = parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()