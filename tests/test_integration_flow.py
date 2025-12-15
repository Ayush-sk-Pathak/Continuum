"""
Continuum Engine - Full Pipeline Integration Tests

=============================================================================
PURPOSE: Prove that all modules connect correctly BEFORE spending money on GPU
=============================================================================

This test validates the complete Shot A → Bridge → Shot B → Verify flow:

1. SceneGraph defines what to generate
2. ConsistencyDict defines what characters look like
3. Renderer generates Shot A
4. BridgeEngine generates transition frame
5. Renderer generates Shot B (with bridge as init_frame)
6. IdentityChecker verifies Alice still looks like Alice

If this test passes, we have HIGH CONFIDENCE that:
- All interfaces are compatible
- Data flows correctly between modules
- The orchestration logic is sound

If this test fails, we catch bugs NOW (free) instead of during GPU rendering ($$$).

=============================================================================
RUNNING THESE TESTS
=============================================================================

From project root:

    # Run all integration tests
    python -m pytest tests/test_integration_flow.py -v

    # Run with detailed output
    python -m pytest tests/test_integration_flow.py -v -s

    # Run specific test
    python -m pytest tests/test_integration_flow.py::TestFullPipeline -v

    # Quick validation (no pytest needed)
    python tests/test_integration_flow.py

=============================================================================
"""

import asyncio
import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import pytest


# =============================================================================
# SECTION 1: MINIMAL INLINE TYPES
# =============================================================================
# These mirror the actual types but are self-contained for test isolation.
# In production, you'd import from the actual modules.


class ShotType(str, Enum):
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"
    EXTREME_CLOSE = "extreme_close"


class TransitionType(str, Enum):
    CUT = "cut"
    DISSOLVE = "dissolve"


class ChunkStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class RenderQuality(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"


class CameraTransition(str, Enum):
    SAME = "same"
    CLOSEUP = "closeup"
    WIDEOUT = "wideout"
    CUSTOM = "custom"


class BridgeMethod(str, Enum):
    CONTROLNET_FULL = "controlnet_full"
    IPADAPTER_ONLY = "ipadapter_only"
    PROMPT_ONLY = "prompt_only"


class IdentityCheckResult(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NO_FACE_BOTH = "no_face_both"
    ERROR = "error"


class AuditStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class JobStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    AUDITING = "auditing"
    APPROVED = "approved"
    FAILED = "failed"
    COMPLETE = "complete"


# =============================================================================
# SECTION 2: DATA STRUCTURES
# =============================================================================

@dataclass
class EntityRef:
    """Reference to an entity in the scene."""
    entity_id: str
    entity_type: str
    display_name: str = ""
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "display_name": self.display_name or self.entity_id,
        }
    
    @classmethod
    def character(cls, entity_id: str, name: str = "") -> "EntityRef":
        return cls(entity_id, "character", name or entity_id)
    
    @classmethod
    def location(cls, entity_id: str, name: str = "") -> "EntityRef":
        return cls(entity_id, "location", name or entity_id)


@dataclass
class CharacterRef:
    """Character reference for rendering."""
    entity_id: str
    name: str
    lora_path: Optional[Path] = None
    face_refs: List[Path] = field(default_factory=list)
    description: str = ""
    lora_strength: float = 0.8
    
    def has_lora(self) -> bool:
        return self.lora_path is not None and self.lora_path.exists()
    
    def has_face_refs(self) -> bool:
        return len(self.face_refs) > 0 and all(p.exists() for p in self.face_refs)


@dataclass
class LocationRef:
    """Location reference for rendering."""
    entity_id: str
    name: str
    ref_images: List[Path] = field(default_factory=list)
    description: str = ""


@dataclass
class CharacterEntity:
    """Character definition in ConsistencyDict."""
    entity_id: str
    name: str
    description: str = ""
    lora_path: Optional[str] = None
    face_refs: List[str] = field(default_factory=list)
    
    def to_character_ref(self, base_path: Path = Path(".")) -> CharacterRef:
        """Convert to CharacterRef for rendering."""
        return CharacterRef(
            entity_id=self.entity_id,
            name=self.name,
            lora_path=Path(self.lora_path) if self.lora_path else None,
            face_refs=[Path(p) for p in self.face_refs],
            description=self.description,
        )


@dataclass
class ConsistencyDict:
    """Maps entity IDs to their visual definitions."""
    characters: Dict[str, CharacterEntity] = field(default_factory=dict)
    locations: Dict[str, dict] = field(default_factory=dict)
    
    def add_character(self, char: CharacterEntity) -> None:
        self.characters[char.entity_id] = char
    
    def get_character(self, entity_id: str) -> Optional[CharacterEntity]:
        return self.characters.get(entity_id)
    
    def get_character_ref(self, entity_id: str) -> Optional[CharacterRef]:
        char = self.get_character(entity_id)
        if char:
            return char.to_character_ref()
        return None


@dataclass
class Chunk:
    """Smallest render unit."""
    chunk_id: str
    shot_id: str
    index: int
    duration_sec: float
    status: ChunkStatus = ChunkStatus.PENDING
    output_path: Optional[str] = None


@dataclass
class Shot:
    """A camera setup within a scene."""
    shot_id: str
    scene_id: str
    index: int
    duration_sec: float
    description: str
    prompt: str
    shot_type: ShotType = ShotType.MEDIUM
    characters: List[EntityRef] = field(default_factory=list)
    location: Optional[EntityRef] = None
    chunks: List[Chunk] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.chunks:
            self.chunks = [Chunk(
                chunk_id=f"{self.shot_id}_chunk_00",
                shot_id=self.shot_id,
                index=0,
                duration_sec=self.duration_sec,
            )]
    
    @property
    def character_ids(self) -> List[str]:
        return [c.entity_id for c in self.characters]


@dataclass
class Scene:
    """A sequence of shots in the same location."""
    scene_id: str
    index: int
    title: str
    description: str
    shots: List[Shot] = field(default_factory=list)
    location: Optional[EntityRef] = None
    characters: List[EntityRef] = field(default_factory=list)
    
    def add_shot(self, shot: Shot) -> None:
        shot.scene_id = self.scene_id
        shot.index = len(self.shots)
        self.shots.append(shot)


@dataclass
class SceneGraph:
    """Complete film structure."""
    project_id: str
    title: str
    scenes: List[Scene] = field(default_factory=list)
    
    def add_scene(self, scene: Scene) -> None:
        scene.index = len(self.scenes)
        self.scenes.append(scene)
    
    @property
    def all_shots(self) -> List[Shot]:
        shots = []
        for scene in self.scenes:
            shots.extend(scene.shots)
        return shots
    
    @property
    def shot_count(self) -> int:
        return sum(len(s.shots) for s in self.scenes)


# =============================================================================
# SECTION 3: MOCK IMPLEMENTATIONS
# =============================================================================

@dataclass
class JobSpec:
    """Render job specification."""
    prompt: str
    duration_sec: float = 4.0
    character_refs: List[CharacterRef] = field(default_factory=list)
    location_refs: List[LocationRef] = field(default_factory=list)
    init_frame: Optional[Path] = None
    width: int = 1280
    height: int = 720
    fps: int = 12
    seed: int = -1
    
    @property
    def frame_count(self) -> int:
        return int(self.duration_sec * self.fps)


@dataclass
class RenderResult:
    """Result of a render job."""
    video_path: Path
    frame_count: int
    fps: float
    duration_sec: float
    resolution: Tuple[int, int]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def exists(self) -> bool:
        return self.video_path.exists()


@dataclass
class BridgeSpec:
    """Specification for bridge frame generation."""
    source_frame: Path
    target_prompt: str
    characters: List[CharacterRef] = field(default_factory=list)
    camera_transition: CameraTransition = CameraTransition.SAME
    target_shot_type: str = "medium"
    seed: int = -1
    width: int = 1280
    height: int = 720
    
    @property
    def source_exists(self) -> bool:
        return self.source_frame.exists()
    
    @classmethod
    def from_shots(
        cls,
        shot_a_last_frame: Path,
        shot_b_prompt: str,
        shot_b_characters: List[CharacterRef],
        shot_a_type: str = "medium",
        shot_b_type: str = "medium",
        **kwargs
    ) -> "BridgeSpec":
        # Infer camera transition
        transition = CameraTransition.SAME
        close_types = {"close", "extreme_close"}
        medium_or_wider = {"wide", "medium", "aerial"}
        
        if shot_a_type in medium_or_wider and shot_b_type in close_types:
            transition = CameraTransition.CLOSEUP
        elif shot_a_type in close_types and shot_b_type in medium_or_wider:
            transition = CameraTransition.WIDEOUT
        elif shot_a_type != shot_b_type:
            transition = CameraTransition.CUSTOM
        
        return cls(
            source_frame=shot_a_last_frame,
            target_prompt=shot_b_prompt,
            characters=shot_b_characters,
            camera_transition=transition,
            target_shot_type=shot_b_type,
            **kwargs
        )


@dataclass
class BridgeResult:
    """Result of bridge frame generation."""
    frame_path: Path
    method: BridgeMethod
    generation_time_sec: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def exists(self) -> bool:
        return self.frame_path.exists()


@dataclass
class FrameFaces:
    """Faces detected in a frame."""
    frame_path: Path
    face_count: int
    
    @property
    def has_faces(self) -> bool:
        return self.face_count > 0


@dataclass
class IdentityComparison:
    """Result of identity comparison."""
    result: IdentityCheckResult
    similarity: Optional[float]
    threshold: float
    source_faces: FrameFaces
    target_faces: FrameFaces
    message: str = ""
    
    @property
    def passed(self) -> bool:
        return self.result == IdentityCheckResult.MATCH
    
    def to_audit_recommendation(self) -> str:
        if self.passed:
            return "approve"
        elif self.result in (IdentityCheckResult.NO_FACE_BOTH,):
            return "manual_review"
        else:
            return "reroll"


@dataclass
class AuditFlag:
    """A single issue found during audit."""
    check_type: str
    frame_range: Tuple[int, int]
    severity: float
    description: str


@dataclass
class AuditResult:
    """Complete audit result."""
    status: AuditStatus
    flags: List[AuditFlag]
    identity_score: Optional[float]
    recommendation: str
    
    @classmethod
    def passed(cls, identity_score: float = 1.0) -> "AuditResult":
        return cls(
            status=AuditStatus.PASS,
            flags=[],
            identity_score=identity_score,
            recommendation="approve"
        )
    
    @classmethod
    def failed(cls, flags: List[AuditFlag], identity_score: Optional[float] = None) -> "AuditResult":
        return cls(
            status=AuditStatus.FAIL,
            flags=flags,
            identity_score=identity_score,
            recommendation="reroll"
        )


class MockRenderer:
    """Mock renderer for testing."""
    
    def __init__(self, output_dir: Path, delay_sec: float = 0.05):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.delay_sec = delay_sec
        self._render_count = 0
    
    async def health_check(self) -> bool:
        return True
    
    async def generate(self, job: JobSpec) -> RenderResult:
        self._render_count += 1
        await asyncio.sleep(self.delay_sec)
        
        # Create fake video file
        video_path = self.output_dir / f"render_{self._render_count:04d}.mp4"
        video_path.write_text(f"MOCK VIDEO: {job.prompt[:50]}")
        
        # Create fake frames
        frames_dir = self.output_dir / f"frames_{self._render_count:04d}"
        frames_dir.mkdir(exist_ok=True)
        
        for i in range(job.frame_count):
            frame_path = frames_dir / f"frame_{i:04d}.png"
            frame_path.write_bytes(b"FAKE_PNG_DATA")
        
        return RenderResult(
            video_path=video_path,
            frame_count=job.frame_count,
            fps=float(job.fps),
            duration_sec=job.duration_sec,
            resolution=(job.width, job.height),
            metadata={
                "mock": True,
                "render_count": self._render_count,
                "frames_dir": str(frames_dir),
                "has_init_frame": job.init_frame is not None,
            }
        )
    
    def get_last_frame_path(self, result: RenderResult) -> Path:
        """Extract last frame from render result."""
        frames_dir = Path(result.metadata["frames_dir"])
        last_frame = frames_dir / f"frame_{result.frame_count - 1:04d}.png"
        return last_frame
    
    def get_first_frame_path(self, result: RenderResult) -> Path:
        """Extract first frame from render result."""
        frames_dir = Path(result.metadata["frames_dir"])
        return frames_dir / "frame_0000.png"


class MockBridgeEngine:
    """Mock bridge engine for testing."""
    
    def __init__(self, output_dir: Path, simulate_delay: float = 0.02):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.simulate_delay = simulate_delay
        self._call_count = 0
    
    async def health_check(self) -> bool:
        return True
    
    def select_method(self, spec: BridgeSpec) -> BridgeMethod:
        has_face_refs = any(c.has_face_refs() for c in spec.characters)
        has_lora = any(c.has_lora() for c in spec.characters)
        
        if has_face_refs or has_lora:
            return BridgeMethod.IPADAPTER_ONLY
        return BridgeMethod.PROMPT_ONLY
    
    async def generate(self, spec: BridgeSpec) -> BridgeResult:
        self._call_count += 1
        
        if not spec.source_exists:
            raise ValueError(f"Source frame not found: {spec.source_frame}")
        
        await asyncio.sleep(self.simulate_delay)
        
        # Copy source as mock output
        output_path = self.output_dir / f"bridge_{self._call_count:04d}.png"
        shutil.copy2(spec.source_frame, output_path)
        
        return BridgeResult(
            frame_path=output_path,
            method=self.select_method(spec),
            generation_time_sec=self.simulate_delay,
            metadata={
                "mock": True,
                "call_count": self._call_count,
                "camera_transition": spec.camera_transition.value,
            }
        )


class MockIdentityChecker:
    """Mock identity checker for testing."""
    
    def __init__(
        self,
        threshold: float = 0.70,
        mock_similarity: float = 0.85,
        mock_face_count: int = 1,
    ):
        self.threshold = threshold
        self.mock_similarity = mock_similarity
        self.mock_face_count = mock_face_count
        self._comparison_count = 0
    
    async def health_check(self) -> bool:
        return True
    
    async def compare(
        self,
        source_frame: Path,
        target_frame: Path,
    ) -> IdentityComparison:
        self._comparison_count += 1
        
        if self.mock_face_count == 0:
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_BOTH,
                similarity=None,
                threshold=self.threshold,
                source_faces=FrameFaces(source_frame, 0),
                target_faces=FrameFaces(target_frame, 0),
                message="Mock: No faces",
            )
        
        result = (
            IdentityCheckResult.MATCH
            if self.mock_similarity >= self.threshold
            else IdentityCheckResult.MISMATCH
        )
        
        return IdentityComparison(
            result=result,
            similarity=self.mock_similarity,
            threshold=self.threshold,
            source_faces=FrameFaces(source_frame, self.mock_face_count),
            target_faces=FrameFaces(target_frame, self.mock_face_count),
            message=f"Mock comparison #{self._comparison_count}",
        )


# =============================================================================
# SECTION 4: ORCHESTRATION LOGIC (What main.py will do)
# =============================================================================

@dataclass
class PipelineConfig:
    """Configuration for the render pipeline."""
    max_attempts: int = 3
    identity_threshold: float = 0.70


@dataclass
class ShotRenderState:
    """Tracks state of a shot through the pipeline."""
    shot: Shot
    status: JobStatus = JobStatus.PENDING
    attempt: int = 0
    render_result: Optional[RenderResult] = None
    bridge_result: Optional[BridgeResult] = None
    identity_result: Optional[IdentityComparison] = None
    audit_result: Optional[AuditResult] = None
    error_message: Optional[str] = None


class PipelineOrchestrator:
    """
    Orchestrates the full render pipeline.
    
    This is a simplified version of what main.py will become.
    It demonstrates the flow:
    
    For each shot:
        1. Build JobSpec from SceneGraph + ConsistencyDict
        2. If not first shot: Generate bridge frame
        3. Render shot (with bridge as init_frame if available)
        4. Extract last frame
        5. Run identity check
        6. If fail and attempts < max: retry
        7. Update audit result
    """
    
    def __init__(
        self,
        renderer: MockRenderer,
        bridge_engine: MockBridgeEngine,
        identity_checker: MockIdentityChecker,
        consistency_dict: ConsistencyDict,
        config: PipelineConfig = None,
    ):
        self.renderer = renderer
        self.bridge_engine = bridge_engine
        self.identity_checker = identity_checker
        self.consistency_dict = consistency_dict
        self.config = config or PipelineConfig()
        
        # State tracking
        self.shot_states: Dict[str, ShotRenderState] = {}
        self.previous_shot_last_frame: Optional[Path] = None
    
    def build_job_spec(
        self,
        shot: Shot,
        init_frame: Optional[Path] = None,
    ) -> JobSpec:
        """
        Build JobSpec from shot definition.
        
        This is where SceneGraph meets ConsistencyDict.
        """
        # Get character references from consistency dict
        character_refs = []
        for char_ref in shot.characters:
            char_entity = self.consistency_dict.get_character(char_ref.entity_id)
            if char_entity:
                character_refs.append(char_entity.to_character_ref())
        
        return JobSpec(
            prompt=shot.prompt,
            duration_sec=shot.duration_sec,
            character_refs=character_refs,
            init_frame=init_frame,
        )
    
    async def render_shot(
        self,
        shot: Shot,
        init_frame: Optional[Path] = None,
    ) -> Tuple[RenderResult, Path]:
        """
        Render a single shot and return result + last frame path.
        """
        job_spec = self.build_job_spec(shot, init_frame)
        result = await self.renderer.generate(job_spec)
        last_frame = self.renderer.get_last_frame_path(result)
        return result, last_frame
    
    async def generate_bridge(
        self,
        source_frame: Path,
        target_shot: Shot,
        source_shot_type: str,
    ) -> BridgeResult:
        """
        Generate bridge frame between shots.
        """
        # Get character refs for target shot
        character_refs = []
        for char_ref in target_shot.characters:
            char_entity = self.consistency_dict.get_character(char_ref.entity_id)
            if char_entity:
                character_refs.append(char_entity.to_character_ref())
        
        bridge_spec = BridgeSpec.from_shots(
            shot_a_last_frame=source_frame,
            shot_b_prompt=target_shot.prompt,
            shot_b_characters=character_refs,
            shot_a_type=source_shot_type,
            shot_b_type=target_shot.shot_type.value,
        )
        
        return await self.bridge_engine.generate(bridge_spec)
    
    async def verify_identity(
        self,
        source_frame: Path,
        target_frame: Path,
    ) -> IdentityComparison:
        """
        Verify identity is preserved between frames.
        """
        return await self.identity_checker.compare(source_frame, target_frame)
    
    async def process_shot(
        self,
        shot: Shot,
        previous_shot: Optional[Shot] = None,
    ) -> ShotRenderState:
        """
        Process a single shot through the full pipeline.
        """
        state = ShotRenderState(shot=shot)
        self.shot_states[shot.shot_id] = state
        
        for attempt in range(self.config.max_attempts):
            state.attempt = attempt + 1
            state.status = JobStatus.GENERATING
            
            try:
                # Step 1: Generate bridge if not first shot
                init_frame = None
                if self.previous_shot_last_frame is not None and previous_shot:
                    state.status = JobStatus.GENERATING
                    bridge_result = await self.generate_bridge(
                        source_frame=self.previous_shot_last_frame,
                        target_shot=shot,
                        source_shot_type=previous_shot.shot_type.value,
                    )
                    state.bridge_result = bridge_result
                    init_frame = bridge_result.frame_path
                
                # Step 2: Render shot
                render_result, last_frame = await self.render_shot(shot, init_frame)
                state.render_result = render_result
                
                # Step 3: Verify identity if we had a bridge
                state.status = JobStatus.AUDITING
                if init_frame is not None:
                    first_frame = self.renderer.get_first_frame_path(render_result)
                    identity_result = await self.verify_identity(
                        source_frame=self.previous_shot_last_frame,
                        target_frame=first_frame,
                    )
                    state.identity_result = identity_result
                    
                    if not identity_result.passed:
                        # Identity check failed
                        if attempt < self.config.max_attempts - 1:
                            continue  # Retry
                        else:
                            state.audit_result = AuditResult.failed(
                                flags=[AuditFlag(
                                    check_type="identity",
                                    frame_range=(0, 1),
                                    severity=1.0 - (identity_result.similarity or 0),
                                    description=f"Identity mismatch: {identity_result.similarity:.3f} < {identity_result.threshold}"
                                )],
                                identity_score=identity_result.similarity,
                            )
                            state.status = JobStatus.FAILED
                            return state
                
                # Step 4: Success!
                state.audit_result = AuditResult.passed(
                    identity_score=state.identity_result.similarity if state.identity_result else 1.0
                )
                state.status = JobStatus.APPROVED
                
                # Update previous frame for next shot
                self.previous_shot_last_frame = last_frame
                
                return state
                
            except Exception as e:
                state.error_message = str(e)
                if attempt < self.config.max_attempts - 1:
                    continue
                else:
                    state.status = JobStatus.FAILED
                    return state
        
        return state
    
    async def process_scene_graph(
        self,
        scene_graph: SceneGraph,
    ) -> Dict[str, ShotRenderState]:
        """
        Process all shots in a scene graph.
        """
        all_shots = scene_graph.all_shots
        previous_shot = None
        
        for shot in all_shots:
            state = await self.process_shot(shot, previous_shot)
            previous_shot = shot
            
            # Stop on failure (in production, might continue with skip)
            if state.status == JobStatus.FAILED:
                break
        
        return self.shot_states


# =============================================================================
# SECTION 5: TEST FIXTURES
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test outputs."""
    path = Path(tempfile.mkdtemp())
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def alice_character(temp_dir) -> CharacterEntity:
    """Create Alice character for testing."""
    # Create face reference files
    face_ref = temp_dir / "alice_face_ref.png"
    face_ref.write_bytes(b"FAKE_FACE_IMAGE")
    
    return CharacterEntity(
        entity_id="alice_001",
        name="Alice",
        description="A young woman with brown hair, wearing a blue dress",
        face_refs=[str(face_ref)],
    )


@pytest.fixture
def kitchen_location() -> EntityRef:
    """Create kitchen location for testing."""
    return EntityRef.location("kitchen_001", "Modern Kitchen")


@pytest.fixture
def consistency_dict(alice_character) -> ConsistencyDict:
    """Create ConsistencyDict with Alice."""
    cd = ConsistencyDict()
    cd.add_character(alice_character)
    return cd


@pytest.fixture
def two_shot_scene_graph(alice_character, kitchen_location) -> SceneGraph:
    """
    Create a minimal 2-shot scene graph for testing.
    
    Shot 1: Medium shot of Alice in kitchen
    Shot 2: Close-up of Alice's face
    """
    alice_ref = EntityRef.character("alice_001", "Alice")
    
    shot1 = Shot(
        shot_id="shot_001",
        scene_id="scene_001",
        index=0,
        duration_sec=4.0,
        description="Alice enters the kitchen",
        prompt="Medium shot of Alice, a young woman with brown hair in blue dress, walking into a modern kitchen, natural lighting",
        shot_type=ShotType.MEDIUM,
        characters=[alice_ref],
        location=kitchen_location,
    )
    
    shot2 = Shot(
        shot_id="shot_002",
        scene_id="scene_001",
        index=1,
        duration_sec=3.0,
        description="Alice looks surprised",
        prompt="Close-up of Alice's face, young woman with brown hair, surprised expression, kitchen background blurred",
        shot_type=ShotType.CLOSE,
        characters=[alice_ref],
        location=kitchen_location,
    )
    
    scene = Scene(
        scene_id="scene_001",
        index=0,
        title="Kitchen Discovery",
        description="Alice enters the kitchen and finds something surprising",
        location=kitchen_location,
        characters=[alice_ref],
    )
    scene.add_shot(shot1)
    scene.add_shot(shot2)
    
    graph = SceneGraph(
        project_id="test_film",
        title="Test Film",
    )
    graph.add_scene(scene)
    
    return graph


@pytest.fixture
def mock_renderer(temp_dir) -> MockRenderer:
    """Create mock renderer."""
    return MockRenderer(output_dir=temp_dir / "renders", delay_sec=0.02)


@pytest.fixture
def mock_bridge_engine(temp_dir) -> MockBridgeEngine:
    """Create mock bridge engine."""
    return MockBridgeEngine(output_dir=temp_dir / "bridges", simulate_delay=0.02)


@pytest.fixture
def mock_identity_checker() -> MockIdentityChecker:
    """Create mock identity checker that passes."""
    return MockIdentityChecker(mock_similarity=0.85)


@pytest.fixture
def failing_identity_checker() -> MockIdentityChecker:
    """Create mock identity checker that fails."""
    return MockIdentityChecker(mock_similarity=0.50)


# =============================================================================
# SECTION 6: TEST CLASSES
# =============================================================================

class TestSceneGraphConstruction:
    """Tests for SceneGraph building."""
    
    def test_create_scene_graph(self, two_shot_scene_graph):
        """Test scene graph creation."""
        assert two_shot_scene_graph.project_id == "test_film"
        assert two_shot_scene_graph.shot_count == 2
        assert len(two_shot_scene_graph.scenes) == 1
    
    def test_shot_has_character(self, two_shot_scene_graph):
        """Test shots contain character references."""
        shots = two_shot_scene_graph.all_shots
        assert all(len(shot.characters) > 0 for shot in shots)
        assert all(shot.characters[0].entity_id == "alice_001" for shot in shots)
    
    def test_shot_types_differ(self, two_shot_scene_graph):
        """Test shot types are different (for bridge testing)."""
        shots = two_shot_scene_graph.all_shots
        assert shots[0].shot_type == ShotType.MEDIUM
        assert shots[1].shot_type == ShotType.CLOSE


class TestConsistencyDictIntegration:
    """Tests for ConsistencyDict integration."""
    
    def test_get_character(self, consistency_dict, alice_character):
        """Test character retrieval."""
        char = consistency_dict.get_character("alice_001")
        assert char is not None
        assert char.name == "Alice"
        assert char.entity_id == alice_character.entity_id
    
    def test_get_character_ref(self, consistency_dict):
        """Test conversion to CharacterRef."""
        ref = consistency_dict.get_character_ref("alice_001")
        assert ref is not None
        assert isinstance(ref, CharacterRef)
        assert ref.entity_id == "alice_001"
    
    def test_missing_character(self, consistency_dict):
        """Test missing character returns None."""
        ref = consistency_dict.get_character_ref("nonexistent")
        assert ref is None


class TestMockRenderer:
    """Tests for MockRenderer behavior."""
    
    @pytest.mark.asyncio
    async def test_render_produces_output(self, mock_renderer):
        """Test rendering produces video file."""
        job = JobSpec(prompt="Test prompt", duration_sec=2.0)
        result = await mock_renderer.generate(job)
        
        assert result.exists
        assert result.frame_count == job.frame_count
        assert result.metadata["mock"] is True
    
    @pytest.mark.asyncio
    async def test_render_with_init_frame(self, mock_renderer, temp_dir):
        """Test rendering with init_frame."""
        init_frame = temp_dir / "init.png"
        init_frame.write_bytes(b"FAKE_INIT")
        
        job = JobSpec(prompt="Test", duration_sec=2.0, init_frame=init_frame)
        result = await mock_renderer.generate(job)
        
        assert result.metadata["has_init_frame"] is True
    
    @pytest.mark.asyncio
    async def test_extract_frames(self, mock_renderer):
        """Test frame extraction from render result."""
        job = JobSpec(prompt="Test", duration_sec=2.0, fps=12)
        result = await mock_renderer.generate(job)
        
        first_frame = mock_renderer.get_first_frame_path(result)
        last_frame = mock_renderer.get_last_frame_path(result)
        
        assert first_frame.exists()
        assert last_frame.exists()
        assert first_frame != last_frame


class TestMockBridgeEngine:
    """Tests for MockBridgeEngine behavior."""
    
    @pytest.mark.asyncio
    async def test_bridge_generation(self, mock_bridge_engine, temp_dir):
        """Test bridge frame generation."""
        source = temp_dir / "source.png"
        source.write_bytes(b"SOURCE_FRAME")
        
        spec = BridgeSpec(
            source_frame=source,
            target_prompt="Close-up shot",
        )
        
        result = await mock_bridge_engine.generate(spec)
        
        assert result.exists
        assert result.method == BridgeMethod.PROMPT_ONLY
    
    @pytest.mark.asyncio
    async def test_bridge_with_character(self, mock_bridge_engine, temp_dir, alice_character):
        """Test bridge uses IP-Adapter when character has refs."""
        source = temp_dir / "source.png"
        source.write_bytes(b"SOURCE")
        
        char_ref = alice_character.to_character_ref()
        spec = BridgeSpec(
            source_frame=source,
            target_prompt="Close-up",
            characters=[char_ref],
        )
        
        result = await mock_bridge_engine.generate(spec)
        
        # Should use IP-Adapter since we have face refs
        assert result.method == BridgeMethod.IPADAPTER_ONLY
    
    def test_camera_transition_inference(self, temp_dir):
        """Test camera transition is correctly inferred."""
        source = temp_dir / "s.png"
        source.write_bytes(b"X")
        
        spec = BridgeSpec.from_shots(
            shot_a_last_frame=source,
            shot_b_prompt="Close-up",
            shot_b_characters=[],
            shot_a_type="medium",
            shot_b_type="close",
        )
        
        assert spec.camera_transition == CameraTransition.CLOSEUP


class TestMockIdentityChecker:
    """Tests for MockIdentityChecker behavior."""
    
    @pytest.mark.asyncio
    async def test_passing_comparison(self, mock_identity_checker, temp_dir):
        """Test identity check passes with high similarity."""
        source = temp_dir / "source.png"
        target = temp_dir / "target.png"
        source.write_bytes(b"S")
        target.write_bytes(b"T")
        
        result = await mock_identity_checker.compare(source, target)
        
        assert result.passed
        assert result.similarity == 0.85
        assert result.to_audit_recommendation() == "approve"
    
    @pytest.mark.asyncio
    async def test_failing_comparison(self, failing_identity_checker, temp_dir):
        """Test identity check fails with low similarity."""
        source = temp_dir / "source.png"
        target = temp_dir / "target.png"
        source.write_bytes(b"S")
        target.write_bytes(b"T")
        
        result = await failing_identity_checker.compare(source, target)
        
        assert not result.passed
        assert result.result == IdentityCheckResult.MISMATCH
        assert result.to_audit_recommendation() == "reroll"


# =============================================================================
# SECTION 7: FULL PIPELINE TESTS (The Main Event)
# =============================================================================

class TestFullPipeline:
    """
    Integration tests for the complete pipeline.
    
    These are the critical tests that prove all modules work together.
    """
    
    @pytest.mark.asyncio
    async def test_single_shot_render(
        self,
        mock_renderer,
        mock_bridge_engine,
        mock_identity_checker,
        consistency_dict,
        two_shot_scene_graph,
    ):
        """Test rendering a single shot works."""
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=mock_identity_checker,
            consistency_dict=consistency_dict,
        )
        
        shot = two_shot_scene_graph.all_shots[0]
        state = await orchestrator.process_shot(shot)
        
        assert state.status == JobStatus.APPROVED
        assert state.render_result is not None
        assert state.render_result.exists
        assert state.bridge_result is None  # First shot, no bridge
    
    @pytest.mark.asyncio
    async def test_two_shot_sequence_with_bridge(
        self,
        mock_renderer,
        mock_bridge_engine,
        mock_identity_checker,
        consistency_dict,
        two_shot_scene_graph,
    ):
        """
        THE CRITICAL TEST: Shot A → Bridge → Shot B with identity verification.
        """
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=mock_identity_checker,
            consistency_dict=consistency_dict,
        )
        
        # Process both shots
        results = await orchestrator.process_scene_graph(two_shot_scene_graph)
        
        # Verify Shot 1
        state1 = results["shot_001"]
        assert state1.status == JobStatus.APPROVED
        assert state1.render_result is not None
        assert state1.bridge_result is None  # First shot
        
        # Verify Shot 2 (with bridge)
        state2 = results["shot_002"]
        assert state2.status == JobStatus.APPROVED
        assert state2.render_result is not None
        assert state2.bridge_result is not None  # Has bridge!
        assert state2.bridge_result.exists
        
        # Verify identity was checked
        assert state2.identity_result is not None
        assert state2.identity_result.passed
        assert state2.identity_result.similarity == 0.85
        
        # Verify audit passed
        assert state2.audit_result is not None
        assert state2.audit_result.status == AuditStatus.PASS
        
        print("\n" + "=" * 60)
        print("✅ FULL PIPELINE TEST PASSED")
        print("=" * 60)
        print(f"  Shot 1: {state1.status.value}")
        print(f"  Shot 2: {state2.status.value}")
        print(f"  Bridge generated: {state2.bridge_result.frame_path.name}")
        print(f"  Identity score: {state2.identity_result.similarity:.3f}")
        print(f"  Camera transition: {state2.bridge_result.metadata['camera_transition']}")
        print("=" * 60)
    
    @pytest.mark.asyncio
    async def test_identity_failure_triggers_reroll(
        self,
        mock_renderer,
        mock_bridge_engine,
        failing_identity_checker,
        consistency_dict,
        two_shot_scene_graph,
    ):
        """Test that identity failure triggers retry and eventually fails."""
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=failing_identity_checker,
            consistency_dict=consistency_dict,
            config=PipelineConfig(max_attempts=3),
        )
        
        results = await orchestrator.process_scene_graph(two_shot_scene_graph)
        
        # Shot 1 should pass (no identity check on first shot)
        state1 = results["shot_001"]
        assert state1.status == JobStatus.APPROVED
        
        # Shot 2 should fail after max attempts
        state2 = results["shot_002"]
        assert state2.status == JobStatus.FAILED
        assert state2.attempt == 3  # Used all attempts
        assert state2.audit_result.status == AuditStatus.FAIL
        
        print("\n  ✅ Identity failure correctly triggered reroll and eventual failure")
    
    @pytest.mark.asyncio
    async def test_job_spec_includes_character_refs(
        self,
        mock_renderer,
        mock_bridge_engine,
        mock_identity_checker,
        consistency_dict,
        two_shot_scene_graph,
    ):
        """Test that JobSpec is built with character refs from ConsistencyDict."""
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=mock_identity_checker,
            consistency_dict=consistency_dict,
        )
        
        shot = two_shot_scene_graph.all_shots[0]
        job_spec = orchestrator.build_job_spec(shot)
        
        assert len(job_spec.character_refs) == 1
        assert job_spec.character_refs[0].entity_id == "alice_001"
        assert job_spec.character_refs[0].name == "Alice"
    
    @pytest.mark.asyncio
    async def test_bridge_uses_correct_shot_types(
        self,
        mock_renderer,
        mock_bridge_engine,
        mock_identity_checker,
        consistency_dict,
        two_shot_scene_graph,
    ):
        """Test bridge correctly infers camera transition from shot types."""
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=mock_identity_checker,
            consistency_dict=consistency_dict,
        )
        
        results = await orchestrator.process_scene_graph(two_shot_scene_graph)
        
        state2 = results["shot_002"]
        bridge_meta = state2.bridge_result.metadata
        
        # Medium → Close should be detected as CLOSEUP
        assert bridge_meta["camera_transition"] == "closeup"


class TestMultiShotSequence:
    """Tests for longer sequences."""
    
    @pytest.fixture
    def four_shot_scene_graph(self, alice_character, kitchen_location) -> SceneGraph:
        """Create a 4-shot scene for sequence testing."""
        alice_ref = EntityRef.character("alice_001", "Alice")
        
        shots_config = [
            ("Wide establishing shot", ShotType.WIDE),
            ("Medium shot of Alice", ShotType.MEDIUM),
            ("Close-up reaction", ShotType.CLOSE),
            ("Wide shot resolution", ShotType.WIDE),
        ]
        
        scene = Scene(
            scene_id="scene_001",
            index=0,
            title="Kitchen Sequence",
            description="Alice in the kitchen",
            location=kitchen_location,
            characters=[alice_ref],
        )
        
        for i, (desc, shot_type) in enumerate(shots_config):
            shot = Shot(
                shot_id=f"shot_{i+1:03d}",
                scene_id="scene_001",
                index=i,
                duration_sec=3.0,
                description=desc,
                prompt=f"{shot_type.value} shot, Alice, kitchen, {desc}",
                shot_type=shot_type,
                characters=[alice_ref],
                location=kitchen_location,
            )
            scene.add_shot(shot)
        
        graph = SceneGraph(project_id="test", title="Test")
        graph.add_scene(scene)
        return graph
    
    @pytest.mark.asyncio
    async def test_four_shot_sequence(
        self,
        mock_renderer,
        mock_bridge_engine,
        mock_identity_checker,
        consistency_dict,
        four_shot_scene_graph,
    ):
        """Test processing a 4-shot sequence."""
        orchestrator = PipelineOrchestrator(
            renderer=mock_renderer,
            bridge_engine=mock_bridge_engine,
            identity_checker=mock_identity_checker,
            consistency_dict=consistency_dict,
        )
        
        results = await orchestrator.process_scene_graph(four_shot_scene_graph)
        
        # All shots should pass
        assert len(results) == 4
        assert all(s.status == JobStatus.APPROVED for s in results.values())
        
        # First shot has no bridge
        assert results["shot_001"].bridge_result is None
        
        # All other shots have bridges
        for i in range(2, 5):
            shot_id = f"shot_{i:03d}"
            assert results[shot_id].bridge_result is not None
            assert results[shot_id].identity_result is not None
        
        print(f"\n  ✅ Successfully processed 4-shot sequence")
        print(f"     Bridges generated: 3")
        print(f"     Identity checks: 3")


# =============================================================================
# SECTION 8: MAIN EXECUTION
# =============================================================================

def run_quick_validation():
    """
    Quick validation without pytest.
    
    Usage: python tests/test_integration_flow.py
    """
    print("=" * 70)
    print("INTEGRATION FLOW QUICK VALIDATION")
    print("=" * 70)
    
    async def validate():
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Setup
            print("\n📦 Setting up test fixtures...")
            
            # Create Alice
            face_ref = temp_dir / "alice_face.png"
            face_ref.write_bytes(b"FACE_DATA")
            
            alice = CharacterEntity(
                entity_id="alice_001",
                name="Alice",
                description="Young woman with brown hair",
                face_refs=[str(face_ref)],
            )
            
            consistency_dict = ConsistencyDict()
            consistency_dict.add_character(alice)
            
            # Create scene graph
            alice_ref = EntityRef.character("alice_001", "Alice")
            kitchen_ref = EntityRef.location("kitchen", "Kitchen")
            
            shot1 = Shot(
                shot_id="shot_001",
                scene_id="scene_001",
                index=0,
                duration_sec=4.0,
                description="Medium shot",
                prompt="Medium shot of Alice in kitchen",
                shot_type=ShotType.MEDIUM,
                characters=[alice_ref],
            )
            
            shot2 = Shot(
                shot_id="shot_002",
                scene_id="scene_001",
                index=1,
                duration_sec=3.0,
                description="Close-up",
                prompt="Close-up of Alice's face",
                shot_type=ShotType.CLOSE,
                characters=[alice_ref],
            )
            
            scene = Scene(
                scene_id="scene_001",
                index=0,
                title="Test Scene",
                description="Test",
                characters=[alice_ref],
            )
            scene.add_shot(shot1)
            scene.add_shot(shot2)
            
            graph = SceneGraph(project_id="test", title="Test")
            graph.add_scene(scene)
            
            print(f"   ✓ Created scene graph with {graph.shot_count} shots")
            
            # Create mocks
            renderer = MockRenderer(output_dir=temp_dir / "renders", delay_sec=0.01)
            bridge_engine = MockBridgeEngine(output_dir=temp_dir / "bridges", simulate_delay=0.01)
            identity_checker = MockIdentityChecker(mock_similarity=0.85)
            
            # Create orchestrator
            orchestrator = PipelineOrchestrator(
                renderer=renderer,
                bridge_engine=bridge_engine,
                identity_checker=identity_checker,
                consistency_dict=consistency_dict,
            )
            
            # Run pipeline
            print("\n🎬 Running full pipeline...")
            print("   Shot 1: Rendering...", end=" ")
            
            results = await orchestrator.process_scene_graph(graph)
            
            # Verify results
            state1 = results["shot_001"]
            state2 = results["shot_002"]
            
            print("✓")
            print("   Shot 2: Rendering + Bridge + Identity...", end=" ")
            
            # Assertions
            assert state1.status == JobStatus.APPROVED, f"Shot 1 failed: {state1.status}"
            assert state2.status == JobStatus.APPROVED, f"Shot 2 failed: {state2.status}"
            assert state2.bridge_result is not None, "No bridge generated"
            assert state2.identity_result is not None, "No identity check"
            assert state2.identity_result.passed, "Identity check failed"
            
            print("✓")
            
            # Summary
            print("\n" + "=" * 70)
            print("✅ ALL VALIDATIONS PASSED")
            print("=" * 70)
            print(f"\n📊 Results Summary:")
            print(f"   Shots processed: {len(results)}")
            print(f"   Shot 1 status: {state1.status.value}")
            print(f"   Shot 2 status: {state2.status.value}")
            print(f"   Bridge frame: {state2.bridge_result.frame_path.name}")
            print(f"   Bridge method: {state2.bridge_result.method.value}")
            print(f"   Camera transition: {state2.bridge_result.metadata['camera_transition']}")
            print(f"   Identity score: {state2.identity_result.similarity:.3f}")
            print(f"   Identity threshold: {state2.identity_result.threshold:.2f}")
            print(f"   Audit result: {state2.audit_result.status.value}")
            print("\n" + "=" * 70)
            print("🎉 The pipeline is ready for real GPU testing!")
            print("=" * 70)
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    asyncio.run(validate())


if __name__ == "__main__":
    run_quick_validation()