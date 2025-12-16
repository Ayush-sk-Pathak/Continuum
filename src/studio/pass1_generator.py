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
    Director (planning) → Pass1Generator (execution) → Audit (verification)
                                    ↓
                            BridgeEngine + Renderer
                                    ↓
                            Pass2Refiner (next stage)

Design Principles:
    1. Orchestration only: No rendering logic, just coordination
    2. Renderer-agnostic: Works with any BaseRenderer implementation
    3. Fail-safe: Always returns or surfaces error, never hangs
    4. Observable: Progress callbacks at each stage
    5. Idempotent: Same chunk + seed → same result
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import hashlib

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class GenerationStage(str, Enum):
    """Stages of the Pass 1 generation pipeline."""
    PREPARING = "preparing"          # Building job spec
    BRIDGE = "bridge"                # Generating bridge frame
    RENDERING = "rendering"          # Running video generation
    AUDITING = "auditing"            # Quality check
    REROLLING = "rerolling"          # Retrying with new seed
    COMPLETED = "completed"          # Success
    FAILED = "failed"                # Max attempts exceeded


class ChunkResult(str, Enum):
    """Result of generating a single chunk."""
    SUCCESS = "success"              # Passed audit
    REROLL = "reroll"                # Failed audit, can retry
    FAILURE = "failure"              # Max attempts, needs human
    ERROR = "error"                  # System error (not audit failure)


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
    
    @property
    def success(self) -> bool:
        return self.result == ChunkResult.SUCCESS
    
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
        skip_if_exists: Skip chunks that already have outputs
        base_seed: Starting seed (-1 for random)
        quality: Render quality preset
    """
    max_reroll_attempts: int = 3
    enable_audit: bool = True
    enable_bridge: bool = True
    skip_if_exists: bool = True
    base_seed: int = -1
    quality: str = "standard"
    output_dir: Optional[Path] = None
    
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
                # Step 1: Generate bridge frame if needed
                bridge_frame_path = None
                if self.config.enable_bridge and self.bridge_engine:
                    bridge_frame_path = await self._generate_bridge_frame(
                        chunk, shot, previous_chunk_output, progress_callback
                    )
                
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
                    
                    if not audit_result.get("passed", False):
                        # Audit failed, try reroll
                        last_error = audit_result.get("reason", "Audit failed")
                        logger.warning(
                            f"Chunk {chunk_id} failed audit (attempt {attempt}): {last_error}"
                        )
                        continue  # Try next attempt
                
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
        
        # Max attempts reached
        elapsed = time.time() - start_time
        
        self._report_progress(
            GenerationStage.FAILED,
            1.0,
            f"Failed after {attempt} attempts",
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
        previous_output: Optional[ChunkOutput] = None
        
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
        for i, shot in enumerate(shots):
            logger.info(f"Processing shot {i+1}/{len(shots)}")
            
            shot_output = await self.generate_shot(
                shot=shot,
                scene=scene,
                progress_callback=progress_callback,
            )
            outputs.append(shot_output)
            
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
        
        # Enrich prompt with world state
        if self.world_state:
            world_context = self._get_world_state_context(shot)
            if world_context:
                prompt = f"{prompt}. {world_context}"
        
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
    
    async def _generate_bridge_frame(
        self,
        chunk: Any,
        shot: Any,
        previous_output: Optional[ChunkOutput],
        progress_callback: Optional[Callable],
    ) -> Optional[Path]:
        """
        Generate bridge frame from previous chunk.
        
        Returns None if:
        - This is the first chunk
        - Previous chunk failed
        - Bridge engine not available
        """
        if not previous_output or not previous_output.video_path:
            return None
        
        if not self.bridge_engine:
            return None
        
        self._report_progress(
            GenerationStage.BRIDGE,
            0.1,
            "Generating bridge frame...",
            self._get_chunk_id(chunk),
            1,
            progress_callback,
        )
        
        try:
            # Extract last frame from previous chunk
            # Generate bridge frame for current chunk's perspective
            bridge_request = {
                "source_video": previous_output.video_path,
                "target_shot": shot,
                "chunk": chunk,
            }
            
            bridge_result = await self.bridge_engine.generate(bridge_request)
            return bridge_result.bridge_frame_path
            
        except Exception as e:
            logger.warning(f"Bridge frame generation failed: {e}")
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
    ) -> Dict[str, Any]:
        """
        Run audit on generated chunk.
        
        Returns dict with:
        - passed: bool
        - reason: str (if failed)
        - details: audit flags
        """
        if not self.reviewer:
            return {"passed": True, "reason": "Audit disabled"}
        
        try:
            # Build review request
            review_request = {
                "video_path": video_path,
                "reference_frame": reference_frame,
                "shot_id": self._get_shot_id(shot),
            }
            
            result = await self.reviewer.review(review_request)
            
            return {
                "passed": result.passed,
                "reason": result.recommendation if hasattr(result, 'recommendation') else "",
                "should_reroll": result.should_reroll if hasattr(result, 'should_reroll') else not result.passed,
                "details": result.to_dict() if hasattr(result, 'to_dict') else {},
            }
            
        except Exception as e:
            logger.error(f"Audit error: {e}")
            # On audit error, assume pass to avoid blocking
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
        """Get world state context for prompt enrichment."""
        if not self.world_state:
            return ""
        
        shot_id = self._get_shot_id(shot)
        
        try:
            return self.world_state.get_prompt_context(shot_id)
        except Exception as e:
            logger.warning(f"Failed to get world state context: {e}")
            return ""
    
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