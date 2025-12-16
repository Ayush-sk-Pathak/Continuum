"""
Continuum Engine - Visual RAG (Retrieval-Augmented Generation)

Provides semantic search over visual assets using CLIP embeddings and vector databases.
This is the "Visual Memory" that enables:
- "Find faces similar to this reference"
- "Find locations with this mood/style"
- "Check if this generated frame matches the reference"

Architecture Position:
    ConsistencyDict → says WHAT entities look like (paths, descriptions)
    VisualRAG → enables FINDING similar assets and VERIFYING consistency

Design Principles:
    1. Backend-agnostic: Pinecone, Chroma, Qdrant, or local numpy
    2. Graceful degradation: Cloud → Local fallback (30s timeout)
    3. Lazy embedding: Don't compute CLIP until needed
    4. Batch-friendly: Support bulk operations for efficiency
    5. Cache-aware: Don't re-embed unchanged images

Integration Points:
    - ConsistencyDict: Get face_refs paths for embedding
    - IdentityChecker: Verify face similarity against stored embeddings
    - BridgeEngine: Find similar compositions for reference
    - Audit: Scene consistency checks (first vs last frame similarity)

Optional Dependencies:
    - clip (openai-clip): For CLIP embeddings (pip install git+https://github.com/openai/CLIP.git)
    - pinecone-client: For Pinecone vector DB (pip install pinecone-client)
    - torch: For CLIP model inference (pip install torch)
    - PIL/Pillow: For image loading (pip install Pillow)
"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# OPTIONAL DEPENDENCY HANDLING
# =============================================================================

# These imports are OPTIONAL. Warnings in your IDE are expected if not installed.
# The system will fall back to mock/local implementations automatically.
#
# To install:
#   pip install Pillow                                    # Image loading
#   pip install torch torchvision                         # PyTorch (for CLIP)
#   pip install git+https://github.com/openai/CLIP.git   # CLIP embeddings
#   pip install pinecone-client                           # Cloud vector DB

# CLIP (OpenAI) - for embeddings
CLIP_AVAILABLE = False
try:
    import clip as clip_module
    import torch
    CLIP_AVAILABLE = True
    logger.debug("CLIP module available")
except ImportError:
    clip_module = None
    torch = None
    logger.debug("CLIP not installed - will use mock embeddings")

# Pinecone - for cloud vector DB
PINECONE_AVAILABLE = False
try:
    import pinecone as pinecone_module
    PINECONE_AVAILABLE = True
    logger.debug("Pinecone module available")
except ImportError:
    pinecone_module = None
    logger.debug("Pinecone not installed - will use local vector DB")

# PIL - for image loading
PIL_AVAILABLE = False
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PILImage = None
    logger.debug("PIL not installed - image loading will fail")


# =============================================================================
# CONSTANTS
# =============================================================================

# CLIP embedding dimension (ViT-B/32 = 512, ViT-L/14 = 768)
DEFAULT_EMBEDDING_DIM = 512

# Similarity thresholds from ARCHITECTURE.md
IDENTITY_SIMILARITY_THRESHOLD = 0.70  # ArcFace face match
SCENE_SIMILARITY_THRESHOLD = 0.85     # Scene consistency check

# Fallback timeout (switch to local if cloud unavailable)
CLOUD_TIMEOUT_SEC = 30.0

# Batch sizes
EMBED_BATCH_SIZE = 32
SEARCH_BATCH_SIZE = 100


# =============================================================================
# ENUMS
# =============================================================================

class EmbeddingType(str, Enum):
    """Types of embeddings stored in the vector DB."""
    FACE = "face"                  # Face crops for identity
    SCENE = "scene"                # Full frame for composition
    OBJECT = "object"              # Object crops for prop tracking
    STYLE = "style"                # Style/mood embeddings
    LOCATION = "location"          # Location reference images


class VectorBackend(str, Enum):
    """Available vector database backends."""
    PINECONE = "pinecone"
    CHROMA = "chroma"
    QDRANT = "qdrant"
    LOCAL = "local"                # Numpy-based local fallback


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class EmbeddingRecord:
    """
    A single embedding record in the vector database.
    
    Attributes:
        embedding_id: Unique identifier
        entity_id: Related entity (character, location, etc.)
        embedding_type: Type of embedding
        vector: The embedding vector
        metadata: Additional searchable metadata
        source_path: Original image path
        source_hash: Hash of source image (for cache invalidation)
    """
    embedding_id: str
    entity_id: str
    embedding_type: EmbeddingType
    vector: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_path: Optional[str] = None
    source_hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (vector excluded for JSON)."""
        return {
            "embedding_id": self.embedding_id,
            "entity_id": self.entity_id,
            "embedding_type": self.embedding_type.value,
            "metadata": self.metadata,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "created_at": self.created_at,
        }


@dataclass
class SearchResult:
    """
    Result from a similarity search.
    
    Attributes:
        embedding_id: ID of the matched embedding
        entity_id: Related entity ID
        score: Similarity score (0-1, higher is more similar)
        metadata: Metadata from the matched record
    """
    embedding_id: str
    entity_id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding_type: Optional[EmbeddingType] = None
    
    @property
    def is_match(self) -> bool:
        """Check if this is a strong match based on type-specific threshold."""
        if self.embedding_type == EmbeddingType.FACE:
            return self.score >= IDENTITY_SIMILARITY_THRESHOLD
        elif self.embedding_type == EmbeddingType.SCENE:
            return self.score >= SCENE_SIMILARITY_THRESHOLD
        return self.score >= 0.7  # Default threshold


@dataclass
class SimilarityCheck:
    """
    Result of a similarity verification.
    
    Used for identity checks and scene consistency.
    """
    query_id: str
    reference_id: str
    similarity: float
    passed: bool
    threshold: float
    check_type: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# EMBEDDING PROVIDER (CLIP)
# =============================================================================

class EmbeddingProvider(ABC):
    """Abstract base for embedding generation."""
    
    @abstractmethod
    def embed_image(self, image_path: Path) -> np.ndarray:
        """Generate embedding for a single image."""
        pass
    
    @abstractmethod
    def embed_images(self, image_paths: List[Path]) -> List[np.ndarray]:
        """Generate embeddings for multiple images (batched)."""
        pass
    
    @abstractmethod
    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding for text (for text-to-image search)."""
        pass
    
    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """Dimension of embeddings produced."""
        pass


class CLIPEmbeddingProvider(EmbeddingProvider):
    """
    CLIP-based embedding provider.
    
    Uses OpenAI's CLIP model for image and text embeddings.
    Falls back to mock embeddings if CLIP is not installed.
    """
    
    def __init__(
        self,
        model_name: str = "ViT-B/32",
        device: str = "cpu",
        use_api: bool = False,
    ):
        """
        Initialize CLIP embedding provider.
        
        Args:
            model_name: CLIP model variant
            device: Device for inference (cpu, cuda, mps)
            use_api: Use API instead of local model
        """
        self.model_name = model_name
        self.device = device
        self.use_api = use_api
        self._model = None
        self._preprocess = None
        self._dim = DEFAULT_EMBEDDING_DIM
        self._initialized = False
        
        # Check if CLIP is available
        if not CLIP_AVAILABLE:
            logger.warning(
                "CLIP not installed. Install with: "
                "pip install git+https://github.com/openai/CLIP.git torch"
            )
        
        logger.info(f"CLIPEmbeddingProvider initialized: model={model_name}, device={device}")
    
    def _ensure_model(self) -> None:
        """Lazy load the CLIP model."""
        if self._initialized:
            return
        
        if not CLIP_AVAILABLE:
            logger.warning("CLIP not available, using mock embeddings")
            self._model = "mock"
            self._initialized = True
            return
        
        try:
            self._model, self._preprocess = clip_module.load(self.model_name, device=self.device)
            self._model.eval()
            
            # Get embedding dimension from model
            with torch.no_grad():
                dummy = torch.randn(1, 3, 224, 224).to(self.device)
                dummy_embed = self._model.encode_image(dummy)
                self._dim = dummy_embed.shape[-1]
            
            self._initialized = True
            logger.info(f"CLIP model loaded: {self.model_name}, dim={self._dim}")
            
        except Exception as e:
            logger.warning(f"Failed to load CLIP model: {e}. Using mock embeddings.")
            self._model = "mock"
            self._initialized = True
    
    def embed_image(self, image_path: Path) -> np.ndarray:
        """Generate CLIP embedding for an image."""
        self._ensure_model()
        
        if self._model == "mock":
            return self._mock_embedding(str(image_path))
        
        if not PIL_AVAILABLE:
            logger.warning("PIL not available, using mock embedding")
            return self._mock_embedding(str(image_path))
        
        try:
            image = PILImage.open(image_path).convert("RGB")
            image_input = self._preprocess(image).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                embedding = self._model.encode_image(image_input)
                embedding = embedding / embedding.norm(dim=-1, keepdim=True)
                return embedding.cpu().numpy().flatten()
                
        except Exception as e:
            logger.error(f"Failed to embed image {image_path}: {e}")
            return self._mock_embedding(str(image_path))
    
    def embed_images(self, image_paths: List[Path]) -> List[np.ndarray]:
        """Batch embed multiple images."""
        self._ensure_model()
        
        if self._model == "mock" or not PIL_AVAILABLE:
            return [self._mock_embedding(str(p)) for p in image_paths]
        
        try:
            embeddings = []
            
            # Process in batches
            for i in range(0, len(image_paths), EMBED_BATCH_SIZE):
                batch_paths = image_paths[i:i + EMBED_BATCH_SIZE]
                
                images = []
                for path in batch_paths:
                    try:
                        img = PILImage.open(path).convert("RGB")
                        images.append(self._preprocess(img))
                    except Exception as e:
                        logger.warning(f"Failed to load {path}: {e}")
                        images.append(torch.zeros(3, 224, 224))
                
                if images:
                    batch = torch.stack(images).to(self.device)
                    
                    with torch.no_grad():
                        batch_embeddings = self._model.encode_image(batch)
                        batch_embeddings = batch_embeddings / batch_embeddings.norm(dim=-1, keepdim=True)
                        
                    for emb in batch_embeddings.cpu().numpy():
                        embeddings.append(emb.flatten())
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return [self._mock_embedding(str(p)) for p in image_paths]
    
    def embed_text(self, text: str) -> np.ndarray:
        """Generate CLIP embedding for text."""
        self._ensure_model()
        
        if self._model == "mock":
            return self._mock_embedding(text)
        
        if not CLIP_AVAILABLE:
            return self._mock_embedding(text)
        
        try:
            text_input = clip_module.tokenize([text]).to(self.device)
            
            with torch.no_grad():
                embedding = self._model.encode_text(text_input)
                embedding = embedding / embedding.norm(dim=-1, keepdim=True)
                return embedding.cpu().numpy().flatten()
                
        except Exception as e:
            logger.error(f"Failed to embed text: {e}")
            return self._mock_embedding(text)
    
    def _mock_embedding(self, seed: str) -> np.ndarray:
        """Generate deterministic mock embedding for testing."""
        hash_val = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        np.random.seed(hash_val)
        vec = np.random.randn(self._dim).astype(np.float32)
        return vec / np.linalg.norm(vec)
    
    @property
    def embedding_dim(self) -> int:
        return self._dim


# =============================================================================
# VECTOR DATABASE BACKENDS
# =============================================================================

class VectorDBBackend(ABC):
    """Abstract base for vector database backends."""
    
    @abstractmethod
    def upsert(self, records: List[EmbeddingRecord]) -> int:
        """Insert or update embedding records. Returns count."""
        pass
    
    @abstractmethod
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_type: Optional[EmbeddingType] = None,
        filter_entity: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search for similar vectors."""
        pass
    
    @abstractmethod
    def get(self, embedding_id: str) -> Optional[EmbeddingRecord]:
        """Get a specific embedding by ID."""
        pass
    
    @abstractmethod
    def delete(self, embedding_ids: List[str]) -> int:
        """Delete embeddings by ID. Returns count deleted."""
        pass
    
    @abstractmethod
    def count(self) -> int:
        """Count total embeddings."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all embeddings."""
        pass


class LocalVectorDB(VectorDBBackend):
    """
    Local numpy-based vector database.
    
    This is the fallback when cloud vector DBs are unavailable.
    Suitable for small-medium datasets (<100k vectors).
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    ):
        """
        Initialize local vector DB.
        
        Args:
            storage_path: Path to persist the database (None = in-memory only)
            embedding_dim: Expected embedding dimension
        """
        self.storage_path = storage_path
        self.embedding_dim = embedding_dim
        
        # In-memory storage
        self._vectors: Dict[str, np.ndarray] = {}
        self._metadata: Dict[str, EmbeddingRecord] = {}
        
        # Load from disk if exists
        if storage_path and storage_path.exists():
            self._load()
        
        logger.info(f"LocalVectorDB initialized: {len(self._vectors)} vectors")
    
    def upsert(self, records: List[EmbeddingRecord]) -> int:
        """Insert or update records."""
        for record in records:
            self._vectors[record.embedding_id] = record.vector
            self._metadata[record.embedding_id] = record
        
        self._save()
        return len(records)
    
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_type: Optional[EmbeddingType] = None,
        filter_entity: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search for similar vectors using cosine similarity."""
        if not self._vectors:
            return []
        
        # Normalize query
        query_norm = query_vector / np.linalg.norm(query_vector)
        
        # Calculate similarities
        results = []
        for emb_id, vector in self._vectors.items():
            record = self._metadata.get(emb_id)
            if not record:
                continue
            
            # Apply filters
            if filter_type and record.embedding_type != filter_type:
                continue
            if filter_entity and record.entity_id != filter_entity:
                continue
            
            # Cosine similarity
            vec_norm = vector / np.linalg.norm(vector)
            similarity = float(np.dot(query_norm, vec_norm))
            
            results.append(SearchResult(
                embedding_id=emb_id,
                entity_id=record.entity_id,
                score=similarity,
                metadata=record.metadata,
                embedding_type=record.embedding_type,
            ))
        
        # Sort by similarity and return top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
    
    def get(self, embedding_id: str) -> Optional[EmbeddingRecord]:
        """Get embedding by ID."""
        return self._metadata.get(embedding_id)
    
    def delete(self, embedding_ids: List[str]) -> int:
        """Delete embeddings."""
        count = 0
        for emb_id in embedding_ids:
            if emb_id in self._vectors:
                del self._vectors[emb_id]
                del self._metadata[emb_id]
                count += 1
        
        self._save()
        return count
    
    def count(self) -> int:
        """Count total embeddings."""
        return len(self._vectors)
    
    def clear(self) -> None:
        """Clear all embeddings."""
        self._vectors.clear()
        self._metadata.clear()
        self._save()
    
    def _save(self) -> None:
        """Save to disk."""
        if not self.storage_path:
            return
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save vectors as npz
        vectors_path = self.storage_path.with_suffix(".npz")
        if self._vectors:
            np.savez_compressed(
                vectors_path,
                ids=list(self._vectors.keys()),
                vectors=np.array(list(self._vectors.values())),
            )
        
        # Save metadata as JSON
        meta_path = self.storage_path.with_suffix(".json")
        meta_dict = {
            emb_id: record.to_dict() 
            for emb_id, record in self._metadata.items()
        }
        with open(meta_path, "w") as f:
            json.dump(meta_dict, f, indent=2)
    
    def _load(self) -> None:
        """Load from disk."""
        vectors_path = self.storage_path.with_suffix(".npz")
        meta_path = self.storage_path.with_suffix(".json")
        
        if vectors_path.exists():
            data = np.load(vectors_path, allow_pickle=True)
            ids = data["ids"]
            vectors = data["vectors"]
            for i, emb_id in enumerate(ids):
                self._vectors[str(emb_id)] = vectors[i]
        
        if meta_path.exists():
            with open(meta_path) as f:
                meta_dict = json.load(f)
            
            for emb_id, data in meta_dict.items():
                record = EmbeddingRecord(
                    embedding_id=data["embedding_id"],
                    entity_id=data["entity_id"],
                    embedding_type=EmbeddingType(data["embedding_type"]),
                    vector=self._vectors.get(emb_id, np.zeros(self.embedding_dim)),
                    metadata=data.get("metadata", {}),
                    source_path=data.get("source_path"),
                    source_hash=data.get("source_hash", ""),
                    created_at=data.get("created_at", ""),
                )
                self._metadata[emb_id] = record


class PineconeVectorDB(VectorDBBackend):
    """
    Pinecone cloud vector database backend.
    
    Primary production backend for Visual RAG.
    Requires pinecone-client: pip install pinecone-client
    """
    
    def __init__(
        self,
        api_key: str,
        environment: str,
        index_name: str,
        namespace: str = "default",
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    ):
        """
        Initialize Pinecone backend.
        
        Args:
            api_key: Pinecone API key
            environment: Pinecone environment (e.g., "us-west1-gcp")
            index_name: Name of the index
            namespace: Namespace within index (for project isolation)
            embedding_dim: Expected embedding dimension
        """
        self.index_name = index_name
        self.namespace = namespace
        self.embedding_dim = embedding_dim
        self._index = None
        
        if not PINECONE_AVAILABLE:
            raise ImportError(
                "Pinecone not installed. Install with: pip install pinecone-client"
            )
        
        try:
            pinecone_module.init(api_key=api_key, environment=environment)
            
            # Create index if doesn't exist
            if index_name not in pinecone_module.list_indexes():
                pinecone_module.create_index(
                    index_name,
                    dimension=embedding_dim,
                    metric="cosine",
                )
            
            self._index = pinecone_module.Index(index_name)
            logger.info(f"Pinecone connected: {index_name}")
            
        except Exception as e:
            logger.error(f"Pinecone initialization failed: {e}")
            raise
    
    def upsert(self, records: List[EmbeddingRecord]) -> int:
        """Upsert records to Pinecone."""
        vectors = []
        for record in records:
            vectors.append({
                "id": record.embedding_id,
                "values": record.vector.tolist(),
                "metadata": {
                    "entity_id": record.entity_id,
                    "embedding_type": record.embedding_type.value,
                    "source_path": record.source_path or "",
                    "source_hash": record.source_hash,
                    **record.metadata,
                },
            })
        
        # Upsert in batches
        batch_size = 100
        total = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self._index.upsert(vectors=batch, namespace=self.namespace)
            total += len(batch)
        
        return total
    
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_type: Optional[EmbeddingType] = None,
        filter_entity: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search Pinecone index."""
        # Build filter
        filter_dict = {}
        if filter_type:
            filter_dict["embedding_type"] = filter_type.value
        if filter_entity:
            filter_dict["entity_id"] = filter_entity
        
        results = self._index.query(
            vector=query_vector.tolist(),
            top_k=top_k,
            namespace=self.namespace,
            filter=filter_dict if filter_dict else None,
            include_metadata=True,
        )
        
        return [
            SearchResult(
                embedding_id=match["id"],
                entity_id=match["metadata"].get("entity_id", ""),
                score=match["score"],
                metadata=match["metadata"],
                embedding_type=EmbeddingType(match["metadata"].get("embedding_type", "scene")),
            )
            for match in results["matches"]
        ]
    
    def get(self, embedding_id: str) -> Optional[EmbeddingRecord]:
        """Fetch specific embedding."""
        results = self._index.fetch(ids=[embedding_id], namespace=self.namespace)
        
        if embedding_id not in results["vectors"]:
            return None
        
        vec_data = results["vectors"][embedding_id]
        return EmbeddingRecord(
            embedding_id=embedding_id,
            entity_id=vec_data["metadata"].get("entity_id", ""),
            embedding_type=EmbeddingType(vec_data["metadata"].get("embedding_type", "scene")),
            vector=np.array(vec_data["values"]),
            metadata=vec_data["metadata"],
            source_path=vec_data["metadata"].get("source_path"),
            source_hash=vec_data["metadata"].get("source_hash", ""),
        )
    
    def delete(self, embedding_ids: List[str]) -> int:
        """Delete embeddings from Pinecone."""
        self._index.delete(ids=embedding_ids, namespace=self.namespace)
        return len(embedding_ids)
    
    def count(self) -> int:
        """Get total vector count."""
        stats = self._index.describe_index_stats()
        return stats["namespaces"].get(self.namespace, {}).get("vector_count", 0)
    
    def clear(self) -> None:
        """Clear the namespace."""
        self._index.delete(delete_all=True, namespace=self.namespace)


# =============================================================================
# VISUAL RAG MAIN CLASS
# =============================================================================

class VisualRAG:
    """
    Visual Retrieval-Augmented Generation system.
    
    High-level interface for:
    - Storing and indexing visual assets with CLIP embeddings
    - Semantic search over characters, locations, props
    - Identity verification (face similarity checks)
    - Scene consistency checks (first vs last frame)
    
    Usage:
        rag = VisualRAG.create_local(storage_path)
        
        # Index character face references
        rag.index_entity(
            entity_id="alice",
            image_paths=[Path("alice_ref_1.png"), Path("alice_ref_2.png")],
            embedding_type=EmbeddingType.FACE,
        )
        
        # Find similar faces
        results = rag.search_similar(
            query_image=Path("generated_frame.png"),
            embedding_type=EmbeddingType.FACE,
            top_k=5,
        )
        
        # Check identity consistency
        check = rag.verify_identity(
            query_image=Path("frame.png"),
            entity_id="alice",
        )
        print(f"Identity match: {check.passed} (score={check.similarity:.2f})")
    """
    
    def __init__(
        self,
        backend: VectorDBBackend,
        embedding_provider: EmbeddingProvider,
    ):
        """
        Initialize Visual RAG.
        
        Args:
            backend: Vector database backend
            embedding_provider: CLIP or other embedding provider
        """
        self.backend = backend
        self.embedder = embedding_provider
        
        # Cache for avoiding re-embedding unchanged images
        self._embedding_cache: Dict[str, Tuple[str, np.ndarray]] = {}
        
        logger.info(
            f"VisualRAG initialized: backend={type(backend).__name__}, "
            f"embedder={type(embedding_provider).__name__}"
        )
    
    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------
    
    @classmethod
    def create_local(
        cls,
        storage_path: Path,
        clip_model: str = "ViT-B/32",
        device: str = "cpu",
    ) -> "VisualRAG":
        """Create Visual RAG with local storage (development/fallback)."""
        backend = LocalVectorDB(
            storage_path=storage_path,
            embedding_dim=DEFAULT_EMBEDDING_DIM,
        )
        embedder = CLIPEmbeddingProvider(
            model_name=clip_model,
            device=device,
        )
        return cls(backend, embedder)
    
    @classmethod
    def create_pinecone(
        cls,
        api_key: str,
        environment: str,
        index_name: str,
        namespace: str = "default",
        clip_model: str = "ViT-B/32",
        device: str = "cpu",
    ) -> "VisualRAG":
        """Create Visual RAG with Pinecone backend (production)."""
        backend = PineconeVectorDB(
            api_key=api_key,
            environment=environment,
            index_name=index_name,
            namespace=namespace,
        )
        embedder = CLIPEmbeddingProvider(
            model_name=clip_model,
            device=device,
        )
        return cls(backend, embedder)
    
    @classmethod
    def create_with_fallback(
        cls,
        pinecone_config: Optional[Dict[str, str]] = None,
        local_path: Path = Path("./visual_rag_cache"),
        clip_model: str = "ViT-B/32",
        device: str = "cpu",
    ) -> "VisualRAG":
        """
        Create Visual RAG with automatic fallback.
        
        Tries Pinecone first, falls back to local on failure.
        """
        embedder = CLIPEmbeddingProvider(
            model_name=clip_model,
            device=device,
        )
        
        if pinecone_config:
            try:
                backend = PineconeVectorDB(**pinecone_config)
                logger.info("Using Pinecone backend")
                return cls(backend, embedder)
            except Exception as e:
                logger.warning(f"Pinecone unavailable ({e}), falling back to local")
        
        backend = LocalVectorDB(storage_path=local_path)
        logger.info("Using local backend")
        return cls(backend, embedder)
    
    # -------------------------------------------------------------------------
    # Indexing Operations
    # -------------------------------------------------------------------------
    
    def index_entity(
        self,
        entity_id: str,
        image_paths: List[Path],
        embedding_type: EmbeddingType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Index images for an entity.
        
        Args:
            entity_id: Entity identifier (e.g., character ID)
            image_paths: List of reference images
            embedding_type: Type of embedding (face, scene, etc.)
            metadata: Additional metadata to store
            
        Returns:
            Number of embeddings created
        """
        records = []
        
        for i, path in enumerate(image_paths):
            if not path.exists():
                logger.warning(f"Image not found: {path}")
                continue
            
            # Check cache
            file_hash = self._hash_file(path)
            cache_key = f"{entity_id}:{path.name}"
            
            if cache_key in self._embedding_cache:
                cached_hash, cached_vec = self._embedding_cache[cache_key]
                if cached_hash == file_hash:
                    vector = cached_vec
                else:
                    vector = self.embedder.embed_image(path)
                    self._embedding_cache[cache_key] = (file_hash, vector)
            else:
                vector = self.embedder.embed_image(path)
                self._embedding_cache[cache_key] = (file_hash, vector)
            
            record = EmbeddingRecord(
                embedding_id=f"{entity_id}:{embedding_type.value}:{i}",
                entity_id=entity_id,
                embedding_type=embedding_type,
                vector=vector,
                metadata=metadata or {},
                source_path=str(path),
                source_hash=file_hash,
            )
            records.append(record)
        
        if records:
            return self.backend.upsert(records)
        return 0
    
    def index_frame(
        self,
        frame_id: str,
        image_path: Path,
        shot_id: str,
        embedding_type: EmbeddingType = EmbeddingType.SCENE,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Index a single frame (for scene consistency checks).
        
        Args:
            frame_id: Unique frame identifier
            image_path: Path to frame image
            shot_id: Parent shot ID
            embedding_type: Type of embedding
            metadata: Additional metadata
            
        Returns:
            True if indexed successfully
        """
        if not image_path.exists():
            logger.warning(f"Frame not found: {image_path}")
            return False
        
        vector = self.embedder.embed_image(image_path)
        file_hash = self._hash_file(image_path)
        
        record = EmbeddingRecord(
            embedding_id=frame_id,
            entity_id=shot_id,
            embedding_type=embedding_type,
            vector=vector,
            metadata={"shot_id": shot_id, **(metadata or {})},
            source_path=str(image_path),
            source_hash=file_hash,
        )
        
        return self.backend.upsert([record]) > 0
    
    def batch_index(
        self,
        items: List[Tuple[str, str, Path, EmbeddingType]],
    ) -> int:
        """
        Batch index multiple items efficiently.
        
        Args:
            items: List of (embedding_id, entity_id, path, type) tuples
            
        Returns:
            Number of items indexed
        """
        # Extract paths for batch embedding
        paths = [item[2] for item in items if item[2].exists()]
        
        if not paths:
            return 0
        
        # Batch embed
        vectors = self.embedder.embed_images(paths)
        
        # Create records
        records = []
        for (emb_id, entity_id, path, emb_type), vector in zip(items, vectors):
            if not path.exists():
                continue
            
            records.append(EmbeddingRecord(
                embedding_id=emb_id,
                entity_id=entity_id,
                embedding_type=emb_type,
                vector=vector,
                source_path=str(path),
                source_hash=self._hash_file(path),
            ))
        
        return self.backend.upsert(records)
    
    # -------------------------------------------------------------------------
    # Search Operations
    # -------------------------------------------------------------------------
    
    def search_similar(
        self,
        query_image: Path,
        embedding_type: Optional[EmbeddingType] = None,
        entity_filter: Optional[str] = None,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Find similar images.
        
        Args:
            query_image: Image to search for
            embedding_type: Filter by embedding type
            entity_filter: Filter by entity ID
            top_k: Number of results
            
        Returns:
            List of similar results, sorted by similarity
        """
        if not query_image.exists():
            logger.warning(f"Query image not found: {query_image}")
            return []
        
        query_vector = self.embedder.embed_image(query_image)
        
        return self.backend.search(
            query_vector=query_vector,
            top_k=top_k,
            filter_type=embedding_type,
            filter_entity=entity_filter,
        )
    
    def search_by_text(
        self,
        text: str,
        embedding_type: Optional[EmbeddingType] = None,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Search images by text description (CLIP text-to-image).
        
        Args:
            text: Text query (e.g., "woman with red hair")
            embedding_type: Filter by type
            top_k: Number of results
            
        Returns:
            List of matching results
        """
        query_vector = self.embedder.embed_text(text)
        
        return self.backend.search(
            query_vector=query_vector,
            top_k=top_k,
            filter_type=embedding_type,
        )
    
    # -------------------------------------------------------------------------
    # Verification Operations
    # -------------------------------------------------------------------------
    
    def verify_identity(
        self,
        query_image: Path,
        entity_id: str,
        threshold: Optional[float] = None,
    ) -> SimilarityCheck:
        """
        Verify if an image matches an entity's stored references.
        
        Used for identity checking in the audit pipeline.
        
        Args:
            query_image: Image to verify
            entity_id: Entity to match against
            threshold: Similarity threshold (default: type-specific)
            
        Returns:
            SimilarityCheck with pass/fail and similarity score
        """
        threshold = threshold or IDENTITY_SIMILARITY_THRESHOLD
        
        results = self.search_similar(
            query_image=query_image,
            embedding_type=EmbeddingType.FACE,
            entity_filter=entity_id,
            top_k=5,
        )
        
        if not results:
            return SimilarityCheck(
                query_id=str(query_image),
                reference_id=entity_id,
                similarity=0.0,
                passed=False,
                threshold=threshold,
                check_type="identity",
                details={"error": "No reference embeddings found"},
            )
        
        # Use best match
        best_match = results[0]
        
        return SimilarityCheck(
            query_id=str(query_image),
            reference_id=entity_id,
            similarity=best_match.score,
            passed=best_match.score >= threshold,
            threshold=threshold,
            check_type="identity",
            details={
                "matches_found": len(results),
                "best_match_id": best_match.embedding_id,
            },
        )
    
    def verify_scene_consistency(
        self,
        first_frame: Path,
        last_frame: Path,
        shot_id: str,
        threshold: Optional[float] = None,
    ) -> SimilarityCheck:
        """
        Check scene consistency between first and last frame.
        
        Used in audit to detect scene drift within a shot.
        
        Args:
            first_frame: First frame of shot
            last_frame: Last frame of shot
            shot_id: Shot identifier
            threshold: Similarity threshold (default: 0.85)
            
        Returns:
            SimilarityCheck with pass/fail
        """
        threshold = threshold or SCENE_SIMILARITY_THRESHOLD
        
        if not first_frame.exists() or not last_frame.exists():
            return SimilarityCheck(
                query_id=str(first_frame),
                reference_id=str(last_frame),
                similarity=0.0,
                passed=False,
                threshold=threshold,
                check_type="scene_consistency",
                details={"error": "Frame(s) not found"},
            )
        
        # Embed both frames
        first_vec = self.embedder.embed_image(first_frame)
        last_vec = self.embedder.embed_image(last_frame)
        
        # Cosine similarity
        similarity = float(np.dot(
            first_vec / np.linalg.norm(first_vec),
            last_vec / np.linalg.norm(last_vec),
        ))
        
        return SimilarityCheck(
            query_id=str(first_frame),
            reference_id=str(last_frame),
            similarity=similarity,
            passed=similarity >= threshold,
            threshold=threshold,
            check_type="scene_consistency",
            details={"shot_id": shot_id},
        )
    
    # -------------------------------------------------------------------------
    # Management Operations
    # -------------------------------------------------------------------------
    
    def delete_entity(self, entity_id: str) -> int:
        """Delete all embeddings for an entity."""
        # Search for all embeddings with this entity
        # This is a simple approach; production might need more efficient methods
        all_ids = []
        
        for emb_type in EmbeddingType:
            results = self.backend.search(
                query_vector=np.zeros(self.embedder.embedding_dim),
                top_k=1000,
                filter_entity=entity_id,
            )
            all_ids.extend([r.embedding_id for r in results])
        
        if all_ids:
            return self.backend.delete(all_ids)
        return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Visual RAG statistics."""
        return {
            "total_embeddings": self.backend.count(),
            "embedding_dim": self.embedder.embedding_dim,
            "cache_size": len(self._embedding_cache),
            "backend_type": type(self.backend).__name__,
        }
    
    def clear(self) -> None:
        """Clear all embeddings (use with caution!)."""
        self.backend.clear()
        self._embedding_cache.clear()
        logger.warning("Visual RAG cleared")
    
    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    
    def _hash_file(self, path: Path) -> str:
        """Generate hash of file for cache invalidation."""
        return hashlib.md5(path.read_bytes()).hexdigest()[:16]


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def get_visual_rag(
    use_pinecone: bool = False,
    pinecone_api_key: Optional[str] = None,
    pinecone_environment: Optional[str] = None,
    pinecone_index: str = "continuum-visual-rag",
    local_path: Optional[Path] = None,
    device: str = "cpu",
) -> VisualRAG:
    """
    Factory function to create VisualRAG instance.
    
    Args:
        use_pinecone: Use Pinecone backend (requires API key)
        pinecone_api_key: Pinecone API key
        pinecone_environment: Pinecone environment
        pinecone_index: Pinecone index name
        local_path: Path for local storage (default: ./data/visual_rag)
        device: Device for CLIP (cpu, cuda, mps)
        
    Returns:
        Configured VisualRAG instance
    """
    local_path = local_path or Path("./data/visual_rag")
    
    if use_pinecone and pinecone_api_key:
        try:
            return VisualRAG.create_pinecone(
                api_key=pinecone_api_key,
                environment=pinecone_environment or "us-west1-gcp",
                index_name=pinecone_index,
                device=device,
            )
        except Exception as e:
            logger.warning(f"Pinecone failed ({e}), falling back to local")
    
    return VisualRAG.create_local(
        storage_path=local_path,
        device=device,
    )


def create_visual_rag(
    project_id: str,
    base_path: Optional[Path] = None,
) -> VisualRAG:
    """
    Create Visual RAG for a specific project.
    
    Args:
        project_id: Project identifier
        base_path: Base storage path
        
    Returns:
        VisualRAG configured for the project
    """
    base_path = base_path or Path("./data")
    storage_path = base_path / "visual_rag" / project_id
    storage_path.mkdir(parents=True, exist_ok=True)
    
    return VisualRAG.create_local(storage_path=storage_path)