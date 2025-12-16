"""
Tests for src/sonic/mixer.py

These tests verify the AudioMixer correctly:
- Places audio at specified timestamps
- Applies volume levels per layer type
- Handles empty mixes (generates silence)
- Works with mix_from_plan API
- Handles missing files gracefully

Requirements:
- FFmpeg must be installed for full tests
- Tests create temporary WAV files for mixing
"""

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from typing import List, Tuple
import pytest

from src.sonic.types import (
    AudioGenerationStatus,
    DialogueLine,
    FoleyEvent,
    FoleyCategory,
    AmbienceSpec,
    AmbienceType,
    ShotAudioPlan,
    SynthesizedAmbience,
    SynthesizedDialogue,
    SynthesizedFoley,
)
from src.sonic.mixer import (
    AudioMixer,
    AudioPlacement,
    MixSpec,
    check_ffmpeg_available,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mixer(temp_dir):
    """Create an AudioMixer instance."""
    return AudioMixer(output_dir=temp_dir / "mixed")


def create_silent_wav(path: Path, duration_sec: float, sample_rate: int = 44100) -> Path:
    """Create a silent WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(sample_rate * duration_sec)
    
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(2)  # Stereo
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        silent_frame = struct.pack('<hh', 0, 0)
        wav.writeframes(silent_frame * num_frames)
    
    return path


def create_tone_wav(path: Path, duration_sec: float, frequency: int = 440, sample_rate: int = 44100) -> Path:
    """Create a WAV file with a tone (for audible testing)."""
    import math
    
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(sample_rate * duration_sec)
    
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        
        for i in range(num_frames):
            t = i / sample_rate
            value = int(16000 * math.sin(2 * math.pi * frequency * t))
            wav.writeframes(struct.pack('<hh', value, value))
    
    return path


# =============================================================================
# UNIT TESTS - MixSpec
# =============================================================================

class TestMixSpec:
    """Tests for MixSpec dataclass."""
    
    def test_empty_spec(self):
        """Empty spec should report is_empty=True."""
        spec = MixSpec(shot_id="test", duration_sec=10.0)
        assert spec.is_empty is True
        assert spec.layer_count == 0
    
    def test_spec_with_placements(self, temp_dir):
        """Spec with placements should not be empty."""
        spec = MixSpec(
            shot_id="test",
            duration_sec=10.0,
            placements=[
                AudioPlacement(
                    audio_path=temp_dir / "test.wav",
                    start_time_sec=0.0,
                    volume_db=-6.0,
                )
            ]
        )
        assert spec.is_empty is False
        assert spec.layer_count == 1


class TestAudioPlacement:
    """Tests for AudioPlacement dataclass."""
    
    def test_string_path_conversion(self):
        """String paths should be converted to Path objects."""
        placement = AudioPlacement(
            audio_path="/tmp/test.wav",
            start_time_sec=1.5,
        )
        assert isinstance(placement.audio_path, Path)
        assert placement.audio_path == Path("/tmp/test.wav")
    
    def test_default_values(self, temp_dir):
        """Default values should be sensible."""
        placement = AudioPlacement(audio_path=temp_dir / "test.wav")
        assert placement.start_time_sec == 0.0
        assert placement.volume_db == 0.0
        assert placement.duration_sec is None
        assert placement.label == ""


# =============================================================================
# INTEGRATION TESTS - AudioMixer
# =============================================================================

@pytest.mark.asyncio
class TestAudioMixer:
    """Integration tests for AudioMixer (require FFmpeg)."""
    
    async def test_ffmpeg_available(self):
        """Check if FFmpeg is available for testing."""
        available = await check_ffmpeg_available()
        if not available:
            pytest.skip("FFmpeg not available")
    
    async def test_mix_single_dialogue(self, mixer, temp_dir):
        """Mix a single dialogue track."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create test audio
        dialogue_path = create_silent_wav(temp_dir / "dialogue.wav", 2.0)
        
        # Create synthesized dialogue
        synth = SynthesizedDialogue(
            line_id="line_001",
            audio_path=dialogue_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello world",
            start_time_sec=1.0,
        )
        
        # Mix
        result = await mixer.mix_shot(
            shot_id="shot_001",
            duration_sec=5.0,
            dialogue=[(synth, line)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 1
        assert result.shot_id == "shot_001"
    
    async def test_mix_all_layers(self, mixer, temp_dir):
        """Mix dialogue, ambience, and foley together."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create test audio files
        dialogue_path = create_silent_wav(temp_dir / "dialogue.wav", 2.0)
        ambience_path = create_silent_wav(temp_dir / "ambience.wav", 10.0)
        foley_path = create_silent_wav(temp_dir / "foley.wav", 0.5)
        
        # Create synthesized audio
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
        
        # Mix
        result = await mixer.mix_shot(
            shot_id="shot_001",
            duration_sec=10.0,
            dialogue=[(synth_dialogue, line)],
            ambience=synth_ambience,
            foley=[(synth_foley, 5.0)],  # Foley at 5 seconds
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 3  # dialogue + ambience + foley
    
    async def test_mix_empty_generates_silence(self, mixer, temp_dir):
        """Empty mix should generate silence, not fail."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        result = await mixer.mix_shot(
            shot_id="shot_empty",
            duration_sec=5.0,
            dialogue=[],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.output_path.exists()
        assert result.component_count == 0
        assert "silence" in result.warnings[0].lower()
    
    async def test_mix_skips_failed_audio(self, mixer, temp_dir):
        """Failed synthesized audio should be skipped, not crash."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create one good and one failed dialogue
        good_path = create_silent_wav(temp_dir / "good.wav", 2.0)
        
        synth_good = SynthesizedDialogue(
            line_id="line_good",
            audio_path=good_path,
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line_good = DialogueLine(
            line_id="line_good",
            character_id="alice",
            text="Good line",
            start_time_sec=0.0,
        )
        
        synth_failed = SynthesizedDialogue(
            line_id="line_failed",
            audio_path=None,  # No path
            status=AudioGenerationStatus.FAILED,
            error="API error",
        )
        line_failed = DialogueLine(
            line_id="line_failed",
            character_id="bob",
            text="Failed line",
            start_time_sec=3.0,
        )
        
        # Mix should succeed with just the good audio
        result = await mixer.mix_shot(
            shot_id="shot_partial",
            duration_sec=5.0,
            dialogue=[(synth_good, line_good), (synth_failed, line_failed)],
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 1  # Only the good one
    
    async def test_mix_from_plan(self, mixer, temp_dir):
        """Test the mix_from_plan orchestrator API."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create test audio
        dialogue_path = create_silent_wav(temp_dir / "dialogue.wav", 2.0)
        foley_path = create_silent_wav(temp_dir / "foley.wav", 0.5)
        
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
                    description="door closes",
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
        
        # Mix
        result = await mixer.mix_from_plan(
            plan=plan,
            dialogue_results=dialogue_results,
            ambience_result=None,
            foley_results=foley_results,
        )
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 2
        assert "scene_001_shot_001" in str(result.output_path)
    
    async def test_probe_audio(self, mixer, temp_dir):
        """Test audio probing utility."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Create a test file
        test_path = create_silent_wav(temp_dir / "probe_test.wav", 3.5)
        
        info = await mixer.probe_audio(test_path)
        
        assert info["duration"] == pytest.approx(3.5, rel=0.1)
        assert info["sample_rate"] == 44100
        assert info["channels"] == 2


# =============================================================================
# VOLUME LEVEL TESTS
# =============================================================================

@pytest.mark.asyncio
class TestVolumeLevels:
    """Tests for volume level handling."""
    
    async def test_default_levels(self, mixer):
        """Verify default volume levels match architecture spec."""
        assert mixer.dialogue_db == 0.0    # Reference level
        assert mixer.foley_db == -6.0      # Below dialogue
        assert mixer.ambience_db == -12.0  # Bed track level
    
    async def test_custom_levels(self, temp_dir):
        """Custom volume levels should be applied."""
        custom_mixer = AudioMixer(
            output_dir=temp_dir / "custom",
            dialogue_db=-3.0,
            foley_db=-9.0,
            ambience_db=-18.0,
        )
        
        assert custom_mixer.dialogue_db == -3.0
        assert custom_mixer.foley_db == -9.0
        assert custom_mixer.ambience_db == -18.0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

@pytest.mark.asyncio
class TestErrorHandling:
    """Tests for error handling."""
    
    async def test_missing_file_fails_gracefully(self, mixer, temp_dir):
        """Missing audio file should result in failed mix."""
        if not await check_ffmpeg_available():
            pytest.skip("FFmpeg not available")
        
        # Reference a file that doesn't exist
        synth = SynthesizedDialogue(
            line_id="line_missing",
            audio_path=temp_dir / "does_not_exist.wav",
            actual_duration_sec=2.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        line = DialogueLine(
            line_id="line_missing",
            character_id="alice",
            text="Missing",
            start_time_sec=0.0,
        )
        
        result = await mixer.mix_shot(
            shot_id="shot_missing",
            duration_sec=5.0,
            dialogue=[(synth, line)],
        )
        
        # Should fail with clear error
        assert result.status == AudioGenerationStatus.FAILED
        assert result.error is not None
        assert "not found" in result.error.lower() or "no such file" in result.error.lower()


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

@pytest.mark.asyncio
class TestHelperFunctions:
    """Tests for helper functions."""
    
    async def test_check_ffmpeg_returns_bool(self):
        """check_ffmpeg_available should return a boolean."""
        result = await check_ffmpeg_available()
        assert isinstance(result, bool)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])