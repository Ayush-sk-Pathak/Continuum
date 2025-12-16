"""
Pytest configuration for Continuum Engine tests.
"""

import sys
from pathlib import Path

import pytest

# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# Add project root to Python path so 'from src.sonic import ...' works
project_root = Path(__file__).parent.parent  # tests/ -> project root
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

pytest_plugins = ('pytest_asyncio',)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as an asyncio test"
    )