#!/usr/bin/env python3
"""
===============================================================================
ADD AUDIO TO FINAL VIDEO (WITH LIP-SYNC)
===============================================================================

Adds TTS dialogue + lip-sync + ambience to an already-stitched final video.

This script:
1. Loads dialogue from project.json
2. Generates TTS for each line (ElevenLabs)
3. Applies lip-sync to video (Wav2Lip via Replicate)
4. Generates ambience (Replicate AudioLDM-2)
5. Mixes all audio with correct timing
6. Overlays on the final video

Usage:
    python tests/test_add_audio_to_final.py ~/Downloads/matrix_zero_final.mp4

Author: Continuum Studios
Date: 2026-01-19
===============================================================================
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
except ImportError:
    pass

from src.sonic import get_tts_engine, get_ambience_engine
from src.sonic.types import (
    AmbienceSpec,
    AmbienceType,
    DialogueLine,
    TTSProvider,
    VoiceConfig,
    VoiceEmotion,
    AudioGenerationStatus,
)
from src.sonic.ambience import AmbienceProvider
from src.sonic.lip_sync import (
    Wav2LipReplicateEngine,
    LatentSyncReplicateEngine,
    LipSyncSpec,
    DialogueSegment,
    LipSyncStatus,
)
from src.post.audio_ducker import AudioDucker, DuckingParams

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_PATH = Path(__file__).parent.parent / "projects" / "matrix_zero" / "project.json"

# Shot durations (from test script: 33 frames / 16 fps = 2.0625s per shot)
SHOT_DURATION = 2.0625
SHOT_COUNT = 6

# Use ElevenLabs for emotional TTS
USE_ELEVENLABS = True

# ElevenLabs voice IDs (pre-made voices)
# See: https://elevenlabs.io/voice-library
ELEVENLABS_VOICES = {
    "goku": "pNInz6obpgDQGcFmaJgB",    # "Adam" - deep, confident, energetic
    "naruto": "ErXwobaYiN019PkySvjV",   # "Antoni" - young, warm, energetic
}

# Emotion mapping - ElevenLabs supports expressive delivery
EMOTION_MAP = {
    "excited": VoiceEmotion.HAPPY,
    "determined": VoiceEmotion.ANGRY,  # Determined = intense delivery
    "confident": VoiceEmotion.NEUTRAL,
    "neutral": VoiceEmotion.NEUTRAL,
}

# Enable lip-sync (requires REPLICATE_API_TOKEN)
# LatentSync (ByteDance) works with anime characters - uses diffusion, not face detection
USE_LIPSYNC = True  # Now enabled - using LatentSync for anime

# Lip-sync engine selection
# Options: "latentsync" (anime-friendly), "wav2lip" (realistic faces only)
LIP_SYNC_ENGINE = "latentsync"


# =============================================================================
# HELPERS
# =============================================================================

def get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def calculate_absolute_time(shot_index: int, start_time_in_shot: float) -> float:
    """Calculate absolute timestamp from shot-relative time."""
    shot_start = shot_index * SHOT_DURATION
    return shot_start + start_time_in_shot


async def generate_tts(
    dialogue_lines: list,
    voice_configs: dict,
    output_dir: Path,
) -> list:
    """Generate TTS for all dialogue lines."""

    if USE_ELEVENLABS:
        if not os.environ.get("ELEVENLABS_API_KEY"):
            print("ERROR: ELEVENLABS_API_KEY not set")
            return []
        print("Using ElevenLabs (emotional TTS)")
        engine = get_tts_engine(
            TTSProvider.ELEVENLABS,
            output_dir=output_dir,
        )
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set")
            return []
        print("Using OpenAI TTS")
        engine = get_tts_engine(
            TTSProvider.OPENAI,
            output_dir=output_dir,
        )

    results = []
    for line, abs_time in dialogue_lines:
        voice_config = voice_configs.get(line.character_id)
        if not voice_config:
            print(f"  WARNING: No voice config for {line.character_id}")
            continue

        print(f"  Generating: \"{line.text[:30]}...\" @ {abs_time:.1f}s")

        try:
            result = await engine.synthesize(line, voice_config)
            if result.status == AudioGenerationStatus.COMPLETE:
                results.append((result, abs_time))
                print(f"    OK: {result.actual_duration_sec:.1f}s")
            else:
                print(f"    FAILED: {result.error}")
        except Exception as e:
            print(f"    ERROR: {e}")

    return results


async def generate_ambience(
    duration: float,
    output_dir: Path,
) -> Path:
    """Generate ambience audio."""

    if not os.environ.get("REPLICATE_API_TOKEN"):
        print("  WARNING: REPLICATE_API_TOKEN not set, skipping ambience")
        return None

    engine = get_ambience_engine(
        AmbienceProvider.REPLICATE,
        output_dir=output_dir,
    )

    spec = AmbienceSpec(
        ambience_id="epic_atmosphere",
        type=AmbienceType.INTERIOR,
        description="epic orchestral ambient atmosphere, heroic tension, anime battle preparation mood, cinematic",
        duration_sec=min(duration, 30),  # AudioLDM max is 30s
        intensity=0.5,
        loop=True,
    )

    print(f"  Generating {spec.duration_sec:.0f}s ambience...")

    try:
        result = await engine.generate(spec)
        if result.status == AudioGenerationStatus.COMPLETE:
            print(f"    OK: {result.actual_duration_sec:.1f}s")
            return result.audio_path
        else:
            print(f"    FAILED: {result.error}")
            return None
    except Exception as e:
        print(f"    ERROR: {e}")
        return None


# =============================================================================
# LIP-SYNC HELPERS
# =============================================================================

def extract_segment(input_video: Path, start: float, end: float, output: Path) -> bool:
    """Extract a video segment using FFmpeg.

    Args:
        input_video: Source video path
        start: Start time in seconds
        end: End time in seconds
        output: Output path for extracted segment

    Returns:
        True if successful
    """
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_video),
        "-t", str(duration),
        "-c:v", "libx264",  # Re-encode for clean cut
        "-preset", "fast",
        "-crf", "18",
        "-an",  # No audio for lip-sync input
        str(output)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    extract_segment error: {result.stderr[:200]}")
        return False
    return True


def replace_segment(
    original: Path,
    replacement: Path,
    start: float,
    end: float,
    output: Path
) -> bool:
    """Replace a segment in the original video with the replacement.

    Uses FFmpeg filter to:
    1. Take frames before 'start' from original
    2. Take replacement video
    3. Take frames after 'end' from original
    4. Concatenate them

    Args:
        original: Original full video
        replacement: Lip-synced segment
        start: Where replacement starts (seconds)
        end: Where replacement ends (seconds)
        output: Output path for combined video

    Returns:
        True if successful
    """
    # Get original video duration
    duration = get_video_duration(original)

    # Build filter_complex for segment replacement
    # This splits the original into before/after parts and concatenates with replacement
    filter_complex = (
        f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[before];"
        f"[1:v]setpts=PTS-STARTPTS[middle];"
        f"[0:v]trim={end}:{duration},setpts=PTS-STARTPTS[after];"
        f"[before][middle][after]concat=n=3:v=1:a=0[outv]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(original),
        "-i", str(replacement),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",  # Handle audio separately later
        str(output)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    replace_segment error: {result.stderr[:200]}")
        return False
    return True


async def apply_lip_sync(
    video_path: Path,
    tts_results: list,
    output_dir: Path,
) -> Path:
    """Apply lip-sync to video for each dialogue segment.

    Args:
        video_path: Input video path
        tts_results: List of (SynthesizedDialogue, abs_time) tuples
        output_dir: Directory for temporary files

    Returns:
        Path to lip-synced video
    """
    if not USE_LIPSYNC:
        print("  Lip-sync disabled")
        return video_path

    if not os.environ.get("REPLICATE_API_TOKEN"):
        print("  WARNING: REPLICATE_API_TOKEN not set, skipping lip-sync")
        return video_path

    if not tts_results:
        print("  No dialogue to lip-sync")
        return video_path

    print(f"  Processing {len(tts_results)} dialogue segments...")
    print(f"  Using engine: {LIP_SYNC_ENGINE}")

    lipsync_dir = output_dir / "lipsync"
    lipsync_dir.mkdir(exist_ok=True)

    # Select lip-sync engine
    if LIP_SYNC_ENGINE == "latentsync":
        print("  LatentSync (ByteDance) - anime-friendly, diffusion-based")
        engine = LatentSyncReplicateEngine(output_dir=lipsync_dir)
    else:
        print("  Wav2Lip - realistic faces only (may fail on anime)")
        engine = Wav2LipReplicateEngine(output_dir=lipsync_dir)

    current_video = video_path

    for i, (tts_result, abs_time) in enumerate(tts_results):
        print(f"\n  Segment {i+1}/{len(tts_results)}: @ {abs_time:.1f}s")

        # Calculate segment boundaries (add padding for context)
        padding = 0.2  # 200ms padding
        segment_start = max(0, abs_time - padding)
        segment_end = abs_time + tts_result.actual_duration_sec + padding

        # 1. Extract video segment
        segment_video = lipsync_dir / f"segment_{i}_input.mp4"
        print(f"    Extracting {segment_start:.1f}s - {segment_end:.1f}s...")

        if not extract_segment(current_video, segment_start, segment_end, segment_video):
            print(f"    FAILED to extract segment, skipping lip-sync")
            continue

        # 2. Run lip-sync on segment
        lipsync_output = lipsync_dir / f"segment_{i}_lipsync.mp4"

        spec = LipSyncSpec(
            input_video=segment_video,
            output_video=lipsync_output,
            shot_id=f"segment_{i}",
            dialogue_segments=[
                DialogueSegment(
                    audio_path=tts_result.audio_path,
                    start_time_sec=padding,  # Relative to segment start
                    end_time_sec=padding + tts_result.actual_duration_sec,
                    character_id=tts_result.line_id.split("_")[0] if hasattr(tts_result, 'line_id') else "unknown",
                    line_id=f"line_{i}",
                )
            ],
        )

        print(f"    Running Wav2Lip via Replicate...")
        try:
            result = await engine.sync(spec)

            if result.status == LipSyncStatus.COMPLETED and result.output_path and result.output_path.exists():
                print(f"    OK: Lip-sync complete")

                # 3. Replace segment in video
                replaced_video = lipsync_dir / f"video_after_lipsync_{i}.mp4"
                print(f"    Replacing segment in video...")

                if replace_segment(current_video, result.output_path, segment_start, segment_end, replaced_video):
                    current_video = replaced_video
                    print(f"    OK: Segment replaced")
                else:
                    print(f"    FAILED to replace segment")
            elif result.status == LipSyncStatus.SKIPPED:
                print(f"    SKIPPED: {result.warnings}")
            else:
                print(f"    FAILED: {result.error}")
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

    return current_video


# =============================================================================
# AUDIO DUCKING HELPERS
# =============================================================================

def create_combined_dialogue(
    tts_results: list,
    output_path: Path,
    video_duration: float,
) -> Path:
    """Create a single audio track with all TTS at correct timing.

    This is used as the "trigger" for ducking - the ambience will lower
    whenever this combined dialogue track has audio.

    Args:
        tts_results: List of (SynthesizedDialogue, abs_time) tuples
        output_path: Where to write the combined audio
        video_duration: Total duration for the output track

    Returns:
        Path to combined dialogue audio
    """
    if not tts_results:
        return None

    # Build filter for combining all TTS with delays
    filter_parts = []
    inputs = []

    for i, (result, abs_time) in enumerate(tts_results):
        inputs.extend(["-i", str(result.audio_path)])
        delay_ms = int(abs_time * 1000)
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[d{i}]")

    # Mix all delayed audio
    mix_inputs = "".join([f"[d{i}]" for i in range(len(tts_results))])
    filter_parts.append(f"{mix_inputs}amix=inputs={len(tts_results)}:duration=longest[out]")

    # Pad to video duration
    filter_parts.append(f"[out]apad=whole_dur={video_duration}[padded]")

    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"] +
        inputs +
        ["-filter_complex", filter_complex] +
        ["-map", "[padded]"] +
        ["-c:a", "aac", "-b:a", "128k"] +
        [str(output_path)]
    )

    print(f"  Creating combined dialogue track...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR creating combined dialogue: {result.stderr[:200]}")
        return None

    return output_path


async def apply_ducking(
    ambience_path: Path,
    dialogue_path: Path,
    output_path: Path,
    duck_level_db: float = -12.0,
) -> Path:
    """Apply ducking to ambience - lower volume during dialogue.

    Args:
        ambience_path: Ambience/music audio
        dialogue_path: Combined dialogue track (trigger)
        output_path: Where to write ducked audio
        duck_level_db: How much to reduce (-12dB is standard)

    Returns:
        Path to ducked ambience, or original if ducking fails
    """
    if not ambience_path or not ambience_path.exists():
        print("  No ambience to duck")
        return ambience_path

    if not dialogue_path or not dialogue_path.exists():
        print("  No dialogue track for ducking trigger")
        return ambience_path

    print(f"  Applying ducking ({duck_level_db}dB reduction during dialogue)...")

    # Use standard preset (good for film/video)
    params = DuckingParams.standard()

    ducker = AudioDucker(default_params=params)

    try:
        result = await ducker.duck(
            music_path=ambience_path,
            dialogue_path=dialogue_path,
            output_path=output_path,
        )

        if result.success:
            print(f"    OK: Ducking applied in {result.processing_time_sec:.1f}s")
            return result.output_path
        else:
            print(f"    FAILED: {result.error}")
            return ambience_path

    except Exception as e:
        print(f"    ERROR: {e}")
        return ambience_path


def mix_and_overlay(
    video_path: Path,
    tts_results: list,
    ambience_path: Path,
    output_path: Path,
    video_duration: float,
):
    """Mix all audio and overlay on video using FFmpeg."""

    print(f"\nMixing audio and overlaying on video...")

    # Build FFmpeg command
    inputs = ["-i", str(video_path)]
    filter_parts = []

    # Add ambience input if available
    audio_index = 1
    if ambience_path and ambience_path.exists():
        inputs.extend(["-i", str(ambience_path)])
        # Loop ambience to video duration, set volume to -15dB
        filter_parts.append(f"[{audio_index}:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration},volume=0.18[amb]")
        audio_index += 1

    # Add TTS inputs
    tts_labels = []
    for i, (result, abs_time) in enumerate(tts_results):
        inputs.extend(["-i", str(result.audio_path)])
        # Delay each TTS to its absolute time
        delay_ms = int(abs_time * 1000)
        label = f"tts{i}"
        filter_parts.append(f"[{audio_index}:a]adelay={delay_ms}|{delay_ms},volume=1.0[{label}]")
        tts_labels.append(f"[{label}]")
        audio_index += 1

    # Mix all audio together
    if ambience_path and ambience_path.exists():
        mix_inputs = "[amb]" + "".join(tts_labels)
        n_inputs = 1 + len(tts_labels)
    else:
        mix_inputs = "".join(tts_labels)
        n_inputs = len(tts_labels)

    if n_inputs > 0:
        filter_parts.append(f"{mix_inputs}amix=inputs={n_inputs}:duration=longest:dropout_transition=0[aout]")
        filter_complex = ";".join(filter_parts)

        cmd = (
            ["ffmpeg", "-y"] +
            inputs +
            ["-filter_complex", filter_complex] +
            ["-map", "0:v", "-map", "[aout]"] +
            ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"] +
            [str(output_path)]
        )
    else:
        # No audio to add
        print("  WARNING: No audio generated, copying video as-is")
        cmd = ["cp", str(video_path), str(output_path)]

    print(f"  Running FFmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FFmpeg ERROR: {result.stderr}")
        return False

    return True


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║       ADD AUDIO TO FINAL VIDEO (WITH LIP-SYNC)                    ║
║       TTS → Lip-Sync → Ambience → Final Mix                       ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    # Get video path from argument or prompt
    if len(sys.argv) > 1:
        video_path = Path(sys.argv[1]).expanduser()
    else:
        video_input = input("Enter path to final video: ").strip()
        video_path = Path(video_input).expanduser()

    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}")
        sys.exit(1)

    print(f"Video: {video_path}")

    # Get video duration
    video_duration = get_video_duration(video_path)
    print(f"Duration: {video_duration:.1f}s")

    # Load project config
    print(f"\nLoading project: {PROJECT_PATH}")
    with open(PROJECT_PATH) as f:
        project = json.load(f)

    # Extract voice configs
    voice_configs = {}
    for char_id, char_data in project["bible"]["characters"].items():
        vc = char_data.get("voice_config", {})
        if vc:
            if USE_ELEVENLABS:
                # Use ElevenLabs with pre-selected expressive voices
                voice_configs[char_id] = VoiceConfig(
                    character_id=char_id,
                    provider=TTSProvider.ELEVENLABS,
                    voice_id=ELEVENLABS_VOICES.get(char_id, "pNInz6obpgDQGcFmaJgB"),
                    speaking_rate=vc.get("speaking_rate", 1.0),
                    pitch_shift=vc.get("pitch", 0.0),
                    custom_params={
                        "stability": 0.5,        # Lower = more expressive
                        "similarity_boost": 0.8,  # Higher = more consistent
                        "style": 0.7,            # Higher = more dramatic
                    }
                )
            else:
                voice_configs[char_id] = VoiceConfig(
                    character_id=char_id,
                    provider=TTSProvider.OPENAI,
                    voice_id=vc.get("voice_id", "onyx"),
                    speaking_rate=vc.get("speaking_rate", 1.0),
                    pitch_shift=vc.get("pitch", 0.0),
                )

    print(f"Voice configs: {list(voice_configs.keys())}")

    # Extract dialogue with absolute timing
    dialogue_lines = []
    shot_index = 0

    for scene in project["scenes"]:
        for shot in scene["shots"]:
            for dlg in shot.get("dialogue", []):
                emotion_str = dlg.get("emotion", "neutral").lower()
                emotion = EMOTION_MAP.get(emotion_str, VoiceEmotion.NEUTRAL)

                line = DialogueLine(
                    line_id=dlg["line_id"],
                    character_id=dlg["character_id"],
                    text=dlg["text"],
                    start_time_sec=dlg["start_time_sec"],
                    emotion=emotion,
                    shot_id=shot["shot_id"],
                    scene_id=scene["scene_id"],
                )

                abs_time = calculate_absolute_time(shot_index, dlg["start_time_sec"])
                dialogue_lines.append((line, abs_time))

            shot_index += 1

    print(f"Dialogue lines: {len(dialogue_lines)}")
    for line, abs_time in dialogue_lines:
        print(f"  [{abs_time:.1f}s] {line.character_id}: \"{line.text}\"")

    # Setup output directory
    output_dir = video_path.parent / "audio_temp"
    output_dir.mkdir(exist_ok=True)

    # Generate TTS
    print(f"\n{'='*60}")
    print("GENERATING TTS")
    print(f"{'='*60}")

    tts_results = await generate_tts(dialogue_lines, voice_configs, output_dir)
    print(f"Generated {len(tts_results)}/{len(dialogue_lines)} dialogue lines")

    # Apply lip-sync to video
    print(f"\n{'='*60}")
    print("APPLYING LIP-SYNC")
    print(f"{'='*60}")

    lipsynced_video = await apply_lip_sync(video_path, tts_results, output_dir)
    if lipsynced_video != video_path:
        print(f"Lip-synced video: {lipsynced_video}")
    else:
        print("Using original video (no lip-sync applied)")

    # Generate ambience
    print(f"\n{'='*60}")
    print("GENERATING AMBIENCE")
    print(f"{'='*60}")

    ambience_path = await generate_ambience(video_duration, output_dir)

    # Apply audio ducking (lower ambience during dialogue)
    print(f"\n{'='*60}")
    print("APPLYING AUDIO DUCKING")
    print(f"{'='*60}")

    if ambience_path and tts_results:
        # Create combined dialogue track for ducking trigger
        combined_dialogue = output_dir / "combined_dialogue.aac"
        combined_dialogue = create_combined_dialogue(
            tts_results=tts_results,
            output_path=combined_dialogue,
            video_duration=video_duration,
        )

        if combined_dialogue:
            # Apply ducking - ambience ducks -12dB during dialogue
            ducked_ambience = output_dir / "ambience_ducked.aac"
            ambience_path = await apply_ducking(
                ambience_path=ambience_path,
                dialogue_path=combined_dialogue,
                output_path=ducked_ambience,
                duck_level_db=-12.0,
            )
            print(f"  Using ducked ambience: {ambience_path}")
        else:
            print("  Skipping ducking (no combined dialogue track)")
    else:
        print("  Skipping ducking (no ambience or no TTS)")

    # Mix and overlay
    print(f"\n{'='*60}")
    print("MIXING & OVERLAYING")
    print(f"{'='*60}")

    output_path = video_path.parent / f"{video_path.stem}_with_audio.mp4"

    success = mix_and_overlay(
        video_path=lipsynced_video,  # Use lip-synced video
        tts_results=tts_results,
        ambience_path=ambience_path,
        output_path=output_path,
        video_duration=video_duration,
    )

    if success:
        print(f"\n{'='*60}")
        print("COMPLETE!")
        print(f"{'='*60}")
        print(f"Output: {output_path}")
        print(f"\nTo verify: ffprobe -show_streams \"{output_path}\"")
        print(f"To play: open \"{output_path}\"")
    else:
        print("\nFailed to create final video")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
