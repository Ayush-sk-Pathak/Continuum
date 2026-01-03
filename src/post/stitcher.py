"""
Video Stitcher - Concatenates multiple clips into a single video.

This is the core assembly module. It takes a StitchJob containing:
- Ordered list of video clips
- Transition specifications between clips
- Output settings (resolution, fps, path)

And produces a single stitched video file.

Design Principles:
    - Fast path when possible: Use stream copy (no re-encoding) when clips match
    - Normalize when needed: Re-encode only if resolution/fps differ
    - Fail early: Validate everything before starting expensive operations
    - Progress tracking: Report status for long operations

Usage:
    from src.post.stitcher import Stitcher
    
    stitcher = Stitcher()
    result = await stitcher.stitch(job)
    
    if result.success:
        print(f"Output: {result.output_path}")
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import (
    VideoClip,
    TransitionSpec,
    TransitionType,
    StitchJob,
    StitchResult,
)
from .ffmpeg_wrapper import (
    probe_video,
    probe_multiple,
    run_ffmpeg,
    VideoInfo,
    FFmpegExecutionError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default output settings
DEFAULT_VIDEO_CODEC = "libx264"
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_PIXEL_FORMAT = "yuv420p"
DEFAULT_CRF = 23  # Quality: 0-51, lower = better, 23 is default

# Tolerance for considering fps "equal"
FPS_TOLERANCE = 0.1


# =============================================================================
# STITCHER CLASS
# =============================================================================

class Stitcher:
    """
    Video stitcher that concatenates clips into a final video.
    
    Supports two modes:
    1. Fast mode (stream copy): When all clips have matching specs
    2. Re-encode mode: When clips need normalization
    
    Attributes:
        temp_dir: Directory for intermediate files (auto-cleaned)
        default_codec: Video codec for re-encoding
        default_crf: Quality setting for re-encoding
    """
    
    def __init__(
        self,
        temp_dir: Optional[Path] = None,
        default_codec: str = DEFAULT_VIDEO_CODEC,
        default_crf: int = DEFAULT_CRF,
    ):
        """
        Initialize the stitcher.
        
        Args:
            temp_dir: Directory for temp files (None = system temp)
            default_codec: Video codec for re-encoding
            default_crf: Quality setting (0-51, lower = better)
        """
        self.temp_dir = temp_dir
        self.default_codec = default_codec
        self.default_crf = default_crf
    
    async def stitch(self, job: StitchJob) -> StitchResult:
        """
        Execute a stitch job.
        
        This is the main entry point. It:
        1. Validates the job
        2. Probes all input clips
        3. Decides: fast path (stream copy) or slow path (re-encode)
        4. Executes the appropriate FFmpeg command
        5. Returns the result
        
        Args:
            job: Complete stitch specification
            
        Returns:
            StitchResult with success status and output path
        """
        start_time = time.monotonic()
        
        # Step 1: Validate job
        errors = job.validate()
        if errors:
            return StitchResult.failed(f"Validation failed: {'; '.join(errors)}")
        
        logger.info(f"Starting stitch: {len(job.clips)} clips â†’ {job.output_path}")
        
        try:
            # Step 2: Probe all clips
            video_infos = await self._probe_clips(job.clips)
            
            # Step 3: Decide strategy
            can_fast_path, warnings = self._can_use_fast_path(
                video_infos, 
                job.target_resolution, 
                job.target_fps
            )
            
            # Step 4: Execute
            if can_fast_path and self._all_cuts(job.transitions):
                logger.info("Using fast path (stream copy)")
                await self._stitch_fast(job, video_infos)
            else:
                logger.info("Using re-encode path")
                await self._stitch_reencode(job, video_infos)
            
            # Step 5: Build result
            duration_sec = time.monotonic() - start_time
            
            # Probe output to get final specs
            output_info = await probe_video(job.output_path)
            
            return StitchResult(
                success=True,
                output_path=job.output_path,
                duration_sec=output_info.duration_sec,
                resolution=output_info.resolution,
                fps=output_info.fps,
                processing_time_sec=duration_sec,
                warnings=warnings,
            )
            
        except FFmpegExecutionError as e:
            logger.error(f"FFmpeg failed: {e}")
            return StitchResult.failed(f"FFmpeg error: {e}")
            
        except Exception as e:
            logger.exception(f"Stitch failed: {e}")
            return StitchResult.failed(str(e))
    
    async def stitch_simple(
        self,
        clips: List[Path],
        output_path: Path,
    ) -> StitchResult:
        """
        Simplified stitch for common case: just concatenate files.
        
        This is a convenience method that creates a StitchJob internally.
        
        Args:
            clips: List of video file paths in order
            output_path: Where to write output
            
        Returns:
            StitchResult
        """
        # Probe clips to build VideoClip objects
        infos = await probe_multiple(clips)
        
        video_clips = [
            VideoClip(
                path=info.path,
                shot_id=f"clip_{i:03d}",
                duration_sec=info.duration_sec,
                resolution=info.resolution,
                fps=info.fps,
                has_audio=info.has_audio,
            )
            for i, info in enumerate(infos)
        ]
        
        job = StitchJob(
            clips=video_clips,
            output_path=output_path,
        )
        
        return await self.stitch(job)
    
    # =========================================================================
    # INTERNAL: Probing
    # =========================================================================
    
    async def _probe_clips(self, clips: List[VideoClip]) -> List[VideoInfo]:
        """
        Probe all clips and return their VideoInfo.
        
        This runs concurrently for efficiency.
        """
        paths = [clip.path for clip in clips]
        return await probe_multiple(paths)
    
    # =========================================================================
    # INTERNAL: Strategy Decision
    # =========================================================================
    
    def _can_use_fast_path(
        self,
        infos: List[VideoInfo],
        target_resolution: Optional[Tuple[int, int]],
        target_fps: Optional[float],
    ) -> Tuple[bool, List[str]]:
        """
        Determine if we can use stream copy (fast) or must re-encode (slow).
        
        Fast path requires:
        - All clips have same resolution
        - All clips have same fps
        - No target resolution/fps override that differs
        - Same codec (preferred but not required)
        
        Returns:
            Tuple of (can_use_fast_path, list of warnings)
        """
        if len(infos) < 2:
            return True, []
        
        warnings = []
        can_fast = True
        
        first = infos[0]
        
        for i, info in enumerate(infos[1:], start=1):
            # Resolution check
            if info.resolution != first.resolution:
                warnings.append(
                    f"Resolution mismatch: clip 0 is {first.width}x{first.height}, "
                    f"clip {i} is {info.width}x{info.height}"
                )
                can_fast = False
            
            # FPS check
            if abs(info.fps - first.fps) > FPS_TOLERANCE:
                warnings.append(
                    f"FPS mismatch: clip 0 is {first.fps:.2f}, "
                    f"clip {i} is {info.fps:.2f}"
                )
                can_fast = False
            
            # Codec check - MUST block fast path to prevent silent failures
            # (VHS_VideoCombine h264 != FFmpeg libx264 h264 even with same codec name)
            if info.codec != first.codec:
                warnings.append(
                    f"Codec mismatch: clip 0 is {first.codec}, "
                    f"clip {i} is {info.codec} - forcing re-encode"
                )
                can_fast = False
            
            # Pixel format check - different formats cause playback issues
            if info.pixel_format != first.pixel_format:
                warnings.append(
                    f"Pixel format mismatch: clip 0 is {first.pixel_format}, "
                    f"clip {i} is {info.pixel_format} - forcing re-encode"
                )
                can_fast = False
        
        # Check if target differs from source
        if target_resolution and target_resolution != first.resolution:
            warnings.append(
                f"Target resolution {target_resolution} differs from source {first.resolution}"
            )
            can_fast = False
        
        if target_fps and abs(target_fps - first.fps) > FPS_TOLERANCE:
            warnings.append(
                f"Target FPS {target_fps} differs from source {first.fps}"
            )
            can_fast = False
        
        return can_fast, warnings
    
    def _all_cuts(self, transitions: List[TransitionSpec]) -> bool:
        """Check if all transitions are simple cuts (no dissolves/fades)."""
        return all(t.type == TransitionType.CUT for t in transitions)
    
    # =========================================================================
    # INTERNAL: Fast Path (Stream Copy)
    # =========================================================================
    
    async def _stitch_fast(
        self,
        job: StitchJob,
        infos: List[VideoInfo],
    ) -> None:
        """
        Stitch using stream copy (no re-encoding).
        
        This is MUCH faster but requires all clips to have matching specs.
        Uses FFmpeg's concat demuxer.
        """
        # Create concat file list
        concat_file = await self._create_concat_file(job.clips)
        
        try:
            # Build FFmpeg command
            args = [
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",  # Stream copy - no re-encoding
                str(job.output_path),
            ]
            
            await run_ffmpeg(args, output_path=job.output_path)
            
        finally:
            # Cleanup temp file
            concat_file.unlink(missing_ok=True)
    
    async def _create_concat_file(self, clips: List[VideoClip]) -> Path:
        """
        Create a concat demuxer file listing all clips.
        
        Format:
            file '/path/to/clip1.mp4'
            file '/path/to/clip2.mp4'
            ...
        """
        # Create temp file
        if self.temp_dir:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            concat_file = self.temp_dir / "concat_list.txt"
        else:
            concat_file = Path(tempfile.mktemp(suffix=".txt"))
        
        # Write file list
        lines = [f"file '{clip.path.absolute()}'" for clip in clips]
        concat_file.write_text("\n".join(lines))
        
        logger.debug(f"Created concat file: {concat_file}")
        return concat_file
    
    # =========================================================================
    # INTERNAL: Re-encode Path
    # =========================================================================
    
    async def _stitch_reencode(
        self,
        job: StitchJob,
        infos: List[VideoInfo],
    ) -> None:
        """
        Stitch with re-encoding for normalization.
        
        This handles:
        - Resolution differences (scales to target)
        - FPS differences (converts to target)
        - Transitions other than cuts (dissolves, fades)
        
        Uses FFmpeg's filter_complex for flexibility.
        """
        # Determine target specs
        target_res = job.target_resolution or infos[0].resolution
        target_fps = job.target_fps or infos[0].fps
        
        # Check if we have any non-cut transitions
        has_transitions = not self._all_cuts(job.transitions)
        
        if has_transitions:
            await self._stitch_with_transitions(job, infos, target_res, target_fps)
        else:
            await self._stitch_normalize_only(job, infos, target_res, target_fps)
    
    async def _stitch_normalize_only(
        self,
        job: StitchJob,
        infos: List[VideoInfo],
        target_res: Tuple[int, int],
        target_fps: float,
    ) -> None:
        """
        Re-encode to normalize specs, but no fancy transitions.
        
        Uses filter_complex to scale/fps-convert each input, then concat.
        """
        n = len(job.clips)
        
        # Build input args
        input_args = []
        for clip in job.clips:
            input_args.extend(["-i", str(clip.path)])
        
        # Build filter graph
        # Each input gets scaled and fps-converted, then all are concatenated
        filter_parts = []
        concat_inputs = []
        
        for i in range(n):
            # Scale and fps filter for each input
            filter_parts.append(
                f"[{i}:v]scale={target_res[0]}:{target_res[1]},"
                f"fps={target_fps},"
                f"format={DEFAULT_PIXEL_FORMAT}[v{i}]"
            )
            concat_inputs.append(f"[v{i}]")
        
        # Concat filter
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]"
        )
        
        filter_complex = ";".join(filter_parts)
        
        # Build full command
        args = (
            input_args +
            ["-filter_complex", filter_complex] +
            ["-map", "[outv]"] +
            ["-c:v", self.default_codec] +
            ["-crf", str(self.default_crf)] +
            ["-preset", "medium"] +
            [str(job.output_path)]
        )
        
        await run_ffmpeg(args, output_path=job.output_path)
    
    async def _stitch_with_transitions(
        self,
        job: StitchJob,
        infos: List[VideoInfo],
        target_res: Tuple[int, int],
        target_fps: float,
    ) -> None:
        """
        Stitch with transitions (dissolves, fades, etc.).
        
        This is the most complex path. It uses xfade filter for transitions.
        """
        n = len(job.clips)
        
        if n == 1:
            # Single clip, just re-encode
            await self._stitch_normalize_only(job, infos, target_res, target_fps)
            return
        
        # Build input args
        input_args = []
        for clip in job.clips:
            input_args.extend(["-i", str(clip.path)])
        
        # Calculate durations for offset calculation
        durations = [info.duration_sec for info in infos]
        
        # Build filter graph with xfade transitions
        filter_parts = []
        
        # First, normalize all inputs
        for i in range(n):
            filter_parts.append(
                f"[{i}:v]scale={target_res[0]}:{target_res[1]},"
                f"fps={target_fps},"
                f"format={DEFAULT_PIXEL_FORMAT}[v{i}]"
            )
        
        # Chain xfade transitions
        # v0 xfade v1 -> tmp1
        # tmp1 xfade v2 -> tmp2
        # ...
        
        current_input = "[v0]"
        cumulative_duration = durations[0]
        
        for i, transition in enumerate(job.transitions):
            next_input = f"[v{i+1}]"
            output = f"[tmp{i}]" if i < len(job.transitions) - 1 else "[outv]"
            
            # Calculate offset (when transition starts)
            offset = cumulative_duration - transition.duration_sec
            
            # Get xfade transition type
            xfade_type = self._transition_to_xfade(transition.type)
            
            filter_parts.append(
                f"{current_input}{next_input}xfade="
                f"transition={xfade_type}:"
                f"duration={transition.duration_sec}:"
                f"offset={offset:.3f}{output}"
            )
            
            # Update for next iteration
            current_input = output
            cumulative_duration += durations[i+1] - transition.duration_sec
        
        filter_complex = ";".join(filter_parts)
        
        # Build full command
        args = (
            input_args +
            ["-filter_complex", filter_complex] +
            ["-map", "[outv]"] +
            ["-c:v", self.default_codec] +
            ["-crf", str(self.default_crf)] +
            ["-preset", "medium"] +
            [str(job.output_path)]
        )
        
        await run_ffmpeg(args, output_path=job.output_path)
    
    def _transition_to_xfade(self, transition_type: TransitionType) -> str:
        """Convert our TransitionType to FFmpeg xfade transition name."""
        mapping = {
            TransitionType.CUT: "fade",  # Instant (duration=0)
            TransitionType.DISSOLVE: "fade",
            TransitionType.FADE_BLACK: "fadeblack",
            TransitionType.FADE_WHITE: "fadewhite",
            TransitionType.WIPE_LEFT: "wipeleft",
            TransitionType.WIPE_RIGHT: "wiperight",
        }
        return mapping.get(transition_type, "fade")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def stitch_clips(
    clips: List[Path],
    output_path: Path,
) -> StitchResult:
    """
    Convenience function to stitch clips without creating a Stitcher instance.
    
    Args:
        clips: List of video paths in order
        output_path: Where to write output
        
    Returns:
        StitchResult
    """
    stitcher = Stitcher()
    return await stitcher.stitch_simple(clips, output_path)


async def stitch_with_dissolves(
    clips: List[Path],
    output_path: Path,
    dissolve_duration: float = 0.5,
) -> StitchResult:
    """
    Convenience function to stitch clips with cross-dissolves between them.
    
    Args:
        clips: List of video paths in order
        output_path: Where to write output
        dissolve_duration: Duration of each dissolve in seconds
        
    Returns:
        StitchResult
    """
    # Probe clips
    infos = await probe_multiple(clips)
    
    video_clips = [
        VideoClip(
            path=info.path,
            shot_id=f"clip_{i:03d}",
            duration_sec=info.duration_sec,
            resolution=info.resolution,
            fps=info.fps,
            has_audio=info.has_audio,
        )
        for i, info in enumerate(infos)
    ]
    
    # Create dissolve transitions
    transitions = [
        TransitionSpec.dissolve(dissolve_duration)
        for _ in range(len(clips) - 1)
    ]
    
    job = StitchJob(
        clips=video_clips,
        output_path=output_path,
        transitions=transitions,
    )
    
    stitcher = Stitcher()
    return await stitcher.stitch(job)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "Stitcher",
    "stitch_clips",
    "stitch_with_dissolves",
]