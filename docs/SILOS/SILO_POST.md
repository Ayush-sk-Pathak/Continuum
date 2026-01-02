# POST SILO - Continuum Engine

## Quick Context for Claude

You are working on the **Post** silo of the Continuum Engine - an AI filmmaking system that generates consistent, multi-shot videos.

This silo is **POST-PRODUCTION**. It handles color matching (make all shots look consistent), audio ducking (lower music during dialogue), and final video stitching. This is the LAST stage before final output.

## System Architecture (Bird's Eye)

```
        ┌──────────────────────────────────────────┐
        │    Studio (video) + Sonic (audio)         │
        └─────────────────────┬────────────────────┘
                              │
                              │ Shot videos + audio tracks
                              ▼
        ╔════════════════════════════════════════════════════════════╗
        ║                     POST (this silo)                       ║
        ║                                                            ║
        ║   ┌────────────────────────────────────────────────────┐  ║
        ║   │                  Stitcher                           │  ║
        ║   │            (assembles final video)                  │  ║
        ║   └────────────────────┬───────────────────────────────┘  ║
        ║                        │                                   ║
        ║            ┌───────────┴───────────┐                      ║
        ║            ▼                       ▼                      ║
        ║   ┌─────────────────┐    ┌─────────────────┐             ║
        ║   │  ColorMatcher   │    │  AudioDucker    │             ║
        ║   │(histogram match)│    │(lower music)    │             ║
        ║   └─────────────────┘    └─────────────────┘             ║
        ║                        │                                   ║
        ║                        ▼                                   ║
        ║              ┌─────────────────┐                          ║
        ║              │  FFmpegWrapper  │                          ║
        ║              │  (encode/mux)   │                          ║
        ║              └─────────────────┘                          ║
        ╚════════════════════════════════════════════════════════════╝
                              │
                              ▼
                    ┌──────────────────┐
                    │   Final .mp4     │
                    │   (output)       │
                    └──────────────────┘
```

## This Silo's Role

| Component | Responsibility |
|-----------|----------------|
| **ColorMatcher** | Match all shot colors to a master shot (histogram matching) |
| **AudioDucker** | Lower background music during dialogue |
| **Stitcher** | Assemble shots into final video with transitions |
| **FFmpegWrapper** | Low-level FFmpeg command execution |

## Key Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `post/color_match.py` | Color consistency | `ColorMatcher`, `ColorProfile` |
| `post/audio_ducker.py` | Music ducking | `AudioDucker`, `DuckingParams` |
| `post/stitcher.py` | Final assembly | `Stitcher`, `StitchJob` |
| `post/ffmpeg_wrapper.py` | FFmpeg utilities | `FFmpegWrapper` |

## Interfaces This Silo EXPOSES

Used by **main.py**:

```python
# From post/color_match.py
@dataclass
class ColorProfile:
    histogram: np.ndarray
    mean_rgb: Tuple[float, float, float]
    
@dataclass
class ColorMatchResult:
    output_path: Path
    success: bool

class ColorMatcher:
    def extract_profile(self, video_path: Path) -> ColorProfile: ...
    def match_to_profile(self, video_path: Path, target: ColorProfile) -> ColorMatchResult: ...

# From post/audio_ducker.py
@dataclass
class DuckingParams:
    dialogue_track: Path
    music_track: Path
    duck_amount_db: float = -12  # How much to lower music
    attack_ms: float = 50
    release_ms: float = 200

@dataclass
class DuckResult:
    output_path: Path
    success: bool

class AudioDucker:
    def duck(self, params: DuckingParams) -> DuckResult: ...

# From post/stitcher.py
class TransitionType(Enum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"

@dataclass
class VideoClip:
    path: Path
    start_time: float
    end_time: float

@dataclass
class AudioTrack:
    path: Path
    track_type: str  # "dialogue" | "music" | "ambience" | "foley"
    volume_db: float

@dataclass
class TransitionSpec:
    type: TransitionType
    duration_sec: float = 0.5

@dataclass
class StitchJob:
    clips: List[VideoClip]
    audio_tracks: List[AudioTrack]
    transitions: List[TransitionSpec]
    output_path: Path

@dataclass
class StitchResult:
    output_path: Path
    duration_sec: float
    success: bool

class Stitcher:
    def stitch(self, job: StitchJob) -> StitchResult: ...
```

## Interfaces This Silo CONSUMES

From **Core**:
```python
from src.core.config import get_config
```

**External:**
- `ffmpeg` - Video encoding and manipulation
- `numpy` - Histogram calculations
- `opencv-python` - Frame extraction for color analysis

## Post-Production Pipeline

```
1. Receive shot videos from Studio
   ↓
2. Extract color profile from master shot (usually shot 1)
   ↓
3. Apply color matching to all other shots
   ↓
4. Receive audio tracks from Sonic
   ↓
5. Apply audio ducking (lower music during dialogue)
   ↓
6. Stitch all clips with transitions
   ↓
7. Final encode with FFmpeg
   ↓
8. Output: final_film.mp4
```

## Common Tasks

### Changing the master shot for color matching
```python
# In main.py or orchestrator
color_matcher = ColorMatcher()

# Use scene 1, shot 2 as master instead of shot 1
master_profile = color_matcher.extract_profile(shots[1].video_path)

for shot in shots[2:]:
    color_matcher.match_to_profile(shot.video_path, master_profile)
```

### Adjusting ducking amount
```python
params = DuckingParams(
    dialogue_track=dialogue_path,
    music_track=music_path,
    duck_amount_db=-18,  # More aggressive ducking (default: -12)
    attack_ms=30,        # Faster duck (default: 50)
)
ducker.duck(params)
```

### Adding a new transition type
```python
# 1. Add to TransitionType enum
class TransitionType(Enum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"
    WIPE = "wipe"  # New

# 2. Implement in Stitcher._apply_transition()
def _apply_transition(self, clip_a: Path, clip_b: Path, spec: TransitionSpec) -> Path:
    if spec.type == TransitionType.WIPE:
        return self._ffmpeg.wipe_transition(clip_a, clip_b, spec.duration_sec)
```

## Current State / Known Issues

| Component | Status | Notes |
|-----------|--------|-------|
| ColorMatcher | ✅ Working | Histogram matching implemented |
| AudioDucker | 🟡 Stubbed | Interface exists |
| Stitcher | ✅ Working | Basic concat works |
| FFmpegWrapper | ✅ Working | Core commands implemented |

**Known Issues:**
- Transitions other than CUT are not implemented
- Audio ducking needs real implementation

## Related Documentation

- `docs/ARCHITECTURE.md` - Section 6 (Post-Production)
- `docs/ARCHITECTURE_SUMMARY.md` - Section 6 (Post)