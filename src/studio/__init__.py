"""
Continuum Engine - Studio Module

The "studio" handles all rendering orchestration:
- Bridge Engine: Generates transition frames between shots
- Pass2 Refiner: Flicker reduction and quality enhancement (future)
- RIFE Interpolator: Frame rate upscaling (future)

This is the "Cloud Muscle" coordination layer - it dispatches jobs
to ComfyUI and assembles results.
"""

from .bridge_engine import (
    # Enums
    BridgeMethod,
    BridgeStatus,
    CameraTransition,
    
    # Data structures
    BridgeSpec,
    BridgeResult,
    BridgeProgress,
    PoseData,
    
    # Base class
    BaseBridgeEngine,
    
    # Implementations
    ComfyUIBridgeEngine,
    MockBridgeEngine,
    
    # Factory
    get_bridge_engine,
    
    # Exceptions
    BridgeError,
    BridgeSourceError,
    BridgePoseError,
    BridgeGenerationError,
)

__all__ = [
    # Enums
    "BridgeMethod",
    "BridgeStatus", 
    "CameraTransition",
    
    # Data structures
    "BridgeSpec",
    "BridgeResult",
    "BridgeProgress",
    "PoseData",
    
    # Base class
    "BaseBridgeEngine",
    
    # Implementations
    "ComfyUIBridgeEngine",
    "MockBridgeEngine",
    
    # Factory
    "get_bridge_engine",
    
    # Exceptions
    "BridgeError",
    "BridgeSourceError",
    "BridgePoseError",
    "BridgeGenerationError",
]