"""
Continuum Engine - Job State Definitions

This module defines the core state enums and dataclasses used throughout
the pipeline. These are the "vocabulary" of job tracking.

Design Principles:
1. Immutable where possible (frozen dataclasses)
2. JSON-serializable for checkpointing
3. Type-safe with explicit enums (no magic strings)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Any, Dict
import json


# =============================================================================
# ENUMS - The vocabulary of job states
# =============================================================================

class JobStatus(str, Enum):
    """
    Lifecycle states for a generation job (shot or chunk).
    
    Flow:
        PENDING → GENERATING → AUDITING → APPROVED → REFINING → COMPLETE
                                    ↓
                                 FAILED (after max retries)
    
    Using (str, Enum) mixin for JSON serialization:
        json.dumps({"status": JobStatus.PENDING})  # Works without custom encoder
    """
    PENDING = "pending"          # Queued, waiting to start
    GENERATING = "generating"    # Pass 1 in progress
    AUDITING = "auditing"        # QA checks running
    FAILED = "failed"            # Max retries exceeded, needs human
    APPROVED = "approved"        # QA passed, ready for refinement
    REFINING = "refining"        # Pass 2 in progress
    COMPLETE = "complete"        # Final output ready


class AuditStatus(str, Enum):
    """
    Result of a QA audit on a generated chunk.
    
    PASS: All checks passed, proceed to next stage
    FAIL: One or more checks failed, trigger re-roll
    WARN: Borderline results, flag for optional human review
    """
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class AuditCheckType(str, Enum):
    """
    Types of QA checks performed by the audit engine.
    
    Explicit enum prevents typos like "identty" vs "identity".
    """
    IDENTITY = "identity"        # ArcFace face similarity
    PHYSICS = "physics"          # Object permanence, gravity
    FLICKER = "flicker"          # Temporal consistency (RAFT)
    SCENE = "scene"              # CLIP embedding drift


# =============================================================================
# DATACLASSES - Structured data containers
# =============================================================================

@dataclass(frozen=True)
class AuditFlag:
    """
    A single issue detected during QA.
    
    Frozen (immutable) because audit results shouldn't change after creation.
    
    Attributes:
        check_type: Which audit check raised this flag
        frame_range: (start_frame, end_frame) where issue occurs
        severity: 0.0 (minor) to 1.0 (critical)
        description: Human-readable explanation
    """
    check_type: AuditCheckType
    frame_range: tuple[int, int]
    severity: float
    description: str
    
    def __post_init__(self):
        """Validate severity is in range."""
        if not 0.0 <= self.severity <= 1.0:
            raise ValueError(f"Severity must be 0.0-1.0, got {self.severity}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "check_type": self.check_type.value,
            "frame_range": list(self.frame_range),
            "severity": self.severity,
            "description": self.description
        }


@dataclass(frozen=True)
class AuditResult:
    """
    Complete result of auditing a generated chunk.
    
    Attributes:
        status: Overall PASS/FAIL/WARN
        flags: List of specific issues found
        identity_score: ArcFace similarity (0.0-1.0), None if not checked
        recommendation: Suggested action ("approve", "reroll", "manual_review")
    """
    status: AuditStatus
    flags: tuple[AuditFlag, ...]  # Tuple for immutability
    identity_score: Optional[float]
    recommendation: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status.value,
            "flags": [f.to_dict() for f in self.flags],
            "identity_score": self.identity_score,
            "recommendation": self.recommendation
        }
    
    @classmethod
    def passed(cls, identity_score: float = 1.0) -> "AuditResult":
        """Factory for a clean pass result."""
        return cls(
            status=AuditStatus.PASS,
            flags=tuple(),
            identity_score=identity_score,
            recommendation="approve"
        )
    
    @classmethod
    def failed(cls, flags: List[AuditFlag], identity_score: Optional[float] = None) -> "AuditResult":
        """Factory for a failed result."""
        return cls(
            status=AuditStatus.FAIL,
            flags=tuple(flags),
            identity_score=identity_score,
            recommendation="reroll"
        )


@dataclass
class JobCheckpoint:
    """
    Persistent state for a generation job, used for crash recovery.
    
    NOT frozen because status changes during job lifecycle.
    
    Attributes:
        job_id: Unique identifier (e.g., "film_001_scene_02_shot_05")
        shot_id: Reference to the shot being generated
        status: Current lifecycle state
        attempt: Current retry attempt (1-indexed, max typically 3)
        rendered_path: Path to output video if generation succeeded
        audit_result: QA results if auditing completed
        created_at: When job was created
        updated_at: Last state change timestamp
        metadata: Flexible dict for renderer-specific data
    """
    job_id: str
    shot_id: str
    status: JobStatus = JobStatus.PENDING
    attempt: int = 1
    rendered_path: Optional[Path] = None
    audit_result: Optional[AuditResult] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Class constant for max retries (can be overridden in config)
    MAX_ATTEMPTS: int = 3
    
    def update_status(self, new_status: JobStatus) -> None:
        """
        Update status and timestamp.
        
        Centralizing this ensures updated_at is always refreshed.
        """
        self.status = new_status
        self.updated_at = datetime.utcnow()
    
    def can_retry(self) -> bool:
        """Check if we haven't exceeded max retry attempts."""
        return self.attempt < self.MAX_ATTEMPTS
    
    def increment_attempt(self) -> None:
        """Bump attempt counter for re-roll."""
        self.attempt += 1
        self.updated_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for persistence."""
        return {
            "job_id": self.job_id,
            "shot_id": self.shot_id,
            "status": self.status.value,
            "attempt": self.attempt,
            "rendered_path": str(self.rendered_path) if self.rendered_path else None,
            "audit_result": self.audit_result.to_dict() if self.audit_result else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }
    
    def save(self, checkpoint_dir: Path) -> Path:
        """
        Persist checkpoint to disk.
        
        Args:
            checkpoint_dir: Directory to save checkpoints
            
        Returns:
            Path to saved checkpoint file
        """
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        filepath = checkpoint_dir / f"{self.job_id}.json"
        
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        
        return filepath
    
    @classmethod
    def load(cls, job_id: str, checkpoint_dir: Path) -> Optional["JobCheckpoint"]:
        """
        Load checkpoint from disk.
        
        Args:
            job_id: ID of job to load
            checkpoint_dir: Directory containing checkpoints
            
        Returns:
            JobCheckpoint if found, None otherwise
        """
        filepath = checkpoint_dir / f"{job_id}.json"
        
        if not filepath.exists():
            return None
        
        with open(filepath, "r") as f:
            data = json.load(f)
        
        # Reconstruct audit result if present
        audit_result = None
        if data.get("audit_result"):
            ar = data["audit_result"]
            flags = tuple(
                AuditFlag(
                    check_type=AuditCheckType(f["check_type"]),
                    frame_range=tuple(f["frame_range"]),
                    severity=f["severity"],
                    description=f["description"]
                )
                for f in ar["flags"]
            )
            audit_result = AuditResult(
                status=AuditStatus(ar["status"]),
                flags=flags,
                identity_score=ar["identity_score"],
                recommendation=ar["recommendation"]
            )
        
        return cls(
            job_id=data["job_id"],
            shot_id=data["shot_id"],
            status=JobStatus(data["status"]),
            attempt=data["attempt"],
            rendered_path=Path(data["rendered_path"]) if data["rendered_path"] else None,
            audit_result=audit_result,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {})
        )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def is_terminal_status(status: JobStatus) -> bool:
    """
    Check if a status represents a terminal (end) state.
    
    Terminal states: FAILED, COMPLETE
    Non-terminal: Everything else (job still in progress)
    """
    return status in (JobStatus.FAILED, JobStatus.COMPLETE)


def is_success_status(status: JobStatus) -> bool:
    """Check if status represents successful completion."""
    return status == JobStatus.COMPLETE