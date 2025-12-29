"""
Continuum Engine - Renderers Module

This module provides the abstraction layer for video generation backends.
All renderers implement BaseRenderer, enabling hot-swapping between:

- WanRenderer: Wan 2.x via ComfyUI (Standard Lane, cost-effective)
- HunyuanCustomRenderer: HunyuanCustom via ComfyUI (identity-preserving, 0.627 ArcFace)
- Future: RunwayRenderer, VeoRenderer (Pro Lane)

Usage:
    # Option 1: Config-driven factory (RECOMMENDED)
    from src.renderers import get_renderer_for_config
    renderer = get_renderer_for_config()  # Reads CONTINUUM_VIDEO_MODEL__MODEL_FAMILY
    
    # Option 2: Explicit renderer type
    from src.renderers import get_renderer, RendererType
    renderer = get_renderer(RendererType.WAN)
    
    # Option 3: Direct class (for testing)
    from src.renderers import WanRenderer, HunyuanCustomRenderer
    renderer = WanRenderer()

Architecture Note:
    The @register_renderer decorator auto-registers renderers when imported.
    Importing this __init__.py triggers all renderer imports, populating
    the global registry before get_renderer() is called.
"""

# =============================================================================
# BASE CLASSES AND TYPES (from base.py)
# =============================================================================

from .base import (
    # Core classes
    BaseRenderer,
    JobSpec,
    RenderResult,
    RenderProgress,
    
    # Reference types
    CharacterRef,
    LocationRef,
    
    # Enums
    RendererType,
    RenderQuality,
    
    # Exceptions
    RenderError,
    RenderTimeoutError,
    RenderConfigError,
    RenderBackendError,
    
    # Registry functions
    register_renderer,
    get_renderer,
    list_renderers,
    get_renderer_for_config,
)

# =============================================================================
# CONCRETE RENDERERS
# =============================================================================

# Import renderers to trigger @register_renderer decorators
# This populates _renderer_registry before any get_renderer() calls

from .wan_renderer import WanRenderer
from .hunyuan_custom_renderer import HunyuanCustomRenderer

# Future renderers (uncomment when implemented):
# from .runway_renderer import RunwayRenderer
# from .veo_renderer import VeoRenderer


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Base classes
    "BaseRenderer",
    "JobSpec",
    "RenderResult",
    "RenderProgress",
    
    # Reference types
    "CharacterRef",
    "LocationRef",
    
    # Enums
    "RendererType",
    "RenderQuality",
    
    # Exceptions
    "RenderError",
    "RenderTimeoutError",
    "RenderConfigError",
    "RenderBackendError",
    
    # Registry functions
    "register_renderer",
    "get_renderer",
    "list_renderers",
    "get_renderer_for_config",
    
    # Concrete renderers
    "WanRenderer",
    "HunyuanCustomRenderer",
]