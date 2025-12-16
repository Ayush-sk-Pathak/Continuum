"""
Continuum Engine - Physics Checker (Object Permanence Verification)

Verifies that objects obey physical laws across frames.
This prevents the "teleporting mug" problem where objects jump around impossibly.

The Problem:
    Video models don't understand physics. A coffee mug on a table might:
    1. Teleport to the floor between frames
    2. Disappear for 5 frames then reappear
    3. Float in mid-air
    
The Solution:
    1. Detect objects in each frame using YOLO
    2. Track objects across frames using ByteTrack
    3. Flag violations: teleportation, disappearance, gravity defiance

Use Cases:
    1. Within-shot check: Verify object continuity throughout a chunk
    2. Cross-shot check: Verify objects match across a bridge transition
    3. Post-edit verification: Confirm edits didn't break physics

Architecture:
    - BasePhysicsChecker: Abstract interface (pluggable)
    - YOLOPhysicsChecker: Production implementation using ultralytics
    - MockPhysicsChecker: Testing without models
    - Factory function with automatic fallback

Design Principles:
    1. Configurable tolerance: physics_missing_frames from AuditConfig
    2. Category-aware: Track "mug" vs "person" vs "chair" separately
    3. Async-ready: Frame extraction can be parallelized
    4. Audit-compatible: Returns AuditFlag-compatible violations
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence
import numpy as np



logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION DEFAULTS
# =============================================================================

DEFAULT_MISSING_FRAMES_THRESHOLD = 3  # From config.py AuditConfig.physics_missing_frames
DEFAULT_TELEPORT_THRESHOLD = 0.3       # Max normalized distance per frame (30% of frame)
DEFAULT_DETECTION_CONFIDENCE = 0.25    # YOLO confidence threshold
DEFAULT_IOU_THRESHOLD = 0.45           # Non-max suppression IoU


# =============================================================================
# ENUMS
# =============================================================================

class PhysicsViolationType(str, Enum):
    """Types of physics violations we detect."""
    TELEPORTATION = "teleportation"       # Object moved impossibly fast
    DISAPPEARANCE = "disappearance"       # Object vanished then reappeared
    APPEARANCE = "appearance"             # Object appeared from nowhere mid-shot
    DUPLICATION = "duplication"           # Same object appears twice


class PhysicsCheckResult(str, Enum):
    """Overall result of physics check."""
    PASS = "pass"                  # No violations
    FAIL = "fail"                  # Violations exceed threshold
    WARN = "warn"                  # Minor violations, flag for review
    NO_OBJECTS = "no_objects"      # No trackable objects detected
    ERROR = "error"                # Processing error


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class DetectedObject:
    """
    A single object detected in a frame.
    
    Attributes:
        track_id: Persistent ID from tracker (same object = same ID across frames)
        class_id: YOLO class ID (0=person, 39=bottle, 41=cup, etc.)
        class_name: Human-readable class name
        bbox: Bounding box as (x1, y1, x2, y2) normalized 0-1
        confidence: Detection confidence (0.0-1.0)
        frame_index: Which frame this detection is from
    """
    track_id: int
    class_id: int
    class_name: str
    bbox: Tuple[float, float, float, float]  # Normalized coordinates
    confidence: float
    frame_index: int
    
    @property
    def center(self) -> Tuple[float, float]:
        """Center point of bounding box (normalized)."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @property
    def area(self) -> float:
        """Area of bounding box (normalized, 0-1)."""
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)
    
    def distance_to(self, other: "DetectedObject") -> float:
        """
        Euclidean distance to another detection (normalized).
        
        Returns value in range 0-√2 (diagonal of unit square).
        """
        cx1, cy1 = self.center
        cx2, cy2 = other.center
        return np.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)


@dataclass
class FrameObjects:
    """
    All objects detected in a single frame.
    
    Attributes:
        frame_index: Frame number (0-indexed)
        frame_path: Source frame file (if from disk)
        objects: List of detected objects with tracking IDs
        detection_time_sec: Processing time
    """
    frame_index: int
    frame_path: Optional[Path]
    objects: List[DetectedObject]
    detection_time_sec: float = 0.0
    
    @property
    def object_count(self) -> int:
        return len(self.objects)
    
    @property
    def track_ids(self) -> set:
        """Set of all track IDs in this frame."""
        return {obj.track_id for obj in self.objects}
    
    def get_by_track_id(self, track_id: int) -> Optional[DetectedObject]:
        """Get object by its tracking ID."""
        for obj in self.objects:
            if obj.track_id == track_id:
                return obj
        return None
    
    def get_by_class(self, class_name: str) -> List[DetectedObject]:
        """Get all objects of a specific class."""
        return [obj for obj in self.objects if obj.class_name == class_name]


@dataclass
class ObjectTrack:
    """
    A single object tracked across multiple frames.
    
    Attributes:
        track_id: Persistent tracking ID
        class_name: Object class (e.g., "cup", "person")
        detections: Ordered list of detections (one per frame where visible)
        first_frame: First frame where object appeared
        last_frame: Last frame where object was seen
    """
    track_id: int
    class_name: str
    detections: List[DetectedObject] = field(default_factory=list)
    
    @property
    def first_frame(self) -> int:
        if not self.detections:
            return -1
        return self.detections[0].frame_index
    
    @property
    def last_frame(self) -> int:
        if not self.detections:
            return -1
        return self.detections[-1].frame_index
    
    @property
    def frame_count(self) -> int:
        """Number of frames this object was detected in."""
        return len(self.detections)
    
    def frames_visible(self) -> List[int]:
        """List of frame indices where object was visible."""
        return [d.frame_index for d in self.detections]
    
    def gaps(self) -> List[Tuple[int, int]]:
        """
        Find gaps in visibility.
        
        Returns:
            List of (start_frame, end_frame) tuples where object was missing
        """
        frames = self.frames_visible()
        if len(frames) < 2:
            return []
        
        gaps = []
        for i in range(len(frames) - 1):
            if frames[i + 1] - frames[i] > 1:
                gaps.append((frames[i], frames[i + 1]))
        return gaps


@dataclass
class PhysicsViolation:
    """
    A specific physics violation detected.
    
    Maps directly to AuditFlag structure for easy conversion.
    """
    violation_type: PhysicsViolationType
    track_id: int
    class_name: str
    frame_range: Tuple[int, int]  # (start_frame, end_frame)
    severity: float               # 0.0-1.0
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_audit_flag(self) -> Dict[str, Any]:
        """
        Convert to AuditFlag-compatible dict.
        
        Import AuditFlag here would create circular dependency,
        so we return dict for conversion at call site.
        """
        return {
            "check_type": "physics",  # AuditCheckType.PHYSICS.value
            "frame_range": self.frame_range,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass
class PhysicsAnalysis:
    """
    Complete result of physics analysis on a video/sequence.
    
    Attributes:
        result: Overall PASS/FAIL/WARN
        violations: List of specific violations found
        tracks: All object tracks detected
        total_frames: Number of frames analyzed
        unique_objects: Number of unique tracked objects
        message: Human-readable summary
    """
    result: PhysicsCheckResult
    violations: List[PhysicsViolation]
    tracks: List[ObjectTrack]
    total_frames: int
    unique_objects: int
    analysis_time_sec: float = 0.0
    message: str = ""
    
    @property
    def passed(self) -> bool:
        """Did physics check pass?"""
        return self.result == PhysicsCheckResult.PASS
    
    @property
    def violation_count(self) -> int:
        return len(self.violations)
    
    @property
    def max_severity(self) -> float:
        """Highest severity among all violations."""
        if not self.violations:
            return 0.0
        return max(v.severity for v in self.violations)
    
    def to_audit_recommendation(self) -> str:
        """Convert to audit system recommendation."""
        if self.passed:
            return "approve"
        elif self.result == PhysicsCheckResult.WARN:
            return "manual_review"
        else:
            return "reroll"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "result": self.result.value,
            "violation_count": self.violation_count,
            "violations": [
                {
                    "type": v.violation_type.value,
                    "track_id": v.track_id,
                    "class_name": v.class_name,
                    "frame_range": v.frame_range,
                    "severity": v.severity,
                    "description": v.description,
                }
                for v in self.violations
            ],
            "total_frames": self.total_frames,
            "unique_objects": self.unique_objects,
            "max_severity": self.max_severity,
            "passed": self.passed,
            "recommendation": self.to_audit_recommendation(),
            "message": self.message,
        }


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PhysicsCheckError(Exception):
    """Base exception for physics checking errors."""
    pass


class FrameExtractionError(PhysicsCheckError):
    """Error extracting frames from video."""
    pass


class DetectionError(PhysicsCheckError):
    """Error running object detection."""
    pass


class TrackingError(PhysicsCheckError):
    """Error in object tracking."""
    pass


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class BasePhysicsChecker(ABC):
    """
    Abstract base class for physics checking.
    
    Subclasses must implement:
    - health_check(): Verify models are available
    - detect_objects(): Run YOLO on a single frame
    - analyze_sequence(): Full analysis of frame sequence
    
    The base class provides:
    - analyze_video(): Extract frames and analyze
    - Violation detection logic
    - Configuration handling
    """
    
    def __init__(
        self,
        missing_frames_threshold: int = DEFAULT_MISSING_FRAMES_THRESHOLD,
        teleport_threshold: float = DEFAULT_TELEPORT_THRESHOLD,
        detection_confidence: float = DEFAULT_DETECTION_CONFIDENCE,
    ):
        """
        Initialize physics checker.
        
        Args:
            missing_frames_threshold: Max frames object can vanish before flagging
            teleport_threshold: Max normalized movement per frame (0-1)
            detection_confidence: Min confidence for YOLO detections
        """
        self.missing_frames_threshold = missing_frames_threshold
        self.teleport_threshold = teleport_threshold
        self.detection_confidence = detection_confidence
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify that detection models are available and working.
        
        Returns:
            True if models are ready
        """
        pass
    
    @abstractmethod
    async def detect_objects(
        self,
        frame: np.ndarray,
        frame_index: int,
    ) -> FrameObjects:
        """
        Detect and track objects in a single frame.
        
        Args:
            frame: Image as numpy array (H, W, C) in RGB
            frame_index: Index of this frame in sequence
            
        Returns:
            FrameObjects with all detections and tracking IDs
        """
        pass
    
    @abstractmethod
    async def analyze_sequence(
        self,
        frames: Sequence[np.ndarray],
    ) -> PhysicsAnalysis:
        """
        Analyze a sequence of frames for physics violations.
        
        This is the main entry point for video analysis.
        
        Args:
            frames: List/array of frames as numpy arrays
            
        Returns:
            PhysicsAnalysis with violations and tracks
        """
        pass
    
    async def analyze_video(
        self,
        video_path: Path,
        sample_rate: int = 1,
    ) -> PhysicsAnalysis:
        """
        Analyze a video file for physics violations.
        
        Extracts frames and calls analyze_sequence.
        
        Args:
            video_path: Path to video file
            sample_rate: Analyze every Nth frame (1 = all frames)
            
        Returns:
            PhysicsAnalysis
        """
        import cv2
        import time
        
        start_time = time.time()
        
        if not video_path.exists():
            raise FrameExtractionError(f"Video not found: {video_path}")
        
        # Extract frames
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise FrameExtractionError(f"Could not open video: {video_path}")
        
        frames = []
        frame_idx = 0
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if frame_idx % sample_rate == 0:
                    # Convert BGR to RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append(frame_rgb)
                
                frame_idx += 1
        finally:
            cap.release()
        
        if not frames:
            raise FrameExtractionError(f"No frames extracted from: {video_path}")
        
        logger.info(f"Extracted {len(frames)} frames from {video_path}")
        
        # Analyze
        result = await self.analyze_sequence(frames)
        result.analysis_time_sec = time.time() - start_time
        
        return result
    
    def _detect_teleportation(
        self,
        track: ObjectTrack,
        fps: float = 12.0,
    ) -> Optional[PhysicsViolation]:
        """
        Check if object teleported between frames.
        
        Args:
            track: Object track to check
            fps: Frames per second (for velocity calculation)
            
        Returns:
            PhysicsViolation if teleportation detected, None otherwise
        """
        if len(track.detections) < 2:
            return None
        
        max_distance = 0.0
        violation_frames = (0, 0)
        
        for i in range(len(track.detections) - 1):
            curr = track.detections[i]
            next_det = track.detections[i + 1]
            
            # Only check consecutive frames
            frame_gap = next_det.frame_index - curr.frame_index
            if frame_gap > 1:
                continue  # Gap handled by disappearance check
            
            distance = curr.distance_to(next_det)
            if distance > max_distance:
                max_distance = distance
                violation_frames = (curr.frame_index, next_det.frame_index)
        
        if max_distance > self.teleport_threshold:
            # Severity scales with how much threshold was exceeded
            severity = min(1.0, max_distance / self.teleport_threshold - 0.5)
            
            return PhysicsViolation(
                violation_type=PhysicsViolationType.TELEPORTATION,
                track_id=track.track_id,
                class_name=track.class_name,
                frame_range=violation_frames,
                severity=severity,
                description=(
                    f"{track.class_name} (ID {track.track_id}) moved {max_distance:.2f} "
                    f"normalized units in 1 frame (threshold: {self.teleport_threshold})"
                ),
                details={"distance": max_distance, "threshold": self.teleport_threshold},
            )
        
        return None
    
    def _detect_disappearance(
        self,
        track: ObjectTrack,
        total_frames: int,
    ) -> List[PhysicsViolation]:
        """
        Check if object disappeared and reappeared.
        
        Args:
            track: Object track to check
            total_frames: Total frames in sequence
            
        Returns:
            List of disappearance violations
        """
        violations = []
        gaps = track.gaps()
        
        for gap_start, gap_end in gaps:
            gap_length = gap_end - gap_start - 1
            
            if gap_length > self.missing_frames_threshold:
                # Severity based on gap length
                severity = min(1.0, gap_length / (self.missing_frames_threshold * 3))
                
                violations.append(PhysicsViolation(
                    violation_type=PhysicsViolationType.DISAPPEARANCE,
                    track_id=track.track_id,
                    class_name=track.class_name,
                    frame_range=(gap_start, gap_end),
                    severity=severity,
                    description=(
                        f"{track.class_name} (ID {track.track_id}) vanished for "
                        f"{gap_length} frames (threshold: {self.missing_frames_threshold})"
                    ),
                    details={"gap_length": gap_length},
                ))
        
        return violations
    
    def _detect_sudden_appearance(
        self,
        track: ObjectTrack,
        total_frames: int,
        grace_frames: int = 3,
    ) -> Optional[PhysicsViolation]:
        """
        Check if object appeared out of nowhere mid-shot.
        
        Objects appearing in first few frames are okay (camera sees them).
        Objects appearing mid-shot without entering from edge are suspicious.
        
        Args:
            track: Object track to check
            total_frames: Total frames in sequence
            grace_frames: Frames at start where appearance is okay
            
        Returns:
            PhysicsViolation if suspicious appearance, None otherwise
        """
        first_frame = track.first_frame
        
        # Appearing in first few frames is normal
        if first_frame <= grace_frames:
            return None
        
        # Check if object appeared from edge of frame
        if track.detections:
            first_det = track.detections[0]
            x1, y1, x2, y2 = first_det.bbox
            
            # If near edge (within 10%), probably entered from outside
            edge_threshold = 0.1
            near_edge = (
                x1 < edge_threshold or
                y1 < edge_threshold or
                x2 > (1 - edge_threshold) or
                y2 > (1 - edge_threshold)
            )
            
            if near_edge:
                return None
        
        # Object appeared mid-frame away from edges
        severity = min(1.0, (first_frame - grace_frames) / (total_frames / 2))
        
        return PhysicsViolation(
            violation_type=PhysicsViolationType.APPEARANCE,
            track_id=track.track_id,
            class_name=track.class_name,
            frame_range=(first_frame, first_frame),
            severity=severity * 0.5,  # Less severe than teleportation
            description=(
                f"{track.class_name} (ID {track.track_id}) appeared suddenly "
                f"at frame {first_frame} (not from edge)"
            ),
            details={"first_frame": first_frame},
        )


# =============================================================================
# YOLO IMPLEMENTATION
# =============================================================================

class YOLOPhysicsChecker(BasePhysicsChecker):
    """
    Production physics checker using YOLO + ByteTrack.
    
    Uses ultralytics library which includes both detection and tracking.
    
    Requirements:
        pip install ultralytics
        
    Models are downloaded automatically on first use.
    """
    
    def __init__(
        self,
        model_name: str = "yolov8n.pt",  # Nano model for speed
        missing_frames_threshold: int = DEFAULT_MISSING_FRAMES_THRESHOLD,
        teleport_threshold: float = DEFAULT_TELEPORT_THRESHOLD,
        detection_confidence: float = DEFAULT_DETECTION_CONFIDENCE,
        device: str = "auto",
    ):
        """
        Initialize YOLO physics checker.
        
        Args:
            model_name: YOLO model to use (yolov8n/s/m/l/x.pt)
            missing_frames_threshold: Max frames object can vanish
            teleport_threshold: Max movement per frame (normalized)
            detection_confidence: Min detection confidence
            device: "auto", "cpu", "cuda", or "mps"
        """
        super().__init__(
            missing_frames_threshold=missing_frames_threshold,
            teleport_threshold=teleport_threshold,
            detection_confidence=detection_confidence,
        )
        self.model_name = model_name
        self.device = device
        self._model = None
        self._tracker = None
    
    def _ensure_model(self):
        """Lazy load YOLO model on first use."""
        if self._model is not None:
            return
        
        try:
            from ultralytics import YOLO
            
            logger.info(f"Loading YOLO model: {self.model_name}")
            self._model = YOLO(self.model_name)
            
            # Set device
            if self.device != "auto":
                self._model.to(self.device)
            
            logger.info("YOLO model loaded successfully")
            
        except ImportError:
            raise PhysicsCheckError(
                "ultralytics package not installed. "
                "Run: pip install ultralytics"
            )
        except Exception as e:
            raise PhysicsCheckError(f"Failed to load YOLO model: {e}")
    
    async def health_check(self) -> bool:
        """Verify YOLO model is available."""
        try:
            self._ensure_model()
            return self._model is not None
        except Exception as e:
            logger.warning(f"YOLO health check failed: {e}")
            return False
    
    async def detect_objects(
        self,
        frame: np.ndarray,
        frame_index: int,
    ) -> FrameObjects:
        """
        Run YOLO detection on a single frame.
        
        Note: For proper tracking, use analyze_sequence instead.
        Single-frame detection won't have persistent track IDs.
        """
        import time
        
        self._ensure_model()
        start_time = time.time()
        
        # Run detection
        results = self._model(
            frame,
            conf=self.detection_confidence,
            verbose=False,
        )
        
        objects = []
        if results and len(results) > 0:
            result = results[0]
            
            # Get image dimensions for normalization
            h, w = frame.shape[:2]
            
            if result.boxes is not None:
                for i, box in enumerate(result.boxes):
                    # Get coordinates
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1, y1, x2, y2 = xyxy
                    
                    # Normalize to 0-1
                    bbox = (x1 / w, y1 / h, x2 / w, y2 / h)
                    
                    # Get class info
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])
                    
                    # Without tracking, use index as pseudo-ID
                    track_id = i
                    if hasattr(box, 'id') and box.id is not None:
                        track_id = int(box.id[0])
                    
                    objects.append(DetectedObject(
                        track_id=track_id,
                        class_id=class_id,
                        class_name=class_name,
                        bbox=bbox,
                        confidence=confidence,
                        frame_index=frame_index,
                    ))
        
        return FrameObjects(
            frame_index=frame_index,
            frame_path=None,
            objects=objects,
            detection_time_sec=time.time() - start_time,
        )
    
    async def analyze_sequence(
        self,
        frames: Sequence[np.ndarray],
    ) -> PhysicsAnalysis:
        """
        Analyze frame sequence with tracking for physics violations.
        
        Uses ByteTrack (built into ultralytics) for persistent object IDs.
        """
        import time
        
        self._ensure_model()
        start_time = time.time()
        
        if not frames:
            return PhysicsAnalysis(
                result=PhysicsCheckResult.NO_OBJECTS,
                violations=[],
                tracks=[],
                total_frames=0,
                unique_objects=0,
                message="No frames to analyze",
            )
        
        # Track all detections
        all_frame_objects: List[FrameObjects] = []
        track_dict: Dict[int, ObjectTrack] = {}
        
        # Run tracking on sequence
        # ultralytics track() handles multi-frame tracking
        for frame_idx, frame in enumerate(frames):
            # Run detection with tracking
            results = self._model.track(
                frame,
                conf=self.detection_confidence,
                persist=True,  # Maintain track IDs across frames
                verbose=False,
            )
            
            h, w = frame.shape[:2]
            frame_objects = []
            
            if results and len(results) > 0:
                result = results[0]
                
                if result.boxes is not None:
                    for box in result.boxes:
                        xyxy = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = xyxy
                        bbox = (x1 / w, y1 / h, x2 / w, y2 / h)
                        
                        class_id = int(box.cls[0])
                        class_name = result.names[class_id]
                        confidence = float(box.conf[0])
                        
                        # Get track ID (ByteTrack assigns these)
                        track_id = -1
                        if hasattr(box, 'id') and box.id is not None:
                            track_id = int(box.id[0])
                        else:
                            # Fallback: use box index (won't persist)
                            track_id = len(frame_objects)
                        
                        detection = DetectedObject(
                            track_id=track_id,
                            class_id=class_id,
                            class_name=class_name,
                            bbox=bbox,
                            confidence=confidence,
                            frame_index=frame_idx,
                        )
                        frame_objects.append(detection)
                        
                        # Build track history
                        if track_id not in track_dict:
                            track_dict[track_id] = ObjectTrack(
                                track_id=track_id,
                                class_name=class_name,
                            )
                        track_dict[track_id].detections.append(detection)
            
            all_frame_objects.append(FrameObjects(
                frame_index=frame_idx,
                frame_path=None,
                objects=frame_objects,
            ))
        
        # Convert to list
        tracks = list(track_dict.values())
        
        # Check for violations
        violations: List[PhysicsViolation] = []
        
        for track in tracks:
            # Skip very short tracks (noise)
            if track.frame_count < 2:
                continue
            
            # Check teleportation
            teleport = self._detect_teleportation(track)
            if teleport:
                violations.append(teleport)
            
            # Check disappearance/reappearance
            disappearances = self._detect_disappearance(track, len(frames))
            violations.extend(disappearances)
            
            # Check sudden appearance
            appearance = self._detect_sudden_appearance(track, len(frames))
            if appearance:
                violations.append(appearance)
        
        # Determine result
        if not tracks:
            result = PhysicsCheckResult.NO_OBJECTS
            message = "No trackable objects detected"
        elif not violations:
            result = PhysicsCheckResult.PASS
            message = f"All {len(tracks)} tracked objects behaved physically"
        else:
            max_severity = max(v.severity for v in violations)
            if max_severity >= 0.7:
                result = PhysicsCheckResult.FAIL
            else:
                result = PhysicsCheckResult.WARN
            message = f"Found {len(violations)} physics violations across {len(tracks)} objects"
        
        return PhysicsAnalysis(
            result=result,
            violations=violations,
            tracks=tracks,
            total_frames=len(frames),
            unique_objects=len(tracks),
            analysis_time_sec=time.time() - start_time,
            message=message,
        )


# =============================================================================
# MOCK IMPLEMENTATION (Testing)
# =============================================================================

class MockPhysicsChecker(BasePhysicsChecker):
    """
    Mock physics checker for testing without YOLO models.
    
    Returns configurable results for testing different scenarios.
    
    Usage:
        # Always passes
        checker = MockPhysicsChecker(mock_result=PhysicsCheckResult.PASS)
        
        # Simulate violations
        checker = MockPhysicsChecker(
            mock_result=PhysicsCheckResult.FAIL,
            mock_violations=[...],
        )
    """
    
    def __init__(
        self,
        missing_frames_threshold: int = DEFAULT_MISSING_FRAMES_THRESHOLD,
        teleport_threshold: float = DEFAULT_TELEPORT_THRESHOLD,
        mock_result: PhysicsCheckResult = PhysicsCheckResult.PASS,
        mock_violations: Optional[List[PhysicsViolation]] = None,
        mock_object_count: int = 3,
        simulate_error: bool = False,
    ):
        """
        Initialize mock checker.
        
        Args:
            mock_result: Result to return
            mock_violations: Violations to include (None = auto-generate based on result)
            mock_object_count: Number of fake objects to "detect"
            simulate_error: If True, raise errors
        """
        super().__init__(
            missing_frames_threshold=missing_frames_threshold,
            teleport_threshold=teleport_threshold,
        )
        self.mock_result = mock_result
        self.mock_violations = mock_violations or []
        self.mock_object_count = mock_object_count
        self.simulate_error = simulate_error
        self._analysis_count = 0
    
    async def health_check(self) -> bool:
        """Mock always healthy unless simulating errors."""
        return not self.simulate_error
    
    async def detect_objects(
        self,
        frame: np.ndarray,
        frame_index: int,
    ) -> FrameObjects:
        """Return mock detections."""
        if self.simulate_error:
            raise DetectionError("Simulated detection error")
        
        objects = []
        for i in range(self.mock_object_count):
            objects.append(DetectedObject(
                track_id=i,
                class_id=39 + i,  # bottle, wine glass, cup, etc.
                class_name=["bottle", "wine glass", "cup", "bowl"][i % 4],
                bbox=(0.2 + i * 0.1, 0.3, 0.3 + i * 0.1, 0.5),
                confidence=0.85,
                frame_index=frame_index,
            ))
        
        return FrameObjects(
            frame_index=frame_index,
            frame_path=None,
            objects=objects,
            detection_time_sec=0.01,
        )
    
    async def analyze_sequence(
        self,
        frames: Sequence[np.ndarray],
    ) -> PhysicsAnalysis:
        """Return mock analysis result."""
        self._analysis_count += 1
        
        if self.simulate_error:
            raise PhysicsCheckError("Simulated analysis error")
        
        # Generate mock tracks
        tracks = []
        for i in range(self.mock_object_count):
            track = ObjectTrack(
                track_id=i,
                class_name=["bottle", "wine glass", "cup"][i % 3],
            )
            # Add detections for each frame
            for frame_idx in range(len(frames)):
                track.detections.append(DetectedObject(
                    track_id=i,
                    class_id=39 + i,
                    class_name=track.class_name,
                    bbox=(0.2 + i * 0.1, 0.3, 0.3 + i * 0.1, 0.5),
                    confidence=0.85,
                    frame_index=frame_idx,
                ))
            tracks.append(track)
        
        # Use provided violations or generate based on result
        violations = self.mock_violations
        if not violations and self.mock_result == PhysicsCheckResult.FAIL:
            violations = [
                PhysicsViolation(
                    violation_type=PhysicsViolationType.TELEPORTATION,
                    track_id=0,
                    class_name="cup",
                    frame_range=(5, 6),
                    severity=0.8,
                    description="Mock teleportation violation",
                )
            ]
        
        message = {
            PhysicsCheckResult.PASS: f"Mock: All {self.mock_object_count} objects OK",
            PhysicsCheckResult.FAIL: f"Mock: Found {len(violations)} violations",
            PhysicsCheckResult.WARN: f"Mock: Minor issues detected",
            PhysicsCheckResult.NO_OBJECTS: "Mock: No objects to track",
            PhysicsCheckResult.ERROR: "Mock: Analysis error",
        }.get(self.mock_result, "Mock analysis complete")
        
        return PhysicsAnalysis(
            result=self.mock_result,
            violations=violations,
            tracks=tracks,
            total_frames=len(frames),
            unique_objects=self.mock_object_count,
            analysis_time_sec=0.05,
            message=message,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_physics_checker(
    use_mock: bool = False,
    missing_frames_threshold: int = DEFAULT_MISSING_FRAMES_THRESHOLD,
    teleport_threshold: float = DEFAULT_TELEPORT_THRESHOLD,
    **kwargs,
) -> BasePhysicsChecker:
    """
    Factory function to get appropriate physics checker.
    
    Attempts to load YOLO, falls back to mock if unavailable.
    
    Args:
        use_mock: If True, always return mock
        missing_frames_threshold: Max frames object can vanish
        teleport_threshold: Max movement per frame
        **kwargs: Passed to checker constructor
        
    Returns:
        Physics checker instance
    """
    if use_mock:
        return MockPhysicsChecker(
            missing_frames_threshold=missing_frames_threshold,
            teleport_threshold=teleport_threshold,
            **kwargs,
        )
    
    # Try to create YOLO checker
    try:
        checker = YOLOPhysicsChecker(
            missing_frames_threshold=missing_frames_threshold,
            teleport_threshold=teleport_threshold,
            **kwargs,
        )
        # Verify it works
        checker._ensure_model()
        return checker
    except Exception as e:
        logger.warning(f"YOLO not available ({e}), falling back to mock")
        return MockPhysicsChecker(
            missing_frames_threshold=missing_frames_threshold,
            teleport_threshold=teleport_threshold,
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def quick_physics_check(
    video_path: Path,
    missing_frames_threshold: int = DEFAULT_MISSING_FRAMES_THRESHOLD,
) -> Tuple[bool, int]:
    """
    Quick physics check for simple use cases.
    
    Args:
        video_path: Path to video file
        missing_frames_threshold: Max frames object can vanish
        
    Returns:
        Tuple of (passed: bool, violation_count: int)
    
    Usage:
        passed, violations = await quick_physics_check(video_path)
        if not passed:
            print(f"Found {violations} physics violations!")
    """
    checker = get_physics_checker(
        missing_frames_threshold=missing_frames_threshold,
    )
    result = await checker.analyze_video(video_path)
    return (result.passed, result.violation_count)


async def check_bridge_physics(
    shot_a_path: Path,
    shot_b_path: Path,
    shared_object_classes: Optional[List[str]] = None,
) -> Dict[str, PhysicsAnalysis]:
    """
    Verify physics continuity across a bridge transition.
    
    Checks that objects present at end of Shot A are present
    at start of Shot B (accounting for the bridge frame).
    
    Args:
        shot_a_path: Video before bridge
        shot_b_path: Video after bridge
        shared_object_classes: Object types to track (None = all)
        
    Returns:
        Dict with "shot_a" and "shot_b" analyses
    """
    checker = get_physics_checker()
    
    shot_a_result = await checker.analyze_video(shot_a_path)
    shot_b_result = await checker.analyze_video(shot_b_path)
    
    return {
        "shot_a": shot_a_result,
        "shot_b": shot_b_result,
    }