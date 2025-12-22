"""
Continuum Engine - Identity Checker (ArcFace Verification)

Verifies that character identity is preserved across frames and shots.
This is the PROOF that Bridge Engine works â€” without it, we're just hoping.

The Problem:
    Video models drift. Alice in frame 1 might not look like Alice in frame 100.
    Bridge frames are supposed to fix this, but how do we KNOW they worked?

The Solution:
    Extract face embeddings using ArcFace (industry standard for face recognition).
    Compare embeddings between frames using cosine similarity.
    Threshold at 0.70 â€” below that, identity has drifted unacceptably.

Use Cases:
    1. Within-shot check: Compare first vs last frame of a chunk
    2. Cross-shot check: Compare Shot A last frame vs Shot B first frame
    3. Bridge verification: Confirm bridge frame matches source identity

Architecture:
    - BaseIdentityChecker: Abstract interface (pluggable)
    - ArcFaceIdentityChecker: Production implementation using insightface
    - MockIdentityChecker: Testing without GPU/models

Design Principles:
    1. Fail gracefully: No face detected â†’ WARN, not crash
    2. Multi-face aware: Handle scenes with multiple characters
    3. Async-ready: Face extraction can be batched
    4. Audit-compatible: Returns AuditResult-compatible data
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION DEFAULTS
# =============================================================================

DEFAULT_IDENTITY_THRESHOLD = 0.70  # From config.py AuditConfig
DEFAULT_DETECTION_THRESHOLD = 0.5  # Face detection confidence
DEFAULT_MODEL_NAME = "buffalo_l"   # ArcFace model variant


# =============================================================================
# ENUMS
# =============================================================================

class IdentityCheckResult(str, Enum):
    """Result of an identity comparison."""
    MATCH = "match"           # Similarity >= threshold
    MISMATCH = "mismatch"     # Similarity < threshold
    NO_FACE_SOURCE = "no_face_source"      # No face in source frame
    NO_FACE_TARGET = "no_face_target"      # No face in target frame
    NO_FACE_BOTH = "no_face_both"          # No face in either frame
    MULTIPLE_FACES = "multiple_faces"      # Ambiguous (multiple faces, unclear match)
    ERROR = "error"           # Processing error


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class FaceEmbedding:
    """
    Extracted face embedding from a frame.
    
    Attributes:
        embedding: 512-dimensional ArcFace vector (normalized)
        bbox: Bounding box as (x1, y1, x2, y2) in pixels
        confidence: Detection confidence (0.0-1.0)
        landmarks: Facial landmarks if available
        frame_path: Source frame (for debugging)
    """
    embedding: np.ndarray
    bbox: Tuple[int, int, int, int]
    confidence: float
    landmarks: Optional[np.ndarray] = None
    frame_path: Optional[Path] = None
    
    @property
    def center(self) -> Tuple[float, float]:
        """Center point of face bounding box."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @property
    def area(self) -> int:
        """Area of bounding box in pixels."""
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)


@dataclass
class FrameFaces:
    """
    All faces detected in a single frame.
    
    Attributes:
        frame_path: Source frame
        faces: List of detected faces with embeddings
        extraction_time_sec: How long extraction took
    """
    frame_path: Path
    faces: List[FaceEmbedding]
    extraction_time_sec: float = 0.0
    
    @property
    def face_count(self) -> int:
        return len(self.faces)
    
    @property
    def has_faces(self) -> bool:
        return self.face_count > 0
    
    @property
    def primary_face(self) -> Optional[FaceEmbedding]:
        """
        Get the primary (largest) face.
        
        Heuristic: Largest bounding box is likely the main character.
        """
        if not self.faces:
            return None
        return max(self.faces, key=lambda f: f.area)
    
    def get_face_by_position(
        self, 
        region: str = "center"
    ) -> Optional[FaceEmbedding]:
        """
        Get face by position in frame.
        
        Args:
            region: "center", "left", "right"
            
        Returns:
            Face closest to specified region, or None
        """
        if not self.faces:
            return None
        
        if region == "center":
            # Assume frame center is at normalized (0.5, 0.5)
            # Would need frame dimensions for exact calculation
            return self.primary_face
        
        # Sort by x-coordinate of center
        sorted_faces = sorted(self.faces, key=lambda f: f.center[0])
        
        if region == "left":
            return sorted_faces[0]
        elif region == "right":
            return sorted_faces[-1]
        
        return self.primary_face


@dataclass
class IdentityComparison:
    """
    Result of comparing identity between two frames.
    
    This is the core output of the identity checker.
    
    Attributes:
        result: Overall result (MATCH, MISMATCH, etc.)
        similarity: Cosine similarity (-1.0 to 1.0), None if no comparison
        threshold: Threshold used for MATCH/MISMATCH decision
        source_faces: Faces in source frame
        target_faces: Faces in target frame
        matched_pairs: List of (source_idx, target_idx, similarity) for multi-face
        message: Human-readable explanation
    """
    result: IdentityCheckResult
    similarity: Optional[float]
    threshold: float
    source_faces: FrameFaces
    target_faces: FrameFaces
    matched_pairs: List[Tuple[int, int, float]] = field(default_factory=list)
    message: str = ""
    comparison_time_sec: float = 0.0
    
    @property
    def passed(self) -> bool:
        """Did identity check pass?"""
        return self.result == IdentityCheckResult.MATCH
    
    @property
    def needs_human_review(self) -> bool:
        """Should this be flagged for human review?"""
        return self.result in (
            IdentityCheckResult.NO_FACE_SOURCE,
            IdentityCheckResult.NO_FACE_TARGET,
            IdentityCheckResult.NO_FACE_BOTH,
            IdentityCheckResult.MULTIPLE_FACES,
        )
    
    def to_audit_recommendation(self) -> str:
        """Convert to audit system recommendation."""
        if self.passed:
            return "approve"
        elif self.needs_human_review:
            return "manual_review"
        else:
            return "reroll"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "result": self.result.value,
            "similarity": self.similarity,
            "threshold": self.threshold,
            "source_face_count": self.source_faces.face_count,
            "target_face_count": self.target_faces.face_count,
            "matched_pairs": self.matched_pairs,
            "message": self.message,
            "passed": self.passed,
            "recommendation": self.to_audit_recommendation(),
        }


# =============================================================================
# EXCEPTIONS
# =============================================================================

class IdentityCheckError(Exception):
    """Base exception for identity checking errors."""
    pass


class ModelLoadError(IdentityCheckError):
    """Failed to load face recognition model."""
    pass


class ImageLoadError(IdentityCheckError):
    """Failed to load or decode image."""
    pass


class ExtractionError(IdentityCheckError):
    """Failed to extract face embeddings."""
    pass


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BaseIdentityChecker(ABC):
    """
    Abstract base class for identity verification.
    
    Defines the interface that all identity checkers must implement.
    This allows hot-swapping between ArcFace, other models, or mocks.
    """
    
    def __init__(
        self,
        threshold: float = DEFAULT_IDENTITY_THRESHOLD,
        detection_threshold: float = DEFAULT_DETECTION_THRESHOLD,
    ):
        """
        Initialize identity checker.
        
        Args:
            threshold: Similarity threshold for MATCH (default 0.70)
            detection_threshold: Face detection confidence threshold
        """
        self.threshold = threshold
        self.detection_threshold = detection_threshold
    
    @abstractmethod
    async def extract_faces(self, frame_path: Path) -> FrameFaces:
        """
        Extract all face embeddings from a frame.
        
        Args:
            frame_path: Path to image file
            
        Returns:
            FrameFaces with all detected faces and embeddings
            
        Raises:
            ImageLoadError: If image cannot be loaded
            ExtractionError: If extraction fails
        """
        pass
    
    @abstractmethod
    async def compare(
        self,
        source_frame: Path,
        target_frame: Path,
        character_hint: Optional[str] = None,
    ) -> IdentityComparison:
        """
        Compare identity between two frames.
        
        This is the primary method for verification.
        
        Args:
            source_frame: Reference frame (e.g., end of Shot A)
            target_frame: Frame to verify (e.g., start of Shot B)
            character_hint: Optional hint for multi-face disambiguation
            
        Returns:
            IdentityComparison with result and scores
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the identity checker is ready.
        
        Returns:
            True if model is loaded and ready
        """
        pass
    
    def compute_similarity(
        self,
        embedding_a: np.ndarray,
        embedding_b: np.ndarray,
    ) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Args:
            embedding_a: First embedding vector (normalized)
            embedding_b: Second embedding vector (normalized)
            
        Returns:
            Cosine similarity (-1.0 to 1.0)
        """
        # Ensure normalized
        norm_a = np.linalg.norm(embedding_a)
        norm_b = np.linalg.norm(embedding_b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        embedding_a = embedding_a / norm_a
        embedding_b = embedding_b / norm_b
        
        return float(np.dot(embedding_a, embedding_b))
    
    async def compare_batch(
        self,
        frame_pairs: List[Tuple[Path, Path]],
    ) -> List[IdentityComparison]:
        """
        Compare identity across multiple frame pairs.
        
        Useful for checking consistency across an entire shot.
        Default implementation just loops; subclasses can optimize.
        
        Args:
            frame_pairs: List of (source, target) path tuples
            
        Returns:
            List of IdentityComparison results
        """
        results = []
        for source, target in frame_pairs:
            result = await self.compare(source, target)
            results.append(result)
        return results
    
    async def check_shot_consistency(
        self,
        frames: List[Path],
        sample_rate: int = 10,
    ) -> IdentityComparison:
        """
        Check identity consistency across a shot.
        
        Compares first frame to sampled frames throughout.
        
        Args:
            frames: All frames in the shot (in order)
            sample_rate: Check every Nth frame
            
        Returns:
            IdentityComparison (worst result across comparisons)
        """
        if len(frames) < 2:
            return IdentityComparison(
                result=IdentityCheckResult.MATCH,
                similarity=1.0,
                threshold=self.threshold,
                source_faces=FrameFaces(frames[0] if frames else Path(), []),
                target_faces=FrameFaces(frames[0] if frames else Path(), []),
                message="Single frame, no comparison needed"
            )
        
        first_frame = frames[0]
        sampled_frames = frames[sample_rate::sample_rate]
        
        # Always include last frame
        if frames[-1] not in sampled_frames:
            sampled_frames.append(frames[-1])
        
        worst_result = None
        worst_similarity = 1.0
        
        for target_frame in sampled_frames:
            comparison = await self.compare(first_frame, target_frame)
            
            if comparison.similarity is not None:
                if comparison.similarity < worst_similarity:
                    worst_similarity = comparison.similarity
                    worst_result = comparison
            
            # Early exit if we find a failure
            if not comparison.passed and comparison.result == IdentityCheckResult.MISMATCH:
                return comparison
        
        return worst_result or IdentityComparison(
            result=IdentityCheckResult.MATCH,
            similarity=worst_similarity,
            threshold=self.threshold,
            source_faces=FrameFaces(first_frame, []),
            target_faces=FrameFaces(frames[-1], []),
            message=f"Checked {len(sampled_frames)} frames, min similarity: {worst_similarity:.3f}"
        )


# =============================================================================
# ARCFACE IMPLEMENTATION (Production)
# =============================================================================

class ArcFaceIdentityChecker(BaseIdentityChecker):
    """
    Production identity checker using ArcFace via insightface.
    
    ArcFace is the industry standard for face recognition:
    - 512-dimensional embeddings
    - Trained on millions of faces
    - Robust to pose, lighting, expression variations
    
    Requires: pip install insightface onnxruntime
    
    Usage:
        checker = ArcFaceIdentityChecker()
        await checker.initialize()
        
        result = await checker.compare(frame_a, frame_b)
        print(f"Similarity: {result.similarity}")
        print(f"Passed: {result.passed}")
    """
    
    def __init__(
        self,
        threshold: float = DEFAULT_IDENTITY_THRESHOLD,
        detection_threshold: float = DEFAULT_DETECTION_THRESHOLD,
        model_name: str = DEFAULT_MODEL_NAME,
        gpu_id: int = 0,
    ):
        """
        Initialize ArcFace checker.
        
        Args:
            threshold: Similarity threshold for MATCH
            detection_threshold: Face detection confidence threshold
            model_name: InsightFace model name (buffalo_l, buffalo_s, etc.)
            gpu_id: GPU to use (-1 for CPU)
        """
        super().__init__(threshold, detection_threshold)
        self.model_name = model_name
        self.gpu_id = gpu_id
        self._model = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Load the ArcFace model.
        
        Called automatically on first use, but can be called explicitly
        to pre-warm the model.
        """
        if self._initialized:
            return
        
        try:
            # Import here to avoid hard dependency
            from insightface.app import FaceAnalysis
            
            # Initialize model
            self._model = FaceAnalysis(
                name=self.model_name,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                if self.gpu_id >= 0
                else ['CPUExecutionProvider']
            )
            
            # Prepare for inference
            self._model.prepare(ctx_id=self.gpu_id, det_size=(640, 640))
            
            self._initialized = True
            logger.info(f"ArcFace model '{self.model_name}' loaded successfully")
            
        except ImportError:
            raise ModelLoadError(
                "insightface not installed. Run: pip install insightface onnxruntime"
            )
        except Exception as e:
            raise ModelLoadError(f"Failed to load ArcFace model: {e}")
    
    async def health_check(self) -> bool:
        """Check if model is loaded and ready."""
        try:
            if not self._initialized:
                await self.initialize()
            return self._model is not None
        except Exception as e:
            logger.error(f"ArcFace health check failed: {e}")
            return False
    
    async def extract_faces(self, frame_path: Path) -> FrameFaces:
        """
        Extract faces from frame using InsightFace.
        """
        import time
        start_time = time.time()
        
        if not self._initialized:
            await self.initialize()
        
        # Load image
        try:
            import cv2
            img = cv2.imread(str(frame_path))
            if img is None:
                raise ImageLoadError(f"Cannot load image: {frame_path}")
        except Exception as e:
            raise ImageLoadError(f"Failed to load {frame_path}: {e}")
        
        # Detect faces
        try:
            # Run on CPU to avoid blocking event loop
            # In production, could use run_in_executor for true async
            detected = self._model.get(img)
        except Exception as e:
            raise ExtractionError(f"Face detection failed: {e}")
        
        # Convert to our data structure
        faces = []
        for face in detected:
            # Filter by detection confidence
            if face.det_score < self.detection_threshold:
                continue
            
            bbox = tuple(int(x) for x in face.bbox)
            
            embedding = FaceEmbedding(
                embedding=face.normed_embedding,
                bbox=bbox,
                confidence=float(face.det_score),
                landmarks=face.landmark_2d_106 if hasattr(face, 'landmark_2d_106') else None,
                frame_path=frame_path,
            )
            faces.append(embedding)
        
        elapsed = time.time() - start_time
        
        return FrameFaces(
            frame_path=frame_path,
            faces=faces,
            extraction_time_sec=elapsed,
        )
    
    async def compare(
        self,
        source_frame: Path,
        target_frame: Path,
        character_hint: Optional[str] = None,
    ) -> IdentityComparison:
        """
        Compare identity between two frames.
        """
        import time
        start_time = time.time()
        
        # Debug: Log comparison request
        logger.debug(
            f"Identity compare: {source_frame.name} vs {target_frame.name}"
            f"{f' (hint: {character_hint})' if character_hint else ''}"
        )
        
        # Extract faces from both frames
        try:
            source_faces = await self.extract_faces(source_frame)
            target_faces = await self.extract_faces(target_frame)
            
            # Debug: Log face detection results
            logger.debug(
                f"  Faces detected: source={source_faces.face_count}, target={target_faces.face_count}"
            )
            
        except (ImageLoadError, ExtractionError) as e:
            logger.warning(f"  Face extraction failed: {e}")
            return IdentityComparison(
                result=IdentityCheckResult.ERROR,
                similarity=None,
                threshold=self.threshold,
                source_faces=FrameFaces(source_frame, []),
                target_faces=FrameFaces(target_frame, []),
                message=str(e),
            )
        
        elapsed = time.time() - start_time
        
        # Handle no-face cases
        if not source_faces.has_faces and not target_faces.has_faces:
            logger.info(f"  Result: NO_FACE_BOTH (no faces in either frame)")
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_BOTH,
                similarity=None,
                threshold=self.threshold,
                source_faces=source_faces,
                target_faces=target_faces,
                message="No faces detected in either frame",
                comparison_time_sec=elapsed,
            )
        
        if not source_faces.has_faces:
            logger.info(f"  Result: NO_FACE_SOURCE (no face in reference)")
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_SOURCE,
                similarity=None,
                threshold=self.threshold,
                source_faces=source_faces,
                target_faces=target_faces,
                message="No face detected in source frame",
                comparison_time_sec=elapsed,
            )
        
        if not target_faces.has_faces:
            logger.info(f"  Result: NO_FACE_TARGET (no face in generated frame)")
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_TARGET,
                similarity=None,
                threshold=self.threshold,
                source_faces=source_faces,
                target_faces=target_faces,
                message="No face detected in target frame",
                comparison_time_sec=elapsed,
            )
        
        # Single face in both: straightforward comparison
        if source_faces.face_count == 1 and target_faces.face_count == 1:
            similarity = self.compute_similarity(
                source_faces.faces[0].embedding,
                target_faces.faces[0].embedding,
            )
            
            result = (
                IdentityCheckResult.MATCH
                if similarity >= self.threshold
                else IdentityCheckResult.MISMATCH
            )
            
            # Debug: Log the key diagnostic info
            pass_fail = "PASS" if result == IdentityCheckResult.MATCH else "FAIL"
            logger.info(
                f"  Identity: {similarity:.4f} vs threshold {self.threshold:.2f} → {pass_fail}"
            )
            
            return IdentityComparison(
                result=result,
                similarity=similarity,
                threshold=self.threshold,
                source_faces=source_faces,
                target_faces=target_faces,
                matched_pairs=[(0, 0, similarity)],
                message=f"Single-face comparison: {similarity:.3f} (threshold: {self.threshold})",
                comparison_time_sec=elapsed,
            )
        
        # Multi-face: use greedy matching (primary faces)
        # TODO: Implement Hungarian algorithm for optimal matching
        source_primary = source_faces.primary_face
        target_primary = target_faces.primary_face
        
        similarity = self.compute_similarity(
            source_primary.embedding,
            target_primary.embedding,
        )
        
        result = (
            IdentityCheckResult.MATCH
            if similarity >= self.threshold
            else IdentityCheckResult.MISMATCH
        )
        
        # Flag as potentially ambiguous
        if source_faces.face_count > 1 or target_faces.face_count > 1:
            message = (
                f"Multi-face scene ({source_faces.face_count} vs {target_faces.face_count}), "
                f"compared primary faces: {similarity:.3f}"
            )
        else:
            message = f"Similarity: {similarity:.3f} (threshold: {self.threshold})"
        
        # Debug: Log the key diagnostic info
        pass_fail = "PASS" if result == IdentityCheckResult.MATCH else "FAIL"
        logger.info(
            f"  Identity: {similarity:.4f} vs threshold {self.threshold:.2f} → {pass_fail} "
            f"(faces: {source_faces.face_count} vs {target_faces.face_count})"
        )
        
        return IdentityComparison(
            result=result,
            similarity=similarity,
            threshold=self.threshold,
            source_faces=source_faces,
            target_faces=target_faces,
            matched_pairs=[(0, 0, similarity)],  # Primary face indices
            message=message,
            comparison_time_sec=elapsed,
        )


# =============================================================================
# MOCK IMPLEMENTATION (Testing)
# =============================================================================

class MockIdentityChecker(BaseIdentityChecker):
    """
    Mock identity checker for testing without models.
    
    Returns configurable results for testing different scenarios.
    
    Usage:
        # Always passes
        checker = MockIdentityChecker(mock_similarity=0.85)
        
        # Always fails
        checker = MockIdentityChecker(mock_similarity=0.50)
        
        # Simulate no face detected
        checker = MockIdentityChecker(mock_face_count=0)
    """
    
    def __init__(
        self,
        threshold: float = DEFAULT_IDENTITY_THRESHOLD,
        mock_similarity: float = 0.85,
        mock_face_count: int = 1,
        simulate_error: bool = False,
    ):
        """
        Initialize mock checker.
        
        Args:
            threshold: Similarity threshold
            mock_similarity: Similarity score to return
            mock_face_count: Number of faces to "detect"
            simulate_error: If True, raise errors on compare
        """
        super().__init__(threshold)
        self.mock_similarity = mock_similarity
        self.mock_face_count = mock_face_count
        self.simulate_error = simulate_error
        self._comparison_count = 0
    
    async def health_check(self) -> bool:
        """Mock always healthy unless simulating errors."""
        return not self.simulate_error
    
    async def extract_faces(self, frame_path: Path) -> FrameFaces:
        """
        Return mock face data.
        """
        if self.simulate_error:
            raise ExtractionError("Simulated extraction error")
        
        faces = []
        for i in range(self.mock_face_count):
            # Generate fake embedding (normalized random vector)
            fake_embedding = np.random.randn(512).astype(np.float32)
            fake_embedding = fake_embedding / np.linalg.norm(fake_embedding)
            
            faces.append(FaceEmbedding(
                embedding=fake_embedding,
                bbox=(100 + i * 200, 100, 300 + i * 200, 400),
                confidence=0.95,
                frame_path=frame_path,
            ))
        
        return FrameFaces(
            frame_path=frame_path,
            faces=faces,
            extraction_time_sec=0.01,
        )
    
    async def compare(
        self,
        source_frame: Path,
        target_frame: Path,
        character_hint: Optional[str] = None,
    ) -> IdentityComparison:
        """
        Return mock comparison result.
        """
        self._comparison_count += 1
        
        if self.simulate_error:
            return IdentityComparison(
                result=IdentityCheckResult.ERROR,
                similarity=None,
                threshold=self.threshold,
                source_faces=FrameFaces(source_frame, []),
                target_faces=FrameFaces(target_frame, []),
                message="Simulated error",
            )
        
        # Handle no-face mock scenario
        if self.mock_face_count == 0:
            return IdentityComparison(
                result=IdentityCheckResult.NO_FACE_BOTH,
                similarity=None,
                threshold=self.threshold,
                source_faces=FrameFaces(source_frame, []),
                target_faces=FrameFaces(target_frame, []),
                message="Mock: No faces configured",
            )
        
        # Generate fake face data
        source_faces = await self.extract_faces(source_frame)
        target_faces = await self.extract_faces(target_frame)
        
        # Use configured similarity
        result = (
            IdentityCheckResult.MATCH
            if self.mock_similarity >= self.threshold
            else IdentityCheckResult.MISMATCH
        )
        
        return IdentityComparison(
            result=result,
            similarity=self.mock_similarity,
            threshold=self.threshold,
            source_faces=source_faces,
            target_faces=target_faces,
            matched_pairs=[(0, 0, self.mock_similarity)],
            message=f"Mock comparison #{self._comparison_count}: {self.mock_similarity:.3f}",
            comparison_time_sec=0.02,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_identity_checker(
    use_mock: bool = False,
    threshold: float = DEFAULT_IDENTITY_THRESHOLD,
    **kwargs
) -> BaseIdentityChecker:
    """
    Factory function to get appropriate identity checker.
    
    Args:
        use_mock: If True, return mock checker
        threshold: Similarity threshold
        **kwargs: Passed to checker constructor
        
    Returns:
        Identity checker instance
    """
    if use_mock:
        return MockIdentityChecker(threshold=threshold, **kwargs)
    return ArcFaceIdentityChecker(threshold=threshold, **kwargs)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def quick_compare(
    source_frame: Path,
    target_frame: Path,
    threshold: float = DEFAULT_IDENTITY_THRESHOLD,
) -> Tuple[bool, float]:
    """
    Quick identity comparison for simple use cases.
    
    Returns:
        Tuple of (passed: bool, similarity: float or -1 if no faces)
    
    Usage:
        passed, similarity = await quick_compare(frame_a, frame_b)
        if passed:
            print(f"Identity preserved! Similarity: {similarity:.2f}")
    """
    checker = ArcFaceIdentityChecker(threshold=threshold)
    result = await checker.compare(source_frame, target_frame)
    
    return (result.passed, result.similarity if result.similarity else -1.0)


async def verify_bridge_frame(
    shot_a_last_frame: Path,
    bridge_frame: Path,
    shot_b_first_frame: Path,
    threshold: float = DEFAULT_IDENTITY_THRESHOLD,
) -> Dict[str, IdentityComparison]:
    """
    Verify identity is preserved across a bridge.
    
    Checks:
    1. Shot A â†’ Bridge Frame (bridge should match source)
    2. Bridge Frame â†’ Shot B (shot B should match bridge)
    
    Returns:
        Dict with "source_to_bridge" and "bridge_to_target" comparisons
    """
    checker = ArcFaceIdentityChecker(threshold=threshold)
    
    source_to_bridge = await checker.compare(shot_a_last_frame, bridge_frame)
    bridge_to_target = await checker.compare(bridge_frame, shot_b_first_frame)
    
    return {
        "source_to_bridge": source_to_bridge,
        "bridge_to_target": bridge_to_target,
    }