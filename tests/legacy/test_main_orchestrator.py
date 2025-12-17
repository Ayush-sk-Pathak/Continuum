"""
Continuum Engine - Orchestrator Tests

Comprehensive test suite for main.py covering:
- Happy path scenarios
- Stress tests
- Nightmare scenarios (things that WILL go wrong in production)
- Edge cases and race conditions

Test Philosophy:
1. Mock cloud dependencies (no real GPU calls)
2. Test failure modes, not just success
3. Verify state management under chaos
4. Ensure crash recovery works

Project Structure:
    Continuum/
    ├── main.py                      <-- Module under test (at root)
    ├── src/
    │   ├── core/
    │   ├── director/
    │   ├── renderers/
    │   ├── studio/
    │   └── audit/
    └── tests/
        └── test_main_orchestrator.py  <-- This file

Run with: pytest tests/test_main_orchestrator.py -v
"""

import asyncio
import json
import pytest
import tempfile
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import logging
import numpy as np

# Module under test (main.py is at project root)
from main import (
    ContinuumOrchestrator,
    PipelineResult,
    ShotResult,
    setup_logging,
)

# Dependencies to mock (from src/ subpackages)
from src.core.job_state import JobStatus, AuditStatus
from src.core.config import Config, ComfyUIConfig, GenerationConfig, AuditConfig, PathsConfig
from src.director.scene_graph import (
    SceneGraph, Scene, Shot, Chunk, ChunkStatus,
    EntityRef, ShotType, TransitionType
)
from src.director.consistency_dict import ConsistencyDict, CharacterEntity, LocationEntity
from src.renderers.base import (
    BaseRenderer, JobSpec, RenderResult, RenderProgress,
    CharacterRef, LocationRef, RendererType
)
from src.studio.bridge_engine import (
    BaseBridgeEngine, BridgeSpec, BridgeResult, BridgeMethod,
    BridgeError, BridgeGenerationError
)
from src.audit.identity_checker import (
    BaseIdentityChecker, IdentityComparison, IdentityCheckResult,
    FrameFaces, FaceEmbedding
)

# =============================================================================
# TEST FIXTURES - Reusable test data
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    dir_path = Path(tempfile.mkdtemp(prefix="continuum_test_"))
    yield dir_path
    # Cleanup
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def mock_config(temp_dir):
    """Create mock configuration."""
    return Config(
        comfyui=ComfyUIConfig(
            host="ws://mock:8188",
            timeout_sec=30.0,
        ),
        generation=GenerationConfig(
            max_shot_duration_sec=12.0,
            default_fps=12,
            output_fps=24,
            max_reroll_attempts=3,
        ),
        audit=AuditConfig(
            identity_threshold=0.70,
            flicker_threshold=0.05,
        ),
        paths=PathsConfig(
            workflows_dir=temp_dir / "workflows",
            output_dir=temp_dir / "output",
            checkpoint_dir=temp_dir / "checkpoints",
        ),
    )


@pytest.fixture
def sample_scene_graph(temp_dir) -> SceneGraph:
    """Create a minimal scene graph for testing."""
    # Create scene graph
    graph = SceneGraph(
        project_id="test_film",
        title="Test Film",
        description="A test film for unit testing",
    )
    
    # Create a scene with 2 shots
    scene = Scene(
        scene_id="scene_01",
        index=0,
        title="Test Scene",
        description="Test scene",
        location=EntityRef.location("kitchen", "Kitchen"),
        characters=[EntityRef.character("alice", "Alice")],
    )
    
    # Shot 1: Alice enters
    shot1 = Shot(
        shot_id="shot_01",
        scene_id="scene_01",
        index=0,
        duration_sec=8.0,
        description="Alice enters the kitchen",
        prompt="A young woman with red hair enters a modern kitchen, medium shot",
        shot_type=ShotType.MEDIUM,
        characters=[EntityRef.character("alice", "Alice")],
        location=EntityRef.location("kitchen", "Kitchen"),
    )
    
    # Shot 2: Alice looks around
    shot2 = Shot(
        shot_id="shot_02",
        scene_id="scene_01",
        index=1,
        duration_sec=6.0,
        description="Alice looks around",
        prompt="The same young woman looks around the kitchen, close-up on face",
        shot_type=ShotType.CLOSE,
        characters=[EntityRef.character("alice", "Alice")],
        location=EntityRef.location("kitchen", "Kitchen"),
    )
    
    scene.add_shot(shot1)
    scene.add_shot(shot2)
    graph.add_scene(scene)
    
    # Save to temp dir
    graph_path = temp_dir / "test_film.json"
    graph.save(graph_path)
    
    return graph


@pytest.fixture
def sample_consistency_dict(temp_dir) -> ConsistencyDict:
    """Create a consistency dict with test characters."""
    bible = ConsistencyDict()
    
    # Create dummy face ref file
    face_ref = temp_dir / "alice_ref.png"
    face_ref.write_bytes(b"fake png data")
    
    bible.add_character(CharacterEntity(
        entity_id="alice",
        name="Alice",
        description="A young woman with red hair",
        lora_path=None,  # No LoRA for this test
        face_refs=[str(face_ref)],
    ))
    
    bible.add_location(LocationEntity(
        entity_id="kitchen",
        name="Kitchen",
        description="A modern kitchen with white cabinets",
    ))
    
    # Save to temp dir
    bible_path = temp_dir / "consistency.json"
    bible.save(bible_path)
    
    return bible


# =============================================================================
# MOCK IMPLEMENTATIONS
# =============================================================================

class MockRenderer(BaseRenderer):
    """Mock renderer for testing without cloud."""
    
    def __init__(
        self,
        fail_on_shot: Optional[List[str]] = None,
        fail_after_attempts: int = 0,
        simulate_timeout: bool = False,
        generation_time_sec: float = 0.1,
    ):
        super().__init__(RendererType.MOCK)
        self.fail_on_shot = fail_on_shot or []
        self.fail_after_attempts = fail_after_attempts
        self.simulate_timeout = simulate_timeout
        self.generation_time_sec = generation_time_sec
        
        self._generate_count: Dict[str, int] = {}
        self._initialized = False
        self.output_dir = Path(tempfile.mkdtemp())
    
    async def initialize(self) -> None:
        self._initialized = True
    
    async def shutdown(self) -> None:
        self._initialized = False
    
    def estimate_cost(self, job: JobSpec) -> float:
        """Mock cost estimate."""
        return 0.01 * job.duration_sec  # $0.01 per second
    
    def estimate_time(self, job: JobSpec) -> float:
        """Mock time estimate."""
        return job.duration_sec * 2  # 2x realtime
    
    async def generate(
        self,
        job: JobSpec,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None
    ) -> RenderResult:
        # Track attempts per job
        job_key = job.prompt[:50]  # Use prompt prefix as key
        self._generate_count[job_key] = self._generate_count.get(job_key, 0) + 1
        attempt = self._generate_count[job_key]
        
        # Simulate timeout
        if self.simulate_timeout:
            await asyncio.sleep(100)  # Will be cancelled
        
        # Simulate generation time
        await asyncio.sleep(self.generation_time_sec)
        
        # Check if we should fail
        should_fail = (
            any(shot_id in job.prompt for shot_id in self.fail_on_shot) or
            (self.fail_after_attempts > 0 and attempt <= self.fail_after_attempts)
        )
        
        if should_fail:
            raise RuntimeError(f"Mock renderer failed on attempt {attempt}")
        
        # Create fake output
        output_path = self.output_dir / f"render_{datetime.now().timestamp()}.mp4"
        output_path.write_bytes(b"fake video data")
        
        # Return properly constructed RenderResult matching real interface
        return RenderResult(
            video_path=output_path,
            frame_count=int(job.duration_sec * 12),  # 12 fps
            fps=12.0,
            duration_sec=job.duration_sec,
            resolution=(1280, 720),
            renderer_type=RendererType.MOCK,
            metadata={"mock": True},
            render_time_sec=self.generation_time_sec,
            cost_estimate=0.01 * job.duration_sec,
        )
    
    async def health_check(self) -> bool:
        return self._initialized


class MockBridgeEngine(BaseBridgeEngine):
    """Mock bridge engine for testing."""
    
    def __init__(
        self,
        fail_on_generate: bool = False,
        output_dir: Optional[Path] = None,
    ):
        super().__init__(output_dir or Path(tempfile.mkdtemp()))
        self.fail_on_generate = fail_on_generate
        self._initialized = False
        self.generate_count = 0
    
    async def initialize(self) -> None:
        self._initialized = True
    
    async def shutdown(self) -> None:
        self._initialized = False
    
    async def generate(
        self,
        spec: BridgeSpec,
        progress_callback: Optional[Callable] = None
    ) -> BridgeResult:
        self.generate_count += 1
        
        if self.fail_on_generate:
            raise BridgeGenerationError("Mock bridge failure")
        
        # Create fake bridge frame
        output_path = self.output_dir / f"bridge_{self.generate_count}.png"
        output_path.write_bytes(b"fake bridge frame")
        
        return BridgeResult(
            frame_path=output_path,
            method=BridgeMethod.IPADAPTER_ONLY,
            generation_time_sec=0.1,
        )
    
    async def extract_pose(self, frame_path: Path):
        return None
    
    async def health_check(self) -> bool:
        return self._initialized


class MockIdentityChecker(BaseIdentityChecker):
    """Mock identity checker for testing."""
    
    def __init__(
        self,
        mock_similarity: float = 0.85,
        fail_on_check: bool = False,
        no_face_detected: bool = False,
    ):
        super().__init__(threshold=0.70)
        self.mock_similarity = mock_similarity
        self.fail_on_check = fail_on_check
        self.no_face_detected = no_face_detected
        self._initialized = False
        self.check_count = 0
    
    async def initialize(self) -> None:
        self._initialized = True
    
    async def shutdown(self) -> None:
        self._initialized = False
    
    async def extract_faces(self, frame_path: Path) -> FrameFaces:
        import numpy as np
        if self.no_face_detected:
            return FrameFaces(frame_path, [])
        
        fake_embedding = np.random.randn(512).astype(np.float32)
        fake_embedding = fake_embedding / np.linalg.norm(fake_embedding)
        
        return FrameFaces(
            frame_path=frame_path,
            faces=[FaceEmbedding(
                embedding=fake_embedding,
                bbox=(100, 100, 300, 400),
                confidence=0.95,
            )],
        )
    
    async def compare(
        self,
        source_frame: Path,
        target_frame: Path,
        character_hint: Optional[str] = None,
    ) -> IdentityComparison:
        self.check_count += 1
        
        if self.fail_on_check:
            raise RuntimeError("Mock identity check failure")
        
        source_faces = await self.extract_faces(source_frame)
        target_faces = await self.extract_faces(target_frame)
        
        if self.no_face_detected:
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_BOTH,
                similarity=None,
                threshold=self.threshold,
                source_faces=source_faces,
                target_faces=target_faces,
            )
        
        passed = self.mock_similarity >= self.threshold
        return IdentityComparison(
            result=IdentityCheckResult.MATCH if passed else IdentityCheckResult.MISMATCH,
            similarity=self.mock_similarity,
            threshold=self.threshold,
            source_faces=source_faces,
            target_faces=target_faces,
        )
    
    async def health_check(self) -> bool:
        return self._initialized


class MockCheckpointManager:
    """Mock checkpoint manager for testing."""
    
    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.completed_shots: List[str] = []
        self.checkpoints: Dict[str, Dict] = {}
    
    def get_completed_shots(self) -> List[str]:
        return self.completed_shots.copy()
    
    def mark_shot_complete(self, shot_id: str, output_path: Path) -> None:
        self.completed_shots.append(shot_id)
        self.checkpoints[shot_id] = {
            "output_path": str(output_path),
            "completed_at": datetime.utcnow().isoformat(),
        }
    
    def clear(self) -> None:
        self.completed_shots.clear()
        self.checkpoints.clear()


# =============================================================================
# HAPPY PATH TESTS
# =============================================================================

class TestHappyPath:
    """Tests for normal, successful operation."""
    
    @pytest.mark.asyncio
    async def test_single_shot_generation(self, temp_dir, mock_config):
        """Test generating a single shot works end-to-end."""
        # Setup: Create minimal scene graph with 1 shot
        graph = SceneGraph(project_id="single_shot", title="Single Shot Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Test shot",
            prompt="A simple test scene",
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        graph.save(temp_dir / "single.json")
        
        # Mock dependencies
        mock_renderer = MockRenderer()
        mock_bridge = MockBridgeEngine()
        mock_identity = MockIdentityChecker()
        mock_checkpoint = MockCheckpointManager(temp_dir / "checkpoints")
        
        # Run orchestrator
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', mock_identity), \
             patch.object(orchestrator, 'checkpoint_manager', mock_checkpoint):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        # Assertions
        assert result.shots_attempted == 1
        assert result.shots_succeeded == 1
        assert result.shots_failed == 0
        assert result.all_succeeded
        assert mock_bridge.generate_count == 0  # First shot = no bridge
    
    @pytest.mark.asyncio
    async def test_two_shots_with_bridge(
        self, temp_dir, sample_scene_graph, sample_consistency_dict, mock_config
    ):
        """Test two shots generates bridge frame between them."""
        mock_renderer = MockRenderer()
        mock_bridge = MockBridgeEngine()
        mock_identity = MockIdentityChecker()
        mock_checkpoint = MockCheckpointManager(temp_dir / "checkpoints")
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', mock_identity), \
             patch.object(orchestrator, 'checkpoint_manager', mock_checkpoint):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = sample_consistency_dict
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_attempted == 2
        assert result.shots_succeeded == 2
        assert mock_bridge.generate_count == 1  # Bridge between shot 1 and 2
    
    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, temp_dir, sample_scene_graph, mock_config):
        """Test resuming skips already-completed shots."""
        mock_renderer = MockRenderer()
        mock_bridge = MockBridgeEngine()
        mock_checkpoint = MockCheckpointManager(temp_dir / "checkpoints")
        
        # Pre-mark shot_01 as complete
        mock_checkpoint.mark_shot_complete("shot_01", temp_dir / "output.mp4")
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', mock_checkpoint):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run(resume=True)
        
        # Should only process shot_02
        assert result.shots_attempted == 1
        assert result.shot_results[0].shot_id == "shot_02"
    
    @pytest.mark.asyncio
    async def test_dry_run_mode(self, temp_dir, sample_scene_graph, mock_config):
        """Test dry run doesn't make real cloud calls."""
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        # Verify dry_run flag is set
        assert orchestrator.dry_run is True


# =============================================================================
# STRESS TESTS
# =============================================================================

class TestStressScenarios:
    """Tests for high-load and edge-of-capacity scenarios."""
    
    @pytest.mark.asyncio
    async def test_many_shots_sequential(self, temp_dir, mock_config):
        """Test processing 20 shots in sequence."""
        # Create scene graph with 20 shots
        graph = SceneGraph(project_id="stress_test", title="Stress Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Stress scene")
        
        for i in range(20):
            shot = Shot(
                shot_id=f"shot_{i:02d}",
                scene_id="s1",
                index=i,
                duration_sec=5.0,
                description=f"Shot {i}",
                prompt=f"Scene {i} action",
            )
            scene.add_shot(shot)
        
        graph.add_scene(scene)
        
        mock_renderer = MockRenderer(generation_time_sec=0.01)  # Fast
        mock_bridge = MockBridgeEngine()
        mock_checkpoint = MockCheckpointManager(temp_dir / "checkpoints")
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', mock_checkpoint):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_attempted == 20
        assert result.shots_succeeded == 20
        assert mock_bridge.generate_count == 19  # 19 bridges for 20 shots
    
    @pytest.mark.asyncio
    async def test_long_prompt_handling(self, temp_dir, mock_config):
        """Test handling of very long prompts."""
        graph = SceneGraph(project_id="long_prompt", title="Long Prompt Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        
        # Create a very long prompt (4000 chars)
        long_prompt = "A detailed scene with " + " and ".join([
            f"element_{i}" for i in range(500)
        ])
        
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Long prompt shot",
            prompt=long_prompt,
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        mock_renderer = MockRenderer()
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_succeeded == 1
    
    @pytest.mark.asyncio
    async def test_many_characters_in_consistency_dict(self, temp_dir, mock_config):
        """Test handling large consistency dictionaries."""
        bible = ConsistencyDict()
        
        # Add 100 characters
        for i in range(100):
            bible.add_character(CharacterEntity(
                entity_id=f"char_{i:03d}",
                name=f"Character {i}",
                description=f"Description for character {i}",
            ))
        
        graph = SceneGraph(project_id="many_chars", title="Many Characters")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Crowd scene")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Crowd",
            prompt="A crowd scene",
            characters=[EntityRef.character(f"char_{i:03d}") for i in range(10)],
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = bible
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_succeeded == 1


# =============================================================================
# NIGHTMARE SCENARIOS - Things that WILL go wrong in production
# =============================================================================

class TestNightmareScenarios:
    """Tests for failure modes and error recovery."""
    
    @pytest.mark.asyncio
    async def test_renderer_fails_then_succeeds(self, temp_dir, mock_config):
        """Test re-roll logic when first attempt fails."""
        graph = SceneGraph(project_id="retry_test", title="Retry Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Test",
            prompt="Retry test shot",
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        # Renderer fails first 2 attempts, succeeds on 3rd
        mock_renderer = MockRenderer(fail_after_attempts=2)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        # Should succeed after retries
        assert result.shots_succeeded == 1
    
    @pytest.mark.asyncio
    async def test_renderer_fails_all_attempts(self, temp_dir, mock_config):
        """Test graceful failure when all re-rolls exhaust."""
        graph = SceneGraph(project_id="fail_test", title="Fail Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Test",
            prompt="Fail test shot",
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        # Renderer always fails (fails more times than max_reroll_attempts)
        mock_renderer = MockRenderer(fail_after_attempts=10)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_failed == 1
        assert result.shots_succeeded == 0
        assert "Failed after" in result.shot_results[0].error
    
    @pytest.mark.asyncio
    async def test_bridge_generation_fails(self, temp_dir, sample_scene_graph, mock_config):
        """Test pipeline continues when bridge frame fails."""
        mock_bridge = MockBridgeEngine(fail_on_generate=True)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        # Should still succeed - bridge failure is non-fatal
        assert result.shots_succeeded == 2
    
    @pytest.mark.asyncio
    async def test_identity_check_fails_triggers_reroll(self, temp_dir, mock_config):
        """Test identity failure triggers re-roll."""
        graph = SceneGraph(project_id="identity_fail", title="Identity Fail")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        
        face_ref = temp_dir / "face.png"
        face_ref.write_bytes(b"fake face")
        
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Test",
            prompt="Identity test",
            characters=[EntityRef.character("alice", "Alice")],
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        bible = ConsistencyDict()
        bible.add_character(CharacterEntity(
            entity_id="alice",
            name="Alice",
            face_refs=[str(face_ref)],
        ))
        
        # Identity checker returns low similarity (below threshold)
        mock_identity = MockIdentityChecker(mock_similarity=0.50)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', mock_identity), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = bible
            orchestrator._initialized = True
            orchestrator.dry_run = False  # Need identity checks to run
            
            result = await orchestrator.run()
        
        # Should fail after max attempts due to identity mismatch
        assert result.shots_failed == 1
        assert mock_identity.check_count >= 1
    
    @pytest.mark.asyncio
    async def test_missing_character_in_consistency_dict(self, temp_dir, mock_config):
        """Test graceful handling of missing character refs."""
        graph = SceneGraph(project_id="missing_char", title="Missing Character")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Test",
            prompt="Test with missing character",
            characters=[EntityRef.character("nonexistent", "Ghost")],
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        # Empty consistency dict - character doesn't exist
        empty_bible = ConsistencyDict()
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = empty_bible
            orchestrator._initialized = True
            
            # Should not crash - degrades gracefully
            result = await orchestrator.run()
        
        assert result.shots_succeeded == 1
    
    @pytest.mark.asyncio
    async def test_empty_scene_graph(self, temp_dir, mock_config):
        """Test handling of empty scene graph."""
        empty_graph = SceneGraph(project_id="empty", title="Empty")
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = empty_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_attempted == 0
        assert result.shots_succeeded == 0
        assert result.shots_failed == 0
    
    @pytest.mark.asyncio
    async def test_partial_success_some_shots_fail(self, temp_dir, mock_config):
        """Test mixed success/failure across shots."""
        graph = SceneGraph(project_id="partial", title="Partial Success")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        
        # 3 shots - middle one will fail
        for i, should_fail in enumerate([False, True, False]):
            shot_id = f"shot_{i:02d}"
            shot = Shot(
                shot_id=shot_id,
                scene_id="s1",
                index=i,
                duration_sec=5.0,
                description=f"Shot {i}",
                prompt=f"FAIL_{shot_id}" if should_fail else f"OK_{shot_id}",
            )
            scene.add_shot(shot)
        
        graph.add_scene(scene)
        
        # Renderer fails on any prompt containing "FAIL_shot_01"
        mock_renderer = MockRenderer(fail_on_shot=["FAIL_shot_01"])
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_attempted == 3
        assert result.shots_succeeded == 2
        assert result.shots_failed == 1
        assert not result.all_succeeded
    
    @pytest.mark.asyncio
    async def test_orchestrator_not_initialized(self, mock_config):
        """Test error when run() called before setup()."""
        orchestrator = ContinuumOrchestrator(config=mock_config)
        
        with pytest.raises(RuntimeError, match="not initialized"):
            await orchestrator.run()
    
    @pytest.mark.asyncio
    async def test_last_frame_state_tracking(self, temp_dir, mock_config):
        """Test _last_frame_path is correctly updated between shots."""
        graph = SceneGraph(project_id="state_test", title="State Test")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        
        for i in range(3):
            shot = Shot(
                shot_id=f"shot_{i:02d}",
                scene_id="s1",
                index=i,
                duration_sec=5.0,
                description=f"Shot {i}",
                prompt=f"Shot {i}",
            )
            scene.add_shot(shot)
        
        graph.add_scene(scene)
        
        mock_renderer = MockRenderer()
        mock_bridge = MockBridgeEngine()
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            # Verify initial state
            assert orchestrator._last_frame_path is None
            
            result = await orchestrator.run()
            
            # After run, _last_frame_path should be set
            assert orchestrator._last_frame_path is not None
        
        assert result.shots_succeeded == 3


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for boundary conditions and unusual inputs."""
    
    @pytest.mark.asyncio
    async def test_shot_with_zero_duration(self, temp_dir, mock_config):
        """Test handling of zero-duration shot."""
        graph = SceneGraph(project_id="zero_dur", title="Zero Duration")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=0.0,  # Edge case!
            description="Zero duration",
            prompt="Instant shot",
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            # Should handle gracefully (might generate minimal output)
            result = await orchestrator.run()
        
        # At minimum, shouldn't crash
        assert result.shots_attempted == 1
    
    @pytest.mark.asyncio
    async def test_generate_specific_shots(self, temp_dir, sample_scene_graph, mock_config):
        """Test filtering to specific shot IDs."""
        mock_renderer = MockRenderer()
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            # Only generate shot_02
            result = await orchestrator.run(shot_ids=["shot_02"])
        
        assert result.shots_attempted == 1
        assert result.shot_results[0].shot_id == "shot_02"
    
    @pytest.mark.asyncio
    async def test_nonexistent_shot_id_filter(self, temp_dir, sample_scene_graph, mock_config):
        """Test filtering with shot ID that doesn't exist."""
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            # Request non-existent shot
            result = await orchestrator.run(shot_ids=["shot_999"])
        
        assert result.shots_attempted == 0
    
    @pytest.mark.asyncio
    async def test_unicode_in_prompts(self, temp_dir, mock_config):
        """Test handling of unicode characters in prompts."""
        graph = SceneGraph(project_id="unicode", title="Unicode Test 日本語")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Test 测试")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Unicode test",
            prompt="A scene with émojis 🎬 and 中文字符 and Ñoño",
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        assert result.shots_succeeded == 1
    
    @pytest.mark.asyncio
    async def test_scene_with_no_characters(self, temp_dir, mock_config):
        """Test shot with no characters (environment only)."""
        graph = SceneGraph(project_id="no_chars", title="No Characters")
        scene = Scene(scene_id="s1", index=0, title="Test", description="Empty room")
        shot = Shot(
            shot_id="shot_01",
            scene_id="s1",
            index=0,
            duration_sec=5.0,
            description="Empty room",
            prompt="An empty kitchen with sunlight streaming through windows",
            characters=[],  # No characters
        )
        scene.add_shot(shot)
        graph.add_scene(scene)
        
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        # Should succeed - identity check skipped for no characters
        assert result.shots_succeeded == 1


# =============================================================================
# CONCURRENCY & ASYNC TESTS
# =============================================================================

class TestConcurrencyAndAsync:
    """Tests for async behavior and potential race conditions."""
    
    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self, temp_dir, mock_config):
        """Test teardown happens on context manager exit."""
        renderer_shutdown_called = False
        bridge_shutdown_called = False
        
        class TrackingRenderer(MockRenderer):
            async def shutdown(self):
                nonlocal renderer_shutdown_called
                renderer_shutdown_called = True
                await super().shutdown()
        
        class TrackingBridge(MockBridgeEngine):
            async def shutdown(self):
                nonlocal bridge_shutdown_called
                bridge_shutdown_called = True
                await super().shutdown()
        
        async with ContinuumOrchestrator(config=mock_config, dry_run=True) as orchestrator:
            orchestrator.renderer = TrackingRenderer()
            orchestrator.bridge_engine = TrackingBridge()
            orchestrator.identity_checker = MockIdentityChecker()
            orchestrator._initialized = True
        
        # After context exit, teardown should have been called
        assert renderer_shutdown_called
        assert bridge_shutdown_called
    
    @pytest.mark.asyncio
    async def test_context_manager_cleanup_on_error(self, temp_dir, mock_config):
        """Test teardown happens even when error occurs."""
        shutdown_called = False
        
        class TrackingRenderer(MockRenderer):
            async def shutdown(self):
                nonlocal shutdown_called
                shutdown_called = True
        
        try:
            async with ContinuumOrchestrator(config=mock_config, dry_run=True) as orchestrator:
                orchestrator.renderer = TrackingRenderer()
                orchestrator.bridge_engine = MockBridgeEngine()
                orchestrator._initialized = True
                raise ValueError("Intentional error")
        except ValueError:
            pass
        
        assert shutdown_called
    
    @pytest.mark.asyncio 
    async def test_multiple_runs_same_orchestrator(self, temp_dir, sample_scene_graph, mock_config):
        """Test running the same orchestrator twice."""
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        mock_checkpoint = MockCheckpointManager(temp_dir)
        
        with patch.object(orchestrator, 'renderer', MockRenderer()), \
             patch.object(orchestrator, 'bridge_engine', MockBridgeEngine()), \
             patch.object(orchestrator, 'identity_checker', MockIdentityChecker()), \
             patch.object(orchestrator, 'checkpoint_manager', mock_checkpoint):
            
            orchestrator.scene_graph = sample_scene_graph
            orchestrator.consistency_dict = ConsistencyDict()
            orchestrator._initialized = True
            
            # First run
            result1 = await orchestrator.run(resume=False)
            assert result1.shots_succeeded == 2
            
            # Reset checkpoint state
            mock_checkpoint.clear()
            orchestrator._last_frame_path = None
            
            # Second run
            result2 = await orchestrator.run(resume=False)
            assert result2.shots_succeeded == 2


# =============================================================================
# RESULT DATACLASS TESTS
# =============================================================================

class TestResultDataclasses:
    """Tests for result dataclass behavior."""
    
    def test_pipeline_result_success_rate(self):
        """Test PipelineResult.success_rate calculation."""
        result = PipelineResult(
            project_id="test",
            shots_attempted=10,
            shots_succeeded=7,
            shots_failed=3,
            total_duration_sec=100.0,
            shot_results=[],
        )
        
        assert result.success_rate == 70.0
        assert not result.all_succeeded
    
    def test_pipeline_result_all_succeeded(self):
        """Test PipelineResult.all_succeeded property."""
        result = PipelineResult(
            project_id="test",
            shots_attempted=5,
            shots_succeeded=5,
            shots_failed=0,
            total_duration_sec=50.0,
            shot_results=[],
        )
        
        assert result.all_succeeded
        assert result.success_rate == 100.0
    
    def test_pipeline_result_zero_shots(self):
        """Test PipelineResult with zero shots."""
        result = PipelineResult(
            project_id="test",
            shots_attempted=0,
            shots_succeeded=0,
            shots_failed=0,
            total_duration_sec=0.0,
            shot_results=[],
        )
        
        assert result.success_rate == 0.0
        assert not result.all_succeeded  # Zero shots != success
    
    def test_shot_result_complete(self):
        """Test ShotResult for completed shot."""
        result = ShotResult(
            shot_id="shot_01",
            status=JobStatus.COMPLETE,
            video_path=Path("/output/video.mp4"),
            identity_score=0.85,
            duration_sec=10.5,
        )
        
        assert result.status == JobStatus.COMPLETE
        assert result.error is None
    
    def test_shot_result_failed(self):
        """Test ShotResult for failed shot."""
        result = ShotResult(
            shot_id="shot_01",
            status=JobStatus.FAILED,
            error="Connection timeout",
            duration_sec=30.0,
        )
        
        assert result.status == JobStatus.FAILED
        assert result.video_path is None


# =============================================================================
# INTEGRATION-STYLE TESTS (Simulating Real Workflow)
# =============================================================================

class TestIntegrationScenarios:
    """Tests simulating realistic production scenarios."""
    
    @pytest.mark.asyncio
    async def test_short_film_workflow(self, temp_dir, mock_config):
        """
        Simulate generating a short film (30 seconds, 5 shots).
        
        This tests the full workflow with realistic structure.
        """
        # Create realistic scene graph
        graph = SceneGraph(
            project_id="short_film",
            title="The Coffee",
            description="A short film about making coffee",
        )
        
        # Scene 1: Morning Kitchen
        scene1 = Scene(
            scene_id="scene_01",
            index=0,
            title="Morning Kitchen",
            description="Morning in the kitchen",
            location=EntityRef.location("kitchen"),
            characters=[EntityRef.character("protagonist")],
        )
        
        shots = [
            ("Wide shot of sunlit kitchen", ShotType.WIDE, 4.0),
            ("Protagonist enters frame", ShotType.MEDIUM, 6.0),
            ("Close-up on coffee maker", ShotType.CLOSE, 3.0),
            ("Protagonist pours coffee", ShotType.MEDIUM, 8.0),
            ("Steam rising from cup", ShotType.EXTREME_CLOSE, 5.0),
        ]
        
        for i, (desc, shot_type, duration) in enumerate(shots):
            shot = Shot(
                shot_id=f"shot_{i+1:02d}",
                scene_id="scene_01",
                index=i,
                duration_sec=duration,
                description=desc,
                prompt=f"{desc}, cinematic lighting, 4K",
                shot_type=shot_type,
                characters=[EntityRef.character("protagonist")] if "Protagonist" in desc else [],
            )
            scene1.add_shot(shot)
        
        graph.add_scene(scene1)
        
        # Create consistency dict
        bible = ConsistencyDict()
        
        face_ref = temp_dir / "protagonist_ref.png"
        face_ref.write_bytes(b"fake face")
        
        bible.add_character(CharacterEntity(
            entity_id="protagonist",
            name="Protagonist",
            description="A person in their 30s, casual clothes",
            face_refs=[str(face_ref)],
        ))
        
        bible.add_location(LocationEntity(
            entity_id="kitchen",
            name="Kitchen",
            description="Modern kitchen with white cabinets, morning light",
        ))
        
        # Run
        orchestrator = ContinuumOrchestrator(config=mock_config, dry_run=True)
        
        mock_renderer = MockRenderer(generation_time_sec=0.05)
        mock_bridge = MockBridgeEngine()
        mock_identity = MockIdentityChecker(mock_similarity=0.82)
        
        with patch.object(orchestrator, 'renderer', mock_renderer), \
             patch.object(orchestrator, 'bridge_engine', mock_bridge), \
             patch.object(orchestrator, 'identity_checker', mock_identity), \
             patch.object(orchestrator, 'checkpoint_manager', MockCheckpointManager(temp_dir)):
            
            orchestrator.scene_graph = graph
            orchestrator.consistency_dict = bible
            orchestrator._initialized = True
            
            result = await orchestrator.run()
        
        # Verify
        assert result.shots_attempted == 5
        assert result.shots_succeeded == 5
        assert mock_bridge.generate_count == 4  # 4 bridges for 5 shots
        assert result.total_duration_sec > 0
        
        # Check individual shots
        for shot_result in result.shot_results:
            assert shot_result.status == JobStatus.COMPLETE
            assert shot_result.video_path is not None


# =============================================================================
# RUN CONFIGURATION
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])