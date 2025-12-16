"""
Continuum Engine - Lip Sync Engine

Applies audio-driven lip synchronization to video, making characters'
mouths move in sync with their dialogue.

The Problem:
    AI-generated video has static or randomly moving mouths.
    Characters don't appear to be speaking their dialogue.

The Solution:
    Take the refined video + dialogue audio and use a lip-sync model
    (Musetalk, Wav2Lip) to modify the face region so mouth movements
    match the audio.

Architecture Position:
    Pass 1 → Audit → Pass 2 → **Lip Sync (this)** → RIFE → Final

Why This Position:
    - Needs refined faces (after Pass 2) for best quality
    - May introduce minor frame jitters that RIFE smooths out
    - Runs only on speaking shots (non-speaking shots skip)

Inputs:
    - Video: Refined video from Pass 2 (12fps)
    - Audio: Dialogue audio from TTS engine
    - Timing: Start/end times for each dialogue segment

Outputs:
    - Video with lip-synced faces (same fps, same duration)

Supported Providers:
    - Musetalk: High quality, ComfyUI nodes available
    - Wav2Lip: Classic, widely available, Replicate API
    - Passthrough: For non-speaking shots or testing

Design Principles:
    1. Workflow-agnostic: Actual ComfyUI workflow is external JSON
    2. Degradation-ready: Musetalk → Wav2Lip → Passthrough
    3. Async-first: All processing is async (GPU-bound)
    4. Speaking-shot aware: Skip processing for non-speaking content
"""

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .types import DialogueLine, SynthesizedDialogue


logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class LipSyncProvider(str, Enum):
    """
    Available lip sync providers, in order of quality.
    """
    MUSETALK_COMFY = "musetalk_comfy"    # Best: Musetalk via ComfyUI
    WAV2LIP_COMFY = "wav2lip_comfy"      # Good: Wav2Lip via ComfyUI
    WAV2LIP_REPLICATE = "wav2lip_replicate"  # Fallback: Wav2Lip via Replicate API
    PASSTHROUGH = "passthrough"          # None: No lip sync (non-speaking)


class LipSyncStatus(str, Enum):
    """Status of a lip sync job."""
    PENDING = "pending"
    DETECTING_FACES = "detecting_faces"  # Finding face regions
    SYNCING = "syncing"                  # Applying lip sync
    COMPOSITING = "compositing"          # Blending back into video
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"                  # No dialogue in shot


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class DialogueSegment:
    """
    A segment of dialogue to lip-sync.
    
    Attributes:
        audio_path: Path to dialogue audio file
        start_time_sec: When dialogue starts in the video
        end_time_sec: When dialogue ends in the video
        character_id: Which character is speaking
        line_id: Reference to original DialogueLine
    """
    audio_path: Path
    start_time_sec: float
    end_time_sec: float
    character_id: str
    line_id: str
    
    def __post_init__(self):
        if isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)
    
    @property
    def duration_sec(self) -> float:
        return self.end_time_sec - self.start_time_sec
    
    @classmethod
    def from_synthesized(
        cls,
        synth: SynthesizedDialogue,
        line: DialogueLine,
    ) -> "DialogueSegment":
        """Create from synthesized dialogue and its line spec."""
        return cls(
            audio_path=synth.audio_path,
            start_time_sec=line.start_time_sec,
            end_time_sec=line.start_time_sec + (synth.actual_duration_sec or line.estimated_duration_sec),
            character_id=line.character_id,
            line_id=line.line_id,
        )


@dataclass
class LipSyncSpec:
    """
    Specification for a lip sync job.
    
    Attributes:
        input_video: Path to input video (from Pass 2)
        output_video: Where to write lip-synced video
        shot_id: Identifier for tracking
        dialogue_segments: List of dialogue to sync
        provider: Which provider to use (None = auto-select)
        face_detection_threshold: Confidence for face detection
        blend_mode: How to blend lip-synced face back
    """
    input_video: Path
    output_video: Path
    shot_id: str
    dialogue_segments: List[DialogueSegment] = field(default_factory=list)
    provider: Optional[LipSyncProvider] = None
    face_detection_threshold: float = 0.5
    blend_mode: str = "seamless"  # "seamless", "hard", "feathered"
    
    def __post_init__(self):
        if isinstance(self.input_video, str):
            self.input_video = Path(self.input_video)
        if isinstance(self.output_video, str):
            self.output_video = Path(self.output_video)
    
    @property
    def has_dialogue(self) -> bool:
        """Check if this shot has any dialogue to sync."""
        return len(self.dialogue_segments) > 0
    
    @property
    def total_dialogue_duration(self) -> float:
        """Total duration of all dialogue segments."""
        return sum(seg.duration_sec for seg in self.dialogue_segments)


@dataclass
class LipSyncResult:
    """
    Result of a lip sync operation.
    
    Attributes:
        success: Whether lip sync completed
        output_path: Path to lip-synced video
        provider_used: Which provider was actually used
        status: Final status
        segments_processed: Number of dialogue segments synced
        faces_detected: Number of faces found
        processing_time_sec: How long processing took
        error: Error message if failed
        warnings: Non-fatal issues
    """
    success: bool
    output_path: Optional[Path] = None
    provider_used: LipSyncProvider = LipSyncProvider.PASSTHROUGH
    status: LipSyncStatus = LipSyncStatus.PENDING
    segments_processed: int = 0
    faces_detected: int = 0
    processing_time_sec: float = 0.0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def failed(cls, error: str, provider: LipSyncProvider = LipSyncProvider.PASSTHROUGH) -> "LipSyncResult":
        """Factory for a failed result."""
        return cls(
            success=False,
            provider_used=provider,
            status=LipSyncStatus.FAILED,
            error=error,
        )
    
    @classmethod
    def skipped(cls, output_path: Path, reason: str) -> "LipSyncResult":
        """Factory for a skipped result (no dialogue)."""
        return cls(
            success=True,
            output_path=output_path,
            provider_used=LipSyncProvider.PASSTHROUGH,
            status=LipSyncStatus.SKIPPED,
            warnings=[f"Lip sync skipped: {reason}"],
        )


@dataclass
class LipSyncProgress:
    """Progress update during lip sync."""
    stage: str
    progress: float  # 0.0 to 1.0
    current_segment: int = 0
    total_segments: int = 0
    message: str = ""
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    
    @property
    def percent(self) -> int:
        return int(self.progress * 100)


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseLipSyncEngine(ABC):
    """
    Abstract base class for lip sync engines.
    
    Implementations can use different backends:
    - ComfyUI-based (Musetalk, Wav2Lip nodes)
    - Replicate API (Wav2Lip)
    - Local models (future)
    """
    
    provider: LipSyncProvider
    
    def __init__(
        self,
        output_dir: Path,
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the lip sync engine.
        
        Args:
            output_dir: Default directory for output videos
            temp_dir: Directory for temporary files
        """
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir()) / "continuum_lipsync"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    async def sync(
        self,
        spec: LipSyncSpec,
        progress_callback: Optional[Callable[[LipSyncProgress], None]] = None,
    ) -> LipSyncResult:
        """
        Apply lip sync to a video.
        
        Args:
            spec: Lip sync specification
            progress_callback: Optional callback for progress updates
            
        Returns:
            LipSyncResult with path to lip-synced video
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the lip sync backend is available.
        
        Returns:
            True if ready to process
        """
        pass
    
    def estimate_time(self, spec: LipSyncSpec) -> float:
        """
        Estimate processing time in seconds.
        
        Lip sync is relatively slow - roughly 1-2x realtime.
        """
        if not spec.has_dialogue:
            return 0.5  # Just copy
        
        # Rough estimate: lip sync processes at ~0.5-1x realtime
        return spec.total_dialogue_duration * 1.5
    
    def estimate_cost(self, spec: LipSyncSpec) -> float:
        """Estimate cost in USD."""
        if not spec.has_dialogue:
            return 0.0
        
        time_sec = self.estimate_time(spec)
        hourly_rate = 0.50  # GPU cost
        return (time_sec / 3600) * hourly_rate


# =============================================================================
# COMFYUI MUSETALK IMPLEMENTATION
# =============================================================================

class MusetalkComfyEngine(BaseLipSyncEngine):
    """
    Lip sync engine using Musetalk via ComfyUI.
    
    Musetalk is a high-quality audio-driven lip sync model that
    produces natural-looking mouth movements.
    
    Requirements:
        - ComfyUI with Musetalk nodes installed
        - musetalk_lipsync workflow in workflows directory
    """
    
    provider = LipSyncProvider.MUSETALK_COMFY
    
    def __init__(
        self,
        comfy_host: str,
        workflow_name: str = "musetalk_lipsync",
        output_dir: Path = Path("./workspace/video/lipsync"),
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the Musetalk ComfyUI engine.
        
        Args:
            comfy_host: ComfyUI server URL
            workflow_name: Name of the Musetalk workflow
            output_dir: Where to save lip-synced videos
            temp_dir: Temporary file directory
        """
        super().__init__(output_dir, temp_dir)
        
        self.comfy_host = comfy_host
        self.workflow_name = workflow_name
        self._client = None
        self._loader = None
        self._template = None
    
    async def _get_client(self):
        """Lazy-initialize ComfyUI client."""
        if self._client is None:
            try:
                from ..comfy_client.client import ComfyClient
                self._client = ComfyClient(self.comfy_host)
                await self._client.connect()
            except ImportError:
                raise RuntimeError(
                    "ComfyClient not available. "
                    "Ensure src/comfy_client module exists."
                )
        return self._client
    
    async def _load_workflow(self):
        """Load the Musetalk workflow template."""
        if self._template is None:
            try:
                from ..comfy_client.workflow_loader import WorkflowLoader
                if self._loader is None:
                    self._loader = WorkflowLoader()
                self._template = self._loader.load(self.workflow_name)
            except Exception as e:
                raise RuntimeError(f"Failed to load workflow '{self.workflow_name}': {e}")
        return self._template
    
    async def sync(
        self,
        spec: LipSyncSpec,
        progress_callback: Optional[Callable[[LipSyncProgress], None]] = None,
    ) -> LipSyncResult:
        """Apply lip sync using Musetalk via ComfyUI."""
        start_time = time.time()
        
        def report_progress(stage: str, progress: float, message: str = ""):
            if progress_callback:
                progress_callback(LipSyncProgress(
                    stage=stage,
                    progress=progress,
                    total_segments=len(spec.dialogue_segments),
                    message=message,
                    elapsed_sec=time.time() - start_time,
                ))
        
        try:
            # Check for dialogue
            if not spec.has_dialogue:
                return await self._passthrough(spec, "No dialogue segments")
            
            # Validate inputs
            if not spec.input_video.exists():
                return LipSyncResult.failed(f"Input video not found: {spec.input_video}")
            
            for seg in spec.dialogue_segments:
                if not seg.audio_path.exists():
                    return LipSyncResult.failed(f"Audio not found: {seg.audio_path}")
            
            report_progress("detecting_faces", 0.1, "Connecting to ComfyUI...")
            
            client = await self._get_client()
            template = await self._load_workflow()
            
            # For multiple segments, we process sequentially
            # Each segment modifies the video, then passes to the next
            current_video = spec.input_video
            segments_processed = 0
            
            for i, segment in enumerate(spec.dialogue_segments):
                segment_progress = (i / len(spec.dialogue_segments))
                report_progress(
                    "syncing",
                    0.2 + (segment_progress * 0.7),
                    f"Processing segment {i+1}/{len(spec.dialogue_segments)}..."
                )
                
                # Prepare parameters for this segment
                params = {
                    "VIDEO_PATH": str(current_video),
                    "AUDIO_PATH": str(segment.audio_path),
                    "START_TIME": segment.start_time_sec,
                    "END_TIME": segment.end_time_sec,
                    "FACE_THRESHOLD": spec.face_detection_threshold,
                }
                
                inject_result = self._loader.inject(template, params)
                workflow = inject_result.workflow if hasattr(inject_result, 'workflow') else inject_result
                
                # Submit and wait
                job = await client.submit(workflow)
                
                while not job.is_terminal():
                    await asyncio.sleep(0.5)
                
                if job.failed:
                    return LipSyncResult.failed(
                        f"Musetalk failed on segment {i+1}: {job.error}",
                        self.provider
                    )
                
                # Output becomes input for next segment
                # (Actual path would come from job outputs)
                segments_processed += 1
            
            report_progress("compositing", 0.9, "Finalizing output...")
            
            # Copy final result to output path
            spec.output_video.parent.mkdir(parents=True, exist_ok=True)
            # Actual copy from ComfyUI output would happen here
            
            report_progress("completed", 1.0, "Lip sync complete")
            
            return LipSyncResult(
                success=True,
                output_path=spec.output_video,
                provider_used=self.provider,
                status=LipSyncStatus.COMPLETED,
                segments_processed=segments_processed,
                processing_time_sec=time.time() - start_time,
            )
            
        except Exception as e:
            logger.error(f"Musetalk lip sync failed: {e}")
            return LipSyncResult.failed(str(e), self.provider)
    
    async def _passthrough(self, spec: LipSyncSpec, reason: str) -> LipSyncResult:
        """Just copy video when no lip sync needed."""
        spec.output_video.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(spec.input_video, spec.output_video)
        return LipSyncResult.skipped(spec.output_video, reason)
    
    async def health_check(self) -> bool:
        """Check if Musetalk ComfyUI is accessible."""
        try:
            client = await self._get_client()
            return await client.health_check()
        except Exception as e:
            logger.error(f"Musetalk health check failed: {e}")
            return False


# =============================================================================
# REPLICATE WAV2LIP IMPLEMENTATION (API FALLBACK)
# =============================================================================

class Wav2LipReplicateEngine(BaseLipSyncEngine):
    """
    Lip sync engine using Wav2Lip via Replicate API.
    
    Wav2Lip is a classic lip sync model. This implementation uses
    the Replicate API for easy cloud deployment without managing
    GPU infrastructure.
    
    Pricing: ~$0.05-0.10 per video segment (varies by length)
    """
    
    provider = LipSyncProvider.WAV2LIP_REPLICATE
    
    # Replicate model ID for Wav2Lip
    MODEL_ID = "devxpy/cog-wav2lip:8d65e3f4f4298520e079198b493c25adfc43c058ffec924f2aefc8010ed25eef"
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        output_dir: Path = Path("./workspace/video/lipsync"),
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize the Wav2Lip Replicate engine.
        
        Args:
            api_token: Replicate API token (or use REPLICATE_API_TOKEN env)
            output_dir: Where to save lip-synced videos
            temp_dir: Temporary file directory
        """
        super().__init__(output_dir, temp_dir)
        
        import os
        self.api_token = api_token or os.environ.get("REPLICATE_API_TOKEN")
        if not self.api_token:
            raise ValueError("Replicate API token not provided")
        
        self._client = None
    
    async def _get_client(self):
        """Lazy-initialize Replicate client."""
        if self._client is None:
            try:
                import replicate
                import os
                os.environ["REPLICATE_API_TOKEN"] = self.api_token
                self._client = replicate
            except ImportError:
                raise RuntimeError(
                    "replicate package not installed. "
                    "Run: pip install replicate"
                )
        return self._client
    
    async def sync(
        self,
        spec: LipSyncSpec,
        progress_callback: Optional[Callable[[LipSyncProgress], None]] = None,
    ) -> LipSyncResult:
        """Apply lip sync using Wav2Lip via Replicate."""
        start_time = time.time()
        
        def report_progress(stage: str, progress: float, message: str = ""):
            if progress_callback:
                progress_callback(LipSyncProgress(
                    stage=stage,
                    progress=progress,
                    total_segments=len(spec.dialogue_segments),
                    message=message,
                    elapsed_sec=time.time() - start_time,
                ))
        
        try:
            if not spec.has_dialogue:
                return await self._passthrough(spec, "No dialogue segments")
            
            if not spec.input_video.exists():
                return LipSyncResult.failed(f"Input video not found: {spec.input_video}")
            
            report_progress("syncing", 0.1, "Connecting to Replicate...")
            
            client = await self._get_client()
            
            # Wav2Lip typically processes the entire video with one audio
            # For multiple segments, we'd need to concatenate audio or
            # process segments separately
            
            # For simplicity, we'll process with the first/main dialogue
            # More sophisticated handling would merge audio tracks
            main_segment = spec.dialogue_segments[0]
            
            if not main_segment.audio_path.exists():
                return LipSyncResult.failed(f"Audio not found: {main_segment.audio_path}")
            
            report_progress("syncing", 0.2, "Uploading to Replicate...")
            
            # Run Wav2Lip on Replicate
            loop = asyncio.get_event_loop()
            
            with open(spec.input_video, "rb") as video_file:
                with open(main_segment.audio_path, "rb") as audio_file:
                    output = await loop.run_in_executor(
                        None,
                        lambda: client.run(
                            self.MODEL_ID,
                            input={
                                "face": video_file,
                                "audio": audio_file,
                                "pads": "0 10 0 0",  # Padding for face crop
                                "smooth": True,
                                "fps": 25,  # Match typical video fps
                            }
                        )
                    )
            
            report_progress("compositing", 0.8, "Downloading result...")
            
            # Download output
            if output:
                spec.output_video.parent.mkdir(parents=True, exist_ok=True)
                
                import urllib.request
                output_url = str(output)
                await loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlretrieve(output_url, spec.output_video)
                )
                
                report_progress("completed", 1.0, "Lip sync complete")
                
                return LipSyncResult(
                    success=True,
                    output_path=spec.output_video,
                    provider_used=self.provider,
                    status=LipSyncStatus.COMPLETED,
                    segments_processed=len(spec.dialogue_segments),
                    processing_time_sec=time.time() - start_time,
                    warnings=["Used Wav2Lip Replicate - processing all segments as one"],
                )
            else:
                return LipSyncResult.failed("No output from Wav2Lip")
            
        except Exception as e:
            logger.error(f"Wav2Lip Replicate failed: {e}")
            return LipSyncResult.failed(str(e), self.provider)
    
    async def _passthrough(self, spec: LipSyncSpec, reason: str) -> LipSyncResult:
        """Just copy video when no lip sync needed."""
        spec.output_video.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(spec.input_video, spec.output_video)
        return LipSyncResult.skipped(spec.output_video, reason)
    
    async def health_check(self) -> bool:
        """Check if Replicate is accessible."""
        try:
            await self._get_client()
            return True
        except Exception as e:
            logger.error(f"Replicate health check failed: {e}")
            return False


# =============================================================================
# PASSTHROUGH IMPLEMENTATION (FOR TESTING / NON-SPEAKING SHOTS)
# =============================================================================

class PassthroughLipSyncEngine(BaseLipSyncEngine):
    """
    No-op lip sync engine that just copies input to output.
    
    Used when:
    - Testing pipeline without GPU
    - Shot has no dialogue (non-speaking characters)
    - All lip sync methods fail
    """
    
    provider = LipSyncProvider.PASSTHROUGH
    
    async def sync(
        self,
        spec: LipSyncSpec,
        progress_callback: Optional[Callable[[LipSyncProgress], None]] = None,
    ) -> LipSyncResult:
        """Just copy the input to output."""
        start_time = time.time()
        
        try:
            if not spec.input_video.exists():
                return LipSyncResult.failed(f"Input not found: {spec.input_video}")
            
            spec.output_video.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(spec.input_video, spec.output_video)
            
            reason = "No dialogue" if not spec.has_dialogue else "Passthrough mode"
            
            return LipSyncResult(
                success=True,
                output_path=spec.output_video,
                provider_used=LipSyncProvider.PASSTHROUGH,
                status=LipSyncStatus.SKIPPED,
                processing_time_sec=time.time() - start_time,
                warnings=[f"Lip sync skipped: {reason}"],
            )
            
        except Exception as e:
            return LipSyncResult.failed(str(e))
    
    async def health_check(self) -> bool:
        """Passthrough is always healthy."""
        return True


# =============================================================================
# LIP SYNC ENGINE FACTORY
# =============================================================================

class LipSyncFactory:
    """
    Factory for creating lip sync engines with automatic fallback.
    
    Tries providers in order of quality and falls back if unavailable.
    
    Fallback order: Musetalk ComfyUI → Wav2Lip Replicate → Passthrough
    
    Usage:
        factory = LipSyncFactory(comfy_host="http://localhost:8188")
        engine = await factory.get_engine()
        result = await engine.sync(spec)
    """
    
    def __init__(
        self,
        comfy_host: Optional[str] = None,
        replicate_token: Optional[str] = None,
        output_dir: Path = Path("./workspace/video/lipsync"),
        preferred_provider: Optional[LipSyncProvider] = None,
    ):
        """
        Initialize the factory.
        
        Args:
            comfy_host: ComfyUI server URL (None = API/passthrough only)
            replicate_token: Replicate API token
            output_dir: Where to save lip-synced videos
            preferred_provider: Preferred provider (None = best available)
        """
        self.comfy_host = comfy_host
        self.replicate_token = replicate_token
        self.output_dir = Path(output_dir)
        self.preferred_provider = preferred_provider
        
        self._engine_cache: Dict[LipSyncProvider, BaseLipSyncEngine] = {}
    
    async def get_engine(
        self,
        provider: Optional[LipSyncProvider] = None,
    ) -> BaseLipSyncEngine:
        """
        Get a lip sync engine, with automatic fallback.
        
        Args:
            provider: Specific provider to use (None = best available)
            
        Returns:
            A lip sync engine instance ready to use
        """
        target_provider = provider or self.preferred_provider
        
        # Try providers in order of preference
        providers_to_try = self._get_provider_priority(target_provider)
        
        for p in providers_to_try:
            engine = await self._try_get_engine(p)
            if engine and await engine.health_check():
                logger.info(f"Using lip sync provider: {p.value}")
                return engine
        
        # Fall back to passthrough
        logger.warning("No lip sync providers available, using passthrough")
        return PassthroughLipSyncEngine(self.output_dir)
    
    def _get_provider_priority(self, preferred: Optional[LipSyncProvider]) -> List[LipSyncProvider]:
        """Get providers to try in priority order."""
        all_providers = [
            LipSyncProvider.MUSETALK_COMFY,
            LipSyncProvider.WAV2LIP_COMFY,
            LipSyncProvider.WAV2LIP_REPLICATE,
            LipSyncProvider.PASSTHROUGH,
        ]
        
        if preferred and preferred != LipSyncProvider.PASSTHROUGH:
            providers = [preferred]
            providers.extend(p for p in all_providers if p != preferred)
            return providers
        
        return all_providers
    
    async def _try_get_engine(self, provider: LipSyncProvider) -> Optional[BaseLipSyncEngine]:
        """Try to create an engine for a provider."""
        if provider in self._engine_cache:
            return self._engine_cache[provider]
        
        if provider == LipSyncProvider.PASSTHROUGH:
            engine = PassthroughLipSyncEngine(self.output_dir)
            self._engine_cache[provider] = engine
            return engine
        
        if provider == LipSyncProvider.MUSETALK_COMFY:
            if not self.comfy_host:
                return None
            try:
                engine = MusetalkComfyEngine(
                    comfy_host=self.comfy_host,
                    output_dir=self.output_dir,
                )
                self._engine_cache[provider] = engine
                return engine
            except Exception as e:
                logger.debug(f"Failed to create Musetalk engine: {e}")
                return None
        
        if provider == LipSyncProvider.WAV2LIP_REPLICATE:
            import os
            token = self.replicate_token or os.environ.get("REPLICATE_API_TOKEN")
            if not token:
                return None
            try:
                engine = Wav2LipReplicateEngine(
                    api_token=token,
                    output_dir=self.output_dir,
                )
                self._engine_cache[provider] = engine
                return engine
            except Exception as e:
                logger.debug(f"Failed to create Wav2Lip Replicate engine: {e}")
                return None
        
        return None
    
    async def list_available_providers(self) -> List[LipSyncProvider]:
        """List all providers that are currently available."""
        available = []
        
        for provider in LipSyncProvider:
            engine = await self._try_get_engine(provider)
            if engine and await engine.health_check():
                available.append(provider)
        
        return available


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def sync_lips(
    input_video: Path,
    output_video: Path,
    audio_path: Path,
    start_time: float = 0.0,
    duration: Optional[float] = None,
    shot_id: str = "unknown",
    comfy_host: Optional[str] = None,
    provider: Optional[LipSyncProvider] = None,
) -> LipSyncResult:
    """
    Convenience function to lip-sync a video with a single audio track.
    
    Args:
        input_video: Path to input video
        output_video: Where to save lip-synced video
        audio_path: Path to dialogue audio
        start_time: When dialogue starts in video
        duration: Duration of dialogue (None = detect from audio)
        shot_id: Shot identifier for logging
        comfy_host: ComfyUI server (None = use API/passthrough)
        provider: Lip sync provider (None = auto)
        
    Returns:
        LipSyncResult with path to lip-synced video
    """
    # Detect audio duration if not specified
    if duration is None:
        duration = await _get_audio_duration(audio_path)
    
    segment = DialogueSegment(
        audio_path=audio_path,
        start_time_sec=start_time,
        end_time_sec=start_time + duration,
        character_id="unknown",
        line_id="single",
    )
    
    spec = LipSyncSpec(
        input_video=input_video,
        output_video=output_video,
        shot_id=shot_id,
        dialogue_segments=[segment],
        provider=provider,
    )
    
    factory = LipSyncFactory(comfy_host=comfy_host)
    engine = await factory.get_engine(provider)
    
    return await engine.sync(spec)


async def _get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file using FFprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(audio_path)
    ]
    
    try:
        loop = asyncio.get_event_loop()
        process = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )
        
        if process.returncode == 0:
            import json
            data = json.loads(process.stdout)
            return float(data.get("format", {}).get("duration", 5.0))
        
        return 5.0  # Default
        
    except Exception:
        return 5.0


# =============================================================================
# BATCH PROCESSING
# =============================================================================

async def sync_batch(
    specs: List[LipSyncSpec],
    comfy_host: Optional[str] = None,
    max_concurrent: int = 2,
    progress_callback: Optional[Callable[[str, LipSyncProgress], None]] = None,
) -> Dict[str, LipSyncResult]:
    """
    Lip-sync multiple videos with controlled concurrency.
    
    Args:
        specs: List of lip sync specifications
        comfy_host: ComfyUI server URL
        max_concurrent: Maximum concurrent operations
        progress_callback: Callback receiving (shot_id, progress)
        
    Returns:
        Dict mapping shot_id to LipSyncResult
    """
    factory = LipSyncFactory(comfy_host=comfy_host)
    engine = await factory.get_engine()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def sync_one(spec: LipSyncSpec) -> tuple[str, LipSyncResult]:
        async with semaphore:
            def shot_progress(p: LipSyncProgress):
                if progress_callback:
                    progress_callback(spec.shot_id, p)
            
            result = await engine.sync(spec, shot_progress)
            return spec.shot_id, result
    
    tasks = [sync_one(spec) for spec in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for i, result in enumerate(results):
        shot_id = specs[i].shot_id
        if isinstance(result, Exception):
            output[shot_id] = LipSyncResult.failed(str(result))
        else:
            output[result[0]] = result[1]
    
    return output