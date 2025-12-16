"""
Continuum Engine - Pacer (The Stability Monitor)

Decides WHEN to cut between shots and chunks to maximize quality
while preventing model drift.

The Problem:
    Video generation models have a "stability window" - after ~12 seconds,
    identity starts to drift, physics get wonky, and quality degrades.
    Naive approach: cut every 12 seconds. But that ignores:
    - Dialogue timing (don't cut mid-sentence)
    - Action beats (cut AFTER the punch lands, not during)
    - Emotional moments (hold on the reaction shot)
    - Transition types (dissolve needs overlap, cut is instant)

The Solution:
    The Pacer analyzes shot content and calculates optimal cut points:
    1. Hard limit: Never exceed max_shot_duration_sec (default 12s)
    2. Soft targets: Prefer cuts at natural break points
    3. Dialogue-aware: Estimate speech timing, avoid mid-line cuts
    4. Transition-aware: Add buffer for dissolves/fades

Architecture Position:
    Scene Graph (what happens) → Pacer (when to cut) → Chunk generation
    
    Director Agent creates shots with target durations.
    Pacer divides shots into render-safe chunks.
    Bridge Engine creates seamless transitions between chunks.

Design Principles:
    1. Conservative: When in doubt, cut earlier (safer)
    2. Configurable: Thresholds from GenerationConfig
    3. Predictable: Same input → same output (no randomness)
    4. Informative: Returns reasoning with suggestions
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS & DEFAULTS
# =============================================================================

# Default timing constants
DEFAULT_MAX_CHUNK_DURATION_SEC = 12.0  # Model stability window
DEFAULT_MIN_CHUNK_DURATION_SEC = 3.0   # Too short = wasted bridge frames
DEFAULT_IDEAL_CHUNK_DURATION_SEC = 8.0  # Sweet spot for quality
DEFAULT_CUT_BUFFER_SEC = 0.5           # Safety margin before hard limit

# Dialogue timing estimates (words per second varies by emotion/character)
DEFAULT_WORDS_PER_SECOND = 2.5         # Normal speech pace
SLOW_WORDS_PER_SECOND = 1.8            # Dramatic/emotional delivery
FAST_WORDS_PER_SECOND = 3.5            # Excited/urgent delivery

# Transition timing requirements
TRANSITION_BUFFER_SEC = {
    "cut": 0.0,           # Instant cut needs no buffer
    "fade": 1.0,          # Fade needs frames for transition
    "dissolve": 1.5,      # Dissolve needs overlap
    "wipe": 0.5,          # Wipe is faster
    "match_cut": 0.0,     # Match cut is instant but needs planning
}

# Action beat keywords that suggest natural cut points
ACTION_BEAT_KEYWORDS = [
    "lands", "hits", "falls", "drops", "catches", "throws",
    "opens", "closes", "enters", "exits", "sits", "stands",
    "turns", "looks", "reacts", "realizes", "discovers",
    "finishes", "completes", "ends", "begins", "starts",
]


# =============================================================================
# ENUMS
# =============================================================================

class CutReason(str, Enum):
    """Why a cut was placed at this point."""
    MAX_DURATION = "max_duration"          # Hit the hard limit
    DIALOGUE_END = "dialogue_end"          # Natural pause in speech
    ACTION_BEAT = "action_beat"            # Action completed
    EMOTIONAL_BEAT = "emotional_beat"      # Hold for reaction
    SCENE_CHANGE = "scene_change"          # Scene boundary
    TRANSITION_BUFFER = "transition_buffer" # Buffer for transition effect
    USER_SPECIFIED = "user_specified"      # Explicit cut in script
    PACING = "pacing"                      # General pacing decision


class PacingStyle(str, Enum):
    """Overall pacing style for the project."""
    FAST = "fast"           # Action film - shorter shots, quick cuts
    NORMAL = "normal"       # Standard pacing
    SLOW = "slow"           # Drama - longer shots, lingering
    DOCUMENTARY = "documentary"  # Long takes, observational


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class DialogueTiming:
    """
    Estimated timing for a dialogue line.
    
    Attributes:
        character_id: Who is speaking
        text: The dialogue text
        estimated_start_sec: When speech begins
        estimated_end_sec: When speech ends
        word_count: Number of words
        is_interruptible: Can this be cut mid-line?
    """
    character_id: str
    text: str
    estimated_start_sec: float
    estimated_end_sec: float
    word_count: int = 0
    is_interruptible: bool = False
    
    def __post_init__(self):
        if self.word_count == 0:
            self.word_count = len(self.text.split())
    
    @property
    def duration_sec(self) -> float:
        return self.estimated_end_sec - self.estimated_start_sec
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "text": self.text,
            "estimated_start_sec": self.estimated_start_sec,
            "estimated_end_sec": self.estimated_end_sec,
            "word_count": self.word_count,
            "duration_sec": self.duration_sec,
        }


@dataclass
class CutPoint:
    """
    A suggested cut point within a shot.
    
    Attributes:
        timestamp_sec: When to cut
        reason: Why this is a good cut point
        confidence: How confident (0-1) this is optimal
        is_required: Must cut here (vs. optional suggestion)
        notes: Human-readable explanation
    """
    timestamp_sec: float
    reason: CutReason
    confidence: float = 1.0
    is_required: bool = False
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_sec": self.timestamp_sec,
            "reason": self.reason.value,
            "confidence": self.confidence,
            "is_required": self.is_required,
            "notes": self.notes,
        }


@dataclass
class ChunkPlan:
    """
    Plan for a single render chunk.
    
    Attributes:
        chunk_index: Position in sequence
        start_sec: Start timestamp
        end_sec: End timestamp
        duration_sec: Chunk length
        cut_reason: Why chunk ends here
        needs_bridge: Does this chunk need a bridge frame to next?
        dialogue_lines: Dialogue contained in this chunk
    """
    chunk_index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    cut_reason: CutReason
    needs_bridge: bool = True
    dialogue_lines: List[DialogueTiming] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "duration_sec": self.duration_sec,
            "cut_reason": self.cut_reason.value,
            "needs_bridge": self.needs_bridge,
            "dialogue_count": len(self.dialogue_lines),
        }


@dataclass
class ShotPacingPlan:
    """
    Complete pacing plan for a shot.
    
    Attributes:
        shot_id: Which shot this plans
        total_duration_sec: Total shot length
        chunks: Planned chunks
        cut_points: All identified cut points
        dialogue_timings: Dialogue timing estimates
        warnings: Any pacing concerns
    """
    shot_id: str
    total_duration_sec: float
    chunks: List[ChunkPlan]
    cut_points: List[CutPoint] = field(default_factory=list)
    dialogue_timings: List[DialogueTiming] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def chunk_count(self) -> int:
        return len(self.chunks)
    
    @property
    def avg_chunk_duration(self) -> float:
        if not self.chunks:
            return 0.0
        return sum(c.duration_sec for c in self.chunks) / len(self.chunks)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "total_duration_sec": self.total_duration_sec,
            "chunk_count": self.chunk_count,
            "avg_chunk_duration": self.avg_chunk_duration,
            "chunks": [c.to_dict() for c in self.chunks],
            "cut_points": [cp.to_dict() for cp in self.cut_points],
            "dialogue_timings": [d.to_dict() for d in self.dialogue_timings],
            "warnings": self.warnings,
        }


@dataclass 
class TransitionSuggestion:
    """
    Suggested transition between two shots.
    
    Attributes:
        from_shot_id: Outgoing shot
        to_shot_id: Incoming shot
        transition_type: Suggested transition
        confidence: How confident in suggestion
        reasoning: Why this transition type
        buffer_sec: Extra time needed for transition
    """
    from_shot_id: str
    to_shot_id: str
    transition_type: str  # "cut", "fade", "dissolve", etc.
    confidence: float = 1.0
    reasoning: str = ""
    buffer_sec: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_shot_id": self.from_shot_id,
            "to_shot_id": self.to_shot_id,
            "transition_type": self.transition_type,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "buffer_sec": self.buffer_sec,
        }


# =============================================================================
# PACER CLASS
# =============================================================================

class Pacer:
    """
    The Stability Monitor - calculates optimal cut points for shots.
    
    Usage:
        pacer = Pacer()
        
        # Plan a shot
        plan = pacer.plan_shot(
            shot_id="scene_01_shot_02",
            duration_sec=25.0,
            dialogue=[
                {"character": "alice", "line": "I can't believe you did that."},
                {"character": "bob", "line": "I had no choice."},
            ],
            description="Alice confronts Bob about the decision.",
        )
        
        print(f"Chunks needed: {plan.chunk_count}")
        for chunk in plan.chunks:
            print(f"  {chunk.start_sec:.1f}s - {chunk.end_sec:.1f}s ({chunk.cut_reason.value})")
        
        # Suggest transition
        transition = pacer.suggest_transition(
            from_shot={"shot_type": "close", "emotion": "tense"},
            to_shot={"shot_type": "wide", "emotion": "relief"},
        )
    """
    
    def __init__(
        self,
        max_chunk_duration_sec: float = DEFAULT_MAX_CHUNK_DURATION_SEC,
        min_chunk_duration_sec: float = DEFAULT_MIN_CHUNK_DURATION_SEC,
        ideal_chunk_duration_sec: float = DEFAULT_IDEAL_CHUNK_DURATION_SEC,
        pacing_style: PacingStyle = PacingStyle.NORMAL,
        words_per_second: float = DEFAULT_WORDS_PER_SECOND,
    ):
        """
        Initialize the Pacer.
        
        Args:
            max_chunk_duration_sec: Hard limit on chunk length (model stability)
            min_chunk_duration_sec: Minimum chunk length (efficiency)
            ideal_chunk_duration_sec: Target chunk length for quality
            pacing_style: Overall pacing style
            words_per_second: Default speech rate for dialogue timing
        """
        self.max_chunk_duration_sec = max_chunk_duration_sec
        self.min_chunk_duration_sec = min_chunk_duration_sec
        self.ideal_chunk_duration_sec = ideal_chunk_duration_sec
        self.pacing_style = pacing_style
        self.words_per_second = words_per_second
        
        # Adjust for pacing style
        self._apply_pacing_style()
    
    def _apply_pacing_style(self) -> None:
        """Adjust parameters based on pacing style."""
        if self.pacing_style == PacingStyle.FAST:
            self.ideal_chunk_duration_sec = min(6.0, self.ideal_chunk_duration_sec)
            self.words_per_second = FAST_WORDS_PER_SECOND
        elif self.pacing_style == PacingStyle.SLOW:
            self.ideal_chunk_duration_sec = max(10.0, self.ideal_chunk_duration_sec)
            self.words_per_second = SLOW_WORDS_PER_SECOND
        elif self.pacing_style == PacingStyle.DOCUMENTARY:
            # Documentary allows longer takes
            self.max_chunk_duration_sec = min(20.0, self.max_chunk_duration_sec + 5.0)
            self.words_per_second = SLOW_WORDS_PER_SECOND
    
    # -------------------------------------------------------------------------
    # Dialogue Timing
    # -------------------------------------------------------------------------
    
    def estimate_dialogue_timing(
        self,
        dialogue: List[Dict[str, str]],
        start_offset_sec: float = 0.5,
        pause_between_lines_sec: float = 0.8,
    ) -> List[DialogueTiming]:
        """
        Estimate timing for dialogue lines.
        
        Args:
            dialogue: List of {"character": str, "line": str} dicts
            start_offset_sec: Delay before first line
            pause_between_lines_sec: Pause between speakers
            
        Returns:
            List of DialogueTiming with estimated timestamps
        """
        timings = []
        current_time = start_offset_sec
        
        for i, line in enumerate(dialogue):
            character = line.get("character", "unknown")
            text = line.get("line", "")
            
            if not text:
                continue
            
            word_count = len(text.split())
            duration = word_count / self.words_per_second
            
            # Add reaction time if speaker changes
            if i > 0 and dialogue[i-1].get("character") != character:
                current_time += pause_between_lines_sec
            
            timing = DialogueTiming(
                character_id=character,
                text=text,
                estimated_start_sec=current_time,
                estimated_end_sec=current_time + duration,
                word_count=word_count,
            )
            timings.append(timing)
            
            current_time += duration
        
        return timings
    
    def get_dialogue_end_times(
        self,
        timings: List[DialogueTiming],
    ) -> List[float]:
        """Get timestamps where dialogue lines end (natural cut points)."""
        return [t.estimated_end_sec for t in timings]
    
    # -------------------------------------------------------------------------
    # Cut Point Analysis
    # -------------------------------------------------------------------------
    
    def find_action_beats(
        self,
        description: str,
        shot_duration_sec: float,
    ) -> List[CutPoint]:
        """
        Find action beats in shot description that suggest cut points.
        
        Analyzes description for action keywords and estimates
        when those actions might complete.
        """
        cut_points = []
        description_lower = description.lower()
        
        for keyword in ACTION_BEAT_KEYWORDS:
            if keyword in description_lower:
                # Estimate action completion time
                # This is a heuristic - in practice, LLM could provide precise timing
                position = description_lower.find(keyword)
                relative_position = position / max(len(description_lower), 1)
                
                # Map text position to approximate time in shot
                estimated_time = relative_position * shot_duration_sec
                
                # Round to reasonable timestamp
                estimated_time = max(2.0, min(shot_duration_sec - 1.0, estimated_time))
                
                cut_points.append(CutPoint(
                    timestamp_sec=estimated_time,
                    reason=CutReason.ACTION_BEAT,
                    confidence=0.6,  # Heuristic, not certain
                    is_required=False,
                    notes=f"Action beat: '{keyword}'",
                ))
        
        return cut_points
    
    def find_natural_cut_points(
        self,
        shot_duration_sec: float,
        dialogue: Optional[List[Dict[str, str]]] = None,
        description: str = "",
    ) -> List[CutPoint]:
        """
        Find all natural cut points in a shot.
        
        Combines dialogue timing, action beats, and duration limits
        to identify optimal cut locations.
        """
        cut_points = []
        
        # Always have a cut at the end
        cut_points.append(CutPoint(
            timestamp_sec=shot_duration_sec,
            reason=CutReason.SCENE_CHANGE if shot_duration_sec <= self.max_chunk_duration_sec else CutReason.MAX_DURATION,
            confidence=1.0,
            is_required=True,
            notes="End of shot",
        ))
        
        # Dialogue-based cuts
        if dialogue:
            timings = self.estimate_dialogue_timing(dialogue)
            for timing in timings:
                # Add cut point after each complete line
                if timing.estimated_end_sec < shot_duration_sec - 1.0:
                    cut_points.append(CutPoint(
                        timestamp_sec=timing.estimated_end_sec + 0.3,  # Brief pause after
                        reason=CutReason.DIALOGUE_END,
                        confidence=0.8,
                        is_required=False,
                        notes=f"After {timing.character_id}'s line",
                    ))
        
        # Action beat cuts
        if description:
            action_cuts = self.find_action_beats(description, shot_duration_sec)
            cut_points.extend(action_cuts)
        
        # Max duration enforcement
        if shot_duration_sec > self.max_chunk_duration_sec:
            # Add mandatory cuts at max_duration intervals
            time = self.max_chunk_duration_sec
            while time < shot_duration_sec:
                cut_points.append(CutPoint(
                    timestamp_sec=time,
                    reason=CutReason.MAX_DURATION,
                    confidence=1.0,
                    is_required=True,
                    notes=f"Max duration ({self.max_chunk_duration_sec}s) reached",
                ))
                time += self.max_chunk_duration_sec
        
        # Sort by timestamp
        cut_points.sort(key=lambda cp: cp.timestamp_sec)
        
        return cut_points
    
    # -------------------------------------------------------------------------
    # Chunk Planning
    # -------------------------------------------------------------------------
    
    def plan_shot(
        self,
        shot_id: str,
        duration_sec: float,
        dialogue: Optional[List[Dict[str, str]]] = None,
        description: str = "",
        transition_out: str = "cut",
    ) -> ShotPacingPlan:
        """
        Create a complete pacing plan for a shot.
        
        This is the main entry point for shot planning.
        
        Args:
            shot_id: Shot identifier
            duration_sec: Total shot duration
            dialogue: Dialogue lines in shot
            description: What happens in the shot
            transition_out: How this shot ends (affects timing)
            
        Returns:
            ShotPacingPlan with chunks and cut points
        """
        warnings = []
        
        # Estimate dialogue timing
        dialogue_timings = []
        if dialogue:
            dialogue_timings = self.estimate_dialogue_timing(dialogue)
            
            # Check if dialogue fits in duration
            if dialogue_timings:
                last_line_end = dialogue_timings[-1].estimated_end_sec
                if last_line_end > duration_sec:
                    warnings.append(
                        f"Dialogue ({last_line_end:.1f}s) exceeds shot duration ({duration_sec:.1f}s)"
                    )
        
        # Find all natural cut points
        cut_points = self.find_natural_cut_points(
            shot_duration_sec=duration_sec,
            dialogue=dialogue,
            description=description,
        )
        
        # Calculate chunks
        chunks = self._calculate_chunks(
            duration_sec=duration_sec,
            cut_points=cut_points,
            dialogue_timings=dialogue_timings,
            transition_out=transition_out,
        )
        
        # Validate chunk count
        if len(chunks) > 10:
            warnings.append(
                f"High chunk count ({len(chunks)}) - consider shortening shot"
            )
        
        return ShotPacingPlan(
            shot_id=shot_id,
            total_duration_sec=duration_sec,
            chunks=chunks,
            cut_points=cut_points,
            dialogue_timings=dialogue_timings,
            warnings=warnings,
        )
    
    def _calculate_chunks(
        self,
        duration_sec: float,
        cut_points: List[CutPoint],
        dialogue_timings: List[DialogueTiming],
        transition_out: str,
    ) -> List[ChunkPlan]:
        """
        Calculate optimal chunks from cut points.
        
        Strategy:
        1. Start with required cut points (max_duration hits)
        2. Try to use natural cut points (dialogue, action) when possible
        3. Avoid cutting mid-dialogue
        4. Ensure chunks meet minimum duration
        """
        if duration_sec <= self.max_chunk_duration_sec:
            # Single chunk - no splitting needed
            return [ChunkPlan(
                chunk_index=0,
                start_sec=0.0,
                end_sec=duration_sec,
                duration_sec=duration_sec,
                cut_reason=CutReason.SCENE_CHANGE,
                needs_bridge=False,  # Last chunk doesn't need bridge
                dialogue_lines=[d for d in dialogue_timings],
            )]
        
        # Multiple chunks needed
        chunks = []
        current_start = 0.0
        chunk_index = 0
        
        # Get required cut points (sorted by time)
        required_cuts = sorted(
            [cp for cp in cut_points if cp.is_required],
            key=lambda cp: cp.timestamp_sec
        )
        
        # Get optional cut points for optimization
        optional_cuts = sorted(
            [cp for cp in cut_points if not cp.is_required],
            key=lambda cp: (-cp.confidence, cp.timestamp_sec)  # Highest confidence first
        )
        
        for required_cut in required_cuts:
            target_end = required_cut.timestamp_sec
            
            # Look for a better natural cut point nearby
            best_cut = required_cut
            best_cut_time = target_end
            
            # Search window: within 2 seconds before the required cut
            search_start = max(current_start + self.min_chunk_duration_sec, target_end - 2.0)
            search_end = target_end
            
            for optional in optional_cuts:
                if search_start <= optional.timestamp_sec <= search_end:
                    # Check if this cut avoids mid-dialogue
                    if not self._cuts_through_dialogue(
                        optional.timestamp_sec, dialogue_timings
                    ):
                        if optional.confidence > best_cut.confidence:
                            best_cut = optional
                            best_cut_time = optional.timestamp_sec
            
            # Create chunk
            chunk_duration = best_cut_time - current_start
            
            # Ensure minimum duration
            if chunk_duration < self.min_chunk_duration_sec and chunk_index > 0:
                # Merge with previous chunk if too short
                if chunks:
                    prev_chunk = chunks[-1]
                    prev_chunk.end_sec = best_cut_time
                    prev_chunk.duration_sec = prev_chunk.end_sec - prev_chunk.start_sec
                    prev_chunk.cut_reason = best_cut.reason
                    current_start = best_cut_time
                    continue
            
            # Get dialogue lines for this chunk
            chunk_dialogue = [
                d for d in dialogue_timings
                if current_start <= d.estimated_start_sec < best_cut_time
            ]
            
            chunk = ChunkPlan(
                chunk_index=chunk_index,
                start_sec=current_start,
                end_sec=best_cut_time,
                duration_sec=chunk_duration,
                cut_reason=best_cut.reason,
                needs_bridge=True,  # Will update last chunk below
                dialogue_lines=chunk_dialogue,
            )
            chunks.append(chunk)
            
            current_start = best_cut_time
            chunk_index += 1
        
        # Last chunk doesn't need bridge (end of shot)
        if chunks:
            chunks[-1].needs_bridge = (transition_out in ["dissolve", "fade"])
        
        return chunks
    
    def _cuts_through_dialogue(
        self,
        cut_time: float,
        dialogue_timings: List[DialogueTiming],
        buffer_sec: float = 0.3,
    ) -> bool:
        """Check if a cut time falls during someone speaking."""
        for timing in dialogue_timings:
            if timing.estimated_start_sec + buffer_sec < cut_time < timing.estimated_end_sec - buffer_sec:
                return True
        return False
    
    # -------------------------------------------------------------------------
    # Transition Suggestions
    # -------------------------------------------------------------------------
    
    def suggest_transition(
        self,
        from_shot: Dict[str, Any],
        to_shot: Dict[str, Any],
    ) -> TransitionSuggestion:
        """
        Suggest transition type between two shots.
        
        Args:
            from_shot: Dict with shot_type, emotion, etc.
            to_shot: Dict with shot_type, emotion, etc.
            
        Returns:
            TransitionSuggestion with type and reasoning
        """
        from_type = from_shot.get("shot_type", "medium")
        to_type = to_shot.get("shot_type", "medium")
        from_emotion = from_shot.get("emotion", "neutral")
        to_emotion = to_shot.get("emotion", "neutral")
        from_id = from_shot.get("shot_id", "shot_a")
        to_id = to_shot.get("shot_id", "shot_b")
        
        # Default to cut
        transition_type = "cut"
        reasoning = "Standard cut transition"
        confidence = 0.8
        
        # Scene/location change → fade
        if from_shot.get("location") != to_shot.get("location"):
            transition_type = "fade"
            reasoning = "Location change - fade provides clear separation"
            confidence = 0.9
        
        # Time jump → dissolve
        elif from_shot.get("time") != to_shot.get("time"):
            transition_type = "dissolve"
            reasoning = "Time change - dissolve indicates passage of time"
            confidence = 0.85
        
        # Emotional shift → dissolve or match cut
        elif from_emotion != to_emotion:
            if self._is_dramatic_shift(from_emotion, to_emotion):
                transition_type = "dissolve"
                reasoning = f"Emotional shift ({from_emotion} → {to_emotion})"
                confidence = 0.75
        
        # Same character, different framing → match cut
        elif from_shot.get("characters") == to_shot.get("characters"):
            if from_type != to_type:
                transition_type = "match_cut"
                reasoning = "Same character, different framing - match cut maintains continuity"
                confidence = 0.7
        
        # Wide to close (or vice versa) → cut
        # This is standard coverage, cut is appropriate
        
        buffer_sec = TRANSITION_BUFFER_SEC.get(transition_type, 0.0)
        
        return TransitionSuggestion(
            from_shot_id=from_id,
            to_shot_id=to_id,
            transition_type=transition_type,
            confidence=confidence,
            reasoning=reasoning,
            buffer_sec=buffer_sec,
        )
    
    def _is_dramatic_shift(self, from_emotion: str, to_emotion: str) -> bool:
        """Check if emotional shift is dramatic enough for special transition."""
        dramatic_pairs = [
            ("tense", "relief"),
            ("happy", "sad"),
            ("calm", "angry"),
            ("fear", "joy"),
            ("despair", "hope"),
        ]
        
        for pair in dramatic_pairs:
            if (from_emotion in pair and to_emotion in pair and 
                from_emotion != to_emotion):
                return True
        return False
    
    # -------------------------------------------------------------------------
    # Batch Planning
    # -------------------------------------------------------------------------
    
    def plan_scene(
        self,
        scene_id: str,
        shots: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Plan pacing for an entire scene.
        
        Args:
            scene_id: Scene identifier
            shots: List of shot dicts with duration_sec, dialogue, description
            
        Returns:
            Dict with shot plans and transition suggestions
        """
        shot_plans = []
        transitions = []
        
        for i, shot in enumerate(shots):
            # Plan individual shot
            plan = self.plan_shot(
                shot_id=shot.get("shot_id", f"{scene_id}_shot_{i:02d}"),
                duration_sec=shot.get("duration_sec", 10.0),
                dialogue=shot.get("dialogue"),
                description=shot.get("description", ""),
                transition_out=shot.get("transition_out", "cut"),
            )
            shot_plans.append(plan)
            
            # Suggest transition to next shot
            if i < len(shots) - 1:
                transition = self.suggest_transition(shot, shots[i + 1])
                transitions.append(transition)
        
        # Calculate totals
        total_duration = sum(p.total_duration_sec for p in shot_plans)
        total_chunks = sum(p.chunk_count for p in shot_plans)
        all_warnings = []
        for plan in shot_plans:
            all_warnings.extend(plan.warnings)
        
        return {
            "scene_id": scene_id,
            "shot_count": len(shots),
            "total_duration_sec": total_duration,
            "total_chunks": total_chunks,
            "shot_plans": [p.to_dict() for p in shot_plans],
            "transitions": [t.to_dict() for t in transitions],
            "warnings": all_warnings,
        }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_pacer(
    max_chunk_duration_sec: Optional[float] = None,
    pacing_style: PacingStyle = PacingStyle.NORMAL,
    config: Optional[Any] = None,  # GenerationConfig
) -> Pacer:
    """
    Factory function to create a Pacer.
    
    Args:
        max_chunk_duration_sec: Override max chunk duration
        pacing_style: Pacing style for project
        config: Optional GenerationConfig for defaults
        
    Returns:
        Configured Pacer instance
    """
    # Get defaults from config if provided
    if config is not None:
        max_duration = max_chunk_duration_sec or config.max_shot_duration_sec
    else:
        max_duration = max_chunk_duration_sec or DEFAULT_MAX_CHUNK_DURATION_SEC
    
    return Pacer(
        max_chunk_duration_sec=max_duration,
        pacing_style=pacing_style,
    )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def quick_chunk_plan(
    duration_sec: float,
    max_chunk_sec: float = DEFAULT_MAX_CHUNK_DURATION_SEC,
) -> List[Tuple[float, float]]:
    """
    Quick calculation of chunk boundaries.
    
    Returns list of (start, end) tuples.
    
    Usage:
        chunks = quick_chunk_plan(25.0)  # 25 second shot
        # Returns: [(0.0, 12.0), (12.0, 24.0), (24.0, 25.0)]
    """
    chunks = []
    start = 0.0
    
    while start < duration_sec:
        end = min(start + max_chunk_sec, duration_sec)
        chunks.append((start, end))
        start = end
    
    return chunks


def estimate_dialogue_duration(
    text: str,
    words_per_second: float = DEFAULT_WORDS_PER_SECOND,
) -> float:
    """
    Estimate duration of dialogue text.
    
    Usage:
        duration = estimate_dialogue_duration("Hello, how are you today?")
        # Returns: ~2.0 seconds
    """
    word_count = len(text.split())
    return word_count / words_per_second