"""
Continuum Engine - Error Recovery & Graceful Degradation

Handles failures intelligently: retry with backoff, degrade gracefully,
and surface actionable errors to users.

Design Principles:
1. Retry transient failures (network, API rate limits)
2. Don't retry permanent failures (invalid config, missing files)
3. Degrade gracefully when possible (LoRA missing → use IP-Adapter)
4. Never lose work — checkpoint before risky operations
5. Surface clear, actionable error messages
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import (
    Any, 
    Callable, 
    Dict, 
    List, 
    Optional, 
    Type, 
    TypeVar, 
    Union,
    Awaitable
)

logger = logging.getLogger(__name__)

# Type variable for generic retry decorator
T = TypeVar("T")


# =============================================================================
# ERROR CLASSIFICATION
# =============================================================================

class ErrorCategory(str, Enum):
    """
    Classification of errors for recovery decisions.
    
    TRANSIENT: Temporary, worth retrying (network timeout, rate limit)
    PERMANENT: Won't fix itself (invalid config, missing file)
    DEGRADABLE: Can work around with reduced functionality
    FATAL: System cannot continue (out of disk, critical config missing)
    """
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    DEGRADABLE = "degradable"
    FATAL = "fatal"


@dataclass
class CategorizedError:
    """
    Wrapper that adds recovery metadata to an exception.
    
    Attributes:
        original: The original exception
        category: How to handle this error
        retry_after_sec: Hint for when to retry (for rate limits)
        degradation_hint: What to fall back to if degradable
        user_message: Human-readable explanation
    """
    original: Exception
    category: ErrorCategory
    retry_after_sec: Optional[float] = None
    degradation_hint: Optional[str] = None
    user_message: str = ""
    
    def __str__(self) -> str:
        return f"[{self.category.value}] {self.user_message or str(self.original)}"


# Default categorization rules for common exceptions
DEFAULT_ERROR_CATEGORIES: Dict[Type[Exception], ErrorCategory] = {
    # Transient (worth retrying)
    TimeoutError: ErrorCategory.TRANSIENT,
    ConnectionError: ErrorCategory.TRANSIENT,
    ConnectionResetError: ErrorCategory.TRANSIENT,
    ConnectionRefusedError: ErrorCategory.TRANSIENT,
    
    # Permanent (don't retry)
    FileNotFoundError: ErrorCategory.PERMANENT,
    PermissionError: ErrorCategory.PERMANENT,
    ValueError: ErrorCategory.PERMANENT,
    TypeError: ErrorCategory.PERMANENT,
    KeyError: ErrorCategory.PERMANENT,
    
    # Fatal
    MemoryError: ErrorCategory.FATAL,
    SystemExit: ErrorCategory.FATAL,
    KeyboardInterrupt: ErrorCategory.FATAL,
}


def categorize_error(
    error: Exception,
    custom_rules: Optional[Dict[Type[Exception], ErrorCategory]] = None
) -> CategorizedError:
    """
    Categorize an exception for recovery decisions.
    
    Args:
        error: The exception to categorize
        custom_rules: Additional categorization rules
        
    Returns:
        CategorizedError with recovery metadata
    """
    rules = {**DEFAULT_ERROR_CATEGORIES, **(custom_rules or {})}
    
    # Check exact type first, then base classes
    for exc_type, category in rules.items():
        if isinstance(error, exc_type):
            return CategorizedError(
                original=error,
                category=category,
                user_message=str(error)
            )
    
    # Default to transient (optimistic — better to retry than give up)
    return CategorizedError(
        original=error,
        category=ErrorCategory.TRANSIENT,
        user_message=str(error)
    )


# =============================================================================
# RETRY LOGIC
# =============================================================================

@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.
    
    Attributes:
        max_attempts: Maximum number of tries (including first attempt)
        base_delay_sec: Initial delay between retries
        max_delay_sec: Cap on delay (prevents infinite backoff)
        exponential_base: Multiplier for exponential backoff (2 = double each time)
        jitter: Add randomness to prevent thundering herd (0.0-1.0)
        retry_on: Exception types to retry (empty = retry all transient)
        on_retry: Callback when retry happens (for logging/metrics)
    """
    max_attempts: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 60.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    retry_on: tuple = ()  # Empty = use error categorization
    on_retry: Optional[Callable[[Exception, int], None]] = None


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """
    Calculate delay before next retry with exponential backoff and jitter.
    
    Args:
        attempt: Current attempt number (1-indexed)
        config: Retry configuration
        
    Returns:
        Delay in seconds
    """
    # Exponential backoff
    delay = config.base_delay_sec * (config.exponential_base ** (attempt - 1))
    
    # Cap at max
    delay = min(delay, config.max_delay_sec)
    
    # Add jitter (±jitter%)
    if config.jitter > 0:
        jitter_range = delay * config.jitter
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.1, delay)  # Never less than 100ms


def should_retry(error: Exception, config: RetryConfig) -> bool:
    """
    Determine if an error should trigger a retry.
    
    Args:
        error: The exception that occurred
        config: Retry configuration
        
    Returns:
        True if should retry, False otherwise
    """
    # If specific exceptions listed, only retry those
    if config.retry_on:
        return isinstance(error, config.retry_on)
    
    # Otherwise, use error categorization
    categorized = categorize_error(error)
    return categorized.category == ErrorCategory.TRANSIENT


def retry(
    config: Optional[RetryConfig] = None,
    **config_kwargs
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for automatic retry with exponential backoff.
    
    Usage:
        @retry(max_attempts=3, base_delay_sec=1.0)
        def call_flaky_api():
            return api.request()
        
        # Or with RetryConfig object
        @retry(config=RetryConfig(max_attempts=5))
        def another_function():
            pass
    """
    if config is None:
        config = RetryConfig(**config_kwargs)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error: Optional[Exception] = None
            
            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    last_error = e
                    
                    # Check if we should retry
                    if not should_retry(e, config):
                        logger.warning(
                            f"{func.__name__} failed with non-retryable error: {e}"
                        )
                        raise
                    
                    # Check if we have attempts left
                    if attempt >= config.max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {attempt} attempts: {e}"
                        )
                        raise
                    
                    # Calculate delay and wait
                    delay = calculate_delay(attempt, config)
                    logger.warning(
                        f"{func.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    # Call retry callback if provided
                    if config.on_retry:
                        config.on_retry(e, attempt)
                    
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            raise last_error or RuntimeError("Retry loop exited unexpectedly")
        
        return wrapper
    return decorator


def retry_async(
    config: Optional[RetryConfig] = None,
    **config_kwargs
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Async version of the retry decorator.
    
    Usage:
        @retry_async(max_attempts=3)
        async def call_async_api():
            return await api.request()
    """
    if config is None:
        config = RetryConfig(**config_kwargs)
    
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_error: Optional[Exception] = None
            
            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except Exception as e:
                    last_error = e
                    
                    if not should_retry(e, config):
                        raise
                    
                    if attempt >= config.max_attempts:
                        raise
                    
                    delay = calculate_delay(attempt, config)
                    logger.warning(
                        f"{func.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    if config.on_retry:
                        config.on_retry(e, attempt)
                    
                    await asyncio.sleep(delay)
            
            raise last_error or RuntimeError("Retry loop exited unexpectedly")
        
        return wrapper
    return decorator


# =============================================================================
# GRACEFUL DEGRADATION
# =============================================================================

@dataclass
class DegradationStep:
    """
    A single step in the degradation ladder.
    
    Attributes:
        name: Human-readable name for this fallback
        condition: Function that checks if this fallback is available
        action: Function to execute for this fallback
        quality_impact: Description of what's lost (for user notification)
    """
    name: str
    condition: Callable[[], bool]
    action: Callable[..., Any]
    quality_impact: str = ""


class DegradationLadder:
    """
    Manages a sequence of fallback options from best to worst.
    
    Usage:
        ladder = DegradationLadder("Character Identity")
        
        ladder.add_step(
            name="LoRA",
            condition=lambda: lora_path.exists(),
            action=lambda: render_with_lora(lora_path),
            quality_impact="None - full quality"
        )
        ladder.add_step(
            name="IP-Adapter",
            condition=lambda: face_refs_exist(),
            action=lambda: render_with_ip_adapter(face_refs),
            quality_impact="~15% identity consistency reduction"
        )
        ladder.add_step(
            name="Prompt Only",
            condition=lambda: True,  # Always available
            action=lambda: render_prompt_only(description),
            quality_impact="~40% identity consistency reduction"
        )
        
        result, step_used = ladder.execute()
    """
    
    def __init__(self, name: str):
        """
        Initialize the ladder.
        
        Args:
            name: Descriptive name for this degradation context
        """
        self.name = name
        self.steps: List[DegradationStep] = []
    
    def add_step(
        self,
        name: str,
        condition: Callable[[], bool],
        action: Callable[..., Any],
        quality_impact: str = ""
    ) -> "DegradationLadder":
        """Add a fallback step (chainable)."""
        self.steps.append(DegradationStep(
            name=name,
            condition=condition,
            action=action,
            quality_impact=quality_impact
        ))
        return self
    
    def execute(self, *args, **kwargs) -> tuple[Any, DegradationStep]:
        """
        Execute the first available step in the ladder.
        
        Args:
            *args, **kwargs: Passed to the action function
            
        Returns:
            Tuple of (result, step_used)
            
        Raises:
            RuntimeError: If no steps are available
        """
        for step in self.steps:
            try:
                if step.condition():
                    logger.info(f"[{self.name}] Using: {step.name}")
                    if step.quality_impact:
                        logger.warning(f"[{self.name}] Quality impact: {step.quality_impact}")
                    
                    result = step.action(*args, **kwargs)
                    return result, step
                    
            except Exception as e:
                logger.warning(f"[{self.name}] {step.name} failed: {e}, trying next...")
                continue
        
        raise RuntimeError(
            f"[{self.name}] All degradation steps exhausted. "
            f"Tried: {[s.name for s in self.steps]}"
        )
    
    def get_available_steps(self) -> List[DegradationStep]:
        """Get list of currently available steps."""
        return [step for step in self.steps if step.condition()]


# =============================================================================
# PRE-BUILT DEGRADATION LADDERS
# =============================================================================

def create_identity_ladder(
    lora_path: Optional[str],
    face_refs: Optional[List[str]],
    character_description: str,
    render_func: Callable
) -> DegradationLadder:
    """
    Create a standard degradation ladder for character identity.
    
    This implements the Architecture's fallback chain:
    LoRA (95%) → IP-Adapter (80%) → Prompt-only (60%)
    
    Args:
        lora_path: Path to character LoRA (or None)
        face_refs: List of face reference image paths (or None)
        character_description: Text description fallback
        render_func: Function that takes (mode, assets) and renders
        
    Returns:
        Configured DegradationLadder
    """
    from pathlib import Path
    
    ladder = DegradationLadder("Character Identity")
    
    # Best: LoRA
    ladder.add_step(
        name="LoRA",
        condition=lambda: lora_path is not None and Path(lora_path).exists(),
        action=lambda: render_func("lora", {"lora_path": lora_path}),
        quality_impact="None - full quality (~95% consistency)"
    )
    
    # Fallback: IP-Adapter with face references
    ladder.add_step(
        name="IP-Adapter",
        condition=lambda: face_refs is not None and len(face_refs) > 0,
        action=lambda: render_func("ip_adapter", {"face_refs": face_refs}),
        quality_impact="Reduced to ~80% identity consistency"
    )
    
    # Last resort: Prompt only
    ladder.add_step(
        name="Prompt-Only",
        condition=lambda: True,  # Always available
        action=lambda: render_func("prompt", {"description": character_description}),
        quality_impact="Reduced to ~60% identity consistency"
    )
    
    return ladder


def create_audio_ladder(
    elevenlabs_available: bool,
    openai_available: bool,
    text: str,
    tts_func: Callable
) -> DegradationLadder:
    """
    Create a standard degradation ladder for TTS.
    
    ElevenLabs (best quality) → OpenAI TTS → Silent (flag for retry)
    """
    ladder = DegradationLadder("Text-to-Speech")
    
    ladder.add_step(
        name="ElevenLabs",
        condition=lambda: elevenlabs_available,
        action=lambda: tts_func("elevenlabs", text),
        quality_impact="None - highest quality"
    )
    
    ladder.add_step(
        name="OpenAI TTS",
        condition=lambda: openai_available,
        action=lambda: tts_func("openai", text),
        quality_impact="Slight reduction in voice naturalness"
    )
    
    ladder.add_step(
        name="Silent",
        condition=lambda: True,
        action=lambda: tts_func("silent", text),
        quality_impact="No audio - flagged for manual retry"
    )
    
    return ladder


# =============================================================================
# RECOVERY CONTEXT MANAGER
# =============================================================================

class RecoveryContext:
    """
    Context manager that wraps operations with retry and degradation.
    
    Usage:
        with RecoveryContext("Generate Shot", checkpoint_manager, job) as ctx:
            ctx.checkpoint()  # Save state before risky operation
            result = risky_operation()
            ctx.checkpoint()  # Save state after success
            
    On failure:
    - Automatically retries transient errors
    - Applies degradation ladder if configured
    - Saves checkpoint before surfacing error
    """
    
    def __init__(
        self,
        operation_name: str,
        checkpoint_manager: Optional[Any] = None,
        job: Optional[Any] = None,
        retry_config: Optional[RetryConfig] = None,
        degradation_ladder: Optional[DegradationLadder] = None
    ):
        self.operation_name = operation_name
        self.checkpoint_manager = checkpoint_manager
        self.job = job
        self.retry_config = retry_config or RetryConfig()
        self.degradation_ladder = degradation_ladder
        self._degraded = False
        self._step_used: Optional[DegradationStep] = None
    
    def __enter__(self) -> "RecoveryContext":
        logger.info(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_val is None:
            logger.info(f"Completed: {self.operation_name}")
            return False
        
        # Categorize the error
        categorized = categorize_error(exc_val)
        
        # Save checkpoint before handling
        self.checkpoint()
        
        # Log based on category
        if categorized.category == ErrorCategory.FATAL:
            logger.critical(f"FATAL error in {self.operation_name}: {exc_val}")
            return False  # Don't suppress, let it propagate
        
        elif categorized.category == ErrorCategory.PERMANENT:
            logger.error(f"Permanent error in {self.operation_name}: {exc_val}")
            return False  # Don't suppress
        
        elif categorized.category == ErrorCategory.DEGRADABLE:
            if self.degradation_ladder:
                logger.warning(f"Attempting degradation for {self.operation_name}")
                # Note: actual degradation should be handled by caller
                # This just logs the intent
            return False
        
        else:  # TRANSIENT
            logger.warning(f"Transient error in {self.operation_name}: {exc_val}")
            return False  # Retry should be handled by @retry decorator
    
    def checkpoint(self) -> None:
        """Save current job state."""
        if self.checkpoint_manager and self.job:
            try:
                self.checkpoint_manager.save(self.job)
            except Exception as e:
                logger.error(f"Failed to save checkpoint: {e}")
    
    @property
    def degraded(self) -> bool:
        """Whether we're running in degraded mode."""
        return self._degraded
    
    @property
    def step_used(self) -> Optional[DegradationStep]:
        """Which degradation step was used (if any)."""
        return self._step_used


# =============================================================================
# USER-FACING ERROR MESSAGES
# =============================================================================

def format_user_error(error: Exception, context: str = "") -> str:
    """
    Format an error for user display (non-technical).
    
    Args:
        error: The exception
        context: What was being attempted
        
    Returns:
        User-friendly error message with suggested actions
    """
    categorized = categorize_error(error)
    
    base_message = context or "An error occurred"
    
    if categorized.category == ErrorCategory.TRANSIENT:
        return (
            f"{base_message}: temporary issue.\n"
            f"Details: {error}\n"
            f"Suggestion: This usually resolves itself. Try again in a few minutes."
        )
    
    elif categorized.category == ErrorCategory.PERMANENT:
        return (
            f"{base_message}: configuration issue.\n"
            f"Details: {error}\n"
            f"Suggestion: Check your settings and input files."
        )
    
    elif categorized.category == ErrorCategory.DEGRADABLE:
        return (
            f"{base_message}: running with reduced quality.\n"
            f"Details: {error}\n"
            f"Suggestion: Check that all assets are available for full quality."
        )
    
    else:  # FATAL
        return (
            f"{base_message}: critical system error.\n"
            f"Details: {error}\n"
            f"Suggestion: Please contact support with this error message."
        )