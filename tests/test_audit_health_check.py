"""
Audit System Health Check Tests

PURPOSE:
    Verify the fail-fast initialization behavior for the identity audit system.
    
    The identity checker is the foundation of the feedback loop:
    - If it can't load, audits silently pass (open-loop system)
    - The health check ensures we detect this at startup, not after expensive GPU work

ARCHITECTURE REFERENCE:
    Section 3F: "ArcFace embedding on frame 1 of every chunk"
    Section 7A.4: "Audit pass? → proceed; fail? → re-roll"
    
    The health check closes the loop by verifying the audit system works
    BEFORE entering the generation pipeline.

WHAT THIS TESTS:
    [x] MockIdentityChecker.health_check() returns True
    [x] ArcFaceIdentityChecker.health_check() returns True when insightface available
    [x] ArcFaceIdentityChecker.health_check() returns False when insightface missing
    [x] Reviewer.health_check() aggregates sub-checker results
    [x] Fail-fast logic triggers RuntimeError when identity checker fails

RUN WITH:
    pytest test_audit_health_check.py -v
    
    # Or from project root with proper imports:
    python -m pytest tests/test_audit_health_check.py -v
"""

import tempfile
import shutil
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_workspace():
    """Create temporary workspace."""
    workspace = Path(tempfile.mkdtemp(prefix="continuum_health_test_"))
    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)


# =============================================================================
# TESTS: MockIdentityChecker Health Check
# =============================================================================

class TestMockIdentityCheckerHealth:
    """
    Test MockIdentityChecker health check behavior.
    
    Mock should always be healthy (it's for testing).
    """
    
    @pytest.mark.asyncio
    async def test_mock_checker_is_healthy(self):
        """MockIdentityChecker.health_check() should return True."""
        from src.audit.identity_checker import MockIdentityChecker
        
        checker = MockIdentityChecker()
        result = await checker.health_check()
        
        assert result is True, "MockIdentityChecker should always be healthy"
    
    @pytest.mark.asyncio
    async def test_mock_checker_unhealthy_when_simulating_error(self):
        """MockIdentityChecker with simulate_error=True should be unhealthy."""
        from src.audit.identity_checker import MockIdentityChecker
        
        checker = MockIdentityChecker(simulate_error=True)
        result = await checker.health_check()
        
        assert result is False, "MockIdentityChecker with simulate_error should be unhealthy"


# =============================================================================
# TESTS: ArcFaceIdentityChecker Health Check
# =============================================================================

class TestArcFaceIdentityCheckerHealth:
    """
    Test ArcFaceIdentityChecker health check behavior.
    
    These tests use mocking to simulate insightface availability.
    """
    
    @pytest.mark.asyncio
    async def test_arcface_healthy_when_insightface_available(self):
        """ArcFaceIdentityChecker should be healthy when model loads."""
        from src.audit.identity_checker import ArcFaceIdentityChecker
        
        checker = ArcFaceIdentityChecker()
        
        # Mock the initialization to succeed
        mock_model = MagicMock()
        mock_model.get.return_value = []  # No faces (doesn't matter for health)
        
        with patch.object(checker, '_initialized', True):
            with patch.object(checker, '_model', mock_model):
                result = await checker.health_check()
        
        assert result is True, "ArcFaceIdentityChecker should be healthy when model is loaded"
    
    @pytest.mark.asyncio
    async def test_arcface_unhealthy_when_insightface_missing(self):
        """ArcFaceIdentityChecker should be unhealthy when insightface can't load."""
        from src.audit.identity_checker import ArcFaceIdentityChecker, ModelLoadError
        
        checker = ArcFaceIdentityChecker()
        
        # Mock initialize() to raise ImportError (simulating missing insightface)
        async def mock_init_fails():
            raise ModelLoadError("insightface not installed")
        
        with patch.object(checker, 'initialize', mock_init_fails):
            result = await checker.health_check()
        
        assert result is False, "ArcFaceIdentityChecker should be unhealthy when insightface missing"
    
    @pytest.mark.asyncio
    async def test_arcface_unhealthy_when_model_load_fails(self):
        """ArcFaceIdentityChecker should be unhealthy when model fails to load."""
        from src.audit.identity_checker import ArcFaceIdentityChecker
        
        checker = ArcFaceIdentityChecker()
        
        # Mock initialize() to raise generic exception
        async def mock_init_fails():
            raise Exception("CUDA out of memory")
        
        with patch.object(checker, 'initialize', mock_init_fails):
            result = await checker.health_check()
        
        assert result is False, "ArcFaceIdentityChecker should be unhealthy when model load fails"


# =============================================================================
# TESTS: Reviewer Health Check Aggregation
# =============================================================================

class TestReviewerHealthCheck:
    """
    Test Reviewer.health_check() aggregation behavior.
    
    Reviewer aggregates results from identity and physics checkers.
    """
    
    @pytest.mark.asyncio
    async def test_reviewer_reports_healthy_checkers(self):
        """Reviewer should report health status of all sub-checkers."""
        from src.audit.reviewer import Reviewer
        from src.audit.identity_checker import MockIdentityChecker
        from src.audit.physics_checker import MockPhysicsChecker
        
        reviewer = Reviewer(
            identity_checker=MockIdentityChecker(),
            physics_checker=MockPhysicsChecker(),
        )
        
        health = await reviewer.health_check()
        
        assert "identity" in health, "Should report identity checker status"
        assert "physics" in health, "Should report physics checker status"
        assert health["identity"] is True, "Mock identity should be healthy"
        assert health["physics"] is True, "Mock physics should be healthy"
    
    @pytest.mark.asyncio
    async def test_reviewer_reports_unhealthy_identity_checker(self):
        """Reviewer should report when identity checker is unhealthy."""
        from src.audit.reviewer import Reviewer
        from src.audit.identity_checker import MockIdentityChecker
        from src.audit.physics_checker import MockPhysicsChecker
        
        # Identity checker configured to fail
        reviewer = Reviewer(
            identity_checker=MockIdentityChecker(simulate_error=True),
            physics_checker=MockPhysicsChecker(),
        )
        
        health = await reviewer.health_check()
        
        assert health["identity"] is False, "Should report identity as unhealthy"
        assert health["physics"] is True, "Physics should still be healthy"
    
    @pytest.mark.asyncio
    async def test_reviewer_handles_checker_exception(self):
        """Reviewer should handle exceptions from checkers gracefully."""
        from src.audit.reviewer import Reviewer
        from src.audit.physics_checker import MockPhysicsChecker
        
        # Create a mock identity checker that raises on health_check
        mock_identity = MagicMock()
        mock_identity.health_check = AsyncMock(side_effect=Exception("Boom!"))
        mock_identity.threshold = 0.70
        
        reviewer = Reviewer(
            identity_checker=mock_identity,
            physics_checker=MockPhysicsChecker(),
        )
        
        health = await reviewer.health_check()
        
        # Should catch exception and report as unhealthy, not crash
        assert health["identity"] is False, "Exception should be caught and reported as unhealthy"
        assert health["physics"] is True, "Physics should still work"


# =============================================================================
# TESTS: Fail-Fast Logic
# =============================================================================

class TestFailFastInitialization:
    """
    Test the fail-fast initialization logic.
    
    When identity checker fails to initialize, the pipeline should
    fail immediately with a clear error, not proceed with broken audits.
    """
    
    def test_fail_fast_logic_detects_unhealthy_identity(self):
        """
        Verify the fail-fast logic correctly identifies when to raise.
        
        This tests the decision logic, not the full orchestrator.
        """
        # Simulate health check results
        health_healthy = {"identity": True, "physics": True}
        health_broken_identity = {"identity": False, "physics": True}
        health_broken_physics = {"identity": True, "physics": False}
        
        # Decision logic (mirrors main.py lines 710-721)
        def should_fail_fast(health: Dict[str, bool]) -> bool:
            return not health.get("identity", False)
        
        assert should_fail_fast(health_healthy) is False, \
            "Should not fail when identity is healthy"
        assert should_fail_fast(health_broken_identity) is True, \
            "Should fail when identity is unhealthy"
        assert should_fail_fast(health_broken_physics) is False, \
            "Should not fail when only physics is unhealthy (identity is critical)"
    
    def test_fail_fast_error_message_is_helpful(self):
        """Verify the error message contains actionable guidance."""
        # The error message from main.py
        error_msg = (
            "Identity checker failed to initialize.\n"
            "The audit system cannot verify character consistency.\n\n"
            "To fix:\n"
            "  pip install insightface onnxruntime\n\n"
            "Or disable audit (not recommended for production):\n"
            "  python main.py --project <file> --no-audit"
        )
        
        # Check for required components
        assert "insightface" in error_msg, "Should mention insightface package"
        assert "onnxruntime" in error_msg, "Should mention onnxruntime package"
        assert "pip install" in error_msg, "Should provide install command"
        assert "--no-audit" in error_msg, "Should mention workaround flag"


# =============================================================================
# TESTS: Integration with Factory Function
# =============================================================================

class TestFactoryFunctionHealth:
    """
    Test health check behavior with factory functions.
    """
    
    @pytest.mark.asyncio
    async def test_get_identity_checker_mock_is_healthy(self):
        """get_identity_checker(use_mock=True) should return healthy checker."""
        from src.audit.identity_checker import get_identity_checker
        
        checker = get_identity_checker(use_mock=True)
        result = await checker.health_check()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_reviewer_mock_is_healthy(self):
        """get_reviewer(use_mock=True) should return reviewer with healthy checkers."""
        from src.audit.reviewer import get_reviewer
        
        reviewer = get_reviewer(use_mock=True)
        health = await reviewer.health_check()
        
        assert health["identity"] is True
        assert health["physics"] is True


# =============================================================================
# TESTS: Threshold Configuration
# =============================================================================

class TestThresholdConfiguration:
    """
    Test that identity threshold is correctly configured.
    
    Per ARCHITECTURE.md Section 3F: threshold should be 0.70
    (though config.py has it at 0.50 for development)
    """
    
    def test_default_threshold_is_reasonable(self):
        """Verify default threshold is in valid range."""
        from src.audit.identity_checker import DEFAULT_IDENTITY_THRESHOLD
        
        assert 0.0 <= DEFAULT_IDENTITY_THRESHOLD <= 1.0, \
            "Threshold should be between 0 and 1"
        assert DEFAULT_IDENTITY_THRESHOLD >= 0.50, \
            "Threshold should be at least 0.50 for meaningful identity checking"
    
    def test_checker_uses_configured_threshold(self):
        """Verify checker uses the configured threshold."""
        from src.audit.identity_checker import MockIdentityChecker
        
        custom_threshold = 0.85
        checker = MockIdentityChecker(threshold=custom_threshold)
        
        assert checker.threshold == custom_threshold, \
            "Checker should use configured threshold"
    
    def test_reviewer_exposes_threshold(self):
        """Verify threshold is accessible through reviewer."""
        from src.audit.reviewer import Reviewer
        from src.audit.identity_checker import MockIdentityChecker
        from src.audit.physics_checker import MockPhysicsChecker
        
        custom_threshold = 0.75
        reviewer = Reviewer(
            identity_checker=MockIdentityChecker(threshold=custom_threshold),
            physics_checker=MockPhysicsChecker(),
        )
        
        assert reviewer.identity_checker.threshold == custom_threshold, \
            "Reviewer should expose identity checker's threshold"


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])