"""
Continuum Engine - ComfyUI Client Module

WebSocket client for communicating with remote ComfyUI servers,
plus workflow template loading and parameter injection.
"""

from .client import (
    # Main client
    ComfyClient,
    # Data structures
    ComfyJob,
    ComfyJobStatus,
    ComfyConnectionInfo,
    # Exceptions
    ComfyError,
    ComfyConnectionError,
    ComfyTimeoutError,
    ComfyJobError,
    # Convenience functions
    get_comfy_client,
    submit_with_retry,
)

from .workflow_loader import (
    # Main loader
    WorkflowLoader,
    # Data structures
    WorkflowTemplate,
    InjectionResult,
    ValidationResult,
    # Parameter builders
    GenerationParams,
    CharacterParams,
    EnvironmentParams,
    # Convenience functions
    get_workflow_loader,
    merge_params,
    # Constants
    KNOWN_PLACEHOLDERS,
)

__all__ = [
    # client.py
    "ComfyClient",
    "ComfyJob",
    "ComfyJobStatus",
    "ComfyConnectionInfo",
    "ComfyError",
    "ComfyConnectionError",
    "ComfyTimeoutError",
    "ComfyJobError",
    "get_comfy_client",
    "submit_with_retry",
    # workflow_loader.py
    "WorkflowLoader",
    "WorkflowTemplate",
    "InjectionResult",
    "ValidationResult",
    "GenerationParams",
    "CharacterParams",
    "EnvironmentParams",
    "get_workflow_loader",
    "merge_params",
    "KNOWN_PLACEHOLDERS",
]