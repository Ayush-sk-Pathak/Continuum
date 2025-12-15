"""
Continuum Engine - Core Module

Shared infrastructure: state management, configuration, checkpointing, error recovery.
"""

from .job_state import (
    # Enums
    JobStatus,
    AuditStatus,
    AuditCheckType,
    # Dataclasses
    AuditFlag,
    AuditResult,
    JobCheckpoint,
    # Utilities
    is_terminal_status,
    is_success_status,
)

from .config import (
    Config,
    get_config,
    reload_config,
    # Nested configs (for type hints)
    GenerationConfig,
    AuditConfig,
    SonicConfig,
    PostConfig,
    ComfyUIConfig,
    PathsConfig,
)

from .checkpointing import (
    CheckpointManager,
    get_checkpoint_manager,
)

from .error_recovery import (
    # Error classification
    ErrorCategory,
    CategorizedError,
    categorize_error,
    # Retry logic
    RetryConfig,
    retry,
    retry_async,
    calculate_delay,
    should_retry,
    # Degradation
    DegradationStep,
    DegradationLadder,
    create_identity_ladder,
    create_audio_ladder,
    # Recovery context
    RecoveryContext,
    format_user_error,
)

__all__ = [
    # job_state
    "JobStatus",
    "AuditStatus", 
    "AuditCheckType",
    "AuditFlag",
    "AuditResult",
    "JobCheckpoint",
    "is_terminal_status",
    "is_success_status",
    # config
    "Config",
    "get_config",
    "reload_config",
    "GenerationConfig",
    "AuditConfig",
    "SonicConfig",
    "PostConfig",
    "ComfyUIConfig",
    "PathsConfig",
    # checkpointing
    "CheckpointManager",
    "get_checkpoint_manager",
    # error_recovery
    "ErrorCategory",
    "CategorizedError",
    "categorize_error",
    "RetryConfig",
    "retry",
    "retry_async",
    "calculate_delay",
    "should_retry",
    "DegradationStep",
    "DegradationLadder",
    "create_identity_ladder",
    "create_audio_ladder",
    "RecoveryContext",
    "format_user_error",
]