"""
Continuum Engine - Renderers Module

Pluggable video generation backends. All renderers implement BaseRenderer,
allowing hot-swap between OSS (Wan, Hunyuan) and Pro (Runway, Veo) backends.
"""

from .base import (
    # Abstract base
    BaseRenderer,
    # Enums
    RendererType,
    RenderQuality,
    # Input types
    JobSpec,
    CharacterRef,
    LocationRef,
    LayoutRegion,
    # Output types
    RenderResult,
    RenderProgress,
    # Exceptions
    RenderError,
    RenderTimeoutError,
    RenderConfigError,
    RenderBackendError,
    # Registry
    register_renderer,
    get_renderer,
    list_renderers,
)

from .wan_renderer import (
    WanRenderer,
    MockRenderer,
)

__all__ = [
    # Base class
    "BaseRenderer",
    # Enums
    "RendererType",
    "RenderQuality",
    # Input types
    "JobSpec",
    "CharacterRef",
    "LocationRef",
    "LayoutRegion",
    # Output types
    "RenderResult",
    "RenderProgress",
    # Exceptions
    "RenderError",
    "RenderTimeoutError",
    "RenderConfigError",
    "RenderBackendError",
    # Registry
    "register_renderer",
    "get_renderer",
    "list_renderers",
    # Concrete renderers
    "WanRenderer",
    "MockRenderer",
]