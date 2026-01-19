"""
Continuum Pipeline Module

High-level orchestrators that coordinate multiple engines for complete workflows.

Available orchestrators:
    - SonicOrchestrator: TTS + Ambience + Mixing for audio track generation
"""

from .sonic_orchestrator import SonicOrchestrator, SonicResult

__all__ = [
    "SonicOrchestrator",
    "SonicResult",
]
