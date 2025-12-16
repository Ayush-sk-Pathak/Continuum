"""
Continuum Engine - Ambience Generator

Generates background atmospheric audio using text-to-audio models.
Ambience runs continuously under dialogue and foley, providing the
sonic "bed" that grounds scenes in their environment.

Supported Providers:
    - Replicate: AudioLDM-2 via API (default)
    - Mock: For testing without API calls

Usage:
    engine = get_ambience_engine(AmbienceProvider.REPLICATE, api_token="...")
    result = await engine.generate(spec)

Design Principles:
    1. Provider abstraction: Swap AudioLDM for MusicGen or future models
    2. Async-first: API calls are I/O bound
    3. Loopable output: Generated audio should loop seamlessly when possible
    4. Scene-level generation: One ambience per scene (not per shot)
"""

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    AmbienceSpec,
    AmbienceType,
    AudioGenerationStatus,
    SynthesizedAmbience,
)


logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER ENUM (separate from TTSProvider)
# =============================================================================

class AmbienceProvider(Enum):
    """Supported ambience generation providers."""
    REPLICATE = auto()    # AudioLDM-2 via Replicate API (default)
    HUGGINGFACE = auto()  # HuggingFace Inference API (future)
    COMFYUI = auto()      # ComfyUI audio nodes (future)
    MOCK = auto()         # Mock for testing


# =============================================================================
# EXCEPTIONS
# =============================================================================

class AmbienceError(Exception):
    """Base exception for ambience generation errors."""
    def __init__(self, message: str, ambience_id: Optional[str] = None):
        super().__init__(message)
        self.ambience_id = ambience_id


class AmbienceConfigError(AmbienceError):
    """Invalid ambience configuration."""
    pass


class AmbienceAPIError(AmbienceError):
    """API call failed."""
    def __init__(self, message: str, ambience_id: Optional[str] = None,
                 status_code: Optional[int] = None):
        super().__init__(message, ambience_id)
        self.status_code = status_code


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseAmbienceEngine(ABC):
    """
    Abstract base class for ambience generation engines.
    
    All ambience providers must implement this interface. This enables
    hot-swapping between Replicate, HuggingFace, or local models.
    
    Attributes:
        provider: Which provider this engine uses
        output_dir: Where to save generated audio files
        sample_rate: Output sample rate (Hz)
    """
    
    provider: AmbienceProvider
    
    def __init__(
        self,
        output_dir: Path,
        sample_rate: int = 44100,
    ):
        """
        Initialize the ambience engine.
        
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
    async def generate(
        self,
        spec: AmbienceSpec,
    ) -> SynthesizedAmbience:
        """
        Generate ambient audio from a specification.
        
        This is the core method. Implementations should:
        1. Build a prompt from the AmbienceSpec
        2. Call the generation API
        3. Save audio to output_dir
        4. Return SynthesizedAmbience with path and metadata
        
        Args:
            spec: The ambience specification
            
        Returns:
            SynthesizedAmbience with path to audio file
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is available.
        
        Returns:
            True if API is reachable and authenticated
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, duration_sec: float) -> float:
        """
        Estimate cost to generate ambience in USD.
        
        Args:
            duration_sec: Duration of audio to generate
            
        Returns:
            Estimated cost in USD
        """
        pass
    
    # -------------------------------------------------------------------------
    # HELPER METHODS (Available to all subclasses)
    # -------------------------------------------------------------------------
    
    def _generate_output_path(self, spec: AmbienceSpec) -> Path:
        """
        Generate a unique output path for an ambience spec.
        
        Format: {output_dir}/{scene_id}_{ambience_id}.wav
        """
        filename = f"{spec.scene_id}_{spec.ambience_id}.wav"
        return self.output_dir / filename
    
    def _build_prompt(self, spec: AmbienceSpec) -> str:
        """
        Build a generation prompt from an AmbienceSpec.
        
        Combines the type hint with the natural language description
        to create an effective prompt for audio generation models.
        """
        # Type-based prefix for better results
        type_hints = {
            AmbienceType.SILENCE: "quiet room tone, subtle background",
            AmbienceType.INTERIOR_QUIET: "quiet indoor ambience",
            AmbienceType.INTERIOR_BUSY: "busy indoor environment",
            AmbienceType.EXTERIOR_URBAN: "city street ambience, urban sounds",
            AmbienceType.EXTERIOR_NATURE: "natural outdoor environment",
            AmbienceType.EXTERIOR_WEATHER: "weather sounds",
            AmbienceType.CROWD: "crowd ambience, many people",
            AmbienceType.INDUSTRIAL: "industrial environment, machinery",
        }
        
        prefix = type_hints.get(spec.type, "ambient background audio")
        
        # Combine with user description
        if spec.description:
            prompt = f"{prefix}, {spec.description}"
        else:
            prompt = prefix
        
        # Add quality hints
        prompt += ", high quality, seamless loop, no music, no voice"
        
        return prompt
    
    def _intensity_to_volume_db(self, intensity: float) -> float:
        """
        Convert intensity (0-1) to volume adjustment in dB.
        
        intensity=0.5 → 0 dB (reference)
        intensity=0.0 → -20 dB (very quiet)
        intensity=1.0 → +6 dB (prominent)
        """
        # Linear mapping: 0→-20dB, 0.5→0dB, 1.0→+6dB
        if intensity <= 0.5:
            return -20 + (intensity * 40)  # -20 to 0
        else:
            return (intensity - 0.5) * 12  # 0 to +6


# =============================================================================
# REPLICATE IMPLEMENTATION
# =============================================================================

class ReplicateAmbienceEngine(BaseAmbienceEngine):
    """
    Ambience engine using Replicate's AudioLDM-2 API.
    
    Replicate provides simple pay-per-use access to AudioLDM-2 without
    managing GPU infrastructure. Good fit for the "vibe coder" constraint.
    
    Pricing (as of 2024):
        - ~$0.02 per generation (varies by duration)
    
    Model: cjwbw/audioldm2-large
    """
    
    provider = AmbienceProvider.REPLICATE
    
    # Replicate model identifier
    MODEL_ID = "cjwbw/audioldm2-large:d7dec8be5c7dd257f3562ff7fcc1ee8339ff34e01f8e4af5fd574e0c65e4ba5e"
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/ambience"),
        sample_rate: int = 44100,
    ):
        super().__init__(output_dir, sample_rate)
        
        self.api_token = api_token or os.environ.get("REPLICATE_API_TOKEN")
        if not self.api_token:
            raise AmbienceConfigError("Replicate API token not provided")
        
        self._client = None
    
    async def _get_client(self):
        """Lazy-initialize the Replicate client."""
        if self._client is None:
            try:
                import replicate
                # Set token in environment for replicate library
                os.environ["REPLICATE_API_TOKEN"] = self.api_token
                self._client = replicate
            except ImportError:
                raise AmbienceConfigError(
                    "replicate package not installed. "
                    "Run: pip install replicate"
                )
        return self._client
    
    async def generate(
        self,
        spec: AmbienceSpec,
    ) -> SynthesizedAmbience:
        """Generate ambience using Replicate's AudioLDM-2."""
        start_time = time.time()
        output_path = self._generate_output_path(spec)
        
        try:
            client = await self._get_client()
            
            # Build prompt
            prompt = self._build_prompt(spec)
            
            logger.info(
                f"Generating ambience {spec.ambience_id}: '{prompt[:60]}...' "
                f"({spec.duration_sec}s)"
            )
            
            # Run the model
            # Note: Replicate's run() is synchronous, so we run in executor
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                lambda: client.run(
                    self.MODEL_ID,
                    input={
                        "prompt": prompt,
                        "duration": min(spec.duration_sec, 30.0),  # Max 30s per call
                        "guidance_scale": 3.5,
                        "num_inference_steps": 50,
                        "num_waveforms": 1,
                    }
                )
            )
            
            # Download the generated audio
            if output and len(output) > 0:
                audio_url = output[0] if isinstance(output, list) else output
                
                # Fetch the audio file
                import urllib.request
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                await loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlretrieve(audio_url, output_path)
                )
                
                generation_time = time.time() - start_time
                logger.info(
                    f"Generated ambience {spec.ambience_id} in {generation_time:.2f}s"
                )
                
                return SynthesizedAmbience(
                    ambience_id=spec.ambience_id,
                    audio_path=output_path,
                    actual_duration_sec=spec.duration_sec,
                    status=AudioGenerationStatus.COMPLETE,
                )
            else:
                return SynthesizedAmbience(
                    ambience_id=spec.ambience_id,
                    status=AudioGenerationStatus.FAILED,
                    error="No output returned from Replicate",
                )
                
        except Exception as e:
            logger.error(f"Replicate ambience generation failed: {e}")
            return SynthesizedAmbience(
                ambience_id=spec.ambience_id,
                status=AudioGenerationStatus.FAILED,
                error=str(e),
            )
    
    async def health_check(self) -> bool:
        """Check if Replicate API is accessible."""
        try:
            client = await self._get_client()
            # Simple check - try to get model info
            loop = asyncio.get_event_loop()
            model = await loop.run_in_executor(
                None,
                lambda: client.models.get("cjwbw/audioldm2-large")
            )
            return model is not None
        except Exception as e:
            logger.error(f"Replicate health check failed: {e}")
            return False
    
    def estimate_cost(self, duration_sec: float) -> float:
        """
        Estimate cost in USD.
        
        Replicate charges ~$0.00055/sec for AudioLDM-2 on A40.
        Rough estimate: $0.02 base + $0.001 per second.
        """
        return 0.02 + (duration_sec * 0.001)


# =============================================================================
# MOCK IMPLEMENTATION (for testing)
# =============================================================================

class MockAmbienceEngine(BaseAmbienceEngine):
    """
    Mock ambience engine for testing without API calls.
    
    Generates silent WAV files or copies from a test fixture directory.
    Useful for:
    - Unit tests
    - Integration tests without API costs
    - Offline development
    """
    
    provider = AmbienceProvider.MOCK
    
    def __init__(
        self,
        output_dir: Path = Path("./workspace/audio/ambience"),
        sample_rate: int = 44100,
        fixture_dir: Optional[Path] = None,
        simulate_delay_sec: float = 0.1,
    ):
        """
        Initialize mock engine.
        
        Args:
            output_dir: Where to save generated files
            sample_rate: Sample rate for generated silence
            fixture_dir: Optional directory with pre-made test audio
            simulate_delay_sec: Artificial delay to simulate API latency
        """
        super().__init__(output_dir, sample_rate)
        self.fixture_dir = fixture_dir
        self.simulate_delay_sec = simulate_delay_sec
    
    async def generate(
        self,
        spec: AmbienceSpec,
    ) -> SynthesizedAmbience:
        """Generate mock ambience (silent WAV or fixture)."""
        start_time = time.time()
        output_path = self._generate_output_path(spec)
        
        # Simulate API delay
        await asyncio.sleep(self.simulate_delay_sec)
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check for fixture file first
            if self.fixture_dir:
                fixture_path = self.fixture_dir / f"{spec.type.name.lower()}.wav"
                if fixture_path.exists():
                    import shutil
                    shutil.copy(fixture_path, output_path)
                    
                    return SynthesizedAmbience(
                        ambience_id=spec.ambience_id,
                        audio_path=output_path,
                        actual_duration_sec=spec.duration_sec,
                        status=AudioGenerationStatus.COMPLETE,
                    )
            
            # Generate silent WAV
            self._generate_silent_wav(output_path, spec.duration_sec)
            
            generation_time = time.time() - start_time
            logger.debug(
                f"Mock generated ambience {spec.ambience_id} in {generation_time:.2f}s"
            )
            
            return SynthesizedAmbience(
                ambience_id=spec.ambience_id,
                audio_path=output_path,
                actual_duration_sec=spec.duration_sec,
                status=AudioGenerationStatus.COMPLETE,
            )
            
        except Exception as e:
            logger.error(f"Mock ambience generation failed: {e}")
            return SynthesizedAmbience(
                ambience_id=spec.ambience_id,
                status=AudioGenerationStatus.FAILED,
                error=str(e),
            )
    
    async def health_check(self) -> bool:
        """Mock is always healthy."""
        return True
    
    def estimate_cost(self, duration_sec: float) -> float:
        """Mock costs nothing."""
        return 0.0
    
    def _generate_silent_wav(self, path: Path, duration_sec: float) -> None:
        """Generate a silent WAV file."""
        import struct
        import wave
        
        num_frames = int(self.sample_rate * duration_sec)
        
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(2)  # Stereo
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(self.sample_rate)
            
            # Write silence (zeros)
            silent_frame = struct.pack('<hh', 0, 0)  # Left=0, Right=0
            wav.writeframes(silent_frame * num_frames)


# =============================================================================
# ENGINE REGISTRY
# =============================================================================

_ambience_registry: Dict[AmbienceProvider, type] = {
    AmbienceProvider.REPLICATE: ReplicateAmbienceEngine,
    AmbienceProvider.MOCK: MockAmbienceEngine,
}


def register_ambience_engine(provider: AmbienceProvider):
    """
    Decorator to register an ambience engine class.
    
    Usage:
        @register_ambience_engine(AmbienceProvider.HUGGINGFACE)
        class HuggingFaceAmbienceEngine(BaseAmbienceEngine):
            ...
    """
    def decorator(cls):
        _ambience_registry[provider] = cls
        return cls
    return decorator


def get_ambience_engine(
    provider: AmbienceProvider,
    **kwargs,
) -> BaseAmbienceEngine:
    """
    Get an ambience engine instance by provider.
    
    Args:
        provider: Which provider to use
        **kwargs: Passed to engine constructor
        
    Returns:
        Instantiated ambience engine
        
    Raises:
        ValueError: If provider not registered
    """
    if provider not in _ambience_registry:
        available = list(_ambience_registry.keys())
        raise ValueError(
            f"Ambience provider '{provider}' not registered. Available: {available}"
        )
    
    return _ambience_registry[provider](**kwargs)


def list_ambience_providers() -> List[AmbienceProvider]:
    """List all registered ambience providers."""
    return list(_ambience_registry.keys())


# =============================================================================
# HELPER: GENERATE FOR SCENE
# =============================================================================

async def generate_scene_ambience(
    engine: BaseAmbienceEngine,
    specs: List[AmbienceSpec],
    max_concurrent: int = 2,
) -> List[SynthesizedAmbience]:
    """
    Generate ambience for multiple specs with controlled concurrency.
    
    Typically there's only one ambience per scene, but this handles
    cases where different shots have different atmospheres.
    
    Args:
        engine: Ambience engine to use
        specs: Ambience specifications to generate
        max_concurrent: Maximum concurrent API calls
        
    Returns:
        List of SynthesizedAmbience results (same order as input)
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def generate_one(spec: AmbienceSpec) -> SynthesizedAmbience:
        async with semaphore:
            return await engine.generate(spec)
    
    tasks = [generate_one(spec) for spec in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to failed results
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append(SynthesizedAmbience(
                ambience_id=specs[i].ambience_id,
                status=AudioGenerationStatus.FAILED,
                error=str(result),
            ))
        else:
            processed.append(result)
    
    return processed


# =============================================================================
# HELPER: LOOP AUDIO FOR DURATION
# =============================================================================

def extend_ambience_to_duration(
    audio_path: Path,
    target_duration_sec: float,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Extend ambience audio to a target duration by looping.
    
    AudioLDM-2 typically generates max 30 seconds. For longer scenes,
    we need to loop the audio seamlessly. This function uses FFmpeg
    to crossfade-loop the audio.
    
    Args:
        audio_path: Path to source audio
        target_duration_sec: Desired duration
        output_path: Where to save (default: overwrites source)
        
    Returns:
        Path to extended audio
        
    Note:
        This is a simple loop. For better results, use proper
        audio looping tools that find optimal loop points.
    """
    import subprocess
    
    if output_path is None:
        output_path = audio_path.with_suffix('.looped.wav')
    
    # Use FFmpeg to loop with crossfade
    # aloop loops the audio, then trim to target duration
    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1',  # Loop infinitely
        '-i', str(audio_path),
        '-t', str(target_duration_sec),  # Trim to target
        '-af', 'afade=t=out:st={:.2f}:d=0.5'.format(target_duration_sec - 0.5),
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg loop failed: {e.stderr.decode()}")
        raise AmbienceError(f"Failed to extend ambience: {e}")