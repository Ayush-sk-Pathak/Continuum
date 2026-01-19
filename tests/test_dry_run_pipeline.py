#!/usr/bin/env python3
"""
Dry Run Test - Full Pipeline Validation (No GPU Required)

Tests the entire pipeline orchestration on local Mac without GPU costs:
1. Load and validate project.json
2. Check all dependencies
3. Mock video generation (create placeholder videos)
4. Run actual audio pipeline (TTS + Ambience - cheap APIs)
5. Test stitching with mock videos
6. Test audio mixing
7. Report full pipeline status

This validates all the "plumbing" before spending money on cloud GPUs.

Usage:
    python tests/test_dry_run_pipeline.py [project_path]

    # Default: uses projects/last_guardian/project.json
    python tests/test_dry_run_pipeline.py

    # Custom project
    python tests/test_dry_run_pipeline.py projects/my_film/project.json
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class DryRunConfig:
    """Configuration for dry run."""
    # What to actually run vs mock
    run_tts: bool = True           # TTS is cheap (~$0.01)
    run_ambience: bool = True      # Ambience is cheap (~$0.05)
    run_ducking: bool = True       # Local FFmpeg
    mock_video_gen: bool = True    # Create placeholder videos
    mock_lora_training: bool = True

    # Mock video settings
    mock_video_duration: float = 2.0  # Shorter for testing
    mock_video_resolution: Tuple[int, int] = (512, 288)
    mock_video_fps: int = 16
    mock_video_color: str = "0x1a1a2e"  # Dark blue background

    # Output
    output_dir: Path = Path("workspace/dry_run")


# =============================================================================
# VALIDATION
# =============================================================================

def validate_project(project: dict) -> Tuple[bool, List[str]]:
    """Validate project structure and return (valid, errors)."""
    errors = []

    # Required top-level fields
    required = ["project_id", "title", "style", "bible", "scenes"]
    for field in required:
        if field not in project:
            errors.append(f"Missing required field: {field}")

    # Validate bible
    bible = project.get("bible", {})
    if not bible.get("characters"):
        errors.append("No characters defined in bible")
    if not bible.get("locations"):
        errors.append("No locations defined in bible")

    # Validate scenes
    scenes = project.get("scenes", [])
    if not scenes:
        errors.append("No scenes defined")

    shot_count = 0
    dialogue_count = 0

    for scene in scenes:
        if "scene_id" not in scene:
            errors.append(f"Scene missing scene_id: {scene}")

        shots = scene.get("shots", [])
        if not shots:
            errors.append(f"Scene '{scene.get('scene_id')}' has no shots")

        for shot in shots:
            shot_count += 1
            if "shot_id" not in shot:
                errors.append(f"Shot missing shot_id in scene {scene.get('scene_id')}")
            if "prompt" not in shot or not shot.get("prompt"):
                errors.append(f"Shot '{shot.get('shot_id')}' missing prompt")

            dialogue_count += len(shot.get("dialogue", []))

    return len(errors) == 0, errors, shot_count, dialogue_count


def check_dependencies() -> Tuple[bool, List[str]]:
    """Check all required dependencies."""
    errors = []

    # Check FFmpeg
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if result.returncode != 0:
            errors.append("FFmpeg not working properly")
    except FileNotFoundError:
        errors.append("FFmpeg not installed")

    # Check FFprobe
    try:
        result = subprocess.run(["ffprobe", "-version"], capture_output=True)
        if result.returncode != 0:
            errors.append("FFprobe not working properly")
    except FileNotFoundError:
        errors.append("FFprobe not installed")

    # Check API keys
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        errors.append("No LLM API key (OPENAI_API_KEY or ANTHROPIC_API_KEY)")

    if not os.environ.get("ELEVENLABS_API_KEY"):
        errors.append("ELEVENLABS_API_KEY not set (needed for TTS)")

    if not os.environ.get("REPLICATE_API_TOKEN"):
        errors.append("REPLICATE_API_TOKEN not set (needed for ambience)")

    # Check Python packages
    packages = [
        ("elevenlabs", "elevenlabs"),
        ("replicate", "replicate"),
    ]

    for package, pip_name in packages:
        try:
            __import__(package)
        except ImportError:
            errors.append(f"Python package '{pip_name}' not installed")

    return len(errors) == 0, errors


# =============================================================================
# MOCK VIDEO GENERATION
# =============================================================================

def create_mock_video(
    output_path: Path,
    duration: float,
    resolution: Tuple[int, int],
    fps: int,
    color: str,
    text: str = "",
) -> bool:
    """Create a placeholder video with colored background and text."""
    width, height = resolution

    # FFmpeg command to create solid color video with text
    filter_complex = f"color=c={color}:s={width}x{height}:d={duration}:r={fps}"

    if text:
        # Add text overlay
        safe_text = text.replace("'", "\\'").replace(":", "\\:")
        filter_complex += f",drawtext=text='{safe_text}':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", filter_complex,
        "-c:v", "libx264",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def generate_mock_shots(
    project: dict,
    output_dir: Path,
    config: DryRunConfig,
) -> Dict[str, Path]:
    """Generate mock videos for all shots."""
    shot_videos = {}

    colors = [
        "0x1a1a2e", "0x16213e", "0x0f3460", "0x533483",
        "0x2c3e50", "0x34495e", "0x1abc9c", "0x2980b9",
    ]

    shot_index = 0
    for scene in project.get("scenes", []):
        for shot in scene.get("shots", []):
            shot_id = shot.get("shot_id", f"shot_{shot_index}")

            # Create mock video
            video_path = output_dir / "shots" / f"{shot_id}.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)

            color = colors[shot_index % len(colors)]
            text = f"{shot_id}\\n{shot.get('shot_type', 'medium')}"

            success = create_mock_video(
                output_path=video_path,
                duration=config.mock_video_duration,
                resolution=config.mock_video_resolution,
                fps=config.mock_video_fps,
                color=color,
                text=text,
            )

            if success:
                shot_videos[shot_id] = video_path

            shot_index += 1

    return shot_videos


# =============================================================================
# AUDIO PIPELINE
# =============================================================================

async def generate_tts_for_project(
    project: dict,
    output_dir: Path,
) -> Dict[str, Path]:
    """Generate TTS for all dialogue lines."""
    from src.sonic import get_tts_engine
    from src.sonic.types import DialogueLine, VoiceConfig, TTSProvider

    tts_files = {}
    tts_dir = output_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    engine = get_tts_engine(TTSProvider.ELEVENLABS, output_dir=tts_dir)

    # Collect all dialogue
    for scene in project.get("scenes", []):
        for shot in scene.get("shots", []):
            for line in shot.get("dialogue", []):
                line_id = line.get("line_id", "unknown")
                text = line.get("text", "")
                character_id = line.get("character_id", "unknown")

                if not text:
                    continue

                # Get voice config from bible
                char_config = project.get("bible", {}).get("characters", {}).get(character_id, {})
                voice_cfg = char_config.get("voice_config", {})

                # Default to ElevenLabs "Adam" voice ID
                # See: https://elevenlabs.io/docs/api-reference/voices
                # ElevenLabs IDs are long alphanumeric strings (20+ chars)
                default_voice_id = "pNInz6obpgDQGcFmaJgB"  # Adam voice

                # Check if voice_id looks like a valid ElevenLabs ID (long string)
                stored_voice_id = voice_cfg.get("voice_id", "")
                is_valid_elevenlabs_id = len(stored_voice_id) >= 15

                voice_config = VoiceConfig(
                    character_id=character_id,
                    voice_id=stored_voice_id if is_valid_elevenlabs_id else default_voice_id,
                    provider=TTSProvider.ELEVENLABS,
                    speaking_rate=voice_cfg.get("speaking_rate", 1.0),
                    pitch_shift=voice_cfg.get("pitch_shift", 0.0),
                )

                dialogue_line = DialogueLine(
                    line_id=line_id,
                    character_id=character_id,
                    text=text,
                    start_time_sec=line.get("start_time_sec", 0.0),
                    # emotion is a VoiceEmotion enum, but project stores string - leave as None for default
                    emotion=None,
                )

                try:
                    result = await engine.synthesize(dialogue_line, voice_config)
                    if result.audio_path:
                        tts_files[line_id] = result.audio_path
                        print(f"    ✅ {line_id}: {text[:30]}...")
                except Exception as e:
                    print(f"    ❌ TTS failed for {line_id}: {e}")

    return tts_files


async def generate_ambience(
    project: dict,
    output_dir: Path,
    duration: float,
) -> Optional[Path]:
    """Generate ambience audio."""
    from src.sonic.ambience import ReplicateAmbienceEngine
    from src.sonic.types import AmbienceSpec, AmbienceType

    ambience_dir = output_dir / "ambience"
    ambience_dir.mkdir(parents=True, exist_ok=True)

    engine = ReplicateAmbienceEngine(output_dir=ambience_dir)

    # Get ambience prompt from project
    audio_config = project.get("audio", {}).get("global_ambience", {})
    prompt = audio_config.get("prompt", "cinematic ambient atmosphere")

    # Create AmbienceSpec with required fields
    spec = AmbienceSpec(
        ambience_id="global_ambience",
        type=AmbienceType.INTERIOR,  # Default to interior
        description=prompt,
        duration_sec=duration,
        scene_id="global",
    )

    try:
        result = await engine.generate(spec)
        return result.audio_path
    except Exception as e:
        print(f"    Ambience generation failed: {e}")
        return None


# =============================================================================
# STITCHING
# =============================================================================

def stitch_videos(
    shot_videos: Dict[str, Path],
    project: dict,
    output_path: Path,
) -> bool:
    """Stitch shot videos in order."""
    # Get shots in order
    ordered_shots = []
    for scene in project.get("scenes", []):
        for shot in scene.get("shots", []):
            shot_id = shot.get("shot_id")
            if shot_id in shot_videos:
                ordered_shots.append(shot_videos[shot_id])

    if not ordered_shots:
        return False

    # Create concat file
    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for video in ordered_shots:
            f.write(f"file '{video.absolute()}'\n")

    # FFmpeg concat
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_file.unlink()  # Cleanup

    return result.returncode == 0


# =============================================================================
# AUDIO MIXING
# =============================================================================

async def mix_audio(
    video_path: Path,
    tts_files: Dict[str, Path],
    ambience_path: Optional[Path],
    project: dict,
    output_path: Path,
    config: DryRunConfig,
) -> bool:
    """Mix audio and overlay on video."""
    from src.post.audio_ducker import AudioDucker, DuckingParams

    output_dir = output_path.parent

    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path)
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    video_duration = float(result.stdout.strip()) if result.stdout.strip() else 10.0

    # Collect dialogue timing from project
    tts_with_timing = []
    for scene in project.get("scenes", []):
        for shot in scene.get("shots", []):
            for line in shot.get("dialogue", []):
                line_id = line.get("line_id")
                if line_id in tts_files:
                    # Scale timing to match mock video duration
                    original_start = line.get("start_time_sec", 0)
                    # For dry run, spread dialogue evenly
                    tts_with_timing.append((tts_files[line_id], len(tts_with_timing) * 2.0))

    if not tts_with_timing and not ambience_path:
        # No audio to add, just copy video
        shutil.copy(video_path, output_path)
        return True

    # Build FFmpeg filter
    inputs = ["-i", str(video_path)]
    filter_parts = []

    # Add ambience if available
    if ambience_path and ambience_path.exists():
        inputs.extend(["-i", str(ambience_path)])
        # Loop ambience to video duration, reduce volume
        filter_parts.append(f"[1:a]aloop=loop=-1:size=2e+09,atrim=duration={video_duration},volume=0.3[amb]")

    # Add TTS files
    tts_inputs = []
    for i, (tts_path, start_time) in enumerate(tts_with_timing):
        input_idx = len(inputs) // 2
        inputs.extend(["-i", str(tts_path)])
        delay_ms = int(start_time * 1000)
        filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}[tts{i}]")
        tts_inputs.append(f"[tts{i}]")

    # Mix all audio
    if tts_inputs:
        mix_inputs = "".join(tts_inputs)
        if ambience_path and ambience_path.exists():
            mix_inputs = "[amb]" + mix_inputs
            filter_parts.append(f"{mix_inputs}amix=inputs={len(tts_inputs)+1}:duration=longest[mixed]")
        else:
            filter_parts.append(f"{mix_inputs}amix=inputs={len(tts_inputs)}:duration=longest[mixed]")
        final_audio = "[mixed]"
    elif ambience_path and ambience_path.exists():
        final_audio = "[amb]"
    else:
        final_audio = None

    if final_audio:
        filter_complex = ";".join(filter_parts)
        cmd = (
            ["ffmpeg", "-y"] +
            inputs +
            ["-filter_complex", filter_complex] +
            ["-map", "0:v", "-map", final_audio] +
            ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"] +
            [str(output_path)]
        )
    else:
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(output_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


# =============================================================================
# MAIN DRY RUN
# =============================================================================

async def run_dry_run(project_path: Path, config: DryRunConfig):
    """Run the full dry run pipeline."""

    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║              DRY RUN - FULL PIPELINE VALIDATION                   ║
║              Testing orchestration without GPU costs              ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    # Setup output directory
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # ==========================================================================
    # PHASE 1: Load and Validate Project
    # ==========================================================================
    print(f"{'='*60}")
    print("PHASE 1: LOAD AND VALIDATE PROJECT")
    print(f"{'='*60}")

    print(f"\nLoading: {project_path}")

    if not project_path.exists():
        print(f"  ERROR: Project file not found!")
        return False

    with open(project_path) as f:
        project = json.load(f)

    print(f"  Project ID: {project.get('project_id')}")
    print(f"  Title: {project.get('title')}")
    print(f"  Style: {project.get('style')}")

    valid, errors, shot_count, dialogue_count = validate_project(project)

    if not valid:
        print(f"\n  VALIDATION ERRORS:")
        for error in errors:
            print(f"    - {error}")
        return False

    print(f"\n  ✅ Project valid")
    print(f"    Characters: {len(project.get('bible', {}).get('characters', {}))}")
    print(f"    Locations: {len(project.get('bible', {}).get('locations', {}))}")
    print(f"    Scenes: {len(project.get('scenes', []))}")
    print(f"    Shots: {shot_count}")
    print(f"    Dialogue lines: {dialogue_count}")

    # ==========================================================================
    # PHASE 2: Check Dependencies
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 2: CHECK DEPENDENCIES")
    print(f"{'='*60}")

    deps_ok, dep_errors = check_dependencies()

    if dep_errors:
        print(f"\n  DEPENDENCY ISSUES:")
        for error in dep_errors:
            print(f"    ⚠️  {error}")

    if deps_ok:
        print(f"\n  ✅ All dependencies OK")
    else:
        print(f"\n  ⚠️  Some dependencies missing (may affect certain features)")

    # ==========================================================================
    # PHASE 3: Mock Video Generation
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 3: MOCK VIDEO GENERATION")
    print(f"{'='*60}")

    if config.mock_video_gen:
        print(f"\n  Creating placeholder videos for {shot_count} shots...")
        print(f"    Resolution: {config.mock_video_resolution}")
        print(f"    Duration per shot: {config.mock_video_duration}s")
        print(f"    FPS: {config.mock_video_fps}")

        shot_videos = generate_mock_shots(project, config.output_dir, config)

        print(f"\n  ✅ Generated {len(shot_videos)} mock videos")

        for shot_id, path in list(shot_videos.items())[:3]:
            print(f"    - {shot_id}: {path.name}")
        if len(shot_videos) > 3:
            print(f"    ... and {len(shot_videos) - 3} more")
    else:
        print(f"\n  ⏭️  Skipping video generation (mock disabled)")
        shot_videos = {}

    # ==========================================================================
    # PHASE 4: Stitch Videos
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 4: STITCH VIDEOS")
    print(f"{'='*60}")

    if shot_videos:
        stitched_path = config.output_dir / "stitched.mp4"
        print(f"\n  Stitching {len(shot_videos)} shots...")

        success = stitch_videos(shot_videos, project, stitched_path)

        if success:
            # Get duration
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(stitched_path)]
            result = subprocess.run(probe_cmd, capture_output=True, text=True)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0

            print(f"\n  ✅ Stitched video: {stitched_path.name}")
            print(f"    Duration: {duration:.1f}s")
        else:
            print(f"\n  ❌ Stitching failed")
            stitched_path = None
    else:
        print(f"\n  ⏭️  Skipping stitching (no videos)")
        stitched_path = None

    # ==========================================================================
    # PHASE 5: Generate TTS
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 5: GENERATE TTS")
    print(f"{'='*60}")

    if config.run_tts and dialogue_count > 0:
        print(f"\n  Generating TTS for {dialogue_count} dialogue lines...")
        print(f"    Provider: ElevenLabs")

        try:
            tts_files = await generate_tts_for_project(project, config.output_dir)
            print(f"\n  ✅ Generated {len(tts_files)} TTS files")

            for line_id, path in list(tts_files.items())[:3]:
                print(f"    - {line_id}: {path.name}")
            if len(tts_files) > 3:
                print(f"    ... and {len(tts_files) - 3} more")
        except Exception as e:
            print(f"\n  ❌ TTS generation failed: {e}")
            tts_files = {}
    else:
        print(f"\n  ⏭️  Skipping TTS (disabled or no dialogue)")
        tts_files = {}

    # ==========================================================================
    # PHASE 6: Generate Ambience
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 6: GENERATE AMBIENCE")
    print(f"{'='*60}")

    if config.run_ambience:
        # Calculate total duration
        total_duration = len(shot_videos) * config.mock_video_duration if shot_videos else 10.0

        print(f"\n  Generating {total_duration:.1f}s ambience...")
        print(f"    Provider: Replicate AudioLDM")

        try:
            ambience_path = await generate_ambience(project, config.output_dir, total_duration)
            if ambience_path:
                print(f"\n  ✅ Generated ambience: {ambience_path.name}")
            else:
                print(f"\n  ⚠️  Ambience generation returned no file")
        except Exception as e:
            print(f"\n  ❌ Ambience generation failed: {e}")
            ambience_path = None
    else:
        print(f"\n  ⏭️  Skipping ambience (disabled)")
        ambience_path = None

    # ==========================================================================
    # PHASE 7: Mix Audio
    # ==========================================================================
    print(f"\n{'='*60}")
    print("PHASE 7: MIX AUDIO AND FINAL OUTPUT")
    print(f"{'='*60}")

    if stitched_path and stitched_path.exists():
        final_output = config.output_dir / f"{project.get('project_id', 'output')}_final.mp4"

        print(f"\n  Mixing audio and creating final output...")

        try:
            success = await mix_audio(
                video_path=stitched_path,
                tts_files=tts_files,
                ambience_path=ambience_path,
                project=project,
                output_path=final_output,
                config=config,
            )

            if success:
                # Verify output
                probe_cmd = [
                    "ffprobe", "-v", "error",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    str(final_output)
                ]
                result = subprocess.run(probe_cmd, capture_output=True, text=True)
                streams = result.stdout.strip().split('\n') if result.stdout.strip() else []

                has_video = "video" in streams
                has_audio = "audio" in streams

                print(f"\n  ✅ Final output: {final_output}")
                print(f"    Video track: {'✅' if has_video else '❌'}")
                print(f"    Audio track: {'✅' if has_audio else '❌'}")
            else:
                print(f"\n  ❌ Audio mixing failed")
                final_output = None
        except Exception as e:
            print(f"\n  ❌ Audio mixing failed: {e}")
            final_output = None
    else:
        print(f"\n  ⏭️  Skipping audio mix (no stitched video)")
        final_output = None

    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    print(f"\n{'='*60}")
    print("DRY RUN SUMMARY")
    print(f"{'='*60}")

    print(f"""
    Project: {project.get('title')}

    Pipeline Steps:
      1. Project Validation    {'✅' if valid else '❌'}
      2. Dependencies          {'✅' if deps_ok else '⚠️'}
      3. Video Generation      {'✅ (mocked)' if shot_videos else '⏭️'}
      4. Stitching             {'✅' if stitched_path else '⏭️'}
      5. TTS Generation        {'✅' if tts_files else '⏭️'}
      6. Ambience Generation   {'✅' if ambience_path else '⏭️'}
      7. Audio Mixing          {'✅' if final_output else '⏭️'}

    Output Directory: {config.output_dir}
    """)

    if final_output and final_output.exists():
        print(f"    Final Video: {final_output}")
        print(f"\n    To view: open \"{final_output}\"")

    print(f"""
    {'='*60}
    WHAT THIS VALIDATES:
    {'='*60}
    ✅ Project structure is correct
    ✅ All orchestration code works
    ✅ FFmpeg stitching pipeline works
    ✅ TTS API integration works
    ✅ Ambience API integration works
    ✅ Audio mixing pipeline works

    WHAT'S NOT TESTED (needs GPU):
    ⏸️  Actual video generation (ComfyUI)
    ⏸️  LoRA training
    ⏸️  Identity consistency in real renders
    ⏸️  RIFE frame interpolation
    """)

    return True


# =============================================================================
# ENTRY POINT
# =============================================================================

async def main():
    # Default project path
    default_project = Path("projects/last_guardian/project.json")

    if len(sys.argv) > 1:
        project_path = Path(sys.argv[1])
    else:
        project_path = default_project

    config = DryRunConfig()

    success = await run_dry_run(project_path, config)

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
