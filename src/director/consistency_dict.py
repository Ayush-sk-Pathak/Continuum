"""
Continuum Engine - Consistency Dictionary

Maps entity IDs to their canonical assets (LoRAs, face references, descriptions).
This is the "Visual Bible" that ensures Alice always looks like Alice.

The Scene Graph says WHO appears WHERE.
The Consistency Dictionary says WHAT they LOOK LIKE.

Design Principles:
1. Single source of truth for entity appearance
2. Supports degradation (LoRA → IP-Adapter → prompt-only)
3. Lazy validation (don't check file existence until needed)
4. JSON-serializable for persistence and LLM communication
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Iterator
from enum import Enum

from ..renderers.base import CharacterRef, LocationRef

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class EntityType(str, Enum):
    """Types of entities tracked in the dictionary."""
    CHARACTER = "character"
    LOCATION = "location"
    PROP = "prop"


class AssetStatus(str, Enum):
    """Status of an entity's assets."""
    COMPLETE = "complete"      # All required assets present
    PARTIAL = "partial"        # Some assets missing (can still render)
    MISSING = "missing"        # No usable assets


# =============================================================================
# ENTITY DEFINITIONS
# =============================================================================

@dataclass
class CharacterEntity:
    """
    Complete definition of a character's visual identity.
    
    Attributes:
        entity_id: Unique identifier (used in scene graph)
        name: Display name
        description: Text description for prompt enhancement
        lora_path: Path to trained LoRA (best quality)
        lora_strength: LoRA application strength (0.0-1.0)
        face_refs: Reference images for IP-Adapter fallback
        style_notes: Additional style guidance
        voice_id: TTS voice ID for dialogue
        tags: Searchable tags
    """
    entity_id: str
    name: str
    description: str = ""
    lora_path: Optional[str] = None
    lora_strength: float = 0.8
    face_refs: List[str] = field(default_factory=list)
    style_notes: str = ""
    voice_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    @property
    def has_lora(self) -> bool:
        """Check if LoRA path is set (doesn't verify file exists)."""
        return self.lora_path is not None and len(self.lora_path) > 0
    
    @property
    def has_face_refs(self) -> bool:
        """Check if face references are set."""
        return len(self.face_refs) > 0
    
    @property
    def identity_method(self) -> str:
        """Best available identity method."""
        if self.has_lora:
            return "lora"
        elif self.has_face_refs:
            return "ip_adapter"
        else:
            return "prompt"
    
    def validate_assets(self) -> AssetStatus:
        """
        Check if assets actually exist on disk.
        
        Returns:
            AssetStatus indicating what's available
        """
        has_valid_lora = self.has_lora and Path(self.lora_path).exists()
        has_valid_refs = self.has_face_refs and any(
            Path(ref).exists() for ref in self.face_refs
        )
        
        if has_valid_lora:
            return AssetStatus.COMPLETE
        elif has_valid_refs or self.description:
            return AssetStatus.PARTIAL
        else:
            return AssetStatus.MISSING
    
    def to_character_ref(self) -> CharacterRef:
        """Convert to renderer-compatible CharacterRef."""
        return CharacterRef(
            entity_id=self.entity_id,
            name=self.name,
            lora_path=Path(self.lora_path) if self.lora_path else None,
            face_refs=[Path(ref) for ref in self.face_refs],
            description=self.description,
            lora_strength=self.lora_strength,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": EntityType.CHARACTER.value,
            "name": self.name,
            "description": self.description,
            "lora_path": self.lora_path,
            "lora_strength": self.lora_strength,
            "face_refs": self.face_refs,
            "style_notes": self.style_notes,
            "voice_id": self.voice_id,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterEntity":
        return cls(
            entity_id=data["entity_id"],
            name=data["name"],
            description=data.get("description", ""),
            lora_path=data.get("lora_path"),
            lora_strength=data.get("lora_strength", 0.8),
            face_refs=data.get("face_refs", []),
            style_notes=data.get("style_notes", ""),
            voice_id=data.get("voice_id"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


@dataclass
class LocationEntity:
    """
    Complete definition of a location's visual identity.
    
    Attributes:
        entity_id: Unique identifier
        name: Display name
        description: Text description
        ref_images: Reference images for the location
        style_notes: Visual style guidance
        lighting_notes: Lighting preferences
        tags: Searchable tags
    """
    entity_id: str
    name: str
    description: str = ""
    ref_images: List[str] = field(default_factory=list)
    style_notes: str = ""
    lighting_notes: str = ""
    ambience_prompt: str = ""  # For audio generation
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    @property
    def has_refs(self) -> bool:
        """Check if reference images are set."""
        return len(self.ref_images) > 0
    
    def validate_assets(self) -> AssetStatus:
        """Check if assets exist on disk."""
        has_valid_refs = self.has_refs and any(
            Path(ref).exists() for ref in self.ref_images
        )
        
        if has_valid_refs:
            return AssetStatus.COMPLETE
        elif self.description:
            return AssetStatus.PARTIAL
        else:
            return AssetStatus.MISSING
    
    def to_location_ref(self) -> LocationRef:
        """Convert to renderer-compatible LocationRef."""
        return LocationRef(
            entity_id=self.entity_id,
            name=self.name,
            ref_images=[Path(ref) for ref in self.ref_images],
            description=self.description,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": EntityType.LOCATION.value,
            "name": self.name,
            "description": self.description,
            "ref_images": self.ref_images,
            "style_notes": self.style_notes,
            "lighting_notes": self.lighting_notes,
            "ambience_prompt": self.ambience_prompt,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationEntity":
        return cls(
            entity_id=data["entity_id"],
            name=data["name"],
            description=data.get("description", ""),
            ref_images=data.get("ref_images", []),
            style_notes=data.get("style_notes", ""),
            lighting_notes=data.get("lighting_notes", ""),
            ambience_prompt=data.get("ambience_prompt", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


@dataclass
class PropEntity:
    """
    Definition of a prop's visual identity.
    
    Props are objects that need to maintain consistency across shots
    (e.g., "the red mug" should always be the same red mug).
    """
    entity_id: str
    name: str
    description: str = ""
    ref_images: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    @property
    def has_refs(self) -> bool:
        return len(self.ref_images) > 0
    
    def validate_assets(self) -> AssetStatus:
        has_valid_refs = self.has_refs and any(
            Path(ref).exists() for ref in self.ref_images
        )
        if has_valid_refs:
            return AssetStatus.COMPLETE
        elif self.description:
            return AssetStatus.PARTIAL
        else:
            return AssetStatus.MISSING
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": EntityType.PROP.value,
            "name": self.name,
            "description": self.description,
            "ref_images": self.ref_images,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PropEntity":
        return cls(
            entity_id=data["entity_id"],
            name=data["name"],
            description=data.get("description", ""),
            ref_images=data.get("ref_images", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


# =============================================================================
# CONSISTENCY DICTIONARY
# =============================================================================

class ConsistencyDict:
    """
    The Visual Bible — maps entity IDs to their canonical assets.
    
    Usage:
        # Create and populate
        bible = ConsistencyDict()
        bible.add_character(CharacterEntity(
            entity_id="alice",
            name="Alice",
            lora_path="/models/alice.safetensors",
            description="A young woman with red hair"
        ))
        
        # Retrieve for rendering
        char_ref = bible.get_character_ref("alice")
        
        # Check what's available
        status = bible.validate_all()
        
        # Save/load
        bible.save(Path("bible.json"))
        bible = ConsistencyDict.load(Path("bible.json"))
    """
    
    def __init__(self):
        self._characters: Dict[str, CharacterEntity] = {}
        self._locations: Dict[str, LocationEntity] = {}
        self._props: Dict[str, PropEntity] = {}
        self._updated_at: str = datetime.utcnow().isoformat()
    
    # -------------------------------------------------------------------------
    # CHARACTER OPERATIONS
    # -------------------------------------------------------------------------
    
    def add_character(self, character: CharacterEntity) -> None:
        """Add or update a character."""
        self._characters[character.entity_id] = character
        self._touch()
        logger.debug(f"Added character: {character.entity_id} ({character.name})")
    
    def get_character(self, entity_id: str) -> Optional[CharacterEntity]:
        """Get a character by ID."""
        return self._characters.get(entity_id)
    
    def get_character_ref(self, entity_id: str) -> Optional[CharacterRef]:
        """Get a renderer-compatible CharacterRef."""
        char = self.get_character(entity_id)
        return char.to_character_ref() if char else None
    
    def remove_character(self, entity_id: str) -> bool:
        """Remove a character. Returns True if it existed."""
        if entity_id in self._characters:
            del self._characters[entity_id]
            self._touch()
            return True
        return False
    
    def list_characters(self) -> List[CharacterEntity]:
        """Get all characters."""
        return list(self._characters.values())
    
    def iter_characters(self) -> Iterator[CharacterEntity]:
        """Iterate over all characters."""
        yield from self._characters.values()
    
    # -------------------------------------------------------------------------
    # LOCATION OPERATIONS
    # -------------------------------------------------------------------------
    
    def add_location(self, location: LocationEntity) -> None:
        """Add or update a location."""
        self._locations[location.entity_id] = location
        self._touch()
        logger.debug(f"Added location: {location.entity_id} ({location.name})")
    
    def get_location(self, entity_id: str) -> Optional[LocationEntity]:
        """Get a location by ID."""
        return self._locations.get(entity_id)
    
    def get_location_ref(self, entity_id: str) -> Optional[LocationRef]:
        """Get a renderer-compatible LocationRef."""
        loc = self.get_location(entity_id)
        return loc.to_location_ref() if loc else None
    
    def remove_location(self, entity_id: str) -> bool:
        """Remove a location."""
        if entity_id in self._locations:
            del self._locations[entity_id]
            self._touch()
            return True
        return False
    
    def list_locations(self) -> List[LocationEntity]:
        """Get all locations."""
        return list(self._locations.values())
    
    def iter_locations(self) -> Iterator[LocationEntity]:
        """Iterate over all locations."""
        yield from self._locations.values()
    
    # -------------------------------------------------------------------------
    # PROP OPERATIONS
    # -------------------------------------------------------------------------
    
    def add_prop(self, prop: PropEntity) -> None:
        """Add or update a prop."""
        self._props[prop.entity_id] = prop
        self._touch()
        logger.debug(f"Added prop: {prop.entity_id} ({prop.name})")
    
    def get_prop(self, entity_id: str) -> Optional[PropEntity]:
        """Get a prop by ID."""
        return self._props.get(entity_id)
    
    def remove_prop(self, entity_id: str) -> bool:
        """Remove a prop."""
        if entity_id in self._props:
            del self._props[entity_id]
            self._touch()
            return True
        return False
    
    def list_props(self) -> List[PropEntity]:
        """Get all props."""
        return list(self._props.values())
    
    # -------------------------------------------------------------------------
    # GENERIC OPERATIONS
    # -------------------------------------------------------------------------
    
    def get_entity(self, entity_id: str, entity_type: Optional[EntityType] = None):
        """
        Get any entity by ID.
        
        If entity_type is provided, only searches that type.
        Otherwise searches all types.
        """
        if entity_type == EntityType.CHARACTER or entity_type is None:
            if entity_id in self._characters:
                return self._characters[entity_id]
        
        if entity_type == EntityType.LOCATION or entity_type is None:
            if entity_id in self._locations:
                return self._locations[entity_id]
        
        if entity_type == EntityType.PROP or entity_type is None:
            if entity_id in self._props:
                return self._props[entity_id]
        
        return None
    
    def has_entity(self, entity_id: str) -> bool:
        """Check if an entity exists."""
        return (
            entity_id in self._characters or
            entity_id in self._locations or
            entity_id in self._props
        )
    
    def all_entity_ids(self) -> Set[str]:
        """Get all entity IDs."""
        return (
            set(self._characters.keys()) |
            set(self._locations.keys()) |
            set(self._props.keys())
        )
    
    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------
    
    def validate_all(self) -> Dict[str, AssetStatus]:
        """
        Validate all entities and return their asset status.
        
        Returns:
            Dict mapping entity_id to AssetStatus
        """
        results = {}
        
        for char in self._characters.values():
            results[char.entity_id] = char.validate_assets()
        
        for loc in self._locations.values():
            results[loc.entity_id] = loc.validate_assets()
        
        for prop in self._props.values():
            results[prop.entity_id] = prop.validate_assets()
        
        return results
    
    def get_missing_entities(self) -> List[str]:
        """Get entity IDs with missing assets."""
        validation = self.validate_all()
        return [
            entity_id for entity_id, status in validation.items()
            if status == AssetStatus.MISSING
        ]
    
    def get_validation_report(self) -> Dict[str, Any]:
        """Get a detailed validation report."""
        validation = self.validate_all()
        
        complete = [eid for eid, s in validation.items() if s == AssetStatus.COMPLETE]
        partial = [eid for eid, s in validation.items() if s == AssetStatus.PARTIAL]
        missing = [eid for eid, s in validation.items() if s == AssetStatus.MISSING]
        
        return {
            "total_entities": len(validation),
            "complete": len(complete),
            "partial": len(partial),
            "missing": len(missing),
            "complete_ids": complete,
            "partial_ids": partial,
            "missing_ids": missing,
            "ready_to_render": len(missing) == 0,
        }
    
    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get dictionary statistics."""
        return {
            "character_count": len(self._characters),
            "location_count": len(self._locations),
            "prop_count": len(self._props),
            "total_entities": len(self.all_entity_ids()),
            "updated_at": self._updated_at,
        }
    
    # -------------------------------------------------------------------------
    # SERIALIZATION
    # -------------------------------------------------------------------------
    
    def _touch(self) -> None:
        """Update timestamp."""
        self._updated_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "characters": {k: v.to_dict() for k, v in self._characters.items()},
            "locations": {k: v.to_dict() for k, v in self._locations.items()},
            "props": {k: v.to_dict() for k, v in self._props.items()},
            "updated_at": self._updated_at,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, path: Path) -> None:
        """Save to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.to_json())
        logger.info(f"Saved consistency dictionary to {path}")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsistencyDict":
        """Create from dict."""
        bible = cls()
        
        for char_data in data.get("characters", {}).values():
            bible.add_character(CharacterEntity.from_dict(char_data))
        
        for loc_data in data.get("locations", {}).values():
            bible.add_location(LocationEntity.from_dict(loc_data))
        
        for prop_data in data.get("props", {}).values():
            bible.add_prop(PropEntity.from_dict(prop_data))
        
        bible._updated_at = data.get("updated_at", datetime.utcnow().isoformat())
        return bible
    
    @classmethod
    def from_json(cls, json_str: str) -> "ConsistencyDict":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    @classmethod
    def load(cls, path: Path) -> "ConsistencyDict":
        """Load from JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        logger.info(f"Loaded consistency dictionary from {path}")
        return cls.from_dict(data)
    
    # -------------------------------------------------------------------------
    # BULK OPERATIONS
    # -------------------------------------------------------------------------
    
    def merge_from(self, other: "ConsistencyDict", overwrite: bool = False) -> int:
        """
        Merge entities from another dictionary.
        
        Args:
            other: Dictionary to merge from
            overwrite: If True, overwrite existing entities
            
        Returns:
            Number of entities added/updated
        """
        count = 0
        
        for char in other.iter_characters():
            if overwrite or char.entity_id not in self._characters:
                self.add_character(char)
                count += 1
        
        for loc in other.iter_locations():
            if overwrite or loc.entity_id not in self._locations:
                self.add_location(loc)
                count += 1
        
        for prop in other.list_props():
            if overwrite or prop.entity_id not in self._props:
                self.add_prop(prop)
                count += 1
        
        return count
    
    def clear(self) -> None:
        """Remove all entities."""
        self._characters.clear()
        self._locations.clear()
        self._props.clear()
        self._touch()


# =============================================================================
# FACTORY HELPERS
# =============================================================================

def create_character(
    entity_id: str,
    name: str,
    description: str = "",
    lora_path: Optional[str] = None,
    face_refs: Optional[List[str]] = None,
    voice_id: Optional[str] = None,
) -> CharacterEntity:
    """
    Factory for creating a character entity.
    
    Usage:
        alice = create_character(
            entity_id="alice",
            name="Alice",
            description="A young woman with red hair and green eyes",
            lora_path="/models/loras/alice_v1.safetensors",
            face_refs=["refs/alice_front.png", "refs/alice_side.png"]
        )
    """
    return CharacterEntity(
        entity_id=entity_id,
        name=name,
        description=description,
        lora_path=lora_path,
        face_refs=face_refs or [],
        voice_id=voice_id,
    )


def create_location(
    entity_id: str,
    name: str,
    description: str = "",
    ref_images: Optional[List[str]] = None,
    ambience_prompt: str = "",
) -> LocationEntity:
    """Factory for creating a location entity."""
    return LocationEntity(
        entity_id=entity_id,
        name=name,
        description=description,
        ref_images=ref_images or [],
        ambience_prompt=ambience_prompt,
    )


def create_prop(
    entity_id: str,
    name: str,
    description: str = "",
    ref_images: Optional[List[str]] = None,
) -> PropEntity:
    """Factory for creating a prop entity."""
    return PropEntity(
        entity_id=entity_id,
        name=name,
        description=description,
        ref_images=ref_images or [],
    )