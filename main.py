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
from src.studio.pass2_refiner import RefinerFactory, ComfyRefiner, BaseRefiner
from src.studio.rife_interpolator import RIFEInterpolator

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
    from src.sonic.mixer import AudioMixer, get_mixer
    from src.sonic.tts_engine import TTSEngine
    from src.sonic.ambience import AmbienceGenerator
    SONIC_AVAILABLE = True
except ImportError:
    SONIC_AVAILABLE = False

# =============================================================================
# IMPORTS - Post-Production - Optional
# =============================================================================

try:
    from src.post.color_match import ColorMatcher
    from src.post.audio_ducker import AudioDucker
    from src.post.stitcher import VideoStitcher
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
        
        # Studio components (generation)
        self.renderer: Optional[BaseRenderer] = None
        self.bridge_engine: Optional[BaseBridgeEngine] = None
        self.pass1_generator: Optional[Pass1Generator] = None
        self.pass2_refiner: Optional[BaseRefiner] = None
        
        # Audit components (verification)
        self.reviewer: Optional[Reviewer] = None
        
        # Sonic components (audio)
        self.audio_mixer: Optional[Any] = None  # AudioMixer
        
        # Post components (final assembly)
        self.stitcher: Optional[Any] = None  # VideoStitcher
        
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
        
        self.progress.report("setup", 0.7, "Initializing audio system...")
        
        # -----------------------------------------------------------------
        # 9. Initialize Audio System (optional)
        # -----------------------------------------------------------------
        if self.pipeline_config.enable_audio and SONIC_AVAILABLE:
            if self.pipeline_config.dry_run:
                logger.info("DRY RUN: Audio generation disabled")
            else:
                logger.info("Initializing audio mixer")
                self.audio_mixer = get_mixer()
        elif not SONIC_AVAILABLE:
            logger.info("Audio system not available (missing dependencies)")
        
        self.progress.report("setup", 0.8, "Initializing checkpoint system...")
        
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
            status=JobStatus.RUNNING,
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
                    progress_callback=self._create_generation_callback(scene.scene_id),
                )
                
                shot_outputs.append(shot_output)
                
                # Update world state with any events from this shot
                self._update_world_state_from_shot(shot, shot_output)
                
                # Update progress tracker
                for _ in shot_output.chunk_outputs:
                    self.progress.chunk_completed()
                
                # Log result
                if shot_output.all_success:
                    logger.info(f"✓ Shot {shot.shot_id}: {len(shot_output.chunk_outputs)} chunks")
                else:
                    logger.warning(f"✗ Shot {shot.shot_id} had failures")
            
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
        """Update world state based on shot events."""
        if not self.world_state:
            return
        
        # In a full implementation, this would:
        # 1. Parse shot description for state-changing events
        # 2. Analyze generated video for object positions
        # 3. Update world state accordingly
        
        # For now, just log
        logger.debug(f"World state update for {shot.shot_id} (placeholder)")
    
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
        """Run Pass 2 vid2vid refinement."""
        if not self.pass2_refiner:
            logger.info("Pass 2 refiner not configured, skipping")
            return
        
        # TODO: Implement Pass 2 refinement
        logger.info("Pass 2 refinement: Not yet implemented")
    
    # -------------------------------------------------------------------------
    # AUDIO GENERATION (PHASE 3)
    # -------------------------------------------------------------------------
    
    async def _run_audio_generation(
        self, 
        scene_results: List[SceneResult],
    ) -> None:
        """Generate audio for all scenes."""
        if not self.audio_mixer:
            logger.info("Audio mixer not configured, skipping")
            return
        
        # TODO: Implement audio generation
        logger.info("Audio generation: Not yet implemented")
    
    # -------------------------------------------------------------------------
    # POST-PRODUCTION (PHASE 4)
    # -------------------------------------------------------------------------
    
    async def _run_post_production(
        self, 
        scene_results: List[SceneResult],
    ) -> Optional[Path]:
        """Run post-production and stitch final output."""
        # TODO: Implement post-production
        logger.info("Post-production: Not yet implemented")
        return None
    
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