"""
FFmpeg Wrapper - Thin abstraction over FFmpeg CLI.

This module treats FFmpeg as "reliable muscle" — it handles:
1. Probing: Extract metadata (duration, resolution, fps, codecs)
2. Execution: Run FFmpeg commands with proper error handling
3. Validation: Check FFmpeg is installed and accessible

Design Principles:
    - Async-first: All I/O operations are async for pipeline integration
    - Fail-fast: Validate inputs before spawning processes
    - Parse errors: Extract meaningful messages from FFmpeg's stderr
    - No state: Pure functions, no class instances needed for basic ops

Usage:
    from src.post.ffmpeg_wrapper import probe_video, run_ffmpeg
    
    info = await probe_video(Path("input.mp4"))
    print(f"Duration: {info.duration_sec}s, Resolution: {info.width}x{info.height}")
    
    await run_ffmpeg(["-i", "input.mp4", "-c", "copy", "output.mp4"])
"""

import asyncio
import json
import logging
import shutil
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class FFmpegError(Exception):
    """Base exception for FFmpeg operations."""
    pass


class FFmpegNotFoundError(FFmpegError):
    """FFmpeg/FFprobe not installed or not in PATH."""
    pass


class FFmpegExecutionError(FFmpegError):
    """FFmpeg command failed during execution."""
    
    def __init__(self, message: str, return_code: int, stderr: str):
        super().__init__(message)
        self.return_code = return_code
        self.stderr = stderr


class ProbeError(FFmpegError):
    """Failed to probe video metadata."""
    pass


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class VideoInfo:
    """
    Metadata extracted from a video file via FFprobe.
    
    Attributes:
        path: Path to the video file
        duration_sec: Duration in seconds
        width: Frame width in pixels
        height: Frame height in pixels
        fps: Frames per second (as float for precision)
        codec: Video codec name (e.g., "h264", "vp9")
        bitrate: Bitrate in bits per second (None if unknown)
        has_audio: Whether the file contains an audio stream
        audio_codec: Audio codec name (None if no audio)
        audio_sample_rate: Audio sample rate in Hz (None if no audio)
        frame_count: Total number of frames (estimated if not exact)
        pixel_format: Pixel format (e.g., "yuv420p")
        raw_info: Complete FFprobe output for advanced use
    """
    path: Path
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    bitrate: Optional[int] = None
    has_audio: bool = False
    audio_codec: Optional[str] = None
    audio_sample_rate: Optional[int] = None
    frame_count: Optional[int] = None
    pixel_format: Optional[str] = None
    raw_info: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def resolution(self) -> Tuple[int, int]:
        """Return (width, height) tuple."""
        return (self.width, self.height)
    
    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio."""
        if self.height == 0:
            return 0.0
        return self.width / self.height
    
    @property
    def is_portrait(self) -> bool:
        """Check if video is portrait orientation."""
        return self.height > self.width
    
    @property
    def is_landscape(self) -> bool:
        """Check if video is landscape orientation."""
        return self.width > self.height


@dataclass
class FFmpegResult:
    """
    Result of an FFmpeg execution.
    
    Attributes:
        success: Whether the command completed successfully
        return_code: Process return code
        stdout: Standard output (usually empty for FFmpeg)
        stderr: Standard error (contains progress and errors)
        duration_sec: How long the command took to run
        output_path: Path to output file (if applicable)
    """
    success: bool
    return_code: int
    stdout: str
    stderr: str
    duration_sec: float
    output_path: Optional[Path] = None


# =============================================================================
# VALIDATION
# =============================================================================

_ffmpeg_checked: bool = False
_ffprobe_checked: bool = False


def check_ffmpeg_installed() -> bool:
    """
    Check if FFmpeg is installed and accessible.
    
    Returns:
        True if FFmpeg is found
        
    Raises:
        FFmpegNotFoundError: If FFmpeg is not found
    """
    global _ffmpeg_checked
    
    if _ffmpeg_checked:
        return True
    
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise FFmpegNotFoundError(
            "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg\n"
            "  Windows: choco install ffmpeg"
        )
    
    _ffmpeg_checked = True
    logger.debug(f"FFmpeg found at: {ffmpeg_path}")
    return True


def check_ffprobe_installed() -> bool:
    """
    Check if FFprobe is installed and accessible.
    
    Returns:
        True if FFprobe is found
        
    Raises:
        FFmpegNotFoundError: If FFprobe is not found
    """
    global _ffprobe_checked
    
    if _ffprobe_checked:
        return True
    
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise FFmpegNotFoundError(
            "FFprobe not found. It usually comes with FFmpeg.\n"
            "Please install FFmpeg and ensure it's in your PATH."
        )
    
    _ffprobe_checked = True
    logger.debug(f"FFprobe found at: {ffprobe_path}")
    return True


async def get_ffmpeg_version() -> str:
    """
    Get the installed FFmpeg version string.
    
    Returns:
        Version string (e.g., "ffmpeg version 6.0")
    """
    check_ffmpeg_installed()
    
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    
    # First line contains version
    first_line = stdout.decode().split("\n")[0]
    return first_line


# =============================================================================
# PROBING
# =============================================================================

async def probe_video(path: Path) -> VideoInfo:
    """
    Extract metadata from a video file using FFprobe.
    
    Args:
        path: Path to the video file
        
    Returns:
        VideoInfo with all extracted metadata
        
    Raises:
        FileNotFoundError: If the video file doesn't exist
        ProbeError: If FFprobe fails to read the file
    """
    check_ffprobe_installed()
    
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")
    
    # FFprobe command for JSON output with all stream info
    cmd = [
        "ffprobe",
        "-v", "quiet",                    # Suppress banner
        "-print_format", "json",          # Output as JSON
        "-show_format",                   # Include format info
        "-show_streams",                  # Include stream info
        str(path),
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        raise ProbeError(f"FFprobe failed for {path}: {error_msg}")
    
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise ProbeError(f"Failed to parse FFprobe output: {e}")
    
    return _parse_probe_output(path, data)


def _parse_probe_output(path: Path, data: Dict[str, Any]) -> VideoInfo:
    """
    Parse FFprobe JSON output into VideoInfo.
    
    This is separated for easier testing and error isolation.
    """
    # Find video stream
    video_stream = None
    audio_stream = None
    
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream
    
    if video_stream is None:
        raise ProbeError(f"No video stream found in {path}")
    
    # Extract format info
    format_info = data.get("format", {})
    
    # Parse duration (try multiple sources)
    duration_sec = _parse_duration(video_stream, format_info)
    
    # Parse FPS (can be in multiple formats)
    fps = _parse_fps(video_stream)
    
    # Parse frame count
    frame_count = _parse_frame_count(video_stream, duration_sec, fps)
    
    # Parse bitrate
    bitrate = None
    if "bit_rate" in format_info:
        try:
            bitrate = int(format_info["bit_rate"])
        except (ValueError, TypeError):
            pass
    
    # Build VideoInfo
    return VideoInfo(
        path=path,
        duration_sec=duration_sec,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=fps,
        codec=video_stream.get("codec_name", "unknown"),
        bitrate=bitrate,
        has_audio=audio_stream is not None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        audio_sample_rate=int(audio_stream["sample_rate"]) if audio_stream and "sample_rate" in audio_stream else None,
        frame_count=frame_count,
        pixel_format=video_stream.get("pix_fmt"),
        raw_info=data,
    )


def _parse_duration(video_stream: Dict, format_info: Dict) -> float:
    """Parse duration from various possible sources."""
    # Try stream duration first
    if "duration" in video_stream:
        try:
            return float(video_stream["duration"])
        except (ValueError, TypeError):
            pass
    
    # Try format duration
    if "duration" in format_info:
        try:
            return float(format_info["duration"])
        except (ValueError, TypeError):
            pass
    
    # Try calculating from frame count and fps
    if "nb_frames" in video_stream and "r_frame_rate" in video_stream:
        try:
            frames = int(video_stream["nb_frames"])
            fps = _parse_fps(video_stream)
            if fps > 0:
                return frames / fps
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    
    # Default to 0 if nothing works
    logger.warning("Could not determine video duration, defaulting to 0")
    return 0.0


def _parse_fps(video_stream: Dict) -> float:
    """
    Parse FPS from video stream.
    
    FFmpeg reports FPS in various formats:
    - "30/1" (fraction)
    - "30000/1001" (NTSC 29.97)
    - "30" (integer)
    """
    # Try r_frame_rate first (real frame rate)
    fps_str = video_stream.get("r_frame_rate", video_stream.get("avg_frame_rate", "0/1"))
    
    if "/" in str(fps_str):
        try:
            num, den = fps_str.split("/")
            if int(den) != 0:
                return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            pass
    else:
        try:
            return float(fps_str)
        except ValueError:
            pass
    
    logger.warning("Could not determine FPS, defaulting to 24")
    return 24.0


def _parse_frame_count(video_stream: Dict, duration: float, fps: float) -> Optional[int]:
    """Parse or calculate frame count."""
    # Try direct frame count
    if "nb_frames" in video_stream:
        try:
            return int(video_stream["nb_frames"])
        except (ValueError, TypeError):
            pass
    
    # Calculate from duration and fps
    if duration > 0 and fps > 0:
        return int(duration * fps)
    
    return None


async def probe_multiple(paths: List[Path]) -> List[VideoInfo]:
    """
    Probe multiple videos concurrently.
    
    Args:
        paths: List of video paths to probe
        
    Returns:
        List of VideoInfo in the same order as input
    """
    tasks = [probe_video(path) for path in paths]
    return await asyncio.gather(*tasks)


# =============================================================================
# EXECUTION
# =============================================================================

async def run_ffmpeg(
    args: List[str],
    output_path: Optional[Path] = None,
    timeout_sec: Optional[float] = None,
    progress_callback: Optional[callable] = None,
) -> FFmpegResult:
    """
    Run an FFmpeg command asynchronously.
    
    Args:
        args: FFmpeg arguments (without "ffmpeg" prefix)
        output_path: Expected output file path (for validation)
        timeout_sec: Maximum execution time (None = no limit)
        progress_callback: Optional callback for progress updates
        
    Returns:
        FFmpegResult with execution details
        
    Raises:
        FFmpegNotFoundError: If FFmpeg is not installed
        FFmpegExecutionError: If the command fails
        asyncio.TimeoutError: If timeout is exceeded
    """
    check_ffmpeg_installed()
    
    # Build full command
    cmd = ["ffmpeg", "-y"] + args  # -y to overwrite output
    
    logger.debug(f"Running FFmpeg: {' '.join(cmd)}")
    
    import time
    start_time = time.monotonic()
    
    # Create subprocess
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    try:
        # Wait for completion with optional timeout
        if timeout_sec:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_sec,
            )
        else:
            stdout, stderr = await proc.communicate()
            
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    
    duration_sec = time.monotonic() - start_time
    stdout_str = stdout.decode(errors="replace")
    stderr_str = stderr.decode(errors="replace")
    
    success = proc.returncode == 0
    
    # Validate output file exists if specified
    if success and output_path:
        output_path = Path(output_path)
        if not output_path.exists():
            success = False
            stderr_str += f"\nExpected output file not created: {output_path}"
    
    result = FFmpegResult(
        success=success,
        return_code=proc.returncode,
        stdout=stdout_str,
        stderr=stderr_str,
        duration_sec=duration_sec,
        output_path=output_path if success else None,
    )
    
    if not success:
        error_msg = _extract_error_message(stderr_str)
        logger.error(f"FFmpeg failed: {error_msg}")
        raise FFmpegExecutionError(
            f"FFmpeg command failed: {error_msg}",
            return_code=proc.returncode,
            stderr=stderr_str,
        )
    
    logger.debug(f"FFmpeg completed in {duration_sec:.2f}s")
    return result


def _extract_error_message(stderr: str) -> str:
    """
    Extract the most relevant error message from FFmpeg stderr.
    
    FFmpeg stderr is verbose. This function finds the actual error.
    """
    lines = stderr.strip().split("\n")
    
    # Look for common error patterns
    error_patterns = [
        r"Error.*",
        r".*: No such file or directory",
        r".*: Invalid argument",
        r".*: Permission denied",
        r".*codec not found.*",
        r".*Unrecognized option.*",
        r".*does not contain.*stream",
    ]
    
    for line in reversed(lines):
        for pattern in error_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return line.strip()
    
    # Fallback: return last non-empty line
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    
    return "Unknown FFmpeg error"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def extract_frame(
    video_path: Path,
    output_path: Path,
    time_sec: float = 0.0,
    quality: int = 2,
) -> Path:
    """
    Extract a single frame from a video.
    
    Args:
        video_path: Source video
        output_path: Where to save the frame (e.g., frame.png)
        time_sec: Timestamp to extract (default: first frame)
        quality: JPEG quality 1-31 (lower = better, default 2)
        
    Returns:
        Path to the extracted frame
    """
    args = [
        "-ss", str(time_sec),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", str(quality),
        str(output_path),
    ]
    
    await run_ffmpeg(args, output_path=output_path)
    return output_path


async def extract_last_frame(video_path: Path, output_path: Path) -> Path:
    """
    Extract the last frame from a video.
    
    Args:
        video_path: Source video
        output_path: Where to save the frame
        
    Returns:
        Path to the extracted frame
    """
    # First probe to get duration
    info = await probe_video(video_path)
    
    # Extract frame slightly before end to avoid potential issues
    time_sec = max(0, info.duration_sec - 0.1)
    
    return await extract_frame(video_path, output_path, time_sec)


async def get_video_duration(path: Path) -> float:
    """
    Quick helper to get just the duration of a video.
    
    Args:
        path: Path to video
        
    Returns:
        Duration in seconds
    """
    info = await probe_video(path)
    return info.duration_sec


async def videos_compatible(paths: List[Path]) -> Tuple[bool, List[str]]:
    """
    Check if multiple videos are compatible for concatenation.
    
    Videos are compatible if they have the same:
    - Resolution
    - FPS
    - Codec (preferred, not required)
    
    Args:
        paths: List of video paths
        
    Returns:
        Tuple of (is_compatible, list of warnings)
    """
    if len(paths) < 2:
        return True, []
    
    infos = await probe_multiple(paths)
    warnings = []
    
    first = infos[0]
    
    for i, info in enumerate(infos[1:], start=1):
        if info.resolution != first.resolution:
            warnings.append(
                f"Resolution mismatch: clip 0 is {first.width}x{first.height}, "
                f"clip {i} is {info.width}x{info.height}"
            )
        
        if abs(info.fps - first.fps) > 0.1:
            warnings.append(
                f"FPS mismatch: clip 0 is {first.fps:.2f}fps, "
                f"clip {i} is {info.fps:.2f}fps"
            )
        
        if info.codec != first.codec:
            warnings.append(
                f"Codec mismatch: clip 0 is {first.codec}, "
                f"clip {i} is {info.codec}"
            )
    
    # Resolution and FPS mismatches are critical
    critical = any("Resolution" in w or "FPS" in w for w in warnings)
    
    return not critical, warnings


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Exceptions
    "FFmpegError",
    "FFmpegNotFoundError",
    "FFmpegExecutionError",
    "ProbeError",
    
    # Data structures
    "VideoInfo",
    "FFmpegResult",
    
    # Validation
    "check_ffmpeg_installed",
    "check_ffprobe_installed",
    "get_ffmpeg_version",
    
    # Probing
    "probe_video",
    "probe_multiple",
    
    # Execution
    "run_ffmpeg",
    
    # Convenience
    "extract_frame",
    "extract_last_frame",
    "get_video_duration",
    "videos_compatible",
]