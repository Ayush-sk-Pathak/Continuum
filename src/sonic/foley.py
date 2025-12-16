"""
Continuum Engine - Foley Engine

Retrieves or generates short, discrete sound effects (foley) for action events.
Unlike ambience (continuous) or TTS (speech), foley handles transient sounds:
footsteps, impacts, doors, object interactions.

Strategy: Library-First + Generation-Fallback
    1. Search sound library (Freesound) using semantic matching
    2. If good match found (score > threshold), download and cache
    3. If no match, fall back to AudioLDM-2 generation
    4. Cache all sounds locally to avoid repeated API calls

Supported Providers:
    - Freesound: 500k+ CC-licensed sounds (primary)
    - AudioLDM: Generation via Replicate (fallback)
    - Mock: For testing without API calls

Usage:
    engine = get_foley_engine(FoleyProvider.HYBRID, freesound_api_key="...")
    result = await engine.retrieve(event)

Architecture Alignment:
    - "CLAP for audio-text alignment" → Semantic search scoring
    - "Full foley library with event-driven triggers" → Freesound + cache
    - "Triggers discrete audio generation" → AudioLDM fallback
"""

import asyncio
import hashlib
import json
import logging
import os
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    AudioGenerationStatus,
    FoleyCategory,
    FoleyEvent,
    SynthesizedFoley,
)


logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER ENUM
# =============================================================================

class FoleyProvider(Enum):
    """Supported foley providers."""
    FREESOUND = auto()    # Library search (primary)
    AUDIOLDM = auto()     # Generation via Replicate (fallback)
    HYBRID = auto()       # Freesound + AudioLDM fallback (recommended)
    MOCK = auto()         # Mock for testing


# =============================================================================
# EXCEPTIONS
# =============================================================================

class FoleyError(Exception):
    """Base exception for foley errors."""
    def __init__(self, message: str, event_id: Optional[str] = None):
        super().__init__(message)
        self.event_id = event_id


class FoleyConfigError(FoleyError):
    """Invalid foley configuration."""
    pass


class FoleySearchError(FoleyError):
    """Sound library search failed."""
    pass


class FoleyDownloadError(FoleyError):
    """Failed to download sound from library."""
    pass


# =============================================================================
# SEARCH RESULT
# =============================================================================

@dataclass
class FoleyMatch:
    """
    A potential match from the sound library.
    
    Attributes:
        sound_id: Provider-specific identifier
        name: Human-readable name
        description: Sound description
        duration_sec: Duration of the sound
        score: Relevance score (0.0-1.0)
        preview_url: URL to preview/download
        license: License type (e.g., "CC-BY", "CC0")
        source: Provider name
    """
    sound_id: str
    name: str
    description: str
    duration_sec: float
    score: float
    preview_url: str
    license: str = "unknown"
    source: str = "freesound"
    
    @property
    def is_good_match(self) -> bool:
        """Check if this is a good enough match (score > 0.7)."""
        return self.score >= 0.7


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseFoleyEngine(ABC):
    """
    Abstract base class for foley engines.
    
    All foley providers must implement this interface. The key method
    is retrieve(), which gets a sound for a FoleyEvent.
    
    Attributes:
        output_dir: Where to save/cache audio files
        cache_dir: Where to cache downloaded library sounds
        sample_rate: Output sample rate (Hz)
    """
    
    provider: FoleyProvider
    
    def __init__(
        self,
        output_dir: Path,
        cache_dir: Optional[Path] = None,
        sample_rate: int = 44100,
    ):
        """
        Initialize the foley engine.
        
        Args:
            output_dir: Directory to save generated/downloaded audio
            cache_dir: Directory to cache library sounds (default: output_dir/cache)
            sample_rate: Output sample rate in Hz
        """
        self.output_dir = Path(output_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else self.output_dir / "cache"
        self.sample_rate = sample_rate
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # ABSTRACT METHODS
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def retrieve(
        self,
        event: FoleyEvent,
    ) -> SynthesizedFoley:
        """
        Retrieve or generate a sound for a foley event.
        
        This is the core method. Implementations should:
        1. Search for matching sounds (if library-based)
        2. Download/generate the sound
        3. Cache for future use
        4. Return SynthesizedFoley with path
        
        Args:
            event: The foley event specification
            
        Returns:
            SynthesizedFoley with path to audio file
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[FoleyMatch]:
        """
        Search for sounds matching a query.
        
        Args:
            query: Natural language description
            max_results: Maximum results to return
            
        Returns:
            List of FoleyMatch results, sorted by score
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is available.
        
        Returns:
            True if API is reachable
        """
        pass
    
    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------
    
    def _generate_output_path(self, event: FoleyEvent) -> Path:
        """Generate output path for a foley event."""
        filename = f"{event.scene_id}_{event.shot_id}_{event.event_id}.wav"
        return self.output_dir / filename
    
    def _get_cache_path(self, sound_id: str, source: str) -> Path:
        """Get cache path for a library sound."""
        # Use hash to avoid filesystem issues with weird IDs
        cache_key = hashlib.md5(f"{source}:{sound_id}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{source}_{cache_key}.wav"
    
    def _is_cached(self, sound_id: str, source: str) -> Optional[Path]:
        """Check if a sound is already cached, return path if so."""
        cache_path = self._get_cache_path(sound_id, source)
        return cache_path if cache_path.exists() else None
    
    def _build_search_query(self, event: FoleyEvent) -> str:
        """
        Build an effective search query from a FoleyEvent.
        
        Combines category hints with the natural language description.
        """
        # Category-based prefixes for better search results
        category_hints = {
            FoleyCategory.FOOTSTEPS: "footstep footsteps walking",
            FoleyCategory.DOOR: "door creak slam close open",
            FoleyCategory.IMPACT: "impact hit punch crash",
            FoleyCategory.OBJECT: "object handling pickup putdown",
            FoleyCategory.CLOTH: "cloth fabric rustling movement",
            FoleyCategory.LIQUID: "liquid water pour splash drip",
            FoleyCategory.ELECTRONIC: "electronic beep buzz notification ui",
            FoleyCategory.VEHICLE: "vehicle car engine motor",
            FoleyCategory.NATURE: "nature animal bird wind",
            FoleyCategory.CUSTOM: "",
        }
        
        hint = category_hints.get(event.category, "")
        
        # Combine hint with description
        if hint and event.description:
            return f"{hint} {event.description}"
        elif event.description:
            return event.description
        else:
            return hint or "sound effect"


# =============================================================================
# FREESOUND IMPLEMENTATION
# =============================================================================

class FreesoundFoleyEngine(BaseFoleyEngine):
    """
    Foley engine using Freesound.org API.
    
    Freesound is a collaborative database of CC-licensed sounds.
    500k+ sounds available, free API with rate limits.
    
    API Limits:
        - 60 requests/minute for search
        - Downloads require OAuth or API key
    
    Attributes:
        api_key: Freesound API key
        min_score: Minimum relevance score to accept (0.0-1.0)
    """
    
    provider = FoleyProvider.FREESOUND
    
    API_BASE = "https://freesound.org/apiv2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/foley"),
        cache_dir: Optional[Path] = None,
        sample_rate: int = 44100,
        min_score: float = 0.5,
    ):
        super().__init__(output_dir, cache_dir, sample_rate)
        
        self.api_key = api_key or os.environ.get("FREESOUND_API_KEY")
        if not self.api_key:
            raise FoleyConfigError("Freesound API key not provided")
        
        self.min_score = min_score
    
    async def retrieve(
        self,
        event: FoleyEvent,
    ) -> SynthesizedFoley:
        """Retrieve a sound from Freesound for the event."""
        output_path = self._generate_output_path(event)
        
        try:
            # Build search query
            query = self._build_search_query(event)
            
            # Search for matches
            matches = await self.search(query, max_results=5)
            
            if not matches:
                logger.warning(f"No sounds found for '{query}'")
                return SynthesizedFoley(
                    event_id=event.event_id,
                    status=AudioGenerationStatus.FAILED,
                    error=f"No sounds found for: {query}",
                )
            
            # Find best match above threshold
            best_match = None
            for match in matches:
                if match.score >= self.min_score:
                    best_match = match
                    break
            
            if not best_match:
                logger.warning(f"No good matches for '{query}' (best: {matches[0].score:.2f})")
                return SynthesizedFoley(
                    event_id=event.event_id,
                    status=AudioGenerationStatus.FAILED,
                    error=f"No matches above threshold {self.min_score}",
                )
            
            # Check cache first
            cached = self._is_cached(best_match.sound_id, "freesound")
            if cached:
                logger.info(f"Using cached sound for {event.event_id}")
                # Copy from cache to output
                import shutil
                shutil.copy(cached, output_path)
                
                return SynthesizedFoley(
                    event_id=event.event_id,
                    audio_path=output_path,
                    source="library:freesound:cached",
                    actual_duration_sec=best_match.duration_sec,
                    status=AudioGenerationStatus.COMPLETE,
                )
            
            # Download the sound
            await self._download_sound(best_match, output_path)
            
            # Also save to cache
            cache_path = self._get_cache_path(best_match.sound_id, "freesound")
            import shutil
            shutil.copy(output_path, cache_path)
            
            logger.info(f"Retrieved foley for {event.event_id}: {best_match.name}")
            
            return SynthesizedFoley(
                event_id=event.event_id,
                audio_path=output_path,
                source="library:freesound",
                actual_duration_sec=best_match.duration_sec,
                status=AudioGenerationStatus.COMPLETE,
            )
            
        except Exception as e:
            logger.error(f"Freesound retrieval failed for {event.event_id}: {e}")
            return SynthesizedFoley(
                event_id=event.event_id,
                status=AudioGenerationStatus.FAILED,
                error=str(e),
            )
    
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[FoleyMatch]:
        """Search Freesound for matching sounds."""
        try:
            # Build API URL
            import urllib.parse
            params = urllib.parse.urlencode({
                "query": query,
                "token": self.api_key,
                "fields": "id,name,description,duration,previews,license,avg_rating,num_ratings",
                "page_size": max_results,
                "sort": "score",
            })
            url = f"{self.API_BASE}/search/text/?{params}"
            
            # Make request
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(url, timeout=10)
            )
            data = json.loads(response.read().decode())
            
            # Parse results
            matches = []
            for i, result in enumerate(data.get("results", [])):
                # Calculate relevance score based on position and ratings
                position_score = 1.0 - (i / max_results) * 0.3
                rating = result.get("avg_rating", 3.0) / 5.0
                num_ratings = min(result.get("num_ratings", 0), 100) / 100
                
                # Weighted score: position matters most, then quality
                score = position_score * 0.6 + rating * 0.3 + num_ratings * 0.1
                
                # Get preview URL (prefer HQ)
                previews = result.get("previews", {})
                preview_url = (
                    previews.get("preview-hq-mp3") or
                    previews.get("preview-lq-mp3") or
                    ""
                )
                
                matches.append(FoleyMatch(
                    sound_id=str(result["id"]),
                    name=result.get("name", "Unknown"),
                    description=result.get("description", "")[:200],
                    duration_sec=result.get("duration", 0.0),
                    score=score,
                    preview_url=preview_url,
                    license=result.get("license", "unknown"),
                    source="freesound",
                ))
            
            return matches
            
        except Exception as e:
            logger.error(f"Freesound search failed: {e}")
            return []
    
    async def _download_sound(self, match: FoleyMatch, output_path: Path) -> None:
        """Download a sound from Freesound."""
        if not match.preview_url:
            raise FoleyDownloadError(f"No preview URL for sound {match.sound_id}")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: urllib.request.urlretrieve(match.preview_url, output_path)
        )
    
    async def health_check(self) -> bool:
        """Check if Freesound API is accessible."""
        try:
            results = await self.search("test", max_results=1)
            return True
        except Exception as e:
            logger.error(f"Freesound health check failed: {e}")
            return False


# =============================================================================
# AUDIOLDM IMPLEMENTATION (GENERATION FALLBACK)
# =============================================================================

class AudioLDMFoleyEngine(BaseFoleyEngine):
    """
    Foley engine using AudioLDM-2 via Replicate.
    
    Used as fallback when sound library doesn't have a good match.
    Better for unusual or specific sounds not in typical libraries.
    
    Note: AudioLDM is optimized for ambience, not short transients.
    Results may need manual review for quality.
    """
    
    provider = FoleyProvider.AUDIOLDM
    
    MODEL_ID = "cjwbw/audioldm2-large:d7dec8be5c7dd257f3562ff7fcc1ee8339ff34e01f8e4af5fd574e0c65e4ba5e"
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/foley"),
        cache_dir: Optional[Path] = None,
        sample_rate: int = 44100,
    ):
        super().__init__(output_dir, cache_dir, sample_rate)
        
        self.api_token = api_token or os.environ.get("REPLICATE_API_TOKEN")
        if not self.api_token:
            raise FoleyConfigError("Replicate API token not provided")
        
        self._client = None
    
    async def _get_client(self):
        """Lazy-initialize Replicate client."""
        if self._client is None:
            try:
                import replicate
                os.environ["REPLICATE_API_TOKEN"] = self.api_token
                self._client = replicate
            except ImportError:
                raise FoleyConfigError(
                    "replicate package not installed. "
                    "Run: pip install replicate"
                )
        return self._client
    
    async def retrieve(
        self,
        event: FoleyEvent,
    ) -> SynthesizedFoley:
        """Generate a sound using AudioLDM-2."""
        start_time = time.time()
        output_path = self._generate_output_path(event)
        
        try:
            client = await self._get_client()
            
            # Build prompt optimized for short sounds
            prompt = self._build_generation_prompt(event)
            
            logger.info(f"Generating foley for {event.event_id}: '{prompt[:50]}...'")
            
            # Generate audio
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                lambda: client.run(
                    self.MODEL_ID,
                    input={
                        "prompt": prompt,
                        "duration": min(event.duration_sec, 5.0),  # Short sounds
                        "guidance_scale": 4.0,  # Higher guidance for precision
                        "num_inference_steps": 50,
                        "num_waveforms": 1,
                    }
                )
            )
            
            # Download result
            if output and len(output) > 0:
                audio_url = output[0] if isinstance(output, list) else output
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                await loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlretrieve(audio_url, output_path)
                )
                
                generation_time = time.time() - start_time
                logger.info(f"Generated foley {event.event_id} in {generation_time:.2f}s")
                
                return SynthesizedFoley(
                    event_id=event.event_id,
                    audio_path=output_path,
                    source="generated:audioldm",
                    actual_duration_sec=event.duration_sec,
                    status=AudioGenerationStatus.COMPLETE,
                )
            else:
                return SynthesizedFoley(
                    event_id=event.event_id,
                    status=AudioGenerationStatus.FAILED,
                    error="No output from AudioLDM",
                )
                
        except Exception as e:
            logger.error(f"AudioLDM foley generation failed: {e}")
            return SynthesizedFoley(
                event_id=event.event_id,
                status=AudioGenerationStatus.FAILED,
                error=str(e),
            )
    
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[FoleyMatch]:
        """Generation engine doesn't support search."""
        return []
    
    async def health_check(self) -> bool:
        """Check if Replicate is accessible."""
        try:
            client = await self._get_client()
            return True
        except Exception as e:
            logger.error(f"Replicate health check failed: {e}")
            return False
    
    def _build_generation_prompt(self, event: FoleyEvent) -> str:
        """Build a generation prompt optimized for short discrete sounds."""
        # Category-specific prompts that work better with AudioLDM
        category_templates = {
            FoleyCategory.FOOTSTEPS: "single footstep sound, {desc}, isolated, clean recording",
            FoleyCategory.DOOR: "door sound effect, {desc}, single instance, no reverb",
            FoleyCategory.IMPACT: "impact sound, {desc}, sharp transient, isolated",
            FoleyCategory.OBJECT: "object sound, {desc}, close microphone, clean",
            FoleyCategory.CLOTH: "cloth movement, {desc}, subtle, foley recording",
            FoleyCategory.LIQUID: "liquid sound, {desc}, close recording",
            FoleyCategory.ELECTRONIC: "electronic sound, {desc}, digital, clean",
            FoleyCategory.VEHICLE: "vehicle sound, {desc}, recording",
            FoleyCategory.NATURE: "nature sound, {desc}, field recording",
            FoleyCategory.CUSTOM: "{desc}, sound effect, isolated, clean",
        }
        
        template = category_templates.get(event.category, "{desc}, sound effect")
        return template.format(desc=event.description)


# =============================================================================
# HYBRID IMPLEMENTATION (RECOMMENDED)
# =============================================================================

class HybridFoleyEngine(BaseFoleyEngine):
    """
    Hybrid foley engine: library-first with generation fallback.
    
    This is the recommended engine for production use. It:
    1. Searches Freesound for matching sounds
    2. If good match found (score > threshold), uses library sound
    3. If no match, falls back to AudioLDM generation
    4. Caches all sounds for future use
    
    Attributes:
        library_engine: Engine for library search (Freesound)
        generation_engine: Engine for fallback generation (AudioLDM)
        min_library_score: Minimum score to accept library match
    """
    
    provider = FoleyProvider.HYBRID
    
    def __init__(
        self,
        freesound_api_key: Optional[str] = None,
        replicate_api_token: Optional[str] = None,
        output_dir: Path = Path("./workspace/audio/foley"),
        cache_dir: Optional[Path] = None,
        sample_rate: int = 44100,
        min_library_score: float = 0.6,
    ):
        super().__init__(output_dir, cache_dir, sample_rate)
        
        self.min_library_score = min_library_score
        
        # Initialize sub-engines
        # Library engine is required
        self.library_engine = FreesoundFoleyEngine(
            api_key=freesound_api_key,
            output_dir=output_dir,
            cache_dir=cache_dir,
            sample_rate=sample_rate,
            min_score=min_library_score,
        )
        
        # Generation engine is optional (fallback)
        self.generation_engine: Optional[AudioLDMFoleyEngine] = None
        if replicate_api_token or os.environ.get("REPLICATE_API_TOKEN"):
            try:
                self.generation_engine = AudioLDMFoleyEngine(
                    api_token=replicate_api_token,
                    output_dir=output_dir,
                    cache_dir=cache_dir,
                    sample_rate=sample_rate,
                )
            except FoleyConfigError:
                logger.warning("Replicate not configured, generation fallback disabled")
    
    async def retrieve(
        self,
        event: FoleyEvent,
    ) -> SynthesizedFoley:
        """Retrieve from library or generate as fallback."""
        # Try library first
        logger.info(f"Searching library for {event.event_id}: '{event.description}'")
        result = await self.library_engine.retrieve(event)
        
        if result.status == AudioGenerationStatus.COMPLETE:
            return result
        
        # Library failed, try generation
        if self.generation_engine:
            logger.info(f"Library miss, falling back to generation for {event.event_id}")
            return await self.generation_engine.retrieve(event)
        
        # No fallback available
        logger.warning(f"No library match and no generation fallback for {event.event_id}")
        return SynthesizedFoley(
            event_id=event.event_id,
            status=AudioGenerationStatus.FAILED,
            error="No library match and generation fallback not available",
        )
    
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[FoleyMatch]:
        """Search the library."""
        return await self.library_engine.search(query, max_results)
    
    async def health_check(self) -> bool:
        """Check if at least one engine is healthy."""
        library_ok = await self.library_engine.health_check()
        generation_ok = (
            await self.generation_engine.health_check()
            if self.generation_engine else False
        )
        return library_ok or generation_ok


# =============================================================================
# MOCK IMPLEMENTATION
# =============================================================================

class MockFoleyEngine(BaseFoleyEngine):
    """
    Mock foley engine for testing.
    
    Returns predefined results or generates silent audio.
    """
    
    provider = FoleyProvider.MOCK
    
    def __init__(
        self,
        output_dir: Path = Path("./workspace/audio/foley"),
        cache_dir: Optional[Path] = None,
        sample_rate: int = 44100,
        simulate_delay_sec: float = 0.1,
    ):
        super().__init__(output_dir, cache_dir, sample_rate)
        self.simulate_delay_sec = simulate_delay_sec
    
    async def retrieve(
        self,
        event: FoleyEvent,
    ) -> SynthesizedFoley:
        """Generate mock foley (silent audio)."""
        await asyncio.sleep(self.simulate_delay_sec)
        
        output_path = self._generate_output_path(event)
        self._generate_silent_wav(output_path, event.duration_sec)
        
        return SynthesizedFoley(
            event_id=event.event_id,
            audio_path=output_path,
            source="mock",
            actual_duration_sec=event.duration_sec,
            status=AudioGenerationStatus.COMPLETE,
        )
    
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[FoleyMatch]:
        """Return mock search results."""
        return [
            FoleyMatch(
                sound_id=f"mock_{i}",
                name=f"Mock Sound {i}",
                description=f"Mock result for: {query}",
                duration_sec=1.0,
                score=0.9 - (i * 0.1),
                preview_url="",
                source="mock",
            )
            for i in range(min(max_results, 3))
        ]
    
    async def health_check(self) -> bool:
        """Mock is always healthy."""
        return True
    
    def _generate_silent_wav(self, path: Path, duration_sec: float) -> None:
        """Generate a silent WAV file."""
        import struct
        import wave
        
        num_frames = int(self.sample_rate * duration_sec)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            silent_frame = struct.pack('<hh', 0, 0)
            wav.writeframes(silent_frame * num_frames)


# =============================================================================
# ENGINE REGISTRY
# =============================================================================

_foley_registry: Dict[FoleyProvider, type] = {
    FoleyProvider.FREESOUND: FreesoundFoleyEngine,
    FoleyProvider.AUDIOLDM: AudioLDMFoleyEngine,
    FoleyProvider.HYBRID: HybridFoleyEngine,
    FoleyProvider.MOCK: MockFoleyEngine,
}


def register_foley_engine(provider: FoleyProvider):
    """Decorator to register a foley engine class."""
    def decorator(cls):
        _foley_registry[provider] = cls
        return cls
    return decorator


def get_foley_engine(
    provider: FoleyProvider,
    **kwargs,
) -> BaseFoleyEngine:
    """
    Get a foley engine instance by provider.
    
    Args:
        provider: Which provider to use
        **kwargs: Passed to engine constructor
        
    Returns:
        Instantiated foley engine
        
    Raises:
        ValueError: If provider not registered
    """
    if provider not in _foley_registry:
        available = list(_foley_registry.keys())
        raise ValueError(
            f"Foley provider '{provider}' not registered. Available: {available}"
        )
    
    return _foley_registry[provider](**kwargs)


def list_foley_providers() -> List[FoleyProvider]:
    """List all registered foley providers."""
    return list(_foley_registry.keys())


# =============================================================================
# BATCH HELPER
# =============================================================================

async def retrieve_batch(
    engine: BaseFoleyEngine,
    events: List[FoleyEvent],
    max_concurrent: int = 3,
) -> List[SynthesizedFoley]:
    """
    Retrieve foley for multiple events with controlled concurrency.
    
    Args:
        engine: Foley engine to use
        events: Events to process
        max_concurrent: Maximum concurrent operations
        
    Returns:
        List of SynthesizedFoley results (same order as input)
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def retrieve_one(event: FoleyEvent) -> SynthesizedFoley:
        async with semaphore:
            return await engine.retrieve(event)
    
    tasks = [retrieve_one(event) for event in events]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append(SynthesizedFoley(
                event_id=events[i].event_id,
                status=AudioGenerationStatus.FAILED,
                error=str(result),
            ))
        else:
            processed.append(result)
    
    return processed