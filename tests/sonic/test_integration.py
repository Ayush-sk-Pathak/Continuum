"""
Comprehensive Integration Tests for Sonic Module

Tests the complete audio pipeline:
- Types and data structures
- TTS Engine (with mock implementation)
- Ambience Engine (mock)
- Foley Engine (mock)
- Mixer (real FFmpeg)
- Lip Sync (passthrough)
- End-to-end pipeline

Run with: pytest tests/sonic/test_integration.py -v

Requirements:
- FFmpeg must be installed for mixer tests
- No API keys needed (all engines use mocks)
"""

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import pytest

# =============================================================================
# IMPORTS - All Sonic Module Components
# =============================================================================

from src.sonic.types import (
    # Enums
    TTSProvider,
    VoiceEmotion,
    AmbienceType,
    FoleyCategory,
    AudioGenerationStatus,
    
    # Voice & Character
    VoiceConfig,
    
    # Dialogue
    DialogueLine,
    SynthesizedDialogue,
    
    # Ambience
    AmbienceSpec,
    SynthesizedAmbience,
    
    # Foley
    FoleyEvent,
    SynthesizedFoley,
    
    # Manifest
    ShotAudioPlan,
    SonicManifest,
    
    # Mix
    MixResult,
)

from src.sonic.ambience import (
    AmbienceProvider,
    MockAmbienceEngine,
)

from src.sonic.foley import (
    FoleyProvider,
    MockFoleyEngine,
    FoleyMatch,
)

from src.sonic.mixer import (
    AudioMixer,
    MixSpec,
    check_ffmpeg_available,
)

from src.sonic.lip_sync import (
    LipSyncProvider,
    LipSyncStatus,
    DialogueSegment,
    LipSyncSpec,
    LipSyncResult,
    PassthroughLipSyncEngine,
    LipSyncFactory,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_rate():
    """Standard sample rate for test audio."""
    return 44100


def create_test_wav(path: Path, duration_sec: float, sample_rate: int = 44100, silent: bool = True) -> Path:
    """Create a test WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(sample_rate * duration_sec)
    
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        
        if silent:
            silent_frame = struct.pack('<hh', 0, 0)
            wav.writeframes(silent_frame * num_frames)
        else:
            # Generate a simple tone
            import math
            for i in range(num_frames):
                t = i / sample_rate
                value = int(16000 * math.sin(2 * math.pi * 440 * t))
                wav.writeframes(struct.pack('<hh', value, value))
    
    return path


def create_test_video(path: Path, duration_sec: float = 5.0, fps: int = 12) -> Path:
    """Create a minimal test video file using FFmpeg."""
    import subprocess
    
    path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:size=320x240:rate={fps}:duration={duration_sec}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"FFmpeg video creation failed: {result.stderr}")
    
    return path


# =============================================================================
# MOCK TTS ENGINE (For Testing)
# =============================================================================

class MockTTSEngine:
    """
    Mock TTS engine for testing without API keys.
    Generates silent WAV files with correct duration.
    """
    
    provider = TTSProvider.ELEVENLABS  # Pretend to be ElevenLabs
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def synthesize(
        self,
        line: DialogueLine,
        config: VoiceConfig,
    ) -> SynthesizedDialogue:
        """Generate a mock audio file."""
        output_path = self.output_dir / f"{line.line_id}.wav"
        
        # Create silent WAV with estimated duration
        duration = line.estimated_duration_sec
        create_test_wav(output_path, duration)
        
        return SynthesizedDialogue(
            line_id=line.line_id,
            audio_path=output_path,
            actual_duration_sec=duration,
            sample_rate=44100,
            status=AudioGenerationStatus.COMPLETE,
        )
    
    async def health_check(self) -> bool:
        return True


# =============================================================================
# TYPE TESTS
# =============================================================================

class TestTypes:
    """Test data structures and type contracts."""
    
    def test_dialogue_line_creation(self):
        """DialogueLine should have sensible defaults."""
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello, world!",
            start_time_sec=0.0,
        )
        
        assert line.line_id == "line_001"
        assert line.character_id == "alice"
        assert line.emotion is None  # default is None (uses character default)
        assert line.estimated_duration_sec > 0  # Should calculate from text
    
    def test_dialogue_line_duration_estimation(self):
        """Duration estimation should scale with text length."""
        short = DialogueLine(
            line_id="short",
            character_id="alice",
            text="Hi",
            start_time_sec=0.0,
        )
        
        long = DialogueLine(
            line_id="long",
            character_id="alice",
            text="This is a much longer sentence that should take more time to speak.",
            start_time_sec=0.0,
        )
        
        assert long.estimated_duration_sec > short.estimated_duration_sec
    
    def test_voice_config_defaults(self):
        """VoiceConfig should have provider-appropriate defaults."""
        config = VoiceConfig(
            character_id="alice",
            voice_id="voice_123",
        )
        
        assert config.provider == TTSProvider.ELEVENLABS  # default
        assert config.speaking_rate == 1.0
        assert config.pitch_shift == 0.0
    
    def test_voice_config_clamping(self):
        """VoiceConfig should clamp values to valid ranges."""
        config = VoiceConfig(
            character_id="alice",
            voice_id="voice_123",
            speaking_rate=10.0,  # Way too high
            pitch_shift=-50.0,   # Way too low
        )
        
        assert config.speaking_rate == 2.0  # Clamped to max
        assert config.pitch_shift == -12.0  # Clamped to min
    
    def test_sonic_manifest_validation_missing_voice(self):
        """SonicManifest.validate() should catch missing voice configs."""
        manifest = SonicManifest(
            manifest_id="test_001",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="line_001",
                            character_id="alice",
                            text="Hello",
                            start_time_sec=0.0,
                        )
                    ],
                ),
            ],
            voice_configs={},  # Missing alice's config!
        )
        
        errors = manifest.validate()
        assert len(errors) > 0
        assert "alice" in errors[0].lower()
    
    def test_sonic_manifest_validation_passes(self):
        """Valid SonicManifest should have no validation errors."""
        manifest = SonicManifest(
            manifest_id="test_002",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="line_001",
                            character_id="alice",
                            text="Hello",
                            start_time_sec=0.0,
                        )
                    ],
                ),
            ],
            voice_configs={
                "alice": VoiceConfig(
                    character_id="alice",
                    voice_id="v_alice",
                )
            },
        )
        
        errors = manifest.validate()
        assert len(errors) == 0
    
    def test_sonic_manifest_total_duration(self):
        """SonicManifest should aggregate duration from all shots."""
        manifest = SonicManifest(
            manifest_id="manifest_001",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=5.0,
                ),
                ShotAudioPlan(
                    shot_id="shot_002",
                    scene_id="scene_001",
                    duration_sec=8.0,
                ),
                ShotAudioPlan(
                    shot_id="shot_003",
                    scene_id="scene_002",
                    duration_sec=3.0,
                ),
            ],
        )
        
        assert manifest.total_duration_sec == 16.0
        assert len(manifest.shot_plans) == 3
    
    def test_shot_audio_plan_properties(self):
        """ShotAudioPlan should have correct property values."""
        plan_with_dialogue = ShotAudioPlan(
            shot_id="shot_001",
            scene_id="scene_001",
            duration_sec=10.0,
            dialogue_lines=[
                DialogueLine(
                    line_id="line_001",
                    character_id="alice",
                    text="Hello",
                    start_time_sec=0.0,
                )
            ],
            foley_events=[
                FoleyEvent(
                    event_id="foley_001",
                    category=FoleyCategory.DOOR,
                    description="door",
                    trigger_time_sec=1.0,
                )
            ],
        )
        
        plan_empty = ShotAudioPlan(
            shot_id="shot_002",
            scene_id="scene_001",
            duration_sec=5.0,
        )
        
        assert plan_with_dialogue.has_dialogue is True
        assert plan_with_dialogue.has_foley is True
        assert plan_empty.has_dialogue is False
        assert plan_empty.has_foley is False
    
    def test_foley_event_categories(self):
        """FoleyEvent should support all defined categories."""
        categories = [
            FoleyCategory.FOOTSTEPS,
            FoleyCategory.DOOR,
            FoleyCategory.IMPACT,
            FoleyCategory.OBJECT,
            FoleyCategory.CLOTH,
            FoleyCategory.LIQUID,
            FoleyCategory.ELECTRONIC,
            FoleyCategory.VEHICLE,
            FoleyCategory.NATURE,
            FoleyCategory.CUSTOM,
        ]
        
        for cat in categories:
            event = FoleyEvent(
                event_id=f"event_{cat.name}",
                category=cat,
                description=f"Test {cat.name} sound",
                trigger_time_sec=1.0,
            )
            assert event.category == cat
    
    def test_synthesized_dialogue_failed_factory(self):
        """SynthesizedDialogue.failed() should create failed result."""
        result = SynthesizedDialogue.failed("line_001", "API timeout")
        
        assert result.line_id == "line_001"
        assert result.status == AudioGenerationStatus.FAILED
        assert result.error == "API timeout"
        assert result.audio_path is None


# =============================================================================
# TTS ENGINE TESTS (Using Mock)
# =============================================================================

@pytest.mark.asyncio
class TestTTSEngine:
    """Test TTS engine abstraction using mock."""
    
    async def test_mock_tts_synthesis(self, temp_dir):
        """Mock TTS should generate valid audio files."""
        engine = MockTTSEngine(output_dir=temp_dir / "tts")
        
        line = DialogueLine(
            line_id="test_line",
            character_id="alice",
            text="Hello, this is a test.",
            start_time_sec=0.0,
        )
        
        config = VoiceConfig(
            character_id="alice",
            voice_id="mock_voice",
        )
        
        result = await engine.synthesize(line, config)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path is not None
        assert result.audio_path.exists()
        assert result.actual_duration_sec > 0
    
    async def test_mock_tts_health_check(self, temp_dir):
        """Mock TTS should always be healthy."""
        engine = MockTTSEngine(output_dir=temp_dir / "tts")
        
        healthy = await engine.health_check()
        assert healthy is True
    
    async def test_mock_tts_multiple_lines(self, temp_dir):
        """Mock TTS should handle multiple lines."""
        engine = MockTTSEngine(output_dir=temp_dir / "tts")
        config = VoiceConfig(character_id="alice", voice_id="mock")
        
        lines = [
            DialogueLine(
                line_id=f"line_{i}",
                character_id="alice",
                text=f"This is line number {i}.",
                start_time_sec=float(i * 2),
            )
            for i in range(5)
        ]
        
        results = []
        for line in lines:
            result = await engine.synthesize(line, config)
            results.append(result)
        
        assert len(results) == 5
        assert all(r.status == AudioGenerationStatus.COMPLETE for r in results)
        assert len(set(r.audio_path for r in results)) == 5  # All unique paths


# =============================================================================
# AMBIENCE ENGINE TESTS
# =============================================================================

@pytest.mark.asyncio
class TestAmbienceEngine:
    """Test ambience engine abstraction."""
    
    async def test_mock_ambience_generation(self, temp_dir):
        """Mock ambience should generate valid audio files."""
        engine = MockAmbienceEngine(output_dir=temp_dir / "ambience")
        
        spec = AmbienceSpec(
            ambience_id="amb_001",
            type=AmbienceType.INTERIOR_QUIET,
            description="Quiet room with light air conditioning hum",
            duration_sec=10.0,
            scene_id="scene_001",
        )
        
        result = await engine.generate(spec)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path is not None
        assert result.audio_path.exists()
        assert result.actual_duration_sec == 10.0
    
    async def test_ambience_types(self, temp_dir):
        """Should support all ambience types."""
        engine = MockAmbienceEngine(output_dir=temp_dir / "ambience")
        
        types_to_test = [
            AmbienceType.SILENCE,
            AmbienceType.INTERIOR_QUIET,
            AmbienceType.INTERIOR_BUSY,
            AmbienceType.EXTERIOR_URBAN,
            AmbienceType.EXTERIOR_NATURE,
            AmbienceType.EXTERIOR_WEATHER,
            AmbienceType.CROWD,
            AmbienceType.INDUSTRIAL,
        ]
        
        for i, amb_type in enumerate(types_to_test):
            spec = AmbienceSpec(
                ambience_id=f"amb_{i}",
                type=amb_type,
                description=f"Test {amb_type.name}",
                duration_sec=2.0,
            )
            
            result = await engine.generate(spec)
            assert result.status == AudioGenerationStatus.COMPLETE
    
    async def test_mock_ambience_health_check(self, temp_dir):
        """Mock ambience should always be healthy."""
        engine = MockAmbienceEngine(output_dir=temp_dir / "ambience")
        
        healthy = await engine.health_check()
        assert healthy is True


# =============================================================================
# FOLEY ENGINE TESTS
# =============================================================================

@pytest.mark.asyncio
class TestFoleyEngine:
    """Test foley engine abstraction."""
    
    async def test_mock_foley_retrieval(self, temp_dir):
        """Mock foley should return valid audio files."""
        engine = MockFoleyEngine(output_dir=temp_dir / "foley")
        
        event = FoleyEvent(
            event_id="foley_001",
            category=FoleyCategory.DOOR,
            description="Door slamming shut",
            trigger_time_sec=2.5,
            duration_sec=0.5,
        )
        
        result = await engine.retrieve(event)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path is not None
        assert result.audio_path.exists()
    
    async def test_mock_foley_search(self, temp_dir):
        """Mock foley should return search results."""
        engine = MockFoleyEngine(output_dir=temp_dir / "foley")
        
        results = await engine.search("footsteps on wood", max_results=3)
        
        assert len(results) == 3
        assert all(isinstance(r, FoleyMatch) for r in results)
        assert all(r.score > 0 for r in results)
    
    async def test_foley_categories(self, temp_dir):
        """Should support all foley categories."""
        engine = MockFoleyEngine(output_dir=temp_dir / "foley")
        
        for i, category in enumerate(FoleyCategory):
            event = FoleyEvent(
                event_id=f"foley_{i}",
                category=category,
                description=f"Test {category.name}",
                trigger_time_sec=float(i),
                duration_sec=0.5,
            )
            
            result = await engine.retrieve(event)
            assert result.status == AudioGenerationStatus.COMPLETE
    
    async def test_mock_foley_health_check(self, temp_dir):
        """Mock foley should always be healthy."""
        engine = MockFoleyEngine(output_dir=temp_dir / "foley")
        
        healthy = await engine.health_check()
        assert healthy is True


# =============================================================================
# MIXER TESTS
# =============================================================================

@pytest.mark.asyncio
class TestMixer:
    """Test audio mixer functionality."""
    
    async def test_ffmpeg_available(self):
        """Check if FFmpeg is available for mixer tests."""
        available = await check_ffmpeg_available()
        if not available:
            pytest.skip("FFmpeg not available")
    
    async def test_mix_single_dialogue(self, temp_dir):
        """Mix a single dialogue track."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create test audio file
        dialogue_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        
        synth_dialogue = SynthesizedDialogue(
            line_id="line_001",
            audio_path=dialogue_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello",
            start_time_sec=1.0,
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_001",
            duration_sec=5.0,
            dialogue=[(synth_dialogue, line)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 1
    
    async def test_mix_dialogue_with_ambience(self, temp_dir):
        """Mix dialogue and ambience together."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create test audio files
        dialogue_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        ambience_path = create_test_wav(temp_dir / "ambience.wav", 10.0)
        
        synth_dialogue = SynthesizedDialogue(
            line_id="line_001",
            audio_path=dialogue_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello",
            start_time_sec=1.0,
        )
        
        synth_ambience = SynthesizedAmbience(
            ambience_id="amb_001",
            audio_path=ambience_path,
            actual_duration_sec=10.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_001",
            duration_sec=10.0,
            dialogue=[(synth_dialogue, line)],
            ambience=synth_ambience,
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 2
    
    async def test_mix_all_layers(self, temp_dir):
        """Mix dialogue, ambience, and foley together."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create test audio files
        dialogue_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        ambience_path = create_test_wav(temp_dir / "ambience.wav", 10.0)
        foley_path = create_test_wav(temp_dir / "foley.wav", 0.5)
        
        synth_dialogue = SynthesizedDialogue(
            line_id="line_001",
            audio_path=dialogue_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello",
            start_time_sec=2.0,
        )
        
        synth_ambience = SynthesizedAmbience(
            ambience_id="amb_001",
            audio_path=ambience_path,
            actual_duration_sec=10.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        
        synth_foley = SynthesizedFoley(
            event_id="foley_001",
            audio_path=foley_path,
            actual_duration_sec=0.5,
            status=AudioGenerationStatus.COMPLETE,
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_001",
            duration_sec=10.0,
            dialogue=[(synth_dialogue, line)],
            ambience=synth_ambience,
            foley=[(synth_foley, 5.0)],  # Foley at 5 seconds
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 3
    
    async def test_mix_empty_generates_silence(self, temp_dir):
        """Empty mix should generate silent audio."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        result = await mixer.mix_shot(
            shot_id="shot_empty",
            duration_sec=5.0,
            dialogue=[],
            ambience=None,
            foley=[],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 0
    
    async def test_mix_from_plan(self, temp_dir):
        """Test mixing using ShotAudioPlan."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create test files
        dialogue_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        foley_path = create_test_wav(temp_dir / "foley.wav", 0.5)
        
        # Create plan
        plan = ShotAudioPlan(
            shot_id="shot_001",
            scene_id="scene_001",
            duration_sec=8.0,
            dialogue_lines=[
                DialogueLine(
                    line_id="line_001",
                    character_id="alice",
                    text="Hello",
                    start_time_sec=1.0,
                ),
            ],
            foley_events=[
                FoleyEvent(
                    event_id="foley_001",
                    category=FoleyCategory.DOOR,
                    description="door",
                    trigger_time_sec=4.0,
                ),
            ],
        )
        
        # Create result dicts
        dialogue_results = {
            "line_001": SynthesizedDialogue(
                line_id="line_001",
                audio_path=dialogue_path,
                actual_duration_sec=2.0,
                status=AudioGenerationStatus.COMPLETE,
            )
        }
        
        foley_results = {
            "foley_001": SynthesizedFoley(
                event_id="foley_001",
                audio_path=foley_path,
                actual_duration_sec=0.5,
                status=AudioGenerationStatus.COMPLETE,
            )
        }
        
        result = await mixer.mix_from_plan(
            plan=plan,
            dialogue_results=dialogue_results,
            ambience_result=None,
            foley_results=foley_results,
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 2


# =============================================================================
# LIP SYNC TESTS
# =============================================================================

@pytest.mark.asyncio
class TestLipSync:
    """Test lip sync engine abstraction."""
    
    async def test_dialogue_segment_creation(self, temp_dir):
        """DialogueSegment should calculate duration correctly."""
        audio_path = create_test_wav(temp_dir / "dialogue.wav", 2.5)
        
        segment = DialogueSegment(
            audio_path=audio_path,
            start_time_sec=1.0,
            end_time_sec=3.5,
            character_id="alice",
            line_id="line_001",
        )
        
        assert segment.duration_sec == 2.5
        assert segment.audio_path.exists()
    
    async def test_dialogue_segment_from_synthesized(self, temp_dir):
        """DialogueSegment should be creatable from TTS output."""
        audio_path = create_test_wav(temp_dir / "dialogue.wav", 2.5)
        
        synth = SynthesizedDialogue(
            line_id="line_001",
            audio_path=audio_path,
            actual_duration_sec=2.5,
            status=AudioGenerationStatus.COMPLETE,
        )
        
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello, world!",
            start_time_sec=1.0,
        )
        
        segment = DialogueSegment.from_synthesized(synth, line)
        
        assert segment.line_id == "line_001"
        assert segment.character_id == "alice"
        assert segment.start_time_sec == 1.0
        assert segment.end_time_sec == 3.5  # 1.0 + 2.5
    
    async def test_lip_sync_spec_no_dialogue(self, temp_dir):
        """LipSyncSpec should detect when there's no dialogue."""
        video_path = temp_dir / "video.mp4"
        
        spec = LipSyncSpec(
            input_video=video_path,
            output_video=temp_dir / "output.mp4",
            shot_id="shot_001",
            dialogue_segments=[],
        )
        
        assert spec.has_dialogue is False
        assert spec.total_dialogue_duration == 0.0
    
    async def test_lip_sync_spec_with_dialogue(self, temp_dir):
        """LipSyncSpec should calculate total dialogue duration."""
        video_path = temp_dir / "video.mp4"
        audio_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        
        spec = LipSyncSpec(
            input_video=video_path,
            output_video=temp_dir / "output.mp4",
            shot_id="shot_001",
            dialogue_segments=[
                DialogueSegment(
                    audio_path=audio_path,
                    start_time_sec=1.0,
                    end_time_sec=3.0,
                    character_id="alice",
                    line_id="line_001",
                ),
                DialogueSegment(
                    audio_path=audio_path,
                    start_time_sec=5.0,
                    end_time_sec=7.0,
                    character_id="alice",
                    line_id="line_002",
                ),
            ],
        )
        
        assert spec.has_dialogue is True
        assert spec.total_dialogue_duration == 4.0
    
    async def test_passthrough_lip_sync_no_dialogue(self, temp_dir):
        """Passthrough engine should just copy video when no dialogue."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        video_path = create_test_video(temp_dir / "input.mp4", duration_sec=3.0)
        output_path = temp_dir / "output.mp4"
        
        engine = PassthroughLipSyncEngine(output_dir=temp_dir / "lipsync")
        
        spec = LipSyncSpec(
            input_video=video_path,
            output_video=output_path,
            shot_id="shot_001",
            dialogue_segments=[],
        )
        
        result = await engine.sync(spec)
        
        assert result.success is True
        assert result.status == LipSyncStatus.SKIPPED
        assert result.output_path.exists()
    
    async def test_passthrough_with_dialogue(self, temp_dir):
        """Passthrough should still work with dialogue (just copy)."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        video_path = create_test_video(temp_dir / "input.mp4", duration_sec=5.0)
        audio_path = create_test_wav(temp_dir / "dialogue.wav", 2.0)
        output_path = temp_dir / "output.mp4"
        
        engine = PassthroughLipSyncEngine(output_dir=temp_dir / "lipsync")
        
        spec = LipSyncSpec(
            input_video=video_path,
            output_video=output_path,
            shot_id="shot_001",
            dialogue_segments=[
                DialogueSegment(
                    audio_path=audio_path,
                    start_time_sec=1.0,
                    end_time_sec=3.0,
                    character_id="alice",
                    line_id="line_001",
                ),
            ],
        )
        
        result = await engine.sync(spec)
        
        assert result.success is True
        assert result.output_path.exists()
    
    async def test_lip_sync_factory_fallback(self, temp_dir):
        """Factory should fall back to passthrough when no providers available."""
        factory = LipSyncFactory(
            comfy_host=None,
            replicate_token=None,
            output_dir=temp_dir / "lipsync",
        )
        
        engine = await factory.get_engine()
        assert engine.provider == LipSyncProvider.PASSTHROUGH
    
    async def test_lip_sync_health_check(self, temp_dir):
        """Passthrough should always be healthy."""
        engine = PassthroughLipSyncEngine(output_dir=temp_dir / "lipsync")
        
        healthy = await engine.health_check()
        assert healthy is True


# =============================================================================
# END-TO-END INTEGRATION TESTS
# =============================================================================

@pytest.mark.asyncio
class TestEndToEndPipeline:
    """
    End-to-end integration tests simulating the full sonic pipeline.
    """
    
    async def test_full_audio_pipeline(self, temp_dir):
        """Test complete audio generation and mixing pipeline."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # 1. Create a SonicManifest (what Director would produce)
        manifest = SonicManifest(
            manifest_id="manifest_001",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="line_001",
                            character_id="alice",
                            text="Hello, welcome to our story.",
                            start_time_sec=1.0,
                        ),
                        DialogueLine(
                            line_id="line_002",
                            character_id="alice",
                            text="This is going to be amazing.",
                            start_time_sec=5.0,
                        ),
                    ],
                    foley_events=[
                        FoleyEvent(
                            event_id="foley_001",
                            category=FoleyCategory.DOOR,
                            description="Door opening",
                            trigger_time_sec=0.5,
                            duration_sec=0.5,
                        ),
                    ],
                    ambience=AmbienceSpec(
                        ambience_id="amb_001",
                        type=AmbienceType.INTERIOR_QUIET,
                        description="Quiet room",
                        duration_sec=10.0,
                        scene_id="scene_001",
                    ),
                ),
            ],
            voice_configs={
                "alice": VoiceConfig(
                    character_id="alice",
                    voice_id="mock_alice",
                ),
            },
        )
        
        # 2. Validate manifest
        errors = manifest.validate()
        assert len(errors) == 0, f"Manifest validation failed: {errors}"
        
        # 3. Generate TTS for all dialogue (using mock)
        tts_engine = MockTTSEngine(output_dir=temp_dir / "tts")
        
        dialogue_results: Dict[str, SynthesizedDialogue] = {}
        for plan in manifest.shot_plans:
            for line in plan.dialogue_lines:
                config = manifest.voice_configs[line.character_id]
                result = await tts_engine.synthesize(line, config)
                assert result.status == AudioGenerationStatus.COMPLETE
                dialogue_results[line.line_id] = result
        
        assert len(dialogue_results) == 2
        
        # 4. Generate ambience
        ambience_engine = MockAmbienceEngine(output_dir=temp_dir / "ambience")
        
        ambience_results: Dict[str, SynthesizedAmbience] = {}
        for plan in manifest.shot_plans:
            if plan.ambience:
                result = await ambience_engine.generate(plan.ambience)
                assert result.status == AudioGenerationStatus.COMPLETE
                ambience_results[plan.ambience.ambience_id] = result
        
        assert len(ambience_results) == 1
        
        # 5. Generate foley
        foley_engine = MockFoleyEngine(output_dir=temp_dir / "foley")
        
        foley_results: Dict[str, SynthesizedFoley] = {}
        for plan in manifest.shot_plans:
            for event in plan.foley_events:
                result = await foley_engine.retrieve(event)
                assert result.status == AudioGenerationStatus.COMPLETE
                foley_results[event.event_id] = result
        
        assert len(foley_results) == 1
        
        # 6. Mix all audio for the shot
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        for plan in manifest.shot_plans:
            result = await mixer.mix_from_plan(
                plan=plan,
                dialogue_results={
                    k: v for k, v in dialogue_results.items()
                    if k in [line.line_id for line in plan.dialogue_lines]
                },
                ambience_result=ambience_results.get(plan.ambience.ambience_id) if plan.ambience else None,
                foley_results={
                    k: v for k, v in foley_results.items()
                    if k in [event.event_id for event in plan.foley_events]
                },
            )
            
            assert result.status == AudioGenerationStatus.COMPLETE
            assert result.output_path.exists()
            assert result.component_count == 4  # 2 dialogue + 1 ambience + 1 foley
    
    async def test_multi_shot_pipeline(self, temp_dir):
        """Test pipeline with multiple shots."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create manifest with 4 shots
        manifest = SonicManifest(
            manifest_id="manifest_002",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id=f"shot_{i:03d}",
                    scene_id="scene_001",
                    duration_sec=5.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id=f"line_{i:03d}",
                            character_id="alice",
                            text=f"This is line number {i}.",
                            start_time_sec=1.0,
                        ),
                    ] if i % 2 == 0 else [],  # Only even shots have dialogue
                )
                for i in range(4)
            ],
            voice_configs={
                "alice": VoiceConfig(
                    character_id="alice",
                    voice_id="mock_alice",
                ),
            },
        )
        
        # Generate TTS only for shots with dialogue
        tts_engine = MockTTSEngine(output_dir=temp_dir / "tts")
        
        dialogue_results: Dict[str, SynthesizedDialogue] = {}
        for plan in manifest.shot_plans:
            for line in plan.dialogue_lines:
                config = manifest.voice_configs[line.character_id]
                result = await tts_engine.synthesize(line, config)
                dialogue_results[line.line_id] = result
        
        # Mix each shot
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        mix_results: Dict[str, MixResult] = {}
        
        for plan in manifest.shot_plans:
            result = await mixer.mix_from_plan(
                plan=plan,
                dialogue_results={
                    k: v for k, v in dialogue_results.items()
                    if k in [line.line_id for line in plan.dialogue_lines]
                },
                ambience_result=None,
                foley_results={},
            )
            mix_results[plan.shot_id] = result
        
        # Verify all shots were processed
        assert len(mix_results) == 4
        
        for i in range(4):
            shot_id = f"shot_{i:03d}"
            assert shot_id in mix_results
            assert mix_results[shot_id].status == AudioGenerationStatus.COMPLETE
            
            # Even shots have dialogue, odd shots are silent
            if i % 2 == 0:
                assert mix_results[shot_id].component_count == 1
            else:
                assert mix_results[shot_id].component_count == 0
    
    async def test_pipeline_handles_failed_synthesis(self, temp_dir):
        """Pipeline should handle individual synthesis failures gracefully."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create one good dialogue and one failed
        good_path = create_test_wav(temp_dir / "good.wav", 2.0)
        
        synth_good = SynthesizedDialogue(
            line_id="line_good",
            audio_path=good_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line_good = DialogueLine(
            line_id="line_good",
            character_id="alice",
            text="Good",
            start_time_sec=0.0,
        )
        
        synth_failed = SynthesizedDialogue(
            line_id="line_failed",
            audio_path=None,
            status=AudioGenerationStatus.FAILED,
            error="API error",
        )
        line_failed = DialogueLine(
            line_id="line_failed",
            character_id="bob",
            text="Failed",
            start_time_sec=3.0,
        )
        
        # Mix should succeed with partial results
        result = await mixer.mix_shot(
            shot_id="shot_partial",
            duration_sec=5.0,
            dialogue=[(synth_good, line_good), (synth_failed, line_failed)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 1  # Only good component


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Test edge cases and error handling."""
    
    async def test_empty_manifest(self):
        """Empty manifest should be valid."""
        manifest = SonicManifest(
            manifest_id="empty_001",
            project_id="proj_001",
            shot_plans=[],
            voice_configs={},
        )
        
        assert manifest.total_duration_sec == 0.0
        assert manifest.total_dialogue_lines == 0
        errors = manifest.validate()
        assert len(errors) == 0
    
    async def test_very_short_audio(self, temp_dir):
        """Very short audio segments should work."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create very short audio (0.1 seconds)
        short_path = create_test_wav(temp_dir / "short.wav", 0.1)
        
        synth = SynthesizedDialogue(
            line_id="short",
            audio_path=short_path,
            actual_duration_sec=0.1,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="short",
            character_id="alice",
            text="Hi",
            start_time_sec=0.0,
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_short",
            duration_sec=1.0,
            dialogue=[(synth, line)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
    
    async def test_overlapping_dialogue(self, temp_dir):
        """Overlapping dialogue should be mixed together."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        mixer = AudioMixer(output_dir=temp_dir / "mixed")
        
        # Create audio files
        path1 = create_test_wav(temp_dir / "line1.wav", 3.0)
        path2 = create_test_wav(temp_dir / "line2.wav", 3.0)
        
        synth1 = SynthesizedDialogue(
            line_id="line1",
            audio_path=path1,
            actual_duration_sec=3.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line1 = DialogueLine(
            line_id="line1",
            character_id="alice",
            text="First line that takes a while",
            start_time_sec=0.0,
        )
        
        synth2 = SynthesizedDialogue(
            line_id="line2",
            audio_path=path2,
            actual_duration_sec=3.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line2 = DialogueLine(
            line_id="line2",
            character_id="bob",
            text="Second line that overlaps",
            start_time_sec=1.5,  # Overlaps with first line!
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_overlap",
            duration_sec=5.0,
            dialogue=[(synth1, line1), (synth2, line2)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 2
    
    async def test_unicode_text_in_dialogue(self, temp_dir):
        """Unicode text should be handled correctly."""
        line = DialogueLine(
            line_id="unicode",
            character_id="alice",
            text="こんにちは世界！🎬 Café résumé naïve",
            start_time_sec=0.0,
        )
        
        # Should not crash and should estimate duration
        assert line.estimated_duration_sec > 0
        
        # Mock TTS should handle it
        tts_engine = MockTTSEngine(output_dir=temp_dir / "tts")
        config = VoiceConfig(character_id="alice", voice_id="mock")
        
        result = await tts_engine.synthesize(line, config)
        assert result.status == AudioGenerationStatus.COMPLETE
    
    async def test_manifest_overlap_detection(self):
        """Manifest should detect potential dialogue overlaps."""
        manifest = SonicManifest(
            manifest_id="overlap_test",
            project_id="proj_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="line_001",
                            character_id="alice",
                            text="This is a long sentence that will take time to say.",
                            start_time_sec=0.0,  # Starts at 0, ~4 seconds
                        ),
                        DialogueLine(
                            line_id="line_002",
                            character_id="bob",
                            text="Interrupting!",
                            start_time_sec=1.0,  # Starts during line_001
                        ),
                    ],
                ),
            ],
            voice_configs={
                "alice": VoiceConfig(character_id="alice", voice_id="v_alice"),
                "bob": VoiceConfig(character_id="bob", voice_id="v_bob"),
            },
        )
        
        errors = manifest.validate()
        # Should warn about potential overlap
        assert any("overlap" in e.lower() for e in errors)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])