"""
Continuum Engine - Audit Module

Quality control for generated content:
- Identity Checker: ArcFace face similarity (P5)
- Physics Checker: Object permanence via YOLO + ByteTrack (future)
- Flicker Checker: Temporal consistency via RAFT (future)
- Reviewer: Orchestrates all checks and produces AuditResult (future)

The audit system is the "Trust but Verify" layer — it proves that
generation worked correctly before surfacing results to users.
"""

from .identity_checker import (
    # Enums
    IdentityCheckResult,
    
    # Data structures
    FaceEmbedding,
    FrameFaces,
    IdentityComparison,
    
    # Base class
    BaseIdentityChecker,
    
    # Implementations
    ArcFaceIdentityChecker,
    MockIdentityChecker,
    
    # Factory
    get_identity_checker,
    
    # Convenience functions
    quick_compare,
    verify_bridge_frame,
    
    # Exceptions
    IdentityCheckError,
    ModelLoadError,
    ImageLoadError,
    ExtractionError,
    
    # Constants
    DEFAULT_IDENTITY_THRESHOLD,
)

__all__ = [
    # Enums
    "IdentityCheckResult",
    
    # Data structures
    "FaceEmbedding",
    "FrameFaces",
    "IdentityComparison",
    
    # Base class
    "BaseIdentityChecker",
    
    # Implementations
    "ArcFaceIdentityChecker",
    "MockIdentityChecker",
    
    # Factory
    "get_identity_checker",
    
    # Convenience functions
    "quick_compare",
    "verify_bridge_frame",
    
    # Exceptions
    "IdentityCheckError",
    "ModelLoadError",
    "ImageLoadError",
    "ExtractionError",
    
    # Constants
    "DEFAULT_IDENTITY_THRESHOLD",
]