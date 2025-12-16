"""
Continuum Engine - Audio Mixer

Combines all audio layers (dialogue, ambience, foley) into a single
mixed audio file per shot. This is the final step in the Sonic pipeline
before handing off to Post-Production.

Layer Hierarchy (loudest to quietest):
    1. Dialogue  - 0 dB (reference level)
    2. Foley     - -6 dB (supports action, doesn't compete with speech)
    3. Ambience  - -12 dB (bed track, always present but subtle)

What This Does:
    - Places audio at correct timestamps on a timeline
    - Applies volume levels per layer type
    - Mixes down to a single stereo WAV file
    - Outputs one mix per shot (aligned with video duration)

What This Does NOT Do:
    - Dynamic ducking (that's post/audio_ducker.py)
    - Generate audio (that's tts_engine.py, ambience.py, foley.py)
    - Video assembly (that's post/stitcher.py)

Technical Approach:
    Uses FFmpeg's amix and adelay filters to combine and time-align
    multiple audio sources into a single output.

Usage:
    mixer = AudioMixer(output_dir=Path("./workspace/audio/mixed"))
    result = await mixer.mix_shot(
        shot_id="shot_001",
        duration_sec=12.0,
        dialogue=[synth_dialogue_1, synth_dialogue_2],
        ambience=synth_ambience,
        foley=[synth_foley_1, synth_foley_2],
    )
"""

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .types import (
    AudioGenerationStatus,
    DialogueLine,
    MixResult,
    ShotAudioPlan,
    SonicManifest,
    SynthesizedAmbience,
    SynthesizedDialogue,
    SynthesizedFoley,
)


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS - Default Mix Levels
# =============================================================================

# Volume levels in dB (relative to 0 dB reference)
DEFAULT_DIALOGUE_DB = 0.0       # Dialogue is the reference level
DEFAULT_FOLEY_DB = -6.0         # Foley supports action, stays clear of dialogue
DEFAULT_AMBIENCE_DB = -12.0     # Ambience is the bed, always subtle

# Audio format settings
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 2            # Stereo output


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class AudioPlacement:
    """
    An audio file placed at a specific time in the mix.
    
    Attributes:
        audio_path: Path to the audio file
        start_time_sec: When to start playing (0 = beginning)
        volume_db: Volume adjustment in dB
        duration_sec: Duration of audio (None = full length)
        label: Human-readable label for debugging
    """
    audio_path: Path
    start_time_sec: float = 0.0
    volume_db: float = 0.0
    duration_sec: Optional[float] = None
    label: str = ""
    
    def __post_init__(self):
        if isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)


@dataclass
class MixSpec:
    """
    Complete specification for a mix operation.
    
    Attributes:
        shot_id: Identifier for the shot
        duration_sec: Total duration of the mix
        placements: All audio placements in the mix
        output_path: Where to write the mixed audio
        sample_rate: Output sample rate
        channels: Number of output channels
    """
    shot_id: str
    duration_sec: float
    placements: List[AudioPlacement] = field(default_factory=list)
    output_path: Optional[Path] = None
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    
    @property
    def is_empty(self) -> bool:
        """Check if there's anything to mix."""
        return len(self.placements) == 0
    
    @property
    def layer_count(self) -> int:
        """Number of audio layers in the mix."""
        return len(self.placements)


# =============================================================================
# AUDIO MIXER
# =============================================================================

class AudioMixer:
    """
    Mixes multiple audio layers into a single output file.
    
    This is the "glue" that combines TTS, ambience, and foley into
    one coherent audio track per shot.
    
    Attributes:
        output_dir: Directory for mixed output files
        sample_rate: Output sample rate
        dialogue_db: Default volume for dialogue
        foley_db: Default volume for foley
        ambience_db: Default volume for ambience
    """
    
    def __init__(
        self,
        output_dir: Path = Path("./workspace/audio/mixed"),
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        dialogue_db: float = DEFAULT_DIALOGUE_DB,
        foley_db: float = DEFAULT_FOLEY_DB,
        ambience_db: float = DEFAULT_AMBIENCE_DB,
    ):
        """
        Initialize the mixer.
        
        Args:
            output_dir: Where to save mixed files
            sample_rate: Output sample rate in Hz
            dialogue_db: Default dialogue volume (dB)
            foley_db: Default foley volume (dB)
            ambience_db: Default ambience volume (dB)
        """
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.dialogue_db = dialogue_db
        self.foley_db = foley_db
        self.ambience_db = ambience_db
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # HIGH-LEVEL API
    # -------------------------------------------------------------------------
    
    async def mix_shot(
        self,
        shot_id: str,
        duration_sec: float,
        dialogue: List[Tuple[SynthesizedDialogue, DialogueLine]],
        ambience: Optional[SynthesizedAmbience] = None,
        foley: List[Tuple[SynthesizedFoley, float]] = None,  # (foley, trigger_time)
        scene_id: str = "",
    ) -> MixResult:
        """
        Mix all audio for a single shot.
        
        This is the main entry point. It takes synthesized audio from
        the various engines and combines them into one file.
        
        Args:
            shot_id: Identifier for the shot
            duration_sec: Total duration of the shot
            dialogue: List of (SynthesizedDialogue, DialogueLine) pairs
            ambience: Optional ambience track
            foley: List of (SynthesizedFoley, trigger_time_sec) pairs
            scene_id: Parent scene identifier
            
        Returns:
            MixResult with path to mixed audio
        """
        start_time = time.time()
        mix_id = f"{scene_id}_{shot_id}" if scene_id else shot_id
        output_path = self.output_dir / f"{mix_id}_mixed.wav"
        
        # Build the mix specification
        spec = MixSpec(
            shot_id=shot_id,
            duration_sec=duration_sec,
            output_path=output_path,
            sample_rate=self.sample_rate,
        )
        
        # Add dialogue placements
        if dialogue:
            for synth, line in dialogue:
                if synth.status == AudioGenerationStatus.COMPLETE and synth.audio_path:
                    spec.placements.append(AudioPlacement(
                        audio_path=synth.audio_path,
                        start_time_sec=line.start_time_sec,
                        volume_db=self.dialogue_db,
                        label=f"dialogue:{line.line_id}",
                    ))
        
        # Add ambience (runs full duration, starts at 0)
        if ambience and ambience.status == AudioGenerationStatus.COMPLETE and ambience.audio_path:
            spec.placements.append(AudioPlacement(
                audio_path=ambience.audio_path,
                start_time_sec=0.0,
                volume_db=self.ambience_db,
                duration_sec=duration_sec,
                label=f"ambience:{ambience.ambience_id}",
            ))
        
        # Add foley placements
        if foley:
            for synth, trigger_time in foley:
                if synth.status == AudioGenerationStatus.COMPLETE and synth.audio_path:
                    spec.placements.append(AudioPlacement(
                        audio_path=synth.audio_path,
                        start_time_sec=trigger_time,
                        volume_db=self.foley_db,
                        label=f"foley:{synth.event_id}",
                    ))
        
        # Handle empty mix (generate silence)
        if spec.is_empty:
            logger.warning(f"No audio to mix for {shot_id}, generating silence")
            await self._generate_silence(output_path, duration_sec)
            
            return MixResult(
                mix_id=mix_id,
                shot_id=shot_id,
                output_path=output_path,
                duration_sec=duration_sec,
                component_count=0,
                status=AudioGenerationStatus.COMPLETE,
                warnings=["No audio components, generated silence"],
            )
        
        # Perform the mix
        try:
            await self._execute_mix(spec)
            
            processing_time = time.time() - start_time
            logger.info(
                f"Mixed {spec.layer_count} layers for {shot_id} "
                f"in {processing_time:.2f}s"
            )
            
            return MixResult(
                mix_id=mix_id,
                shot_id=shot_id,
                output_path=output_path,
                duration_sec=duration_sec,
                component_count=spec.layer_count,
                status=AudioGenerationStatus.COMPLETE,
            )
            
        except Exception as e:
            logger.error(f"Mix failed for {shot_id}: {e}")
            return MixResult.failed(mix_id, shot_id, str(e))
    
    async def mix_from_plan(
        self,
        plan: ShotAudioPlan,
        dialogue_results: Dict[str, SynthesizedDialogue],
        ambience_result: Optional[SynthesizedAmbience],
        foley_results: Dict[str, SynthesizedFoley],
    ) -> MixResult:
        """
        Mix audio using a ShotAudioPlan and pre-synthesized results.
        
        This is the orchestrator-friendly API that takes the plan from
        SonicManifest and the results from the various engines.
        
        Args:
            plan: The audio plan for this shot
            dialogue_results: Map of line_id -> SynthesizedDialogue
            ambience_result: The synthesized ambience (if any)
            foley_results: Map of event_id -> SynthesizedFoley
            
        Returns:
            MixResult with path to mixed audio
        """
        # Build dialogue list with timing info
        dialogue = []
        for line in plan.dialogue_lines:
            synth = dialogue_results.get(line.line_id)
            if synth:
                dialogue.append((synth, line))
        
        # Build foley list with timing info
        foley = []
        for event in plan.foley_events:
            synth = foley_results.get(event.event_id)
            if synth:
                foley.append((synth, event.trigger_time_sec))
        
        return await self.mix_shot(
            shot_id=plan.shot_id,
            duration_sec=plan.duration_sec,
            dialogue=dialogue,
            ambience=ambience_result,
            foley=foley,
            scene_id=plan.scene_id,
        )
    
    # -------------------------------------------------------------------------
    # LOW-LEVEL MIX EXECUTION
    # -------------------------------------------------------------------------
    
    async def _execute_mix(self, spec: MixSpec) -> None:
        """
        Execute the mix using FFmpeg.
        
        Strategy:
        1. Each input gets a delay filter (adelay) for timing
        2. Each input gets a volume filter for level adjustment
        3. All inputs are combined with amix filter
        4. Output is trimmed to exact duration
        """
        if not spec.placements:
            raise ValueError("No placements in mix spec")
        
        # Build FFmpeg command
        cmd = ["ffmpeg", "-y"]  # -y to overwrite
        
        # Add inputs
        for placement in spec.placements:
            if not placement.audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {placement.audio_path}")
            cmd.extend(["-i", str(placement.audio_path)])
        
        # Build filter graph
        filter_parts = []
        mix_inputs = []
        
        for i, placement in enumerate(spec.placements):
            stream = f"[{i}:a]"
            output = f"[a{i}]"
            
            filters = []
            
            # Delay filter (convert seconds to milliseconds)
            if placement.start_time_sec > 0:
                delay_ms = int(placement.start_time_sec * 1000)
                filters.append(f"adelay={delay_ms}|{delay_ms}")  # L|R channels
            
            # Volume filter
            if placement.volume_db != 0:
                filters.append(f"volume={placement.volume_db}dB")
            
            # Trim to duration if specified
            if placement.duration_sec:
                # apad pads with silence, then atrim cuts to duration
                filters.append(f"apad=whole_dur={spec.duration_sec}")
                filters.append(f"atrim=duration={spec.duration_sec}")
            
            # Build filter chain for this input
            if filters:
                filter_chain = ",".join(filters)
                filter_parts.append(f"{stream}{filter_chain}{output}")
                mix_inputs.append(output)
            else:
                mix_inputs.append(stream)
        
        # Combine all streams with amix
        # normalize=0 prevents auto-normalization (we control levels)
        # dropout_transition smooths when streams end
        inputs_str = "".join(mix_inputs)
        n_inputs = len(mix_inputs)
        filter_parts.append(
            f"{inputs_str}amix=inputs={n_inputs}:normalize=0:dropout_transition=0.5[mixed]"
        )
        
        # Final trim to exact duration
        filter_parts.append(f"[mixed]atrim=duration={spec.duration_sec}[out]")
        
        # Complete filter graph
        filter_graph = ";".join(filter_parts)
        
        cmd.extend([
            "-filter_complex", filter_graph,
            "-map", "[out]",
            "-ar", str(spec.sample_rate),
            "-ac", str(spec.channels),
            "-c:a", "pcm_s16le",  # WAV format
            str(spec.output_path)
        ])
        
        # Execute FFmpeg
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        
        loop = asyncio.get_event_loop()
        process = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
        )
        
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {process.stderr}")
    
    async def _generate_silence(self, output_path: Path, duration_sec: float) -> None:
        """Generate a silent audio file of the specified duration."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={self.sample_rate}:cl=stereo",
            "-t", str(duration_sec),
            "-c:a", "pcm_s16le",
            str(output_path)
        ]
        
        loop = asyncio.get_event_loop()
        process = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )
        
        if process.returncode != 0:
            raise RuntimeError(f"Failed to generate silence: {process.stderr}")
    
    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------
    
    async def probe_audio(self, audio_path: Path) -> Dict[str, Any]:
        """
        Probe an audio file for metadata.
        
        Returns:
            Dict with duration, sample_rate, channels, codec
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(audio_path)
        ]
        
        loop = asyncio.get_event_loop()
        process = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )
        
        if process.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {process.stderr}")
        
        import json
        data = json.loads(process.stdout)
        
        # Extract audio stream info
        audio_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_stream = stream
                break
        
        if not audio_stream:
            return {"duration": 0, "sample_rate": 0, "channels": 0, "codec": "unknown"}
        
        return {
            "duration": float(data.get("format", {}).get("duration", 0)),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "channels": int(audio_stream.get("channels", 0)),
            "codec": audio_stream.get("codec_name", "unknown"),
        }


# =============================================================================
# MANIFEST-LEVEL MIXING
# =============================================================================

async def mix_manifest(
    mixer: AudioMixer,
    manifest: SonicManifest,
    dialogue_results: Dict[str, SynthesizedDialogue],
    ambience_results: Dict[str, SynthesizedAmbience],
    foley_results: Dict[str, SynthesizedFoley],
    max_concurrent: int = 3,
) -> Dict[str, MixResult]:
    """
    Mix all shots in a SonicManifest.
    
    This is the top-level orchestration function that processes
    an entire manifest's worth of audio.
    
    Args:
        mixer: AudioMixer instance
        manifest: The complete sonic manifest
        dialogue_results: All synthesized dialogue, keyed by line_id
        ambience_results: All synthesized ambience, keyed by ambience_id
        foley_results: All synthesized foley, keyed by event_id
        max_concurrent: Maximum concurrent mix operations
        
    Returns:
        Dict mapping shot_id to MixResult
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def mix_one_shot(plan: ShotAudioPlan) -> Tuple[str, MixResult]:
        async with semaphore:
            # Get ambience for this shot (or scene-level)
            ambience = None
            if plan.ambience:
                ambience = ambience_results.get(plan.ambience.ambience_id)
            elif manifest.global_ambience:
                ambience = ambience_results.get(manifest.global_ambience.ambience_id)
            
            result = await mixer.mix_from_plan(
                plan=plan,
                dialogue_results=dialogue_results,
                ambience_result=ambience,
                foley_results=foley_results,
            )
            return plan.shot_id, result
    
    # Mix all shots
    tasks = [mix_one_shot(plan) for plan in manifest.shot_plans]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Build result dict
    output = {}
    for i, result in enumerate(results):
        shot_id = manifest.shot_plans[i].shot_id
        if isinstance(result, Exception):
            output[shot_id] = MixResult.failed(
                mix_id=shot_id,
                shot_id=shot_id,
                error=str(result),
            )
        else:
            output[result[0]] = result[1]
    
    return output


# =============================================================================
# HEALTH CHECK
# =============================================================================

async def check_ffmpeg_available() -> bool:
    """
    Check if FFmpeg is available for mixing operations.
    
    Returns:
        True if FFmpeg is installed and accessible
    """
    try:
        process = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
            )
        )
        return process.returncode == 0
    except FileNotFoundError:
        return False