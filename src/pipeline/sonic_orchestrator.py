"""
Continuum Engine - Sonic Orchestrator

Orchestrates all audio generation for a project: TTS, ambience, and mixing.
This module bridges the gap between project.json and the Sonic Engine.

Usage:
    orchestrator = SonicOrchestrator()
    result = await orchestrator.run(
        project_path=Path("projects/matrix_zero/project.json"),
        shot_durations={"shot_01": 5.0, "shot_02": 5.0, ...},
        output_dir=Path("./workspace/audio"),
    )

Design Principles:
    1. Project-to-Manifest conversion: Parse project.json into SonicManifest
    2. Parallel generation: TTS and ambience run concurrently
    3. Per-shot mixing: Each shot gets its own mixed audio file
    4. Scalable: Works for any project, not just test scripts
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.sonic import (
    get_tts_engine,
    get_ambience_engine,
    get_mixer,
)
from src.sonic.types import (
    AmbienceSpec,
    AmbienceType,
    AudioGenerationStatus,
    DialogueLine,
    MixResult,
    ShotAudioPlan,
    SonicManifest,
    SynthesizedAmbience,
    SynthesizedDialogue,
    TTSProvider,
    VoiceConfig,
    VoiceEmotion,
)
from src.sonic.ambience import AmbienceProvider


logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class SonicResult:
    """
    Result of running the Sonic Orchestrator.

    Attributes:
        success: Whether all audio generated successfully
        per_shot_audio: Mapping of shot_id to mixed audio path
        total_duration_sec: Total audio duration
        dialogue_count: Number of dialogue lines generated
        errors: List of error messages
        warnings: List of warning messages
        generation_time_sec: How long the whole process took
    """
    success: bool = False
    per_shot_audio: Dict[str, Path] = field(default_factory=dict)
    total_duration_sec: float = 0.0
    dialogue_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generation_time_sec: float = 0.0


# =============================================================================
# EMOTION MAPPING
# =============================================================================

# Map project.json emotion strings to VoiceEmotion enum
EMOTION_MAP: Dict[str, VoiceEmotion] = {
    "neutral": VoiceEmotion.NEUTRAL,
    "happy": VoiceEmotion.HAPPY,
    "excited": VoiceEmotion.HAPPY,  # Map excited -> happy
    "sad": VoiceEmotion.SAD,
    "angry": VoiceEmotion.ANGRY,
    "fearful": VoiceEmotion.FEARFUL,
    "scared": VoiceEmotion.FEARFUL,
    "surprised": VoiceEmotion.SURPRISED,
    "whisper": VoiceEmotion.WHISPER,
    "shouting": VoiceEmotion.SHOUTING,
    "confident": VoiceEmotion.NEUTRAL,  # Confident is delivered through text/direction
    "determined": VoiceEmotion.NEUTRAL,  # Determined -> neutral with energy
}


# Map project.json ambience type strings to AmbienceType enum
AMBIENCE_TYPE_MAP: Dict[str, AmbienceType] = {
    "silence": AmbienceType.SILENCE,
    "interior": AmbienceType.INTERIOR,
    "interior_quiet": AmbienceType.INTERIOR_QUIET,
    "interior_busy": AmbienceType.INTERIOR_BUSY,
    "exterior": AmbienceType.EXTERIOR_URBAN,
    "urban": AmbienceType.URBAN,
    "nature": AmbienceType.NATURE,
    "water": AmbienceType.WATER,
    "crowd": AmbienceType.CROWD,
    "industrial": AmbienceType.INDUSTRIAL,
    "cinematic": AmbienceType.INTERIOR,  # Cinematic -> interior (neutral base)
}


# =============================================================================
# SONIC ORCHESTRATOR
# =============================================================================

class SonicOrchestrator:
    """
    Orchestrates audio generation for a project.

    This class handles:
    1. Loading project.json and building SonicManifest
    2. Generating TTS for all dialogue lines
    3. Generating ambience
    4. Mixing all audio per-shot

    Attributes:
        openai_api_key: API key for OpenAI TTS
        replicate_api_token: API token for Replicate (ambience)
        max_concurrent_tts: Max concurrent TTS API calls
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        elevenlabs_api_key: Optional[str] = None,
        replicate_api_token: Optional[str] = None,
        max_concurrent_tts: int = 3,
    ):
        """
        Initialize the orchestrator.

        Args:
            openai_api_key: OpenAI API key (defaults to env var)
            elevenlabs_api_key: ElevenLabs API key (defaults to env var)
            replicate_api_token: Replicate API token (defaults to env var)
            max_concurrent_tts: Max concurrent TTS calls (default 3)
        """
        self.openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.elevenlabs_api_key = elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.replicate_api_token = replicate_api_token or os.environ.get("REPLICATE_API_TOKEN")
        self.max_concurrent_tts = max_concurrent_tts

    # -------------------------------------------------------------------------
    # MAIN ENTRY POINT
    # -------------------------------------------------------------------------

    async def run(
        self,
        project_path: Path,
        shot_durations: Dict[str, float],
        output_dir: Path,
    ) -> SonicResult:
        """
        Run the full audio generation pipeline.

        Args:
            project_path: Path to project.json
            shot_durations: Actual video durations per shot (shot_id -> seconds)
            output_dir: Directory to save all audio files

        Returns:
            SonicResult with paths to mixed audio
        """
        start_time = time.time()
        result = SonicResult()

        # Create output directories
        output_dir = Path(output_dir)
        dialogue_dir = output_dir / "dialogue"
        ambience_dir = output_dir / "ambience"
        mixed_dir = output_dir / "mixed"

        for d in [dialogue_dir, ambience_dir, mixed_dir]:
            d.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: Load project and build manifest
            logger.info(f"Loading project from {project_path}")
            manifest = self._build_manifest_from_project(project_path, shot_durations)

            # Validate manifest
            issues = manifest.validate()
            if issues:
                for issue in issues:
                    logger.warning(f"Manifest issue: {issue}")
                    result.warnings.append(issue)

            # Step 2: Generate TTS for all dialogue (parallel with ambience)
            # Step 3: Generate ambience
            logger.info(f"Generating audio: {manifest.total_dialogue_lines} dialogue lines, ambience")

            tts_task = self._generate_all_tts(manifest, dialogue_dir)
            ambience_task = self._generate_ambience(manifest, ambience_dir)

            tts_results, ambience_result = await asyncio.gather(
                tts_task,
                ambience_task,
                return_exceptions=True,
            )

            # Handle exceptions
            if isinstance(tts_results, Exception):
                result.errors.append(f"TTS generation failed: {tts_results}")
                tts_results = {}
            if isinstance(ambience_result, Exception):
                result.errors.append(f"Ambience generation failed: {ambience_result}")
                ambience_result = None

            # Step 4: Mix audio per shot
            logger.info("Mixing audio per shot")
            mix_results = await self._mix_all_shots(
                manifest,
                tts_results,
                ambience_result,
                shot_durations,
                mixed_dir,
            )

            # Build result
            for shot_id, mix_result in mix_results.items():
                if mix_result.status == AudioGenerationStatus.COMPLETE:
                    result.per_shot_audio[shot_id] = mix_result.output_path
                else:
                    result.warnings.append(f"Mix failed for {shot_id}: {mix_result.error}")

            result.success = len(result.errors) == 0
            result.dialogue_count = len(tts_results)
            result.total_duration_sec = sum(shot_durations.values())

        except Exception as e:
            logger.exception("Sonic orchestrator failed")
            result.errors.append(str(e))
            result.success = False

        result.generation_time_sec = time.time() - start_time
        logger.info(f"Sonic orchestrator completed in {result.generation_time_sec:.1f}s")

        return result

    # -------------------------------------------------------------------------
    # MANIFEST BUILDING
    # -------------------------------------------------------------------------

    def _build_manifest_from_project(
        self,
        project_path: Path,
        shot_durations: Dict[str, float],
    ) -> SonicManifest:
        """
        Convert project.json to SonicManifest.

        Handles field mapping:
        - "pitch" -> "pitch_shift"
        - emotion strings -> VoiceEmotion enum
        - ambience type strings -> AmbienceType enum
        """
        with open(project_path) as f:
            project = json.load(f)

        project_id = project.get("project_id", "unknown")

        # Extract voice configs from bible.characters
        voice_configs: Dict[str, VoiceConfig] = {}
        bible = project.get("bible", {})
        characters = bible.get("characters", {})

        for char_id, char_data in characters.items():
            vc_data = char_data.get("voice_config", {})
            if vc_data:
                provider_str = vc_data.get("provider", "openai").upper()
                provider = TTSProvider[provider_str] if provider_str in TTSProvider.__members__ else TTSProvider.OPENAI

                voice_configs[char_id] = VoiceConfig(
                    character_id=char_id,
                    provider=provider,
                    voice_id=vc_data.get("voice_id", ""),
                    speaking_rate=vc_data.get("speaking_rate", 1.0),
                    pitch_shift=vc_data.get("pitch", 0.0),  # Note: project uses "pitch"
                    default_emotion=VoiceEmotion.NEUTRAL,
                )

        # Extract dialogue from scenes.shots
        shot_plans: List[ShotAudioPlan] = []
        scenes = project.get("scenes", [])

        for scene in scenes:
            scene_id = scene.get("scene_id", "")
            shots = scene.get("shots", [])

            for shot in shots:
                shot_id = shot.get("shot_id", "")
                duration = shot_durations.get(shot_id, shot.get("duration_sec", 5.0))

                # Convert dialogue entries
                dialogue_lines: List[DialogueLine] = []
                for dlg in shot.get("dialogue", []):
                    emotion_str = dlg.get("emotion", "neutral").lower()
                    emotion = EMOTION_MAP.get(emotion_str, VoiceEmotion.NEUTRAL)

                    dialogue_lines.append(DialogueLine(
                        line_id=dlg.get("line_id", ""),
                        character_id=dlg.get("character_id", ""),
                        text=dlg.get("text", ""),
                        start_time_sec=dlg.get("start_time_sec", 0.0),
                        emotion=emotion,
                        shot_id=shot_id,
                        scene_id=scene_id,
                    ))

                shot_plans.append(ShotAudioPlan(
                    shot_id=shot_id,
                    scene_id=scene_id,
                    duration_sec=duration,
                    dialogue_lines=dialogue_lines,
                    ambience=None,  # Use global ambience
                    foley_events=[],  # No foley for MVP
                ))

        # Extract global ambience
        global_ambience = None
        audio_config = project.get("audio", {})
        amb_data = audio_config.get("global_ambience")

        if amb_data:
            type_str = amb_data.get("type", "interior").lower()
            amb_type = AMBIENCE_TYPE_MAP.get(type_str, AmbienceType.INTERIOR)

            # Calculate total duration for ambience
            total_duration = sum(shot_durations.values())

            global_ambience = AmbienceSpec(
                ambience_id=amb_data.get("ambience_id", "global_ambience"),
                type=amb_type,
                description=amb_data.get("prompt", "ambient background audio"),
                duration_sec=total_duration,
                intensity=0.5,  # Default intensity
                loop=True,
            )

        return SonicManifest(
            manifest_id=f"{project_id}_sonic",
            project_id=project_id,
            voice_configs=voice_configs,
            shot_plans=shot_plans,
            global_ambience=global_ambience,
        )

    # -------------------------------------------------------------------------
    # TTS GENERATION
    # -------------------------------------------------------------------------

    async def _generate_all_tts(
        self,
        manifest: SonicManifest,
        output_dir: Path,
    ) -> Dict[str, SynthesizedDialogue]:
        """
        Generate TTS for all dialogue lines in the manifest.

        Uses controlled concurrency to avoid rate limits.

        Returns:
            Mapping of line_id to SynthesizedDialogue
        """
        results: Dict[str, SynthesizedDialogue] = {}

        # Collect all dialogue lines
        all_lines: List[Tuple[DialogueLine, VoiceConfig]] = []
        for plan in manifest.shot_plans:
            for line in plan.dialogue_lines:
                voice_config = manifest.get_voice_config(line.character_id)
                if voice_config:
                    all_lines.append((line, voice_config))
                else:
                    logger.warning(f"No voice config for character {line.character_id}")

        if not all_lines:
            logger.info("No dialogue lines to generate")
            return results

        # Determine provider from first voice config (assume consistent per project)
        provider = all_lines[0][1].provider

        # Get TTS engine
        if provider == TTSProvider.OPENAI:
            if not self.openai_api_key:
                raise ValueError("OpenAI API key required for TTS")
            engine = get_tts_engine(
                TTSProvider.OPENAI,
                api_key=self.openai_api_key,
                output_dir=output_dir,
            )
        else:
            if not self.elevenlabs_api_key:
                raise ValueError("ElevenLabs API key required for TTS")
            engine = get_tts_engine(
                TTSProvider.ELEVENLABS,
                api_key=self.elevenlabs_api_key,
                output_dir=output_dir,
            )

        # Generate with semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent_tts)

        async def generate_one(line: DialogueLine, voice_config: VoiceConfig) -> Tuple[str, SynthesizedDialogue]:
            async with semaphore:
                try:
                    result = await engine.synthesize(line, voice_config)
                    logger.info(f"Generated TTS for {line.line_id}: {result.actual_duration_sec:.1f}s")
                    return (line.line_id, result)
                except Exception as e:
                    logger.error(f"TTS failed for {line.line_id}: {e}")
                    return (line.line_id, SynthesizedDialogue.failed(line.line_id, str(e)))

        # Run all TTS in parallel with concurrency control
        tasks = [generate_one(line, vc) for line, vc in all_lines]
        results_list = await asyncio.gather(*tasks)

        for line_id, synth in results_list:
            results[line_id] = synth

        return results

    # -------------------------------------------------------------------------
    # AMBIENCE GENERATION
    # -------------------------------------------------------------------------

    async def _generate_ambience(
        self,
        manifest: SonicManifest,
        output_dir: Path,
    ) -> Optional[SynthesizedAmbience]:
        """
        Generate global ambience for the project.
        """
        if not manifest.global_ambience:
            logger.info("No global ambience specified")
            return None

        if not self.replicate_api_token:
            logger.warning("Replicate API token not set, skipping ambience")
            return None

        engine = get_ambience_engine(
            AmbienceProvider.REPLICATE,
            api_token=self.replicate_api_token,
            output_dir=output_dir,
        )

        try:
            result = await engine.generate(manifest.global_ambience)
            logger.info(f"Generated ambience: {result.actual_duration_sec:.1f}s")
            return result
        except Exception as e:
            logger.error(f"Ambience generation failed: {e}")
            return SynthesizedAmbience(
                ambience_id=manifest.global_ambience.ambience_id,
                status=AudioGenerationStatus.FAILED,
                error=str(e),
            )

    # -------------------------------------------------------------------------
    # MIXING
    # -------------------------------------------------------------------------

    async def _mix_all_shots(
        self,
        manifest: SonicManifest,
        tts_results: Dict[str, SynthesizedDialogue],
        ambience: Optional[SynthesizedAmbience],
        shot_durations: Dict[str, float],
        output_dir: Path,
    ) -> Dict[str, MixResult]:
        """
        Mix audio for all shots.

        Each shot gets its own mixed audio file combining:
        - Dialogue lines for that shot
        - Global ambience (trimmed to shot duration)
        """
        mixer = get_mixer(
            output_dir=output_dir,
            dialogue_db=0.0,
            ambience_db=-15.0,  # Per project.json global_ambience.volume_db
        )

        results: Dict[str, MixResult] = {}

        for plan in manifest.shot_plans:
            shot_id = plan.shot_id
            duration = shot_durations.get(shot_id, plan.duration_sec)

            # Gather dialogue for this shot
            dialogue_pairs: List[Tuple[SynthesizedDialogue, DialogueLine]] = []
            for line in plan.dialogue_lines:
                synth = tts_results.get(line.line_id)
                if synth and synth.status == AudioGenerationStatus.COMPLETE:
                    dialogue_pairs.append((synth, line))

            # Mix
            try:
                mix_result = await mixer.mix_shot(
                    shot_id=shot_id,
                    duration_sec=duration,
                    dialogue=dialogue_pairs,
                    ambience=ambience if ambience and ambience.status == AudioGenerationStatus.COMPLETE else None,
                    foley=[],  # No foley for MVP
                    scene_id=plan.scene_id,
                )
                results[shot_id] = mix_result
                logger.info(f"Mixed audio for {shot_id}: {mix_result.output_path}")
            except Exception as e:
                logger.error(f"Mixing failed for {shot_id}: {e}")
                results[shot_id] = MixResult.failed(
                    mix_id=f"{plan.scene_id}_{shot_id}",
                    shot_id=shot_id,
                    error=str(e),
                )

        return results
