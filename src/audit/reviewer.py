"""
Continuum Engine - Reviewer (Audit Orchestrator)

The "Trust but Verify" brain. Orchestrates all QA checks on generated video chunks
and makes the final PASS/FAIL/REROLL decision.

The Problem:
    We have multiple QA checkers (identity, physics, eventually flicker).
    Each returns its own result format. We need a single decision point.

The Solution:
    Reviewer aggregates all checks, weights their results, and produces
    a unified AuditResult that the job pipeline can act on.

Decision Logic:
    1. Run all enabled checks in parallel (for speed)
    2. Aggregate flags from each checker
    3. Apply severity weighting
    4. Make final call: PASS â†’ continue, FAIL â†’ reroll, WARN â†’ flag for review

Use Cases:
    1. Within-shot audit: Check identity + physics within a single chunk
    2. Cross-shot audit: Verify bridge transition preserved continuity
    3. Full-shot audit: Both within-shot and cross-shot combined

Architecture Position:
    PASS 1 â†’ [REVIEWER] â†’ Pass 2 (if approved)
                â†“
           REROLL (if failed, attempt < max)
                â†“
           HUMAN REVIEW (if max attempts exceeded)

Design Principles:
    1. Parallel execution: Don't wait for identity to finish before physics
    2. Fail fast option: Can short-circuit on first hard failure
    3. Extensible: Easy to add flicker check, scene consistency, etc.
    4. Configurable: Thresholds come from AuditConfig
    5. Audit trail: Every decision is logged with reasoning
"""

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

# Local imports - using relative imports for module structure
from .identity_checker import (
    BaseIdentityChecker,
    IdentityComparison,
    IdentityCheckResult,
    get_identity_checker,
)
from .physics_checker import (
    BasePhysicsChecker,
    PhysicsAnalysis,
    PhysicsCheckResult,
    PhysicsViolation,
    get_physics_checker,
)

# Import from sibling modules
# Note: When integrated, these will be proper relative imports
# For now, we also support absolute imports for testing
try:
    from ..core.job_state import AuditResult, AuditFlag, AuditStatus, AuditCheckType
    from ..core.config import AuditConfig, get_config
except ImportError:
    # Fallback for standalone testing
    from core.job_state import AuditResult, AuditFlag, AuditStatus, AuditCheckType
    from core.config import AuditConfig, get_config


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION DEFAULTS
# =============================================================================

DEFAULT_IDENTITY_WEIGHT = 1.0      # Identity failures are critical
DEFAULT_PHYSICS_WEIGHT = 0.8       # Physics issues slightly less critical
DEFAULT_FLICKER_WEIGHT = 0.6       # Flicker is annoying but survivable
DEFAULT_FAIL_THRESHOLD = 0.7       # Weighted severity above this = FAIL
DEFAULT_WARN_THRESHOLD = 0.3       # Weighted severity above this = WARN


# =============================================================================
# ENUMS
# =============================================================================

class AuditMode(str, Enum):
    """What type of audit to perform."""
    WITHIN_SHOT = "within_shot"      # Check single chunk internally
    CROSS_SHOT = "cross_shot"        # Check transition between shots
    FULL = "full"                    # Both within and cross-shot


class CheckType(str, Enum):
    """Types of checks the reviewer can run."""
    IDENTITY = "identity"
    PHYSICS = "physics"
    FLICKER = "flicker"      # Future: RAFT optical flow
    SCENE = "scene"          # Future: CLIP consistency


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ReviewRequest:
    """
    Request to review a generated video chunk.
    
    Attributes:
        video_path: Path to the rendered video chunk
        reference_frame: Optional reference for identity (e.g., character LoRA ref)
        previous_shot_path: For cross-shot audit, the preceding video
        shot_id: Identifier for logging/tracking
        checks_enabled: Which checks to run (default: all available)
        character_ids: Characters expected in this shot (for identity checking)
    """
    video_path: Path
    reference_frame: Optional[Path] = None
    previous_shot_path: Optional[Path] = None
    shot_id: str = ""
    checks_enabled: List[CheckType] = field(default_factory=lambda: [
        CheckType.IDENTITY,
        CheckType.PHYSICS,
    ])
    character_ids: List[str] = field(default_factory=list)
    
    @property
    def mode(self) -> AuditMode:
        """Determine audit mode from request parameters."""
        if self.previous_shot_path:
            return AuditMode.CROSS_SHOT
        return AuditMode.WITHIN_SHOT


@dataclass
class CheckResult:
    """
    Result from a single check (identity, physics, etc.).
    
    Normalized structure for aggregation.
    """
    check_type: CheckType
    passed: bool
    severity: float              # 0.0 (no issues) to 1.0 (critical)
    flags: List[AuditFlag]
    score: Optional[float]       # e.g., identity similarity
    recommendation: str          # "approve", "reroll", "manual_review"
    details: Dict[str, Any] = field(default_factory=dict)
    execution_time_sec: float = 0.0


@dataclass
class ReviewResult:
    """
    Complete result of reviewing a video chunk.
    
    This is the reviewer's output, which gets converted to AuditResult
    for the job pipeline.
    """
    audit_result: AuditResult
    check_results: List[CheckResult]
    mode: AuditMode
    video_path: Path
    shot_id: str
    total_time_sec: float = 0.0
    
    @property
    def passed(self) -> bool:
        return self.audit_result.status == AuditStatus.PASS
    
    @property
    def should_reroll(self) -> bool:
        return self.audit_result.recommendation == "reroll"
    
    @property
    def needs_human_review(self) -> bool:
        return self.audit_result.recommendation == "manual_review"
    
    def summary(self) -> str:
        """Human-readable summary of the review."""
        status = self.audit_result.status.value.upper()
        checks = ", ".join(cr.check_type.value for cr in self.check_results)
        flag_count = len(self.audit_result.flags)
        
        return (
            f"[{status}] Shot {self.shot_id}: "
            f"{flag_count} flags from checks [{checks}] "
            f"â†’ {self.audit_result.recommendation}"
        )


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ReviewError(Exception):
    """Base exception for review errors."""
    pass


class FrameExtractionError(ReviewError):
    """Error extracting frames from video."""
    pass


class CheckExecutionError(ReviewError):
    """Error running a specific check."""
    pass


# =============================================================================
# REVIEWER CLASS
# =============================================================================

class Reviewer:
    """
    Orchestrates QA checks on generated video chunks.
    
    The Reviewer is the decision-maker that aggregates multiple
    specialized checkers into a single PASS/FAIL/REROLL verdict.
    
    Usage:
        reviewer = Reviewer()
        
        # Simple within-shot review
        result = await reviewer.review(ReviewRequest(
            video_path=Path("chunk_001.mp4"),
            shot_id="scene_01_shot_03",
        ))
        
        if result.should_reroll:
            # Re-generate the chunk
            pass
        elif result.needs_human_review:
            # Surface to user
            pass
        else:
            # Proceed to Pass 2
            pass
    """
    
    def __init__(
        self,
        identity_checker: Optional[BaseIdentityChecker] = None,
        physics_checker: Optional[BasePhysicsChecker] = None,
        config: Optional[AuditConfig] = None,
        identity_weight: float = DEFAULT_IDENTITY_WEIGHT,
        physics_weight: float = DEFAULT_PHYSICS_WEIGHT,
        fail_threshold: float = DEFAULT_FAIL_THRESHOLD,
        warn_threshold: float = DEFAULT_WARN_THRESHOLD,
        parallel_checks: bool = True,
        fail_fast: bool = False,
    ):
        """
        Initialize the Reviewer.
        
        Args:
            identity_checker: Custom identity checker (or None to auto-create)
            physics_checker: Custom physics checker (or None to auto-create)
            config: Audit configuration (or None to use global config)
            identity_weight: Weight for identity check severity (0-1)
            physics_weight: Weight for physics check severity (0-1)
            fail_threshold: Weighted severity above this = FAIL
            warn_threshold: Weighted severity above this = WARN
            parallel_checks: Run checks in parallel (faster)
            fail_fast: Stop on first hard failure (saves compute)
        """
        self.config = config or get_config().audit
        
        # Initialize checkers with config thresholds
        self.identity_checker = identity_checker or get_identity_checker(
            threshold=self.config.identity_threshold,
        )
        self.physics_checker = physics_checker or get_physics_checker(
            missing_frames_threshold=self.config.physics_missing_frames,
        )
        
        # Weights for severity aggregation
        self.identity_weight = identity_weight
        self.physics_weight = physics_weight
        
        # Decision thresholds
        self.fail_threshold = fail_threshold
        self.warn_threshold = warn_threshold
        
        # Execution options
        self.parallel_checks = parallel_checks
        self.fail_fast = fail_fast
        
        # Stats tracking
        self._reviews_performed = 0
        self._total_review_time = 0.0
    
    async def review(self, request: ReviewRequest) -> ReviewResult:
        """
        Perform a complete review of a video chunk.
        
        This is the main entry point.
        
        Args:
            request: Review request with video path and options
            
        Returns:
            ReviewResult with audit decision and details
        """
        start_time = time.time()
        self._reviews_performed += 1
        
        logger.info(
            f"Starting review #{self._reviews_performed} for {request.shot_id} "
            f"mode={request.mode.value}"
        )
        
        # Validate request
        if not request.video_path.exists():
            raise ReviewError(f"Video not found: {request.video_path}")
        
        # Run enabled checks
        check_results: List[CheckResult] = []
        
        if self.parallel_checks:
            check_results = await self._run_checks_parallel(request)
        else:
            check_results = await self._run_checks_sequential(request)
        
        # Aggregate into final decision
        audit_result = self._aggregate_results(check_results)
        
        elapsed = time.time() - start_time
        self._total_review_time += elapsed
        
        result = ReviewResult(
            audit_result=audit_result,
            check_results=check_results,
            mode=request.mode,
            video_path=request.video_path,
            shot_id=request.shot_id,
            total_time_sec=elapsed,
        )
        
        logger.info(f"Review complete: {result.summary()}")
        
        return result
    
    async def _run_checks_parallel(
        self,
        request: ReviewRequest,
    ) -> List[CheckResult]:
        """Run all enabled checks in parallel."""
        tasks = []
        
        if CheckType.IDENTITY in request.checks_enabled:
            tasks.append(self._run_identity_check(request))
        
        if CheckType.PHYSICS in request.checks_enabled:
            tasks.append(self._run_physics_check(request))
        
        # Future: Add flicker, scene checks here
        
        if not tasks:
            logger.warning("No checks enabled, auto-passing")
            return []
        
        # Run all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results, handling any exceptions
        check_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Check failed with exception: {result}")
                # Create a failed check result
                check_results.append(CheckResult(
                    check_type=CheckType.IDENTITY,  # TODO: Track which check failed
                    passed=False,
                    severity=0.5,  # Moderate severity for errors
                    flags=[AuditFlag(
                        check_type=AuditCheckType.IDENTITY,
                        frame_range=(0, 0),
                        severity=0.5,
                        description=f"Check error: {str(result)}",
                    )],
                    score=None,
                    recommendation="manual_review",
                    details={"error": str(result)},
                ))
            else:
                check_results.append(result)
        
        return check_results
    
    async def _run_checks_sequential(
        self,
        request: ReviewRequest,
    ) -> List[CheckResult]:
        """Run checks one at a time (with optional fail-fast)."""
        check_results = []
        
        if CheckType.IDENTITY in request.checks_enabled:
            result = await self._run_identity_check(request)
            check_results.append(result)
            
            if self.fail_fast and not result.passed and result.severity >= self.fail_threshold:
                logger.info("Fail-fast triggered on identity check")
                return check_results
        
        if CheckType.PHYSICS in request.checks_enabled:
            result = await self._run_physics_check(request)
            check_results.append(result)
            
            if self.fail_fast and not result.passed and result.severity >= self.fail_threshold:
                logger.info("Fail-fast triggered on physics check")
                return check_results
        
        return check_results
    
    async def _run_identity_check(
        self,
        request: ReviewRequest,
    ) -> CheckResult:
        """
        Run identity check on the video.
        
        Strategy:
        - Within-shot: Compare first frame vs last frame
        - Cross-shot: Compare previous shot's last frame vs this shot's first frame
        - With reference: Compare reference frame vs first frame
        """
        start_time = time.time()
        
        try:
            # Extract frames for comparison
            source_frame, target_frame = await self._get_identity_frames(request)
            
            # Run comparison
            comparison: IdentityComparison = await self.identity_checker.compare(
                source_frame=source_frame,
                target_frame=target_frame,
                character_hint=request.character_ids[0] if request.character_ids else None,
            )
            
            # Convert to CheckResult
            flags = []
            if not comparison.passed:
                # Clamp severity to 0.0-1.0 range (similarity can exceed 1.0 due to numerical precision)
                flag_severity = max(0.0, min(1.0, 1.0 - (comparison.similarity or 0.0)))
                flags.append(AuditFlag(
                    check_type=AuditCheckType.IDENTITY,
                    frame_range=(0, -1),  # Whole video
                    severity=flag_severity,
                    description=comparison.message,
                ))
            
            # Determine severity
            if comparison.passed:
                severity = 0.0
            elif comparison.result == IdentityCheckResult.MISMATCH:
                # Severity based on how far below threshold
                similarity = comparison.similarity or 0.0
                severity = min(1.0, (comparison.threshold - similarity) / comparison.threshold + 0.3)
            elif comparison.needs_human_review:
                severity = 0.4  # Ambiguous cases get moderate severity
            else:
                severity = 0.8  # Errors get high severity
            
            return CheckResult(
                check_type=CheckType.IDENTITY,
                passed=comparison.passed,
                severity=severity,
                flags=flags,
                score=comparison.similarity,
                recommendation=comparison.to_audit_recommendation(),
                details=comparison.to_dict(),
                execution_time_sec=time.time() - start_time,
            )
            
        except Exception as e:
            logger.error(f"Identity check failed: {e}")
            return CheckResult(
                check_type=CheckType.IDENTITY,
                passed=False,
                severity=0.5,
                flags=[AuditFlag(
                    check_type=AuditCheckType.IDENTITY,
                    frame_range=(0, 0),
                    severity=0.5,
                    description=f"Identity check error: {str(e)}",
                )],
                score=None,
                recommendation="manual_review",
                details={"error": str(e)},
                execution_time_sec=time.time() - start_time,
            )
        finally:
            # Clean up temp files
            await self._cleanup_temp_frames()
    
    async def _run_physics_check(
        self,
        request: ReviewRequest,
    ) -> CheckResult:
        """Run physics check on the video."""
        start_time = time.time()
        
        try:
            # Run analysis
            analysis: PhysicsAnalysis = await self.physics_checker.analyze_video(
                video_path=request.video_path,
            )
            
            # Convert violations to AuditFlags
            flags = []
            for violation in analysis.violations:
                flags.append(AuditFlag(
                    check_type=AuditCheckType.PHYSICS,
                    frame_range=violation.frame_range,
                    severity=violation.severity,
                    description=violation.description,
                ))
            
            return CheckResult(
                check_type=CheckType.PHYSICS,
                passed=analysis.passed,
                severity=analysis.max_severity,
                flags=flags,
                score=1.0 - analysis.max_severity if analysis.passed else 0.0,
                recommendation=analysis.to_audit_recommendation(),
                details=analysis.to_dict(),
                execution_time_sec=time.time() - start_time,
            )
            
        except Exception as e:
            logger.error(f"Physics check failed: {e}")
            return CheckResult(
                check_type=CheckType.PHYSICS,
                passed=False,
                severity=0.5,
                flags=[AuditFlag(
                    check_type=AuditCheckType.PHYSICS,
                    frame_range=(0, 0),
                    severity=0.5,
                    description=f"Physics check error: {str(e)}",
                )],
                score=None,
                recommendation="manual_review",
                details={"error": str(e)},
                execution_time_sec=time.time() - start_time,
            )
    
    async def _get_identity_frames(
        self,
        request: ReviewRequest,
    ) -> Tuple[Path, Path]:
        """
        Extract frames for identity comparison.
        
        Returns paths to temporary frame files.
        """
        # If reference frame provided, use it as source
        if request.reference_frame and request.reference_frame.exists():
            source_frame = request.reference_frame
            target_frame = await self._extract_frame(request.video_path, frame_index=0)
            return (source_frame, target_frame)
        
        # Cross-shot: compare last frame of previous to first frame of current
        if request.mode == AuditMode.CROSS_SHOT and request.previous_shot_path:
            source_frame = await self._extract_frame(
                request.previous_shot_path,
                frame_index=-1,  # Last frame
            )
            target_frame = await self._extract_frame(
                request.video_path,
                frame_index=0,  # First frame
            )
            return (source_frame, target_frame)
        
        # Within-shot: compare first to last frame
        source_frame = await self._extract_frame(request.video_path, frame_index=0)
        target_frame = await self._extract_frame(request.video_path, frame_index=-1)
        
        return (source_frame, target_frame)
    
    async def _extract_frame(
        self,
        video_path: Path,
        frame_index: int = 0,
    ) -> Path:
        """
        Extract a single frame from video.
        
        Args:
            video_path: Path to video
            frame_index: Frame to extract (0 = first, -1 = last)
            
        Returns:
            Path to temporary frame file
        """
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            raise FrameExtractionError(f"Could not open video: {video_path}")
        
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames == 0:
                raise FrameExtractionError(f"Video has no frames: {video_path}")
            
            # Handle negative index
            if frame_index < 0:
                frame_index = total_frames + frame_index
            
            # Seek to frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            
            ret, frame = cap.read()
            if not ret:
                raise FrameExtractionError(
                    f"Could not read frame {frame_index} from {video_path}"
                )
            
            # Save to temp file
            temp_dir = Path(tempfile.gettempdir()) / "continuum_reviewer"
            temp_dir.mkdir(exist_ok=True)
            
            temp_path = temp_dir / f"frame_{video_path.stem}_{frame_index}_{time.time():.0f}.jpg"
            cv2.imwrite(str(temp_path), frame)
            
            # Track for cleanup
            if not hasattr(self, '_temp_frames'):
                self._temp_frames = []
            self._temp_frames.append(temp_path)
            
            return temp_path
            
        finally:
            cap.release()
    
    async def _cleanup_temp_frames(self):
        """Clean up temporary frame files."""
        if hasattr(self, '_temp_frames'):
            for path in self._temp_frames:
                try:
                    if path.exists():
                        path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp frame {path}: {e}")
            self._temp_frames = []
    
    def _aggregate_results(
        self,
        check_results: List[CheckResult],
    ) -> AuditResult:
        """
        Aggregate multiple check results into a single AuditResult.
        
        Uses weighted severity to determine final status.
        """
        if not check_results:
            # No checks run, auto-pass
            return AuditResult.passed(identity_score=1.0)
        
        # Collect all flags
        all_flags: List[AuditFlag] = []
        for result in check_results:
            all_flags.extend(result.flags)
        
        # Calculate weighted severity
        total_weight = 0.0
        weighted_severity = 0.0
        identity_score = None
        
        for result in check_results:
            if result.check_type == CheckType.IDENTITY:
                weight = self.identity_weight
                identity_score = result.score
            elif result.check_type == CheckType.PHYSICS:
                weight = self.physics_weight
            else:
                weight = 0.5  # Default weight for unknown checks
            
            weighted_severity += result.severity * weight
            total_weight += weight
        
        # Normalize
        if total_weight > 0:
            weighted_severity /= total_weight
        
        # Determine status and recommendation
        if weighted_severity >= self.fail_threshold:
            status = AuditStatus.FAIL
            recommendation = "reroll"
        elif weighted_severity >= self.warn_threshold:
            status = AuditStatus.WARN
            # Check if any individual check recommends human review
            has_review_recommendation = any(
                cr.recommendation == "manual_review" for cr in check_results
            )
            recommendation = "manual_review" if has_review_recommendation else "reroll"
        else:
            status = AuditStatus.PASS
            recommendation = "approve"
        
        # Override if all checks passed but we have warnings
        all_passed = all(cr.passed for cr in check_results)
        if all_passed and status != AuditStatus.PASS:
            # Checks passed but severity calculation suggests otherwise
            # Trust the individual checks
            status = AuditStatus.PASS
            recommendation = "approve"
        
        logger.debug(
            f"Aggregated {len(check_results)} checks: "
            f"weighted_severity={weighted_severity:.3f} â†’ {status.value}"
        )
        
        return AuditResult(
            status=status,
            flags=tuple(all_flags),
            identity_score=identity_score,
            recommendation=recommendation,
        )
    
    async def health_check(self) -> Dict[str, bool]:
        """
        Check health of all sub-checkers.
        
        Returns:
            Dict mapping checker name to health status
        """
        results = {}
        
        try:
            results["identity"] = await self.identity_checker.health_check()
        except Exception as e:
            logger.warning(f"Identity checker health check failed: {e}")
            results["identity"] = False
        
        try:
            results["physics"] = await self.physics_checker.health_check()
        except Exception as e:
            logger.warning(f"Physics checker health check failed: {e}")
            results["physics"] = False
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get reviewer statistics."""
        return {
            "reviews_performed": self._reviews_performed,
            "total_review_time_sec": self._total_review_time,
            "avg_review_time_sec": (
                self._total_review_time / self._reviews_performed
                if self._reviews_performed > 0 else 0.0
            ),
        }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_reviewer(
    use_mock: bool = False,
    config: Optional[AuditConfig] = None,
    **kwargs,
) -> Reviewer:
    """
    Factory function to create a Reviewer.
    
    Args:
        use_mock: If True, use mock checkers (for testing)
        config: Audit configuration
        **kwargs: Passed to Reviewer constructor
        
    Returns:
        Configured Reviewer instance
    """
    if use_mock:
        from .identity_checker import MockIdentityChecker
        from .physics_checker import MockPhysicsChecker
        
        return Reviewer(
            identity_checker=MockIdentityChecker(),
            physics_checker=MockPhysicsChecker(),
            config=config,
            **kwargs,
        )
    
    return Reviewer(config=config, **kwargs)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def quick_review(
    video_path: Path,
    shot_id: str = "unknown",
) -> Tuple[bool, str]:
    """
    Quick review for simple use cases.
    
    Args:
        video_path: Path to video chunk
        shot_id: Identifier for logging
        
    Returns:
        Tuple of (passed: bool, recommendation: str)
    
    Usage:
        passed, action = await quick_review(Path("chunk.mp4"))
        if not passed:
            if action == "reroll":
                # Re-generate
            else:
                # Manual review needed
    """
    reviewer = get_reviewer()
    result = await reviewer.review(ReviewRequest(
        video_path=video_path,
        shot_id=shot_id,
    ))
    
    return (result.passed, result.audit_result.recommendation)


async def review_bridge_transition(
    shot_a_path: Path,
    shot_b_path: Path,
    bridge_frame_path: Optional[Path] = None,
) -> ReviewResult:
    """
    Review a bridge transition between two shots.
    
    Verifies that:
    1. Identity is preserved across the bridge
    2. Physics are consistent
    
    Args:
        shot_a_path: Video before bridge
        shot_b_path: Video after bridge
        bridge_frame_path: Optional bridge frame for additional verification
        
    Returns:
        ReviewResult for the transition
    """
    reviewer = get_reviewer()
    
    result = await reviewer.review(ReviewRequest(
        video_path=shot_b_path,
        previous_shot_path=shot_a_path,
        reference_frame=bridge_frame_path,
        shot_id=f"bridge_{shot_a_path.stem}_to_{shot_b_path.stem}",
    ))
    
    return result