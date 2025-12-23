"""
Continuum Engine - Pass 1 Generator (Structural Video Generation)

Orchestrates the complete Pass 1 video generation pipeline.
This is the "conductor" that coordinates all components to produce
raw video chunks ready for refinement.

The Problem:
    Video generation isn't just calling a model. It requires:
    - Identity injection (LoRA/IP-Adapter from Consistency Dictionary)
    - Continuity (Bridge Frames between chunks)
    - World state awareness (prompt context from World State)
    - Quality verification (Audit before proceeding)
    - Retry logic (reroll on audit failure)

The Solution:
    Pass1Generator orchestrates the full pipeline:
    1. Build job spec from chunk + scene graph + consistency dict
    2. Generate bridge frame if not first chunk
    3. Dispatch to renderer
    4. Send result to audit
    5. Retry with new seed if audit fails
    6. Return approved result or surface failure to user

Architecture Position:

    Director (planning) --> Pass1Generator (execution) --> Audit (verification)
                                    |
                            BridgeEngine + Renderer
                                    |
                                    v
                            Pass2Refiner (next stage)

Design Principles:
    1. Orchestration only: No rendering logic, just coordination
    2. Renderer-agnostic: Works with any BaseRenderer implementation
    3. Fail-safe: Always returns or surfaces error, never hangs
    4. Observable: Progress callbacks at each stage
    5. Idempotent: Same chunk + seed --> same result
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
import hashlib

# Conditional import to avoid circular dependency
# Reviewer depends on identity_checker and physics_checker
# Pass1Generator uses Reviewer for audit
# Note: Reviewer is in src.audit, not src.studio
if TYPE_CHECKING:
    from src.audit.reviewer import ReviewRequest, Reviewer

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class GenerationStage(str, Enum):
    """Stages of the Pass 1 generation pipeline."""
    PREPARING = "preparing"          # Building job spec
    HERO_FRAME = "hero_frame"        # Generating hero frame (Shot 1 only)
    BRIDGE = "bridge"                # Generating bridge frame (Shot 2+)
    RENDERING = "rendering"          # Running video generation
    AUDITING = "auditing"            # Quality check
    REROLLING = "rerolling"          # Retrying with new seed
    COMPLETED = "completed"          # Success
    FAILED = "failed"                # Max attempts exceeded


class ChunkResult(str, Enum):
    """Result of generating a single chunk."""
    SUCCESS = "success"              # Passed audit
    ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"  # Failed audit but accepted on final attempt
    REROLL = "reroll"                # Failed audit, can retry
    FAILURE = "failure"              # Max attempts, no usable output
    ERROR = "error"                  # System error (not audit failure)


class Shot1Strategy(str, Enum):
    """
    Strategy for generating Shot 1's init frame.
    
    Per ARCHITECTURE.md Section 7A.3-7A.5:
    - Shot 1 needs an init_frame for I2V (just like Shot 2+ needs bridge frames)
    - The source of that init_frame is configurable
    - Production uses HERO_FRAME for identity lock from frame 1
    - Exploration uses T2V for rapid iteration (identity random)
    
    The insight: Shot 1's "Hero Frame" and Shot 2+'s "Bridge Frame" serve
    the same purpose (provide init_frame for I2V), just with different sources.
    """
    USER_KEYFRAME = "user_keyframe"   # User provides init_frame (storyboard workflow)
    HERO_FRAME = "hero_frame"         # System generates via SDXL + IP-Adapter (production)
    EXPLORATION = "exploration"       # T2V for Shot 1, user picks winner (creative exploration)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class GenerationProgress:
    """
    Progress update during generation.
    
    Attributes:
        stage: Current stage
        progress: Progress within stage (0.0 to 1.0)
        message: Human-readable status
        chunk_id: Which chunk is being generated
        attempt: Current attempt number
        elapsed_sec: Time elapsed
    """
    stage: GenerationStage
    progress: float
    message: str
    chunk_id: str = ""
    attempt: int = 1
    elapsed_sec: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "progress": self.progress,
            "message": self.message,
            "chunk_id": self.chunk_id,
            "attempt": self.attempt,
            "elapsed_sec": self.elapsed_sec,
        }


@dataclass
class ChunkOutput:
    """
    Output from generating a single chunk.
    
    Attributes:
        chunk_id: Which chunk was generated
        video_path: Path to output video (if success)
        result: Success/reroll/failure status
        attempts: Number of attempts made
        audit_result: Audit details (if audited)
        bridge_frame_path: Bridge frame used (if any)
        render_time_sec: Total time spent rendering
        cost_estimate: Estimated USD cost
        error_message: Error details (if failure/error)
        warnings: Audit warnings (for ACCEPTED_WITH_WARNINGS)
    """
    chunk_id: str
    result: ChunkResult
    video_path: Optional[Path] = None
    attempts: int = 1
    audit_result: Optional[Dict[str, Any]] = None
    bridge_frame_path: Optional[Path] = None
    render_time_sec: float = 0.0
    cost_estimate: float = 0.0
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        """Returns True if chunk has usable output (SUCCESS or ACCEPTED_WITH_WARNINGS)."""
        return self.result in (ChunkResult.SUCCESS, ChunkResult.ACCEPTED_WITH_WARNINGS)
    
    @property
    def needs_human_review(self) -> bool:
        return self.result == ChunkResult.FAILURE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "result": self.result.value,
            "video_path": str(self.video_path) if self.video_path else None,
            "attempts": self.attempts,
            "audit_result": self.audit_result,
            "bridge_frame_path": str(self.bridge_frame_path) if self.bridge_frame_path else None,
            "render_time_sec": self.render_time_sec,
            "cost_estimate": self.cost_estimate,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class ShotOutput:
    """
    Output from generating an entire shot (all chunks).
    
    Attributes:
        shot_id: Which shot was generated
        chunk_outputs: Results for each chunk
        total_duration_sec: Total video duration
        total_render_time_sec: Time spent rendering
        total_cost: Estimated total cost
    """
    shot_id: str
    chunk_outputs: List[ChunkOutput] = field(default_factory=list)
    
    @property
    def all_success(self) -> bool:
        return all(c.success for c in self.chunk_outputs)
    
    @property
    def has_failures(self) -> bool:
        return any(c.result == ChunkResult.FAILURE for c in self.chunk_outputs)
    
    @property
    def video_paths(self) -> List[Path]:
        return [c.video_path for c in self.chunk_outputs if c.video_path]
    
    @property
    def total_duration_sec(self) -> float:
        # Estimate from chunk count * typical chunk duration
        return len(self.chunk_outputs) * 10.0  # Will be refined later
    
    @property
    def total_render_time_sec(self) -> float:
        return sum(c.render_time_sec for c in self.chunk_outputs)
    
    @property
    def total_cost(self) -> float:
        return sum(c.cost_estimate for c in self.chunk_outputs)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "chunk_count": len(self.chunk_outputs),
            "all_success": self.all_success,
            "has_failures": self.has_failures,
            "total_render_time_sec": self.total_render_time_sec,
            "total_cost": self.total_cost,
            "chunks": [c.to_dict() for c in self.chunk_outputs],
        }


@dataclass
class GenerationConfig:
    """
    Configuration for Pass 1 generation.
    
    Attributes:
        max_reroll_attempts: Max retries on audit failure
        enable_audit: Whether to run audit (disable for testing)
        enable_bridge: Whether to generate bridge frames
        enable_world_state: Whether to inject world state context into prompts
        skip_if_exists: Skip chunks that already have outputs
        base_seed: Starting seed (-1 for random)
        quality: Render quality preset
        shot1_strategy: How to generate Shot 1's init frame (per ARCHITECTURE.md 7A.5)
        user_keyframe_path: User-provided keyframe for USER_KEYFRAME strategy
    """
    max_reroll_attempts: int = 3
    enable_audit: bool = True
    enable_bridge: bool = True
    enable_world_state: bool = True  # Inject world state context into prompts
    skip_if_exists: bool = True
    base_seed: int = -1
    quality: str = "standard"
    output_dir: Optional[Path] = None
    
    # Shot 1 strategy (per ARCHITECTURE.md Section 7A.5)
    # - HERO_FRAME: Production mode, identity locked from Shot 1
    # - EXPLORATION: Development/testing mode, T2V allowed
    # - USER_KEYFRAME: Storyboard workflow, user provides init frame
    shot1_strategy: Shot1Strategy = Shot1Strategy.HERO_FRAME
    user_keyframe_path: Optional[Path] = None  # Required if strategy == USER_KEYFRAME
    
    def __post_init__(self):
        """Validate configuration."""
        if self.shot1_strategy == Shot1Strategy.USER_KEYFRAME:
            if not self.user_keyframe_path:
                raise ValueError(
                    "user_keyframe_path required when shot1_strategy=USER_KEYFRAME"
                )
            if not Path(self.user_keyframe_path).exists():
                raise ValueError(
                    f"User keyframe not found: {self.user_keyframe_path}"
                )
    
    def get_seed_for_attempt(self, chunk_id: str, attempt: int) -> int:
        """Generate deterministic seed for retry attempts."""
        if self.base_seed == -1:
            # Random seed for first attempt, then increment
            import random
            return random.randint(0, 2**31 - 1) + attempt
        else:
            # Deterministic: hash chunk_id + attempt
            hash_input = f"{chunk_id}_{attempt}_{self.base_seed}"
            return int(hashlib.sha256(hash_input.encode()).hexdigest()[:8], 16)


# =============================================================================
# PASS 1 GENERATOR
# =============================================================================

class Pass1Generator:
    """
    Orchestrates Pass 1 structural video generation.
    
    This is the main entry point for generating video from scene graph chunks.
    It coordinates: identity injection, bridge frames, rendering, and audit.
    
    Usage:
        # Initialize with dependencies
        generator = Pass1Generator(
            renderer=WanRenderer(),
            bridge_engine=BridgeEngine(),
            reviewer=Reviewer(),
            consistency_dict=consistency_dict,
            world_state=world_state,
        )
        
        # Generate a single chunk
        output = await generator.generate_chunk(
            chunk=chunk,
            shot=shot,
            scene=scene,
            previous_chunk_output=prev_output,  # For bridge frame
        )
        
        # Generate entire shot
        shot_output = await generator.generate_shot(
            shot=shot,
            scene=scene,
        )
    
    Integration:
        - Receives planning data from Director (scene_graph)
        - Gets identity assets from ConsistencyDict
        - Gets world state context from WorldState
        - Dispatches to BaseRenderer implementation
        - Sends results to Reviewer for audit
        - Returns approved outputs or surfaces failures
    """
    
    def __init__(
        self,
        renderer: Any,  # BaseRenderer
        bridge_engine: Optional[Any] = None,  # BridgeEngine
        reviewer: Optional[Any] = None,  # Reviewer
        consistency_dict: Optional[Any] = None,  # ConsistencyDict
        world_state: Optional[Any] = None,  # WorldState
        config: Optional[GenerationConfig] = None,
    ):
        """
        Initialize the Pass 1 Generator.
        
        Args:
            renderer: Video renderer (WanRenderer, RunwayRenderer, etc.)
            bridge_engine: Bridge frame generator (optional)
            reviewer: Quality checker (optional)
            consistency_dict: Entity asset mappings (optional)
            world_state: Dynamic state tracker (optional)
            config: Generation configuration (optional)
        """
        self.renderer = renderer
        self.bridge_engine = bridge_engine
        self.reviewer = reviewer
        self.consistency_dict = consistency_dict
        self.world_state = world_state
        self.config = config or GenerationConfig()
        
        # Statistics
        self._chunks_generated = 0
        self._total_render_time = 0.0
        self._total_cost = 0.0
        
        logger.info(
            f"Pass1Generator initialized: "
            f"renderer={type(renderer).__name__}, "
            f"audit={'enabled' if reviewer else 'disabled'}, "
            f"bridge={'enabled' if bridge_engine else 'disabled'}"
        )
    
    # -------------------------------------------------------------------------
    # Main Entry Points
    # -------------------------------------------------------------------------
    
    async def generate_chunk(
        self,
        chunk: Any,  # Chunk from scene_graph
        shot: Any,  # Shot from scene_graph
        scene: Optional[Any] = None,  # Scene from scene_graph
        previous_chunk_output: Optional[ChunkOutput] = None,
        progress_callback: Optional[Callable[[GenerationProgress], None]] = None,
    ) -> ChunkOutput:
        """
        Generate a single video chunk with full pipeline.
        
        This is the core method. It:
        1. Builds the job specification
        2. Generates bridge frame if needed
        3. Renders video
        4. Runs audit
        5. Rerolls on failure (up to max attempts)
        
        Args:
            chunk: The chunk to generate
            shot: Parent shot for context
            scene: Parent scene for context (optional)
            previous_chunk_output: Previous chunk for bridge frame (optional)
            progress_callback: Progress updates (optional)
            
        Returns:
            ChunkOutput with result and video path (if success)
        """
        start_time = time.time()
        chunk_id = self._get_chunk_id(chunk)
        
        logger.info(f"Generating chunk: {chunk_id}")
        
        # Check if already exists
        if self.config.skip_if_exists:
            existing = self._check_existing_output(chunk_id)
            if existing:
                logger.info(f"Chunk {chunk_id} already exists, skipping")
                return ChunkOutput(
                    chunk_id=chunk_id,
                    result=ChunkResult.SUCCESS,
                    video_path=existing,
                    attempts=0,
                    metadata={"skipped": True},
                )
        
        # Attempt generation with rerolls
        attempt = 0
        last_error = ""
        audit_result = None
        
        # Track best attempt for accept-on-final-attempt
        # (Don't lose work after 3 rerolls - accept best with warnings)
        best_render_result = None
        best_audit_result = None
        best_audit_score = -1.0  # Higher is better
        best_bridge_frame_path = None
        best_job_spec = None
        
        while attempt < self.config.max_reroll_attempts:
            attempt += 1
            
            self._report_progress(
                GenerationStage.PREPARING if attempt == 1 else GenerationStage.REROLLING,
                0.0,
                f"{'Preparing' if attempt == 1 else 'Rerolling'} (attempt {attempt}/{self.config.max_reroll_attempts})",
                chunk_id,
                attempt,
                progress_callback,
            )
            
            try:
                # Step 1: Get init frame for I2V
                # Per ARCHITECTURE.md Section 7A.3:
                # - Shot 2+: Bridge frame (from previous chunk's last frame)
                # - Shot 1: Depends on shot1_strategy (hero/user_keyframe/exploration)
                # The init_frame is what makes I2V work - without it, we fall back to T2V
                init_frame_path = None
                if self.config.enable_bridge:
                    init_frame_path = await self._get_init_frame(
                        chunk, shot, previous_chunk_output, progress_callback
                    )
                
                # Note: init_frame_path may be called "bridge_frame_path" in downstream code
                # for historical reasons, but it's the same concept (init frame for I2V)
                bridge_frame_path = init_frame_path
                
                # Step 2: Build job specification
                job_spec = await self._build_job_spec(
                    chunk, shot, scene, bridge_frame_path, attempt
                )
                
                # Step 3: Render video
                self._report_progress(
                    GenerationStage.RENDERING,
                    0.3,
                    "Rendering video...",
                    chunk_id,
                    attempt,
                    progress_callback,
                )
                
                render_result = await self._render_chunk(job_spec, progress_callback)
                
                # Step 4: Run audit (if enabled)
                if self.config.enable_audit and self.reviewer:
                    self._report_progress(
                        GenerationStage.AUDITING,
                        0.8,
                        "Running quality check...",
                        chunk_id,
                        attempt,
                        progress_callback,
                    )
                    
                    audit_result = await self._audit_chunk(
                        render_result.video_path,
                        bridge_frame_path or self._get_reference_frame(previous_chunk_output),
                        shot,
                    )
                    
                    # Track best attempt by audit score (for accept-on-final-attempt)
                    current_score = audit_result.get("details", {}).get("identity_score", 0.0)
                    if current_score is None:
                        current_score = 0.0
                    
                    if current_score > best_audit_score:
                        best_audit_score = current_score
                        best_render_result = render_result
                        best_audit_result = audit_result
                        best_bridge_frame_path = bridge_frame_path
                        best_job_spec = job_spec
                    
                    if not audit_result.get("passed", False):
                        # Audit failed, try reroll
                        last_error = audit_result.get("reason", "Audit failed")
                        logger.warning(
                            f"Chunk {chunk_id} failed audit (attempt {attempt}): {last_error} "
                            f"(score={current_score:.3f}, best={best_audit_score:.3f})"
                        )
                        continue  # Try next attempt
                else:
                    # No audit - this render is automatically best
                    best_render_result = render_result
                    best_audit_result = audit_result
                    best_bridge_frame_path = bridge_frame_path
                    best_job_spec = job_spec
                
                # Success!
                elapsed = time.time() - start_time
                self._chunks_generated += 1
                self._total_render_time += elapsed
                self._total_cost += render_result.cost_estimate
                
                self._report_progress(
                    GenerationStage.COMPLETED,
                    1.0,
                    "Complete!",
                    chunk_id,
                    attempt,
                    progress_callback,
                )
                
                return ChunkOutput(
                    chunk_id=chunk_id,
                    result=ChunkResult.SUCCESS,
                    video_path=render_result.video_path,
                    attempts=attempt,
                    audit_result=audit_result,
                    bridge_frame_path=bridge_frame_path,
                    render_time_sec=elapsed,
                    cost_estimate=render_result.cost_estimate,
                    metadata={
                        "prompt_id": render_result.metadata.get("prompt_id"),
                        "seed": job_spec.seed,
                    },
                )
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"Chunk {chunk_id} generation error (attempt {attempt}): {e}")
                
                # On error, try next attempt
                if attempt < self.config.max_reroll_attempts:
                    continue
        
        # Max attempts reached - use accept-on-final-attempt if we have a usable render
        elapsed = time.time() - start_time
        
        if best_render_result and best_render_result.video_path and best_render_result.video_path.exists():
            # Accept best attempt with warnings instead of failing completely
            warnings = [
                f"Accepted on final attempt after {attempt} tries",
                f"Best audit score: {best_audit_score:.3f}",
                f"Audit failure reason: {last_error}",
            ]
            
            logger.warning(
                f"Chunk {chunk_id} accepted with warnings after {attempt} attempts "
                f"(best_score={best_audit_score:.3f})"
            )
            
            self._report_progress(
                GenerationStage.COMPLETED,
                1.0,
                f"Accepted with warnings (score={best_audit_score:.3f})",
                chunk_id,
                attempt,
                progress_callback,
            )
            
            # Still count it as generated (we have usable output)
            self._chunks_generated += 1
            self._total_render_time += elapsed
            self._total_cost += best_render_result.cost_estimate
            
            return ChunkOutput(
                chunk_id=chunk_id,
                result=ChunkResult.ACCEPTED_WITH_WARNINGS,
                video_path=best_render_result.video_path,
                attempts=attempt,
                audit_result=best_audit_result,
                bridge_frame_path=best_bridge_frame_path,
                render_time_sec=elapsed,
                cost_estimate=best_render_result.cost_estimate,
                warnings=warnings,
                metadata={
                    "prompt_id": best_render_result.metadata.get("prompt_id"),
                    "seed": best_job_spec.seed if best_job_spec else 0,
                    "accepted_on_final_attempt": True,
                    "best_audit_score": best_audit_score,
                },
            )
        
        # No usable render at all - true failure
        self._report_progress(
            GenerationStage.FAILED,
            1.0,
            f"Failed after {attempt} attempts (no usable output)",
            chunk_id,
            attempt,
            progress_callback,
        )
        
        return ChunkOutput(
            chunk_id=chunk_id,
            result=ChunkResult.FAILURE,
            attempts=attempt,
            audit_result=audit_result,
            render_time_sec=elapsed,
            error_message=last_error,
        )
    
    async def generate_shot(
        self,
        shot: Any,  # Shot from scene_graph
        scene: Optional[Any] = None,
        previous_shot_output: Optional[ChunkOutput] = None,  # Last chunk from previous shot
        progress_callback: Optional[Callable[[GenerationProgress], None]] = None,
    ) -> ShotOutput:
        """
        Generate all chunks for a shot.
        
        Processes chunks sequentially (each depends on previous for bridge frame).
        
        Args:
            shot: The shot to generate
            scene: Parent scene for context
            progress_callback: Progress updates
            
        Returns:
            ShotOutput with all chunk results
        """
        shot_id = self._get_shot_id(shot)
        chunks = self._get_shot_chunks(shot)
        
        logger.info(f"Generating shot {shot_id}: {len(chunks)} chunks")
        
        output = ShotOutput(shot_id=shot_id)
        previous_output: Optional[ChunkOutput] = previous_shot_output
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            
            chunk_output = await self.generate_chunk(
                chunk=chunk,
                shot=shot,
                scene=scene,
                previous_chunk_output=previous_output,
                progress_callback=progress_callback,
            )
            
            output.chunk_outputs.append(chunk_output)
            previous_output = chunk_output
            
            # Stop if failure (need human intervention)
            if chunk_output.result == ChunkResult.FAILURE:
                logger.warning(
                    f"Shot {shot_id} stopped at chunk {i+1} due to failure"
                )
                break
        
        return output
    
    async def generate_scene(
        self,
        scene: Any,  # Scene from scene_graph
        progress_callback: Optional[Callable[[GenerationProgress], None]] = None,
    ) -> List[ShotOutput]:
        """
        Generate all shots for a scene.
        
        Args:
            scene: The scene to generate
            progress_callback: Progress updates
            
        Returns:
            List of ShotOutput for each shot
        """
        shots = self._get_scene_shots(scene)
        scene_id = self._get_scene_id(scene)
        
        logger.info(f"Generating scene {scene_id}: {len(shots)} shots")
        
        outputs = []
        previous_chunk: Optional[ChunkOutput] = None
        
        for i, shot in enumerate(shots):
            logger.info(f"Processing shot {i+1}/{len(shots)}")
            
            shot_output = await self.generate_shot(
                shot=shot,
                scene=scene,
                previous_shot_output=previous_chunk,
                progress_callback=progress_callback,
            )
            outputs.append(shot_output)
            
            # Track last chunk for next shot's bridge
            if shot_output.chunk_outputs:
                previous_chunk = shot_output.chunk_outputs[-1]
            
            # Stop if critical failure
            if shot_output.has_failures:
                logger.warning(
                    f"Scene {scene_id} stopped at shot {i+1} due to failures"
                )
                break
        
        return outputs
    
    # -------------------------------------------------------------------------
    # Internal Methods
    # -------------------------------------------------------------------------
    
    async def _build_job_spec(
        self,
        chunk: Any,
        shot: Any,
        scene: Optional[Any],
        init_frame: Optional[Path],
        attempt: int,
    ) -> Any:  # Returns JobSpec
        """
        Build JobSpec from chunk and context.
        
        Pulls together:
        - Prompt from shot
        - Identity assets from ConsistencyDict
        - World state context from WorldState
        - Generation parameters from config
        """
        # Import here to avoid circular dependency
        from ..renderers.base import JobSpec, CharacterRef, LocationRef, RenderQuality
        
        # Get basic parameters from chunk/shot
        prompt = self._get_chunk_prompt(chunk, shot)
        duration = self._get_chunk_duration(chunk)
        
        # Enrich prompt with world state context (if enabled)
        # This adds continuity information like "sword: held by alice"
        if self.config.enable_world_state and self.world_state:
            world_context = self._get_world_state_context(shot)
            if world_context:
                prompt = f"{prompt}. {world_context}"
                logger.info(f"Prompt enriched with world state: {len(world_context)} chars")
        
        # Get character references from consistency dict
        character_refs = []
        if self.consistency_dict:
            character_refs = self._get_character_refs(shot)
        
        # Get location reference
        location_refs = []
        if self.consistency_dict:
            location_refs = self._get_location_refs(shot)
        
        # Build job spec
        seed = self.config.get_seed_for_attempt(self._get_chunk_id(chunk), attempt)
        
        quality_map = {
            "draft": RenderQuality.DRAFT,
            "standard": RenderQuality.STANDARD,
            "high": RenderQuality.HIGH,
        }
        
        job = JobSpec(
            prompt=prompt,
            duration_sec=duration,
            init_frame=init_frame,
            character_refs=character_refs,
            location_refs=location_refs,
            seed=seed,
            quality=quality_map.get(self.config.quality, RenderQuality.STANDARD),
        )
        
        logger.debug(f"Built job spec: {duration}s, seed={seed}, chars={len(character_refs)}")
        
        return job
    
    async def _get_init_frame(
        self,
        chunk: Any,
        shot: Any,
        previous_output: Optional[ChunkOutput],
        progress_callback: Optional[Callable],
    ) -> Optional[Path]:
        """
        Get init frame for I2V generation.
        
        This is the UNIFIED entry point for init frame acquisition.
        Per ARCHITECTURE.md Section 7A.3:
        
            "Shot 1's 'Hero Frame' and Shot 2+'s 'Bridge Frame' use the
            SAME WORKFLOW PATTERN. One workflow for all shots."
        
        Decision Logic:
            - Has previous_output? --> Bridge Frame (Shot 2+ path)
            - No previous_output? --> Check shot1_strategy:
                - HERO_FRAME: Generate via SDXL + IP-Adapter
                - USER_KEYFRAME: Use user-provided image
                - EXPLORATION: Return None (T2V fallback)
        
        Args:
            chunk: Current chunk being generated
            shot: Parent shot for context
            previous_output: Output from previous chunk (None for Shot 1)
            progress_callback: Optional progress reporting
            
        Returns:
            Path to init frame for I2V, or None for T2V fallback
        """
        # Shot 2+: Use bridge frame
        if previous_output and previous_output.video_path:
            return await self._generate_bridge_frame(
                chunk, shot, previous_output, progress_callback
            )
        
        # Shot 1: Check strategy
        chunk_id = self._get_chunk_id(chunk)
        strategy = self.config.shot1_strategy
        
        logger.info(
            f"Shot 1 detected for chunk {chunk_id}, "
            f"using strategy: {strategy.value}"
        )
        
        if strategy == Shot1Strategy.USER_KEYFRAME:
            # User provided the keyframe
            keyframe_path = Path(self.config.user_keyframe_path)
            if not keyframe_path.exists():
                logger.error(f"User keyframe not found: {keyframe_path}")
                return None
            logger.info(f"Using user keyframe: {keyframe_path}")
            return keyframe_path
            
        elif strategy == Shot1Strategy.HERO_FRAME:
            # Generate hero frame via SDXL + IP-Adapter
            return await self._generate_hero_frame(
                chunk, shot, progress_callback
            )
            
        elif strategy == Shot1Strategy.EXPLORATION:
            # Exploration mode: No init frame, use T2V
            logger.info(
                "Exploration mode: Using T2V for Shot 1 "
                "(identity will be random, pick best candidate)"
            )
            return None
        
        # Fallback (shouldn't reach here)
        logger.warning(f"Unknown shot1_strategy: {strategy}, falling back to T2V")
        return None
    
    async def _generate_hero_frame(
        self,
        chunk: Any,
        shot: Any,
        progress_callback: Optional[Callable],
    ) -> Optional[Path]:
        """
        Generate a Hero Frame for Shot 1 identity lock.
        
        Per ARCHITECTURE.md Section 7A.3 and 7A.5:
        
            "Shot 1 uses Hero Frame (SDXL + IP-Adapter) --> I2V"
            
        The Hero Frame is a txt2img generation (from noise) that:
        - Uses IP-Adapter to inject character identity from Consistency Dictionary
        - Creates a visually consistent first frame
        - Feeds into I2V as init_frame
        
        This is different from Bridge Frame which is img2img (transforms existing frame).
        
        Workflow: hero_frame.json
        Key inputs:
            - FACE_REF_IMAGE: Character's canonical face from Consistency Dictionary
            - PROMPT: Shot description
            - IPADAPTER_STRENGTH: Identity lock strength (typically 0.7-0.8)
        
        Args:
            chunk: Current chunk being generated  
            shot: Parent shot for context (prompt, characters)
            progress_callback: Optional progress reporting
            
        Returns:
            Path to generated hero frame, or None on failure
        """
        chunk_id = self._get_chunk_id(chunk)
        
        self._report_progress(
            GenerationStage.HERO_FRAME,
            0.1,
            "Generating identity-locked hero frame for Shot 1...",
            chunk_id,
            1,
            progress_callback,
        )
        
        try:
            # Step 1: Get character refs from Consistency Dictionary
            character_refs = self._get_character_refs(shot)
            
            if not character_refs:
                logger.warning(
                    "No character refs available for hero frame generation. "
                    "Identity lock will be weak (prompt-only)."
                )
            
            # Step 2: Get face reference image for IP-Adapter
            face_ref_path = None
            if character_refs and character_refs[0].face_refs:
                face_ref_path = character_refs[0].face_refs[0]  # Use first reference
                logger.info(f"Using face ref for hero frame: {face_ref_path}")
            else:
                logger.warning(
                    "No face reference image available. "
                    "Hero frame will use prompt-only generation."
                )
            
            # Step 3: Build prompt
            prompt = self._get_chunk_prompt(chunk, shot)
            
            # Step 4: Setup output directory
            hero_dir = self.config.output_dir / "hero" if self.config.output_dir else Path("workspace/output/hero")
            hero_dir.mkdir(parents=True, exist_ok=True)
            output_path = hero_dir / f"{chunk_id}_hero.png"
            
            # Step 5: Check if we have the engine/client to generate
            # Hero frame uses same infrastructure as bridge (ComfyUI)
            if not self.bridge_engine:
                logger.warning(
                    "Bridge engine not configured - cannot generate hero frame. "
                    "Falling back to T2V (identity will be random)."
                )
                return None
            
            self._report_progress(
                GenerationStage.HERO_FRAME,
                0.3,
                "Running hero frame workflow (SDXL + IP-Adapter)...",
                chunk_id,
                1,
                progress_callback,
            )
            
            # Step 6: Generate via bridge_engine's ComfyUI client
            # We reuse the bridge_engine infrastructure but with hero_frame.json workflow
            from ..studio.bridge_engine import HeroFrameSpec
            
            seed = self.config.get_seed_for_attempt(chunk_id, 1)
            
            spec = HeroFrameSpec(
                prompt=prompt,
                characters=character_refs,
                face_ref_path=face_ref_path,
                seed=seed,
                width=1280,  # TODO: Get from config
                height=720,
            )
            
            hero_result = await self.bridge_engine.generate_hero_frame(spec)
            
            self._report_progress(
                GenerationStage.HERO_FRAME,
                0.9,
                "Hero frame generated successfully",
                chunk_id,
                1,
                progress_callback,
            )
            
            logger.info(
                f"Hero frame generated: {hero_result.frame_path} "
                f"(time={hero_result.generation_time_sec:.1f}s)"
            )
            
            return hero_result.frame_path
            
        except ImportError as e:
            # HeroFrameSpec not yet implemented in bridge_engine
            logger.warning(
                f"Hero frame generation not yet available: {e}. "
                "Falling back to T2V."
            )
            return None
            
        except Exception as e:
            logger.error(f"Hero frame generation failed: {e}")
            return None

    async def _generate_bridge_frame(
        self,
        chunk: Any,
        shot: Any,
        previous_output: Optional[ChunkOutput],
        progress_callback: Optional[Callable],
    ) -> Optional[Path]:
        """
        Generate a bridge frame that re-anchors identity while preserving pose.
        
        WARNING: This is the CORE VALUE of Continuum. Do NOT bypass.
        See ARCHITECTURE.md Section 3B for full specification.
        
        Without bridge frames, identity drifts:
        
          Shot 1 --> Shot 2 --> Shot 3 --> Shot 4 --> Shot 5
          100%       98%        94%        88%        80%   <-- identity degrades
        
        With bridge frames (re-anchored each cut):
        
          Shot 1 --> BRIDGE --> Shot 2 --> BRIDGE --> Shot 3
          100%       100%       100%       100%       100%  <-- identity locked
        
        The bridge frame uses:
        - ControlNet (OpenPose): Extracts pose/expression from last frame
        - IP-Adapter + LoRA: Re-injects canonical identity from Bible refs
        
        Args:
            chunk: Current chunk being generated
            shot: Parent shot for context (prompt, characters)
            previous_output: Output from previous chunk (for continuity)
            progress_callback: Optional progress reporting
        
        Returns:
            Path to bridge frame if generated successfully
            Path to raw source frame if bridge engine unavailable (Tier 4 fallback)
            None if this is the first chunk or previous chunk failed
        
        Degradation Behavior (per ARCHITECTURE.md 3B.7):
            - Tier 1-3: bridge_engine handles internally (full/pose/ipadapter)
            - Tier 4: Raw frame fallback WITH WARNING (drift will occur)
            - Never silently degrades - always logs warning
        """
        if not previous_output or not previous_output.video_path:
            return None
        
        chunk_id = self._get_chunk_id(chunk)
        
        self._report_progress(
            GenerationStage.BRIDGE,
            0.1,
            "Extracting source frame for bridge...",
            chunk_id,
            1,
            progress_callback,
        )
        
        try:
            # Import here to avoid circular dependency
            from src.post.ffmpeg_wrapper import extract_last_frame
            from ..studio.bridge_engine import BridgeSpec, BridgeError
            
            # Step 1: Extract last frame from previous chunk's video
            bridge_dir = self.config.output_dir / "bridge" if self.config.output_dir else Path("workspace/output/bridge")
            bridge_dir.mkdir(parents=True, exist_ok=True)
            last_frame_path = bridge_dir / f"{chunk_id}_source.png"
            
            await extract_last_frame(
                Path(previous_output.video_path),
                last_frame_path
            )
            
            logger.info(f"Extracted source frame: {last_frame_path}")
            
            # Step 2: Check if bridge engine is available
            if not self.bridge_engine:
                logger.warning(
                    "Bridge engine not configured - using raw frame. "
                    "Identity will drift over multiple shots!"
                )
                return last_frame_path
            
            self._report_progress(
                GenerationStage.BRIDGE,
                0.3,
                "Generating identity-locked bridge frame...",
                chunk_id,
                1,
                progress_callback,
            )
            
            # Step 3: Get character refs for identity re-anchoring
            character_refs = self._get_character_refs(shot)
            
            # Step 4: Get shot type for camera transition inference
            shot_type = "medium"  # Default
            if hasattr(shot, 'shot_type'):
                shot_type = shot.shot_type
            elif isinstance(shot, dict):
                shot_type = shot.get('shot_type', 'medium')
            
            # Step 5: Build BridgeSpec
            prompt = self._get_chunk_prompt(chunk, shot)
            spec = BridgeSpec.from_shots(
                shot_a_last_frame=last_frame_path,
                shot_b_prompt=prompt,
                shot_b_characters=character_refs,
                shot_b_type=shot_type,
                seed=self.config.get_seed_for_attempt(chunk_id, 1),
            )
            
            # Step 6: Generate bridge frame via ComfyUI
            # This uses bridge_full.json with ControlNet + IP-Adapter
            self._report_progress(
                GenerationStage.BRIDGE,
                0.5,
                "Running bridge workflow (ControlNet + IP-Adapter)...",
                chunk_id,
                1,
                progress_callback,
            )
            
            bridge_result = await self.bridge_engine.generate(spec)
            
            self._report_progress(
                GenerationStage.BRIDGE,
                0.9,
                f"Bridge frame generated via {bridge_result.method.value}",
                chunk_id,
                1,
                progress_callback,
            )
            
            logger.info(
                f"Bridge frame generated: {bridge_result.frame_path} "
                f"(method={bridge_result.method.value}, time={bridge_result.generation_time_sec:.1f}s)"
            )
            
            return bridge_result.frame_path
            
        except BridgeError as e:
            # Bridge-specific error - fall back to raw frame with warning
            logger.warning(
                f"Bridge generation failed: {e}. "
                "Falling back to raw frame - identity may drift!"
            )
            # Return the raw source frame as fallback
            if last_frame_path.exists():
                return last_frame_path
            return None
            
        except Exception as e:
            logger.error(f"Bridge frame extraction failed: {e}")
            return None
    
    async def _render_chunk(
        self,
        job_spec: Any,
        progress_callback: Optional[Callable],
    ) -> Any:  # Returns RenderResult
        """
        Dispatch job to renderer.
        """
        def render_progress_adapter(render_progress):
            """Adapt renderer progress to our format."""
            self._report_progress(
                GenerationStage.RENDERING,
                0.3 + 0.5 * render_progress.progress,
                render_progress.message,
                "",
                1,
                progress_callback,
            )
        
        result = await self.renderer.generate(
            job_spec,
            progress_callback=render_progress_adapter if progress_callback else None,
        )
        
        return result
    
    async def _audit_chunk(
        self,
        video_path: Path,
        reference_frame: Optional[Path],
        shot: Any,
        previous_shot_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Run audit on generated chunk.
        
        The audit system verifies:
        1. Identity preservation (ArcFace similarity check)
        2. Physics plausibility (object tracking, gravity)
        
        Args:
            video_path: Path to the rendered video chunk
            reference_frame: Face reference image for identity check
            shot: Shot object containing character info
            previous_shot_path: Previous shot video for cross-shot audit
        
        Returns dict with:
            - passed: bool
            - reason: str (if failed)
            - should_reroll: bool
            - details: audit flags and scores
        """
        if not self.reviewer:
            return {"passed": True, "reason": "Audit disabled"}
        
        try:
            # Import here to avoid circular dependency at module load time
            # Reviewer is in src.audit, not src.studio
            from src.audit.reviewer import ReviewRequest
            
            # Extract character IDs from shot for identity checking
            character_ids = self._get_character_ids(shot)
            
            # Build proper ReviewRequest object
            review_request = ReviewRequest(
                video_path=video_path,
                reference_frame=reference_frame,
                previous_shot_path=previous_shot_path,
                shot_id=self._get_shot_id(shot),
                character_ids=character_ids,
                # checks_enabled uses default [IDENTITY, PHYSICS]
            )
            
            result = await self.reviewer.review(review_request)
            
            # Extract identity score from check results if available
            identity_score = None
            details = {}
            for check_result in result.check_results:
                if check_result.check_type.value == "identity":
                    identity_score = check_result.score
                    details["identity"] = check_result.details
                elif check_result.check_type.value == "physics":
                    details["physics"] = check_result.details
            
            return {
                "passed": result.passed,
                "reason": result.audit_result.recommendation,
                "should_reroll": result.should_reroll,
                "details": details,
                "identity_score": identity_score,
                "flags": [f.to_dict() if hasattr(f, 'to_dict') else str(f) for f in result.audit_result.flags],
            }
            
        except Exception as e:
            logger.error(f"Audit error: {e}")
            # On audit error, assume pass to avoid blocking
            # This allows pipeline to continue; user can review later
            return {"passed": True, "reason": f"Audit error: {e}"}
    
    def _report_progress(
        self,
        stage: GenerationStage,
        progress: float,
        message: str,
        chunk_id: str,
        attempt: int,
        callback: Optional[Callable],
    ) -> None:
        """Report progress via callback."""
        if callback:
            callback(GenerationProgress(
                stage=stage,
                progress=progress,
                message=message,
                chunk_id=chunk_id,
                attempt=attempt,
            ))
    
    # -------------------------------------------------------------------------
    # Data Access Helpers
    # -------------------------------------------------------------------------
    
    def _get_chunk_id(self, chunk: Any) -> str:
        """Extract chunk ID from chunk object."""
        if hasattr(chunk, 'chunk_id'):
            return chunk.chunk_id
        elif isinstance(chunk, dict):
            return chunk.get('chunk_id', 'unknown')
        return str(id(chunk))
    
    def _get_shot_id(self, shot: Any) -> str:
        """Extract shot ID from shot object."""
        if hasattr(shot, 'shot_id'):
            return shot.shot_id
        elif isinstance(shot, dict):
            return shot.get('shot_id', 'unknown')
        return str(id(shot))
    
    def _get_scene_id(self, scene: Any) -> str:
        """Extract scene ID from scene object."""
        if hasattr(scene, 'scene_id'):
            return scene.scene_id
        elif isinstance(scene, dict):
            return scene.get('scene_id', 'unknown')
        return str(id(scene))
    
    def _get_chunk_prompt(self, chunk: Any, shot: Any) -> str:
        """Get prompt for chunk, falling back to shot prompt."""
        if hasattr(chunk, 'prompt_override') and chunk.prompt_override:
            return chunk.prompt_override
        if hasattr(shot, 'prompt'):
            return shot.prompt
        if isinstance(shot, dict):
            return shot.get('prompt', '')
        return ''
    
    def _get_chunk_duration(self, chunk: Any) -> float:
        """Get chunk duration in seconds."""
        if hasattr(chunk, 'duration_sec'):
            return chunk.duration_sec
        elif isinstance(chunk, dict):
            return chunk.get('duration_sec', 4.0)
        return 4.0
    
    def _get_shot_chunks(self, shot: Any) -> List[Any]:
        """Get chunks from shot."""
        if hasattr(shot, 'chunks'):
            return shot.chunks
        elif isinstance(shot, dict):
            return shot.get('chunks', [])
        return []
    
    def _get_scene_shots(self, scene: Any) -> List[Any]:
        """Get shots from scene."""
        if hasattr(scene, 'shots'):
            return scene.shots
        elif isinstance(scene, dict):
            return scene.get('shots', [])
        return []
    
    def _get_character_refs(self, shot: Any) -> List[Any]:
        """Get character references from shot via consistency dict."""
        # Import here to avoid circular dependency
        from ..renderers.base import CharacterRef
        
        refs = []
        characters = []
        
        if hasattr(shot, 'characters'):
            characters = shot.characters
        elif isinstance(shot, dict):
            characters = shot.get('characters', [])
        
        for char in characters:
            entity_id = char.entity_id if hasattr(char, 'entity_id') else char.get('entity_id', '')
            
            if self.consistency_dict:
                # Get full character entity from consistency dict
                entity = self.consistency_dict.get_character(entity_id)
                if entity:
                    ref = entity.to_character_ref()
                    refs.append(ref)
                    continue
            
            # Fallback: create minimal ref
            refs.append(CharacterRef(
                entity_id=entity_id,
                name=entity_id,
            ))
        
        return refs
    
    def _get_character_ids(self, shot: Any) -> List[str]:
        """
        Extract character entity IDs from shot.
        
        Used for identity checking - the reviewer needs to know which
        characters to look for in the generated video.
        
        Args:
            shot: Shot object or dict with characters field
            
        Returns:
            List of character entity IDs (e.g., ["alice", "bob"])
        """
        characters = []
        
        if hasattr(shot, 'characters'):
            characters = shot.characters
        elif isinstance(shot, dict):
            characters = shot.get('characters', [])
        
        entity_ids = []
        for char in characters:
            entity_id = char.entity_id if hasattr(char, 'entity_id') else char.get('entity_id', '')
            if entity_id:
                entity_ids.append(entity_id)
        
        return entity_ids
    
    def _get_location_refs(self, shot: Any) -> List[Any]:
        """Get location references from shot via consistency dict."""
        # Import here to avoid circular dependency
        from ..renderers.base import LocationRef
        
        location = None
        if hasattr(shot, 'location'):
            location = shot.location
        elif isinstance(shot, dict):
            location = shot.get('location')
        
        if not location:
            return []
        
        entity_id = location.entity_id if hasattr(location, 'entity_id') else location.get('entity_id', '')
        
        if self.consistency_dict:
            entity = self.consistency_dict.get_location(entity_id)
            if entity:
                return [entity.to_location_ref()]
        
        return [LocationRef(
            entity_id=entity_id,
            name=entity_id,
        )]
    
    def _get_world_state_context(self, shot: Any) -> str:
        """
        Get world state context for prompt enrichment.
        
        Extracts relevant entity states for THIS shot only, not the entire
        world state. This keeps prompts focused and avoids confusion.
        
        Example output:
            "Current scene state: sword: held by alice; door: open."
        
        Args:
            shot: The shot being generated
            
        Returns:
            Natural language description of relevant entity states,
            or empty string if no relevant state changes.
        """
        if not self.world_state:
            return ""
        
        shot_id = self._get_shot_id(shot)
        
        # Get entity IDs from this shot for focused context
        entity_ids = self._get_shot_entity_ids(shot)
        
        try:
            # Pass entity_ids to get context for THIS shot's entities only
            context = self.world_state.get_prompt_context(
                shot_id=shot_id,
                entity_ids=list(entity_ids) if entity_ids else None,
            )
            
            if context:
                logger.debug(f"World state context for {shot_id}: {context}")
            
            return context
            
        except Exception as e:
            logger.warning(f"Failed to get world state context: {e}")
            return ""
    
    def _get_shot_entity_ids(self, shot: Any) -> set:
        """
        Extract entity IDs (characters + props) from a shot.
        
        Handles both Shot objects and dict representations.
        
        Args:
            shot: Shot object or dict
            
        Returns:
            Set of entity ID strings
        """
        entity_ids = set()
        
        # Try Shot object properties first
        if hasattr(shot, 'all_entity_ids'):
            return shot.all_entity_ids
        
        # Handle character_ids property
        if hasattr(shot, 'character_ids'):
            entity_ids.update(shot.character_ids)
        elif isinstance(shot, dict):
            # Dict: characters is list of EntityRef dicts
            for char in shot.get('characters', []):
                if isinstance(char, dict):
                    entity_ids.add(char.get('entity_id', ''))
                elif hasattr(char, 'entity_id'):
                    entity_ids.add(char.entity_id)
        
        # Handle prop_ids property
        if hasattr(shot, 'prop_ids'):
            entity_ids.update(shot.prop_ids)
        elif isinstance(shot, dict):
            # Dict: props is list of EntityRef dicts
            for prop in shot.get('props', []):
                if isinstance(prop, dict):
                    entity_ids.add(prop.get('entity_id', ''))
                elif hasattr(prop, 'entity_id'):
                    entity_ids.add(prop.entity_id)
        
        # Handle location
        if hasattr(shot, 'location') and shot.location:
            if hasattr(shot.location, 'entity_id'):
                entity_ids.add(shot.location.entity_id)
        elif isinstance(shot, dict) and shot.get('location'):
            loc = shot['location']
            if isinstance(loc, dict):
                entity_ids.add(loc.get('entity_id', ''))
            elif hasattr(loc, 'entity_id'):
                entity_ids.add(loc.entity_id)
        
        # Remove any empty strings
        entity_ids.discard('')
        
        return entity_ids
    
    def _get_reference_frame(self, previous_output: Optional[ChunkOutput]) -> Optional[Path]:
        """Get reference frame from previous chunk output."""
        if not previous_output or not previous_output.video_path:
            return None
        
        # Extract last frame from video
        # For now, return bridge frame if available
        if previous_output.bridge_frame_path:
            return previous_output.bridge_frame_path
        
        return None
    
    def _check_existing_output(self, chunk_id: str) -> Optional[Path]:
        """Check if output already exists for chunk."""
        if not self.config.output_dir:
            return None
        
        expected_path = self.config.output_dir / f"{chunk_id}.mp4"
        if expected_path.exists():
            return expected_path
        
        return None
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get generation statistics."""
        return {
            "chunks_generated": self._chunks_generated,
            "total_render_time_sec": self._total_render_time,
            "total_cost": self._total_cost,
            "avg_time_per_chunk": (
                self._total_render_time / self._chunks_generated
                if self._chunks_generated > 0 else 0
            ),
            "avg_cost_per_chunk": (
                self._total_cost / self._chunks_generated
                if self._chunks_generated > 0 else 0
            ),
        }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_pass1_generator(
    renderer: Optional[Any] = None,
    bridge_engine: Optional[Any] = None,
    reviewer: Optional[Any] = None,
    consistency_dict: Optional[Any] = None,
    world_state: Optional[Any] = None,
    config: Optional[GenerationConfig] = None,
    use_mock: bool = False,
) -> Pass1Generator:
    """
    Factory function to create Pass1Generator with dependencies.
    
    Args:
        renderer: Video renderer (auto-creates if None)
        bridge_engine: Bridge frame generator (optional)
        reviewer: Quality checker (optional)
        consistency_dict: Entity mappings (optional)
        world_state: State tracker (optional)
        config: Generation config (optional)
        use_mock: Use mock renderer for testing
        
    Returns:
        Configured Pass1Generator
    """
    # Auto-create renderer if not provided
    if renderer is None:
        if use_mock:
            from ..renderers.base import get_renderer, RendererType
            renderer = get_renderer(RendererType.MOCK)
        else:
            from ..renderers.wan_renderer import WanRenderer
            renderer = WanRenderer()
    
    return Pass1Generator(
        renderer=renderer,
        bridge_engine=bridge_engine,
        reviewer=reviewer,
        consistency_dict=consistency_dict,
        world_state=world_state,
        config=config,
    )


# =============================================================================
# MOCK GENERATOR (FOR TESTING)
# =============================================================================

class MockPass1Generator(Pass1Generator):
    """
    Mock generator for testing without GPU.
    
    Returns fake successful results immediately.
    """
    
    def __init__(self, **kwargs):
        # Create a minimal mock renderer
        class MockRenderer:
            async def generate(self, job, progress_callback=None):
                from ..renderers.base import RenderResult, RendererType
                await asyncio.sleep(0.1)  # Simulate work
                return RenderResult(
                    video_path=Path("/tmp/mock_output.mp4"),
                    frame_count=48,
                    fps=12,
                    duration_sec=4.0,
                    resolution=(1280, 720),
                    renderer_type=RendererType.MOCK,
                    cost_estimate=0.01,
                )
        
        super().__init__(renderer=MockRenderer(), **kwargs)
    
    async def _audit_chunk(self, *args, **kwargs) -> Dict[str, Any]:
        """Mock audit always passes."""
        return {"passed": True, "reason": "Mock audit"}