"""
Color Matcher - Normalizes color/brightness across video clips.

AI video generators often produce slightly different color grades per shot,
even with the same prompt. This module fixes that by matching all clips
to a "master shot" reference.

Methods:
    1. MEAN_STD: Match mean and standard deviation of RGB channels (fast)
    2. HISTOGRAM: Full histogram matching (more accurate, slower)

Design Principles:
    - Non-destructive: Creates new files, doesn't modify originals
    - Batch-friendly: Process multiple clips against one reference
    - FFmpeg-based: Uses proven filters, not custom pixel manipulation

Usage:
    from src.post.color_match import ColorMatcher
    
    matcher = ColorMatcher()
    
    # Analyze master shot
    reference = await matcher.analyze_reference(master_clip_path)
    
    # Match other clips to it
    matched_path = await matcher.match_clip(clip_path, reference, output_path)
"""

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from . import ColorMatchMethod
from .ffmpeg_wrapper import (
    probe_video,
    run_ffmpeg,
    extract_frame,
    VideoInfo,
    FFmpegExecutionError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Number of frames to sample for analysis (more = accurate, slower)
DEFAULT_SAMPLE_FRAMES = 5

# Frame positions to sample (as fraction of duration)
SAMPLE_POSITIONS = [0.1, 0.3, 0.5, 0.7, 0.9]


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ChannelStats:
    """
    Statistics for a single color channel.
    
    Attributes:
        mean: Average value (0-255)
        std: Standard deviation
        min: Minimum value
        max: Maximum value
        median: Median value
    """
    mean: float
    std: float
    min: float = 0.0
    max: float = 255.0
    median: float = 128.0


@dataclass
class ColorProfile:
    """
    Color profile of a video or image.
    
    Contains statistics for each RGB channel plus luminance.
    This is what we match against.
    
    Attributes:
        source_path: Path to the analyzed video/image
        red: Red channel statistics
        green: Green channel statistics
        blue: Blue channel statistics
        luminance: Overall brightness statistics
        sample_count: Number of frames analyzed
        metadata: Additional analysis info
    """
    source_path: Path
    red: ChannelStats
    green: ChannelStats
    blue: ChannelStats
    luminance: ChannelStats
    sample_count: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def brightness(self) -> float:
        """Overall brightness (0-255)."""
        return self.luminance.mean
    
    @property
    def contrast(self) -> float:
        """Contrast estimate based on luminance std."""
        return self.luminance.std
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/logging."""
        return {
            "source_path": str(self.source_path),
            "red": {"mean": self.red.mean, "std": self.red.std},
            "green": {"mean": self.green.mean, "std": self.green.std},
            "blue": {"mean": self.blue.mean, "std": self.blue.std},
            "luminance": {"mean": self.luminance.mean, "std": self.luminance.std},
            "sample_count": self.sample_count,
        }


@dataclass
class ColorMatchResult:
    """
    Result of a color matching operation.
    
    Attributes:
        success: Whether matching succeeded
        output_path: Path to the color-matched video
        reference_profile: The profile we matched to
        original_profile: The clip's original profile
        adjustments: What corrections were applied
        processing_time_sec: How long it took
        error: Error message if failed
    """
    success: bool
    output_path: Optional[Path] = None
    reference_profile: Optional[ColorProfile] = None
    original_profile: Optional[ColorProfile] = None
    adjustments: Dict[str, float] = field(default_factory=dict)
    processing_time_sec: float = 0.0
    error: Optional[str] = None
    
    @classmethod
    def failed(cls, error: str) -> "ColorMatchResult":
        """Factory for failed result."""
        return cls(success=False, error=error)


# =============================================================================
# COLOR MATCHER CLASS
# =============================================================================

class ColorMatcher:
    """
    Matches color/brightness of video clips to a reference.
    
    This solves the "every AI shot looks slightly different" problem
    by normalizing all clips to match a master shot.
    
    Attributes:
        method: Which matching algorithm to use
        temp_dir: Directory for intermediate files
        sample_frames: How many frames to analyze per clip
    """
    
    def __init__(
        self,
        method: ColorMatchMethod = ColorMatchMethod.MEAN_STD,
        temp_dir: Optional[Path] = None,
        sample_frames: int = DEFAULT_SAMPLE_FRAMES,
    ):
        """
        Initialize the color matcher.
        
        Args:
            method: MEAN_STD (fast) or HISTOGRAM (accurate)
            temp_dir: Where to store temp files (None = system temp)
            sample_frames: Frames to sample for analysis
        """
        self.method = method
        self.temp_dir = temp_dir
        self.sample_frames = sample_frames
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    async def analyze_reference(self, video_path: Path) -> ColorProfile:
        """
        Analyze a video to create a color profile reference.
        
        This is typically called on the "master shot" that other
        clips should match.
        
        Args:
            video_path: Path to the reference video
            
        Returns:
            ColorProfile that can be used for matching
        """
        video_path = Path(video_path)
        logger.info(f"Analyzing reference: {video_path}")
        
        # Extract sample frames
        frames = await self._extract_sample_frames(video_path)
        
        try:
            # Analyze each frame
            profiles = []
            for frame_path in frames:
                profile = await self._analyze_frame(frame_path)
                profiles.append(profile)
            
            # Average the profiles
            return self._average_profiles(profiles, video_path)
            
        finally:
            # Cleanup temp frames
            for frame in frames:
                frame.unlink(missing_ok=True)
    
    async def match_clip(
        self,
        clip_path: Path,
        reference: ColorProfile,
        output_path: Path,
    ) -> ColorMatchResult:
        """
        Match a clip's colors to a reference profile.
        
        Args:
            clip_path: Video to color-correct
            reference: Profile to match (from analyze_reference)
            output_path: Where to write the corrected video
            
        Returns:
            ColorMatchResult with success status and adjustments made
        """
        import time
        start_time = time.monotonic()
        
        clip_path = Path(clip_path)
        output_path = Path(output_path)
        
        logger.info(f"Matching {clip_path.name} to reference")
        
        try:
            # Analyze the clip
            clip_profile = await self.analyze_reference(clip_path)
            
            # Calculate adjustments needed
            adjustments = self._calculate_adjustments(clip_profile, reference)
            
            # Apply adjustments via FFmpeg
            await self._apply_color_correction(
                clip_path, 
                output_path, 
                adjustments
            )
            
            processing_time = time.monotonic() - start_time
            
            return ColorMatchResult(
                success=True,
                output_path=output_path,
                reference_profile=reference,
                original_profile=clip_profile,
                adjustments=adjustments,
                processing_time_sec=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Color matching failed: {e}")
            return ColorMatchResult.failed(str(e))
    
    async def match_batch(
        self,
        clip_paths: List[Path],
        reference: ColorProfile,
        output_dir: Path,
    ) -> List[ColorMatchResult]:
        """
        Match multiple clips to the same reference.
        
        More efficient than calling match_clip repeatedly because
        it can parallelize analysis.
        
        Args:
            clip_paths: Videos to color-correct
            reference: Profile to match
            output_dir: Directory for output files
            
        Returns:
            List of ColorMatchResult in same order as input
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Process clips (could parallelize, but FFmpeg is CPU-heavy)
        results = []
        for clip_path in clip_paths:
            output_path = output_dir / f"matched_{clip_path.name}"
            result = await self.match_clip(clip_path, reference, output_path)
            results.append(result)
        
        return results
    
    async def auto_match(
        self,
        clip_paths: List[Path],
        output_dir: Path,
        master_index: int = 0,
    ) -> Tuple[ColorProfile, List[ColorMatchResult]]:
        """
        Convenience method: analyze master and match all others.
        
        Args:
            clip_paths: All clips (including master)
            output_dir: Directory for output files
            master_index: Which clip is the master (default: first)
            
        Returns:
            Tuple of (reference_profile, list of results)
        """
        if not clip_paths:
            raise ValueError("No clips provided")
        
        if master_index >= len(clip_paths):
            raise ValueError(f"Master index {master_index} out of range")
        
        # Analyze master
        master_path = clip_paths[master_index]
        reference = await self.analyze_reference(master_path)
        
        # Match all clips (including master, for consistency)
        results = await self.match_batch(clip_paths, reference, output_dir)
        
        return reference, results
    
    # =========================================================================
    # INTERNAL: Frame Extraction
    # =========================================================================
    
    async def _extract_sample_frames(self, video_path: Path) -> List[Path]:
        """
        Extract evenly-spaced frames from a video for analysis.
        
        Returns paths to temporary frame files.
        
        Handles short videos by reducing sample count.
        """
        info = await probe_video(video_path)
        duration = info.duration_sec
        
        # Create temp directory for frames
        if self.temp_dir:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            frame_dir = self.temp_dir
        else:
            frame_dir = Path(tempfile.mkdtemp())
        
        frames = []
        
        # Adjust sample count for short videos
        # For very short videos (<2s), take fewer samples to avoid extraction failures
        effective_sample_count = self.sample_frames
        if duration < 2.0:
            # For videos under 2 seconds, just take 1-2 frames
            effective_sample_count = max(1, min(2, int(duration * 2)))
        elif duration < 5.0:
            # For videos under 5 seconds, limit to 3 frames
            effective_sample_count = min(3, self.sample_frames)
        
        # Calculate positions based on actual sample count
        if effective_sample_count == 1:
            positions = [0.5]  # Just grab the middle
        elif effective_sample_count == 2:
            positions = [0.25, 0.75]
        else:
            # Use evenly spaced positions, avoiding very start/end
            positions = SAMPLE_POSITIONS[:effective_sample_count]
        
        for i, pos in enumerate(positions):
            time_sec = duration * pos
            # Clamp to valid range (leave small margin at edges)
            time_sec = max(0.01, min(duration - 0.01, time_sec))
            frame_path = frame_dir / f"sample_{video_path.stem}_{i:02d}.png"
            
            try:
                await extract_frame(video_path, frame_path, time_sec)
                if frame_path.exists():
                    frames.append(frame_path)
            except Exception as e:
                logger.warning(f"Failed to extract frame at {time_sec:.2f}s: {e}")
        
        if not frames:
            raise ValueError(f"Could not extract any frames from {video_path}")
        
        return frames
    
    # =========================================================================
    # INTERNAL: Analysis
    # =========================================================================
    
    async def _analyze_frame(self, frame_path: Path) -> ColorProfile:
        """
        Analyze a single frame to extract color statistics.
        
        Uses FFmpeg's signalstats filter for accurate measurement.
        """
        # FFmpeg command to get color statistics
        # signalstats outputs: Yavg, Ymin, Ymax, etc. for each component
        args = [
            "-i", str(frame_path),
            "-vf", "signalstats=stat=tout+vrep+brng,metadata=mode=print",
            "-f", "null",
            "-",
        ]
        
        try:
            # Run FFmpeg and capture stderr (where stats are printed)
            from .ffmpeg_wrapper import check_ffmpeg_installed
            check_ffmpeg_installed()
            
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            stats_output = stderr.decode(errors="replace")
            
            # Parse the statistics
            return self._parse_signalstats(stats_output, frame_path)
            
        except Exception as e:
            logger.warning(f"signalstats failed, using fallback: {e}")
            return await self._analyze_frame_fallback(frame_path)
    
    def _parse_signalstats(self, output: str, source_path: Path) -> ColorProfile:
        """
        Parse FFmpeg signalstats output.
        
        Example output lines:
            [Parsed_signalstats_0 @ ...] YAVG=128.5 YMIN=16 YMAX=235
        """
        # Default values if parsing fails
        y_avg, y_std = 128.0, 50.0
        u_avg, v_avg = 128.0, 128.0
        
        # Look for key statistics in output
        for line in output.split("\n"):
            if "YAVG" in line:
                # Parse Y (luminance) average
                try:
                    parts = line.split()
                    for part in parts:
                        if part.startswith("YAVG="):
                            y_avg = float(part.split("=")[1])
                        elif part.startswith("UAVG="):
                            u_avg = float(part.split("=")[1])
                        elif part.startswith("VAVG="):
                            v_avg = float(part.split("=")[1])
                except (ValueError, IndexError):
                    pass
        
        # Convert YUV-ish stats to RGB-ish profile
        # This is approximate but works for matching purposes
        return ColorProfile(
            source_path=source_path,
            red=ChannelStats(mean=y_avg + (v_avg - 128) * 0.5, std=y_std * 0.9),
            green=ChannelStats(mean=y_avg - (u_avg - 128) * 0.2 - (v_avg - 128) * 0.2, std=y_std),
            blue=ChannelStats(mean=y_avg + (u_avg - 128) * 0.5, std=y_std * 0.9),
            luminance=ChannelStats(mean=y_avg, std=y_std),
            sample_count=1,
        )
    
    async def _analyze_frame_fallback(self, frame_path: Path) -> ColorProfile:
        """
        Fallback analysis using simpler FFmpeg filters.
        
        Used when signalstats isn't available or fails.
        """
        # Use a simple approach: get average color via scale to 1x1
        args = [
            "-i", str(frame_path),
            "-vf", "scale=1:1",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-",
        ]
        
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        
        if len(stdout) >= 3:
            r, g, b = stdout[0], stdout[1], stdout[2]
        else:
            r, g, b = 128, 128, 128
        
        # Estimate luminance
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        
        return ColorProfile(
            source_path=frame_path,
            red=ChannelStats(mean=float(r), std=50.0),
            green=ChannelStats(mean=float(g), std=50.0),
            blue=ChannelStats(mean=float(b), std=50.0),
            luminance=ChannelStats(mean=luminance, std=50.0),
            sample_count=1,
        )
    
    def _average_profiles(
        self, 
        profiles: List[ColorProfile], 
        source_path: Path
    ) -> ColorProfile:
        """
        Average multiple frame profiles into one video profile.
        """
        if not profiles:
            raise ValueError("No profiles to average")
        
        if len(profiles) == 1:
            return profiles[0]
        
        # Average each channel
        def avg_channel(channels: List[ChannelStats]) -> ChannelStats:
            return ChannelStats(
                mean=sum(c.mean for c in channels) / len(channels),
                std=sum(c.std for c in channels) / len(channels),
                min=min(c.min for c in channels),
                max=max(c.max for c in channels),
            )
        
        return ColorProfile(
            source_path=source_path,
            red=avg_channel([p.red for p in profiles]),
            green=avg_channel([p.green for p in profiles]),
            blue=avg_channel([p.blue for p in profiles]),
            luminance=avg_channel([p.luminance for p in profiles]),
            sample_count=len(profiles),
        )
    
    # =========================================================================
    # INTERNAL: Adjustment Calculation
    # =========================================================================
    
    def _calculate_adjustments(
        self,
        source: ColorProfile,
        target: ColorProfile,
    ) -> Dict[str, float]:
        """
        Calculate FFmpeg filter parameters to match source to target.
        
        Returns adjustment values for brightness, contrast, saturation,
        and RGB channel shifts.
        """
        adjustments = {}
        
        # Brightness adjustment (based on luminance mean)
        # FFmpeg eq filter: brightness is -1.0 to 1.0
        lum_diff = target.luminance.mean - source.luminance.mean
        adjustments["brightness"] = lum_diff / 255.0  # Normalize to -1..1
        
        # Contrast adjustment (based on luminance std)
        # FFmpeg eq filter: contrast is 0.0 to 2.0 (1.0 = no change)
        if source.luminance.std > 0:
            contrast_ratio = target.luminance.std / source.luminance.std
            adjustments["contrast"] = max(0.5, min(2.0, contrast_ratio))
        else:
            adjustments["contrast"] = 1.0
        
        # RGB channel adjustments (colorbalance filter)
        # Range is -1.0 to 1.0
        r_diff = target.red.mean - source.red.mean
        g_diff = target.green.mean - source.green.mean
        b_diff = target.blue.mean - source.blue.mean
        
        adjustments["red_shift"] = r_diff / 255.0
        adjustments["green_shift"] = g_diff / 255.0
        adjustments["blue_shift"] = b_diff / 255.0
        
        # Clamp all values to safe ranges
        adjustments["brightness"] = max(-0.5, min(0.5, adjustments["brightness"]))
        adjustments["red_shift"] = max(-0.5, min(0.5, adjustments["red_shift"]))
        adjustments["green_shift"] = max(-0.5, min(0.5, adjustments["green_shift"]))
        adjustments["blue_shift"] = max(-0.5, min(0.5, adjustments["blue_shift"]))
        
        logger.debug(f"Calculated adjustments: {adjustments}")
        return adjustments
    
    # =========================================================================
    # INTERNAL: Apply Correction
    # =========================================================================
    
    async def _apply_color_correction(
        self,
        input_path: Path,
        output_path: Path,
        adjustments: Dict[str, float],
    ) -> None:
        """
        Apply calculated adjustments to a video using FFmpeg.
        
        Uses the eq (brightness/contrast) and colorbalance filters.
        """
        # Build filter chain
        filters = []
        
        # Brightness and contrast (eq filter)
        brightness = adjustments.get("brightness", 0.0)
        contrast = adjustments.get("contrast", 1.0)
        
        if abs(brightness) > 0.01 or abs(contrast - 1.0) > 0.01:
            filters.append(f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}")
        
        # RGB balance (colorbalance filter)
        r_shift = adjustments.get("red_shift", 0.0)
        g_shift = adjustments.get("green_shift", 0.0)
        b_shift = adjustments.get("blue_shift", 0.0)
        
        if abs(r_shift) > 0.01 or abs(g_shift) > 0.01 or abs(b_shift) > 0.01:
            # colorbalance uses shadows/midtones/highlights
            # We apply to midtones for general correction
            filters.append(
                f"colorbalance=rm={r_shift:.4f}:gm={g_shift:.4f}:bm={b_shift:.4f}"
            )
        
        # If no filters needed, just copy
        if not filters:
            logger.info("No color correction needed, copying file")
            args = [
                "-i", str(input_path),
                "-c", "copy",
                str(output_path),
            ]
        else:
            filter_chain = ",".join(filters)
            logger.info(f"Applying filters: {filter_chain}")
            
            args = [
                "-i", str(input_path),
                "-vf", filter_chain,
                "-c:v", "libx264",
                "-crf", "18",  # High quality for color work
                "-preset", "medium",
                "-c:a", "copy",  # Keep audio unchanged
                str(output_path),
            ]
        
        await run_ffmpeg(args, output_path=output_path)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def match_to_master(
    clips: List[Path],
    output_dir: Path,
    master_index: int = 0,
) -> List[Path]:
    """
    Convenience function: match all clips to a master shot.
    
    Args:
        clips: List of video paths (master must be included)
        output_dir: Where to write matched clips
        master_index: Index of the master clip (default: first)
        
    Returns:
        List of paths to color-matched clips (same order as input)
    """
    matcher = ColorMatcher()
    _, results = await matcher.auto_match(clips, output_dir, master_index)
    
    return [
        result.output_path if result.success else clips[i]
        for i, result in enumerate(results)
    ]


async def quick_analyze(video_path: Path) -> ColorProfile:
    """
    Convenience function: quickly analyze a video's color profile.
    
    Args:
        video_path: Video to analyze
        
    Returns:
        ColorProfile with statistics
    """
    matcher = ColorMatcher(sample_frames=3)  # Fewer frames for speed
    return await matcher.analyze_reference(video_path)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Data structures
    "ChannelStats",
    "ColorProfile",
    "ColorMatchResult",
    
    # Main class
    "ColorMatcher",
    
    # Convenience functions
    "match_to_master",
    "quick_analyze",
]