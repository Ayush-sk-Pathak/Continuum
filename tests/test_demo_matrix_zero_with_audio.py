#!/usr/bin/env python3
"""
===============================================================================
TEST DEMO: MATRIX ZERO - WITH AUDIO
===============================================================================

Full pipeline: Video + Audio (TTS + Ambience + Mixing)

This script extends test_demo_matrix_zero.py by adding:
- TTS dialogue generation (OpenAI)
- Ambience generation (AudioLDM-2 via Replicate)
- Audio mixing per shot
- Video+audio stitching

Prerequisites:
    export CONTINUUM_COMFYUI__HOST="wss://xxx-8188.proxy.runpod.net"
    export OPENAI_API_KEY="sk-..."
    export REPLICATE_API_TOKEN="r8_..."

Usage:
    python tests/test_demo_matrix_zero_with_audio.py

Author: Continuum Studios
Date: 2026-01-19
===============================================================================
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
except ImportError:
    # dotenv not installed, rely on shell environment
    pass

from src.pipeline import SonicOrchestrator
from src.post.stitcher import stitch_with_audio

# =============================================================================
# CONFIGURATION
# =============================================================================

# Project config path
PROJECT_PATH = Path(__file__).parent.parent / "projects" / "matrix_zero" / "project.json"

# Video settings (must match test_demo_matrix_zero.py)
FRAME_COUNT = 33        # ~2 seconds at 16fps
FRAME_RATE = 16
WIDTH = 512
HEIGHT = 288

# Shot IDs matching project.json
SHOT_IDS = ["shot_01", "shot_02", "shot_03", "shot_04", "shot_05", "shot_06"]

# Output settings
OUTPUT_PREFIX = "matrix_zero"


# =============================================================================
# MAIN PIPELINE
# =============================================================================

async def generate_audio(
    project_path: Path,
    shot_durations: dict,
    output_dir: Path,
) -> dict:
    """
    Generate all audio using SonicOrchestrator.

    Args:
        project_path: Path to project.json
        shot_durations: Dict of shot_id -> duration in seconds
        output_dir: Directory for audio output

    Returns:
        Dict mapping shot_id to audio file path
    """
    print(f"\n{'='*60}")
    print(f"AUDIO GENERATION")
    print(f"{'='*60}")

    # Check API keys
    if not os.environ.get("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY not set, TTS will fail")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        print("WARNING: REPLICATE_API_TOKEN not set, ambience will be skipped")

    orchestrator = SonicOrchestrator()

    print(f"Project: {project_path}")
    print(f"Shots: {list(shot_durations.keys())}")
    print(f"Output: {output_dir}")

    result = await orchestrator.run(
        project_path=project_path,
        shot_durations=shot_durations,
        output_dir=output_dir,
    )

    print(f"\nAudio generation complete:")
    print(f"  Success: {result.success}")
    print(f"  Dialogue lines: {result.dialogue_count}")
    print(f"  Duration: {result.total_duration_sec:.1f}s")
    print(f"  Time: {result.generation_time_sec:.1f}s")

    if result.errors:
        print(f"  Errors:")
        for err in result.errors:
            print(f"    - {err}")

    if result.warnings:
        print(f"  Warnings:")
        for warn in result.warnings:
            print(f"    - {warn}")

    return result.per_shot_audio


async def stitch_videos_with_audio(
    video_files: list,
    audio_tracks: dict,
    output_path: Path,
) -> bool:
    """
    Stitch video files with their corresponding audio tracks.

    Args:
        video_files: List of video file paths in order
        audio_tracks: Dict mapping shot_id to audio file path
        output_path: Path for final output

    Returns:
        True if successful
    """
    print(f"\n{'='*60}")
    print(f"STITCHING VIDEO + AUDIO")
    print(f"{'='*60}")

    print(f"Video clips: {len(video_files)}")
    for i, vf in enumerate(video_files):
        shot_id = SHOT_IDS[i]
        has_audio = shot_id in audio_tracks
        print(f"  {shot_id}: {vf.name} {'+ audio' if has_audio else '(no audio)'}")

    print(f"Output: {output_path}")

    result = await stitch_with_audio(
        video_clips=video_files,
        audio_tracks=audio_tracks,
        output_path=output_path,
        shot_ids=SHOT_IDS[:len(video_files)],
    )

    if result.success:
        print(f"\nStitch complete!")
        print(f"  Output: {result.output_path}")
        print(f"  Duration: {result.duration_sec:.1f}s")
        print(f"  Resolution: {result.resolution}")
        print(f"  Processing time: {result.processing_time_sec:.1f}s")
        return True
    else:
        print(f"\nStitch FAILED: {result.error}")
        return False


async def main_async():
    """Async main function."""
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║       MATRIX ZERO - WITH AUDIO                                    ║
║       Full Pipeline: Video + TTS + Ambience + Mixing              ║
║                                                                   ║
║       This script assumes videos are already generated.           ║
║       It adds audio and creates the final stitched video.         ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    # Check for existing videos
    print("Checking for video files...")
    print("This script expects videos to be downloaded from RunPod to a local directory.")
    print("")

    video_dir = Path(input("Enter path to video files directory: ").strip())
    if not video_dir.exists():
        print(f"ERROR: Directory not found: {video_dir}")
        sys.exit(1)

    # Find video files
    video_files = []
    for shot_id in SHOT_IDS:
        # Look for files matching pattern
        patterns = [
            f"{OUTPUT_PREFIX}_{shot_id}*.mp4",
            f"{OUTPUT_PREFIX}_shot{shot_id.split('_')[1]}*.mp4",
        ]
        found = None
        for pattern in patterns:
            matches = list(video_dir.glob(pattern))
            if matches:
                found = matches[0]
                break

        if not found:
            # Try with just shot number
            shot_num = int(shot_id.split("_")[1])
            matches = list(video_dir.glob(f"*shot{shot_num:02d}*.mp4"))
            if matches:
                found = matches[0]

        if found:
            video_files.append(found)
            print(f"  Found {shot_id}: {found.name}")
        else:
            print(f"  MISSING {shot_id}")

    if len(video_files) != len(SHOT_IDS):
        print(f"\nWARNING: Found {len(video_files)}/{len(SHOT_IDS)} videos")
        proceed = input("Continue with available videos? (y/n): ").strip().lower()
        if proceed != 'y':
            sys.exit(0)

    # Calculate shot durations (use actual video duration or estimate)
    shot_durations = {}
    for i, shot_id in enumerate(SHOT_IDS[:len(video_files)]):
        # Default to ~2 seconds (33 frames / 16 fps)
        shot_durations[shot_id] = FRAME_COUNT / FRAME_RATE

    print(f"\nShot durations: {shot_durations}")

    # Setup output directory
    output_dir = video_dir / "audio"
    output_dir.mkdir(exist_ok=True)

    # Step 1: Generate audio
    audio_tracks = await generate_audio(
        project_path=PROJECT_PATH,
        shot_durations=shot_durations,
        output_dir=output_dir,
    )

    # Step 2: Stitch with audio
    final_output = video_dir / f"{OUTPUT_PREFIX}_final_with_audio.mp4"
    success = await stitch_videos_with_audio(
        video_files=video_files,
        audio_tracks=audio_tracks,
        output_path=final_output,
    )

    if success:
        print(f"\n{'='*60}")
        print(f"PIPELINE COMPLETE!")
        print(f"{'='*60}")
        print(f"Final video: {final_output}")
        print(f"\nTo verify audio:")
        print(f"  ffprobe -show_streams {final_output}")
    else:
        print(f"\nPipeline failed. Check errors above.")
        sys.exit(1)


def main():
    """Entry point."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
