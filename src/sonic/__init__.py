"""
Continuum Engine - Sonic Module

Generates and mixes all audio layers for the final film:
- TTS Engine: Dialogue synthesis (ElevenLabs, OpenAI)
- Lip Sync: Audio-driven mouth animation (Musetalk, Wav2Lip)
- Ambience: Background atmosphere (AudioLDM-2)
- Foley: Event-triggered sound effects
- Mixer: Combines all layers with smart ducking

This module runs as "Track B" in parallel with video generation (Track A).
Lip sync is unique: it takes audio but modifies video (runs after Pass 2).
"""

from .types import (
    # Enums
    TTSProvider,
    VoiceEmotion,
    AmbienceType,
    FoleyCategory,
    AudioGenerationStatus,
    
    # Voice & Character
    VoiceConfig,
    
    # Dialogue
    DialogueLine,
    SynthesizedDialogue,
    
    # Ambience
    AmbienceSpec,
    SynthesizedAmbience,
    
    # Foley
    FoleyEvent,
    SynthesizedFoley,
    
    # Manifest
    ShotAudioPlan,
    SonicManifest,
    
    # Mix
    MixResult,
)

from .lip_sync import (
    # Enums
    LipSyncProvider,
    LipSyncStatus,
    
    # Data structures
    DialogueSegment,
    LipSyncSpec,
    LipSyncResult,
    LipSyncProgress,
    
    # Classes
    BaseLipSyncEngine,
    MusetalkComfyEngine,
    Wav2LipReplicateEngine,
    PassthroughLipSyncEngine,
    LipSyncFactory,
    
    # Functions
    sync_lips,
    sync_batch,
)

# Engine imports (lazy - only if needed)
# These are imported explicitly to avoid loading heavy dependencies at module load
# Usage: from src.sonic import get_tts_engine, AudioMixer

__all__ = [
    # Enums
    "TTSProvider",
    "VoiceEmotion",
    "AmbienceType",
    "FoleyCategory",
    "AudioGenerationStatus",
    
    # Voice & Character
    "VoiceConfig",
    
    # Dialogue
    "DialogueLine",
    "SynthesizedDialogue",
    
    # Ambience
    "AmbienceSpec",
    "SynthesizedAmbience",
    
    # Foley
    "FoleyEvent",
    "SynthesizedFoley",
    
    # Manifest
    "ShotAudioPlan",
    "SonicManifest",
    
    # Mix
    "MixResult",
    
    # Lip Sync
    "LipSyncProvider",
    "LipSyncStatus",
    "DialogueSegment",
    "LipSyncSpec",
    "LipSyncResult",
    "LipSyncProgress",
    "BaseLipSyncEngine",
    "MusetalkComfyEngine",
    "Wav2LipReplicateEngine",
    "PassthroughLipSyncEngine",
    "LipSyncFactory",
    "sync_lips",
    "sync_batch",
]


# =============================================================================
# LAZY ENGINE ACCESSORS
# =============================================================================

def get_tts_engine(provider, **kwargs):
    """Get a TTS engine instance. See tts_engine.py for details."""
    from .tts_engine import get_tts_engine as _get
    return _get(provider, **kwargs)


def get_ambience_engine(provider, **kwargs):
    """Get an ambience engine instance. See ambience.py for details."""
    from .ambience import get_ambience_engine as _get
    return _get(provider, **kwargs)


def get_foley_engine(provider, **kwargs):
    """Get a foley engine instance. See foley.py for details."""
    from .foley import get_foley_engine as _get
    return _get(provider, **kwargs)


def get_mixer(**kwargs):
    """Get an AudioMixer instance. See mixer.py for details."""
    from .mixer import AudioMixer
    return AudioMixer(**kwargs)


def get_lip_sync_engine(provider=None, **kwargs):
    """Get a LipSync engine instance. See lip_sync.py for details."""
    from .lip_sync import LipSyncFactory
    import asyncio
    factory = LipSyncFactory(**kwargs)
    # Note: This is sync wrapper - use LipSyncFactory directly for async
    return asyncio.get_event_loop().run_until_complete(factory.get_engine(provider))