"""
Continuum Engine - World State Tracker (The Stage Manager)

Tracks the dynamic state of objects and characters across shots.
This is the "memory of what happened" that complements the Consistency Dictionary.

The Problem:
    - Consistency Dictionary: Tells us WHAT things LOOK LIKE (static)
    - Scene Graph: Tells us WHO appears WHERE (structural)
    - World State: Tells us WHERE things ARE and WHAT HAPPENED to them (dynamic)

    Without world state, the system forgets that the mug fell off the table
    in Scene 2, and might place it back on the table in Scene 3.

The Solution:
    A lightweight "stage manager" that:
    1. Tracks object positions using named locations ("table_left", "floor")
    2. Tracks object states (intact, broken, held_by_alice, etc.)
    3. Records events that mutate state ("mug_thrown", "door_opened")
    4. Provides state snapshots for any point in the timeline
    5. Feeds into prompt generation for continuity

Architecture Position:
    Scene Graph (structure) + Consistency Dict (appearance) + World State (dynamics)
    ↓
    Director Agent queries all three to generate accurate prompts
    ↓
    Physics Checker verifies output matches expected world state

Design Principles:
    1. Event-sourced: State is derived from sequence of events (auditable)
    2. Shot-scoped: State is queried per-shot for prompt generation
    3. JSON-serializable: Can be saved, loaded, sent to LLMs
    4. Lightweight: Named positions, not full 3D coordinates (simple enough for LLMs)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from copy import deepcopy

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class ObjectState(str, Enum):
    """Common states for trackable objects."""
    INTACT = "intact"              # Default state
    BROKEN = "broken"              # Shattered, destroyed
    OPEN = "open"                  # For doors, containers
    CLOSED = "closed"              # For doors, containers
    ON = "on"                      # For lights, devices
    OFF = "off"                    # For lights, devices
    HELD = "held"                  # Being carried by someone
    DROPPED = "dropped"            # Recently released
    HIDDEN = "hidden"              # Not visible in scene
    VISIBLE = "visible"            # Explicitly visible
    WET = "wet"                    # Liquid contact
    BURNING = "burning"            # On fire
    EMPTY = "empty"                # Container emptied
    FULL = "full"                  # Container filled


class PositionType(str, Enum):
    """Types of position specifications."""
    NAMED = "named"                # "table_left", "floor", "door_frame"
    RELATIVE = "relative"          # "next_to:alice", "on:table"
    HELD_BY = "held_by"            # "held_by:alice"
    OFFSCREEN = "offscreen"        # Not in current shot
    UNKNOWN = "unknown"            # Position not tracked


class EventType(str, Enum):
    """Types of state-changing events."""
    MOVE = "move"                  # Object changes position
    STATE_CHANGE = "state_change"  # Object state changes (break, open, etc.)
    APPEAR = "appear"              # Object enters scene
    DISAPPEAR = "disappear"        # Object exits scene
    PICKUP = "pickup"              # Character picks up object
    DROP = "drop"                  # Character releases object
    INTERACT = "interact"          # Generic interaction
    TRANSFER = "transfer"          # Object moves between characters


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Position:
    """
    Position of an object in the scene.
    
    Uses named positions for simplicity (LLM-friendly).
    Not full 3D coordinates - that's overkill for prompt generation.
    
    Examples:
        Position(type=NAMED, value="kitchen_table")
        Position(type=RELATIVE, value="on:counter")
        Position(type=HELD_BY, value="alice")
    """
    type: PositionType
    value: str
    confidence: float = 1.0  # How sure are we? (1.0 = script-defined, 0.5 = inferred)
    
    def __str__(self) -> str:
        if self.type == PositionType.HELD_BY:
            return f"held by {self.value}"
        elif self.type == PositionType.RELATIVE:
            parts = self.value.split(":")
            if len(parts) == 2:
                return f"{parts[0]} {parts[1]}"
            return self.value
        elif self.type == PositionType.OFFSCREEN:
            return "offscreen"
        elif self.type == PositionType.UNKNOWN:
            return "unknown location"
        else:
            return self.value.replace("_", " ")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "value": self.value,
            "confidence": self.confidence,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        return cls(
            type=PositionType(data["type"]),
            value=data["value"],
            confidence=data.get("confidence", 1.0),
        )
    
    @classmethod
    def named(cls, location: str, confidence: float = 1.0) -> "Position":
        """Factory for named position."""
        return cls(PositionType.NAMED, location, confidence)
    
    @classmethod
    def relative(cls, relation: str, anchor: str, confidence: float = 1.0) -> "Position":
        """Factory for relative position (e.g., 'on', 'table')."""
        return cls(PositionType.RELATIVE, f"{relation}:{anchor}", confidence)
    
    @classmethod
    def held_by(cls, character_id: str, confidence: float = 1.0) -> "Position":
        """Factory for held-by-character position."""
        return cls(PositionType.HELD_BY, character_id, confidence)
    
    @classmethod
    def offscreen(cls) -> "Position":
        """Factory for offscreen position."""
        return cls(PositionType.OFFSCREEN, "offscreen", 1.0)
    
    @classmethod
    def unknown(cls) -> "Position":
        """Factory for unknown position."""
        return cls(PositionType.UNKNOWN, "unknown", 0.0)


@dataclass
class TrackedObject:
    """
    Current state of a tracked object (prop or character).
    
    Attributes:
        entity_id: Links to ConsistencyDict entity
        entity_type: "prop" or "character"
        position: Where the object is
        state: Current state (intact, broken, etc.)
        holder: Who is holding this (if held)
        custom_states: Additional state flags
        last_updated_shot: Which shot last changed this object
    """
    entity_id: str
    entity_type: str  # "prop", "character"
    position: Position
    state: ObjectState = ObjectState.INTACT
    holder: Optional[str] = None  # Character ID if being held
    custom_states: Dict[str, Any] = field(default_factory=dict)
    last_updated_shot: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "position": self.position.to_dict(),
            "state": self.state.value,
            "holder": self.holder,
            "custom_states": self.custom_states,
            "last_updated_shot": self.last_updated_shot,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedObject":
        return cls(
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
            position=Position.from_dict(data["position"]),
            state=ObjectState(data.get("state", "intact")),
            holder=data.get("holder"),
            custom_states=data.get("custom_states", {}),
            last_updated_shot=data.get("last_updated_shot", ""),
        )
    
    def to_prompt_description(self) -> str:
        """
        Generate a natural language description for prompt injection.
        
        Example: "The red mug lies broken on the kitchen floor"
        """
        parts = []
        
        # State descriptor
        if self.state == ObjectState.BROKEN:
            parts.append("broken")
        elif self.state == ObjectState.OPEN:
            parts.append("open")
        elif self.state == ObjectState.WET:
            parts.append("wet")
        elif self.state == ObjectState.BURNING:
            parts.append("burning")
        
        # Position descriptor
        position_str = str(self.position)
        
        if self.holder:
            return f"{' '.join(parts)} (held by {self.holder})" if parts else f"(held by {self.holder})"
        elif position_str:
            return f"{' '.join(parts)}, {position_str}" if parts else position_str
        
        return " ".join(parts) if parts else "present in scene"


@dataclass
class StateEvent:
    """
    A single state-changing event.
    
    Events are the source of truth - current state is derived
    by replaying events in order (event sourcing pattern).
    
    Attributes:
        event_id: Unique identifier
        event_type: Type of event (move, state_change, etc.)
        entity_id: What object/character was affected
        shot_id: When this happened (shot reference)
        timestamp: When event was recorded
        old_value: Previous state/position (for debugging)
        new_value: New state/position
        caused_by: What triggered this (character ID, script action, etc.)
        description: Human-readable description
    """
    event_id: str
    event_type: EventType
    entity_id: str
    shot_id: str
    timestamp: str
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    caused_by: Optional[str] = None
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "entity_id": self.entity_id,
            "shot_id": self.shot_id,
            "timestamp": self.timestamp,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "caused_by": self.caused_by,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateEvent":
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            entity_id=data["entity_id"],
            shot_id=data["shot_id"],
            timestamp=data["timestamp"],
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            caused_by=data.get("caused_by"),
            description=data.get("description", ""),
        )


@dataclass
class SceneSetup:
    """
    Initial state setup for a scene.
    
    Defines where everything is at the start of a scene,
    before any events occur.
    """
    scene_id: str
    location_id: str
    initial_objects: Dict[str, TrackedObject] = field(default_factory=dict)
    named_positions: Dict[str, str] = field(default_factory=dict)  # "table_left" -> "left side of kitchen table"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "location_id": self.location_id,
            "initial_objects": {k: v.to_dict() for k, v in self.initial_objects.items()},
            "named_positions": self.named_positions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSetup":
        return cls(
            scene_id=data["scene_id"],
            location_id=data["location_id"],
            initial_objects={
                k: TrackedObject.from_dict(v) 
                for k, v in data.get("initial_objects", {}).items()
            },
            named_positions=data.get("named_positions", {}),
        )


# =============================================================================
# WORLD STATE MANAGER
# =============================================================================

class WorldState:
    """
    The Stage Manager - tracks dynamic state of all objects and characters.
    
    Usage:
        # Initialize with scene setup
        world = WorldState()
        world.setup_scene(SceneSetup(
            scene_id="scene_01",
            location_id="kitchen",
            initial_objects={
                "red_mug": TrackedObject(
                    entity_id="red_mug",
                    entity_type="prop",
                    position=Position.named("kitchen_table"),
                )
            }
        ))
        
        # Apply events as shots are processed
        world.apply_event(StateEvent(
            event_id="evt_001",
            event_type=EventType.MOVE,
            entity_id="red_mug",
            shot_id="scene_01_shot_03",
            timestamp=datetime.utcnow().isoformat(),
            new_value={"position": Position.named("floor").to_dict()},
            description="Mug knocked off table",
        ))
        
        # Query state for prompt generation
        mug_state = world.get_object_state("red_mug")
        prompt_context = world.get_prompt_context("scene_01_shot_04")
    """
    
    def __init__(self, project_id: str = "default"):
        """
        Initialize world state tracker.
        
        Args:
            project_id: Project identifier for namespacing
        """
        self.project_id = project_id
        self._scenes: Dict[str, SceneSetup] = {}
        self._current_state: Dict[str, TrackedObject] = {}
        self._events: List[StateEvent] = []
        self._event_counter = 0
        self._current_scene_id: Optional[str] = None
        self._shot_order: List[str] = []  # Ordered list of processed shots
    
    # -------------------------------------------------------------------------
    # Scene Setup
    # -------------------------------------------------------------------------
    
    def setup_scene(self, setup: SceneSetup) -> None:
        """
        Initialize state for a scene.
        
        Call this before processing shots in a scene.
        Resets object positions to scene's initial state.
        """
        self._scenes[setup.scene_id] = setup
        self._current_scene_id = setup.scene_id
        
        # Apply initial object positions
        for entity_id, tracked_obj in setup.initial_objects.items():
            self._current_state[entity_id] = deepcopy(tracked_obj)
        
        logger.info(
            f"Scene '{setup.scene_id}' setup complete: "
            f"{len(setup.initial_objects)} objects positioned"
        )
    
    def get_scene_setup(self, scene_id: str) -> Optional[SceneSetup]:
        """Get setup for a specific scene."""
        return self._scenes.get(scene_id)
    
    # -------------------------------------------------------------------------
    # Event Application
    # -------------------------------------------------------------------------
    
    def apply_event(self, event: StateEvent) -> None:
        """
        Apply a state-changing event.
        
        This is the primary way to mutate world state.
        Events are recorded for history/debugging.
        """
        # Record event
        self._events.append(event)
        
        # Track shot order
        if event.shot_id and event.shot_id not in self._shot_order:
            self._shot_order.append(event.shot_id)
        
        # Get or create tracked object
        if event.entity_id not in self._current_state:
            # New object appearing
            self._current_state[event.entity_id] = TrackedObject(
                entity_id=event.entity_id,
                entity_type="prop",  # Default, can be overridden
                position=Position.unknown(),
            )
        
        obj = self._current_state[event.entity_id]
        
        # Apply event based on type
        if event.event_type == EventType.MOVE:
            if event.new_value and "position" in event.new_value:
                obj.position = Position.from_dict(event.new_value["position"])
                obj.holder = None  # Moving clears held status
        
        elif event.event_type == EventType.STATE_CHANGE:
            if event.new_value and "state" in event.new_value:
                obj.state = ObjectState(event.new_value["state"])
            if event.new_value and "custom_states" in event.new_value:
                obj.custom_states.update(event.new_value["custom_states"])
        
        elif event.event_type == EventType.PICKUP:
            if event.caused_by:
                obj.holder = event.caused_by
                obj.position = Position.held_by(event.caused_by)
        
        elif event.event_type == EventType.DROP:
            obj.holder = None
            if event.new_value and "position" in event.new_value:
                obj.position = Position.from_dict(event.new_value["position"])
            else:
                # Default: drop at current character position
                obj.position = Position.named("floor", confidence=0.7)
        
        elif event.event_type == EventType.APPEAR:
            if event.new_value and "position" in event.new_value:
                obj.position = Position.from_dict(event.new_value["position"])
        
        elif event.event_type == EventType.DISAPPEAR:
            obj.position = Position.offscreen()
        
        elif event.event_type == EventType.TRANSFER:
            # Object transferred between characters
            if event.new_value and "new_holder" in event.new_value:
                obj.holder = event.new_value["new_holder"]
                obj.position = Position.held_by(event.new_value["new_holder"])
        
        # Update tracking metadata
        obj.last_updated_shot = event.shot_id
        
        logger.debug(
            f"Applied event {event.event_id}: {event.entity_id} "
            f"{event.event_type.value} in {event.shot_id}"
        )
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        self._event_counter += 1
        return f"evt_{self._event_counter:06d}"
    
    # -------------------------------------------------------------------------
    # Convenience Event Methods
    # -------------------------------------------------------------------------
    
    def move_object(
        self,
        entity_id: str,
        new_position: Position,
        shot_id: str,
        caused_by: Optional[str] = None,
        description: str = "",
    ) -> StateEvent:
        """Convenience method to move an object."""
        event = StateEvent(
            event_id=self._generate_event_id(),
            event_type=EventType.MOVE,
            entity_id=entity_id,
            shot_id=shot_id,
            timestamp=datetime.utcnow().isoformat(),
            old_value={"position": self._current_state.get(entity_id, TrackedObject(
                entity_id=entity_id,
                entity_type="prop",
                position=Position.unknown(),
            )).position.to_dict()} if entity_id in self._current_state else None,
            new_value={"position": new_position.to_dict()},
            caused_by=caused_by,
            description=description or f"{entity_id} moved to {new_position}",
        )
        self.apply_event(event)
        return event
    
    def change_state(
        self,
        entity_id: str,
        new_state: ObjectState,
        shot_id: str,
        caused_by: Optional[str] = None,
        description: str = "",
    ) -> StateEvent:
        """Convenience method to change object state."""
        old_state = self._current_state.get(entity_id)
        event = StateEvent(
            event_id=self._generate_event_id(),
            event_type=EventType.STATE_CHANGE,
            entity_id=entity_id,
            shot_id=shot_id,
            timestamp=datetime.utcnow().isoformat(),
            old_value={"state": old_state.state.value} if old_state else None,
            new_value={"state": new_state.value},
            caused_by=caused_by,
            description=description or f"{entity_id} changed to {new_state.value}",
        )
        self.apply_event(event)
        return event
    
    def pickup_object(
        self,
        entity_id: str,
        character_id: str,
        shot_id: str,
        description: str = "",
    ) -> StateEvent:
        """Convenience method for character picking up object."""
        event = StateEvent(
            event_id=self._generate_event_id(),
            event_type=EventType.PICKUP,
            entity_id=entity_id,
            shot_id=shot_id,
            timestamp=datetime.utcnow().isoformat(),
            caused_by=character_id,
            description=description or f"{character_id} picks up {entity_id}",
        )
        self.apply_event(event)
        return event
    
    def drop_object(
        self,
        entity_id: str,
        drop_position: Position,
        shot_id: str,
        description: str = "",
    ) -> StateEvent:
        """Convenience method for dropping an object."""
        holder = self._current_state.get(entity_id, TrackedObject(
            entity_id=entity_id,
            entity_type="prop",
            position=Position.unknown(),
        )).holder
        event = StateEvent(
            event_id=self._generate_event_id(),
            event_type=EventType.DROP,
            entity_id=entity_id,
            shot_id=shot_id,
            timestamp=datetime.utcnow().isoformat(),
            caused_by=holder,
            new_value={"position": drop_position.to_dict()},
            description=description or f"{entity_id} dropped at {drop_position}",
        )
        self.apply_event(event)
        return event
    
    # -------------------------------------------------------------------------
    # State Queries
    # -------------------------------------------------------------------------
    
    def get_object_state(self, entity_id: str) -> Optional[TrackedObject]:
        """Get current state of an object."""
        return self._current_state.get(entity_id)
    
    def get_all_objects(self) -> Dict[str, TrackedObject]:
        """Get all tracked objects."""
        return dict(self._current_state)
    
    def get_objects_at_position(self, position_value: str) -> List[TrackedObject]:
        """Get all objects at a specific position."""
        return [
            obj for obj in self._current_state.values()
            if obj.position.value == position_value
        ]
    
    def get_held_objects(self, character_id: str) -> List[TrackedObject]:
        """Get all objects held by a character."""
        return [
            obj for obj in self._current_state.values()
            if obj.holder == character_id
        ]
    
    def get_objects_in_state(self, state: ObjectState) -> List[TrackedObject]:
        """Get all objects in a specific state."""
        return [
            obj for obj in self._current_state.values()
            if obj.state == state
        ]
    
    def get_state_at_shot(self, shot_id: str) -> Dict[str, TrackedObject]:
        """
        Get world state as it was at a specific shot.
        
        Replays events up to (and including) the specified shot.
        Useful for generating prompts for re-renders.
        """
        # Find shot position in order
        try:
            shot_index = self._shot_order.index(shot_id)
        except ValueError:
            # Shot not found, return current state
            logger.warning(f"Shot {shot_id} not in history, returning current state")
            return dict(self._current_state)
        
        # Get shots up to this point
        relevant_shots = set(self._shot_order[:shot_index + 1])
        
        # Replay events
        state: Dict[str, TrackedObject] = {}
        
        # Start with initial scene state
        for scene in self._scenes.values():
            for entity_id, obj in scene.initial_objects.items():
                state[entity_id] = deepcopy(obj)
        
        # Apply events up to shot
        for event in self._events:
            if event.shot_id in relevant_shots:
                if event.entity_id not in state:
                    state[event.entity_id] = TrackedObject(
                        entity_id=event.entity_id,
                        entity_type="prop",
                        position=Position.unknown(),
                    )
                
                obj = state[event.entity_id]
                
                # Apply event (simplified replay)
                if event.event_type == EventType.MOVE and event.new_value:
                    if "position" in event.new_value:
                        obj.position = Position.from_dict(event.new_value["position"])
                elif event.event_type == EventType.STATE_CHANGE and event.new_value:
                    if "state" in event.new_value:
                        obj.state = ObjectState(event.new_value["state"])
                elif event.event_type == EventType.PICKUP:
                    obj.holder = event.caused_by
                    if event.caused_by:
                        obj.position = Position.held_by(event.caused_by)
                elif event.event_type == EventType.DROP and event.new_value:
                    obj.holder = None
                    if "position" in event.new_value:
                        obj.position = Position.from_dict(event.new_value["position"])
        
        return state
    
    # -------------------------------------------------------------------------
    # Prompt Generation Support
    # -------------------------------------------------------------------------
    
    def get_prompt_context(
        self,
        shot_id: str,
        entity_ids: Optional[List[str]] = None,
    ) -> str:
        """
        Generate prompt context describing current world state.
        
        Returns natural language description suitable for injection
        into generation prompts.
        
        Args:
            shot_id: Current shot (for state lookup)
            entity_ids: Specific entities to describe (None = all)
            
        Returns:
            Natural language description of world state
        """
        state = self.get_state_at_shot(shot_id)
        
        if entity_ids:
            state = {k: v for k, v in state.items() if k in entity_ids}
        
        if not state:
            return ""
        
        descriptions = []
        
        for entity_id, obj in state.items():
            desc = obj.to_prompt_description()
            if desc and desc != "present in scene":
                descriptions.append(f"{entity_id.replace('_', ' ')}: {desc}")
        
        if not descriptions:
            return ""
        
        return "Current scene state: " + "; ".join(descriptions) + "."
    
    def get_expected_positions(
        self,
        shot_id: str,
        entity_ids: List[str],
    ) -> Dict[str, Position]:
        """
        Get expected positions for physics checking.
        
        Returns position expectations that physics_checker can verify against.
        """
        state = self.get_state_at_shot(shot_id)
        return {
            entity_id: state[entity_id].position
            for entity_id in entity_ids
            if entity_id in state
        }
    
    # -------------------------------------------------------------------------
    # Event History
    # -------------------------------------------------------------------------
    
    def get_events_for_entity(self, entity_id: str) -> List[StateEvent]:
        """Get all events affecting an entity."""
        return [e for e in self._events if e.entity_id == entity_id]
    
    def get_events_for_shot(self, shot_id: str) -> List[StateEvent]:
        """Get all events in a specific shot."""
        return [e for e in self._events if e.shot_id == shot_id]
    
    def get_recent_events(self, n: int = 10) -> List[StateEvent]:
        """Get N most recent events."""
        return self._events[-n:]
    
    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "project_id": self.project_id,
            "scenes": {k: v.to_dict() for k, v in self._scenes.items()},
            "current_state": {k: v.to_dict() for k, v in self._current_state.items()},
            "events": [e.to_dict() for e in self._events],
            "current_scene_id": self._current_scene_id,
            "shot_order": self._shot_order,
            "event_counter": self._event_counter,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldState":
        """Deserialize from dict."""
        world = cls(project_id=data.get("project_id", "default"))
        
        world._scenes = {
            k: SceneSetup.from_dict(v) 
            for k, v in data.get("scenes", {}).items()
        }
        world._current_state = {
            k: TrackedObject.from_dict(v) 
            for k, v in data.get("current_state", {}).items()
        }
        world._events = [
            StateEvent.from_dict(e) 
            for e in data.get("events", [])
        ]
        world._current_scene_id = data.get("current_scene_id")
        world._shot_order = data.get("shot_order", [])
        world._event_counter = data.get("event_counter", 0)
        
        return world
    
    def save(self, filepath: Path) -> None:
        """Save state to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"World state saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: Path) -> "WorldState":
        """Load state from JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        world = cls.from_dict(data)
        logger.info(f"World state loaded from {filepath}")
        return world
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about world state."""
        return {
            "project_id": self.project_id,
            "scene_count": len(self._scenes),
            "object_count": len(self._current_state),
            "event_count": len(self._events),
            "shot_count": len(self._shot_order),
            "current_scene": self._current_scene_id,
            "objects_by_state": {
                state.value: len(self.get_objects_in_state(state))
                for state in ObjectState
                if self.get_objects_in_state(state)
            },
        }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_world_state(
    project_id: str = "default",
    initial_setup: Optional[SceneSetup] = None,
) -> WorldState:
    """
    Factory function to create WorldState.
    
    Args:
        project_id: Project identifier
        initial_setup: Optional initial scene setup
        
    Returns:
        Configured WorldState instance
    """
    world = WorldState(project_id=project_id)
    
    if initial_setup:
        world.setup_scene(initial_setup)
    
    return world


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_simple_setup(
    scene_id: str,
    location_id: str,
    objects: Dict[str, str],
) -> SceneSetup:
    """
    Create a simple scene setup from object:position pairs.
    
    Args:
        scene_id: Scene identifier
        location_id: Location identifier
        objects: Dict of entity_id -> position_name
        
    Returns:
        SceneSetup ready for use
        
    Example:
        setup = create_simple_setup(
            scene_id="scene_01",
            location_id="kitchen",
            objects={
                "red_mug": "kitchen_table",
                "knife": "counter",
            }
        )
    """
    initial_objects = {}
    for entity_id, position_name in objects.items():
        initial_objects[entity_id] = TrackedObject(
            entity_id=entity_id,
            entity_type="prop",
            position=Position.named(position_name),
        )
    
    return SceneSetup(
        scene_id=scene_id,
        location_id=location_id,
        initial_objects=initial_objects,
    )