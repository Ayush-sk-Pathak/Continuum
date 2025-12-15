"""
Continuum Engine - Asset Store

Handles storage and retrieval of binary assets (LoRAs, images, videos).
Supports local filesystem and S3 backends with local caching.

Design Principles:
1. Backend-agnostic interface (local, S3, future cloud storage)
2. Automatic caching for remote assets
3. Lazy loading (don't fetch until needed)
4. Graceful fallback (S3 unavailable → use local cache)
"""

import hashlib
import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, BinaryIO
from enum import Enum
import json

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & TYPES
# =============================================================================

class AssetType(str, Enum):
    """Types of assets we store."""
    LORA = "lora"              # LoRA model files (.safetensors)
    IMAGE = "image"            # Reference images (PNG, JPG)
    VIDEO = "video"            # Video clips (MP4)
    AUDIO = "audio"            # Audio files (WAV, MP3)
    WORKFLOW = "workflow"      # ComfyUI workflows (JSON)
    OTHER = "other"


class StorageBackend(str, Enum):
    """Available storage backends."""
    LOCAL = "local"
    S3 = "s3"


# =============================================================================
# ASSET METADATA
# =============================================================================

@dataclass
class AssetMetadata:
    """
    Metadata for a stored asset.
    
    Attributes:
        asset_id: Unique identifier
        asset_type: Type of asset
        filename: Original filename
        size_bytes: File size
        content_hash: SHA256 hash of content
        created_at: When asset was stored
        tags: Searchable tags
        metadata: Additional key-value data
    """
    asset_id: str
    asset_type: AssetType
    filename: str
    size_bytes: int = 0
    content_hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetMetadata":
        return cls(
            asset_id=data["asset_id"],
            asset_type=AssetType(data["asset_type"]),
            filename=data["filename"],
            size_bytes=data.get("size_bytes", 0),
            content_hash=data.get("content_hash", ""),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# ABSTRACT BACKEND
# =============================================================================

class StorageBackendBase(ABC):
    """Abstract base for storage backends."""
    
    @abstractmethod
    def store(self, asset_id: str, data: bytes, metadata: AssetMetadata) -> str:
        """Store an asset. Returns the storage path/key."""
        pass
    
    @abstractmethod
    def retrieve(self, asset_id: str) -> Optional[bytes]:
        """Retrieve an asset by ID. Returns None if not found."""
        pass
    
    @abstractmethod
    def exists(self, asset_id: str) -> bool:
        """Check if an asset exists."""
        pass
    
    @abstractmethod
    def delete(self, asset_id: str) -> bool:
        """Delete an asset. Returns True if it existed."""
        pass
    
    @abstractmethod
    def get_metadata(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get metadata for an asset."""
        pass
    
    @abstractmethod
    def list_assets(self, asset_type: Optional[AssetType] = None) -> List[str]:
        """List asset IDs, optionally filtered by type."""
        pass


# =============================================================================
# LOCAL FILESYSTEM BACKEND
# =============================================================================

class LocalStorageBackend(StorageBackendBase):
    """
    Local filesystem storage backend.
    
    Directory structure:
        base_path/
        ├── lora/
        │   └── {asset_id}.safetensors
        ├── image/
        │   └── {asset_id}.png
        ├── metadata/
        │   └── {asset_id}.json
        └── ...
    """
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Create directory structure."""
        for asset_type in AssetType:
            (self.base_path / asset_type.value).mkdir(parents=True, exist_ok=True)
        (self.base_path / "metadata").mkdir(parents=True, exist_ok=True)
    
    def _get_asset_path(self, asset_id: str, asset_type: AssetType) -> Path:
        """Get the path for an asset file."""
        return self.base_path / asset_type.value / asset_id
    
    def _get_metadata_path(self, asset_id: str) -> Path:
        """Get the path for metadata file."""
        return self.base_path / "metadata" / f"{asset_id}.json"
    
    def store(self, asset_id: str, data: bytes, metadata: AssetMetadata) -> str:
        """Store an asset locally."""
        # Store the actual file
        asset_path = self._get_asset_path(asset_id, metadata.asset_type)
        asset_path.write_bytes(data)
        
        # Update metadata with size and hash
        metadata.size_bytes = len(data)
        metadata.content_hash = hashlib.sha256(data).hexdigest()
        
        # Store metadata
        meta_path = self._get_metadata_path(asset_id)
        meta_path.write_text(json.dumps(metadata.to_dict(), indent=2))
        
        logger.debug(f"Stored asset {asset_id} ({len(data)} bytes) at {asset_path}")
        return str(asset_path)
    
    def retrieve(self, asset_id: str) -> Optional[bytes]:
        """Retrieve an asset from local storage."""
        metadata = self.get_metadata(asset_id)
        if not metadata:
            return None
        
        asset_path = self._get_asset_path(asset_id, metadata.asset_type)
        if not asset_path.exists():
            return None
        
        return asset_path.read_bytes()
    
    def exists(self, asset_id: str) -> bool:
        """Check if asset exists."""
        meta_path = self._get_metadata_path(asset_id)
        return meta_path.exists()
    
    def delete(self, asset_id: str) -> bool:
        """Delete an asset."""
        metadata = self.get_metadata(asset_id)
        if not metadata:
            return False
        
        # Delete asset file
        asset_path = self._get_asset_path(asset_id, metadata.asset_type)
        if asset_path.exists():
            asset_path.unlink()
        
        # Delete metadata
        meta_path = self._get_metadata_path(asset_id)
        if meta_path.exists():
            meta_path.unlink()
        
        logger.debug(f"Deleted asset {asset_id}")
        return True
    
    def get_metadata(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get metadata for an asset."""
        meta_path = self._get_metadata_path(asset_id)
        if not meta_path.exists():
            return None
        
        data = json.loads(meta_path.read_text())
        return AssetMetadata.from_dict(data)
    
    def list_assets(self, asset_type: Optional[AssetType] = None) -> List[str]:
        """List all asset IDs."""
        meta_dir = self.base_path / "metadata"
        if not meta_dir.exists():
            return []
        
        asset_ids = []
        for meta_file in meta_dir.glob("*.json"):
            asset_id = meta_file.stem
            
            if asset_type:
                metadata = self.get_metadata(asset_id)
                if metadata and metadata.asset_type == asset_type:
                    asset_ids.append(asset_id)
            else:
                asset_ids.append(asset_id)
        
        return asset_ids
    
    def get_local_path(self, asset_id: str) -> Optional[Path]:
        """Get the local filesystem path for an asset."""
        metadata = self.get_metadata(asset_id)
        if not metadata:
            return None
        
        path = self._get_asset_path(asset_id, metadata.asset_type)
        return path if path.exists() else None


# =============================================================================
# S3 BACKEND (Optional)
# =============================================================================

class S3StorageBackend(StorageBackendBase):
    """
    S3 storage backend with local caching.
    
    Assets are stored in S3 and cached locally for fast access.
    Falls back to cache if S3 is unavailable.
    """
    
    def __init__(
        self,
        bucket: str,
        prefix: str = "assets",
        cache_dir: Optional[Path] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region: str = "us-east-1",
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        
        # Local cache
        self._cache_dir = cache_dir or Path.home() / ".continuum" / "asset_cache"
        self._local_backend = LocalStorageBackend(self._cache_dir)
        
        # S3 client (lazy initialization)
        self._client = None
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
    
    def _get_client(self):
        """Lazy-initialize S3 client."""
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client(
                    "s3",
                    region_name=self.region,
                    aws_access_key_id=self._aws_access_key_id,
                    aws_secret_access_key=self._aws_secret_access_key,
                )
            except ImportError:
                logger.warning("boto3 not installed, S3 backend unavailable")
                return None
            except Exception as e:
                logger.warning(f"Failed to initialize S3 client: {e}")
                return None
        return self._client
    
    def _s3_key(self, asset_id: str, asset_type: AssetType) -> str:
        """Generate S3 key for an asset."""
        return f"{self.prefix}/{asset_type.value}/{asset_id}"
    
    def _metadata_key(self, asset_id: str) -> str:
        """Generate S3 key for metadata."""
        return f"{self.prefix}/metadata/{asset_id}.json"
    
    def store(self, asset_id: str, data: bytes, metadata: AssetMetadata) -> str:
        """Store to S3 and local cache."""
        # Always store locally first (cache)
        self._local_backend.store(asset_id, data, metadata)
        
        # Try to store in S3
        client = self._get_client()
        if client:
            try:
                # Store asset
                key = self._s3_key(asset_id, metadata.asset_type)
                client.put_object(Bucket=self.bucket, Key=key, Body=data)
                
                # Store metadata
                meta_key = self._metadata_key(asset_id)
                client.put_object(
                    Bucket=self.bucket,
                    Key=meta_key,
                    Body=json.dumps(metadata.to_dict()).encode(),
                    ContentType="application/json"
                )
                
                logger.debug(f"Stored asset {asset_id} to S3: s3://{self.bucket}/{key}")
                return f"s3://{self.bucket}/{key}"
                
            except Exception as e:
                logger.warning(f"Failed to store {asset_id} to S3: {e}")
        
        # Return local path as fallback
        return str(self._local_backend.get_local_path(asset_id))
    
    def retrieve(self, asset_id: str) -> Optional[bytes]:
        """Retrieve from cache or S3."""
        # Check local cache first
        data = self._local_backend.retrieve(asset_id)
        if data:
            return data
        
        # Try S3
        client = self._get_client()
        if client:
            try:
                metadata = self._get_s3_metadata(asset_id)
                if metadata:
                    key = self._s3_key(asset_id, metadata.asset_type)
                    response = client.get_object(Bucket=self.bucket, Key=key)
                    data = response["Body"].read()
                    
                    # Cache locally
                    self._local_backend.store(asset_id, data, metadata)
                    
                    logger.debug(f"Retrieved {asset_id} from S3 and cached locally")
                    return data
                    
            except Exception as e:
                logger.warning(f"Failed to retrieve {asset_id} from S3: {e}")
        
        return None
    
    def _get_s3_metadata(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get metadata from S3."""
        client = self._get_client()
        if not client:
            return None
        
        try:
            meta_key = self._metadata_key(asset_id)
            response = client.get_object(Bucket=self.bucket, Key=meta_key)
            data = json.loads(response["Body"].read().decode())
            return AssetMetadata.from_dict(data)
        except Exception:
            return None
    
    def exists(self, asset_id: str) -> bool:
        """Check local cache then S3."""
        if self._local_backend.exists(asset_id):
            return True
        
        client = self._get_client()
        if client:
            try:
                meta_key = self._metadata_key(asset_id)
                client.head_object(Bucket=self.bucket, Key=meta_key)
                return True
            except Exception:
                pass
        
        return False
    
    def delete(self, asset_id: str) -> bool:
        """Delete from both S3 and cache."""
        deleted = self._local_backend.delete(asset_id)
        
        client = self._get_client()
        if client:
            try:
                metadata = self.get_metadata(asset_id)
                if metadata:
                    key = self._s3_key(asset_id, metadata.asset_type)
                    client.delete_object(Bucket=self.bucket, Key=key)
                    client.delete_object(Bucket=self.bucket, Key=self._metadata_key(asset_id))
                    deleted = True
            except Exception as e:
                logger.warning(f"Failed to delete {asset_id} from S3: {e}")
        
        return deleted
    
    def get_metadata(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get metadata from cache or S3."""
        # Check local first
        metadata = self._local_backend.get_metadata(asset_id)
        if metadata:
            return metadata
        
        # Try S3
        return self._get_s3_metadata(asset_id)
    
    def list_assets(self, asset_type: Optional[AssetType] = None) -> List[str]:
        """List assets from local cache."""
        # For simplicity, list from local cache
        # Full S3 listing would require pagination
        return self._local_backend.list_assets(asset_type)
    
    def get_local_path(self, asset_id: str) -> Optional[Path]:
        """Get local path, downloading from S3 if needed."""
        # Check if already cached
        path = self._local_backend.get_local_path(asset_id)
        if path:
            return path
        
        # Try to download from S3
        data = self.retrieve(asset_id)
        if data:
            return self._local_backend.get_local_path(asset_id)
        
        return None


# =============================================================================
# ASSET STORE (Main Interface)
# =============================================================================

class AssetStore:
    """
    Main interface for asset storage.
    
    Provides a unified API regardless of backend (local or S3).
    Handles asset registration, retrieval, and path resolution.
    
    Usage:
        # Create store
        store = AssetStore.create_local(Path("./assets"))
        
        # Store an asset
        with open("alice.safetensors", "rb") as f:
            store.store_file("alice_lora", f, AssetType.LORA, tags=["character"])
        
        # Get path for rendering
        path = store.get_path("alice_lora")
        
        # Register existing file (don't copy)
        store.register_external("kitchen_ref", Path("./refs/kitchen.png"), AssetType.IMAGE)
    """
    
    def __init__(self, backend: StorageBackendBase):
        self._backend = backend
        self._external_paths: Dict[str, Path] = {}  # For registered external files
    
    @classmethod
    def create_local(cls, base_path: Path) -> "AssetStore":
        """Create a store with local filesystem backend."""
        backend = LocalStorageBackend(base_path)
        return cls(backend)
    
    @classmethod
    def create_s3(
        cls,
        bucket: str,
        prefix: str = "assets",
        cache_dir: Optional[Path] = None,
        **kwargs
    ) -> "AssetStore":
        """Create a store with S3 backend."""
        backend = S3StorageBackend(bucket, prefix, cache_dir, **kwargs)
        return cls(backend)
    
    # -------------------------------------------------------------------------
    # STORAGE OPERATIONS
    # -------------------------------------------------------------------------
    
    def store_bytes(
        self,
        asset_id: str,
        data: bytes,
        asset_type: AssetType,
        filename: str = "",
        tags: Optional[List[str]] = None,
        **extra_metadata
    ) -> str:
        """
        Store raw bytes as an asset.
        
        Returns the storage location (path or S3 URI).
        """
        metadata = AssetMetadata(
            asset_id=asset_id,
            asset_type=asset_type,
            filename=filename or asset_id,
            tags=tags or [],
            metadata=extra_metadata,
        )
        return self._backend.store(asset_id, data, metadata)
    
    def store_file(
        self,
        asset_id: str,
        file: BinaryIO,
        asset_type: AssetType,
        filename: str = "",
        tags: Optional[List[str]] = None,
        **extra_metadata
    ) -> str:
        """Store a file object as an asset."""
        data = file.read()
        return self.store_bytes(asset_id, data, asset_type, filename, tags, **extra_metadata)
    
    def store_path(
        self,
        asset_id: str,
        source_path: Path,
        asset_type: AssetType,
        tags: Optional[List[str]] = None,
        **extra_metadata
    ) -> str:
        """Store a file from a path."""
        with open(source_path, "rb") as f:
            return self.store_file(
                asset_id, f, asset_type,
                filename=source_path.name,
                tags=tags,
                **extra_metadata
            )
    
    def register_external(
        self,
        asset_id: str,
        path: Path,
        asset_type: AssetType,
        tags: Optional[List[str]] = None,
    ) -> None:
        """
        Register an external file without copying it.
        
        Useful for large files that shouldn't be duplicated
        (e.g., LoRAs already in a models directory).
        """
        if not path.exists():
            raise FileNotFoundError(f"External file not found: {path}")
        
        self._external_paths[asset_id] = path.resolve()
        
        # Store just metadata
        metadata = AssetMetadata(
            asset_id=asset_id,
            asset_type=asset_type,
            filename=path.name,
            size_bytes=path.stat().st_size,
            tags=tags or [],
            metadata={"external_path": str(path.resolve())},
        )
        
        # Store empty bytes (metadata only)
        # In a real implementation, you might skip the backend entirely
        meta_path = self._backend._get_metadata_path(asset_id) if hasattr(self._backend, '_get_metadata_path') else None
        if meta_path:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(metadata.to_dict(), indent=2))
        
        logger.debug(f"Registered external asset {asset_id} -> {path}")
    
    # -------------------------------------------------------------------------
    # RETRIEVAL OPERATIONS
    # -------------------------------------------------------------------------
    
    def get_bytes(self, asset_id: str) -> Optional[bytes]:
        """Get asset content as bytes."""
        # Check external paths first
        if asset_id in self._external_paths:
            path = self._external_paths[asset_id]
            return path.read_bytes() if path.exists() else None
        
        return self._backend.retrieve(asset_id)
    
    def get_path(self, asset_id: str) -> Optional[Path]:
        """
        Get a local filesystem path for the asset.
        
        This is the primary method for getting assets for rendering.
        Downloads from S3 if needed.
        """
        # Check external paths first
        if asset_id in self._external_paths:
            path = self._external_paths[asset_id]
            return path if path.exists() else None
        
        # Get from backend
        if hasattr(self._backend, 'get_local_path'):
            return self._backend.get_local_path(asset_id)
        
        # Fallback: retrieve bytes and check metadata for path
        metadata = self._backend.get_metadata(asset_id)
        if metadata and hasattr(self._backend, '_get_asset_path'):
            return self._backend._get_asset_path(asset_id, metadata.asset_type)
        
        return None
    
    def get_metadata(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get metadata for an asset."""
        return self._backend.get_metadata(asset_id)
    
    def exists(self, asset_id: str) -> bool:
        """Check if an asset exists."""
        if asset_id in self._external_paths:
            return self._external_paths[asset_id].exists()
        return self._backend.exists(asset_id)
    
    # -------------------------------------------------------------------------
    # LISTING & SEARCH
    # -------------------------------------------------------------------------
    
    def list_assets(self, asset_type: Optional[AssetType] = None) -> List[str]:
        """List all asset IDs."""
        backend_assets = self._backend.list_assets(asset_type)
        external_assets = list(self._external_paths.keys())
        return list(set(backend_assets + external_assets))
    
    def list_by_type(self, asset_type: AssetType) -> List[str]:
        """List assets of a specific type."""
        return self._backend.list_assets(asset_type)
    
    def search_by_tag(self, tag: str) -> List[str]:
        """Search assets by tag."""
        results = []
        for asset_id in self.list_assets():
            metadata = self.get_metadata(asset_id)
            if metadata and tag in metadata.tags:
                results.append(asset_id)
        return results
    
    # -------------------------------------------------------------------------
    # DELETION
    # -------------------------------------------------------------------------
    
    def delete(self, asset_id: str) -> bool:
        """Delete an asset."""
        if asset_id in self._external_paths:
            del self._external_paths[asset_id]
            # Don't delete the actual external file
        return self._backend.delete(asset_id)
    
    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        all_assets = self.list_assets()
        
        by_type = {}
        total_size = 0
        
        for asset_id in all_assets:
            metadata = self.get_metadata(asset_id)
            if metadata:
                type_name = metadata.asset_type.value
                by_type[type_name] = by_type.get(type_name, 0) + 1
                total_size += metadata.size_bytes
        
        return {
            "total_assets": len(all_assets),
            "by_type": by_type,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "external_count": len(self._external_paths),
        }