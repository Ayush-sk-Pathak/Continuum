# SONIC SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Sonic** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos with synchronized audio.

This silo is the **AUDIO ENGINE**. It handles text-to-speech (TTS), ambient sound generation, foley (sound effects), audio mixing, and lip sync. Audio runs in PARALLEL with video generation.

## System Architecture (Bird's Eye)

```
        ┌──────────────────────────────────────────┐
        │      Director (provides SonicManifest)    │
        └─────────────────────┬────────────────────┘
                              │
                              ▼
        ╔════════════════════════════════════════════════════════════╗
        ║                    SONIC (this silo)                       ║
        ║                                                            ║
        ║   ┌──────────────────────────────────────────────────┐    ║
        ║   │                   Mixer                           │    ║
        ║   │            (orchestrates + mixes)                 │    ║
        ║   └──────────────────────┬───────────────────────────┘    ║
        ║                          │                                 ║
        ║          ┌───────────────┼───────────────┐                ║
        ║          ▼               ▼               ▼                ║
        ║   ┌───────────┐   ┌───────────┐   ┌───────────┐          ║
        ║   │    TTS    │   │ Ambience  │   │   Foley   │          ║
        ║   │(dialogue) │   │(background)│   │  (SFX)   │          ║
        ║   └───────────┘   └───────────┘   └───────────┘          ║
        ║                          │                                 ║
        ║                          ▼                                 ║
        ║              ┌─────────────────┐                          ║
        ║              │    Lip Sync     │                          ║
        ║              │   (MuseTalk)    │                          ║
        ║              └─────────────────┘                          ║
        ╚════════════════════════════════════════════════════════════╝
                              │
                              ▼ Audio tracks
        ┌──────────────────────────────────────────┐
        │      Post (ducks audio, final mix)        │
        └──────────────────────────────────────────┘
```

## This Silo's Role

| Component | Responsibility |
|-----------|----------------|
| **TTSEngine** | Convert dialogue text to speech (ElevenLabs/OpenAI) |
| **Ambience** | Generate background audio (AudioLDM) |
| **Foley** | Retrieve/generate sound effects |
| **Mixer** | Combine audio tracks with proper timing |
| **LipSync** | Synchronize video with dialogue (MuseTalk via ComfyUI) |
| **types.py** | Dataclasses for audio specs and results |

## Key Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `sonic/types.py` | Type definitions | `SonicManifest`, `DialogueLine`, `AmbienceSpec`, `FoleyEvent` |
| `sonic/tts_engine.py` | Text-to-speech | `TTSEngine`, `ElevenLabsTTS` |
| `sonic/ambience.py` | Background audio | `AmbienceEngine`, `AudioLDMProvider` |
| `sonic/foley.py` | Sound effects | `FoleyEngine` |
| `sonic/mixer.py` | Audio mixing | `AudioMixer` |
| `sonic/lip_sync.py` | Lip synchronization | `LipSyncEngine`, `MuseTalkLipSync` |

## Interfaces This Silo EXPOSES

Used by **main.py** and **Post**:

```python
# From sonic/types.py
class TTSProvider(Enum):
    ELEVENLABS = auto()
    OPENAI = auto()
    LOCAL = auto()

class VoiceEmotion(Enum):
    NEUTRAL = auto()
    HAPPY = auto()
    SAD = auto()
    # etc.

class AmbienceType(Enum):
    SILENCE = auto()
    INTERIOR_QUIET = auto()
    EXTERIOR_URBAN = auto()
    NATURE = auto()
    # etc.

class FoleyCategory(Enum):
    FOOTSTEPS = auto()
    DOOR = auto()
    IMPACT = auto()
    # etc.

@dataclass
class VoiceConfig:
    character_id: str
    provider: TTSProvider
    voice_id: str
    speaking_rate: float = 1.0

@dataclass
class DialogueLine:
    line_id: str
    character_id: str
    text: str
    start_time_sec: float
    emotion: Optional[VoiceEmotion] = None

@dataclass
class AmbienceSpec:
    ambience_id: str
    type: AmbienceType
    description: str
    duration_sec: float

@dataclass
class FoleyEvent:
    event_id: str
    category: FoleyCategory
    description: str
    trigger_time_sec: float

@dataclass
class ShotAudioPlan:
    shot_id: str
    duration_sec: float
    dialogue_lines: List[DialogueLine]
    ambience: Optional[AmbienceSpec]
    foley_events: List[FoleyEvent]

@dataclass
class SonicManifest:
    manifest_id: str
    voice_configs: Dict[str, VoiceConfig]
    shot_plans: List[ShotAudioPlan]
    global_ambience: Optional[AmbienceSpec]

@dataclass
class SynthesizedDialogue:
    line_id: str
    audio_path: Path
    actual_duration_sec: float

@dataclass
class MixResult:
    mix_id: str
    shot_id: str
    output_path: Path
    duration_sec: float

# From sonic/tts_engine.py
class BaseTTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, line: DialogueLine, voice: VoiceConfig) -> SynthesizedDialogue: ...

def get_tts_engine(provider: TTSProvider) -> BaseTTSEngine: ...

# From sonic/lip_sync.py
@dataclass
class LipSyncSpec:
    video_path: Path
    audio_path: Path
    character_id: str

@dataclass
class LipSyncResult:
    output_video_path: Path
    success: bool

class BaseLipSyncEngine(ABC):
    @abstractmethod
    async def apply_lip_sync(self, spec: LipSyncSpec) -> LipSyncResult: ...
```

## Interfaces This Silo CONSUMES

From **Core**:
```python
from src.core.config import get_config
```

From **ComfyClient** (for MuseTalk lip sync):
```python
from src.comfy_client.client import ComfyUIClient
from src.comfy_client.workflow_loader import WorkflowLoader
```

**External APIs:**
- ElevenLabs API - TTS
- OpenAI TTS API - Alternative TTS
- AudioLDM - Ambience generation (via ComfyUI or HuggingFace)

## Audio Pipeline Flow

```
1. Director creates SonicManifest from script
   ↓
2. TTSEngine generates dialogue audio files
   ↓
3. Ambience engine generates background audio
   ↓
4. Foley engine retrieves/generates sound effects
   ↓
5. Mixer combines all tracks per shot
   ↓
6. LipSync applies mouth movement to video
   ↓
7. Post applies ducking (lower music during dialogue)
```

## Common Tasks

### Adding a new TTS provider
```python
# 1. Add to TTSProvider enum
class TTSProvider(Enum):
    ELEVENLABS = auto()
    OPENAI = auto()
    NEW_PROVIDER = auto()

# 2. Create implementation class
class NewProviderTTS(BaseTTSEngine):
    async def synthesize(self, line: DialogueLine, voice: VoiceConfig) -> SynthesizedDialogue:
        # Call new provider API
        # Return audio file path

# 3. Update get_tts_engine factory
def get_tts_engine(provider: TTSProvider) -> BaseTTSEngine:
    if provider == TTSProvider.NEW_PROVIDER:
        return NewProviderTTS()
```

### Adding a new ambience type
```python
# 1. Add to AmbienceType enum
class AmbienceType(Enum):
    # ... existing
    UNDERWATER = auto()

# 2. Add prompt mapping in ambience.py
AMBIENCE_PROMPTS = {
    AmbienceType.UNDERWATER: "underwater bubbles, muffled sounds, ocean depth",
}
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| types.py | ✅ Working | All dataclasses defined |
| TTSEngine | 🟡 Stubbed | Interface exists, needs ElevenLabs integration |
| Ambience | 🟡 Stubbed | Interface exists |
| Foley | 🟡 Stubbed | Interface exists |
| Mixer | 🟡 Stubbed | Interface exists |
| LipSync (MuseTalk) | 🟡 Stubbed | Workflow exists, integration pending |

**MVP Priority:** TTS + LipSync > Ambience > Foley > Mixer

## Related Documentation

- `docs/ARCHITECTURE.md` - Section 4 (Sonic Engine)
- `docs/ARCHITECTURE_SUMMARY.md` - Section 5 (Audio)
- `workflows/shared/musetalk_lipsync.json` - Lip sync workflow