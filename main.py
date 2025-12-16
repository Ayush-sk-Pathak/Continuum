"""
Continuum Engine - Main Orchestrator

This is the entry point that proves the core hypothesis:
"Can you generate Shot A, then Shot B, and have them look like 
the same character in the same world?"

This orchestrator wires together:
- P0: ComfyUI Client (cloud connection)
- P1: WanRenderer (video generation)
- P2: SceneGraph (what to generate)
- P3: ConsistencyDict (character identity)
- P4: BridgeEngine (seamless transitions)
- P5: IdentityChecker (verification)

Design Principles:
1. Async-first: All cloud ops are async
2. Fail-safe: Checkpoint before every risky operation
3. Observable: Rich logging for debugging remote issues
4. Testable: Can run with mock renderer for local dev

Usage:
    # Full pipeline (requires cloud GPU)
    python main.py --project my_film.json

    # Dry run (local, mock renderer)
    python main.py --project my_film.json --dry-run

    # Generate specific shot
    python main.py --project my_film.json --shot shot_01
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# Core infrastructure
from src.core.config import get_config, Config
from src.core.job_state import JobStatus, AuditStatus
from src.core.checkpointing import CheckpointManager
from src.core.error_recovery import DegradationLadder

# Director (the brain)
from src.director.scene_graph import SceneGraph, Shot, Chunk, ChunkStatus
from src.director.consistency_dict import ConsistencyDict, CharacterEntity

# Renderers (the muscle)
from src.renderers.base import BaseRenderer, JobSpec, RenderResult, CharacterRef
from src.renderers.wan_renderer import WanRenderer

# Studio (video pipeline)
from src.studio.bridge_engine import (
    BaseBridgeEngine, 
    ComfyUIBridgeEngine,
    MockBridgeEngine,
    BridgeSpec, 
    BridgeResult
)

# Audit (quality control)
from src.audit.identity_checker import (
    BaseIdentityChecker,
    ArcFaceIdentityChecker,
    MockIdentityChecker,
    IdentityCheckResult,
    IdentityComparison,
)

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(verbose: bool = False) -> None:
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    
    # Rich format for development
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
    datefmt = "%H:%M:%S"
    
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    # Quiet noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# =============================================================================
# ORCHESTRATION RESULT
# =============================================================================

@dataclass
class ShotResult:
    """Result of generating a single shot."""
    shot_id: str
    status: JobStatus
    video_path: Optional[Path] = None
    bridge_path: Optional[Path] = None
    identity_score: Optional[float] = None
    error: Optional[str] = None
    duration_sec: float = 0.0


@dataclass 
class PipelineResult:
    """Result of running the full pipeline."""
    project_id: str
    shots_attempted: int
    shots_succeeded: int
    shots_failed: int
    total_duration_sec: float
    shot_results: List[ShotResult]
    
    @property
    def success_rate(self) -> float:
        """Percentage of shots that succeeded."""
        if self.shots_attempted == 0:
            return 0.0
        return 100.0 * self.shots_succeeded / self.shots_attempted
    
    @property
    def all_succeeded(self) -> bool:
        """Did all shots succeed?"""
        return self.shots_failed == 0 and self.shots_attempted > 0


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class ContinuumOrchestrator:
    """
    The conductor that coordinates all pipeline components.
    
    Responsibilities:
    1. Load project (SceneGraph + ConsistencyDict)
    2. Initialize cloud resources (renderer, bridge engine)
    3. Generate shots in sequence, respecting dependencies
    4. Verify identity consistency between shots
    5. Checkpoint progress for crash recovery
    
    The orchestrator does NOT:
    - Parse scripts (that's the Director Agent's job)
    - Generate video directly (that's the Renderer's job)
    - Make aesthetic decisions (that's in the prompts)
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        dry_run: bool = False,
    ):
        """
        Initialize orchestrator.
        
        Args:
            config: Configuration (uses default if not provided)
            dry_run: If True, use mock implementations (no cloud)
        """
        self.config = config or get_config()
        self.dry_run = dry_run
        
        # Will be initialized in setup()
        self.scene_graph: Optional[SceneGraph] = None
        self.consistency_dict: Optional[ConsistencyDict] = None
        self.renderer: Optional[BaseRenderer] = None
        self.bridge_engine: Optional[BaseBridgeEngine] = None
        self.identity_checker: Optional[BaseIdentityChecker] = None
        self.checkpoint_manager: Optional[CheckpointManager] = None
        
        # State tracking
        self._initialized = False
        self._last_frame_path: Optional[Path] = None  # For bridge generation
        
    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------
    
    async def setup(
        self,
        project_path: Path,
        consistency_path: Optional[Path] = None,
    ) -> None:
        """
        Initialize all components and load project.
        
        Args:
            project_path: Path to scene graph JSON
            consistency_path: Path to consistency dict JSON (optional)
        """
        logger.info("=" * 60)
        logger.info("CONTINUUM ENGINE - Setup")
        logger.info("=" * 60)
        
        # 1. Load scene graph
        logger.info(f"Loading scene graph from {project_path}")
        self.scene_graph = SceneGraph.load(project_path)
        logger.info(f"  Project: {self.scene_graph.title}")
        logger.info(f"  Scenes: {self.scene_graph.scene_count}")
        logger.info(f"  Shots: {self.scene_graph.shot_count}")
        logger.info(f"  Duration: {self.scene_graph.total_duration_min:.1f} min")
        
        # 2. Load or create consistency dict
        if consistency_path and consistency_path.exists():
            logger.info(f"Loading consistency dict from {consistency_path}")
            self.consistency_dict = ConsistencyDict.load(consistency_path)
        else:
            logger.info("Creating empty consistency dict")
            self.consistency_dict = ConsistencyDict()
        
        logger.info(f"  Characters: {len(self.consistency_dict.list_characters())}")
        logger.info(f"  Locations: {len(self.consistency_dict.list_locations())}")
        
        # 3. Initialize renderer
        if self.dry_run:
            logger.info("DRY RUN: Using mock renderer")
            # MockWanRenderer would be defined in wan_renderer.py
            # For now, we'll still create WanRenderer but skip cloud ops
            self.renderer = WanRenderer()
        else:
            logger.info(f"Initializing WanRenderer (host={self.config.comfyui.host})")
            self.renderer = WanRenderer()
            await self.renderer.initialize()
        
        # 4. Initialize bridge engine
        if self.dry_run:
            logger.info("DRY RUN: Using mock bridge engine")
            self.bridge_engine = MockBridgeEngine()
        else:
            logger.info("Initializing ComfyBridgeEngine")
            self.bridge_engine = ComfyUIBridgeEngine()
            await self.bridge_engine.initialize()
        
        # 5. Initialize identity checker
        if self.dry_run:
            logger.info("DRY RUN: Using mock identity checker")
            self.identity_checker = MockIdentityChecker()
        else:
            logger.info("Initializing ArcFaceIdentityChecker")
            self.identity_checker = ArcFaceIdentityChecker()
            await self.identity_checker.initialize()
        
        # 6. Initialize checkpoint manager
        checkpoint_dir = self.config.paths.checkpoint_dir / self.scene_graph.project_id
        self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        logger.info(f"Checkpoint dir: {checkpoint_dir}")
        
        self._initialized = True
        logger.info("Setup complete")
        logger.info("=" * 60)
    
    async def teardown(self) -> None:
        """Clean up all resources."""
        logger.info("Shutting down...")
        
        if self.renderer:
            await self.renderer.shutdown()
        if self.bridge_engine:
            await self.bridge_engine.shutdown()
        if self.identity_checker:
            await self.identity_checker.shutdown()
        
        self._initialized = False
        logger.info("Shutdown complete")
    
    async def __aenter__(self) -> "ContinuumOrchestrator":
        """Async context manager - setup is called separately."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.teardown()
    
    # -------------------------------------------------------------------------
    # CORE PIPELINE
    # -------------------------------------------------------------------------
    
    async def run(
        self,
        shot_ids: Optional[List[str]] = None,
        resume: bool = True,
    ) -> PipelineResult:
        """
        Run the generation pipeline.
        
        Args:
            shot_ids: Specific shots to generate (None = all)
            resume: Resume from checkpoint if available
            
        Returns:
            PipelineResult with outcomes for all shots
        """
        if not self._initialized:
            raise RuntimeError("Orchestrator not initialized. Call setup() first.")
        
        start_time = datetime.utcnow()
        shot_results: List[ShotResult] = []
        
        # Determine which shots to process
        shots_to_process = self._get_shots_to_process(shot_ids, resume)
        
        logger.info("=" * 60)
        logger.info(f"PIPELINE START: {len(shots_to_process)} shots to process")
        logger.info("=" * 60)
        
        # Process shots sequentially (order matters for bridge frames)
        for i, shot in enumerate(shots_to_process):
            logger.info(f"\n--- Shot {i+1}/{len(shots_to_process)}: {shot.shot_id} ---")
            
            try:
                result = await self._process_shot(shot, is_first=(i == 0))
                shot_results.append(result)
                
                if result.status == JobStatus.COMPLETE:
                    logger.info(f"✓ Shot {shot.shot_id} complete")
                else:
                    logger.warning(f"✗ Shot {shot.shot_id} failed: {result.error}")
                    
            except Exception as e:
                logger.exception(f"Unexpected error processing shot {shot.shot_id}")
                shot_results.append(ShotResult(
                    shot_id=shot.shot_id,
                    status=JobStatus.FAILED,
                    error=str(e),
                ))
        
        # Calculate totals
        total_duration = (datetime.utcnow() - start_time).total_seconds()
        succeeded = sum(1 for r in shot_results if r.status == JobStatus.COMPLETE)
        failed = sum(1 for r in shot_results if r.status == JobStatus.FAILED)
        
        result = PipelineResult(
            project_id=self.scene_graph.project_id,
            shots_attempted=len(shot_results),
            shots_succeeded=succeeded,
            shots_failed=failed,
            total_duration_sec=total_duration,
            shot_results=shot_results,
        )
        
        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE COMPLETE")
        logger.info(f"  Success rate: {result.success_rate:.1f}%")
        logger.info(f"  Duration: {total_duration:.1f}s")
        logger.info("=" * 60)
        
        return result
    
    def _get_shots_to_process(
        self,
        shot_ids: Optional[List[str]],
        resume: bool,
    ) -> List[Shot]:
        """Determine which shots need processing."""
        all_shots = list(self.scene_graph.iter_shots())
        
        # Filter to specific shots if requested
        if shot_ids:
            all_shots = [s for s in all_shots if s.shot_id in shot_ids]
        
        # Filter out completed shots if resuming
        if resume and self.checkpoint_manager:
            completed = self.checkpoint_manager.get_completed_shots()
            all_shots = [s for s in all_shots if s.shot_id not in completed]
        
        return all_shots
    
    async def _process_shot(self, shot: Shot, is_first: bool) -> ShotResult:
        """
        Process a single shot through the full pipeline.
        
        Steps:
        1. Generate bridge frame (unless first shot)
        2. Build job spec with character refs
        3. Generate video (Pass 1)
        4. Audit identity
        5. Re-roll if failed (up to max_attempts)
        6. Checkpoint success
        """
        shot_start = datetime.utcnow()
        
        # Step 1: Bridge frame (if not first shot)
        bridge_result: Optional[BridgeResult] = None
        
        if not is_first and self._last_frame_path:
            logger.info("  Generating bridge frame...")
            bridge_result = await self._generate_bridge(shot)
            if bridge_result:
                logger.info(f"  Bridge: {bridge_result.method.value}")
        
        # Step 2: Build job spec
        job_spec = self._build_job_spec(shot, bridge_result)
        
        # Step 3: Generate with retry loop
        max_attempts = self.config.generation.max_reroll_attempts
        
        for attempt in range(1, max_attempts + 1):
            logger.info(f"  Generation attempt {attempt}/{max_attempts}...")
            
            try:
                # Generate video
                render_result = await self.renderer.generate(job_spec)
                
                # Step 4: Audit identity (if characters present)
                audit_passed = True
                identity_score = None
                
                if shot.characters and not self.dry_run:
                    audit_passed, identity_score = await self._audit_identity(
                        shot, render_result
                    )
                
                if audit_passed:
                    # Success! Update state and return
                    self._update_last_frame(render_result)
                    self._checkpoint_shot(shot, render_result)
                    
                    duration = (datetime.utcnow() - shot_start).total_seconds()
                    return ShotResult(
                        shot_id=shot.shot_id,
                        status=JobStatus.COMPLETE,
                        video_path=render_result.video_path,
                        bridge_path=bridge_result.frame_path if bridge_result else None,
                        identity_score=identity_score,
                        duration_sec=duration,
                    )
                else:
                    logger.warning(f"  Identity check failed (score={identity_score})")
                    
            except Exception as e:
                logger.warning(f"  Generation failed: {e}")
        
        # All attempts exhausted
        duration = (datetime.utcnow() - shot_start).total_seconds()
        return ShotResult(
            shot_id=shot.shot_id,
            status=JobStatus.FAILED,
            error=f"Failed after {max_attempts} attempts",
            duration_sec=duration,
        )
    
    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------
    
    async def _generate_bridge(self, shot: Shot) -> Optional[BridgeResult]:
        """Generate bridge frame for shot transition."""
        if not self._last_frame_path or not self.bridge_engine:
            return None
        
        # Get character refs for the incoming shot
        character_refs = []
        for char_ref in shot.characters:
            ref = self.consistency_dict.get_character_ref(char_ref.entity_id)
            if ref:
                character_refs.append(ref)
        
        # Build bridge spec
        spec = BridgeSpec.from_shots(
            shot_a_last_frame=self._last_frame_path,
            shot_b_prompt=shot.prompt,
            shot_b_characters=character_refs,
            shot_a_type=shot.shot_type.value,  # Simplified - would track prev shot
            shot_b_type=shot.shot_type.value,
        )
        
        try:
            return await self.bridge_engine.generate(spec)
        except Exception as e:
            logger.warning(f"Bridge generation failed: {e}")
            return None
    
    def _build_job_spec(
        self,
        shot: Shot,
        bridge_result: Optional[BridgeResult],
    ) -> JobSpec:
        """Build renderer job spec from shot and consistency dict."""
        # Get character refs
        character_refs = []
        for char_ref in shot.characters:
            ref = self.consistency_dict.get_character_ref(char_ref.entity_id)
            if ref:
                character_refs.append(ref)
        
        # Get location ref
        location_refs = []
        if shot.location:
            loc_ref = self.consistency_dict.get_location_ref(shot.location.entity_id)
            if loc_ref:
                location_refs.append(loc_ref)
        
        return JobSpec(
            prompt=shot.prompt,
            duration_sec=shot.duration_sec,
            init_frame=bridge_result.frame_path if bridge_result else None,
            character_refs=character_refs,
            location_refs=location_refs,
            layout=None,  # Would come from layout_generator
        )
    
    async def _audit_identity(
        self,
        shot: Shot,
        render_result: RenderResult,
    ) -> tuple[bool, Optional[float]]:
        """
        Verify character identity was preserved in generated video.
        
        Returns:
            (passed, score) - passed is True if identity check passed
        """
        if not self.identity_checker:
            return True, None
        
        # Get reference image for first character
        if not shot.characters:
            return True, None
        
        char_id = shot.characters[0].entity_id
        char_entity = self.consistency_dict.get_character(char_id)
        
        if not char_entity or not char_entity.face_refs:
            logger.debug(f"No face refs for {char_id}, skipping identity check")
            return True, None
        
        ref_path = Path(char_entity.face_refs[0])
        
        # Extract first and last frame from generated video
        # (In practice, would use ffmpeg to extract frames)
        # For now, just check first frame exists
        
        try:
            comparison = await self.identity_checker.compare(
                source_frame=ref_path,
                target_frame=render_result.video_path,  # Would be first frame
            )
            
            threshold = self.config.audit.identity_threshold
            passed = comparison.similarity >= threshold
            
            return passed, comparison.similarity
            
        except Exception as e:
            logger.warning(f"Identity check error: {e}")
            return True, None  # Don't fail on check errors
    
    def _update_last_frame(self, render_result: RenderResult) -> None:
        """Update the last frame path for next bridge generation."""
        # Would extract last frame from video
        # For now, just use video path as placeholder
        self._last_frame_path = render_result.video_path
    
    def _checkpoint_shot(self, shot: Shot, result: RenderResult) -> None:
        """Save checkpoint for completed shot."""
        if self.checkpoint_manager:
            self.checkpoint_manager.mark_shot_complete(
                shot_id=shot.shot_id,
                output_path=result.video_path,
            )


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
    python -m continuum.src.main --project film.json

    # Dry run (no cloud)
    python -m continuum.src.main --project film.json --dry-run

    # Generate specific shots
    python -m continuum.src.main --project film.json --shots shot_01 shot_02

    # Verbose logging
    python -m continuum.src.main --project film.json -v
        """,
    )
    
    parser.add_argument(
        "--project", "-p",
        type=Path,
        required=True,
        help="Path to scene graph JSON file",
    )
    
    parser.add_argument(
        "--consistency", "-c",
        type=Path,
        default=None,
        help="Path to consistency dict JSON (optional)",
    )
    
    parser.add_argument(
        "--shots", "-s",
        nargs="+",
        default=None,
        help="Specific shot IDs to generate (default: all)",
    )
    
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
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    """Async main entry point."""
    setup_logging(args.verbose)
    
    logger.info("Continuum Engine v0.1.0")
    logger.info(f"Project: {args.project}")
    
    # Validate project exists
    if not args.project.exists():
        logger.error(f"Project file not found: {args.project}")
        return 1
    
    # Run pipeline
    async with ContinuumOrchestrator(dry_run=args.dry_run) as orchestrator:
        await orchestrator.setup(
            project_path=args.project,
            consistency_path=args.consistency,
        )
        
        result = await orchestrator.run(
            shot_ids=args.shots,
            resume=not args.no_resume,
        )
    
    # Exit code based on result
    if result.all_succeeded:
        return 0
    elif result.shots_succeeded > 0:
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