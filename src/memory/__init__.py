"""
Continuum Engine - Memory Module

Asset storage and retrieval. Handles LoRAs, reference images, and other
binary assets with support for local and S3 backends.
"""

from .asset_store import (
    # Main class
    AssetStore,
    # Metadata
    AssetMetadata,
    # Enums
    AssetType,
    StorageBackend,
    # Backends (for advanced use)
    StorageBackendBase,
    LocalStorageBackend,
    S3StorageBackend,
)

__all__ = [
    # Main class
    "AssetStore",
    # Metadata
    "AssetMetadata",
    # Enums
    "AssetType",
    "StorageBackend",
    # Backends
    "StorageBackendBase",
    "LocalStorageBackend",
    "S3StorageBackend",
]