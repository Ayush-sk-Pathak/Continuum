"""
Continuum Engine - Text-to-Speech Engine

Synthesizes dialogue audio from text using pluggable TTS providers.
Follows the same pattern as renderers: abstract base + concrete implementations.

Supported Providers:
    - ElevenLabs: High quality, expressive (default)
    - OpenAI: Fast, good quality, cheaper

Usage:
    engine = get_tts_engine(TTSProvider.ELEVENLABS, api_key="...")
    result = await engine.synthesize(line, voice_config)

Design Principles:
    1. Provider abstraction: Director doesn't care which TTS we use
    2. Async-first: API calls are I/O bound
    3. Granular: One line at a time (enables retakes)
    4. Fail gracefully: Return error result, don't crash pipeline
"""

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    AudioGenerationStatus,
    DialogueLine,
    SynthesizedDialogue,
    TTSProvider,
    VoiceConfig,
    VoiceEmotion,
)


logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class TTSError(Exception):
    """Base exception for TTS errors."""
    def __init__(self, message: str, line_id: Optional[str] = None):
        super().__init__(message)
        self.line_id = line_id


class TTSConfigError(TTSError):
    """Invalid TTS configuration."""
    pass


class TTSAPIError(TTSError):
    """API call failed."""
    def __init__(self, message: str, line_id: Optional[str] = None, 
                 status_code: Optional[int] = None):
        super().__init__(message, line_id)
        self.status_code = status_code


class TTSQuotaError(TTSError):
    """API quota exceeded."""
    pass


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseTTSEngine(ABC):
    """
    Abstract base class for TTS engines.
    
    All TTS providers must implement this interface. This enables
    hot-swapping between ElevenLabs, OpenAI, or local TTS without
    changing any orchestration code.
    
    Attributes:
        provider: Which provider this engine uses
        output_dir: Where to save generated audio files
        sample_rate: Output sample rate (Hz)
    """
    
    provider: TTSProvider
    
    def __init__(
        self,
        output_dir: Path,
        sample_rate: int = 44100,
    ):
        """
        Initialize the TTS engine.
        
        Args:
            output_dir: Directory to save generated audio
            sample_rate: Output sample rate in Hz
        """
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # ABSTRACT METHODS (Must implement)
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def synthesize(
        self,
        line: DialogueLine,
        voice_config: VoiceConfig,
    ) -> SynthesizedDialogue:
        """
        Synthesize a single line of dialogue.
        
        This is the core method. Implementations should:
        1. Map VoiceConfig to provider-specific settings
        2. Call the TTS API
        3. Save audio to output_dir
        4. Return SynthesizedDialogue with path and metadata
        
        Args:
            line: The dialogue line to synthesize
            voice_config: Voice settings for the character
            
        Returns:
            SynthesizedDialogue with path to audio file
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the TTS provider is available.
        
        Returns:
            True if API is reachable and authenticated
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, text: str) -> float:
        """
        Estimate cost to synthesize text in USD.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Estimated cost in USD
        """
        pass
    
    @abstractmethod
    async def list_voices(self) -> List[Dict[str, Any]]:
        """
        List available voices from the provider.
        
        Returns:
            List of voice info dicts with at least 'voice_id' and 'name'
        """
        pass
    
    # -------------------------------------------------------------------------
    # OPTIONAL METHODS (Override if needed)
    # -------------------------------------------------------------------------
    
    async def initialize(self) -> None:
        """
        Perform any async initialization.
        
        Called once before first synthesize(). Override if your engine
        needs to warm up, authenticate, etc.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Clean up resources.
        
        Called when engine is no longer needed.
        """
        pass
    
    def supports_emotion(self, emotion: VoiceEmotion) -> bool:
        """
        Check if this provider supports a specific emotion.
        
        Args:
            emotion: Emotion to check
            
        Returns:
            True if emotion is supported
        """
        # Most providers support basic emotions
        return emotion in [VoiceEmotion.NEUTRAL, VoiceEmotion.HAPPY, VoiceEmotion.SAD]
    
    # -------------------------------------------------------------------------
    # HELPER METHODS (Available to all subclasses)
    # -------------------------------------------------------------------------
    
    def _generate_output_path(self, line: DialogueLine) -> Path:
        """
        Generate a unique output path for a dialogue line.
        
        Format: {output_dir}/{scene_id}_{shot_id}_{line_id}.wav
        """
        filename = f"{line.scene_id}_{line.shot_id}_{line.line_id}.wav"
        return self.output_dir / filename
    
    def _build_ssml(
        self,
        text: str,
        emotion: Optional[VoiceEmotion],
        direction: Optional[str],
    ) -> str:
        """
        Build SSML markup for expressive synthesis.
        
        Only used by providers that support SSML.
        """
        # Base case: no special markup needed
        if not emotion and not direction:
            return text
        
        # Wrap in speak tags
        ssml = f'<speak>{text}</speak>'
        
        # Note: Actual SSML varies by provider. Subclasses should override
        # if they need provider-specific SSML.
        
        return ssml
    
    def _map_emotion_to_style(self, emotion: VoiceEmotion) -> str:
        """
        Map our emotion enum to provider-agnostic style hints.
        
        Subclasses should override with provider-specific mappings.
        """
        mapping = {
            VoiceEmotion.NEUTRAL: "neutral",
            VoiceEmotion.HAPPY: "cheerful",
            VoiceEmotion.SAD: "sad",
            VoiceEmotion.ANGRY: "angry",
            VoiceEmotion.FEARFUL: "fearful",
            VoiceEmotion.SURPRISED: "surprised",
            VoiceEmotion.WHISPER: "whispering",
            VoiceEmotion.SHOUTING: "shouting",
        }
        return mapping.get(emotion, "neutral")


# =============================================================================
# ELEVENLABS IMPLEMENTATION
# =============================================================================

class ElevenLabsTTSEngine(BaseTTSEngine):
    """
    TTS engine using ElevenLabs API.
    
    ElevenLabs provides high-quality, expressive voices with emotion control.
    It's the default provider for Continuum due to quality.
    
    Pricing (as of 2024):
        - ~$0.30 per 1000 characters (varies by plan)
    
    Attributes:
        api_key: ElevenLabs API key
        model_id: Which ElevenLabs model to use
    """
    
    provider = TTSProvider.ELEVENLABS
    
    # ElevenLabs model IDs
    MODEL_MULTILINGUAL_V2 = "eleven_multilingual_v2"
    MODEL_TURBO_V2 = "eleven_turbo_v2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/dialogue"),
        sample_rate: int = 44100,
        model_id: str = MODEL_MULTILINGUAL_V2,
    ):
        super().__init__(output_dir, sample_rate)
        
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise TTSConfigError("ElevenLabs API key not provided")
        
        self.model_id = model_id
        self._client = None  # Lazy init
    
    async def _get_client(self):
        """Lazy-initialize the ElevenLabs client."""
        if self._client is None:
            try:
                from elevenlabs.client import AsyncElevenLabs
                self._client = AsyncElevenLabs(api_key=self.api_key)
            except ImportError:
                raise TTSConfigError(
                    "elevenlabs package not installed. "
                    "Run: pip install elevenlabs"
                )
        return self._client
    
    async def synthesize(
        self,
        line: DialogueLine,
        voice_config: VoiceConfig,
    ) -> SynthesizedDialogue:
        """Synthesize dialogue using ElevenLabs."""
        start_time = time.time()
        output_path = self._generate_output_path(line)
        
        try:
            client = await self._get_client()
            
            # Determine emotion/style
            emotion = line.emotion or voice_config.default_emotion
            
            # Build voice settings
            voice_settings = {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.5 if emotion != VoiceEmotion.NEUTRAL else 0.0,
                "use_speaker_boost": True,
            }
            
            # Apply emotion modifiers
            if emotion == VoiceEmotion.WHISPER:
                voice_settings["stability"] = 0.8
                voice_settings["style"] = 0.2
            elif emotion == VoiceEmotion.SHOUTING:
                voice_settings["stability"] = 0.3
                voice_settings["style"] = 0.8
            
            # Generate audio
            logger.info(f"Synthesizing line {line.line_id}: '{line.text[:50]}...'")
            
            audio = await client.generate(
                text=line.text,
                voice=voice_config.voice_id,
                model=self.model_id,
                voice_settings=voice_settings,
            )
            
            # Save to file
            audio_bytes = b"".join([chunk async for chunk in audio])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            
            # Calculate duration (rough estimate: ElevenLabs returns MP3)
            # For accurate duration, we'd need to probe the file
            duration_sec = len(audio_bytes) / (self.sample_rate * 2)  # Rough estimate
            
            generation_time = time.time() - start_time
            logger.info(f"Synthesized {line.line_id} in {generation_time:.2f}s")
            
            return SynthesizedDialogue(
                line_id=line.line_id,
                audio_path=output_path,
                actual_duration_sec=duration_sec,
                sample_rate=self.sample_rate,
                status=AudioGenerationStatus.COMPLETE,
                generation_time_sec=generation_time,
            )
            
        except Exception as e:
            logger.error(f"ElevenLabs synthesis failed for {line.line_id}: {e}")
            return SynthesizedDialogue.failed(line.line_id, str(e))
    
    async def health_check(self) -> bool:
        """Check if ElevenLabs API is accessible."""
        try:
            client = await self._get_client()
            # Try to list voices as a health check
            voices = await client.voices.get_all()
            return len(voices.voices) > 0
        except Exception as e:
            logger.error(f"ElevenLabs health check failed: {e}")
            return False
    
    def estimate_cost(self, text: str) -> float:
        """Estimate cost in USD (~$0.30 per 1000 chars)."""
        char_count = len(text)
        return (char_count / 1000) * 0.30
    
    async def list_voices(self) -> List[Dict[str, Any]]:
        """List available ElevenLabs voices."""
        try:
            client = await self._get_client()
            response = await client.voices.get_all()
            return [
                {
                    "voice_id": voice.voice_id,
                    "name": voice.name,
                    "category": voice.category,
                    "labels": voice.labels,
                }
                for voice in response.voices
            ]
        except Exception as e:
            logger.error(f"Failed to list ElevenLabs voices: {e}")
            return []
    
    def supports_emotion(self, emotion: VoiceEmotion) -> bool:
        """ElevenLabs supports all emotions via style parameter."""
        return True


# =============================================================================
# OPENAI IMPLEMENTATION
# =============================================================================

class OpenAITTSEngine(BaseTTSEngine):
    """
    TTS engine using OpenAI's TTS API.
    
    OpenAI TTS is faster and cheaper than ElevenLabs but less expressive.
    Good for drafts or budget-conscious projects.
    
    Pricing (as of 2024):
        - $15.00 per 1M characters (~$0.015 per 1000 chars)
    
    Available voices: alloy, echo, fable, onyx, nova, shimmer
    """
    
    provider = TTSProvider.OPENAI
    
    # OpenAI voice options
    VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/dialogue"),
        sample_rate: int = 44100,
        model: str = "tts-1",  # or "tts-1-hd" for higher quality
    ):
        super().__init__(output_dir, sample_rate)
        
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise TTSConfigError("OpenAI API key not provided")
        
        self.model = model
        self._client = None
    
    async def _get_client(self):
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise TTSConfigError(
                    "openai package not installed. "
                    "Run: pip install openai"
                )
        return self._client
    
    async def synthesize(
        self,
        line: DialogueLine,
        voice_config: VoiceConfig,
    ) -> SynthesizedDialogue:
        """Synthesize dialogue using OpenAI TTS."""
        start_time = time.time()
        output_path = self._generate_output_path(line)
        
        try:
            client = await self._get_client()
            
            # OpenAI has limited voice options - map voice_id or use default
            voice = voice_config.voice_id if voice_config.voice_id in self.VOICES else "alloy"
            
            # Apply speed adjustment
            speed = voice_config.speaking_rate
            
            logger.info(f"Synthesizing line {line.line_id}: '{line.text[:50]}...'")
            
            response = await client.audio.speech.create(
                model=self.model,
                voice=voice,
                input=line.text,
                speed=speed,
                response_format="wav",
            )
            
            # Save to file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, "wb") as f:
                f.write(response.content)
            
            # Get actual duration by probing file (or estimate)
            duration_sec = line.estimated_duration_sec  # Use estimate for now
            
            generation_time = time.time() - start_time
            logger.info(f"Synthesized {line.line_id} in {generation_time:.2f}s")
            
            return SynthesizedDialogue(
                line_id=line.line_id,
                audio_path=output_path,
                actual_duration_sec=duration_sec,
                sample_rate=self.sample_rate,
                status=AudioGenerationStatus.COMPLETE,
                generation_time_sec=generation_time,
            )
            
        except Exception as e:
            logger.error(f"OpenAI TTS failed for {line.line_id}: {e}")
            return SynthesizedDialogue.failed(line.line_id, str(e))
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible."""
        try:
            client = await self._get_client()
            # Simple models list as health check
            models = await client.models.list()
            return True
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False
    
    def estimate_cost(self, text: str) -> float:
        """Estimate cost in USD (~$0.015 per 1000 chars)."""
        char_count = len(text)
        return (char_count / 1000) * 0.015
    
    async def list_voices(self) -> List[Dict[str, Any]]:
        """List available OpenAI voices (static list)."""
        return [
            {"voice_id": "alloy", "name": "Alloy", "description": "Neutral, balanced"},
            {"voice_id": "echo", "name": "Echo", "description": "Warm, conversational"},
            {"voice_id": "fable", "name": "Fable", "description": "Expressive, narrative"},
            {"voice_id": "onyx", "name": "Onyx", "description": "Deep, authoritative"},
            {"voice_id": "nova", "name": "Nova", "description": "Friendly, upbeat"},
            {"voice_id": "shimmer", "name": "Shimmer", "description": "Clear, professional"},
        ]
    
    def supports_emotion(self, emotion: VoiceEmotion) -> bool:
        """OpenAI TTS has limited emotion support."""
        # OpenAI doesn't have explicit emotion control
        return emotion == VoiceEmotion.NEUTRAL


# =============================================================================
# ENGINE REGISTRY
# =============================================================================

_tts_registry: Dict[TTSProvider, type] = {
    TTSProvider.ELEVENLABS: ElevenLabsTTSEngine,
    TTSProvider.OPENAI: OpenAITTSEngine,
}


def register_tts_engine(provider: TTSProvider):
    """
    Decorator to register a TTS engine class.
    
    Usage:
        @register_tts_engine(TTSProvider.LOCAL)
        class LocalTTSEngine(BaseTTSEngine):
            ...
    """
    def decorator(cls):
        _tts_registry[provider] = cls
        return cls
    return decorator


def get_tts_engine(
    provider: TTSProvider,
    **kwargs,
) -> BaseTTSEngine:
    """
    Get a TTS engine instance by provider.
    
    Args:
        provider: Which TTS provider to use
        **kwargs: Passed to engine constructor
        
    Returns:
        Instantiated TTS engine
        
    Raises:
        ValueError: If provider not registered
    """
    if provider not in _tts_registry:
        available = list(_tts_registry.keys())
        raise ValueError(
            f"TTS provider '{provider}' not registered. Available: {available}"
        )
    
    return _tts_registry[provider](**kwargs)


def list_tts_providers() -> List[TTSProvider]:
    """List all registered TTS providers."""
    return list(_tts_registry.keys())


# =============================================================================
# BATCH SYNTHESIS HELPER
# =============================================================================

async def synthesize_batch(
    engine: BaseTTSEngine,
    lines: List[DialogueLine],
    voice_configs: Dict[str, VoiceConfig],
    max_concurrent: int = 3,
) -> List[SynthesizedDialogue]:
    """
    Synthesize multiple dialogue lines with controlled concurrency.
    
    This helper prevents overwhelming the API with too many concurrent
    requests while still being faster than sequential processing.
    
    Args:
        engine: TTS engine to use
        lines: Lines to synthesize
        voice_configs: Mapping of character_id -> VoiceConfig
        max_concurrent: Maximum concurrent API calls
        
    Returns:
        List of SynthesizedDialogue results (same order as input)
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def synthesize_one(line: DialogueLine) -> SynthesizedDialogue:
        async with semaphore:
            voice_config = voice_configs.get(line.character_id)
            if not voice_config:
                return SynthesizedDialogue.failed(
                    line.line_id,
                    f"No voice config for character '{line.character_id}'"
                )
            return await engine.synthesize(line, voice_config)
    
    tasks = [synthesize_one(line) for line in lines]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to failed results
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append(SynthesizedDialogue.failed(
                lines[i].line_id,
                str(result)
            ))
        else:
            processed.append(result)
    
    return processed