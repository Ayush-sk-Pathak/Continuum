"""
Tests for Sonic Module Types and Data Structures

Tests cover:
- Enum completeness and values
- Dataclass initialization and defaults
- Validation methods
- Edge cases and boundary conditions
- Serialization/deserialization (future-proofing)
"""

import pytest
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Import all types from the sonic module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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


# =============================================================================
# ENUM TESTS
# =============================================================================

class TestEnums:
    """Test all enum types for completeness and expected values."""
    
    def test_tts_provider_has_expected_values(self):
        """TTSProvider should have all expected providers."""
        providers = list(TTSProvider)
        assert TTSProvider.ELEVENLABS in providers
        assert TTSProvider.OPENAI in providers
        assert TTSProvider.LOCAL in providers
        assert len(providers) == 3
    
    def test_voice_emotion_has_all_emotions(self):
        """VoiceEmotion should cover the emotion spectrum."""
        emotions = list(VoiceEmotion)
        expected = [
            VoiceEmotion.NEUTRAL,
            VoiceEmotion.HAPPY,
            VoiceEmotion.SAD,
            VoiceEmotion.ANGRY,
            VoiceEmotion.FEARFUL,
            VoiceEmotion.SURPRISED,
            VoiceEmotion.WHISPER,
            VoiceEmotion.SHOUTING,
        ]
        for emotion in expected:
            assert emotion in emotions
        assert len(emotions) == 8
    
    def test_ambience_type_covers_environments(self):
        """AmbienceType should cover common environments."""
        types = list(AmbienceType)
        assert AmbienceType.SILENCE in types
        assert AmbienceType.INTERIOR_QUIET in types
        assert AmbienceType.EXTERIOR_URBAN in types
        assert AmbienceType.EXTERIOR_NATURE in types
        assert len(types) == 8
    
    def test_foley_category_covers_sound_types(self):
        """FoleyCategory should cover common sound effect types."""
        categories = list(FoleyCategory)
        assert FoleyCategory.FOOTSTEPS in categories
        assert FoleyCategory.DOOR in categories
        assert FoleyCategory.IMPACT in categories
        assert FoleyCategory.CUSTOM in categories
        assert len(categories) == 10
    
    def test_audio_generation_status_lifecycle(self):
        """AudioGenerationStatus should cover the full lifecycle."""
        statuses = list(AudioGenerationStatus)
        assert AudioGenerationStatus.PENDING in statuses
        assert AudioGenerationStatus.GENERATING in statuses
        assert AudioGenerationStatus.COMPLETE in statuses
        assert AudioGenerationStatus.FAILED in statuses
        assert AudioGenerationStatus.SKIPPED in statuses


# =============================================================================
# VOICE CONFIG TESTS
# =============================================================================

class TestVoiceConfig:
    """Test VoiceConfig dataclass."""
    
    def test_default_values(self):
        """VoiceConfig should have sensible defaults."""
        config = VoiceConfig(character_id="alice")
        assert config.character_id == "alice"
        assert config.provider == TTSProvider.ELEVENLABS
        assert config.voice_id == ""
        assert config.speaking_rate == 1.0
        assert config.pitch_shift == 0.0
        assert config.default_emotion == VoiceEmotion.NEUTRAL
        assert config.custom_params == {}
    
    def test_speaking_rate_clamping(self):
        """Speaking rate should be clamped to valid range."""
        # Too low
        config = VoiceConfig(character_id="test", speaking_rate=0.1)
        assert config.speaking_rate == 0.5  # Clamped to min
        
        # Too high
        config = VoiceConfig(character_id="test", speaking_rate=5.0)
        assert config.speaking_rate == 2.0  # Clamped to max
        
        # Valid
        config = VoiceConfig(character_id="test", speaking_rate=1.5)
        assert config.speaking_rate == 1.5
    
    def test_pitch_shift_clamping(self):
        """Pitch shift should be clamped to valid range."""
        # Too low
        config = VoiceConfig(character_id="test", pitch_shift=-24.0)
        assert config.pitch_shift == -12.0  # Clamped to min
        
        # Too high
        config = VoiceConfig(character_id="test", pitch_shift=24.0)
        assert config.pitch_shift == 12.0  # Clamped to max
        
        # Valid
        config = VoiceConfig(character_id="test", pitch_shift=-5.0)
        assert config.pitch_shift == -5.0
    
    def test_custom_params_isolation(self):
        """Custom params should be isolated between instances."""
        config1 = VoiceConfig(character_id="a")
        config2 = VoiceConfig(character_id="b")
        
        config1.custom_params["key"] = "value"
        
        assert "key" not in config2.custom_params


# =============================================================================
# DIALOGUE LINE TESTS
# =============================================================================

class TestDialogueLine:
    """Test DialogueLine dataclass."""
    
    def test_basic_creation(self):
        """DialogueLine should store all required fields."""
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="Hello, world!",
            start_time_sec=5.0,
        )
        assert line.line_id == "line_001"
        assert line.character_id == "alice"
        assert line.text == "Hello, world!"
        assert line.start_time_sec == 5.0
    
    def test_estimated_duration_calculation(self):
        """Estimated duration should be based on word count."""
        # Short line
        short = DialogueLine(
            line_id="1", character_id="a", text="Hi", start_time_sec=0
        )
        assert short.estimated_duration_sec == pytest.approx(0.4, rel=0.1)
        
        # Longer line (~10 words = 4 seconds)
        long = DialogueLine(
            line_id="2",
            character_id="a",
            text="This is a longer sentence with about ten words total here",
            start_time_sec=0,
        )
        assert long.estimated_duration_sec == pytest.approx(4.0, rel=0.2)
    
    def test_empty_text_duration(self):
        """Empty text should have zero duration."""
        line = DialogueLine(
            line_id="1", character_id="a", text="", start_time_sec=0
        )
        assert line.estimated_duration_sec == 0.0
    
    def test_optional_fields(self):
        """Optional fields should have None defaults."""
        line = DialogueLine(
            line_id="1", character_id="a", text="test", start_time_sec=0
        )
        assert line.emotion is None
        assert line.direction is None
        assert line.shot_id == ""
        assert line.scene_id == ""


# =============================================================================
# SYNTHESIZED DIALOGUE TESTS
# =============================================================================

class TestSynthesizedDialogue:
    """Test SynthesizedDialogue dataclass."""
    
    def test_successful_synthesis_result(self):
        """SynthesizedDialogue should store successful results."""
        result = SynthesizedDialogue(
            line_id="line_001",
            audio_path=Path("/path/to/audio.wav"),
            actual_duration_sec=2.5,
            sample_rate=44100,
            status=AudioGenerationStatus.COMPLETE,
            generation_time_sec=0.8,
        )
        assert result.line_id == "line_001"
        assert result.audio_path == Path("/path/to/audio.wav")
        assert result.status == AudioGenerationStatus.COMPLETE
    
    def test_failed_factory_method(self):
        """SynthesizedDialogue.failed() should create a failure result."""
        result = SynthesizedDialogue.failed("line_001", "API rate limited")
        
        assert result.line_id == "line_001"
        assert result.status == AudioGenerationStatus.FAILED
        assert result.error == "API rate limited"
        assert result.audio_path is None
    
    def test_path_string_conversion(self):
        """String paths should be converted to Path objects."""
        result = SynthesizedDialogue(
            line_id="1",
            audio_path="/string/path.wav",  # String, not Path
            status=AudioGenerationStatus.COMPLETE,
        )
        assert isinstance(result.audio_path, Path)
        assert str(result.audio_path) == "/string/path.wav"


# =============================================================================
# AMBIENCE SPEC TESTS
# =============================================================================

class TestAmbienceSpec:
    """Test AmbienceSpec dataclass."""
    
    def test_basic_creation(self):
        """AmbienceSpec should store all fields."""
        spec = AmbienceSpec(
            ambience_id="amb_001",
            type=AmbienceType.EXTERIOR_URBAN,
            description="busy city street with traffic",
            duration_sec=30.0,
        )
        assert spec.ambience_id == "amb_001"
        assert spec.type == AmbienceType.EXTERIOR_URBAN
        assert spec.description == "busy city street with traffic"
        assert spec.duration_sec == 30.0
    
    def test_intensity_clamping(self):
        """Intensity should be clamped to 0-1 range."""
        # Too low
        spec = AmbienceSpec(
            ambience_id="1",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=10,
            intensity=-0.5,
        )
        assert spec.intensity == 0.0
        
        # Too high
        spec = AmbienceSpec(
            ambience_id="2",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=10,
            intensity=1.5,
        )
        assert spec.intensity == 1.0
        
        # Valid
        spec = AmbienceSpec(
            ambience_id="3",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=10,
            intensity=0.7,
        )
        assert spec.intensity == 0.7
    
    def test_default_values(self):
        """Defaults should be sensible."""
        spec = AmbienceSpec(
            ambience_id="1",
            type=AmbienceType.INTERIOR_QUIET,
            description="office",
            duration_sec=60,
        )
        assert spec.intensity == 0.5
        assert spec.loop is True
        assert spec.shot_id == ""
        assert spec.scene_id == ""


# =============================================================================
# FOLEY EVENT TESTS
# =============================================================================

class TestFoleyEvent:
    """Test FoleyEvent dataclass."""
    
    def test_basic_creation(self):
        """FoleyEvent should store all fields."""
        event = FoleyEvent(
            event_id="foley_001",
            category=FoleyCategory.IMPACT,
            description="glass breaking on tile floor",
            trigger_time_sec=4.5,
        )
        assert event.event_id == "foley_001"
        assert event.category == FoleyCategory.IMPACT
        assert event.description == "glass breaking on tile floor"
        assert event.trigger_time_sec == 4.5
    
    def test_default_duration(self):
        """Default duration should be 1 second."""
        event = FoleyEvent(
            event_id="1",
            category=FoleyCategory.FOOTSTEPS,
            description="step",
            trigger_time_sec=0,
        )
        assert event.duration_sec == 1.0
    
    def test_custom_volume(self):
        """Volume adjustment should be stored."""
        event = FoleyEvent(
            event_id="1",
            category=FoleyCategory.IMPACT,
            description="loud crash",
            trigger_time_sec=0,
            volume_db=6.0,  # Louder than normal
        )
        assert event.volume_db == 6.0


# =============================================================================
# SHOT AUDIO PLAN TESTS
# =============================================================================

class TestShotAudioPlan:
    """Test ShotAudioPlan dataclass."""
    
    def test_empty_plan(self):
        """Empty plan should have no dialogue or foley."""
        plan = ShotAudioPlan(
            shot_id="shot_001",
            scene_id="scene_001",
            duration_sec=12.0,
        )
        assert plan.has_dialogue is False
        assert plan.has_foley is False
        assert len(plan.dialogue_lines) == 0
        assert len(plan.foley_events) == 0
        assert plan.ambience is None
    
    def test_plan_with_dialogue(self):
        """Plan with dialogue should report has_dialogue=True."""
        plan = ShotAudioPlan(
            shot_id="shot_001",
            scene_id="scene_001",
            duration_sec=12.0,
            dialogue_lines=[
                DialogueLine(
                    line_id="1", character_id="a", text="Hello", start_time_sec=0
                ),
            ],
        )
        assert plan.has_dialogue is True
        assert plan.has_foley is False
    
    def test_plan_with_foley(self):
        """Plan with foley should report has_foley=True."""
        plan = ShotAudioPlan(
            shot_id="shot_001",
            scene_id="scene_001",
            duration_sec=12.0,
            foley_events=[
                FoleyEvent(
                    event_id="1",
                    category=FoleyCategory.DOOR,
                    description="door slam",
                    trigger_time_sec=5.0,
                ),
            ],
        )
        assert plan.has_dialogue is False
        assert plan.has_foley is True


# =============================================================================
# SONIC MANIFEST TESTS
# =============================================================================

class TestSonicManifest:
    """Test SonicManifest dataclass and validation."""
    
    def test_empty_manifest(self):
        """Empty manifest should have zero counts."""
        manifest = SonicManifest(
            manifest_id="manifest_001",
            project_id="project_001",
        )
        assert manifest.total_dialogue_lines == 0
        assert manifest.total_foley_events == 0
        assert manifest.total_duration_sec == 0.0
    
    def test_manifest_with_content(self):
        """Manifest with content should calculate totals correctly."""
        manifest = SonicManifest(
            manifest_id="manifest_001",
            project_id="project_001",
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="1", character_id="a", text="Hi", start_time_sec=0
                        ),
                        DialogueLine(
                            line_id="2", character_id="b", text="Hello", start_time_sec=2
                        ),
                    ],
                    foley_events=[
                        FoleyEvent(
                            event_id="f1",
                            category=FoleyCategory.DOOR,
                            description="door",
                            trigger_time_sec=1,
                        ),
                    ],
                ),
                ShotAudioPlan(
                    shot_id="shot_002",
                    scene_id="scene_001",
                    duration_sec=5.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="3", character_id="a", text="Bye", start_time_sec=0
                        ),
                    ],
                ),
            ],
        )
        assert manifest.total_dialogue_lines == 3
        assert manifest.total_foley_events == 1
        assert manifest.total_duration_sec == 15.0
    
    def test_get_voice_config(self):
        """get_voice_config should return config or None."""
        manifest = SonicManifest(
            manifest_id="1",
            project_id="1",
            voice_configs={
                "alice": VoiceConfig(
                    character_id="alice",
                    voice_id="alice_voice_123",
                ),
            },
        )
        
        alice_config = manifest.get_voice_config("alice")
        assert alice_config is not None
        assert alice_config.voice_id == "alice_voice_123"
        
        bob_config = manifest.get_voice_config("bob")
        assert bob_config is None
    
    def test_validate_missing_voice_config(self):
        """Validation should catch missing voice configs."""
        manifest = SonicManifest(
            manifest_id="1",
            project_id="1",
            voice_configs={
                "alice": VoiceConfig(character_id="alice"),
            },
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="1",
                            character_id="alice",  # Has config
                            text="Hi",
                            start_time_sec=0,
                        ),
                        DialogueLine(
                            line_id="2",
                            character_id="bob",  # Missing config!
                            text="Hello",
                            start_time_sec=2,
                        ),
                    ],
                ),
            ],
        )
        
        issues = manifest.validate()
        assert len(issues) == 1
        assert "bob" in issues[0]
        assert "Missing voice config" in issues[0]
    
    def test_validate_overlapping_dialogue(self):
        """Validation should warn about overlapping dialogue."""
        manifest = SonicManifest(
            manifest_id="1",
            project_id="1",
            voice_configs={
                "alice": VoiceConfig(character_id="alice"),
            },
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="1",
                            character_id="alice",
                            text="This is a really long sentence that takes several seconds",
                            start_time_sec=0.0,
                        ),
                        DialogueLine(
                            line_id="2",
                            character_id="alice",
                            text="This starts too soon",
                            start_time_sec=1.0,  # Overlaps with previous!
                        ),
                    ],
                ),
            ],
        )
        
        issues = manifest.validate()
        assert len(issues) >= 1
        assert any("overlap" in issue.lower() for issue in issues)
    
    def test_validate_clean_manifest(self):
        """Valid manifest should have no issues."""
        manifest = SonicManifest(
            manifest_id="1",
            project_id="1",
            voice_configs={
                "alice": VoiceConfig(character_id="alice"),
                "bob": VoiceConfig(character_id="bob"),
            },
            shot_plans=[
                ShotAudioPlan(
                    shot_id="shot_001",
                    scene_id="scene_001",
                    duration_sec=10.0,
                    dialogue_lines=[
                        DialogueLine(
                            line_id="1",
                            character_id="alice",
                            text="Hi",
                            start_time_sec=0.0,
                        ),
                        DialogueLine(
                            line_id="2",
                            character_id="bob",
                            text="Hello",
                            start_time_sec=5.0,  # Plenty of gap
                        ),
                    ],
                ),
            ],
        )
        
        issues = manifest.validate()
        assert len(issues) == 0


# =============================================================================
# MIX RESULT TESTS
# =============================================================================

class TestMixResult:
    """Test MixResult dataclass."""
    
    def test_successful_result(self):
        """MixResult should store successful mix info."""
        result = MixResult(
            mix_id="mix_001",
            shot_id="shot_001",
            output_path=Path("/path/to/mixed.wav"),
            duration_sec=12.0,
            component_count=5,
            peak_db=-3.0,
            status=AudioGenerationStatus.COMPLETE,
        )
        assert result.mix_id == "mix_001"
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.component_count == 5
    
    def test_failed_factory_method(self):
        """MixResult.failed() should create a failure result."""
        result = MixResult.failed("mix_001", "shot_001", "FFmpeg crashed")
        
        assert result.mix_id == "mix_001"
        assert result.shot_id == "shot_001"
        assert result.status == AudioGenerationStatus.FAILED
        assert result.error == "FFmpeg crashed"
        assert result.output_path is None
    
    def test_warnings_list(self):
        """Warnings should be stored."""
        result = MixResult(
            mix_id="1",
            shot_id="1",
            status=AudioGenerationStatus.COMPLETE,
            warnings=["Low audio level detected", "Possible clipping at 5.2s"],
        )
        assert len(result.warnings) == 2


# =============================================================================
# EDGE CASES AND NIGHTMARE SCENARIOS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_unicode_in_dialogue(self):
        """Dialogue should handle unicode characters."""
        line = DialogueLine(
            line_id="1",
            character_id="narrator",
            text="日本語テスト 🎬 Ελληνικά",
            start_time_sec=0,
        )
        assert "日本語" in line.text
        assert "🎬" in line.text
    
    def test_very_long_text(self):
        """Very long text should not break."""
        long_text = "word " * 10000  # 10k words
        line = DialogueLine(
            line_id="1",
            character_id="a",
            text=long_text,
            start_time_sec=0,
        )
        # Should estimate ~4000 seconds (10k words / 2.5 words per second)
        assert line.estimated_duration_sec > 3000
    
    def test_zero_duration_shot(self):
        """Zero duration shot should be handled."""
        plan = ShotAudioPlan(
            shot_id="1",
            scene_id="1",
            duration_sec=0.0,
        )
        assert plan.duration_sec == 0.0
    
    def test_negative_time_values(self):
        """Negative times should be stored (validation is caller's job)."""
        line = DialogueLine(
            line_id="1",
            character_id="a",
            text="test",
            start_time_sec=-5.0,  # Invalid but should store
        )
        assert line.start_time_sec == -5.0
    
    def test_path_with_spaces_and_special_chars(self):
        """Paths with special characters should work."""
        result = SynthesizedDialogue(
            line_id="1",
            audio_path="/path/with spaces/and (parens)/file.wav",
            status=AudioGenerationStatus.COMPLETE,
        )
        assert "spaces" in str(result.audio_path)
        assert "(parens)" in str(result.audio_path)
    
    def test_empty_character_id(self):
        """Empty character ID should be allowed (narrator case)."""
        line = DialogueLine(
            line_id="1",
            character_id="",
            text="Narrator text",
            start_time_sec=0,
        )
        assert line.character_id == ""
    
    def test_manifest_with_100_shots(self):
        """Large manifest should work."""
        shots = [
            ShotAudioPlan(
                shot_id=f"shot_{i:03d}",
                scene_id="scene_001",
                duration_sec=10.0,
                dialogue_lines=[
                    DialogueLine(
                        line_id=f"line_{i}",
                        character_id="alice",
                        text=f"Line number {i}",
                        start_time_sec=0,
                    )
                ],
            )
            for i in range(100)
        ]
        
        manifest = SonicManifest(
            manifest_id="large",
            project_id="stress_test",
            voice_configs={"alice": VoiceConfig(character_id="alice")},
            shot_plans=shots,
        )
        
        assert manifest.total_dialogue_lines == 100
        assert manifest.total_duration_sec == 1000.0
        assert len(manifest.validate()) == 0
    
    def test_special_characters_in_ids(self):
        """IDs with special characters should be handled."""
        line = DialogueLine(
            line_id="line-001_v2.final",
            character_id="char:alice@main",
            text="test",
            start_time_sec=0,
        )
        assert line.line_id == "line-001_v2.final"
        assert line.character_id == "char:alice@main"


# =============================================================================
# IMMUTABILITY AND ISOLATION TESTS
# =============================================================================

class TestImmutabilityAndIsolation:
    """Test that instances don't leak state."""
    
    def test_dialogue_lines_list_isolation(self):
        """Modifying one plan's dialogue shouldn't affect another."""
        plan1 = ShotAudioPlan(shot_id="1", scene_id="1", duration_sec=10)
        plan2 = ShotAudioPlan(shot_id="2", scene_id="1", duration_sec=10)
        
        plan1.dialogue_lines.append(
            DialogueLine(line_id="x", character_id="a", text="t", start_time_sec=0)
        )
        
        assert len(plan2.dialogue_lines) == 0
    
    def test_voice_configs_dict_isolation(self):
        """Modifying one manifest's voice configs shouldn't affect another."""
        manifest1 = SonicManifest(manifest_id="1", project_id="1")
        manifest2 = SonicManifest(manifest_id="2", project_id="1")
        
        manifest1.voice_configs["alice"] = VoiceConfig(character_id="alice")
        
        assert "alice" not in manifest2.voice_configs
    
    def test_metadata_dict_isolation(self):
        """Metadata dicts should be isolated."""
        manifest1 = SonicManifest(manifest_id="1", project_id="1")
        manifest2 = SonicManifest(manifest_id="2", project_id="1")
        
        manifest1.metadata["key"] = "value"
        
        assert "key" not in manifest2.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])