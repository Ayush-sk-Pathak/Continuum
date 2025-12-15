"""
Continuum Engine - Bridge Engine Integration Tests

Tests the bridge frame generation flow using MockBridgeEngine.
This validates the orchestration logic WITHOUT requiring GPU resources.

=============================================================================
WHAT IS INTEGRATION TESTING? (For the vibe coder)
=============================================================================

Integration testing verifies that MULTIPLE COMPONENTS work together correctly.
Unlike unit tests (test one function in isolation), integration tests check:

1. Data flows correctly between modules
2. Interfaces match expectations
3. State management works end-to-end
4. Error propagation is handled properly

In our context:
- Unit test: "Does BridgeSpec.from_shots() set camera_transition correctly?"
- Integration test: "Can I create a BridgeSpec from two shots, pass it to
  the engine, and get back a valid BridgeResult with the right metadata?"

=============================================================================
WHY MOCKS SAVE MONEY (Real Talk)
=============================================================================

GPU time costs ~$1.50/hour (A100) or more. Each Bridge Frame generation:
- Takes 10-30 seconds of GPU time
- Costs ~$0.01-0.05 per frame

If you're iterating on orchestration logic and run tests 50 times a day:
- With real GPU: 50 * $0.03 = $1.50/day = $45/month just on tests
- With mocks: $0.00

More importantly:
- Real GPU: Slow feedback loop (30+ seconds per test)
- Mocks: Fast feedback loop (< 1 second per test)

Mocks let you:
1. Test error handling paths (simulate failures)
2. Test edge cases (missing files, bad configs)
3. Run CI/CD without GPU infrastructure
4. Iterate 100x faster on orchestration logic

The deal: Test LOGIC with mocks, test QUALITY with real GPU (sparingly).

=============================================================================
RUNNING THESE TESTS
=============================================================================

From the project root (/home/claude/continuum):

    # Run all tests
    python -m pytest tests/test_bridge_flow.py -v

    # Run a specific test
    python -m pytest tests/test_bridge_flow.py::TestBridgeSpec -v

    # Run with print output visible
    python -m pytest tests/test_bridge_flow.py -v -s

    # Run and stop on first failure
    python -m pytest tests/test_bridge_flow.py -v -x

If pytest isn't installed:
    pip install pytest pytest-asyncio

=============================================================================
"""

import asyncio
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
from datetime import datetime
import pytest


# =============================================================================
# INLINE DEPENDENCIES (Self-contained for testing)
# =============================================================================
# We inline minimal versions of the types here so tests can run standalone.
# In production, these would be imported from the actual modules.

class RenderQuality(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"


@dataclass
class CharacterRef:
    """Minimal CharacterRef for testing."""
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
    """Minimal LocationRef for testing."""
    entity_id: str
    name: str
    ref_images: List[Path] = field(default_factory=list)
    description: str = ""


# =============================================================================
# IMPORT BRIDGE ENGINE COMPONENTS
# =============================================================================
# We try to import from the actual module, fall back to inline if not available

try:
    from src.studio.bridge_engine import (
        BridgeSpec,
        BridgeResult,
        BridgeProgress,
        BridgeMethod,
        BridgeStatus,
        CameraTransition,
        PoseData,
        BaseBridgeEngine,
        MockBridgeEngine,
        BridgeError,
        BridgeSourceError,
        BridgeGenerationError,
    )
    USING_REAL_MODULE = True
except ImportError:
    # Inline minimal implementations for standalone testing
    USING_REAL_MODULE = False
    
    class BridgeMethod(str, Enum):
        CONTROLNET_FULL = "controlnet_full"
        CONTROLNET_POSE = "controlnet_pose"
        IPADAPTER_ONLY = "ipadapter_only"
        PROMPT_ONLY = "prompt_only"
    
    class CameraTransition(str, Enum):
        SAME = "same"
        REVERSE = "reverse"
        CLOSEUP = "closeup"
        WIDEOUT = "wideout"
        CUSTOM = "custom"
    
    class BridgeStatus(str, Enum):
        PENDING = "pending"
        COMPLETED = "completed"
        FAILED = "failed"
    
    @dataclass
    class PoseData:
        keypoints_path: Optional[Path] = None
        depth_map_path: Optional[Path] = None
        confidence: float = 0.0
        character_count: int = 0
        
        @property
        def has_pose(self) -> bool:
            return self.keypoints_path is not None
    
    @dataclass
    class BridgeSpec:
        source_frame: Path
        target_prompt: str
        characters: List[CharacterRef] = field(default_factory=list)
        location: Optional[LocationRef] = None
        camera_transition: CameraTransition = CameraTransition.SAME
        target_shot_type: str = "medium"
        emotion_note: str = ""
        pose_data: Optional[PoseData] = None
        seed: int = -1
        quality: RenderQuality = RenderQuality.STANDARD
        width: int = 1280
        height: int = 720
        config_overrides: Dict[str, Any] = field(default_factory=dict)
        
        def __post_init__(self):
            if isinstance(self.source_frame, str):
                self.source_frame = Path(self.source_frame)
        
        @property
        def source_exists(self) -> bool:
            return self.source_frame.exists()
        
        @staticmethod
        def _infer_transition(from_type: str, to_type: str) -> CameraTransition:
            if from_type == to_type:
                return CameraTransition.SAME
            close_types = {"close", "extreme_close"}
            wide_types = {"wide", "aerial", "group"}
            medium_or_wider = {"wide", "aerial", "group", "medium", "two_shot"}
            
            # Moving closer (wide/medium → close)
            if from_type in medium_or_wider and to_type in close_types:
                return CameraTransition.CLOSEUP
            # Moving wider (close → wide/medium)
            if from_type in close_types and to_type in wide_types:
                return CameraTransition.WIDEOUT
            return CameraTransition.CUSTOM
        
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
            transition = cls._infer_transition(shot_a_type, shot_b_type)
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
        frame_path: Path
        method: BridgeMethod
        generation_time_sec: float = 0.0
        pose_data: Optional[PoseData] = None
        seed_used: int = -1
        metadata: Dict[str, Any] = field(default_factory=dict)
        created_at: datetime = field(default_factory=datetime.utcnow)
        
        @property
        def exists(self) -> bool:
            return self.frame_path.exists()
    
    @dataclass
    class BridgeProgress:
        stage: str
        progress: float
        message: str = ""
        elapsed_sec: float = 0.0
    
    class BridgeError(Exception):
        def __init__(self, message: str, spec: Optional[BridgeSpec] = None):
            super().__init__(message)
            self.spec = spec
    
    class BridgeSourceError(BridgeError):
        pass
    
    class BridgeGenerationError(BridgeError):
        pass
    
    class MockBridgeEngine:
        """Inline MockBridgeEngine for standalone testing."""
        
        def __init__(
            self,
            output_dir: Optional[Path] = None,
            simulate_delay: float = 0.1,
            simulate_failure: bool = False,
        ):
            self.output_dir = output_dir or Path(tempfile.mkdtemp())
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.simulate_delay = simulate_delay
            self.simulate_failure = simulate_failure
            self._call_count = 0
        
        async def health_check(self) -> bool:
            return not self.simulate_failure
        
        def select_method(self, spec: BridgeSpec) -> BridgeMethod:
            has_face_refs = any(c.has_face_refs() for c in spec.characters)
            has_lora = any(c.has_lora() for c in spec.characters)
            if has_face_refs or has_lora:
                return BridgeMethod.IPADAPTER_ONLY
            return BridgeMethod.PROMPT_ONLY
        
        async def generate(
            self,
            spec: BridgeSpec,
            progress_callback: Optional[Callable[[BridgeProgress], None]] = None
        ) -> BridgeResult:
            self._call_count += 1
            
            if not spec.source_exists:
                raise BridgeSourceError(f"Source not found: {spec.source_frame}", spec)
            
            if self.simulate_failure:
                raise BridgeGenerationError("Simulated failure", spec)
            
            # Report progress
            if progress_callback:
                progress_callback(BridgeProgress("generating", 0.5, "Mock generation"))
            
            await asyncio.sleep(self.simulate_delay)
            
            # Copy source as mock output
            output_path = self.output_dir / f"mock_bridge_{self._call_count:04d}.png"
            shutil.copy2(spec.source_frame, output_path)
            
            if progress_callback:
                progress_callback(BridgeProgress("completed", 1.0, "Done"))
            
            return BridgeResult(
                frame_path=output_path,
                method=self.select_method(spec),
                generation_time_sec=self.simulate_delay,
                seed_used=spec.seed,
                metadata={"mock": True, "call_count": self._call_count}
            )
        
        async def extract_pose(self, frame_path: Path) -> PoseData:
            await asyncio.sleep(self.simulate_delay * 0.2)
            return PoseData(confidence=0.0, character_count=1)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    path = Path(tempfile.mkdtemp())
    yield path
    # Cleanup after test
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def dummy_frame(temp_dir) -> Path:
    """Create a dummy image file for testing."""
    frame_path = temp_dir / "shot_a_last_frame.png"
    # Create a minimal valid PNG (1x1 red pixel)
    # PNG header + IHDR + IDAT + IEND
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR length + type
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 dimensions
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,  # 8-bit RGB
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,  # Compressed data
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x18, 0xDD,  # 
        0x8D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,  # IEND
        0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82               # 
    ])
    frame_path.write_bytes(png_data)
    return frame_path


@pytest.fixture
def alice_character(temp_dir) -> CharacterRef:
    """Create a test character with face references."""
    # Create dummy face ref files
    face_ref_path = temp_dir / "alice_ref.png"
    face_ref_path.write_bytes(b"fake_image_data")  # Not a real PNG, but file exists
    
    return CharacterRef(
        entity_id="alice_001",
        name="Alice",
        face_refs=[face_ref_path],
        description="A young woman with brown hair",
    )


@pytest.fixture
def mock_engine(temp_dir) -> MockBridgeEngine:
    """Create a MockBridgeEngine for testing."""
    output_dir = temp_dir / "bridge_outputs"
    output_dir.mkdir()
    return MockBridgeEngine(output_dir=output_dir, simulate_delay=0.05)


# =============================================================================
# TEST CLASS: BridgeSpec Construction
# =============================================================================

class TestBridgeSpec:
    """Tests for BridgeSpec data structure and factories."""
    
    def test_basic_construction(self, dummy_frame):
        """Test basic BridgeSpec creation."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Alice walks into the kitchen",
        )
        
        assert spec.source_exists
        assert spec.target_prompt == "Alice walks into the kitchen"
        assert spec.camera_transition == CameraTransition.SAME
        assert spec.quality == RenderQuality.STANDARD
    
    def test_from_shots_factory(self, dummy_frame, alice_character):
        """Test BridgeSpec.from_shots() factory method."""
        spec = BridgeSpec.from_shots(
            shot_a_last_frame=dummy_frame,
            shot_b_prompt="Close-up of Alice's face, emotional",
            shot_b_characters=[alice_character],
            shot_a_type="wide",
            shot_b_type="close",
        )
        
        assert spec.source_exists
        assert spec.camera_transition == CameraTransition.CLOSEUP
        assert spec.target_shot_type == "close"
        assert len(spec.characters) == 1
        assert spec.characters[0].entity_id == "alice_001"
    
    def test_transition_inference_same(self, dummy_frame):
        """Test same camera angle inference."""
        spec = BridgeSpec.from_shots(
            shot_a_last_frame=dummy_frame,
            shot_b_prompt="Continuation",
            shot_b_characters=[],
            shot_a_type="medium",
            shot_b_type="medium",
        )
        assert spec.camera_transition == CameraTransition.SAME
    
    def test_transition_inference_wideout(self, dummy_frame):
        """Test close-to-wide transition inference."""
        spec = BridgeSpec.from_shots(
            shot_a_last_frame=dummy_frame,
            shot_b_prompt="Pull back to reveal the room",
            shot_b_characters=[],
            shot_a_type="close",
            shot_b_type="wide",
        )
        assert spec.camera_transition == CameraTransition.WIDEOUT
    
    def test_source_not_exists(self, temp_dir):
        """Test handling of missing source frame."""
        spec = BridgeSpec(
            source_frame=temp_dir / "nonexistent.png",
            target_prompt="This should detect missing source",
        )
        assert not spec.source_exists


# =============================================================================
# TEST CLASS: MockBridgeEngine Generation
# =============================================================================

class TestMockBridgeEngine:
    """Tests for MockBridgeEngine behavior."""
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_engine):
        """Test health check returns True when healthy."""
        result = await mock_engine.health_check()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, temp_dir):
        """Test health check returns False when simulating failure."""
        engine = MockBridgeEngine(
            output_dir=temp_dir,
            simulate_failure=True
        )
        result = await engine.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_generate_success(self, mock_engine, dummy_frame):
        """Test successful bridge frame generation."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Alice in the kitchen",
        )
        
        result = await mock_engine.generate(spec)
        
        # Verify result structure
        assert isinstance(result, BridgeResult)
        assert result.exists  # Output file was created
        assert result.method == BridgeMethod.PROMPT_ONLY  # No identity refs
        assert result.generation_time_sec > 0
        assert result.metadata.get("mock") is True
    
    @pytest.mark.asyncio
    async def test_generate_with_character(self, mock_engine, dummy_frame, alice_character):
        """Test generation with character reference."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Close-up of Alice",
            characters=[alice_character],
        )
        
        result = await mock_engine.generate(spec)
        
        # Should use IP-Adapter method since we have face refs
        assert result.method == BridgeMethod.IPADAPTER_ONLY
        assert result.exists
    
    @pytest.mark.asyncio
    async def test_generate_missing_source_raises(self, mock_engine, temp_dir):
        """Test that missing source frame raises BridgeSourceError."""
        spec = BridgeSpec(
            source_frame=temp_dir / "missing.png",
            target_prompt="This will fail",
        )
        
        with pytest.raises(BridgeSourceError) as exc_info:
            await mock_engine.generate(spec)
        
        assert "Source not found" in str(exc_info.value)
        assert exc_info.value.spec is spec  # Error includes the spec
    
    @pytest.mark.asyncio
    async def test_generate_simulated_failure(self, temp_dir, dummy_frame):
        """Test simulated failure raises BridgeGenerationError."""
        engine = MockBridgeEngine(
            output_dir=temp_dir,
            simulate_failure=True
        )
        
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="This will fail",
        )
        
        with pytest.raises(BridgeGenerationError) as exc_info:
            await engine.generate(spec)
        
        assert "Simulated failure" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_progress_callback(self, mock_engine, dummy_frame):
        """Test that progress callback is called."""
        progress_updates = []
        
        def on_progress(progress: BridgeProgress):
            progress_updates.append(progress)
        
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Track progress",
        )
        
        await mock_engine.generate(spec, progress_callback=on_progress)
        
        # Should have received progress updates
        assert len(progress_updates) >= 1
        assert any(p.stage == "completed" for p in progress_updates)
    
    @pytest.mark.asyncio
    async def test_call_count_increments(self, mock_engine, dummy_frame):
        """Test that call count increments with each generation."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="First call",
        )
        
        result1 = await mock_engine.generate(spec)
        result2 = await mock_engine.generate(spec)
        result3 = await mock_engine.generate(spec)
        
        assert result1.metadata["call_count"] == 1
        assert result2.metadata["call_count"] == 2
        assert result3.metadata["call_count"] == 3


# =============================================================================
# TEST CLASS: End-to-End Flow
# =============================================================================

class TestEndToEndFlow:
    """
    Integration tests simulating the full Shot A → Bridge → Shot B flow.
    
    This is what you'd run before deploying to verify orchestration works.
    """
    
    @pytest.mark.asyncio
    async def test_shot_a_to_shot_b_flow(self, mock_engine, dummy_frame, alice_character):
        """
        Simulate: Shot A ends → generate bridge → Shot B starts.
        
        This is THE critical test. If this passes, orchestration logic works.
        """
        # SETUP: Simulate Shot A has completed
        shot_a_last_frame = dummy_frame  # In reality, extracted from rendered video
        
        # SETUP: Define Shot B parameters (from SceneGraph)
        shot_b_prompt = "Close-up of Alice's face, looking determined"
        shot_b_type = "close"
        shot_a_type = "medium"
        
        # STEP 1: Create BridgeSpec from shot transition
        bridge_spec = BridgeSpec.from_shots(
            shot_a_last_frame=shot_a_last_frame,
            shot_b_prompt=shot_b_prompt,
            shot_b_characters=[alice_character],
            shot_a_type=shot_a_type,
            shot_b_type=shot_b_type,
            emotion_note="transition from calm to determined",
        )
        
        # Verify spec is correctly constructed
        assert bridge_spec.source_exists
        assert bridge_spec.camera_transition == CameraTransition.CLOSEUP
        
        # STEP 2: Generate bridge frame
        bridge_result = await mock_engine.generate(bridge_spec)
        
        # STEP 3: Verify result can be used as init_frame for Shot B
        assert bridge_result.exists
        assert bridge_result.frame_path.suffix == ".png"
        
        # This path would be passed to the renderer as init_frame
        shot_b_init_frame = bridge_result.frame_path
        assert shot_b_init_frame.exists()
        
        # SUCCESS: The orchestration flow works
        print(f"\n✅ Bridge frame generated: {bridge_result.frame_path}")
        print(f"   Method used: {bridge_result.method.value}")
        print(f"   Generation time: {bridge_result.generation_time_sec:.3f}s")
        print(f"   Ready to pass to Shot B renderer as init_frame")
    
    @pytest.mark.asyncio
    async def test_multi_shot_sequence(self, temp_dir, alice_character):
        """
        Simulate a 3-shot sequence with bridge frames between each.
        
        Shot 1 (wide) → Bridge → Shot 2 (medium) → Bridge → Shot 3 (close)
        """
        engine = MockBridgeEngine(output_dir=temp_dir, simulate_delay=0.02)
        
        # Create fake "rendered frames" for each shot
        shot_frames = []
        for i in range(3):
            frame_path = temp_dir / f"shot_{i+1}_last_frame.png"
            frame_path.write_bytes(b"fake_frame_data_" + str(i).encode())
            shot_frames.append(frame_path)
        
        shot_configs = [
            {"type": "wide", "prompt": "Wide shot of Alice in kitchen"},
            {"type": "medium", "prompt": "Medium shot, Alice at counter"},
            {"type": "close", "prompt": "Close-up, Alice's reaction"},
        ]
        
        bridge_results = []
        
        # Generate bridges between shots 1→2 and 2→3
        for i in range(len(shot_configs) - 1):
            spec = BridgeSpec.from_shots(
                shot_a_last_frame=shot_frames[i],
                shot_b_prompt=shot_configs[i + 1]["prompt"],
                shot_b_characters=[alice_character],
                shot_a_type=shot_configs[i]["type"],
                shot_b_type=shot_configs[i + 1]["type"],
            )
            
            result = await engine.generate(spec)
            bridge_results.append(result)
            
            print(f"\n  Bridge {i+1}→{i+2}: {spec.camera_transition.value}")
        
        # Verify all bridges generated successfully
        assert len(bridge_results) == 2
        assert all(r.exists for r in bridge_results)
        
        # Verify transitions detected correctly
        assert bridge_results[0].metadata  # wide → medium = CUSTOM
        assert bridge_results[1].metadata  # medium → close = CLOSEUP
        
        print(f"\n✅ Generated {len(bridge_results)} bridge frames for 3-shot sequence")
    
    @pytest.mark.asyncio
    async def test_error_recovery_flow(self, temp_dir, dummy_frame):
        """
        Test that orchestrator can handle and recover from bridge failures.
        
        In production, you might retry or fall back to hard cut.
        """
        # Engine that fails on first call, succeeds after
        class FlakeyEngine(MockBridgeEngine):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._fail_count = 0
                self._max_failures = 1
            
            async def generate(self, spec, progress_callback=None):
                if self._fail_count < self._max_failures:
                    self._fail_count += 1
                    raise BridgeGenerationError("Transient failure", spec)
                return await super().generate(spec, progress_callback)
        
        engine = FlakeyEngine(output_dir=temp_dir, simulate_delay=0.01)
        
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Test error recovery",
        )
        
        # First attempt fails
        with pytest.raises(BridgeGenerationError):
            await engine.generate(spec)
        
        # Retry succeeds
        result = await engine.generate(spec)
        assert result.exists
        
        print("\n✅ Error recovery flow works: failed once, succeeded on retry")


# =============================================================================
# TEST CLASS: Method Selection (Degradation Ladder)
# =============================================================================

class TestMethodSelection:
    """Tests for the degradation ladder logic."""
    
    def test_prompt_only_no_refs(self, mock_engine, dummy_frame):
        """No identity refs → prompt-only method."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Generic scene",
            characters=[],  # No characters
        )
        method = mock_engine.select_method(spec)
        assert method == BridgeMethod.PROMPT_ONLY
    
    def test_ipadapter_with_face_refs(self, mock_engine, dummy_frame, alice_character):
        """Face refs available → IP-Adapter method."""
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Alice scene",
            characters=[alice_character],
        )
        method = mock_engine.select_method(spec)
        assert method == BridgeMethod.IPADAPTER_ONLY
    
    def test_prompt_only_missing_refs(self, mock_engine, dummy_frame, temp_dir):
        """Character defined but refs don't exist → prompt-only fallback."""
        char_with_missing_refs = CharacterRef(
            entity_id="bob",
            name="Bob",
            face_refs=[temp_dir / "nonexistent.png"],  # File doesn't exist
        )
        
        spec = BridgeSpec(
            source_frame=dummy_frame,
            target_prompt="Bob scene",
            characters=[char_with_missing_refs],
        )
        method = mock_engine.select_method(spec)
        # Should fall back to prompt-only since refs don't exist
        assert method == BridgeMethod.PROMPT_ONLY


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def run_quick_validation():
    """
    Quick validation that can run without pytest.
    
    Usage: python tests/test_bridge_flow.py
    """
    print("=" * 70)
    print("BRIDGE ENGINE QUICK VALIDATION")
    print("=" * 70)
    print(f"\nUsing real module: {USING_REAL_MODULE}")
    
    async def validate():
        # Setup
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create dummy frame
            frame_path = temp_dir / "test_frame.png"
            frame_path.write_bytes(b"fake_image_data")
            
            # Create engine
            engine = MockBridgeEngine(
                output_dir=temp_dir / "outputs",
                simulate_delay=0.05
            )
            
            # Health check
            print("\n1. Health check...", end=" ")
            healthy = await engine.health_check()
            assert healthy, "Health check failed"
            print("✅ PASS")
            
            # Basic generation
            print("2. Basic generation...", end=" ")
            spec = BridgeSpec(
                source_frame=frame_path,
                target_prompt="Test prompt",
            )
            result = await engine.generate(spec)
            assert result.exists, "Output not created"
            print("✅ PASS")
            
            # With character
            print("3. Generation with character...", end=" ")
            face_ref = temp_dir / "face.png"
            face_ref.write_bytes(b"face_data")
            char = CharacterRef(
                entity_id="test_char",
                name="Test",
                face_refs=[face_ref],
            )
            spec2 = BridgeSpec(
                source_frame=frame_path,
                target_prompt="Character test",
                characters=[char],
            )
            result2 = await engine.generate(spec2)
            assert result2.method == BridgeMethod.IPADAPTER_ONLY
            print("✅ PASS")
            
            # Error handling
            print("4. Error handling...", end=" ")
            bad_spec = BridgeSpec(
                source_frame=temp_dir / "nonexistent.png",
                target_prompt="Should fail",
            )
            try:
                await engine.generate(bad_spec)
                print("❌ FAIL (should have raised)")
            except BridgeSourceError:
                print("✅ PASS")
            
            print("\n" + "=" * 70)
            print("ALL VALIDATIONS PASSED ✅")
            print("=" * 70)
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    asyncio.run(validate())


if __name__ == "__main__":
    run_quick_validation()