"""
Continuum Engine - Shot Event Parser

Extracts state change events from shot descriptions for World State tracking.

The Problem:
    Shot descriptions contain implicit state changes:
    - "Alice picks up the sword" → sword is now held by alice
    - "The mug falls and shatters" → mug is now on floor, state=broken
    - "Bob opens the door" → door state=open
    
    Without parsing these, the World State doesn't know that Alice has
    the sword in the next shot, causing continuity errors.

The Solution:
    A lightweight pattern-based parser that:
    1. Matches common action verbs (pick up, drop, break, open, close, etc.)
    2. Extracts subject (who/what) and object (what's affected)
    3. Generates StateEvents for WorldState consumption
    
    This is NOT an LLM. It uses simple regex patterns that cover ~80% of
    common filmmaking actions. For complex scenes, explicit events can be
    declared in the scene graph JSON.

Architecture Position:
    Scene Graph → Shot Event Parser → World State → Physics Checker
                         ↓                  ↓
              Parses descriptions    Validates output

Design Principles:
    1. Pattern-based: No ML models, no API calls
    2. Explicit override: Scene graph can declare events directly
    3. Fail-safe: If parsing fails, no event is recorded (safe default)
    4. Extensible: New patterns can be added without changing interface

Usage:
    parser = ShotEventParser()
    events = parser.parse_shot(shot, available_entities)
    for event in events:
        world_state.apply_event(event)

Vibe Coder Note:
    This is "dumb" pattern matching, not AI. It will miss nuanced
    descriptions but catches the obvious ones. The architecture allows
    upgrading to LLM-based parsing in Director Agent Phase 2 without
    changing the WorldState interface.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from src.director.world_state import (
    EventType,
    ObjectState,
    Position,
    StateEvent,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION PATTERNS
# =============================================================================

@dataclass
class ActionPattern:
    """
    A pattern for detecting state-changing actions in text.
    
    Attributes:
        pattern: Regex pattern with named groups (subject, object)
        event_type: What kind of event this creates
        new_state: State to apply (for state_change events)
        position_type: Position type for move events
        description_template: Template for event description
    """
    pattern: str
    event_type: EventType
    new_state: Optional[ObjectState] = None
    position_type: Optional[str] = None  # "floor", "held_by:{subject}", etc.
    description_template: str = "{subject} {action} {object}"
    
    def compile(self) -> re.Pattern:
        """Compile the regex pattern."""
        return re.compile(self.pattern, re.IGNORECASE)


# Common action patterns for filmmaking scenarios
# Pattern groups: subject (who does it), object (what's affected)
ACTION_PATTERNS: List[ActionPattern] = [
    # PICKUP actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:picks?\s+up|grabs?|takes?|lifts?)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.PICKUP,
        description_template="{subject} picks up {object}",
    ),
    
    # DROP actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:drops?|releases?|lets?\s+go\s+of|puts?\s+down)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.DROP,
        position_type="floor",
        description_template="{subject} drops {object}",
    ),
    
    # PLACE actions (drop with specific position)
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:places?|puts?|sets?)\s+(?:the\s+)?(?P<object>\w+)\s+on\s+(?:the\s+)?(?P<location>\w+)",
        event_type=EventType.MOVE,
        description_template="{subject} places {object} on {location}",
    ),
    
    # THROW actions (implies drop at unpredictable location)
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:throws?|tosses?|hurls?|flings?)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.DROP,
        position_type="floor",
        description_template="{subject} throws {object}",
    ),
    
    # BREAK actions
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+(?:breaks?|shatters?|smashes?|cracks?|crumbles?)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.BROKEN,
        description_template="{object} breaks",
    ),
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:breaks?|shatters?|smashes?|destroys?)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.BROKEN,
        description_template="{subject} breaks {object}",
    ),
    
    # OPEN actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+opens?\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.OPEN,
        description_template="{subject} opens {object}",
    ),
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+opens?",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.OPEN,
        description_template="{object} opens",
    ),
    
    # CLOSE actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+closes?\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.CLOSED,
        description_template="{subject} closes {object}",
    ),
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+closes?",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.CLOSED,
        description_template="{object} closes",
    ),
    
    # TURN ON actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:turns?\s+on|activates?|switches?\s+on|lights?)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.ON,
        description_template="{subject} turns on {object}",
    ),
    
    # TURN OFF actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:turns?\s+off|deactivates?|switches?\s+off)\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.OFF,
        description_template="{subject} turns off {object}",
    ),
    
    # FALL actions
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+(?:falls?|tumbles?|topples?|drops?)",
        event_type=EventType.MOVE,
        position_type="floor",
        description_template="{object} falls",
    ),
    
    # GIVE/HAND actions (transfer)
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:gives?|hands?|passes?)\s+(?:the\s+)?(?P<object>\w+)\s+to\s+(?P<recipient>\w+)",
        event_type=EventType.TRANSFER,
        description_template="{subject} gives {object} to {recipient}",
    ),
    
    # HIDE actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+hides?\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.HIDDEN,
        description_template="{subject} hides {object}",
    ),
    
    # APPEAR/ENTER actions
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+(?:appears?|enters?|arrives?|comes?\s+in)",
        event_type=EventType.APPEAR,
        description_template="{object} appears",
    ),
    
    # LEAVE/EXIT actions
    ActionPattern(
        pattern=r"(?:the\s+)?(?P<object>\w+)\s+(?:leaves?|exits?|disappears?|goes?\s+away)",
        event_type=EventType.DISAPPEAR,
        description_template="{object} leaves",
    ),
    
    # SPILL/WET actions
    ActionPattern(
        pattern=r"(?P<subject>\w+)\s+(?:spills?|pours?)\s+(?:\w+\s+)?on\s+(?:the\s+)?(?P<object>\w+)",
        event_type=EventType.STATE_CHANGE,
        new_state=ObjectState.WET,
        description_template="{object} gets wet",
    ),
]

# Compile patterns once at module load
COMPILED_PATTERNS: List[Tuple[ActionPattern, re.Pattern]] = [
    (pattern, pattern.compile()) for pattern in ACTION_PATTERNS
]


# =============================================================================
# EXPLICIT EVENT SCHEMA
# =============================================================================

@dataclass
class ExplicitEvent:
    """
    Event declared explicitly in scene graph JSON.
    
    Schema for shot.metadata["events"]:
    [
        {
            "type": "pickup",
            "subject": "alice",
            "object": "sword",
            "description": "Alice grabs the ancient sword"
        },
        {
            "type": "state_change",
            "object": "mirror",
            "new_state": "broken"
        }
    ]
    """
    type: str
    object: str  # Required: what entity is affected
    subject: Optional[str] = None
    new_state: Optional[str] = None
    position: Optional[str] = None
    recipient: Optional[str] = None
    description: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplicitEvent":
        return cls(
            type=data.get("type", "interact"),
            object=data.get("object", ""),
            subject=data.get("subject"),
            new_state=data.get("new_state"),
            position=data.get("position"),
            recipient=data.get("recipient"),
            description=data.get("description"),
        )


# =============================================================================
# PARSER
# =============================================================================

class ShotEventParser:
    """
    Parses shot descriptions to extract state change events.
    
    Two sources of events:
    1. Pattern matching on shot.description
    2. Explicit events in shot.metadata["events"]
    
    Explicit events take precedence (can override pattern-detected events).
    """
    
    def __init__(
        self,
        enable_pattern_matching: bool = True,
        enable_explicit_events: bool = True,
    ):
        """
        Initialize the parser.
        
        Args:
            enable_pattern_matching: Whether to parse descriptions
            enable_explicit_events: Whether to use metadata events
        """
        self.enable_pattern_matching = enable_pattern_matching
        self.enable_explicit_events = enable_explicit_events
        self._event_counter = 0
    
    def parse_shot(
        self,
        shot_id: str,
        description: str,
        metadata: Dict[str, Any],
        known_entities: Set[str],
        characters: Optional[List[str]] = None,
        props: Optional[List[str]] = None,
    ) -> List[StateEvent]:
        """
        Parse a shot and extract state change events.
        
        Args:
            shot_id: The shot identifier
            description: Shot description text
            metadata: Shot metadata (may contain explicit events)
            known_entities: Set of valid entity IDs (for validation)
            characters: List of character IDs in this shot
            props: List of prop IDs in this shot
            
        Returns:
            List of StateEvents to apply to WorldState
        """
        events: List[StateEvent] = []
        
        # Normalize entity names for matching
        entity_lookup = self._build_entity_lookup(known_entities)
        
        # Build context from shot participants
        shot_context = {
            "characters": set(characters or []),
            "props": set(props or []),
        }
        
        # 1. Extract explicit events from metadata (highest priority)
        if self.enable_explicit_events and "events" in metadata:
            explicit_events = self._parse_explicit_events(
                shot_id, metadata["events"], entity_lookup
            )
            events.extend(explicit_events)
            logger.debug(f"Shot {shot_id}: {len(explicit_events)} explicit events")
        
        # 2. Parse description for patterns
        if self.enable_pattern_matching:
            parsed_events = self._parse_description(
                shot_id, description, entity_lookup, shot_context
            )
            
            # Only add parsed events for entities not already covered by explicit
            explicit_objects = {e.entity_id for e in events}
            for event in parsed_events:
                if event.entity_id not in explicit_objects:
                    events.append(event)
            
            logger.debug(f"Shot {shot_id}: {len(parsed_events)} parsed events")
        
        if events:
            logger.info(f"Shot {shot_id}: extracted {len(events)} state events")
            
        return events
    
    def _build_entity_lookup(self, known_entities: Set[str]) -> Dict[str, str]:
        """
        Build a lookup table for entity name normalization.
        
        Handles variations like:
        - "sword" → "sword"
        - "the_sword" → "sword"
        - "Sword" → "sword"
        """
        lookup = {}
        for entity_id in known_entities:
            # Exact match
            lookup[entity_id.lower()] = entity_id
            # Without underscores
            lookup[entity_id.lower().replace("_", "")] = entity_id
            # Without common prefixes
            if entity_id.lower().startswith("the_"):
                lookup[entity_id.lower()[4:]] = entity_id
        return lookup
    
    def _resolve_entity(
        self,
        name: str,
        entity_lookup: Dict[str, str],
    ) -> Optional[str]:
        """
        Resolve a name from the description to a known entity ID.
        
        Returns None if the name doesn't match any known entity.
        """
        if not name:
            return None
            
        normalized = name.lower().strip()
        
        # Direct lookup
        if normalized in entity_lookup:
            return entity_lookup[normalized]
        
        # Try without common articles
        for article in ["the", "a", "an"]:
            if normalized.startswith(article + " "):
                rest = normalized[len(article) + 1:]
                if rest in entity_lookup:
                    return entity_lookup[rest]
        
        return None
    
    def _parse_explicit_events(
        self,
        shot_id: str,
        events_data: List[Dict[str, Any]],
        entity_lookup: Dict[str, str],
    ) -> List[StateEvent]:
        """Parse explicit events from metadata."""
        events = []
        
        for data in events_data:
            try:
                explicit = ExplicitEvent.from_dict(data)
                
                # Resolve entity ID
                entity_id = self._resolve_entity(explicit.object, entity_lookup)
                if not entity_id:
                    # Use the name as-is if not in lookup (might be new entity)
                    entity_id = explicit.object.lower().replace(" ", "_")
                
                # Map type string to EventType
                event_type = self._map_event_type(explicit.type)
                
                # Build new_value based on event type
                new_value = self._build_new_value(explicit, entity_lookup)
                
                event = StateEvent(
                    event_id=self._generate_event_id(),
                    event_type=event_type,
                    entity_id=entity_id,
                    shot_id=shot_id,
                    timestamp=datetime.utcnow().isoformat(),
                    caused_by=explicit.subject,
                    new_value=new_value,
                    description=explicit.description or f"{explicit.type} {entity_id}",
                )
                events.append(event)
                
            except Exception as e:
                logger.warning(f"Failed to parse explicit event: {data}, error: {e}")
                
        return events
    
    def _parse_description(
        self,
        shot_id: str,
        description: str,
        entity_lookup: Dict[str, str],
        shot_context: Dict[str, Set[str]],
    ) -> List[StateEvent]:
        """Parse description text for action patterns."""
        events = []
        
        # Try each pattern
        for action_pattern, compiled_regex in COMPILED_PATTERNS:
            for match in compiled_regex.finditer(description):
                groups = match.groupdict()
                
                # Extract object (required)
                obj_name = groups.get("object", "")
                entity_id = self._resolve_entity(obj_name, entity_lookup)
                
                # If not a known entity, skip (avoid false positives)
                if not entity_id:
                    continue
                
                # Extract subject if present
                subject_name = groups.get("subject")
                subject_id = None
                if subject_name:
                    subject_id = self._resolve_entity(subject_name, entity_lookup)
                    # If subject looks like a character name but isn't in our list,
                    # it might still be valid
                    if not subject_id and subject_name.lower() in {
                        c.lower() for c in shot_context.get("characters", set())
                    }:
                        subject_id = subject_name.lower()
                
                # Build new_value
                new_value = {}
                
                if action_pattern.new_state:
                    new_value["state"] = action_pattern.new_state.value
                
                if action_pattern.position_type:
                    if action_pattern.position_type == "floor":
                        new_value["position"] = Position.named("floor", confidence=0.7).to_dict()
                    elif action_pattern.position_type.startswith("held_by:"):
                        if subject_id:
                            new_value["position"] = Position.held_by(subject_id).to_dict()
                
                # Handle PLACE pattern with location
                if "location" in groups:
                    loc_name = groups["location"]
                    new_value["position"] = Position.named(
                        loc_name.lower().replace(" ", "_"),
                        confidence=0.8
                    ).to_dict()
                
                # Handle TRANSFER pattern with recipient
                if "recipient" in groups:
                    recipient_name = groups["recipient"]
                    recipient_id = self._resolve_entity(recipient_name, entity_lookup)
                    if recipient_id:
                        new_value["new_holder"] = recipient_id
                        new_value["position"] = Position.held_by(recipient_id).to_dict()
                
                # Build description
                desc = action_pattern.description_template.format(
                    subject=subject_name or "someone",
                    object=obj_name,
                    action=action_pattern.event_type.value,
                    location=groups.get("location", ""),
                    recipient=groups.get("recipient", ""),
                )
                
                event = StateEvent(
                    event_id=self._generate_event_id(),
                    event_type=action_pattern.event_type,
                    entity_id=entity_id,
                    shot_id=shot_id,
                    timestamp=datetime.utcnow().isoformat(),
                    caused_by=subject_id,
                    new_value=new_value if new_value else None,
                    description=desc.strip(),
                )
                events.append(event)
                
                logger.debug(f"Pattern match: '{match.group()}' → {event.event_type.value} {entity_id}")
        
        return events
    
    def _map_event_type(self, type_str: str) -> EventType:
        """Map string to EventType enum."""
        type_map = {
            "pickup": EventType.PICKUP,
            "pick_up": EventType.PICKUP,
            "grab": EventType.PICKUP,
            "take": EventType.PICKUP,
            "drop": EventType.DROP,
            "release": EventType.DROP,
            "move": EventType.MOVE,
            "place": EventType.MOVE,
            "state_change": EventType.STATE_CHANGE,
            "change": EventType.STATE_CHANGE,
            "break": EventType.STATE_CHANGE,
            "open": EventType.STATE_CHANGE,
            "close": EventType.STATE_CHANGE,
            "appear": EventType.APPEAR,
            "enter": EventType.APPEAR,
            "disappear": EventType.DISAPPEAR,
            "exit": EventType.DISAPPEAR,
            "leave": EventType.DISAPPEAR,
            "transfer": EventType.TRANSFER,
            "give": EventType.TRANSFER,
            "hand": EventType.TRANSFER,
            "interact": EventType.INTERACT,
        }
        return type_map.get(type_str.lower(), EventType.INTERACT)
    
    def _build_new_value(
        self,
        explicit: ExplicitEvent,
        entity_lookup: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """Build new_value dict from explicit event."""
        new_value = {}
        
        if explicit.new_state:
            try:
                state = ObjectState(explicit.new_state.lower())
                new_value["state"] = state.value
            except ValueError:
                # Custom state, store as-is
                new_value["custom_states"] = {explicit.new_state: True}
        
        if explicit.position:
            new_value["position"] = Position.named(
                explicit.position.lower().replace(" ", "_")
            ).to_dict()
        
        if explicit.recipient:
            recipient_id = self._resolve_entity(explicit.recipient, entity_lookup)
            if recipient_id:
                new_value["new_holder"] = recipient_id
                new_value["position"] = Position.held_by(recipient_id).to_dict()
        
        return new_value if new_value else None
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        self._event_counter += 1
        timestamp = datetime.utcnow().strftime("%H%M%S")
        return f"parsed_{timestamp}_{self._event_counter:04d}"


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_shot_event_parser(
    enable_pattern_matching: bool = True,
    enable_explicit_events: bool = True,
) -> ShotEventParser:
    """
    Factory function to create a ShotEventParser.
    
    Args:
        enable_pattern_matching: Whether to parse descriptions
        enable_explicit_events: Whether to use metadata events
        
    Returns:
        Configured ShotEventParser instance
    """
    return ShotEventParser(
        enable_pattern_matching=enable_pattern_matching,
        enable_explicit_events=enable_explicit_events,
    )


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def parse_shot_events(
    shot_id: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
    known_entities: Optional[Set[str]] = None,
    characters: Optional[List[str]] = None,
    props: Optional[List[str]] = None,
) -> List[StateEvent]:
    """
    Convenience function to parse events from a shot.
    
    Example:
        events = parse_shot_events(
            shot_id="scene_01_shot_03",
            description="Alice picks up the sword and walks to the door.",
            known_entities={"alice", "sword", "door"},
            characters=["alice"],
            props=["sword", "door"],
        )
    """
    parser = get_shot_event_parser()
    return parser.parse_shot(
        shot_id=shot_id,
        description=description,
        metadata=metadata or {},
        known_entities=known_entities or set(),
        characters=characters,
        props=props,
    )