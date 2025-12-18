"""
Continuum Engine - Checkpoint Manager

Handles persistence and recovery of job state. If the system crashes mid-render,
we resume from the last checkpoint, not from scratch.

Design Principles:
1. Atomic writes (temp file + rename) — no corrupted checkpoints
2. Index file tracks all active jobs — fast enumeration without scanning
3. Cleanup policies — don't accumulate GB of old checkpoints
4. S3 backup support — optional redundancy for critical jobs
"""

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Iterator
from contextlib import contextmanager
import logging
import threading

from .job_state import JobCheckpoint, JobStatus, is_terminal_status

logger = logging.getLogger(__name__)


# =============================================================================
# CHECKPOINT MANAGER
# =============================================================================

class CheckpointManager:
    """
    Manages job checkpoint persistence with atomic writes and cleanup.
    
    Usage:
        manager = CheckpointManager(Path("./workspace/checkpoints"))
        
        # Save a checkpoint
        manager.save(job_checkpoint)
        
        # Load a checkpoint
        job = manager.load("job_123")
        
        # Resume all incomplete jobs after crash
        for job in manager.get_incomplete_jobs():
            pipeline.resume(job)
        
        # Cleanup old completed jobs
        manager.cleanup(max_age_days=7, keep_failed=True)
    """
    
    # Filename for the index that tracks all checkpoints
    INDEX_FILENAME = "_checkpoint_index.json"
    
    def __init__(
        self,
        checkpoint_dir: Path,
        s3_client: Optional[object] = None,  # boto3 client, typed as object to avoid import
        s3_bucket: Optional[str] = None,
        s3_prefix: str = "checkpoints/"
    ):
        """
        Initialize the checkpoint manager.
        
        Args:
            checkpoint_dir: Local directory for checkpoint files
            s3_client: Optional boto3 S3 client for backup
            s3_bucket: S3 bucket name if using backup
            s3_prefix: S3 key prefix for checkpoint files
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        
        # Thread lock for index operations
        self._lock = threading.Lock()
        
        # Ensure index exists
        self._init_index()
    
    # -------------------------------------------------------------------------
    # CORE OPERATIONS
    # -------------------------------------------------------------------------
    
    def save(self, checkpoint: JobCheckpoint, backup_to_s3: bool = False) -> Path:
        """
        Save a checkpoint atomically.
        
        Uses write-to-temp-then-rename pattern to prevent corruption
        if the process is killed mid-write.
        
        Args:
            checkpoint: The job checkpoint to save
            backup_to_s3: Whether to also upload to S3
            
        Returns:
            Path to the saved checkpoint file
        """
        filepath = self._checkpoint_path(checkpoint.job_id)
        
        # Write to temp file first
        with self._atomic_write(filepath) as tmp_path:
            with open(tmp_path, "w") as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
        
        # Update index
        self._update_index(checkpoint.job_id, checkpoint.status, checkpoint.updated_at)
        
        # Optional S3 backup
        if backup_to_s3 and self.s3_client and self.s3_bucket:
            self._backup_to_s3(filepath, checkpoint.job_id)
        
        logger.debug(f"Saved checkpoint: {checkpoint.job_id} (status={checkpoint.status.value})")
        return filepath
    
    def load(self, job_id: str, fallback_to_s3: bool = False) -> Optional[JobCheckpoint]:
        """
        Load a checkpoint by job ID.
        
        Args:
            job_id: The job ID to load
            fallback_to_s3: If local file missing, try S3
            
        Returns:
            JobCheckpoint if found, None otherwise
        """
        filepath = self._checkpoint_path(job_id)
        
        # Try local first
        if filepath.exists():
            return self._load_from_file(filepath)
        
        # Fallback to S3 if enabled
        if fallback_to_s3 and self.s3_client and self.s3_bucket:
            logger.info(f"Local checkpoint missing, trying S3: {job_id}")
            if self._restore_from_s3(job_id):
                return self._load_from_file(filepath)
        
        return None
    
    def delete(self, job_id: str, delete_from_s3: bool = False) -> bool:
        """
        Delete a checkpoint.
        
        Args:
            job_id: The job ID to delete
            delete_from_s3: Also delete from S3 backup
            
        Returns:
            True if deleted, False if not found
        """
        filepath = self._checkpoint_path(job_id)
        
        deleted = False
        if filepath.exists():
            filepath.unlink()
            deleted = True
            logger.debug(f"Deleted checkpoint: {job_id}")
        
        # Remove from index
        self._remove_from_index(job_id)
        
        # Delete from S3 if requested
        if delete_from_s3 and self.s3_client and self.s3_bucket:
            self._delete_from_s3(job_id)
        
        return deleted
    
    def exists(self, job_id: str) -> bool:
        """Check if a checkpoint exists."""
        return self._checkpoint_path(job_id).exists()
    
    # -------------------------------------------------------------------------
    # ENUMERATION & QUERYING
    # -------------------------------------------------------------------------
    
    def get_all_jobs(self) -> List[JobCheckpoint]:
        """Load all checkpoints (can be slow for many jobs)."""
        checkpoints = []
        for filepath in self.checkpoint_dir.glob("*.json"):
            if filepath.name == self.INDEX_FILENAME:
                continue
            checkpoint = self._load_from_file(filepath)
            if checkpoint:
                checkpoints.append(checkpoint)
        return checkpoints
    
    def get_incomplete_jobs(self) -> Iterator[JobCheckpoint]:
        """
        Yield all jobs that are not in a terminal state.
        
        Used after crash recovery to resume work.
        """
        index = self._load_index()
        for job_id, entry in index.items():
            status = JobStatus(entry["status"])
            if not is_terminal_status(status):
                checkpoint = self.load(job_id)
                if checkpoint:
                    yield checkpoint
    
    def get_jobs_by_status(self, status: JobStatus) -> Iterator[JobCheckpoint]:
        """Yield all jobs with a specific status."""
        index = self._load_index()
        for job_id, entry in index.items():
            if entry["status"] == status.value:
                checkpoint = self.load(job_id)
                if checkpoint:
                    yield checkpoint
    
    def get_failed_jobs(self) -> Iterator[JobCheckpoint]:
        """Yield all failed jobs (convenience method)."""
        return self.get_jobs_by_status(JobStatus.FAILED)
    
    def get_completed_scenes(self) -> set:
        """Get set of completed scene IDs."""
        completed = set()
        for job in self.get_all_jobs():
            if job.status == JobStatus.COMPLETE and job.scene_id:
                completed.add(job.scene_id)
        return completed

    def mark_scene_complete(self, scene_id: str) -> None:
        """Mark a scene as complete."""
        # For now, just log - actual implementation would update persistent state
        logger.info(f"Scene {scene_id} marked complete")
    
    def count_by_status(self) -> Dict[str, int]:
        """Get count of jobs per status (fast, uses index)."""
        index = self._load_index()
        counts: Dict[str, int] = {}
        for entry in index.values():
            status = entry["status"]
            counts[status] = counts.get(status, 0) + 1
        return counts
    
    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------
    
    def cleanup(
        self,
        max_age_days: Optional[int] = None,
        max_count: Optional[int] = None,
        keep_failed: bool = True,
        keep_incomplete: bool = True,
        dry_run: bool = False
    ) -> List[str]:
        """
        Clean up old checkpoints based on policies.
        
        Args:
            max_age_days: Delete checkpoints older than this (by updated_at)
            max_count: Keep only the N most recent completed checkpoints
            keep_failed: Don't delete failed jobs (for debugging)
            keep_incomplete: Don't delete jobs still in progress
            dry_run: Return what would be deleted without actually deleting
            
        Returns:
            List of job IDs that were (or would be) deleted
        """
        to_delete: List[str] = []
        index = self._load_index()
        
        # Build list of candidates
        candidates = []
        for job_id, entry in index.items():
            status = JobStatus(entry["status"])
            updated_at = datetime.fromisoformat(entry["updated_at"])
            
            # Skip based on keep policies
            if keep_failed and status == JobStatus.FAILED:
                continue
            if keep_incomplete and not is_terminal_status(status):
                continue
            
            candidates.append((job_id, status, updated_at))
        
        # Sort by updated_at (oldest first)
        candidates.sort(key=lambda x: x[2])
        
        now = datetime.utcnow()
        
        # Apply max_age policy
        if max_age_days is not None:
            cutoff = now - timedelta(days=max_age_days)
            for job_id, status, updated_at in candidates:
                if updated_at < cutoff:
                    to_delete.append(job_id)
        
        # Apply max_count policy (only to completed jobs)
        if max_count is not None:
            completed = [
                (job_id, updated_at) 
                for job_id, status, updated_at in candidates
                if status == JobStatus.COMPLETE and job_id not in to_delete
            ]
            if len(completed) > max_count:
                # Delete oldest ones beyond the limit
                completed.sort(key=lambda x: x[1])  # Oldest first
                excess = completed[:-max_count]  # All but the newest max_count
                to_delete.extend(job_id for job_id, _ in excess)
        
        # Deduplicate
        to_delete = list(set(to_delete))
        
        # Execute deletion
        if not dry_run:
            for job_id in to_delete:
                self.delete(job_id)
            logger.info(f"Cleanup: deleted {len(to_delete)} checkpoints")
        else:
            logger.info(f"Cleanup (dry run): would delete {len(to_delete)} checkpoints")
        
        return to_delete
    
    def clear_all(self, confirm: bool = False) -> int:
        """
        Delete ALL checkpoints. Use with caution.
        
        Args:
            confirm: Must be True to actually delete
            
        Returns:
            Number of checkpoints deleted
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to clear all checkpoints")
        
        count = 0
        for filepath in self.checkpoint_dir.glob("*.json"):
            if filepath.name != self.INDEX_FILENAME:
                filepath.unlink()
                count += 1
        
        # Reset index
        self._save_index({})
        
        logger.warning(f"Cleared all checkpoints: {count} deleted")
        return count
    
    # -------------------------------------------------------------------------
    # INDEX MANAGEMENT
    # -------------------------------------------------------------------------
    
    def _init_index(self) -> None:
        """Ensure index file exists."""
        index_path = self.checkpoint_dir / self.INDEX_FILENAME
        if not index_path.exists():
            self._save_index({})
    
    def _load_index(self) -> Dict[str, Dict]:
        """Load the checkpoint index."""
        index_path = self.checkpoint_dir / self.INDEX_FILENAME
        try:
            with open(index_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _save_index(self, index: Dict[str, Dict]) -> None:
        """Save the checkpoint index atomically."""
        index_path = self.checkpoint_dir / self.INDEX_FILENAME
        with self._atomic_write(index_path) as tmp_path:
            with open(tmp_path, "w") as f:
                json.dump(index, f, indent=2)
    
    def _update_index(self, job_id: str, status: JobStatus, updated_at: datetime) -> None:
        """Update a single entry in the index."""
        with self._lock:
            index = self._load_index()
            index[job_id] = {
                "status": status.value,
                "updated_at": updated_at.isoformat()
            }
            self._save_index(index)
    
    def _remove_from_index(self, job_id: str) -> None:
        """Remove an entry from the index."""
        with self._lock:
            index = self._load_index()
            if job_id in index:
                del index[job_id]
                self._save_index(index)
    
    def rebuild_index(self) -> int:
        """
        Rebuild index from checkpoint files on disk.
        
        Use if index gets corrupted or out of sync.
        
        Returns:
            Number of checkpoints indexed
        """
        logger.info("Rebuilding checkpoint index from disk...")
        index = {}
        
        for filepath in self.checkpoint_dir.glob("*.json"):
            if filepath.name == self.INDEX_FILENAME:
                continue
            
            checkpoint = self._load_from_file(filepath)
            if checkpoint:
                index[checkpoint.job_id] = {
                    "status": checkpoint.status.value,
                    "updated_at": checkpoint.updated_at.isoformat()
                }
        
        self._save_index(index)
        logger.info(f"Index rebuilt: {len(index)} checkpoints")
        return len(index)
    
    # -------------------------------------------------------------------------
    # S3 BACKUP
    # -------------------------------------------------------------------------
    
    def _backup_to_s3(self, filepath: Path, job_id: str) -> bool:
        """Upload checkpoint to S3."""
        if not self.s3_client or not self.s3_bucket:
            return False
        
        try:
            s3_key = f"{self.s3_prefix}{job_id}.json"
            self.s3_client.upload_file(str(filepath), self.s3_bucket, s3_key)
            logger.debug(f"Backed up to S3: {s3_key}")
            return True
        except Exception as e:
            logger.warning(f"S3 backup failed for {job_id}: {e}")
            return False
    
    def _restore_from_s3(self, job_id: str) -> bool:
        """Download checkpoint from S3 to local."""
        if not self.s3_client or not self.s3_bucket:
            return False
        
        try:
            s3_key = f"{self.s3_prefix}{job_id}.json"
            filepath = self._checkpoint_path(job_id)
            self.s3_client.download_file(self.s3_bucket, s3_key, str(filepath))
            logger.info(f"Restored from S3: {job_id}")
            return True
        except Exception as e:
            logger.debug(f"S3 restore failed for {job_id}: {e}")
            return False
    
    def _delete_from_s3(self, job_id: str) -> bool:
        """Delete checkpoint from S3."""
        if not self.s3_client or not self.s3_bucket:
            return False
        
        try:
            s3_key = f"{self.s3_prefix}{job_id}.json"
            self.s3_client.delete_object(Bucket=self.s3_bucket, Key=s3_key)
            logger.debug(f"Deleted from S3: {s3_key}")
            return True
        except Exception as e:
            logger.warning(f"S3 delete failed for {job_id}: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    
    def _checkpoint_path(self, job_id: str) -> Path:
        """Get the filesystem path for a checkpoint."""
        # Sanitize job_id for filesystem safety
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
        return self.checkpoint_dir / f"{safe_id}.json"
    
    def _load_from_file(self, filepath: Path) -> Optional[JobCheckpoint]:
        """Load a checkpoint from a specific file."""
        try:
            return JobCheckpoint.load(filepath.stem, filepath.parent)
        except Exception as e:
            logger.error(f"Failed to load checkpoint {filepath}: {e}")
            return None
    
    @contextmanager
    def _atomic_write(self, target_path: Path):
        """
        Context manager for atomic file writes.
        
        Writes to a temp file, then renames to target.
        If anything fails, temp file is cleaned up.
        
        Usage:
            with self._atomic_write(Path("output.json")) as tmp:
                with open(tmp, "w") as f:
                    f.write(data)
            # File is now atomically moved to output.json
        """
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self.checkpoint_dir,
            prefix=".tmp_",
            suffix=".json"
        )
        tmp_path = Path(tmp_path)
        
        try:
            # Close the file descriptor (we'll reopen by path)
            import os
            os.close(tmp_fd)
            
            yield tmp_path
            
            # Atomic rename (on POSIX systems)
            shutil.move(str(tmp_path), str(target_path))
            
        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                tmp_path.unlink()
            raise


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_checkpoint_manager() -> CheckpointManager:
    """
    Get a CheckpointManager using paths from global config.
    
    Usage:
        from continuum.src.core.checkpointing import get_checkpoint_manager
        manager = get_checkpoint_manager()
    """
    from .config import get_config
    config = get_config()
    
    # TODO: Add S3 client initialization when AWS is configured
    s3_client = None
    if config.has_api_key("aws") and config.s3_bucket:
        try:
            import boto3
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=config.get_secret("aws_access_key_id"),
                aws_secret_access_key=config.get_secret("aws_secret_access_key"),
                region_name=config.s3_region
            )
        except ImportError:
            logger.warning("boto3 not installed, S3 backup disabled")
    
    return CheckpointManager(
        checkpoint_dir=config.paths.checkpoint_dir,
        s3_client=s3_client,
        s3_bucket=config.s3_bucket,
        s3_prefix="checkpoints/"
    )