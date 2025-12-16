"""
Continuum Engine - Post-Production Module

Handles the final assembly of generated shots into a polished video:
- Stitcher: Concatenates shots with transitions
- Color Matcher: Normalizes color across shots to match a master
- Audio Mixer: Balances music, dialogue, and ambience with smart ducking

Design Philosophy:
    This module is a "leaf node" — it sits at the end of the pipeline and
    has no upstream dependencies except video files. This isolation means:
    1. It can be tested independently with dummy files
    2. It doesn't care how videos were generated (mock, GPU, hand-drawn)
    3. It can be swapped out entirely without touching generation code

All operations wrap FFmpeg, treating it as a reliable "muscle" we orchestrate.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime


# =============================================================================
# ENUMS
# =============================================================================

class TransitionType(Enum):
    """Types of transitions between shots."""
    CUT = auto()          # Hard cut (most common)
    DISSOLVE = auto()     # Cross-dissolve
    FADE_BLACK = auto()   # Fade to black, then in
    FADE_WHITE = auto()   # Fade to white, then in
    WIPE_LEFT = auto()    # Wipe from right to left
    WIPE_RIGHT = auto()   # Wipe from left to right


class AudioTrackType(Enum):
    """Categories of audio tracks for mixing."""
    DIALOGUE = auto()     # Speech - highest priority, ducks others
    MUSIC = auto()        # Score/soundtrack - ducked during dialogue
    AMBIENCE = auto()     # Room tone, atmosphere - always low
    FOLEY = auto()        # Sound effects - mixed based on scene
    MASTER = auto()       # Final mixed output


class ColorMatchMethod(Enum):
    """Methods for matching color between shots."""
    HISTOGRAM = auto()    # Match histogram distribution (fast, good)
    MEAN_STD = auto()     # Match mean and std deviation (faster, rougher)
    NEURAL = auto()       # Neural style transfer (slow, best) - future


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class VideoClip:
    """
    Represents a single video clip for post-production.
    
    This is the input unit for the stitcher. It wraps a video file
    with metadata needed for assembly.
    
    Attributes:
        path: Path to the video file
        shot_id: Identifier linking back to scene graph
        duration_sec: Duration in seconds (cached to avoid repeated probing)
        resolution: (width, height) tuple
        fps: Frames per second
        has_audio: Whether the clip contains an audio track
        metadata: Additional info (scene_id, characters, etc.)
    """
    path: Path
    shot_id: str
    duration_sec: float
    resolution: tuple[int, int]
    fps: float
    has_audio: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Ensure path is a Path object."""
        if isinstance(self.path, str):
            self.path = Path(self.path)
    
    @property
    def exists(self) -> bool:
        """Check if the video file exists."""
        return self.path.exists()
    
    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio."""
        if self.resolution[1] == 0:
            return 0.0
        return self.resolution[0] / self.resolution[1]


@dataclass
class AudioTrack:
    """
    Represents an audio track for mixing.
    
    Attributes:
        path: Path to the audio file
        track_type: Category (dialogue, music, etc.)
        volume_db: Volume adjustment in decibels
        start_time_sec: When this track starts in the timeline
        duration_sec: Length of the track
        duck_amount_db: How much to duck when dialogue is present
    """
    path: Path
    track_type: AudioTrackType
    volume_db: float = 0.0
    start_time_sec: float = 0.0
    duration_sec: Optional[float] = None  # None = full length
    duck_amount_db: float = -12.0  # Standard ducking amount
    
    def __post_init__(self):
        if isinstance(self.path, str):
            self.path = Path(self.path)


@dataclass
class TransitionSpec:
    """
    Specification for a transition between two clips.
    
    Attributes:
        type: The transition type
        duration_sec: How long the transition takes
        params: Type-specific parameters (e.g., wipe angle)
    """
    type: TransitionType = TransitionType.CUT
    duration_sec: float = 0.0  # 0 = instant cut
    params: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def cut(cls) -> "TransitionSpec":
        """Factory for a simple hard cut."""
        return cls(type=TransitionType.CUT, duration_sec=0.0)
    
    @classmethod
    def dissolve(cls, duration_sec: float = 0.5) -> "TransitionSpec":
        """Factory for a cross-dissolve."""
        return cls(type=TransitionType.DISSOLVE, duration_sec=duration_sec)
    
    @classmethod
    def fade_black(cls, duration_sec: float = 1.0) -> "TransitionSpec":
        """Factory for fade to/from black."""
        return cls(type=TransitionType.FADE_BLACK, duration_sec=duration_sec)


@dataclass 
class StitchJob:
    """
    Complete specification for a stitch operation.
    
    This is the input to the Stitcher. It contains everything needed
    to assemble a final video from clips.
    
    Attributes:
        clips: Ordered list of video clips to stitch
        transitions: Transitions between clips (len = len(clips) - 1)
        output_path: Where to write the final video
        target_resolution: Output resolution (None = use first clip's)
        target_fps: Output frame rate (None = use first clip's)
        master_clip_index: Which clip to use as color reference (0 = first)
        audio_tracks: Additional audio to mix in
        normalize_color: Whether to apply color matching
        normalize_audio: Whether to apply audio normalization
    """
    clips: List[VideoClip]
    output_path: Path
    transitions: List[TransitionSpec] = field(default_factory=list)
    target_resolution: Optional[tuple[int, int]] = None
    target_fps: Optional[float] = None
    master_clip_index: int = 0
    audio_tracks: List[AudioTrack] = field(default_factory=list)
    normalize_color: bool = True
    normalize_audio: bool = True
    
    def __post_init__(self):
        if isinstance(self.output_path, str):
            self.output_path = Path(self.output_path)
        
        # If no transitions specified, default to cuts
        if not self.transitions and len(self.clips) > 1:
            self.transitions = [TransitionSpec.cut() for _ in range(len(self.clips) - 1)]
    
    def validate(self) -> List[str]:
        """
        Validate the job specification.
        
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        if not self.clips:
            errors.append("No clips provided")
        
        for i, clip in enumerate(self.clips):
            if not clip.exists:
                errors.append(f"Clip {i} ({clip.shot_id}) not found: {clip.path}")
        
        if len(self.transitions) != max(0, len(self.clips) - 1):
            errors.append(
                f"Transition count mismatch: got {len(self.transitions)}, "
                f"expected {len(self.clips) - 1}"
            )
        
        if self.master_clip_index >= len(self.clips):
            errors.append(
                f"Master clip index {self.master_clip_index} out of range "
                f"(only {len(self.clips)} clips)"
            )
        
        return errors
    
    @property
    def total_duration_sec(self) -> float:
        """Calculate total duration accounting for transitions."""
        if not self.clips:
            return 0.0
        
        duration = sum(clip.duration_sec for clip in self.clips)
        
        # Subtract transition overlaps
        for transition in self.transitions:
            duration -= transition.duration_sec
        
        return max(0.0, duration)


@dataclass
class StitchResult:
    """
    Result of a stitch operation.
    
    Attributes:
        success: Whether the operation completed
        output_path: Path to the output file (if successful)
        duration_sec: Final video duration
        resolution: Final resolution
        fps: Final frame rate
        processing_time_sec: How long the operation took
        warnings: Non-fatal issues encountered
        error: Error message (if failed)
    """
    success: bool
    output_path: Optional[Path] = None
    duration_sec: float = 0.0
    resolution: Optional[tuple[int, int]] = None
    fps: float = 0.0
    processing_time_sec: float = 0.0
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def failed(cls, error: str) -> "StitchResult":
        """Factory for a failed result."""
        return cls(success=False, error=error)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "TransitionType",
    "AudioTrackType",
    "ColorMatchMethod",
    
    # Data structures
    "VideoClip",
    "AudioTrack",
    "TransitionSpec",
    "StitchJob",
    "StitchResult",
]