"""
Continuum Engine - Scene Graph

Hierarchical representation of a video project:
    Film â†’ Scenes â†’ Shots â†’ Chunks

This is the "blueprint" that the Director Agent creates and the
renderers consume. It tracks what happens when, who appears where,
and how the narrative flows.

Design Principles:
1. Immutable-ish: Build once, then read. Modifications create new versions.
2. JSON-serializable: Can be saved, loaded, and sent to LLMs
3. Entity-aware: Tracks which characters/locations appear in each shot
4. Chunk-ready: Shots are pre-divided into render-sized chunks
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Iterator
import hashlib
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class ShotType(str, Enum):
    """Camera shot types for cinematic language."""
    WIDE = "wide"              # Establishing shot, full environment
    MEDIUM = "medium"          # Character from waist up
    CLOSE = "close"            # Face/detail focus
    EXTREME_CLOSE = "extreme_close"  # Eye, hand, object detail
    OVER_SHOULDER = "over_shoulder"  # Conversation framing
    POV = "pov"                # Point of view
    TWO_SHOT = "two_shot"      # Two characters in frame
    GROUP = "group"            # Multiple characters
    INSERT = "insert"          # Cutaway to object/detail
    AERIAL = "aerial"          # Overhead/drone view


class TransitionType(str, Enum):
    """Transition between shots/scenes."""
    CUT = "cut"                # Hard cut (default)
    FADE = "fade"              # Fade to/from black
    DISSOLVE = "dissolve"      # Cross-dissolve
    WIPE = "wipe"              # Wipe transition
    MATCH_CUT = "match_cut"    # Match on action/shape


class ChunkStatus(str, Enum):
    """Render status of a chunk."""
    PENDING = "pending"
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# ENTITY REFERENCES (Lightweight IDs)
# =============================================================================

@dataclass
class EntityRef:
    """
    Lightweight reference to an entity (character, location, prop).
    
    The full entity data lives in the Consistency Dictionary.
    This is just a pointer with minimal context.
    """
    entity_id: str
    entity_type: str  # "character", "location", "prop"
    display_name: str = ""
    
    def __hash__(self):
        return hash((self.entity_id, self.entity_type))
    
    def __eq__(self, other):
        if not isinstance(other, EntityRef):
            return False
        return self.entity_id == other.entity_id and self.entity_type == other.entity_type
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "display_name": self.display_name or self.entity_id,
        }
    
    @classmethod
    def character(cls, entity_id: str, name: str = "") -> "EntityRef":
        """Factory for character reference."""
        return cls(entity_id, "character", name or entity_id)
    
    @classmethod
    def location(cls, entity_id: str, name: str = "") -> "EntityRef":
        """Factory for location reference."""
        return cls(entity_id, "location", name or entity_id)
    
    @classmethod
    def prop(cls, entity_id: str, name: str = "") -> "EntityRef":
        """Factory for prop reference."""
        return cls(entity_id, "prop", name or entity_id)


# =============================================================================
# CHUNK (Smallest Render Unit)
# =============================================================================

@dataclass
class Chunk:
    """
    A single render unit within a shot.
    
    Shots are divided into chunks because:
    1. Models have max generation length (~12-15 seconds stable)
    2. Chunks can be rendered in parallel
    3. Failed chunks can be re-rolled without losing entire shot
    
    Attributes:
        chunk_id: Unique identifier
        shot_id: Parent shot ID
        index: Position within shot (0-indexed)
        duration_sec: Target duration
        start_time_sec: Start time within shot
        prompt_override: Optional prompt modification for this chunk
        status: Render status
        output_path: Path to rendered output (when complete)
    """
    chunk_id: str
    shot_id: str
    index: int
    duration_sec: float
    start_time_sec: float = 0.0
    prompt_override: Optional[str] = None
    status: ChunkStatus = ChunkStatus.PENDING
    output_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def end_time_sec(self) -> float:
        """End time within shot."""
        return self.start_time_sec + self.duration_sec
    
    @property
    def is_first(self) -> bool:
        """Is this the first chunk in the shot?"""
        return self.index == 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "shot_id": self.shot_id,
            "index": self.index,
            "duration_sec": self.duration_sec,
            "start_time_sec": self.start_time_sec,
            "prompt_override": self.prompt_override,
            "status": self.status.value,
            "output_path": self.output_path,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=data["chunk_id"],
            shot_id=data["shot_id"],
            index=data["index"],
            duration_sec=data["duration_sec"],
            start_time_sec=data.get("start_time_sec", 0.0),
            prompt_override=data.get("prompt_override"),
            status=ChunkStatus(data.get("status", "pending")),
            output_path=data.get("output_path"),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# SHOT (Camera Setup)
# =============================================================================

@dataclass
class Shot:
    """
    A continuous camera take within a scene.
    
    A shot represents one "camera setup" â€” continuous footage from
    one angle until a cut. Shots are divided into chunks for rendering.
    
    Attributes:
        shot_id: Unique identifier
        scene_id: Parent scene ID
        index: Position within scene (0-indexed)
        duration_sec: Total duration
        shot_type: Camera framing (wide, close, etc.)
        description: What happens in this shot
        prompt: Generation prompt for this shot
        characters: Characters appearing in this shot
        location: Where this shot takes place
        props: Props featured in this shot
        camera_notes: Camera movement/angle notes
        transition_in: How we enter this shot
        transition_out: How we exit this shot
        chunks: Render chunks for this shot
    """
    shot_id: str
    scene_id: str
    index: int
    duration_sec: float
    description: str
    prompt: str
    shot_type: ShotType = ShotType.MEDIUM
    characters: List[EntityRef] = field(default_factory=list)
    location: Optional[EntityRef] = None
    props: List[EntityRef] = field(default_factory=list)
    camera_notes: str = ""
    transition_in: TransitionType = TransitionType.CUT
    transition_out: TransitionType = TransitionType.CUT
    chunks: List[Chunk] = field(default_factory=list)
    dialogue: List[Dict[str, str]] = field(default_factory=list)  # [{"character": "alice", "line": "Hello"}]
    events: List[Dict[str, Any]] = field(default_factory=list)  # State change events for WorldState
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Auto-generate chunks if not provided."""
        if not self.chunks:
            self.chunks = self._generate_chunks()
    
    def _generate_chunks(self, max_chunk_duration: float = 12.0) -> List[Chunk]:
        """
        Divide shot into render-sized chunks.
        
        Default max is 12 seconds (within model stability window).
        """
        chunks = []
        remaining = self.duration_sec
        current_time = 0.0
        index = 0
        
        while remaining > 0:
            chunk_duration = min(remaining, max_chunk_duration)
            
            chunk = Chunk(
                chunk_id=f"{self.shot_id}_chunk_{index:02d}",
                shot_id=self.shot_id,
                index=index,
                duration_sec=chunk_duration,
                start_time_sec=current_time,
            )
            chunks.append(chunk)
            
            current_time += chunk_duration
            remaining -= chunk_duration
            index += 1
        
        return chunks
    
    @property
    def chunk_count(self) -> int:
        """Number of chunks in this shot."""
        return len(self.chunks)
    
    @property
    def all_entities(self) -> Set[EntityRef]:
        """All entities (characters, location, props) in this shot."""
        entities = set(self.characters)
        if self.location:
            entities.add(self.location)
        entities.update(self.props)
        return entities
    
    @property
    def character_ids(self) -> List[str]:
        """List of character entity IDs."""
        return [c.entity_id for c in self.characters]
    
    @property
    def prop_ids(self) -> List[str]:
        """List of prop entity IDs."""
        return [p.entity_id for p in self.props]
    
    @property
    def all_entity_ids(self) -> Set[str]:
        """All entity IDs (characters, location, props) for event parsing."""
        ids = set(self.character_ids)
        ids.update(self.prop_ids)
        if self.location:
            ids.add(self.location.entity_id)
        return ids
    
    @property
    def is_multi_character(self) -> bool:
        """Does this shot have multiple characters?"""
        return len(self.characters) > 1
    
    @property
    def has_dialogue(self) -> bool:
        """Does this shot have dialogue?"""
        return len(self.dialogue) > 0
    
    @property
    def has_state_events(self) -> bool:
        """Does this shot have explicit state change events?"""
        return len(self.events) > 0
    
    def get_pending_chunks(self) -> List[Chunk]:
        """Get chunks that haven't been rendered yet."""
        return [c for c in self.chunks if c.status == ChunkStatus.PENDING]
    
    def get_completed_chunks(self) -> List[Chunk]:
        """Get successfully rendered chunks."""
        return [c for c in self.chunks if c.status == ChunkStatus.COMPLETED]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "index": self.index,
            "duration_sec": self.duration_sec,
            "description": self.description,
            "prompt": self.prompt,
            "shot_type": self.shot_type.value,
            "characters": [c.to_dict() for c in self.characters],
            "location": self.location.to_dict() if self.location else None,
            "props": [p.to_dict() for p in self.props],
            "camera_notes": self.camera_notes,
            "transition_in": self.transition_in.value,
            "transition_out": self.transition_out.value,
            "chunks": [c.to_dict() for c in self.chunks],
            "dialogue": self.dialogue,
            "events": self.events,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Shot":
        characters = [
            EntityRef(**c) for c in data.get("characters", [])
        ]
        location = EntityRef(**data["location"]) if data.get("location") else None
        props = [EntityRef(**p) for p in data.get("props", [])]
        chunks = [Chunk.from_dict(c) for c in data.get("chunks", [])]
        
        shot = cls(
            shot_id=data["shot_id"],
            scene_id=data["scene_id"],
            index=data["index"],
            duration_sec=data["duration_sec"],
            description=data["description"],
            prompt=data["prompt"],
            shot_type=ShotType(data.get("shot_type", "medium")),
            characters=characters,
            location=location,
            props=props,
            camera_notes=data.get("camera_notes", ""),
            transition_in=TransitionType(data.get("transition_in", "cut")),
            transition_out=TransitionType(data.get("transition_out", "cut")),
            chunks=chunks,  # Provide chunks to avoid regeneration
            dialogue=data.get("dialogue", []),
            events=data.get("events", []),
            metadata=data.get("metadata", {}),
        )
        return shot


# =============================================================================
# SCENE (Continuous Location/Time)
# =============================================================================

@dataclass
class Scene:
    """
    A scene is a sequence of shots in the same location/time.
    
    Scenes represent a continuous segment of the story â€” when the
    location or time changes significantly, it's a new scene.
    
    Attributes:
        scene_id: Unique identifier
        index: Position in film (0-indexed)
        title: Scene title/heading
        description: What happens in this scene
        location: Primary location
        time_of_day: Lighting/mood context
        characters: All characters appearing in scene
        shots: Shots within this scene
    """
    scene_id: str
    index: int
    title: str
    description: str
    location: Optional[EntityRef] = None
    time_of_day: str = "day"  # "day", "night", "dawn", "dusk"
    characters: List[EntityRef] = field(default_factory=list)
    shots: List[Shot] = field(default_factory=list)
    mood: str = ""  # "tense", "romantic", "action", etc.
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_sec(self) -> float:
        """Total duration of all shots in scene."""
        return sum(shot.duration_sec for shot in self.shots)
    
    @property
    def shot_count(self) -> int:
        """Number of shots in scene."""
        return len(self.shots)
    
    @property
    def chunk_count(self) -> int:
        """Total chunks across all shots."""
        return sum(shot.chunk_count for shot in self.shots)
    
    @property
    def all_entities(self) -> Set[EntityRef]:
        """All entities appearing in this scene."""
        entities = set(self.characters)
        if self.location:
            entities.add(self.location)
        for shot in self.shots:
            entities.update(shot.all_entities)
        return entities
    
    def get_shots_with_character(self, character_id: str) -> List[Shot]:
        """Get all shots featuring a specific character."""
        return [
            shot for shot in self.shots
            if character_id in shot.character_ids
        ]
    
    def add_shot(self, shot: Shot) -> None:
        """Add a shot to this scene."""
        shot.scene_id = self.scene_id
        shot.index = len(self.shots)
        self.shots.append(shot)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "index": self.index,
            "title": self.title,
            "description": self.description,
            "location": self.location.to_dict() if self.location else None,
            "time_of_day": self.time_of_day,
            "characters": [c.to_dict() for c in self.characters],
            "shots": [s.to_dict() for s in self.shots],
            "mood": self.mood,
            "notes": self.notes,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scene":
        location = EntityRef(**data["location"]) if data.get("location") else None
        characters = [EntityRef(**c) for c in data.get("characters", [])]
        shots = [Shot.from_dict(s) for s in data.get("shots", [])]
        
        return cls(
            scene_id=data["scene_id"],
            index=data["index"],
            title=data["title"],
            description=data["description"],
            location=location,
            time_of_day=data.get("time_of_day", "day"),
            characters=characters,
            shots=shots,
            mood=data.get("mood", ""),
            notes=data.get("notes", ""),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# SCENE GRAPH (The Complete Film)
# =============================================================================

@dataclass
class SceneGraph:
    """
    Complete hierarchical representation of a video project.
    
    This is the master blueprint that contains:
    - All scenes in order
    - All shots within scenes
    - All chunks within shots
    - All entity references
    
    The Director Agent builds this from a script, and the renderers
    consume it to generate the actual video.
    
    Usage:
        # Create from scratch
        graph = SceneGraph(project_id="my_film", title="My Film")
        scene = Scene(scene_id="scene_01", ...)
        graph.add_scene(scene)
        
        # Save and load
        graph.save(Path("project.json"))
        graph = SceneGraph.load(Path("project.json"))
        
        # Iterate for rendering
        for chunk in graph.iter_chunks():
            result = await renderer.generate(chunk_to_job(chunk))
    """
    project_id: str
    title: str
    description: str = ""
    scenes: List[Scene] = field(default_factory=list)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    version: int = 1
    author: str = ""
    
    # Global settings
    target_fps: int = 24
    target_resolution: tuple = (1280, 720)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # -------------------------------------------------------------------------
    # PROPERTIES
    # -------------------------------------------------------------------------
    
    @property
    def scene_count(self) -> int:
        """Number of scenes."""
        return len(self.scenes)
    
    @property
    def shot_count(self) -> int:
        """Total shots across all scenes."""
        return sum(scene.shot_count for scene in self.scenes)
    
    @property
    def chunk_count(self) -> int:
        """Total chunks across all scenes and shots."""
        return sum(scene.chunk_count for scene in self.scenes)
    
    @property
    def total_duration_sec(self) -> float:
        """Total duration of the film."""
        return sum(scene.duration_sec for scene in self.scenes)
    
    @property
    def total_duration_min(self) -> float:
        """Total duration in minutes."""
        return self.total_duration_sec / 60.0
    
    @property
    def all_characters(self) -> Set[EntityRef]:
        """All unique characters in the film."""
        characters = set()
        for scene in self.scenes:
            for char in scene.characters:
                if char.entity_type == "character":
                    characters.add(char)
        return characters
    
    @property
    def all_locations(self) -> Set[EntityRef]:
        """All unique locations in the film."""
        locations = set()
        for scene in self.scenes:
            if scene.location:
                locations.add(scene.location)
        return locations
    
    @property
    def all_entities(self) -> Set[EntityRef]:
        """All unique entities in the film."""
        entities = set()
        for scene in self.scenes:
            entities.update(scene.all_entities)
        return entities
    
    # -------------------------------------------------------------------------
    # SCENE MANAGEMENT
    # -------------------------------------------------------------------------
    
    def add_scene(self, scene: Scene) -> None:
        """Add a scene to the graph."""
        scene.index = len(self.scenes)
        self.scenes.append(scene)
        self._touch()
    
    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """Get a scene by ID."""
        for scene in self.scenes:
            if scene.scene_id == scene_id:
                return scene
        return None
    
    def get_shot(self, shot_id: str) -> Optional[Shot]:
        """Get a shot by ID (searches all scenes)."""
        for scene in self.scenes:
            for shot in scene.shots:
                if shot.shot_id == shot_id:
                    return shot
        return None
    
    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        """Get a chunk by ID (searches all scenes and shots)."""
        for scene in self.scenes:
            for shot in scene.shots:
                for chunk in shot.chunks:
                    if chunk.chunk_id == chunk_id:
                        return chunk
        return None
    
    # -------------------------------------------------------------------------
    # ITERATION
    # -------------------------------------------------------------------------
    
    def iter_scenes(self) -> Iterator[Scene]:
        """Iterate over scenes in order."""
        yield from self.scenes
    
    def iter_shots(self) -> Iterator[Shot]:
        """Iterate over all shots in order."""
        for scene in self.scenes:
            yield from scene.shots
    
    def iter_chunks(self) -> Iterator[Chunk]:
        """Iterate over all chunks in order."""
        for scene in self.scenes:
            for shot in scene.shots:
                yield from shot.chunks
    
    def iter_pending_chunks(self) -> Iterator[Chunk]:
        """Iterate over chunks that need rendering."""
        for chunk in self.iter_chunks():
            if chunk.status == ChunkStatus.PENDING:
                yield chunk
    
    def iter_shots_with_character(self, character_id: str) -> Iterator[Shot]:
        """Iterate over shots featuring a specific character."""
        for scene in self.scenes:
            for shot in scene.shots:
                if character_id in shot.character_ids:
                    yield shot
    
    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the scene graph."""
        pending = sum(1 for c in self.iter_chunks() if c.status == ChunkStatus.PENDING)
        completed = sum(1 for c in self.iter_chunks() if c.status == ChunkStatus.COMPLETED)
        failed = sum(1 for c in self.iter_chunks() if c.status == ChunkStatus.FAILED)
        
        return {
            "project_id": self.project_id,
            "title": self.title,
            "total_duration_sec": self.total_duration_sec,
            "total_duration_min": round(self.total_duration_min, 2),
            "scene_count": self.scene_count,
            "shot_count": self.shot_count,
            "chunk_count": self.chunk_count,
            "chunks_pending": pending,
            "chunks_completed": completed,
            "chunks_failed": failed,
            "progress_percent": round(100 * completed / max(1, self.chunk_count), 1),
            "character_count": len(self.all_characters),
            "location_count": len(self.all_locations),
        }
    
    # -------------------------------------------------------------------------
    # SERIALIZATION
    # -------------------------------------------------------------------------
    
    def _touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "scenes": [s.to_dict() for s in self.scenes],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "author": self.author,
            "target_fps": self.target_fps,
            "target_resolution": list(self.target_resolution),
            "metadata": self.metadata,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, path: Path) -> None:
        """Save to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.to_json())
        logger.info(f"Saved scene graph to {path}")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneGraph":
        """Create from dict."""
        scenes = [Scene.from_dict(s) for s in data.get("scenes", [])]
        resolution = data.get("target_resolution", [1280, 720])
        
        return cls(
            project_id=data["project_id"],
            title=data["title"],
            description=data.get("description", ""),
            scenes=scenes,
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat()),
            version=data.get("version", 1),
            author=data.get("author", ""),
            target_fps=data.get("target_fps", 24),
            target_resolution=tuple(resolution),
            metadata=data.get("metadata", {}),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "SceneGraph":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    @classmethod
    def load(cls, path: Path) -> "SceneGraph":
        """Load from JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        logger.info(f"Loaded scene graph from {path}")
        return cls.from_dict(data)
    
    # -------------------------------------------------------------------------
    # HASHING (For Change Detection)
    # -------------------------------------------------------------------------
    
    def content_hash(self) -> str:
        """
        Generate a hash of the scene graph content.
        
        Used to detect if the graph has changed (for caching, etc.)
        """
        # Hash the JSON representation (excluding timestamps)
        data = self.to_dict()
        data.pop("created_at", None)
        data.pop("updated_at", None)
        
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# =============================================================================
# BUILDER HELPERS
# =============================================================================

def generate_id(prefix: str = "") -> str:
    """Generate a unique ID."""
    unique = uuid.uuid4().hex[:8]
    return f"{prefix}_{unique}" if prefix else unique


def create_scene(
    title: str,
    description: str,
    location_id: Optional[str] = None,
    location_name: Optional[str] = None,
    character_ids: Optional[List[str]] = None,
    time_of_day: str = "day",
    mood: str = "",
) -> Scene:
    """
    Factory function to create a scene with sensible defaults.
    
    Usage:
        scene = create_scene(
            title="Kitchen Morning",
            description="Alice makes breakfast",
            location_id="kitchen",
            character_ids=["alice"]
        )
    """
    scene_id = generate_id("scene")
    
    location = None
    if location_id:
        location = EntityRef.location(location_id, location_name or location_id)
    
    characters = []
    if character_ids:
        characters = [EntityRef.character(cid) for cid in character_ids]
    
    return Scene(
        scene_id=scene_id,
        index=0,  # Will be set when added to graph
        title=title,
        description=description,
        location=location,
        time_of_day=time_of_day,
        characters=characters,
        mood=mood,
    )


def create_shot(
    description: str,
    prompt: str,
    duration_sec: float = 4.0,
    shot_type: ShotType = ShotType.MEDIUM,
    character_ids: Optional[List[str]] = None,
    location_id: Optional[str] = None,
    prop_ids: Optional[List[str]] = None,
    dialogue: Optional[List[Dict[str, str]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    camera_notes: str = "",
    max_chunk_duration: float = 12.0,
) -> Shot:
    """
    Factory function to create a shot with auto-chunking.
    
    Usage:
        shot = create_shot(
            description="Alice picks up the sword and walks to the door",
            prompt="A woman picking up an ancient sword, morning light",
            duration_sec=8.0,
            shot_type=ShotType.MEDIUM,
            character_ids=["alice"],
            prop_ids=["sword", "door"],
            events=[
                {"type": "pickup", "subject": "alice", "object": "sword"}
            ]
        )
    """
    shot_id = generate_id("shot")
    
    characters = []
    if character_ids:
        characters = [EntityRef.character(cid) for cid in character_ids]
    
    location = None
    if location_id:
        location = EntityRef.location(location_id)
    
    props = []
    if prop_ids:
        props = [EntityRef.prop(pid) for pid in prop_ids]
    
    shot = Shot(
        shot_id=shot_id,
        scene_id="",  # Will be set when added to scene
        index=0,  # Will be set when added to scene
        duration_sec=duration_sec,
        description=description,
        prompt=prompt,
        shot_type=shot_type,
        characters=characters,
        location=location,
        props=props,
        dialogue=dialogue or [],
        events=events or [],
        camera_notes=camera_notes,
        chunks=[],  # Will be auto-generated
    )
    
    # Generate chunks with custom max duration
    shot.chunks = shot._generate_chunks(max_chunk_duration)
    
    return shot