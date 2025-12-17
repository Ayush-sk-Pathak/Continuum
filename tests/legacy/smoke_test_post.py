#!/usr/bin/env python3
"""
Smoke Test for post/ module.

Creates dummy video/audio files using FFmpeg, then tests:
1. FFmpeg wrapper (probe, extract frame)
2. Stitcher (concatenate clips)
3. Color matcher (analyze and match)
4. Audio ducker (duck music under dialogue)

Run from project root:
    python tests/smoke_test_post.py
    
Requirements:
    - FFmpeg installed
    - Python 3.10+
"""

import asyncio
import tempfile
import shutil
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.post.ffmpeg_wrapper import (
    check_ffmpeg_installed,
    get_ffmpeg_version,
    probe_video,
    run_ffmpeg,
    extract_frame,
    FFmpegNotFoundError,
)
from src.post.stitcher import Stitcher, stitch_clips
from src.post.color_match import ColorMatcher, quick_analyze
from src.post.audio_ducker import AudioDucker, DuckingParams


# =============================================================================
# TEST UTILITIES
# =============================================================================

class SmokeTestRunner:
    """Simple test runner with colored output."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.temp_dir = None
    
    def setup(self):
        """Create temp directory for test files."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="post_smoke_"))
        print(f"\n📁 Temp directory: {self.temp_dir}\n")
    
    def cleanup(self):
        """Remove temp directory."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"\n🧹 Cleaned up {self.temp_dir}")
    
    def test(self, name: str, success: bool, detail: str = ""):
        """Record test result."""
        if success:
            self.passed += 1
            print(f"  ✅ {name}")
            if detail:
                print(f"     └─ {detail}")
        else:
            self.failed += 1
            print(f"  ❌ {name}")
            if detail:
                print(f"     └─ {detail}")
    
    def summary(self):
        """Print final summary."""
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"  SMOKE TEST RESULTS: {self.passed}/{total} passed")
        if self.failed == 0:
            print("  🎉 All tests passed!")
        else:
            print(f"  ⚠️  {self.failed} test(s) failed")
        print(f"{'='*60}\n")
        return self.failed == 0


# =============================================================================
# DUMMY FILE GENERATORS
# =============================================================================

async def create_test_video(
    output_path: Path,
    duration_sec: float = 2.0,
    color: str = "red",
    resolution: str = "320x240",
    fps: int = 12,
    with_audio: bool = False,
) -> Path:
    """
    Create a test video using FFmpeg's test sources.
    
    Colors: red, green, blue, yellow, white, black
    """
    # Use color source for solid color video
    video_filter = f"color=c={color}:s={resolution}:d={duration_sec}:r={fps}"
    
    args = [
        "-f", "lavfi",
        "-i", video_filter,
    ]
    
    if with_audio:
        # Add sine wave audio
        args.extend([
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration_sec}",
        ])
    
    args.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-t", str(duration_sec),
    ])
    
    if with_audio:
        args.extend(["-c:a", "aac", "-b:a", "128k"])
    
    args.append(str(output_path))
    
    await run_ffmpeg(args, output_path=output_path)
    return output_path


async def create_test_audio(
    output_path: Path,
    duration_sec: float = 2.0,
    frequency: int = 440,
) -> Path:
    """Create a test audio file (sine wave)."""
    args = [
        "-f", "lavfi",
        "-i", f"sine=frequency={frequency}:duration={duration_sec}",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path),
    ]
    
    await run_ffmpeg(args, output_path=output_path)
    return output_path


async def create_speech_like_audio(
    output_path: Path,
    duration_sec: float = 2.0,
) -> Path:
    """Create audio that mimics speech (for ducking tests)."""
    # Use a mix of frequencies in speech range with gaps
    args = [
        "-f", "lavfi",
        "-i", (
            f"sine=frequency=300:duration={duration_sec},"
            f"volume=0.5"
        ),
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path),
    ]
    
    await run_ffmpeg(args, output_path=output_path)
    return output_path


# =============================================================================
# TESTS
# =============================================================================

async def test_ffmpeg_wrapper(runner: SmokeTestRunner):
    """Test the FFmpeg wrapper module."""
    print("\n🔧 Testing FFmpeg Wrapper...")
    
    # Test 1: FFmpeg installed
    try:
        check_ffmpeg_installed()
        runner.test("FFmpeg installed", True)
    except FFmpegNotFoundError as e:
        runner.test("FFmpeg installed", False, str(e))
        return  # Can't continue without FFmpeg
    
    # Test 2: Get version
    try:
        version = await get_ffmpeg_version()
        runner.test("Get FFmpeg version", True, version[:50])
    except Exception as e:
        runner.test("Get FFmpeg version", False, str(e))
    
    # Test 3: Create test video
    test_video = runner.temp_dir / "test_video.mp4"
    try:
        await create_test_video(test_video, duration_sec=1.0, color="blue")
        runner.test("Create test video", test_video.exists())
    except Exception as e:
        runner.test("Create test video", False, str(e))
        return
    
    # Test 4: Probe video
    try:
        info = await probe_video(test_video)
        runner.test(
            "Probe video metadata",
            info.duration_sec > 0 and info.width > 0,
            f"{info.width}x{info.height}, {info.duration_sec:.1f}s, {info.fps}fps"
        )
    except Exception as e:
        runner.test("Probe video metadata", False, str(e))
    
    # Test 5: Extract frame
    frame_path = runner.temp_dir / "frame.png"
    try:
        await extract_frame(test_video, frame_path, time_sec=0.5)
        runner.test("Extract frame", frame_path.exists())
    except Exception as e:
        runner.test("Extract frame", False, str(e))


async def test_stitcher(runner: SmokeTestRunner):
    """Test the Stitcher module."""
    print("\n🎬 Testing Stitcher...")
    
    # Create test clips
    clip1 = runner.temp_dir / "clip1.mp4"
    clip2 = runner.temp_dir / "clip2.mp4"
    clip3 = runner.temp_dir / "clip3.mp4"
    
    try:
        await create_test_video(clip1, duration_sec=1.0, color="red")
        await create_test_video(clip2, duration_sec=1.0, color="green")
        await create_test_video(clip3, duration_sec=1.0, color="blue")
        runner.test("Create test clips", all(c.exists() for c in [clip1, clip2, clip3]))
    except Exception as e:
        runner.test("Create test clips", False, str(e))
        return
    
    # Test 1: Simple stitch (fast path)
    output1 = runner.temp_dir / "stitched_simple.mp4"
    try:
        result = await stitch_clips([clip1, clip2, clip3], output1)
        runner.test(
            "Stitch 3 clips (fast path)",
            result.success and output1.exists(),
            f"Duration: {result.duration_sec:.1f}s" if result.success else result.error
        )
    except Exception as e:
        runner.test("Stitch 3 clips (fast path)", False, str(e))
    
    # Test 2: Stitch with different resolutions (re-encode path)
    clip_hd = runner.temp_dir / "clip_hd.mp4"
    try:
        await create_test_video(clip_hd, duration_sec=1.0, color="yellow", resolution="640x480")
        
        output2 = runner.temp_dir / "stitched_mixed.mp4"
        result = await stitch_clips([clip1, clip_hd], output2)
        runner.test(
            "Stitch mixed resolutions (re-encode)",
            result.success and output2.exists(),
            f"Warnings: {len(result.warnings)}" if result.success else result.error
        )
    except Exception as e:
        runner.test("Stitch mixed resolutions (re-encode)", False, str(e))
    
    # Test 3: Single clip (edge case)
    output3 = runner.temp_dir / "stitched_single.mp4"
    try:
        result = await stitch_clips([clip1], output3)
        runner.test("Stitch single clip", result.success)
    except Exception as e:
        runner.test("Stitch single clip", False, str(e))


async def test_color_matcher(runner: SmokeTestRunner):
    """Test the ColorMatcher module."""
    print("\n🎨 Testing Color Matcher...")
    
    # Create clips with different colors
    bright_clip = runner.temp_dir / "bright.mp4"
    dark_clip = runner.temp_dir / "dark.mp4"
    
    try:
        await create_test_video(bright_clip, duration_sec=1.0, color="white")
        await create_test_video(dark_clip, duration_sec=1.0, color="gray")
        runner.test("Create color test clips", True)
    except Exception as e:
        runner.test("Create color test clips", False, str(e))
        return
    
    # Test 1: Analyze video
    try:
        profile = await quick_analyze(bright_clip)
        runner.test(
            "Analyze color profile",
            profile.brightness > 0,
            f"Brightness: {profile.brightness:.1f}"
        )
    except Exception as e:
        runner.test("Analyze color profile", False, str(e))
    
    # Test 2: Match colors
    matcher = ColorMatcher(sample_frames=2)  # Fewer frames for speed
    output = runner.temp_dir / "color_matched.mp4"
    
    try:
        reference = await matcher.analyze_reference(bright_clip)
        result = await matcher.match_clip(dark_clip, reference, output)
        runner.test(
            "Match clip to reference",
            result.success and output.exists(),
            f"Brightness adj: {result.adjustments.get('brightness', 0):.3f}" if result.success else result.error
        )
    except Exception as e:
        runner.test("Match clip to reference", False, str(e))


async def test_audio_ducker(runner: SmokeTestRunner):
    """Test the AudioDucker module."""
    print("\n🔊 Testing Audio Ducker...")
    
    # Create test audio
    music = runner.temp_dir / "music.m4a"
    dialogue = runner.temp_dir / "dialogue.m4a"
    
    try:
        await create_test_audio(music, duration_sec=2.0, frequency=200)  # Low = music
        await create_speech_like_audio(dialogue, duration_sec=2.0)  # Speech-like
        runner.test("Create test audio", music.exists() and dialogue.exists())
    except Exception as e:
        runner.test("Create test audio", False, str(e))
        return
    
    # Test 1: Basic ducking
    ducker = AudioDucker(default_params=DuckingParams.standard())
    output = runner.temp_dir / "ducked.m4a"
    
    try:
        result = await ducker.duck(music, dialogue, output)
        runner.test(
            "Duck music under dialogue",
            result.success and output.exists(),
            f"Time: {result.processing_time_sec:.2f}s" if result.success else result.error
        )
    except Exception as e:
        runner.test("Duck music under dialogue", False, str(e))
    
    # Test 2: Duck video audio
    video_with_audio = runner.temp_dir / "video_audio.mp4"
    try:
        await create_test_video(video_with_audio, duration_sec=2.0, color="blue", with_audio=True)
        
        output_video = runner.temp_dir / "video_ducked.mp4"
        result = await ducker.duck_video(video_with_audio, dialogue, output_video)
        runner.test(
            "Duck video audio",
            result.success and output_video.exists(),
            "Video preserved" if result.success else result.error
        )
    except Exception as e:
        runner.test("Duck video audio", False, str(e))
    
    # Test 3: Preset validation
    try:
        gentle = DuckingParams.gentle()
        aggressive = DuckingParams.aggressive()
        runner.test(
            "Ducking presets",
            gentle.duck_level_db > aggressive.duck_level_db,
            f"Gentle: {gentle.duck_level_db}dB, Aggressive: {aggressive.duck_level_db}dB"
        )
    except Exception as e:
        runner.test("Ducking presets", False, str(e))


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all smoke tests."""
    print("=" * 60)
    print("  POST MODULE SMOKE TEST")
    print("=" * 60)
    
    runner = SmokeTestRunner()
    
    try:
        runner.setup()
        
        await test_ffmpeg_wrapper(runner)
        await test_stitcher(runner)
        await test_color_matcher(runner)
        await test_audio_ducker(runner)
        
    finally:
        runner.cleanup()
    
    success = runner.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())