"""
Continuum Engine - Cache Manager

Provides multi-tier caching (Memory → Disk → Remote) for resilient operation.
This is the "local fallback" that keeps the system running when cloud services
are unavailable.

The Problem:
    Cloud services (S3, Pinecone, APIs) can be slow or unavailable.
    Without caching:
    - Every asset fetch is a network call (~100-500ms)
    - Cloud outage = complete system failure
    - Development requires constant internet

The Solution:
    Multi-tier cache with automatic fallback:
    - L1 (Memory): Hot data, instant access (~1μs)
    - L2 (Disk): Warm data, fast access (~1ms)
    - L3 (Remote): Cold data, network fetch (~100ms+)

Architecture Position:
    AssetStore → uses Cache for local storage
    VisualRAG → uses Cache for embedding persistence
    SceneGraph → uses Cache for LLM-generated graphs
    BridgeEngine → uses Cache for frame extraction

Design Principles:
    1. Transparent: Callers don't know if data came from cache
    2. LRU eviction: Automatic cleanup when space is limited
    3. TTL support: Time-based expiration for stale data
    4. Type-aware: Different strategies for different data types
    5. Observable: Statistics for debugging and monitoring
    6. Offline-friendly: Full operation without network
"""

import hashlib
import json
import logging
import os
import pickle
import shutil
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar, Union
import tempfile

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default cache sizes
DEFAULT_MEMORY_CACHE_SIZE = 100  # Number of items in memory
DEFAULT_DISK_CACHE_SIZE_MB = 1024  # 1GB disk cache
DEFAULT_TTL_HOURS = 24  # Default time-to-live

# Cache subdirectories
CACHE_SUBDIRS = ["images", "videos", "embeddings", "metadata", "frames", "audio", "workflows"]


# =============================================================================
# TYPE VARIABLES
# =============================================================================

T = TypeVar("T")  # Generic type for cached values


# =============================================================================
# ENUMS
# =============================================================================

class CacheType(str, Enum):
    """Types of cached data (affects storage strategy)."""
    IMAGE = "images"           # PNG, JPG files
    VIDEO = "videos"           # MP4 files
    EMBEDDING = "embeddings"   # Numpy arrays / vectors
    METADATA = "metadata"      # JSON metadata
    FRAME = "frames"           # Extracted video frames
    AUDIO = "audio"            # WAV, MP3 files
    WORKFLOW = "workflows"     # ComfyUI JSON workflows
    GENERIC = "generic"        # Arbitrary data


class CacheStrategy(str, Enum):
    """Caching strategies."""
    LRU = "lru"                # Least Recently Used eviction
    LFU = "lfu"                # Least Frequently Used eviction
    TTL = "ttl"                # Time-based expiration only
    FIFO = "fifo"              # First In First Out


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class CacheEntry:
    """
    Metadata for a cached item.
    
    Stored alongside the actual data to track access patterns and expiration.
    """
    key: str
    cache_type: CacheType
    size_bytes: int
    created_at: float  # timestamp
    accessed_at: float  # timestamp (for LRU)
    access_count: int = 0  # (for LFU)
    ttl_sec: Optional[float] = None
    content_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl_sec is None:
            return False
        return time.time() > (self.created_at + self.ttl_sec)
    
    @property
    def age_sec(self) -> float:
        """Age of entry in seconds."""
        return time.time() - self.created_at
    
    def touch(self) -> None:
        """Update access time and count."""
        self.accessed_at = time.time()
        self.access_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "cache_type": self.cache_type.value,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "ttl_sec": self.ttl_sec,
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        return cls(
            key=data["key"],
            cache_type=CacheType(data["cache_type"]),
            size_bytes=data["size_bytes"],
            created_at=data["created_at"],
            accessed_at=data["accessed_at"],
            access_count=data.get("access_count", 0),
            ttl_sec=data.get("ttl_sec"),
            content_hash=data.get("content_hash", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CacheStats:
    """Statistics about cache usage."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size_bytes: int = 0
    entry_count: int = 0
    oldest_entry_age_sec: float = 0.0
    newest_entry_age_sec: float = 0.0
    
    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def size_mb(self) -> float:
        """Total size in megabytes."""
        return self.total_size_bytes / (1024 * 1024)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hit_rate:.2%}",
            "evictions": self.evictions,
            "total_size_mb": f"{self.size_mb:.2f}",
            "entry_count": self.entry_count,
            "oldest_age_sec": self.oldest_entry_age_sec,
            "newest_age_sec": self.newest_entry_age_sec,
        }


# =============================================================================
# MEMORY CACHE (L1)
# =============================================================================

class MemoryCache(Generic[T]):
    """
    In-memory LRU cache (L1 tier).
    
    Fast access for hot data. Thread-safe with lock.
    """
    
    def __init__(
        self,
        max_size: int = DEFAULT_MEMORY_CACHE_SIZE,
        strategy: CacheStrategy = CacheStrategy.LRU,
    ):
        """
        Initialize memory cache.
        
        Args:
            max_size: Maximum number of items
            strategy: Eviction strategy
        """
        self.max_size = max_size
        self.strategy = strategy
        self._cache: OrderedDict[str, Tuple[T, CacheEntry]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()
    
    def get(self, key: str) -> Optional[T]:
        """Get item from cache."""
        with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                return None
            
            value, entry = self._cache[key]
            
            # Check TTL
            if entry.is_expired:
                self._remove(key)
                self._stats.misses += 1
                return None
            
            # Update access (LRU)
            entry.touch()
            if self.strategy == CacheStrategy.LRU:
                self._cache.move_to_end(key)
            
            self._stats.hits += 1
            return value
    
    def put(
        self,
        key: str,
        value: T,
        cache_type: CacheType = CacheType.GENERIC,
        ttl_sec: Optional[float] = None,
        size_bytes: int = 0,
    ) -> None:
        """Put item in cache."""
        with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                self._evict_one()
            
            # Create entry
            now = time.time()
            entry = CacheEntry(
                key=key,
                cache_type=cache_type,
                size_bytes=size_bytes or self._estimate_size(value),
                created_at=now,
                accessed_at=now,
                ttl_sec=ttl_sec,
            )
            
            self._cache[key] = (value, entry)
            self._stats.entry_count = len(self._cache)
    
    def delete(self, key: str) -> bool:
        """Delete item from cache."""
        with self._lock:
            return self._remove(key)
    
    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats()
    
    def contains(self, key: str) -> bool:
        """Check if key exists (without touching)."""
        with self._lock:
            if key not in self._cache:
                return False
            _, entry = self._cache[key]
            return not entry.is_expired
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            stats = CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                entry_count=len(self._cache),
            )
            
            if self._cache:
                ages = [time.time() - e.created_at for _, e in self._cache.values()]
                stats.oldest_entry_age_sec = max(ages)
                stats.newest_entry_age_sec = min(ages)
                stats.total_size_bytes = sum(e.size_bytes for _, e in self._cache.values())
            
            return stats
    
    def _remove(self, key: str) -> bool:
        """Internal remove without lock."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def _evict_one(self) -> None:
        """Evict one item based on strategy."""
        if not self._cache:
            return
        
        if self.strategy == CacheStrategy.LRU:
            # Remove oldest (first item in OrderedDict)
            key = next(iter(self._cache))
        elif self.strategy == CacheStrategy.LFU:
            # Remove least frequently used
            key = min(self._cache.keys(), key=lambda k: self._cache[k][1].access_count)
        else:  # FIFO
            key = next(iter(self._cache))
        
        self._remove(key)
        self._stats.evictions += 1
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate memory size of value."""
        try:
            import sys
            return sys.getsizeof(value)
        except:
            return 1024  # Default estimate


# =============================================================================
# DISK CACHE (L2)
# =============================================================================

class DiskCache:
    """
    Disk-based LRU cache (L2 tier).
    
    Persistent storage for warm data. Survives restarts.
    Uses file system for storage with JSON metadata index.
    """
    
    def __init__(
        self,
        cache_dir: Path,
        max_size_mb: float = DEFAULT_DISK_CACHE_SIZE_MB,
        strategy: CacheStrategy = CacheStrategy.LRU,
    ):
        """
        Initialize disk cache.
        
        Args:
            cache_dir: Base directory for cache files
            max_size_mb: Maximum cache size in megabytes
            strategy: Eviction strategy
        """
        self.cache_dir = Path(cache_dir)
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.strategy = strategy
        
        # Create directory structure
        self._ensure_directories()
        
        # Index file for metadata
        self._index_path = self.cache_dir / "index.json"
        self._index: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        
        # Load existing index
        self._load_index()
        
        # Stats
        self._stats = CacheStats()
        
        logger.info(f"DiskCache initialized: {cache_dir} (max {max_size_mb}MB)")
    
    def _ensure_directories(self) -> None:
        """Create cache directory structure."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for subdir in CACHE_SUBDIRS:
            (self.cache_dir / subdir).mkdir(exist_ok=True)
    
    def _load_index(self) -> None:
        """Load index from disk."""
        if self._index_path.exists():
            try:
                with open(self._index_path) as f:
                    data = json.load(f)
                self._index = {
                    k: CacheEntry.from_dict(v) 
                    for k, v in data.items()
                }
                logger.debug(f"Loaded cache index: {len(self._index)} entries")
            except Exception as e:
                logger.warning(f"Failed to load cache index: {e}")
                self._index = {}
    
    def _save_index(self) -> None:
        """Save index to disk."""
        try:
            with open(self._index_path, "w") as f:
                json.dump(
                    {k: v.to_dict() for k, v in self._index.items()},
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"Failed to save cache index: {e}")
    
    def _get_file_path(self, key: str, cache_type: CacheType) -> Path:
        """Get file path for a cache key."""
        # Sanitize key for filesystem
        safe_key = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.cache_dir / cache_type.value / safe_key
    
    def get(self, key: str) -> Optional[bytes]:
        """Get item from disk cache."""
        with self._lock:
            if key not in self._index:
                self._stats.misses += 1
                return None
            
            entry = self._index[key]
            
            # Check TTL
            if entry.is_expired:
                self.delete(key)
                self._stats.misses += 1
                return None
            
            # Read file
            file_path = self._get_file_path(key, entry.cache_type)
            if not file_path.exists():
                # Index out of sync, remove entry
                del self._index[key]
                self._save_index()
                self._stats.misses += 1
                return None
            
            try:
                data = file_path.read_bytes()
                entry.touch()
                self._stats.hits += 1
                return data
            except Exception as e:
                logger.warning(f"Failed to read cache file {file_path}: {e}")
                self._stats.misses += 1
                return None
    
    def get_path(self, key: str) -> Optional[Path]:
        """Get file path for cached item (if exists)."""
        with self._lock:
            if key not in self._index:
                return None
            
            entry = self._index[key]
            if entry.is_expired:
                return None
            
            file_path = self._get_file_path(key, entry.cache_type)
            return file_path if file_path.exists() else None
    
    def put(
        self,
        key: str,
        data: bytes,
        cache_type: CacheType = CacheType.GENERIC,
        ttl_sec: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Put item in disk cache.
        
        Returns:
            Path to the cached file
        """
        with self._lock:
            size = len(data)
            
            # Evict if necessary
            self._ensure_space(size)
            
            # Write file
            file_path = self._get_file_path(key, cache_type)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(data)
            
            # Create entry
            now = time.time()
            entry = CacheEntry(
                key=key,
                cache_type=cache_type,
                size_bytes=size,
                created_at=now,
                accessed_at=now,
                ttl_sec=ttl_sec,
                content_hash=hashlib.md5(data).hexdigest(),
                metadata=metadata or {},
            )
            
            self._index[key] = entry
            self._save_index()
            
            self._stats.entry_count = len(self._index)
            
            return file_path
    
    def put_file(
        self,
        key: str,
        source_path: Path,
        cache_type: CacheType = CacheType.GENERIC,
        ttl_sec: Optional[float] = None,
        copy: bool = True,
    ) -> Path:
        """
        Put a file in cache (by copying or moving).
        
        Args:
            key: Cache key
            source_path: Source file path
            cache_type: Type of cached data
            ttl_sec: Time-to-live in seconds
            copy: If True, copy file; if False, move file
            
        Returns:
            Path to the cached file
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        
        with self._lock:
            size = source_path.stat().st_size
            self._ensure_space(size)
            
            dest_path = self._get_file_path(key, cache_type)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            if copy:
                shutil.copy2(source_path, dest_path)
            else:
                shutil.move(source_path, dest_path)
            
            # Create entry
            now = time.time()
            entry = CacheEntry(
                key=key,
                cache_type=cache_type,
                size_bytes=size,
                created_at=now,
                accessed_at=now,
                ttl_sec=ttl_sec,
            )
            
            self._index[key] = entry
            self._save_index()
            
            return dest_path
    
    def delete(self, key: str) -> bool:
        """Delete item from cache."""
        with self._lock:
            if key not in self._index:
                return False
            
            entry = self._index[key]
            file_path = self._get_file_path(key, entry.cache_type)
            
            # Delete file
            if file_path.exists():
                file_path.unlink()
            
            # Remove from index
            del self._index[key]
            self._save_index()
            
            return True
    
    def clear(self) -> None:
        """Clear all cached items."""
        with self._lock:
            # Delete all files in cache subdirectories
            for subdir in CACHE_SUBDIRS:
                subdir_path = self.cache_dir / subdir
                if subdir_path.exists():
                    shutil.rmtree(subdir_path)
                subdir_path.mkdir(exist_ok=True)
            
            # Clear index
            self._index.clear()
            self._save_index()
            
            # Reset stats
            self._stats = CacheStats()
            
            logger.info("Disk cache cleared")
    
    def contains(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self._lock:
            if key not in self._index:
                return False
            entry = self._index[key]
            if entry.is_expired:
                return False
            file_path = self._get_file_path(key, entry.cache_type)
            return file_path.exists()
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            total_size = sum(e.size_bytes for e in self._index.values())
            
            stats = CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                total_size_bytes=total_size,
                entry_count=len(self._index),
            )
            
            if self._index:
                ages = [time.time() - e.created_at for e in self._index.values()]
                stats.oldest_entry_age_sec = max(ages) if ages else 0
                stats.newest_entry_age_sec = min(ages) if ages else 0
            
            return stats
    
    def _ensure_space(self, needed_bytes: int) -> None:
        """Ensure enough space is available, evicting if necessary."""
        current_size = sum(e.size_bytes for e in self._index.values())
        
        while current_size + needed_bytes > self.max_size_bytes and self._index:
            self._evict_one()
            current_size = sum(e.size_bytes for e in self._index.values())
    
    def _evict_one(self) -> None:
        """Evict one item based on strategy."""
        if not self._index:
            return
        
        # Find item to evict
        if self.strategy == CacheStrategy.LRU:
            key = min(self._index.keys(), key=lambda k: self._index[k].accessed_at)
        elif self.strategy == CacheStrategy.LFU:
            key = min(self._index.keys(), key=lambda k: self._index[k].access_count)
        elif self.strategy == CacheStrategy.TTL:
            # Evict oldest
            key = min(self._index.keys(), key=lambda k: self._index[k].created_at)
        else:  # FIFO
            key = min(self._index.keys(), key=lambda k: self._index[k].created_at)
        
        self.delete(key)
        self._stats.evictions += 1
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            expired = [k for k, v in self._index.items() if v.is_expired]
            for key in expired:
                self.delete(key)
            return len(expired)
    
    def list_keys(self, cache_type: Optional[CacheType] = None) -> List[str]:
        """List all cache keys, optionally filtered by type."""
        with self._lock:
            if cache_type is None:
                return list(self._index.keys())
            return [k for k, v in self._index.items() if v.cache_type == cache_type]


# =============================================================================
# UNIFIED CACHE MANAGER
# =============================================================================

class CacheManager:
    """
    Unified multi-tier cache manager.
    
    Provides a single interface for L1 (memory) and L2 (disk) caching
    with automatic tier management.
    
    Usage:
        cache = CacheManager(cache_dir=Path("./cache"))
        
        # Store data
        cache.put("asset:123", data, cache_type=CacheType.IMAGE)
        
        # Retrieve (checks L1, then L2)
        data = cache.get("asset:123")
        
        # Store file directly
        cache.put_file("video:456", Path("output.mp4"), CacheType.VIDEO)
        
        # Get file path (for direct file access)
        path = cache.get_path("video:456")
        
        # Statistics
        stats = cache.get_combined_stats()
    """
    
    def __init__(
        self,
        cache_dir: Path,
        memory_size: int = DEFAULT_MEMORY_CACHE_SIZE,
        disk_size_mb: float = DEFAULT_DISK_CACHE_SIZE_MB,
        default_ttl_hours: float = DEFAULT_TTL_HOURS,
        strategy: CacheStrategy = CacheStrategy.LRU,
    ):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Base directory for disk cache
            memory_size: Max items in memory cache
            disk_size_mb: Max disk cache size in MB
            default_ttl_hours: Default TTL for cached items
            strategy: Eviction strategy
        """
        self.cache_dir = Path(cache_dir)
        self.default_ttl_sec = default_ttl_hours * 3600
        
        # Initialize tiers
        self._memory = MemoryCache[bytes](max_size=memory_size, strategy=strategy)
        self._disk = DiskCache(cache_dir, max_size_mb=disk_size_mb, strategy=strategy)
        
        # Offline mode flag
        self._offline_mode = False
        
        logger.info(
            f"CacheManager initialized: memory={memory_size} items, "
            f"disk={disk_size_mb}MB, ttl={default_ttl_hours}h"
        )
    
    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------
    
    def get(self, key: str) -> Optional[bytes]:
        """
        Get item from cache, checking L1 then L2.
        
        Args:
            key: Cache key
            
        Returns:
            Cached data or None if not found
        """
        # Check L1 (memory)
        data = self._memory.get(key)
        if data is not None:
            return data
        
        # Check L2 (disk)
        data = self._disk.get(key)
        if data is not None:
            # Promote to L1
            entry = self._disk._index.get(key)
            if entry:
                self._memory.put(
                    key, data, 
                    cache_type=entry.cache_type,
                    ttl_sec=entry.ttl_sec,
                    size_bytes=entry.size_bytes,
                )
            return data
        
        return None
    
    def get_path(self, key: str) -> Optional[Path]:
        """
        Get file path for cached item (disk only).
        
        Useful when you need to pass a path to another tool
        rather than loading data into memory.
        """
        return self._disk.get_path(key)
    
    def put(
        self,
        key: str,
        data: bytes,
        cache_type: CacheType = CacheType.GENERIC,
        ttl_sec: Optional[float] = None,
        memory_only: bool = False,
        disk_only: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        Put item in cache.
        
        Args:
            key: Cache key
            data: Data to cache
            cache_type: Type of data (affects storage location)
            ttl_sec: Time-to-live (uses default if None)
            memory_only: Only store in L1
            disk_only: Only store in L2
            metadata: Additional metadata
            
        Returns:
            Path to disk file (if stored on disk)
        """
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        path = None
        
        # Store in L2 (disk) unless memory_only
        if not memory_only:
            path = self._disk.put(key, data, cache_type, ttl, metadata)
        
        # Store in L1 (memory) unless disk_only
        if not disk_only:
            self._memory.put(key, data, cache_type, ttl, len(data))
        
        return path
    
    def put_file(
        self,
        key: str,
        source_path: Path,
        cache_type: CacheType = CacheType.GENERIC,
        ttl_sec: Optional[float] = None,
        copy: bool = True,
    ) -> Path:
        """
        Put a file in cache.
        
        Args:
            key: Cache key
            source_path: Source file to cache
            cache_type: Type of file
            ttl_sec: Time-to-live
            copy: Copy (True) or move (False) the file
            
        Returns:
            Path to cached file
        """
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        return self._disk.put_file(key, source_path, cache_type, ttl, copy)
    
    def delete(self, key: str) -> bool:
        """Delete item from both tiers."""
        memory_deleted = self._memory.delete(key)
        disk_deleted = self._disk.delete(key)
        return memory_deleted or disk_deleted
    
    def contains(self, key: str) -> bool:
        """Check if key exists in any tier."""
        return self._memory.contains(key) or self._disk.contains(key)
    
    def clear(self) -> None:
        """Clear all caches."""
        self._memory.clear()
        self._disk.clear()
        logger.info("All caches cleared")
    
    # -------------------------------------------------------------------------
    # Typed Convenience Methods
    # -------------------------------------------------------------------------
    
    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached JSON data."""
        data = self.get(key)
        if data is None:
            return None
        try:
            return json.loads(data.decode())
        except Exception:
            return None
    
    def put_json(
        self,
        key: str,
        data: Dict[str, Any],
        ttl_sec: Optional[float] = None,
    ) -> Optional[Path]:
        """Put JSON data in cache."""
        return self.put(
            key,
            json.dumps(data, indent=2).encode(),
            cache_type=CacheType.METADATA,
            ttl_sec=ttl_sec,
        )
    
    def get_pickle(self, key: str) -> Optional[Any]:
        """Get pickled Python object."""
        data = self.get(key)
        if data is None:
            return None
        try:
            return pickle.loads(data)
        except Exception:
            return None
    
    def put_pickle(
        self,
        key: str,
        obj: Any,
        ttl_sec: Optional[float] = None,
    ) -> Optional[Path]:
        """Put Python object in cache (pickled)."""
        return self.put(
            key,
            pickle.dumps(obj),
            cache_type=CacheType.GENERIC,
            ttl_sec=ttl_sec,
        )
    
    # -------------------------------------------------------------------------
    # Offline Mode
    # -------------------------------------------------------------------------
    
    def enable_offline_mode(self) -> None:
        """Enable offline mode (rely only on cache)."""
        self._offline_mode = True
        logger.info("Cache offline mode ENABLED")
    
    def disable_offline_mode(self) -> None:
        """Disable offline mode."""
        self._offline_mode = False
        logger.info("Cache offline mode DISABLED")
    
    @property
    def is_offline(self) -> bool:
        """Check if running in offline mode."""
        return self._offline_mode
    
    # -------------------------------------------------------------------------
    # Cache Warming
    # -------------------------------------------------------------------------
    
    def warm(
        self,
        keys: List[str],
        fetch_func: Callable[[str], Optional[bytes]],
        cache_type: CacheType = CacheType.GENERIC,
    ) -> int:
        """
        Warm cache by pre-fetching items.
        
        Args:
            keys: Keys to warm
            fetch_func: Function to fetch data for a key
            cache_type: Type of data being cached
            
        Returns:
            Number of items successfully warmed
        """
        warmed = 0
        for key in keys:
            if not self.contains(key):
                try:
                    data = fetch_func(key)
                    if data:
                        self.put(key, data, cache_type)
                        warmed += 1
                except Exception as e:
                    logger.warning(f"Failed to warm cache for {key}: {e}")
        
        logger.info(f"Cache warmed: {warmed}/{len(keys)} items")
        return warmed
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    def get_combined_stats(self) -> Dict[str, Any]:
        """Get combined statistics from all tiers."""
        memory_stats = self._memory.get_stats()
        disk_stats = self._disk.get_stats()
        
        return {
            "memory": memory_stats.to_dict(),
            "disk": disk_stats.to_dict(),
            "combined": {
                "total_hits": memory_stats.hits + disk_stats.hits,
                "total_misses": memory_stats.misses + disk_stats.misses,
                "combined_hit_rate": f"{(memory_stats.hits + disk_stats.hits) / max(1, memory_stats.hits + memory_stats.misses + disk_stats.misses):.2%}",
                "total_evictions": memory_stats.evictions + disk_stats.evictions,
                "total_entries": memory_stats.entry_count + disk_stats.entry_count,
                "total_size_mb": f"{disk_stats.size_mb:.2f}",
            },
            "offline_mode": self._offline_mode,
        }
    
    # -------------------------------------------------------------------------
    # Maintenance
    # -------------------------------------------------------------------------
    
    def cleanup_expired(self) -> int:
        """Remove expired entries from disk cache."""
        return self._disk.cleanup_expired()
    
    def list_keys(self, cache_type: Optional[CacheType] = None) -> List[str]:
        """List all cached keys."""
        return self._disk.list_keys(cache_type)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def get_cache_manager(
    cache_dir: Optional[Path] = None,
    memory_size: int = DEFAULT_MEMORY_CACHE_SIZE,
    disk_size_mb: float = DEFAULT_DISK_CACHE_SIZE_MB,
) -> CacheManager:
    """
    Factory function to create CacheManager.
    
    Args:
        cache_dir: Cache directory (default: ~/.continuum/cache)
        memory_size: Memory cache size
        disk_size_mb: Disk cache size in MB
        
    Returns:
        Configured CacheManager
    """
    if cache_dir is None:
        cache_dir = Path.home() / ".continuum" / "cache"
    
    return CacheManager(
        cache_dir=cache_dir,
        memory_size=memory_size,
        disk_size_mb=disk_size_mb,
    )


def create_project_cache(
    project_id: str,
    base_path: Optional[Path] = None,
) -> CacheManager:
    """
    Create a cache manager for a specific project.
    
    Args:
        project_id: Project identifier
        base_path: Base cache path
        
    Returns:
        CacheManager scoped to the project
    """
    base = base_path or Path.home() / ".continuum" / "cache"
    project_cache_dir = base / project_id
    
    return CacheManager(
        cache_dir=project_cache_dir,
        memory_size=50,  # Smaller per-project cache
        disk_size_mb=512,
    )


# =============================================================================
# DECORATORS
# =============================================================================

def cached(
    cache: CacheManager,
    key_func: Callable[..., str],
    cache_type: CacheType = CacheType.GENERIC,
    ttl_sec: Optional[float] = None,
):
    """
    Decorator for caching function results.
    
    Usage:
        cache = CacheManager(...)
        
        @cached(cache, key_func=lambda x: f"process:{x}")
        def expensive_process(input_data: str) -> bytes:
            # ... expensive computation ...
            return result
    """
    def decorator(func: Callable[..., bytes]):
        def wrapper(*args, **kwargs) -> bytes:
            key = key_func(*args, **kwargs)
            
            # Check cache
            result = cache.get(key)
            if result is not None:
                return result
            
            # Compute and cache
            result = func(*args, **kwargs)
            if result is not None:
                cache.put(key, result, cache_type, ttl_sec)
            
            return result
        return wrapper
    return decorator