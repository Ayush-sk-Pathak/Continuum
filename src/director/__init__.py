"""
Continuum Engine - Director Module

The "brain" of the system. Parses scripts, plans shots, maintains
consistency, and orchestrates the rendering pipeline.
"""

from .scene_graph import (
    # Main classes
    SceneGraph,
    Scene,
    Shot,
    Chunk,
    # Entity references
    EntityRef,
    # Enums
    ShotType,
    TransitionType,
    ChunkStatus,
    # Factory functions
    create_scene,
    create_shot,
    generate_id,
)

from .consistency_dict import (
    # Main class
    ConsistencyDict,
    # Entity definitions
    CharacterEntity,
    LocationEntity,
    PropEntity,
    # Enums
    EntityType,
    AssetStatus,
    # Factory functions
    create_character,
    create_location,
    create_prop,
)

from .script_parser import (
    # Main class
    DirectorAgent,
    DirectorConfig,
    # Enums
    LLMProvider,
    # Convenience functions
    parse_script,
    save_project,
    load_project,
)

__all__ = [
    # scene_graph
    "SceneGraph",
    "Scene",
    "Shot",
    "Chunk",
    "EntityRef",
    "ShotType",
    "TransitionType",
    "ChunkStatus",
    "create_scene",
    "create_shot",
    "generate_id",
    # consistency_dict
    "ConsistencyDict",
    "CharacterEntity",
    "LocationEntity",
    "PropEntity",
    "EntityType",
    "AssetStatus",
    "create_character",
    "create_location",
    "create_prop",
    # script_parser (Director Agent)
    "DirectorAgent",
    "DirectorConfig",
    "LLMProvider",
    "parse_script",
    "save_project",
    "load_project",
]