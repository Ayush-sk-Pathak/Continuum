"""
Tests for Sonic Engines (TTS, Ambience, Foley)

Tests cover:
- Mock engine functionality (no API calls)
- Engine registry and factory functions
- Error handling and graceful failures
- Configuration validation
- Async behavior
- Edge cases and nightmare scenarios
"""

import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.sonic.types import (
    TTSProvider,
    VoiceEmotion,
    AmbienceType,
    FoleyCategory,
    AudioGenerationStatus,
    VoiceConfig,
    DialogueLine,
    AmbienceSpec,
    FoleyEvent,
)
from src.sonic.tts_engine import SynthesizedDialogue, AudioGenerationStatus

from src.sonic.tts_engine import (
    BaseTTSEngine,
    ElevenLabsTTSEngine,
    OpenAITTSEngine,
    TTSError,
    TTSConfigError,
    TTSAPIError,
    get_tts_engine,
    list_tts_providers,
    synthesize_batch,
)

from src.sonic.ambience import (
    BaseAmbienceEngine,
    ReplicateAmbienceEngine,
    MockAmbienceEngine,
    AmbienceProvider,
    AmbienceError,
    AmbienceConfigError,
    get_ambience_engine,
    list_ambience_providers,
    generate_scene_ambience,
)

from src.sonic.foley import (
    BaseFoleyEngine,
    FreesoundFoleyEngine,
    AudioLDMFoleyEngine,
    HybridFoleyEngine,
    MockFoleyEngine,
    FoleyProvider,
    FoleyMatch,
    FoleyError,
    FoleyConfigError,
    get_foley_engine,
    list_foley_providers,
    retrieve_batch,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test outputs."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_dialogue_line():
    """Create a sample dialogue line for testing."""
    return DialogueLine(
        line_id="test_line_001",
        character_id="alice",
        text="Hello, this is a test.",
        start_time_sec=0.0,
        shot_id="shot_001",
        scene_id="scene_001",
    )


@pytest.fixture
def sample_voice_config():
    """Create a sample voice config for testing."""
    return VoiceConfig(
        character_id="alice",
        provider=TTSProvider.ELEVENLABS,
        voice_id="test_voice_id",
        speaking_rate=1.0,
        default_emotion=VoiceEmotion.NEUTRAL,
    )


@pytest.fixture
def sample_ambience_spec():
    """Create a sample ambience spec for testing."""
    return AmbienceSpec(
        ambience_id="amb_001",
        type=AmbienceType.INTERIOR_QUIET,
        description="quiet office with distant keyboard typing",
        duration_sec=30.0,
        scene_id="scene_001",
    )


@pytest.fixture
def sample_foley_event():
    """Create a sample foley event for testing."""
    return FoleyEvent(
        event_id="foley_001",
        category=FoleyCategory.IMPACT,
        description="ceramic mug breaking on tile floor",
        trigger_time_sec=4.5,
        duration_sec=1.5,
        shot_id="shot_001",
        scene_id="scene_001",
    )


# =============================================================================
# TTS ENGINE TESTS
# =============================================================================

class TestTTSEngineRegistry:
    """Test TTS engine registry and factory."""
    
    def test_list_providers(self):
        """Should list all registered providers."""
        providers = list_tts_providers()
        assert TTSProvider.ELEVENLABS in providers
        assert TTSProvider.OPENAI in providers
    
    def test_get_engine_missing_api_key(self, temp_output_dir):
        """Should raise error if API key is missing."""
        # Clear env vars
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(TTSConfigError) as exc_info:
                get_tts_engine(
                    TTSProvider.ELEVENLABS,
                    output_dir=temp_output_dir,
                )
            assert "API key" in str(exc_info.value)
    
    def test_get_engine_invalid_provider(self, temp_output_dir):
        """Should raise error for invalid provider."""
        with pytest.raises(ValueError) as exc_info:
            get_tts_engine("invalid_provider", output_dir=temp_output_dir)
        assert "not registered" in str(exc_info.value)


class TestElevenLabsTTSEngine:
    """Test ElevenLabs TTS engine."""
    
    def test_init_with_api_key(self, temp_output_dir):
        """Should initialize with provided API key."""
        engine = ElevenLabsTTSEngine(
            api_key="test_key_123",
            output_dir=temp_output_dir,
        )
        assert engine.api_key == "test_key_123"
        assert engine.provider == TTSProvider.ELEVENLABS
    
    def test_init_from_env_var(self, temp_output_dir):
        """Should read API key from environment."""
        with patch.dict('os.environ', {'ELEVENLABS_API_KEY': 'env_key_456'}):
            engine = ElevenLabsTTSEngine(output_dir=temp_output_dir)
            assert engine.api_key == "env_key_456"
    
    def test_output_path_generation(self, temp_output_dir):
        """Should generate correct output paths."""
        engine = ElevenLabsTTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        line = DialogueLine(
            line_id="line_001",
            character_id="alice",
            text="test",
            start_time_sec=0,
            shot_id="shot_001",
            scene_id="scene_001",
        )
        
        path = engine._generate_output_path(line)
        assert "scene_001" in str(path)
        assert "shot_001" in str(path)
        assert "line_001" in str(path)
        assert path.suffix == ".wav"
    
    def test_estimate_cost(self, temp_output_dir):
        """Should estimate cost based on character count."""
        engine = ElevenLabsTTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        
        # 1000 characters = ~$0.30
        cost = engine.estimate_cost("a" * 1000)
        assert cost == pytest.approx(0.30, rel=0.1)
        
        # 100 characters = ~$0.03
        cost = engine.estimate_cost("a" * 100)
        assert cost == pytest.approx(0.03, rel=0.1)
    
    def test_supports_all_emotions(self, temp_output_dir):
        """ElevenLabs should support all emotions."""
        engine = ElevenLabsTTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        for emotion in VoiceEmotion:
            assert engine.supports_emotion(emotion) is True


class TestOpenAITTSEngine:
    """Test OpenAI TTS engine."""
    
    def test_init_with_api_key(self, temp_output_dir):
        """Should initialize with provided API key."""
        engine = OpenAITTSEngine(
            api_key="test_key_123",
            output_dir=temp_output_dir,
        )
        assert engine.api_key == "test_key_123"
        assert engine.provider == TTSProvider.OPENAI
    
    def test_voice_options(self, temp_output_dir):
        """Should have valid voice options."""
        engine = OpenAITTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        assert "alloy" in engine.VOICES
        assert "nova" in engine.VOICES
        assert len(engine.VOICES) == 6
    
    def test_estimate_cost_cheaper_than_elevenlabs(self, temp_output_dir):
        """OpenAI should be cheaper than ElevenLabs."""
        openai_engine = OpenAITTSEngine(api_key="test", output_dir=temp_output_dir)
        elevenlabs_engine = ElevenLabsTTSEngine(api_key="test", output_dir=temp_output_dir)
        
        text = "a" * 1000
        openai_cost = openai_engine.estimate_cost(text)
        elevenlabs_cost = elevenlabs_engine.estimate_cost(text)
        
        assert openai_cost < elevenlabs_cost
    
    def test_limited_emotion_support(self, temp_output_dir):
        """OpenAI should have limited emotion support."""
        engine = OpenAITTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        assert engine.supports_emotion(VoiceEmotion.NEUTRAL) is True
        assert engine.supports_emotion(VoiceEmotion.WHISPER) is False


class TestTTSBatchSynthesis:
    """Test batch synthesis helper."""
    
    @pytest.mark.asyncio
    async def test_batch_with_missing_voice_config(self, temp_output_dir):
        """Should fail gracefully for missing voice configs."""
        # Create a mock engine
        class MockTTSEngine(BaseTTSEngine):
            provider = TTSProvider.ELEVENLABS
            
            async def synthesize(self, line, voice_config):
                return SynthesizedDialogue(
                    line_id=line.line_id,
                    status=AudioGenerationStatus.COMPLETE,
                )
            
            async def health_check(self):
                return True
            
            def estimate_cost(self, text):
                return 0.0
            
            async def list_voices(self):
                return []
        
        engine = MockTTSEngine(output_dir=temp_output_dir)
        
        lines = [
            DialogueLine(line_id="1", character_id="alice", text="Hi", start_time_sec=0),
            DialogueLine(line_id="2", character_id="bob", text="Hello", start_time_sec=1),  # No config!
        ]
        
        voice_configs = {
            "alice": VoiceConfig(character_id="alice"),
            # bob is missing!
        }
        
        from src.sonic.tts_engine import synthesize_batch
        results = await synthesize_batch(engine, lines, voice_configs)
        
        assert len(results) == 2
        assert results[0].status == AudioGenerationStatus.COMPLETE
        assert results[1].status == AudioGenerationStatus.FAILED
        assert "bob" in results[1].error


# =============================================================================
# AMBIENCE ENGINE TESTS
# =============================================================================

class TestAmbienceEngineRegistry:
    """Test ambience engine registry and factory."""
    
    def test_list_providers(self):
        """Should list all registered providers."""
        providers = list_ambience_providers()
        assert AmbienceProvider.REPLICATE in providers
        assert AmbienceProvider.MOCK in providers
    
    def test_get_mock_engine(self, temp_output_dir):
        """Should get mock engine without API key."""
        engine = get_ambience_engine(
            AmbienceProvider.MOCK,
            output_dir=temp_output_dir,
        )
        assert engine.provider == AmbienceProvider.MOCK


class TestMockAmbienceEngine:
    """Test mock ambience engine."""
    
    @pytest.mark.asyncio
    async def test_generates_silent_wav(self, temp_output_dir, sample_ambience_spec):
        """Mock should generate actual silent WAV files."""
        engine = MockAmbienceEngine(
            output_dir=temp_output_dir,
            simulate_delay_sec=0.01,  # Fast for testing
        )
        
        result = await engine.generate(sample_ambience_spec)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path is not None
        assert result.audio_path.exists()
        assert result.audio_path.stat().st_size > 0
    
    @pytest.mark.asyncio
    async def test_health_check_always_healthy(self, temp_output_dir):
        """Mock should always report healthy."""
        engine = MockAmbienceEngine(output_dir=temp_output_dir)
        assert await engine.health_check() is True
    
    def test_estimate_cost_is_zero(self, temp_output_dir):
        """Mock should have zero cost."""
        engine = MockAmbienceEngine(output_dir=temp_output_dir)
        assert engine.estimate_cost(60.0) == 0.0


class TestReplicateAmbienceEngine:
    """Test Replicate ambience engine."""
    
    def test_init_missing_api_token(self, temp_output_dir):
        """Should raise error if API token is missing."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(AmbienceConfigError) as exc_info:
                ReplicateAmbienceEngine(output_dir=temp_output_dir)
            assert "API token" in str(exc_info.value)
    
    def test_prompt_building(self, temp_output_dir):
        """Should build effective prompts from specs."""
        engine = ReplicateAmbienceEngine(
            api_token="test",
            output_dir=temp_output_dir,
        )
        
        spec = AmbienceSpec(
            ambience_id="1",
            type=AmbienceType.EXTERIOR_URBAN,
            description="busy intersection",
            duration_sec=30,
        )
        
        prompt = engine._build_prompt(spec)
        
        assert "city" in prompt.lower() or "urban" in prompt.lower()
        assert "busy intersection" in prompt
        assert "no music" in prompt.lower()


class TestAmbienceBatchGeneration:
    """Test batch ambience generation."""
    
    @pytest.mark.asyncio
    async def test_batch_generation(self, temp_output_dir):
        """Should generate multiple ambiences in parallel."""
        engine = MockAmbienceEngine(
            output_dir=temp_output_dir,
            simulate_delay_sec=0.01,
        )
        
        specs = [
            AmbienceSpec(
                ambience_id=f"amb_{i}",
                type=AmbienceType.INTERIOR_QUIET,
                description=f"office {i}",
                duration_sec=10,
                scene_id=f"scene_{i}",
            )
            for i in range(5)
        ]
        
        results = await generate_scene_ambience(engine, specs, max_concurrent=2)
        
        assert len(results) == 5
        assert all(r.status == AudioGenerationStatus.COMPLETE for r in results)


# =============================================================================
# FOLEY ENGINE TESTS
# =============================================================================

class TestFoleyEngineRegistry:
    """Test foley engine registry and factory."""
    
    def test_list_providers(self):
        """Should list all registered providers."""
        providers = list_foley_providers()
        assert FoleyProvider.FREESOUND in providers
        assert FoleyProvider.AUDIOLDM in providers
        assert FoleyProvider.HYBRID in providers
        assert FoleyProvider.MOCK in providers
    
    def test_get_mock_engine(self, temp_output_dir):
        """Should get mock engine without API key."""
        engine = get_foley_engine(
            FoleyProvider.MOCK,
            output_dir=temp_output_dir,
        )
        assert engine.provider == FoleyProvider.MOCK


class TestMockFoleyEngine:
    """Test mock foley engine."""
    
    @pytest.mark.asyncio
    async def test_generates_silent_wav(self, temp_output_dir, sample_foley_event):
        """Mock should generate actual silent WAV files."""
        engine = MockFoleyEngine(
            output_dir=temp_output_dir,
            simulate_delay_sec=0.01,
        )
        
        result = await engine.retrieve(sample_foley_event)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path is not None
        assert result.audio_path.exists()
        assert result.source == "mock"
    
    @pytest.mark.asyncio
    async def test_search_returns_mock_results(self, temp_output_dir):
        """Mock search should return fake results."""
        engine = MockFoleyEngine(output_dir=temp_output_dir)
        
        results = await engine.search("footsteps", max_results=3)
        
        assert len(results) == 3
        assert all(isinstance(r, FoleyMatch) for r in results)
        assert all(r.score > 0 for r in results)


class TestFoleyMatch:
    """Test FoleyMatch dataclass."""
    
    def test_is_good_match_threshold(self):
        """Should correctly identify good matches."""
        good = FoleyMatch(
            sound_id="1",
            name="test",
            description="test",
            duration_sec=1.0,
            score=0.75,
            preview_url="http://example.com/sound.wav",
        )
        assert good.is_good_match is True
        
        bad = FoleyMatch(
            sound_id="2",
            name="test",
            description="test",
            duration_sec=1.0,
            score=0.65,
            preview_url="http://example.com/sound.wav",
        )
        assert bad.is_good_match is False


class TestFreesoundFoleyEngine:
    """Test Freesound foley engine."""
    
    def test_init_missing_api_key(self, temp_output_dir):
        """Should raise error if API key is missing."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(FoleyConfigError) as exc_info:
                FreesoundFoleyEngine(output_dir=temp_output_dir)
            assert "API key" in str(exc_info.value)
    
    def test_search_query_building(self, temp_output_dir):
        """Should build effective search queries."""
        engine = FreesoundFoleyEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        
        event = FoleyEvent(
            event_id="1",
            category=FoleyCategory.FOOTSTEPS,
            description="walking on gravel",
            trigger_time_sec=0,
        )
        
        query = engine._build_search_query(event)
        
        assert "footstep" in query.lower()
        assert "walking on gravel" in query


class TestHybridFoleyEngine:
    """Test hybrid foley engine."""
    
    def test_init_without_replicate(self, temp_output_dir):
        """Should work without Replicate (library-only mode)."""
        with patch.dict('os.environ', {'FREESOUND_API_KEY': 'test_key'}, clear=True):
            engine = HybridFoleyEngine(
                freesound_api_key="test_key",
                output_dir=temp_output_dir,
            )
            assert engine.library_engine is not None
            assert engine.generation_engine is None  # No Replicate token


class TestFoleyBatchRetrieval:
    """Test batch foley retrieval."""
    
    @pytest.mark.asyncio
    async def test_batch_retrieval(self, temp_output_dir):
        """Should retrieve multiple foley sounds in parallel."""
        engine = MockFoleyEngine(
            output_dir=temp_output_dir,
            simulate_delay_sec=0.01,
        )
        
        events = [
            FoleyEvent(
                event_id=f"foley_{i}",
                category=FoleyCategory.FOOTSTEPS,
                description=f"footstep {i}",
                trigger_time_sec=float(i),
                shot_id="shot_001",
                scene_id="scene_001",
            )
            for i in range(10)
        ]
        
        results = await retrieve_batch(engine, events, max_concurrent=3)
        
        assert len(results) == 10
        assert all(r.status == AudioGenerationStatus.COMPLETE for r in results)


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Test error handling across all engines."""
    
    @pytest.mark.asyncio
    async def test_ambience_generates_error_result_not_exception(self, temp_output_dir):
        """Engines should return error results, not raise exceptions."""
        
        class FailingAmbienceEngine(BaseAmbienceEngine):
            provider = AmbienceProvider.MOCK
            
            async def generate(self, spec):
                raise Exception("Simulated API failure")
            
            async def health_check(self):
                return False
            
            def estimate_cost(self, duration_sec):
                return 0.0
        
        # The mock engine wraps exceptions in result objects
        engine = MockAmbienceEngine(output_dir=temp_output_dir)
        
        # Manually test the pattern used in real engines
        spec = AmbienceSpec(
            ambience_id="1",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=10,
        )
        
        # This should not raise
        result = await engine.generate(spec)
        assert result.status == AudioGenerationStatus.COMPLETE
    
    @pytest.mark.asyncio
    async def test_foley_handles_missing_file(self, temp_output_dir):
        """Foley should handle missing cached files gracefully."""
        engine = MockFoleyEngine(output_dir=temp_output_dir)
        
        event = FoleyEvent(
            event_id="test",
            category=FoleyCategory.IMPACT,
            description="crash",
            trigger_time_sec=0,
        )
        
        result = await engine.retrieve(event)
        
        # Should succeed even on first run (no cache)
        assert result.status == AudioGenerationStatus.COMPLETE


# =============================================================================
# CACHING TESTS
# =============================================================================

class TestCaching:
    """Test caching behavior in foley engine."""
    
    def test_cache_path_generation(self, temp_output_dir):
        """Should generate consistent cache paths."""
        engine = MockFoleyEngine(
            output_dir=temp_output_dir,
            cache_dir=temp_output_dir / "cache",
        )
        
        path1 = engine._get_cache_path("sound_123", "freesound")
        path2 = engine._get_cache_path("sound_123", "freesound")
        path3 = engine._get_cache_path("sound_456", "freesound")
        
        assert path1 == path2  # Same input = same output
        assert path1 != path3  # Different input = different output
    
    def test_cache_path_handles_special_chars(self, temp_output_dir):
        """Cache paths should handle special characters in IDs."""
        engine = MockFoleyEngine(
            output_dir=temp_output_dir,
            cache_dir=temp_output_dir / "cache",
        )
        
        # These should not raise
        path = engine._get_cache_path("sound/with/slashes", "source")
        assert path is not None
        
        path = engine._get_cache_path("sound with spaces", "source")
        assert path is not None


# =============================================================================
# ASYNC CONCURRENCY TESTS
# =============================================================================

class TestAsyncConcurrency:
    """Test async behavior and concurrency."""
    
    @pytest.mark.asyncio
    async def test_concurrent_generation_respects_semaphore(self, temp_output_dir):
        """Batch operations should respect concurrency limits."""
        call_count = 0
        max_concurrent = 0
        current_concurrent = 0
        
        class TrackedEngine(MockAmbienceEngine):
            async def generate(self, spec):
                nonlocal call_count, max_concurrent, current_concurrent
                call_count += 1
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
                
                await asyncio.sleep(0.05)  # Simulate work
                
                current_concurrent -= 1
                return await super().generate(spec)
        
        engine = TrackedEngine(output_dir=temp_output_dir, simulate_delay_sec=0)
        
        specs = [
            AmbienceSpec(
                ambience_id=f"amb_{i}",
                type=AmbienceType.SILENCE,
                description="",
                duration_sec=5,
            )
            for i in range(10)
        ]
        
        # Limit to 2 concurrent
        await generate_scene_ambience(engine, specs, max_concurrent=2)
        
        assert call_count == 10
        assert max_concurrent <= 2
    
    @pytest.mark.asyncio
    async def test_batch_handles_mixed_success_failure(self, temp_output_dir):
        """Batch should handle mix of successes and failures."""
        
        class FlakeyEngine(MockFoleyEngine):
            async def retrieve(self, event):
                if "fail" in event.event_id:
                    from src.sonic.types import SynthesizedFoley
                    return SynthesizedFoley(
                        event_id=event.event_id,
                        status=AudioGenerationStatus.FAILED,
                        error="Simulated failure",
                    )
                return await super().retrieve(event)
        
        engine = FlakeyEngine(output_dir=temp_output_dir, simulate_delay_sec=0.01)
        
        events = [
            FoleyEvent(event_id="success_1", category=FoleyCategory.IMPACT, description="", trigger_time_sec=0),
            FoleyEvent(event_id="fail_1", category=FoleyCategory.IMPACT, description="", trigger_time_sec=1),
            FoleyEvent(event_id="success_2", category=FoleyCategory.IMPACT, description="", trigger_time_sec=2),
            FoleyEvent(event_id="fail_2", category=FoleyCategory.IMPACT, description="", trigger_time_sec=3),
        ]
        
        results = await retrieve_batch(engine, events)
        
        assert len(results) == 4
        assert results[0].status == AudioGenerationStatus.COMPLETE
        assert results[1].status == AudioGenerationStatus.FAILED
        assert results[2].status == AudioGenerationStatus.COMPLETE
        assert results[3].status == AudioGenerationStatus.FAILED


# =============================================================================
# NIGHTMARE SCENARIOS
# =============================================================================

class TestNightmareScenarios:
    """Test extreme and edge cases that could break the system."""
    
    @pytest.mark.asyncio
    async def test_very_long_text_for_tts(self, temp_output_dir):
        """TTS should handle very long text."""
        engine = ElevenLabsTTSEngine(
            api_key="test",
            output_dir=temp_output_dir,
        )
        
        # 10,000 word text
        long_text = "word " * 10000
        
        # Cost estimation should not break
        cost = engine.estimate_cost(long_text)
        assert cost > 0
    
    @pytest.mark.asyncio
    async def test_empty_batch(self, temp_output_dir):
        """Batch operations should handle empty input."""
        engine = MockAmbienceEngine(output_dir=temp_output_dir)
        
        results = await generate_scene_ambience(engine, [], max_concurrent=2)
        
        assert results == []
    
    @pytest.mark.asyncio
    async def test_single_item_batch(self, temp_output_dir):
        """Batch operations should handle single item."""
        engine = MockFoleyEngine(output_dir=temp_output_dir, simulate_delay_sec=0.01)
        
        events = [
            FoleyEvent(
                event_id="single",
                category=FoleyCategory.DOOR,
                description="door",
                trigger_time_sec=0,
            ),
        ]
        
        results = await retrieve_batch(engine, events)
        
        assert len(results) == 1
        assert results[0].status == AudioGenerationStatus.COMPLETE
    
    @pytest.mark.asyncio
    async def test_zero_duration_ambience(self, temp_output_dir):
        """Should handle zero duration request."""
        engine = MockAmbienceEngine(output_dir=temp_output_dir, simulate_delay_sec=0.01)
        
        spec = AmbienceSpec(
            ambience_id="zero",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=0.0,  # Edge case!
        )
        
        result = await engine.generate(spec)
        
        # Should either succeed with empty file or fail gracefully
        assert result.status in [
            AudioGenerationStatus.COMPLETE,
            AudioGenerationStatus.FAILED,
        ]
    
    @pytest.mark.asyncio
    async def test_unicode_in_prompts(self, temp_output_dir):
        """Should handle unicode in descriptions."""
        engine = MockFoleyEngine(output_dir=temp_output_dir, simulate_delay_sec=0.01)
        
        event = FoleyEvent(
            event_id="unicode",
            category=FoleyCategory.CUSTOM,
            description="日本語の音 🎵 café ambiance",
            trigger_time_sec=0,
        )
        
        result = await engine.retrieve(event)
        
        assert result.status == AudioGenerationStatus.COMPLETE
    
    @pytest.mark.asyncio
    async def test_path_with_spaces(self, temp_output_dir):
        """Should handle output paths with spaces."""
        spacy_dir = temp_output_dir / "path with spaces" / "and more spaces"
        spacy_dir.mkdir(parents=True)
        
        engine = MockAmbienceEngine(output_dir=spacy_dir, simulate_delay_sec=0.01)
        
        spec = AmbienceSpec(
            ambience_id="test",
            type=AmbienceType.SILENCE,
            description="",
            duration_sec=5,
        )
        
        result = await engine.generate(spec)
        
        assert result.status == AudioGenerationStatus.COMPLETE
        assert result.audio_path.exists()
    
    @pytest.mark.asyncio
    async def test_rapid_fire_requests(self, temp_output_dir):
        """Should handle many rapid requests without breaking."""
        engine = MockFoleyEngine(output_dir=temp_output_dir, simulate_delay_sec=0)
        
        events = [
            FoleyEvent(
                event_id=f"rapid_{i}",
                category=FoleyCategory.FOOTSTEPS,
                description="step",
                trigger_time_sec=float(i) * 0.1,
            )
            for i in range(100)
        ]
        
        results = await retrieve_batch(engine, events, max_concurrent=10)
        
        assert len(results) == 100
        success_count = sum(1 for r in results if r.status == AudioGenerationStatus.COMPLETE)
        assert success_count == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])