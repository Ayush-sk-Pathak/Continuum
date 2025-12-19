"""
Sonic Module - Type Definitions

All dataclasses, enums, and type contracts for the Sonic module.
Separated from implementation to keep __init__.py slim and avoid circular imports.

Key Types:
    - SonicManifest: Master audio plan from Director (input to this module)
    - DialogueLine / SynthesizedDialogue: TTS input/output
    - AmbienceSpec / SynthesizedAmbience: Background audio input/output
    - FoleyEvent / SynthesizedFoley: Sound effects input/output
    - MixResult: Final mixed audio output
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime


# =============================================================================
# ENUMS
# =============================================================================

class TTSProvider(Enum):
    """Supported text-to-speech providers."""
    ELEVENLABS = auto()    # High quality, expressive (default)
    OPENAI = auto()        # Fast, good quality
    LOCAL = auto()         # Coqui/XTTS for offline (future)


class VoiceEmotion(Enum):
    """Emotional tone for dialogue delivery."""
    NEUTRAL = auto()
    HAPPY = auto()
    SAD = auto()
    ANGRY = auto()
    FEARFUL = auto()
    SURPRISED = auto()
    WHISPER = auto()
    SHOUTING = auto()


class AmbienceType(Enum):
    """Categories of ambient background audio."""
    SILENCE = auto()       # Room tone only
    INTERIOR_QUIET = auto()  # Office, bedroom
    INTERIOR_BUSY = auto()   # Restaurant, mall
    EXTERIOR_URBAN = auto()  # City street, traffic
    EXTERIOR_NATURE = auto() # Forest, beach, park
    EXTERIOR_WEATHER = auto() # Rain, wind, thunder
    CROWD = auto()           # Stadium, concert
    INDUSTRIAL = auto()      # Factory, construction
    # Aliases for simpler usage in main.py
    INTERIOR = auto()        # General interior
    URBAN = auto()           # General urban  
    NATURE = auto()          # General nature
    WATER = auto()           # Water sounds


class FoleyCategory(Enum):
    """Categories of sound effects."""
    FOOTSTEPS = auto()
    DOOR = auto()
    IMPACT = auto()        # Punch, crash, fall
    OBJECT = auto()        # Pick up, put down, slide
    CLOTH = auto()         # Rustling, movement
    LIQUID = auto()        # Pour, splash, drink
    ELECTRONIC = auto()    # Beep, buzz, notification
    VEHICLE = auto()       # Engine, horn, brakes
    NATURE = auto()        # Animal, wind, water
    CUSTOM = auto()        # User-specified


class AudioGenerationStatus(Enum):
    """Status of an audio generation job."""
    PENDING = auto()
    GENERATING = auto()
    COMPLETE = auto()
    FAILED = auto()
    SKIPPED = auto()       # Intentionally not generated (e.g., silent scene)


# =============================================================================
# VOICE & CHARACTER CONFIGURATION
# =============================================================================

@dataclass
class VoiceConfig:
    """
    Configuration for a character's voice.
    
    Stored in ConsistencyDict alongside visual assets.
    Maps a character_id to their canonical voice settings.
    
    Attributes:
        character_id: Links to ConsistencyDict entity
        provider: Which TTS service to use
        voice_id: Provider-specific voice identifier
        speaking_rate: Speed multiplier (1.0 = normal)
        pitch_shift: Semitones to shift (-12 to +12)
        default_emotion: Baseline emotional tone
        custom_params: Provider-specific settings
    """
    character_id: str
    provider: TTSProvider = TTSProvider.ELEVENLABS
    voice_id: str = ""  # e.g., "21m00Tcm4TlvDq8ikWAM" for ElevenLabs
    speaking_rate: float = 1.0
    pitch_shift: float = 0.0
    default_emotion: VoiceEmotion = VoiceEmotion.NEUTRAL
    custom_params: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Clamp values to valid ranges
        self.speaking_rate = max(0.5, min(2.0, self.speaking_rate))
        self.pitch_shift = max(-12.0, min(12.0, self.pitch_shift))


# =============================================================================
# DIALOGUE STRUCTURES
# =============================================================================

@dataclass
class DialogueLine:
    """
    A single line of dialogue to be synthesized.
    
    This is the atomic unit of speech generation. The TTS engine
    processes these one at a time, allowing granular retakes.
    
    Attributes:
        line_id: Unique identifier for this line
        character_id: Who is speaking (links to VoiceConfig)
        text: The actual dialogue text
        start_time_sec: When this line starts in the shot timeline
        emotion: Emotional override (None = use character default)
        direction: Acting notes (e.g., "sarcastically", "under breath")
        shot_id: Which shot this belongs to
        scene_id: Which scene this belongs to
    """
    line_id: str
    character_id: str
    text: str
    start_time_sec: float
    emotion: Optional[VoiceEmotion] = None
    direction: Optional[str] = None
    shot_id: str = ""
    scene_id: str = ""
    
    @property
    def estimated_duration_sec(self) -> float:
        """
        Rough estimate of speech duration.
        
        Rule of thumb: ~150 words per minute = 2.5 words per second.
        This is just for planning; actual duration comes from synthesis.
        """
        word_count = len(self.text.split())
        return word_count / 2.5


@dataclass
class SynthesizedDialogue:
    """
    Result of synthesizing a DialogueLine.
    
    Attributes:
        line_id: Links back to source DialogueLine
        audio_path: Path to generated .wav file
        actual_duration_sec: Real duration of audio
        sample_rate: Audio sample rate (usually 44100 or 48000)
        status: Generation status
        error: Error message if failed
        generation_time_sec: How long synthesis took
    """
    line_id: str
    audio_path: Optional[Path] = None
    actual_duration_sec: float = 0.0
    sample_rate: int = 44100
    status: AudioGenerationStatus = AudioGenerationStatus.PENDING
    error: Optional[str] = None
    generation_time_sec: float = 0.0
    
    def __post_init__(self):
        if isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)
    
    @classmethod
    def failed(cls, line_id: str, error: str) -> "SynthesizedDialogue":
        """Factory for a failed synthesis."""
        return cls(
            line_id=line_id,
            status=AudioGenerationStatus.FAILED,
            error=error
        )


# =============================================================================
# AMBIENCE STRUCTURES
# =============================================================================

@dataclass
class AmbienceSpec:
    """
    Specification for background ambient audio.
    
    Ambience runs continuously under dialogue and foley.
    It's generated once per scene (or shot if environment changes).
    
    Attributes:
        ambience_id: Unique identifier
        type: Category of ambience
        description: Natural language description for AudioLDM
        duration_sec: How long to generate
        intensity: Volume/prominence (0.0-1.0)
        loop: Whether to loop the generated audio
        shot_id: Which shot this belongs to (empty = scene-wide)
        scene_id: Which scene this belongs to
    """
    ambience_id: str
    type: AmbienceType
    description: str  # e.g., "quiet office with distant keyboard typing"
    duration_sec: float
    intensity: float = 0.5
    loop: bool = True
    shot_id: str = ""  # Empty = applies to whole scene
    scene_id: str = ""
    
    def __post_init__(self):
        self.intensity = max(0.0, min(1.0, self.intensity))


@dataclass
class SynthesizedAmbience:
    """
    Result of generating ambience audio.
    
    Attributes:
        ambience_id: Links back to source AmbienceSpec
        audio_path: Path to generated .wav file
        actual_duration_sec: Real duration (may differ from requested)
        status: Generation status
        error: Error message if failed
    """
    ambience_id: str
    audio_path: Optional[Path] = None
    actual_duration_sec: float = 0.0
    status: AudioGenerationStatus = AudioGenerationStatus.PENDING
    error: Optional[str] = None
    
    def __post_init__(self):
        if isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)


# =============================================================================
# FOLEY STRUCTURES
# =============================================================================

@dataclass
class FoleyEvent:
    """
    A single sound effect triggered at a specific time.
    
    Foley is event-driven: something happens on screen, we play a sound.
    These are typically short (< 2 seconds) and precisely timed.
    
    Attributes:
        event_id: Unique identifier
        category: Type of sound effect
        description: Natural language description for retrieval/generation
        trigger_time_sec: When to play in the shot timeline
        duration_sec: Expected duration (for overlap checking)
        volume_db: Volume adjustment from default
        shot_id: Which shot this belongs to
        scene_id: Which scene this belongs to
    """
    event_id: str
    category: FoleyCategory
    description: str  # e.g., "heavy footsteps on wooden floor"
    trigger_time_sec: float
    duration_sec: float = 1.0
    volume_db: float = 0.0
    shot_id: str = ""
    scene_id: str = ""


@dataclass
class SynthesizedFoley:
    """
    Result of retrieving/generating a foley sound.
    
    Note: Foley often comes from libraries rather than generation.
    The source field tracks where it came from.
    
    Attributes:
        event_id: Links back to source FoleyEvent
        audio_path: Path to the audio file
        source: Where this came from ("library", "generated", "custom")
        actual_duration_sec: Real duration
        status: Generation status
        error: Error message if failed
    """
    event_id: str
    audio_path: Optional[Path] = None
    source: str = "library"
    actual_duration_sec: float = 0.0
    status: AudioGenerationStatus = AudioGenerationStatus.PENDING
    error: Optional[str] = None
    
    def __post_init__(self):
        if isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)


# =============================================================================
# SONIC MANIFEST (The Master Plan)
# =============================================================================

@dataclass
class ShotAudioPlan:
    """
    Audio plan for a single shot.
    
    Groups all audio elements that belong to one shot.
    This is the unit of parallel processing.
    """
    shot_id: str
    scene_id: str
    duration_sec: float
    dialogue_lines: List[DialogueLine] = field(default_factory=list)
    ambience: Optional[AmbienceSpec] = None
    foley_events: List[FoleyEvent] = field(default_factory=list)
    
    @property
    def has_dialogue(self) -> bool:
        return len(self.dialogue_lines) > 0
    
    @property
    def has_foley(self) -> bool:
        return len(self.foley_events) > 0


@dataclass
class SonicManifest:
    """
    Complete audio specification for a scene or film.
    
    This is the primary input to the Sonic module, generated by the
    Director when parsing the script. It contains everything needed
    to synthesize all audio for a production.
    
    Attributes:
        manifest_id: Unique identifier
        project_id: Links to parent project
        voice_configs: Character voice settings
        shot_plans: Per-shot audio specifications
        global_ambience: Scene-wide ambient audio (if any)
        created_at: Timestamp
        metadata: Additional info
    """
    manifest_id: str
    project_id: str
    voice_configs: Dict[str, VoiceConfig] = field(default_factory=dict)
    shot_plans: List[ShotAudioPlan] = field(default_factory=list)
    global_ambience: Optional[AmbienceSpec] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_dialogue_lines(self) -> int:
        return sum(len(plan.dialogue_lines) for plan in self.shot_plans)
    
    @property
    def total_foley_events(self) -> int:
        return sum(len(plan.foley_events) for plan in self.shot_plans)
    
    @property
    def total_duration_sec(self) -> float:
        return sum(plan.duration_sec for plan in self.shot_plans)
    
    def get_voice_config(self, character_id: str) -> Optional[VoiceConfig]:
        """Get voice config for a character, or None if not found."""
        return self.voice_configs.get(character_id)
    
    def validate(self) -> List[str]:
        """
        Validate the manifest for completeness.
        
        Returns:
            List of error/warning messages (empty if valid)
        """
        issues = []
        
        # Check all dialogue has voice configs
        for plan in self.shot_plans:
            for line in plan.dialogue_lines:
                if line.character_id not in self.voice_configs:
                    issues.append(
                        f"Missing voice config for character '{line.character_id}' "
                        f"(line: {line.line_id})"
                    )
        
        # Check for overlapping dialogue in same shot
        for plan in self.shot_plans:
            lines = sorted(plan.dialogue_lines, key=lambda x: x.start_time_sec)
            for i in range(len(lines) - 1):
                end_time = lines[i].start_time_sec + lines[i].estimated_duration_sec
                if end_time > lines[i + 1].start_time_sec:
                    issues.append(
                        f"Possible dialogue overlap in shot {plan.shot_id}: "
                        f"{lines[i].line_id} may run into {lines[i + 1].line_id}"
                    )
        
        return issues


# =============================================================================
# MIX RESULT
# =============================================================================

@dataclass
class MixResult:
    """
    Result of mixing all audio for a shot or scene.
    
    Attributes:
        mix_id: Unique identifier
        shot_id: Which shot this mix is for
        output_path: Path to final mixed audio
        duration_sec: Duration of mixed audio
        component_count: Number of audio sources mixed
        peak_db: Peak volume level
        status: Mix status
        error: Error message if failed
        warnings: Non-fatal issues
    """
    mix_id: str
    shot_id: str
    output_path: Optional[Path] = None
    duration_sec: float = 0.0
    component_count: int = 0
    peak_db: float = 0.0
    status: AudioGenerationStatus = AudioGenerationStatus.PENDING
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if isinstance(self.output_path, str):
            self.output_path = Path(self.output_path)
    
    @classmethod
    def failed(cls, mix_id: str, shot_id: str, error: str) -> "MixResult":
        """Factory for a failed mix."""
        return cls(
            mix_id=mix_id,
            shot_id=shot_id,
            status=AudioGenerationStatus.FAILED,
            error=error
        )