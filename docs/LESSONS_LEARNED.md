# Lessons Learned: Interface Mismatches & Wrong Assumptions

> **Purpose:** A living document tracking assumptions that caused errors, their corrections, and how to avoid repeating them. Update this whenever a new mismatch is discovered.
>
> **Last Updated:** 2025-12-17 (Added lessons 33-36: WorkflowLoader methods, ComfyClient constructor, KSampler seed, bridge architecture)

---

## Quick Reference: Source of Truth Files

Before writing code that uses these interfaces, **always check these files first**:

| Interface | Source of Truth | Key Classes |
|-----------|-----------------|-------------|
| Renderer | `src/renderers/base.py` | `BaseRenderer`, `RenderResult`, `JobSpec`, `CharacterRef` |
| Scene Graph | `src/director/scene_graph.py` | `SceneGraph`, `Scene`, `Shot`, `Chunk`, `EntityRef` |
| Consistency Dict | `src/director/consistency_dict.py` | `ConsistencyDict`, `CharacterEntity`, `LocationEntity` |
| World State | `src/director/world_state.py` | `WorldState`, `SceneSetup`, `TrackedObject`, `StateEvent` |
| Pacer | `src/director/pacer.py` | `Pacer`, `PacingStyle`, `ShotPacingPlan`, `ChunkTiming` |
| Bridge Engine | `src/studio/bridge_engine.py` | `BaseBridgeEngine`, `BridgeSpec`, `BridgeResult` |
| Pass 1 Generator | `src/studio/pass1_generator.py` | `Pass1Generator`, `GenerationConfig`, `ChunkOutput`, `ShotOutput` |
| Pass 2 Refiner | `src/studio/pass2_refiner.py` | `BaseRefiner`, `RefineSpec`, `RefineResult` |
| RIFE Interpolator | `src/studio/rife_interpolator.py` | `BaseInterpolator`, `InterpolationSpec`, `InterpolationResult` |
| Identity Checker | `src/audit/identity_checker.py` | `BaseIdentityChecker`, `IdentityComparison`, `FrameFaces` |
| Physics Checker | `src/audit/physics_checker.py` | `BasePhysicsChecker`, `PhysicsViolation`, `TrackingResult` |
| Reviewer | `src/audit/reviewer.py` | `Reviewer`, `ReviewRequest`, `ReviewResult`, `ReviewDecision` |
| Sonic Types | `src/sonic/types.py` | `SonicManifest`, `DialogueLine`, `VoiceConfig`, `AmbienceSpec`, `FoleyEvent` |
| TTS Engine | `src/sonic/tts_engine.py` | `BaseTTSEngine`, `SynthesizedDialogue` |
| Ambience | `src/sonic/ambience.py` | `BaseAmbienceEngine`, `SynthesizedAmbience` |
| Foley | `src/sonic/foley.py` | `BaseFoleyEngine`, `SynthesizedFoley`, `FoleyMatch` |
| Mixer | `src/sonic/mixer.py` | `AudioMixer`, `MixSpec`, `MixResult` |
| Lip Sync | `src/sonic/lip_sync.py` | `BaseLipSyncEngine`, `LipSyncSpec`, `DialogueSegment` |
| Visual RAG | `src/memory/visual_rag.py` | `VisualRAG`, `EmbeddingRecord`, `SearchResult`, `SimilarityCheck` |
| Cache | `src/memory/cache.py` | `CacheManager`, `MemoryCache`, `DiskCache`, `CacheEntry` |
| Asset Store | `src/memory/asset_store.py` | `AssetStore`, `AssetMetadata`, `LocalStorageBackend` |
| Config | `src/core/config.py` | `Config`, `GenerationConfig`, `AuditConfig` |
| Job State | `src/core/job_state.py` | `JobStatus`, `JobCheckpoint`, `AuditResult` |
| Error Recovery | `src/core/error_recovery.py` | `RetryConfig`, `DegradationLadder` |
| Workflow Loader | `src/comfy_client/workflow_loader.py` | `WorkflowLoader`, `WorkflowTemplate` (load by NAME, not path) |
| Main Orchestrator | `src/main.py` | `ContinuumOrchestrator`, `PipelineConfig`, `PipelineResult` |

---

## Error Log

### 1. Scene.__init__() Missing `title` Argument

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: Scene.__init__() missing 1 required positional argument: 'title'` |
| **Wrong Assumption** | `Scene` only needs `scene_id`, `index`, `description` |
| **Correct Interface** | `Scene` requires `title` as a required positional argument |
| **Source of Truth** | `src/director/scene_graph.py` lines 420-445 |

**Wrong:**
```python
scene = Scene(scene_id="s1", index=0, description="Test")
```

**Correct:**
```python
scene = Scene(scene_id="s1", index=0, title="Test Title", description="Test")
```

**Prevention:** Always check dataclass field order. Required fields without defaults must be provided.

---

### 2. RenderResult Missing Required Fields

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `RenderResult.__init__() missing 3 required positional arguments: 'duration_sec', 'resolution', and 'renderer_type'` |
| **Wrong Assumption** | `RenderResult` only needs `video_path`, `frame_count`, `fps`, `metadata` |
| **Correct Interface** | `RenderResult` requires 6 fields before optional ones |
| **Source of Truth** | `src/renderers/base.py` lines 200-230 |

**Wrong:**
```python
RenderResult(
    video_path=output_path,
    frame_count=120,
    fps=12.0,
    metadata={"mock": True},
)
```

**Correct:**
```python
RenderResult(
    video_path=output_path,
    frame_count=120,
    fps=12.0,
    duration_sec=10.0,
    resolution=(1280, 720),
    renderer_type=RendererType.MOCK,
    metadata={"mock": True},
)
```

**Prevention:** When mocking a dataclass, check ALL fields. Dataclass field order matters ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â required fields come before optional ones with defaults.

---

### 3. BaseRenderer Missing Abstract Methods

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: Can't instantiate abstract class MockRenderer without an implementation for abstract methods 'estimate_cost', 'estimate_time'` |
| **Wrong Assumption** | `BaseRenderer` only requires `generate()`, `initialize()`, `shutdown()` |
| **Correct Interface** | Also requires `estimate_cost(job) -> float` and `estimate_time(job) -> float` |
| **Source of Truth** | `src/renderers/base.py` lines 340-375 |

**Wrong:**
```python
class MockRenderer(BaseRenderer):
    async def generate(self, job, callback=None): ...
    async def initialize(self): ...
    async def shutdown(self): ...
```

**Correct:**
```python
class MockRenderer(BaseRenderer):
    async def generate(self, job, callback=None): ...
    async def initialize(self): ...
    async def shutdown(self): ...
    def estimate_cost(self, job: JobSpec) -> float: return 0.01
    def estimate_time(self, job: JobSpec) -> float: return 10.0
```

**Prevention:** When subclassing an ABC, grep for `@abstractmethod` to find ALL required methods:
```bash
grep -n "@abstractmethod" src/renderers/base.py
```

---

### 4. Wrong Method Name: `compare_to_reference` vs `compare`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `'MockIdentityChecker' object has no attribute 'compare_to_reference'` |
| **Wrong Assumption** | Identity checker has a `compare_to_reference(reference_path, target_path)` method |
| **Correct Interface** | Method is `compare(source_frame, target_frame, character_hint=None)` |
| **Source of Truth** | `src/audit/identity_checker.py` lines 302-321 |
| **Impact** | **This was a real bug in main.py, not just a test issue** |

**Wrong (in main.py):**
```python
comparison = await self.identity_checker.compare_to_reference(
    reference_path=ref_path,
    target_path=render_result.video_path,
)
```

**Correct:**
```python
comparison = await self.identity_checker.compare(
    source_frame=ref_path,
    target_frame=render_result.video_path,
)
```

**Prevention:** Before calling any method, verify it exists:
```bash
grep -n "def compare" src/audit/identity_checker.py
```

---

### 5. Wrong Class Name: `ComfyBridgeEngine` vs `ComfyUIBridgeEngine`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `"ComfyBridgeEngine" is not defined` |
| **Wrong Assumption** | Class is named `ComfyBridgeEngine` |
| **Correct Interface** | Class is named `ComfyUIBridgeEngine` (with "UI") |
| **Source of Truth** | `src/studio/bridge_engine.py` line 434 |

**Wrong:**
```python
from src.studio.bridge_engine import ComfyBridgeEngine
self.bridge_engine = ComfyBridgeEngine()
```

**Correct:**
```python
from src.studio.bridge_engine import ComfyUIBridgeEngine
self.bridge_engine = ComfyUIBridgeEngine()
```

**Prevention:** Use grep or IDE autocomplete to verify exact class names:
```bash
grep -n "^class.*BridgeEngine" src/studio/bridge_engine.py
```

---

### 6. Wrong Parameter Name: `base_delay` vs `base_delay_sec`

| | |
|---|---|
| **Date** | 2025-12-15 |
| **Error** | `TypeError: RetryConfig.__init__() got an unexpected keyword argument 'base_delay'` |
| **Wrong Assumption** | Parameter is named `base_delay` |
| **Correct Interface** | Parameter is named `base_delay_sec` (with `_sec` suffix) |
| **Source of Truth** | `src/core/error_recovery.py` line 155 |

**Wrong:**
```python
@retry_async(RetryConfig(max_attempts=3, base_delay=1.0))
```

**Correct:**
```python
@retry_async(RetryConfig(max_attempts=3, base_delay_sec=1.0))
```

**Prevention:** The codebase uses `_sec` suffix for time durations. Always check parameter names before using.

---

## Naming Conventions Discovered

| Pattern | Convention | Examples |
|---------|------------|----------|
| Time durations | `_sec` suffix | `base_delay_sec`, `duration_sec`, `timeout_sec` |
| ComfyUI classes | Include "UI" | `ComfyUIBridgeEngine`, `ComfyUIConfig` |
| Entity references | `EntityRef.type()` factory | `EntityRef.character("id")`, `EntityRef.location("id")` |
| Async methods | `async def` prefix | All cloud/IO operations are async |
| Abstract methods | Must implement all | Check with `grep "@abstractmethod"` |

---

## Verification Commands

Run these before assuming an interface:

```bash
# Find all required fields in a dataclass
grep -A 30 "class RenderResult" src/renderers/base.py

# Find all abstract methods in a base class
grep -n "@abstractmethod" src/renderers/base.py

# Find exact class names
grep -n "^class.*Engine" src/studio/bridge_engine.py

# Find method signatures
grep -n "def compare" src/audit/identity_checker.py

# Find parameter names
grep -A 20 "class RetryConfig" src/core/error_recovery.py
```

---

## Process Improvements

### Before Writing New Code
1. **Check source of truth file** for the interface you're using
2. **Grep for class/method names** to verify exact spelling
3. **Check ALL required fields** in dataclasses (fields without `= default` are required)
4. **Check ALL abstract methods** when subclassing ABCs

### Before Running Tests
1. Run import check: `python -c "from module import Class; print('OK')"`
2. Run collection only: `pytest tests/file.py --collect-only`
3. Then run full tests: `pytest tests/file.py -v`

### When Tests Fail
1. Read the **exact error message** ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â it usually names the missing field/method
2. Check the **source of truth file** for correct interface
3. Fix the **actual bug** (might be in test mock OR in production code)
4. **Update this document** with the lesson learned

---

## Template for New Entries

```markdown
### N. [Brief Error Description]

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Error** | `exact error message` |
| **Wrong Assumption** | What we thought |
| **Correct Interface** | What it actually is |
| **Source of Truth** | `file path` line numbers |
| **Impact** | Test issue / Real bug in production code |

**Wrong:**
\`\`\`python
# bad code
\`\`\`

**Correct:**
\`\`\`python
# good code
\`\`\`

**Prevention:** How to avoid this in future
```

---

---

### 7. ComfyUI Workflow Format: UI vs API

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `{"error": {"type": "invalid_prompt", "message": "Cannot execute because a node is missing the class_type property."}}` |
| **Wrong Assumption** | Workflow JSON files work directly with `/prompt` endpoint |
| **Correct Interface** | ComfyUI has TWO formats: UI format (`{"nodes": [...]}`) and API format (`{"node_id": {"class_type": ...}}`) |
| **Source of Truth** | ComfyUI API docs |

**Wrong:**
```python
# Submitting UI-format workflow (has "nodes" array)
workflow = json.load(open("workflow.json"))  # UI format
client.submit_workflow(workflow)  # FAILS
```

**Correct:**
```python
# Must use API format (node IDs as keys)
# Export from ComfyUI with "Save (API Format)" or convert
```

**Prevention:** Check if workflow has `"nodes"` key ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â if yes, it's UI format and needs conversion.

---

### 8. WorkflowLoader Returns Object, Not Dict

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: object of type 'WorkflowTemplate' has no len()` |
| **Wrong Assumption** | `loader.load()` returns a dict |
| **Correct Interface** | Returns `WorkflowTemplate` object with `.workflow` attribute |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
workflow = loader.load("t2v_wan21.json")
print(len(workflow))  # FAILS
```

**Correct:**
```python
template = loader.load("t2v_wan21.json")
workflow = template.workflow  # Get the actual dict
print(len(workflow))  # Works
```

---

### 9. ComfyClient Requires Explicit connect()

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ComfyConnectionError: Not connected to ComfyUI` |
| **Wrong Assumption** | Client connects automatically on first request |
| **Correct Interface** | Must call `await client.connect()` before submitting |
| **Source of Truth** | `src/comfy_client/client.py` |

**Wrong:**
```python
client = ComfyClient(host=url)
await client.submit_workflow(workflow)  # FAILS
```

**Correct:**
```python
client = ComfyClient(host=url)
await client.connect()  # REQUIRED
await client.submit_workflow(workflow)
```

---

### 10. ComfyClient Method Names

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: 'ComfyClient' object has no attribute 'queue_prompt'` |
| **Wrong Assumption** | Method names match ComfyUI API names |
| **Correct Interface** | Our wrapper uses different names |
| **Source of Truth** | `src/comfy_client/client.py` |

| Wrong | Correct |
|-------|---------|
| `ComfyUIClient` | `ComfyClient` |
| `queue_prompt()` | `submit_workflow()` |
| `get_status()` | `get_history()` |
| `load_workflow()` | `load()` |

**Prevention:** Always check: `print([m for m in dir(ComfyClient) if not m.startswith('_')])`

---

### 11. Sonic Module: AmbienceSpec Uses `type` Not `ambience_type`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: AmbienceSpec.__init__() got an unexpected keyword argument 'ambience_type'` |
| **Wrong Assumption** | Field is named `ambience_type` for clarity |
| **Correct Interface** | Field is simply `type` (matches enum name) |
| **Source of Truth** | `src/sonic/types.py` line 216 |

**Wrong:**
```python
AmbienceSpec(ambience_id="amb_001", ambience_type=AmbienceType.INTERIOR_QUIET, ...)
```

**Correct:**
```python
AmbienceSpec(ambience_id="amb_001", type=AmbienceType.INTERIOR_QUIET, ...)
```

**Prevention:** Check dataclass field names with: `grep -A 10 "class AmbienceSpec" src/sonic/types.py`

---

### 12. Sonic Module: SonicManifest Uses `manifest_id` Not `job_id`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `TypeError: SonicManifest.__init__() got an unexpected keyword argument 'job_id'` |
| **Wrong Assumption** | Uses `job_id` like other job-related classes |
| **Correct Interface** | Uses `manifest_id` and `project_id` |
| **Source of Truth** | `src/sonic/types.py` lines 358-364 |

**Wrong:**
```python
SonicManifest(job_id="job_001", shot_plans=[...])
```

**Correct:**
```python
SonicManifest(manifest_id="manifest_001", project_id="proj_001", shot_plans=[...])
```

---

### 13. Sonic Module: VoiceConfig Uses `speaking_rate` Not `speed`

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: 'VoiceConfig' object has no attribute 'speed'` |
| **Wrong Assumption** | Simple names: `speed`, `pitch` |
| **Correct Interface** | Explicit names: `speaking_rate`, `pitch_shift` |
| **Source of Truth** | `src/sonic/types.py` lines 101-107 |

**Wrong:**
```python
config.speed  # FAILS
config.pitch  # FAILS
```

**Correct:**
```python
config.speaking_rate  # 0.5 to 2.0
config.pitch_shift    # -12 to +12 semitones
```

---

### 14. WorkflowLoader.load() Takes NAME, Not Path

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | Workflow not found or wrong type |
| **Wrong Assumption** | `load()` takes a `Path` object |
| **Correct Interface** | `load()` takes workflow NAME as string (no extension, no path) |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
loader.load(Path("workflows/refine_freelong.json"))
loader.load("workflows/refine_freelong.json")
```

**Correct:**
```python
loader.load("refine_freelong")  # Just the name, loader finds the file
```

**Prevention:** WorkflowLoader manages its own workflow directory internally.

---

### 15. Cross-Module Imports Use `..` for Parent Directory

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ModuleNotFoundError: No module named 'client'` |
| **Wrong Assumption** | Can use `.client` for any sibling module |
| **Correct Interface** | Use `..module_name.file` for different parent directories |
| **Source of Truth** | Python relative import rules |

**Wrong (in src/studio/pass2_refiner.py):**
```python
from .client import ComfyClient  # FAILS - client.py is in comfy_client/, not studio/
```

**Correct:**
```python
from ..comfy_client.client import ComfyClient  # Go up to src/, then into comfy_client/
```

**Pattern:**
- `.module` = same directory
- `..module` = parent's sibling directory
- `...module` = grandparent's sibling (avoid if possible)

---

### 16. TTSProvider Has No MOCK Value

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `AttributeError: type object 'TTSProvider' has no attribute 'MOCK'` |
| **Wrong Assumption** | All provider enums have a MOCK variant |
| **Correct Interface** | `TTSProvider` only has `ELEVENLABS`, `OPENAI`, `LOCAL` |
| **Source of Truth** | `src/sonic/types.py` lines 26-30 |

**Wrong:**
```python
engine = get_tts_engine(TTSProvider.MOCK, ...)  # FAILS
```

**Correct:**
```python
# Create your own mock class for testing
class MockTTSEngine:
    provider = TTSProvider.ELEVENLABS  # Pretend to be real provider
    async def synthesize(self, line, config): ...
```

**Note:** `AmbienceProvider` and `FoleyProvider` DO have `.MOCK` variants. TTSProvider doesn't.

---

### 17. tests/conftest.py Needs Path Setup for `src` Imports

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ModuleNotFoundError: No module named 'src'` |
| **Wrong Assumption** | pytest automatically finds `src/` |
| **Correct Interface** | Must add project root to `sys.path` in conftest.py |
| **Source of Truth** | Python import system |

**Required in tests/conftest.py:**
```python
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent  # tests/ -> project root
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

**Note:** This worked in Claude's sandbox because `python -m pytest` adds current dir to path. Direct `pytest` command doesn't always do this.

---

## Claude Judgment Errors (Likely to Repeat)

> **Purpose:** Patterns where Claude's instincts lead to suboptimal decisions. These are likely to recur as the codebase grows more complex. Review before major sessions.

### J1. Hiding Warnings Instead of Questioning Them

**Error:** When IDE showed "Import 'clip' could not be resolved", immediately reached for `# type: ignore` to suppress warning.

**Better Approach:** Ask "Are these warnings useful?" - in this case, warnings served as documentation that optional dependencies aren't installed.

**Pattern to Watch:** Claude defaults to "fix the red squiggles" rather than evaluating whether warnings provide value.

---

### J2. Putting Annotations on Wrong Lines

**Error:** Added `# type: ignore` to the fallback `= None` lines instead of the actual `import` lines causing warnings.

```python
# WRONG - comment on fallback line doesn't help
except ImportError:
    clip_module = None  # type: ignore  <- This line isn't the problem

# RIGHT - comment on import line
try:
    import clip  # type: ignore[import-not-found]  <- This is what triggers warning
```

**Pattern to Watch:** When unfamiliar with syntax/tooling, Claude may place annotations mechanically without verifying they're in the correct location.

---

### J3. Over-Engineering Before Questioning Necessity

**Error:** Built elaborate optional dependency handling (module-level flags, fallback patterns, mock implementations) before asking "should we just install these dependencies?"

**Better Approach:** Ask user's intent first. Sometimes `pip install Pillow` is the right answer, not 50 lines of fallback code.

**Pattern to Watch:** Claude tends toward comprehensive solutions when simple ones suffice. As codebase grows, this creates unnecessary complexity.

---

### J4. Assuming Previous Code is Correct

**Error:** When building `pass1_generator.py`, initially trusted that existing interfaces in other files were complete and correct without verification.

**Better Approach:** Always `view` the actual source files before building integrations. Interfaces evolve and documentation may lag.

**Pattern to Watch:** As file count grows, Claude may rely on memory of files from earlier in conversation rather than re-checking current state.

---

*Add new judgment errors above this line as they're discovered.*

---

## Sonic Module Quick Reference

| Class | Required Fields | Common Mistakes |
|-------|-----------------|-----------------|
| `DialogueLine` | `line_id`, `character_id`, `text`, `start_time_sec` | `emotion` default is `None`, not `NEUTRAL` |
| `VoiceConfig` | `character_id` | `speaking_rate` not `speed`, `pitch_shift` not `pitch` |
| `AmbienceSpec` | `ambience_id`, `type`, `description`, `duration_sec` | `type` not `ambience_type` |
| `SonicManifest` | `manifest_id`, `project_id` | Not `job_id` |
| `ShotAudioPlan` | `shot_id`, `scene_id`, `duration_sec` | No `.validate()` method (it's on `SonicManifest`) |


### 18. Edge case- Workflow JSON doesn't accept `_meta` Keys

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `ValueError: Workflow validation failed: ["Node _meta: missing 'class_type'"]` |
| **Wrong Assumption** | Workflow JSONs can have `_meta` key for documentation |
| **Correct Interface** | `validate()` treats ALL keys as ComfyUI nodes |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` lines 486-493 |

**Note:** Loader skips `_` prefixed FILES but NOT `_` prefixed KEYS in workflow dict.

**Prevention:** Don't add metadata keys to workflow JSONs. Document in README or code comments.

---
###19
# ASSUMPTION: LoRAs trained on wan2.1_t2v work with wan2.1_i2v
# Both share UNet architecture. Verify if upgrading to Wan 3.x.
```

---

## Role in Architecture (Systems Thinking)

### The Bridge Frame Problem

---

## Role in Architecture (Systems Thinking)

### The Bridge Frame Problem
Shot A (ends)                    Shot B (starts)
|                                |
v                                v
+----------+                    +----------+
|Frame 144 | ---- BRIDGE -----> |Frame 1   |
+----------+                    +----------+
|                                |
| Extract last frame             | Must match:
|                                |  - Visual continuity (I2V)
v                                |  - Character identity (LoRA)
+----------------------------------------------------------+
|           pass1_img2vid_lora.json  <-- THIS FILE         |
|                                                          |
|  Inputs:                                                 |
|    - INIT_IMAGE: last frame of Shot A                    |
|    - LORA_PATH: alice_v1.safetensors                     |
|    - PROMPT: "Alice walks to the door"                   |
|                                                          |
|  Guarantees:                                             |
|    - Frame 1 of Shot B visually matches Frame 144        |
|    - Alice face remains consistent                       |
+----------------------------------------------------------+



### 20. Early Return Hides Subsequent Logic Paths

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | I2V workflows never used LoRA even when character had trained LoRA |
| **Wrong Assumption** | Sequential condition checks are safe |
| **Correct Interface** | Extract ALL state first, then make compound decision |
| **Source of Truth** | `src/renderers/wan_renderer.py` `_select_workflow_template()` |

**Wrong:**
```python
def _select_workflow_template(self, job):
    if job.has_init_frame:
        return self.WORKFLOW_IMG2VID  # Returns early, never checks LoRA!
    if job.has_lora:
        return self.WORKFLOW_WITH_LORA
```

**Correct:**
```python
def _select_workflow_template(self, job):
    has_lora = job.character_refs and job.character_refs[0].has_lora()
    if job.has_init_frame:
        if has_lora:
            return self.WORKFLOW_IMG2VID_LORA
        return self.WORKFLOW_IMG2VID
    # ... etc
```

**Prevention:** When function has multiple independent dimensions (I2V vs T2V, LoRA vs no-LoRA), extract state into booleans first, then use decision matrix.

---

### 21. Orphan Nodes Waste VRAM - Stress Tests Catch What Contract Tests Miss

### 21. Orphan Nodes Waste VRAM - Stress Tests Catch What Contract Tests Miss

| | |
|---|---|
| **Date** | 2025-12-16 |
| **Error** | `bridge_ipadapter.json` had orphan node `encode_face_ref` that nothing used |
| **Wrong Assumption** | If JSON is valid and nodes exist, workflow is correct |
| **Correct Interface** | Every node must contribute to output path |
| **Detection** | Stress test with BFS from output nodes backwards |

**The Bug:**
```json
"encode_face_ref": { ... },  // Created but never referenced
"apply_ipadapter": {
    "image": ["prep_face_ref", 0]  // Uses prep, not encode!
}
```

**Why Contract Tests Missed It:**
- JSON valid [OK]
- Node has class_type [OK]
- Node connections valid [OK]
- No dangling references [OK]

**Why Stress Test Caught It:**
- Traced backwards from SaveImage
- Found `encode_face_ref` unreachable
- Flagged as orphan (wastes VRAM)

**Prevention:** Run orphan detection on all workflows. Orphans indicate copy-paste errors or misunderstanding of node requirements.

---

### 22. Enum/Class Defined in Wrong Module - Import Path Mismatch

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `ImportError: cannot import name 'AmbienceProvider' from 'src.sonic.types'` |
| **Wrong Assumption** | All sonic enums/types are in `types.py` |
| **Correct Interface** | `AmbienceProvider` is in `ambience.py`, `FoleyProvider` is in `foley.py` |
| **Source of Truth** | Check actual file with `grep "class ClassName" src/sonic/*.py` |

**Wrong:**
```python
from src.sonic.types import (
    AmbienceProvider,  # NOT HERE
    FoleyProvider,     # NOT HERE
    DialogueLine,      # This one IS here
)
```

**Correct:**
```python
from src.sonic.ambience import AmbienceProvider
from src.sonic.foley import FoleyProvider
from src.sonic.types import DialogueLine
```

**Prevention:** Before importing, verify location:
```bash
grep -r "class AmbienceProvider" src/
```

---

### 23. Enum Value Doesn't Exist - Using Wrong Status Name

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: type object 'JobStatus' has no attribute 'RUNNING'` |
| **Wrong Assumption** | `JobStatus.RUNNING` exists |
| **Correct Interface** | Use `JobStatus.GENERATING` (the actual enum value) |
| **Source of Truth** | `src/core/job_state.py` |

**Available JobStatus values:**
```python
PENDING = "pending"
GENERATING = "generating"  # NOT "RUNNING"
AUDITING = "auditing"
FAILED = "failed"
APPROVED = "approved"
REFINING = "refining"
COMPLETE = "complete"
```

**Prevention:** Check enum definition before using:
```bash
grep -A 10 "class JobStatus" src/core/job_state.py
```

---

### 24. Mock Implementation Missing Required Interface Methods

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'MockBridgeEngine' object has no attribute 'shutdown'` |
| **Wrong Assumption** | Mocks only need to implement "active" methods |
| **Correct Interface** | Mocks must implement ALL base class methods, including lifecycle |
| **Source of Truth** | Check base class for all abstract/expected methods |

**Wrong:**
```python
class MockBridgeEngine(BaseBridgeEngine):
    async def generate(self, spec): ...
    async def health_check(self): ...
    # Missing: shutdown()
```

**Correct:**
```python
class MockBridgeEngine(BaseBridgeEngine):
    async def generate(self, spec): ...
    async def health_check(self): ...
    async def shutdown(self) -> None:
        """Mock shutdown - no cleanup needed."""
        pass
```

**Prevention:** When creating mocks, grep for all methods in base class:
```bash
grep -n "async def\|def " src/studio/bridge_engine.py | grep -A5 "class Base"
```

---

### 25. main.py Calls Methods That Don't Exist in Implementation

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'CheckpointManager' object has no attribute 'get_completed_scenes'` |
| **Wrong Assumption** | main.py and CheckpointManager are in sync |
| **Correct Interface** | main.py was written expecting methods that were never implemented |
| **Source of Truth** | `src/core/checkpointing.py` |

**Methods main.py expects but didn't exist:**
- `get_completed_scenes()` 
- `mark_scene_complete(scene_id)`

**Fix:** Add missing methods to CheckpointManager:
```python
def get_completed_scenes(self) -> set:
    """Get set of completed scene IDs."""
    completed = set()
    for job in self.get_all_jobs():
        if job.status == JobStatus.COMPLETE and job.scene_id:
            completed.add(job.scene_id)
    return completed

def mark_scene_complete(self, scene_id: str) -> None:
    """Mark a scene as complete."""
    logger.info(f"Scene {scene_id} marked complete")
```

**Prevention:** When main.py calls a method, verify it exists:
```bash
grep -n "def method_name" src/core/checkpointing.py
```

---

### 26. Dataclass Missing Required Argument in Constructor Call

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: InterpolationSpec.__init__() missing 1 required positional argument: 'shot_id'` |
| **Wrong Assumption** | Only path and fps arguments needed |
| **Correct Interface** | `shot_id` is required (no default value) |
| **Source of Truth** | `src/studio/rife_interpolator.py` |

**Wrong:**
```python
spec = InterpolationSpec(
    input_path=video_path,
    output_path=output_path,
    target_fps=target_fps,
)
```

**Correct:**
```python
spec = InterpolationSpec(
    input_path=video_path,
    output_path=output_path,
    shot_id=shot_output.shot_id,  # Required!
    target_fps=target_fps,
)
```

**Prevention:** Check dataclass definition for required fields (those without `= default`):
```bash
grep -A 15 "class InterpolationSpec" src/studio/rife_interpolator.py
```

---

### 27. JSON Schema Mismatch - EntityRef Requires Objects, Not Strings

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: EntityRef() argument after ** must be a mapping, not str` |
| **Wrong Assumption** | Characters can be listed as string IDs: `["alice", "bob"]` |
| **Correct Interface** | Characters must be EntityRef objects with `entity_id`, `entity_type`, `display_name` |
| **Source of Truth** | `src/director/scene_graph.py` - `Shot.from_dict()` |

**Wrong (sample_project.json):**
```json
"characters": ["alice"]
```

**Correct:**
```json
"characters": [
  {
    "entity_id": "alice",
    "entity_type": "character",
    "display_name": "Alice"
  }
]
```

**Prevention:** Always check `from_dict()` method to see expected JSON structure:
```bash
grep -A 20 "def from_dict" src/director/scene_graph.py
```

---

### 28. I2V Workflow Node Parameter Mismatches

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `Required input is missing: batch_size` and `unexpected keyword argument 'image'` |
| **Wrong Assumption** | Workflow template has all required parameters |
| **Correct Interface** | WanImageToVideo node requires `batch_size` and uses `start_image` not `image` |
| **Source of Truth** | ComfyUI node definition / error messages |

**Fixes applied to `pass1_img2vid.json`:**
```python
# Missing parameter
workflow['wan_i2v']['inputs']['batch_size'] = 1

# Wrong parameter name
workflow['wan_i2v']['inputs']['start_image'] = workflow['wan_i2v']['inputs'].pop('image')
```

**Prevention:** Test workflows against actual ComfyUI before committing. Error messages tell you exactly what's wrong.

---

### 29. Nested Config Access - Using Wrong Attribute Path

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `AttributeError: 'Config' object has no attribute 'comfyui_host'` |
| **Wrong Assumption** | Config fields are flat: `config.comfyui_host` |
| **Correct Interface** | Config is nested: `config.comfyui.host` |
| **Source of Truth** | `src/core/config.py` |

**Config structure is NESTED:**
```python
# Wrong - flat access
config.comfyui_host        # WRONG
config.comfyui_port        # WRONG
config.workflows_dir       # WRONG

# Correct - nested access
config.comfyui.host        # CORRECT
config.comfyui.timeout_sec # CORRECT
config.paths.workflows_dir # CORRECT
```

**Nested config classes:**
-  `config.comfyui` --> `ComfyUIConfig`
-  `config.paths` --> `PathsConfig`
-  `config.generation` --> `GenerationConfig`
-  `config.audit` --> `AuditConfig`
-  `config.sonic` --> `SonicConfig`
-  `config.post` --> `PostConfig`

**Prevention:** Check config.py for nested structure before accessing:
```bash
grep -n "class.*Config" src/core/config.py
```

---

### 30. Environment Variable Naming for Nested Pydantic Settings

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | Environment variable `COMFYUI_URL` ignored, still using localhost |
| **Wrong Assumption** | Env var name matches the field name |
| **Correct Interface** | Use `CONTINUUM_` prefix + double underscore for nesting |
| **Source of Truth** | `src/core/config.py` line 409 |

**Pydantic BaseSettings env var convention:**
```bash
# Pattern: {PREFIX}_{SECTION}__{FIELD}
# Note the DOUBLE underscore between section and field

# Wrong
export COMFYUI_URL="wss://..."           # WRONG - Ignored
export COMFYUI_HOST="wss://..."          # WRONG - Ignored

# Correct  
export CONTINUUM_COMFYUI__HOST="wss://..."    # CORRECT - Works
export CONTINUUM_COMFYUI__TIMEOUT_SEC=600     # CORRECT - Works
export CONTINUUM_PATHS__WORKFLOWS_DIR="/x"    # CORRECT - Works
```

**Key rules:**
1. Prefix is `CONTINUUM_` (from Config class)
2. Double underscore `__` separates nested config sections
3. Field names are uppercase

**Prevention:** Check config.py for `env_prefix` and examples:
```bash
grep -n "CONTINUUM_" src/core/config.py
```


---

### 31. Passing Dict When Function Expects Dataclass

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'dict' object has no attribute 'source_exists'` |
| **Wrong Assumption** | Any dict-like structure works |
| **Correct Interface** | Must pass the actual dataclass type |
| **Source of Truth** | Function signature |

**Pattern:** Function accepts `spec: BridgeSpec` but caller passes a dict:
```python
# Wrong - passing a dict
bridge_request = {
    "source_video": previous_output.video_path,
    "target_shot": shot,
}
result = await bridge_engine.generate(bridge_request)  # WRONG - Fails

# Correct - use the dataclass
spec = BridgeSpec.from_shots(
    shot_a_last_frame=last_frame_path,
    shot_b_prompt=shot.prompt,
    shot_b_characters=[],
)
result = await bridge_engine.generate(spec)  # CORRECT - Works
```

**Prevention:** Always check the function signature and use proper types. Look for factory methods like `Dataclass.from_something()` that make construction easier.

---

### 32. Method Naming Inconsistency Between Components

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'ComfyClient' object has no attribute 'upload_image'` and `'ComfyClient' object has no attribute 'submit'` |
| **Component** | `bridge_engine.py`, `rife_interpolator.py` calling `client.py` |

**Wrong Assumption:** Components calling `ComfyClient` assumed methods named `upload_image` and `submit` existed.

**Reality:** The actual method names were:
-  `upload_file()` -- generic file upload returning dict
-  `submit_workflow()` -- workflow submission

**Why It Happened:** Different developers or different development phases used different naming conventions. Bridge engine was written expecting simpler method names that matched the semantic action (upload_image, submit) while the client used more explicit names (upload_file, submit_workflow).

**Fix:** Added alias methods to ComfyClient:
```python
async def upload_image(self, image_path: Path, subfolder: str = "") -> str:
    """Alias for upload_file that returns just the filename."""
    result = await self.upload_file(image_path, subfolder=subfolder, file_type="input")
    return result.get("name", image_path.name)

async def submit(self, workflow: Dict[str, Any]) -> ComfyJob:
    """Alias for submit_workflow for backward compatibility."""
    return await self.submit_workflow(workflow)
```

**Prevention:** 
1. Define canonical method names in base classes/interfaces
2. When adding new callers, check exact method names in the implementation
3. Add aliases when method naming diverges to maintain backward compatibility

---

### 33. WorkflowLoader Method Name: `inject` not `inject_params`

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `'WorkflowLoader' object has no attribute 'inject_params'` |
| **Wrong Assumption** | Method is named `inject_params(workflow, params)` |
| **Correct Interface** | Method is `inject(template, params)` or convenience method `load_and_inject(name, params)` |
| **Source of Truth** | `src/comfy_client/workflow_loader.py` |

**Wrong:**
```python
workflow = self.workflow_loader.load(workflow_name)
workflow = self.workflow_loader.inject_params(workflow, params)  # WRONG
```

**Correct:**
```python
# Option 1: Two-step
template = self.workflow_loader.load(workflow_name)
result = self.workflow_loader.inject(template, params)
workflow = result.workflow

# Option 2: One-step (preferred)
workflow = self.workflow_loader.load_and_inject(workflow_name, params)  # CORRECT
```

**Prevention:** Check WorkflowLoader methods:
```bash
grep -n "def inject\|def load_and_inject" src/comfy_client/workflow_loader.py
```

---

### 34. ComfyClient Constructor - Host Contains Full URL, No Port Parameter

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `TypeError: ComfyClient.__init__() got an unexpected keyword argument 'port'` |
| **Wrong Assumption** | Constructor takes separate `host` and `port` parameters |
| **Correct Interface** | `host` is the full WebSocket URL including port |
| **Source of Truth** | `src/comfy_client/client.py` |

**Wrong:**
```python
ComfyClient(
    host=config.comfyui.host,
    port=config.comfyui.port,  # WRONG - Parameter does not exist
)
```

**Correct:**
```python
ComfyClient(
    host=config.comfyui.host,  # Full URL like "wss://...proxy.runpod.net:8188"
)
# OR
ComfyClient(
    config=config.comfyui,  # Pass entire ComfyUIConfig object
)
```

**Prevention:** The `host` field already contains the full URL with port. Check ComfyUIConfig:
```bash
grep -A 10 "class ComfyUIConfig" src/core/config.py
```

---

### 35. ComfyUI KSampler Seed Must Be >= 0

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Error** | `Value -1 smaller than min of 0` for seed parameter |
| **Wrong Assumption** | Seed value `-1` means "random" (like some libraries) |
| **Correct Interface** | KSampler requires seed >= 0, must generate random value explicitly |
| **Source of Truth** | ComfyUI KSampler node validation |

**Wrong:**
```python
params = {
    "SEED": spec.seed if spec.seed >= 0 else -1,  # WRONG - -1 is invalid
}
```

**Correct:**
```python
import random
params = {
    "SEED": spec.seed if spec.seed >= 0 else random.randint(0, 2**32 - 1),  # CORRECT
}
```

**Prevention:** ComfyUI nodes validate inputs strictly. Never assume sentinel values like `-1` are accepted. When in doubt, check ComfyUI node definitions or test with ComfyUI UI.

---

### 36. Architecture Mismatch: Wrong Model Family for Bridge Frames

| | |
|---|---|
| **Date** | 2025-12-17 |
| **Issue** | `bridge_basic.json` uses SDXL for bridge frame generation |
| **Wrong Assumption** | SDXL img2img is suitable for creating continuity between Wan video shots |
| **Correct Approach** | Use Wan I2V (Image-to-Video) to maintain visual consistency |

**Why SDXL Bridge Was Wrong:**
1. SDXL generates a single static image, not video
2. Different model family than Wan = style mismatch risk
3. Requires extra 6.5GB model download
4. Generated bridge image never actually gets used by Shot 2

**Correct Architecture:**
Shot 1 last frame --> Wan I2V (pass1_img2vid) --> Shot 2 video
Instead of:
Shot 1 last frame --> SDXL img2img --> Bridge image --> ??? (dead end)

**Prevention:** When designing cross-shot continuity:
1. Use the same model family for all shots
2. Leverage I2V (image-to-video) capabilities of the primary renderer
3. Don't introduce additional model dependencies without clear benefit

---

### 37. Workflow JSON `_meta` Nodes Break ComfyUI Validation

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Workflow validation failed: ["Node _meta: missing 'class_type'"]` |
| **Wrong Assumption** | Can include `_meta` documentation node in workflow JSON |
| **Correct Interface** | Every top-level key in workflow JSON must be a valid ComfyUI node with `class_type` |

**Wrong:**
```json
{
  "_meta": {
    "title": "My Workflow",
    "version": "1.0.0"
  },
  "load_image": {
    "class_type": "LoadImage",
    ...
  }
}
```

**Correct:**
```json
{
  "load_image": {
    "class_type": "LoadImage",
    ...
  }
}
```

**Prevention:** Don't add metadata nodes to workflow JSON. If documentation is needed, use comments in a separate file or rely on `_description` fields in `models.json`.

---

### 38. ComfyJob Uses `prompt_id` Not `job_id`

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `'ComfyJob' object has no attribute 'job_id'` |
| **Wrong Assumption** | Job identifier is called `job_id` |
| **Correct Interface** | Use `job.prompt_id` for job identification |
| **Source of Truth** | `src/comfy_client/client.py` ComfyJob dataclass |

**Wrong:**
```python
job = await client.submit(workflow)
result = await client.wait_for_completion(job.job_id)  # WRONG
```

**Correct:**
```python
job = await client.submit(workflow)
result = await client.wait_for_completion(job.prompt_id)  # CORRECT
```

**Prevention:** Check ComfyJob dataclass definition before using attributes:
```bash
grep -A 15 "class ComfyJob" src/comfy_client/client.py
```

---

### 39. ComfyJob Outputs Are Nested Dict, Not `output_images` List

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `'ComfyJob' object has no attribute 'output_images'` |
| **Wrong Assumption** | Outputs are in `job.output_images[0]` |
| **Correct Interface** | Outputs are in `job.outputs` dict keyed by node_id |
| **Source of Truth** | WanRenderer._download_output pattern |

**Wrong:**
```python
await client.download_output(job.output_images[0], save_path)  # WRONG
```

**Correct:**
```python
for node_id, outputs in job.outputs.items():
    if "images" in outputs:
        items = outputs["images"]
        if items:
            await client.download_output(
                filename=items[0].get("filename"),
                subfolder=items[0].get("subfolder", ""),
                file_type="output",
                save_path=save_path
            )
            break
```

**Prevention:** Follow existing patterns in WanRenderer. The output structure is:
```python
job.outputs = {
    "node_id": {
        "images": [{"filename": "...", "subfolder": "..."}]
        # OR
        "gifs": [{"filename": "...", "subfolder": "..."}]
    }
}
```

---

### 40. SceneGraph Requires Full Schema - Shots Need `scene_id` Inside Them

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `KeyError: 'scene_id'` when parsing Shot |
| **Wrong Assumption** | Minimal JSON with just `id`, `duration`, `prompt` is sufficient |
| **Correct Interface** | Each shot must include `shot_id`, `scene_id`, `index`, `duration_sec`, etc. |

**Wrong:**
```json
{
  "shots": [
    {"id": "shot_01", "duration": 1.0, "prompt": "..."}
  ]
}
```

**Correct:**
```json
{
  "shots": [
    {
      "shot_id": "shot_01",
      "scene_id": "scene_01",
      "index": 0,
      "duration_sec": 1.0,
      "prompt": "...",
      "shot_type": "medium",
      "characters": [],
      "props": [],
      "chunks": [],
      "dialogue": []
    }
  ]
}
```

**Prevention:** Use existing test files as templates:
```bash
cat tests/sample_project_2shot.json
```

---

### 41. I2V 14B Models Need Extended Timeout (15-20 min, not 5 min)

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Job timed out after 300s` during I2V generation |
| **Wrong Assumption** | 5 minute timeout is sufficient for all Wan models |
| **Correct Interface** | I2V uses 14B model (vs T2V 1.3B), needs 10-20 minute timeout |

| Model | Params | Typical Gen Time (4s video) |
|-------|--------|----------------------------|
| T2V 1.3B | 1.3 billion | ~2-3 min |
| I2V 14B | 14 billion | ~15-20 min |

**Fix:**
```bash
export CONTINUUM_COMFYUI__TIMEOUT_SEC=1200  # 20 minutes
```

**Prevention:** When switching from T2V to I2V, remember the model size difference. There's no smaller I2V variant in Wan 2.1.

---

### 42. DWPreprocessor Requires comfyui_controlnet_aux Custom Node

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Cannot execute because node DWPreprocessor does not exist` |
| **Wrong Assumption** | Pose detection nodes are built into ComfyUI |
| **Correct Interface** | Must install ControlNet Preprocessors custom node pack |

**Installation (RunPod):**
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
pip install -r comfyui_controlnet_aux/requirements.txt
# Restart ComfyUI
```

**Alternative Nodes Available After Install:**
- `DWPreprocessor` (DWPose - recommended)
- `OpenposePreprocessor` (OpenPose)
- `DepthAnythingV2Preprocessor` (Depth estimation)

**Prevention:** Before creating workflows that use preprocessors, verify nodes exist:
```bash
# Check installed custom nodes
ls /workspace/runpod-slim/ComfyUI/custom_nodes/
```

---


### 43. Relative Import Across Package Boundaries

### 43. Relative Import Across Package Boundaries

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `No module named 'src.studio.reviewer'` |
| **Wrong Assumption** | Used `from .reviewer import ReviewRequest` in `pass1_generator.py` |
| **Correct Interface** | Reviewer is in `src/audit/`, not `src/studio/` -- use `from src.audit.reviewer import ReviewRequest` |
| **Source of Truth** | Check import statements in `main.py` to see actual module paths |
| **Prevention** | Relative imports (`.module`) only work within same package. Cross-package requires absolute import. |

---
---

### 44. Scene Has `duration_sec`, Not `total_duration_sec`

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `AttributeError: 'Scene' object has no attribute 'total_duration_sec'` |
| **Wrong Assumption** | Scene property follows `total_` naming pattern |
| **Correct Interface** | Scene uses `duration_sec` (property that sums shot durations) |
| **Source of Truth** | `src/director/scene_graph.py` line 387-389 |

**Wrong:**
```python
duration_sec=scene.total_duration_sec
```

**Correct:**
```python
duration_sec=scene.duration_sec
```

**Prevention:** Check scene_graph.py for exact property names before using. Scene has `duration_sec`, `shot_count`, `chunk_count` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â none have `total_` prefix.

---

### 45. Workflow Names Must Match Existing JSON Files

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Workflow template 'refine_freelong' not found in workflows` |
| **Wrong Assumption** | Workflow mapping could use planned names before files created |
| **Correct Interface** | Workflow names must match actual `.json` files in repository |
| **Source of Truth** | Files in project root: `ls *.json` |

**Available refine workflows:**
- `refine_vid2vid_simple.json` ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã¢â‚¬Å“ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦
- `refine_vid2vid_temporal.json` ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã¢â‚¬Å“ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦
- `refine_freelong.json` ÃƒÆ’Ã‚Â¢Ãƒâ€šÃ‚ÂÃƒâ€¦Ã¢â‚¬â„¢ (doesn't exist)

**Prevention:** Before adding workflow mappings, verify the `.json` file exists:
```bash
ls *.json | grep -i refine
```

---

### 46. ArcFace Similarity Can Exceed 1.0 ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â Clamp Derived Values

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `Severity must be 0.0-1.0, got 1.0883083045482635` |
| **Wrong Assumption** | Cosine similarity is always in [0, 1] range |
| **Correct Interface** | Floating point precision can cause similarity > 1.0, so `1.0 - similarity` can be negative |
| **Source of Truth** | AuditFlag in `src/core/job_state.py` validates severity in `__post_init__` |

**Wrong:**
```python
severity=1.0 - (comparison.similarity or 0.0)
```

**Correct:**
```python
severity=max(0.0, min(1.0, 1.0 - (comparison.similarity or 0.0)))
```

**Prevention:** Any value that feeds into a bounded dataclass field must be clamped to that range first.

---

### 47. ComfyClient Connections Require Explicit shutdown() in Engines

| | |
|---|---|
| **Date** | 2025-12-19 |
| **Error** | `ERROR | asyncio | Unclosed client session` at pipeline end |
| **Wrong Assumption** | Python garbage collection will clean up aiohttp sessions |
| **Correct Interface** | Each engine with `_client: ComfyClient` must implement `shutdown()` that calls `_client.disconnect()` |
| **Source of Truth** | `src/comfy_client/client.py` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â `disconnect()` method closes aiohttp session |

**Pattern for Base Classes:**
```python
class BaseEngine(ABC):
    async def shutdown(self) -> None:
        """Default no-op. Override if holding resources."""
        pass  # Subclasses override if needed
```

**Pattern for ComfyUI Implementations:**
```python
class ComfyUIEngine(BaseEngine):
    def __init__(self):
        self._client = None  # Lazy initialized
    
    async def shutdown(self) -> None:
        """Disconnect from ComfyUI and release resources."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error during shutdown: {e}")
            finally:
                self._client = None  # Clear reference even on error
```

**Files Updated with This Pattern:**
- `pass2_refiner.py` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â `BaseRefiner`, `ComfyUIRefiner`
- `lip_sync.py` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â `BaseLipSyncEngine`, `MusetalkComfyEngine`
- `rife_interpolator.py` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â `BaseInterpolator`, `ComfyRIFEInterpolator`

**Prevention:** When creating any new engine that uses `ComfyClient`:
1. Add `_client = None` in `__init__`
2. Use lazy initialization in `_get_client()`
3. Implement `shutdown()` that disconnects and clears `_client`
4. Ensure `main.py` calls `shutdown()` during pipeline teardown

---

### 48. RIFE VFI Node Installation on RunPod

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node RIFE VFI does not exist` |
| **Wrong Assumption** | Frame interpolation nodes are built into ComfyUI |
| **Correct Interface** | Must install ComfyUI-Frame-Interpolation custom node + download model |

**Installation Steps (RunPod):**
```bash
# 1. Clone the node
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation

# 2. Install dependencies (use no-cupy to avoid CUDA detection issues)
pip3 install -r ComfyUI-Frame-Interpolation/requirements-no-cupy.txt

# 3. Set backend to taichi (avoids cupy issues)
sed -i 's/ops_backend: "cupy"/ops_backend: "taichi"/' ComfyUI-Frame-Interpolation/config.yaml

# 4. Download RIFE model
mkdir -p ComfyUI-Frame-Interpolation/ckpts
cd ComfyUI-Frame-Interpolation/ckpts
wget -O rife47.pth "https://github.com/styler00dollar/VSGAN-tensorrt-docker/releases/download/models/rife47.pth"

# 5. Restart ComfyUI
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Verify Installation:**
```bash
# Check node loaded (look for "ComfyUI-Frame-Interpolation" in import times)
tail -50 /workspace/runpod-slim/comfyui.log | grep -i "frame-interp"

# Check server is healthy
curl -s http://localhost:8188/system_stats
```

**Workflow File:** `rife_interpolation.json` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â uses `RIFE VFI` node with `rife47.pth`

**Note:** This installation is on persistent storage (`/workspace/`) so it survives pod restarts. However, you must restart ComfyUI after a fresh pod start to load the node.

---

### 49. Enum Names Must Match Definition Exactly

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `AttributeError: type object 'FoleyCategory' has no attribute 'DOORS'. Did you mean: 'DOOR'?` |
| **Wrong Assumption** | Enum names can be guessed (pluralized, past tense, etc.) |
| **Correct Interface** | Check actual enum definition in `types.py` |

**Wrong ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ Correct Mappings:**
```python
FoleyCategory.DOORS       ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ FoleyCategory.DOOR
FoleyCategory.ELECTRONICS ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ FoleyCategory.ELECTRONIC
FoleyCategory.HANDLING    ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ FoleyCategory.OBJECT
AudioGenerationStatus.COMPLETED ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ AudioGenerationStatus.COMPLETE
```

**Prevention:** Before using any enum, verify the exact values:
```bash
grep -A 15 "class EnumName" src/core/types.py
```

---

### 50. ComfyUI Workflows Need Local Files Uploaded First

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Invalid video file: workspace/output/t2v_00045_.mp4` |
| **Wrong Assumption** | ComfyUI can access local file paths passed in workflow |
| **Correct Interface** | Files must be uploaded to ComfyUI server first via `client.upload_file()` |

**Wrong (local path):**
```python
params = {
    "INPUT_VIDEO": str(spec.input_path),  # ÃƒÆ’Ã‚Â¢Ãƒâ€šÃ‚ÂÃƒâ€¦Ã¢â‚¬â„¢ Local path doesn't exist on server
}
```

**Correct (upload first):**
```python
# Upload file to ComfyUI server
upload_result = await client.upload_file(spec.input_path, subfolder="", file_type="input")
remote_name = upload_result.get("name", spec.input_path.name)

params = {
    "INPUT_VIDEO": remote_name,  # ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã¢â‚¬Å“ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ Use remote filename
}
```

**Prevention:** Any workflow that takes file input needs to upload first. Check bridge_engine.py for the pattern.

---

### 51. RIFE VFI Node Requires clear_cache_after_n_frames Parameter

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Required input is missing: clear_cache_after_n_frames` |
| **Wrong Assumption** | Optional parameters have defaults |
| **Correct Interface** | `RIFE VFI` node requires `clear_cache_after_n_frames` explicitly |

**Fix in workflow JSON:**
```json
"rife_interpolate": {
  "class_type": "RIFE VFI",
  "inputs": {
    "ckpt_name": "rife47.pth",
    "clear_cache_after_n_frames": 10,  // ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â Ãƒâ€šÃ‚Â Required, prevents OOM
    ...
  }
}
```

**Prevention:** Test workflows in ComfyUI UI before committing to JSON. Missing required inputs show immediately in the UI.

---

### 52. RIFE Interpolator - Multiplier Type Must Match Result Type

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `unsupported operand type(s) for *: 'dict' * 'float'` |
| **Wrong Assumption** | `result.duration_sec` is always a float |
| **Correct Interface** | When workflow returns, result may be dict-like before proper parsing |
| **Source of Truth** | `src/studio/rife_interpolator.py` - `interpolate()` method |

**Context:** The RIFE interpolator submits a ComfyUI job, but when calculating the interpolated duration (original_duration * multiplier), the result object hasn't been properly converted to `InterpolationResult` yet.

**Fix needed in `rife_interpolator.py`:**
```python
# Ensure duration is extracted as float before multiplication
original_duration = float(result.get("duration_sec", 0) if isinstance(result, dict) else result.duration_sec)
interpolated_duration = original_duration * spec.multiplier
```

**Prevention:** Always verify the type of intermediate values when chaining operations, especially after async workflows return.

---

### 53. MixResult Object Does Not Have `.success` Attribute

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `'MixResult' object has no attribute 'success'` |
| **Wrong Assumption** | `MixResult` has a boolean `success` field |
| **Correct Interface** | Check `MixResult` dataclass in `src/sonic/mixer.py` for actual fields |
| **Source of Truth** | `src/sonic/mixer.py` - `MixResult` dataclass |

**Wrong (in main.py):**
```python
if mix_result.success:
    # handle success
```

**Correct (check actual fields):**
```python
if mix_result.output_path and mix_result.output_path.exists():
    # handle success
# Or check duration:
if mix_result.duration_sec > 0:
    # handle success
```

**Prevention:** Always verify dataclass fields before accessing:
```bash
grep -A 10 "class MixResult" src/sonic/mixer.py
```

---

### 54. FFmpeg Frame Extraction May Fail on Short Videos

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Expected output file not created: .../color_temp/sample_t2v_00055__04.png` |
| **Wrong Assumption** | FFmpeg will always extract the requested number of frames |
| **Correct Interface** | Short videos (< 1 second) may not have enough frames to sample |
| **Source of Truth** | `src/post/color_match.py` - frame extraction logic |

**Context:** The color matcher tries to extract 5 evenly-spaced frames for histogram analysis. A 0.8-second video at 12fps only has ~10 frames total, and FFmpeg's select filter may skip requested frames.

**Fix needed:** Add frame count check before extraction:
```python
# Get video duration/frame count first
probe = await ffprobe(video_path)
total_frames = int(probe.get("nb_frames", 0))

# Adjust sample count for short videos
sample_count = min(5, total_frames // 2)  # At least 2 frames between samples
```

**Prevention:** Any FFmpeg operation that samples frames should first verify the video has enough frames.

---

### 55. KSamplerBatch Node Not Available in Default ComfyUI

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node KSamplerBatch does not exist` |
| **Wrong Assumption** | KSamplerBatch is a standard ComfyUI node |
| **Correct Interface** | It's from ComfyUI-KJNodes custom node package |
| **Workflow Affected** | `refine_vid2vid_temporal.json` |

**Status:** ComfyUI-KJNodes IS installed on RunPod but node not loading. May need:
1. Restart ComfyUI after fresh pod start
2. Check for dependency conflicts
3. Verify KSamplerBatch still exists in latest KJNodes version

**Workaround:** Use `refine_vid2vid_simple.json` which uses standard KSampler instead:
```python
# In pass2_refiner.py template selection
template_name = "refine_vid2vid_simple"  # Fallback that works
```

**Investigation Commands:**
```bash
grep -r "KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-KJNodes/
# If not found, the node may have been renamed or removed in newer versions
```

---

### 56. DWPreprocessor Node Requires Model Download

| | |
|---|---|
| **Date** | 2025-12-20 |
| **Error** | `Cannot execute because node DWPreprocessor does not exist` |
| **Wrong Assumption** | controlnet_aux nodes are ready to use after installation |
| **Correct Interface** | DWPreprocessor needs DWPose models downloaded separately |
| **Workflow Affected** | `bridge_pose_extract.json` |

**Status:** `comfyui_controlnet_aux` IS installed but DWPreprocessor not loading. Likely cause:
1. DWPose models not downloaded
2. ONNX runtime not installed
3. Dependency conflict

**Current Fallback:** Bridge engine falls back to `ipadapter_only` method when pose extraction fails. This works but produces less consistent results.

**Fix (on RunPod):**
```bash
# Install onnxruntime
pip3 install onnxruntime-gpu

# Download DWPose models
cd /workspace/runpod-slim/ComfyUI/custom_nodes/comfyui_controlnet_aux
python3 -c "from src.controlnet_aux.dwpose import DWposeDetector; DWposeDetector()"

# Restart ComfyUI
```

**Alternative:** Create `bridge_openpose.json` using OpenPosePreprocessor which may be more reliable.


57. ComfyJob.progress is a Dict, Not a Float
Date2025-12-20Errorunsupported operand type(s) for *: 'dict' * 'float'Wrong Assumptionjob.progress is a float representing completion percentageCorrect Interfacejob.progress is a Dict[str, Any] with "value" and "max" keysSource of Truthsrc/comfy_client/client.py lines 63, 644-645
Wrong:
pythonif job.progress:
    progress_pct = 0.4 + (job.progress * 0.5)  # ÃƒÂ¢Ã‚ÂÃ…â€™ dict * float
Correct:
pythonif job.progress:
    progress_value = job.progress.get("value", 0)
    progress_max = job.progress.get("max", 100)
    progress_pct = float(progress_value) / float(progress_max) if progress_max > 0 else 0.0
    final_progress = 0.4 + (progress_pct * 0.5)  # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦
Prevention: Always check the type of ComfyJob fields in client.py before using them. Progress updates from WebSocket are stored as dicts.

58. MixResult Has .status, Not .success
Date2025-12-20Error'MixResult' object has no attribute 'success'Wrong AssumptionMixResult has a .success boolean like other result classesCorrect InterfaceMixResult uses .status (AudioGenerationStatus enum) and .output_pathSource of Truthsrc/sonic/types.py lines 424-455
Wrong:
pythonif result.success:  # ÃƒÂ¢Ã‚ÂÃ…â€™ AttributeError
    use(result.output_path)
Correct:
pythonif result.status == AudioGenerationStatus.COMPLETE and result.output_path:  # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦
    use(result.output_path)
Prevention: Check the actual dataclass definition before assuming field names. Not all *Result classes have the same interface.

59. Short Videos Break Frame Extraction Assumptions
Date2025-12-20ErrorExpected output file not created: sample_t2v_00055__04.pngWrong AssumptionAll videos have enough duration to sample 5 frames at [0.1, 0.3, 0.5, 0.7, 0.9] positionsCorrect InterfaceVideos under 2 seconds may fail frame extraction at late positionsSource of Truthsrc/post/color_match.py _extract_sample_frames()
Wrong:
pythonfor pos in [0.1, 0.3, 0.5, 0.7, 0.9]:  # ÃƒÂ¢Ã‚ÂÃ…â€™ Assumes video is long enough
    time_sec = duration * pos
    await extract_frame(video, output, time_sec)
Correct:
python# Adjust sample count for short videos
if duration < 2.0:
    effective_samples = max(1, min(2, int(duration * 2)))
elif duration < 5.0:
    effective_samples = min(3, requested_samples)
# Also: wrap extract_frame in try/except, validate file exists
Prevention: Any time-based sampling must handle edge cases:

Very short videos (< 2s)
Empty/corrupt videos (0 duration)
Extraction failures (missing output file)

60. Wan I2V Does NOT Need IP-Adapter ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Identity Comes from Bridge Frame
Date2025-12-21Wrong AssumptionNeed to create pass1_img2vid_ipadapter.json workflow for identity in I2VCorrect ArchitectureIdentity is locked at Bridge Engine stage (SDXL + IP-Adapter), then passed to Wan I2V via CLIP Vision encoding of the bridge frameSource of TruthARCHITECTURE_SUMMARY.md Section 2: "Identity lock survives; the style doesn't matter"
Why this matters:

Wan 2.1 does NOT have native IP-Adapter support in ComfyUI
The WORKFLOW_IMG2VID_IPADAPTER constant in wan_renderer.py is a placeholder that should NOT be implemented
Correct flow: Bridge Engine (SDXL+IPAdapter) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ bridge_frame.png ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Wan I2V (CLIP Vision encodes frame)

Prevention: Don't try to add IP-Adapter to Wan workflows. Identity anchoring happens BEFORE video generation.

---
---
### 61. World State Tracking ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Full Implementation Pattern

| | |
|---|---|
| **Date** | 2025-12-21 |
| **Category** | Architecture Pattern (not a bug) |
| **Problem** | Props "teleport" between shots because system forgets state changes |
| **Solution** | Event-sourced World State with parser integration |
| **Source of Truth** | ARCHITECTURE.md, ARCHITECTURE_SUMMARY.md Section 4 |

**The Problem:**

Without dynamic state tracking, continuity breaks:
- Shot 3: "Alice picks up the sword"
- Shot 4: Alice rendered without sword (system forgot the pickup)
- Shot 5: Sword back on table (teleportation)

**The Solution ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 4 File Pattern:**

| File | Role | Key Addition |
|------|------|--------------|
| `shot_event_parser.py` | Extracts events from descriptions | Pattern matching + explicit events |
| `scene_graph.py` | Stores explicit events | `Shot.events: List[Dict]` field |
| `main.py` | Wires parser to WorldState | `_update_world_state_from_shot()` |
| `pass1_generator.py` | Injects state into prompts | `_get_world_state_context()` |

**Data Flow:**
Shot.description ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ShotEventParser ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬â€œÃ‚Âº List[StateEvent]
Shot.events ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ‹Å“                              ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡
ÃƒÂ¢Ã¢â‚¬â€œÃ‚Â¼
WorldState.apply_event()
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡
ÃƒÂ¢Ã¢â‚¬â€œÃ‚Â¼
Next shot's prompt includes:
"Current scene state: sword: held by alice"

**Key Design Decisions:**

1. **Pattern Matching (No LLM):** ShotEventParser uses regex, not AI. Catches ~80% of common actions. Explicit events in scene graph handle the rest.

2. **Explicit Override:** Scene graph can declare events directly:
```json
   {
     "events": [
       {"type": "pickup", "subject": "alice", "object": "sword"}
     ]
   }
```

3. **Focused Context:** Only entities IN THE CURRENT SHOT get their state injected into prompts. Avoids cluttering with irrelevant info.

4. **Config Flag:** `GenerationConfig.enable_world_state` allows disabling for testing.

5. **Fail-Safe:** All world state operations wrapped in try/except. Pipeline continues if tracking fails.

**Event Types Supported:**

| Event Type | Example Description | Result |
|------------|---------------------|--------|
| `pickup` | "Alice picks up the sword" | `sword.position = held_by:alice` |
| `drop` | "She drops the mug" | `mug.position = floor` |
| `move` | "He places the book on the table" | `book.position = table` |
| `state_change` | "The mirror shatters" | `mirror.state = broken` |
| `transfer` | "Alice hands the key to Bob" | `key.holder = bob` |
| `appear` | "A dragon appears" | `dragon.position = scene` |
| `disappear` | "The ghost vanishes" | `ghost.position = offscreen` |

**Prevention Checklist:**

- [ ] New props in scene graph? Add to `initial_objects` in SceneSetup
- [ ] Complex action? Use explicit `events` field, don't rely on pattern matching
- [ ] Testing continuity? Enable verbose logging to see world state updates
- [ ] Debugging teleportation? Check `WorldState.get_events_for_entity()` history

**Architecture Alignment:**

From ARCHITECTURE.md:
> "Step 4 (The Bridge): It generates a Bridge Frame (preserving the end-state emotion/props)"

From ARCHITECTURE_SUMMARY.md:
> "The World State tells us *where* things are and *what happened* to them."

---
---

### 62. Claude Project Files Are FLATTENED ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Actual Project Uses Nested `src/`

| | |
|---|---|
| **Date** | 2025-12-21 |
| **Category** | Environment Gotcha (not a code bug) |
| **Problem** | Claude's `/mnt/project/` shows all files at root level |
| **Reality** | Actual VS Code project uses proper nested `src/` structure |
| **Impact** | Wrong import paths if you assume flat structure |

**What Claude Sees:**
/mnt/project/
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ scene_graph.py
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ pass1_generator.py
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ identity_checker.py
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ mixer.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ...

**What Actually Exists (VS Code):**
CONTINUUM/
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ src/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ audit/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ identity_checker.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ physics_checker.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ reviewer.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ director/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ scene_graph.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ world_state.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ shot_event_parser.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ studio/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ pass1_generator.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ bridge_engine.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ rife_interpolator.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ sonic/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ mixer.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ...
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ workflows/
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ main.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ...

**Mapping Table:**

| Claude path | Actual path | Import statement |
|-------------|-------------|------------------|
| `/mnt/project/scene_graph.py` | `src/director/scene_graph.py` | `from src.director.scene_graph import ...` |
| `/mnt/project/pass1_generator.py` | `src/studio/pass1_generator.py` | `from src.studio.pass1_generator import ...` |
| `/mnt/project/identity_checker.py` | `src/audit/identity_checker.py` | `from src.audit.identity_checker import ...` |
| `/mnt/project/mixer.py` | `src/sonic/mixer.py` | `from src.sonic.mixer import ...` |
| `/mnt/project/world_state.py` | `src/director/world_state.py` | `from src.director.world_state import ...` |
| `/mnt/project/bridge_engine.py` | `src/studio/bridge_engine.py` | `from src.studio.bridge_engine import ...` |
| `/mnt/project/color_match.py` | `src/post/color_match.py` | `from src.post.color_match import ...` |
| `/mnt/project/client.py` | `src/comfy_client/client.py` | `from src.comfy_client.client import ...` |

**Prevention:**

1. **Always use `src.` prefix** in import statements
2. **Check existing imports** in the file before adding new ones
3. **When creating new files**, ask user which `src/` subfolder it belongs in
4. **Don't trust** Claude's flat view ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â reference this table

**Why This Happens:**

Claude Projects flatten uploaded files to `/mnt/project/` regardless of original folder structure. The nested `src/` organization is preserved in the actual codebase but not visible in Claude's file view.

<!-- 
  APPEND THIS TO THE END OF LESSONS_LEARNED.md 
  (before the final "Add new entries above this line" comment)
-->

### 63. Entity Classes Use `entity_id`, Not `id`

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `AttributeError: 'CharacterEntity' object has no attribute 'id'` |
| **Wrong Assumption** | Entity dataclasses have an `id` field |
| **Correct Interface** | All entity classes use `entity_id` as the identifier field |
| **Source of Truth** | `src/director/consistency_dict.py` |

**Affected Classes:**
- `CharacterEntity.entity_id`
- `LocationEntity.entity_id`
- `PropEntity.entity_id`

**Wrong:**
```python
known.update(c.id for c in self.consistency_dict.list_characters())
```

**Correct:**
```python
known.update(c.entity_id for c in self.consistency_dict.list_characters())
```

**Prevention:** Check dataclass definitions before accessing fields:
```bash
grep -n "entity_id\|character_id" src/director/consistency_dict.py | head -10
```

---

### 64. Import Paths Must Be Absolute from `src.`

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `ModuleNotFoundError: No module named 'world_state'` |
| **Wrong Assumption** | Can import sibling modules by name alone |
| **Correct Interface** | All imports must use full path from `src.` |
| **Source of Truth** | Project uses absolute imports throughout |

**Wrong (in `src/director/shot_event_parser.py`):**
```python
from world_state import EventType, ObjectState, Position, StateEvent
```

**Correct:**
```python
from src.director.world_state import EventType, ObjectState, Position, StateEvent
```

**Prevention:** Always use `from src.<package>.<module> import ...` pattern. Never bare module names.

---

### 65. RunPod: scikit-image Required for Pose Extraction

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `No module named 'skimage'` during pose extraction |
| **Wrong Assumption** | All OpenPose dependencies are installed |
| **Correct Interface** | Must install scikit-image separately |
| **Workflow Affected** | `bridge_pose_extract.json` (OpenposePreprocessor) |

**Fix (on RunPod):**
```bash
pip3 install scikit-image
```

**Then restart ComfyUI:**
```bash
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Prevention:** See RUNPOD.md Section 3 for required dependencies.

---

### 66. Pod ID: Watch for `1` (one) vs `l` (lowercase L)

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `WSServerHandshakeError: 404, Invalid response status` |
| **Wrong Assumption** | Typed pod ID correctly |
| **Correct Interface** | **Always copy Pod ID from browser URL, never type manually** |

**Example:**
- Wrong: `1yhiozmwkjopf7` (starts with number one)
- Correct: `lyhiozmwkjopf7` (starts with lowercase L)

**Prevention:** 
1. Click ComfyUI link in RunPod dashboard
2. Copy the URL from browser address bar
3. Extract pod ID from URL (everything before `-8188.proxy.runpod.net`)

---

### 65. list_characters() Returns Objects, Not IDs

| | |
|---|---|
| **Date** | 2025-12-22 |
| **Error** | `TypeError: unhashable type: 'CharacterEntity'` |
| **Wrong Assumption** | `ConsistencyDict.list_*()` methods return ID strings |
| **Correct Interface** | They return full entity objects (CharacterEntity, LocationEntity, PropEntity) |
| **Source of Truth** | `src/director/consistency_dict.py` lines 364, 399, 429 |

**Wrong:**
```python
known = set()
known.update(self.consistency_dict.list_characters())  # Objects aren't hashable!
```

**Correct:**
```python
known = set()
known.update(c.entity_id for c in self.consistency_dict.list_characters())
```

**Method Return Types:**
- `list_characters()` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `List[CharacterEntity]`
- `list_locations()` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `List[LocationEntity]`
- `list_props()` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `List[PropEntity]`

**Prevention:** Check return type hints before using list methods.

### 67. RunPod Template Auto-Starts ComfyUI ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Don't Double-Start

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | `OSError: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8188): address already in use` |
| **Wrong Assumption** | ComfyUI needs to be manually started after pod launch |
| **Correct Interface** | RunPod's template may auto-start ComfyUI on port 8188 |
| **Impact** | Manual start fails; logs show crash but ComfyUI is actually running |

**Symptom:**
```
[1]+  Exit 1   nohup python3 main.py --listen 0.0.0.0 --port 8188
```
But `curl localhost:8188/system_stats` returns valid JSON.

**Root Cause:**
RunPod's ComfyUI template includes auto-start. When you run the manual start command, it conflicts with the already-running instance.

**Correct Startup Procedure:**
```bash
# First, check if ComfyUI is already running
curl -s http://localhost:8188/system_stats | head -c 100

# If it returns JSON ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ already running, skip to pip install only
# If it fails ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ then start manually:
pkill -f "python.*main.py.*8188"
sleep 2
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

**Prevention:** Always check if ComfyUI is running before attempting to start it.
---

## 68. Workflow Documentation Convention

Workflow JSON files can include documentation using keys prefixed with `_`:
```json
{
  "_comment": "What this workflow does",
  "_architecture_ref": "Section X.Y in ARCHITECTURE.md",
  
  "actual_node": {
    "class_type": "...",
    "inputs": {...}
  }
}
```

These keys are:
- Preserved in template files (for developer documentation)
- Skipped during validation
- Stripped before submission to ComfyUI

___

### 69. ComfyUI Workflows May Reference Non-Existent Nodes

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | `Cannot execute because node KSamplerBatch does not exist` then `Cannot execute because node TemporalSmooth does not exist` |
| **Wrong Assumption** | Workflow JSON files were tested and use standard ComfyUI nodes |
| **Correct Interface** | Some workflows were created with aspirational/custom nodes that don't exist publicly |
| **Workflows Affected** | `refine_vid2vid_temporal.json` |

**Non-Existent Nodes Found:**

| Node | What It Was Supposed To Do | Replacement |
|------|---------------------------|-------------|
| `KSamplerBatch` | Batch sampling with `temporal_coherence` param | Standard `KSampler` |
| `TemporalSmooth` | Blend neighboring frames to reduce flicker | Removed (use FFmpeg post-processing instead) |

**Wrong (original workflow):**
```json
{
  "batch_sampler": {
    "class_type": "KSamplerBatch",
    "inputs": {
      "batch_size": "{{TEMPORAL_WINDOW}}",
      "temporal_coherence": true
    }
  },
  "temporal_smooth": {
    "class_type": "TemporalSmooth",
    "inputs": {
      "window_size": 3,
      "strength": 0.3
    }
  }
}
```

**Correct (fixed workflow):**
```json
{
  "sampler": {
    "class_type": "KSampler",
    "inputs": {
      // Standard params only, no temporal_coherence
    }
  }
  // TemporalSmooth removed entirely
}
```

**Prevention:**
1. Before using a workflow, verify ALL `class_type` values exist on your ComfyUI instance
2. Test workflows manually in ComfyUI web UI before integrating
3. Use `grep "class_type" workflow.json` to list all required nodes
4. Check RunPod logs for node loading: `cat /tmp/comfyui.log | grep "Loading:"`

**Note:** After this fix, `refine_vid2vid_temporal.json` is functionally identical to `refine_vid2vid_simple.json`. Consider consolidating them.

---

### 70. ComfyUI Node Packs Don't Always Contain Expected Nodes

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | Installed ComfyUI-Inspire-Pack expecting `KSamplerBatch`, but it wasn't there |
| **Wrong Assumption** | Node names imply which pack provides them |
| **Correct Interface** | Must verify node exists in pack before installing |

**Investigation Steps:**
```bash
# Search ComfyUI-Manager's node database for a node
grep -r "KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-Manager/extension-node-map.json

# Search installed packs for a node class
grep -r "class_type.*KSamplerBatch" /workspace/runpod-slim/ComfyUI/custom_nodes/
```

**What We Found:**
- `KSamplerBatch` - Does NOT exist in any standard pack
- `CRT_KSamplerBatch` - Different node, different pack
- `quadmoonKSamplerBatched` - Different node, different pack

**Prevention:** Before installing a pack to fix a missing node:
1. Search ComfyUI-Manager's node database for exact node name
2. Verify the pack actually provides that exact `class_type`
3. Consider if the workflow itself is the problem (using non-existent nodes)

___
### 71. ComfyUI Job Polling Requires wait_for_completion(), Not Manual Loop

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Error** | RIFE interpolation hung forever despite ComfyUI job completing successfully |
| **Wrong Assumption** | `job.is_terminal()` would return True when job completes |
| **Correct Interface** | Must use `client.wait_for_completion(prompt_id)` to properly track completion |
| **Affected Files** | `pass2_refiner.py`, `rife_interpolator.py` |

**Broken Pattern:**
```python
job = await client.submit(workflow)
while not job.is_terminal():  # Never becomes true!
    await asyncio.sleep(0.5)
```

**Working Pattern (from wan_renderer.py):**
```python
comfy_job = await client.submit_workflow(workflow)
completed_job = await client.wait_for_completion(
    comfy_job.prompt_id,
    timeout_sec=600,
    progress_callback=progress_adapter
)
# Now completed_job.outputs has the results
```

**Why the broken pattern fails:**
- `client.submit()` returns a `ComfyJob` object
- WebSocket messages update tracking *inside* the client, not the returned object
- The `job` object's state never changes, so `is_terminal()` always returns False

**Prevention:** All ComfyUI-based modules should follow the same pattern:
1. `client.submit_workflow()` - submit job
2. `client.wait_for_completion()` - wait with proper tracking
3. `client.download_output()` - download results
---

### 72. Vid2Vid Without Temporal Consistency Causes Flicker

| | |
|---|---|
| **Date** | 2025-12-23 |
| **Symptom** | Output video has flickering faces - like 2 faces juxtaposed |
| **Root Cause** | Pass 2 refinement using plain `KSampler` processes frames independently |
| **Why It Happens** | Each frame gets slightly different "reimagining" of the face |
| **Affected File** | `workflows/refine_vid2vid_temporal.json` |

**The Broken Fix:**
When `KSamplerBatch` (temporal) and `TemporalSmooth` nodes don't exist, replacing them with standard `KSampler` removes temporal consistency entirely.

**Workarounds:**
1. Use `--no-pass2` flag to skip refinement (recommended until fixed)
2. Lower denoise strength to ~0.1 (nearly a no-op)
3. Use FFmpeg temporal smoothing post-process

**Proper Fix (Future):**
- Find ComfyUI node pack with real temporal vid2vid
- Or use AnimateDiff/SVD-based refinement
- Or implement latent blending between frames (CoNo-style)

**Key Insight:** Pass 2 is optional polish. Without proper temporal processing, it's actively harmful - makes output worse, not better.

---
### 73. WanAnimateToVideo is NOT an I2V Node

| | |
|---|---|
| **Date** | 2025-12-24 |
| **Error** | Identity score dropped from 97% to 22% when using WanAnimateToVideo instead of WanImageToVideo |
| **Wrong Assumption** | `clip_vision_output` + `reference_image` would give I2V behavior with identity anchoring |
| **Correct Interface** | `WanAnimateToVideo` is T2V with identity reference, NOT I2V continuation |
| **Source of Truth** | ComfyUI object_info API on RunPod |

**Critical Distinction:**

| Node | `start_image` | `clip_vision_output` | `reference_image` | Behavior |
|------|--------------|---------------------|------------------|----------|
| `WanImageToVideo` | ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | ÃƒÂ¢Ã‚ÂÃ…â€™ | Frame 1 IS the start_image (I2V) |
| `WanAnimateToVideo` | ÃƒÂ¢Ã‚ÂÃ…â€™ | ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Generates FROM SCRATCH using references (T2V) |

**What We Thought:**
clip_vision_output (bridge frame) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ structural guidance

reference_image (face ref) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ identity anchor
= I2V with identity consistency


**What Actually Happens:**
clip_vision_output ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ WEAK semantic hint only

reference_image ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ identity TARGET
= T2V that tries to match reference but IGNORES bridge frame structure


**Test Results:**
- WanImageToVideo with bridge frame: **97.67%** identity
- WanAnimateToVideo with reference_image: **22.78%** identity (CATASTROPHIC)

**Prevention:** 
1. Test new node behaviors with single-shot before pipeline integration
2. Verify node purpose (T2V vs I2V) by checking if `start_image` exists
3. "Experimental" nodes with empty descriptions should be approached with extreme caution

---

### 74. face_video Input Provides Per-Frame Identity Anchoring

| | |
|---|---|
| **Date** | 2025-12-24 |
| **Discovery** | `WanAnimateToVideo`'s `face_video` input accepts repeated face reference as video frames |
| **Result** | **98.32% identity** - matches or beats WanImageToVideo |
| **Why It Works** | Per-frame face guidance, not just single reference |

**Available Inputs on WanAnimateToVideo:**
```python
optional: {
    'clip_vision_output',   # Semantic guidance
    'reference_image',      # Scene appearance
    'face_video',          # ÃƒÂ¢Ã¢â‚¬Â Ã‚Â PER-FRAME FACE GUIDANCE
    'pose_video',          # Motion/pose guidance
    'background_video',    # Background consistency
    'continue_motion',     # Multi-chunk continuity
}
```

**Working Configuration:**
Bridge Frame ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ clip_vision_output (structure)
Bridge Frame ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ reference_image (scene appearance)
Face Ref ÃƒÆ’Ã¢â‚¬â€ N frames ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ RepeatImageBatch ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ face_video (per-frame identity)

**Workflow Snippet:**
```json
{
  "repeat_face_ref": {
    "class_type": "RepeatImageBatch",
    "inputs": {
      "image": ["load_face_ref", 0],
      "amount": "{{FRAMES}}"
    }
  },
  "wan_animate": {
    "class_type": "WanAnimateToVideo",
    "inputs": {
      "clip_vision_output": ["clip_vision_encode", 0],
      "reference_image": ["load_init_image", 0],
      "face_video": ["repeat_face_ref", 0]
    }
  }
}
```

**Key Insight:** 
- `reference_image` = single image for overall appearance
- `face_video` = VIDEO input for per-frame face guidance
- Repeating face ref N times creates a "constant face video" that anchors identity every frame

**This is the IP-Adapter equivalent for Wan video models.**

---
### 77. Identity vs Expression: The Core Disentanglement Problem (Research Summary)

| | |
|---|---|
| **Date** | 2025-12-24 |
| **Source** | Deep research on identity preservation in AI video generation |
| **Core Problem** | Pixel-level face conditioning locks BOTH identity AND expression |
| **Solution Direction** | Use embedding-level identity (ArcFace) + separate expression control |

**Why Our face_video Approach Failed for Expressions:**

We used `RepeatImageBatch` to create N copies of the same face image and fed it to `face_video`. This is **pixel-level conditioning on every frame** - the worst case for expression freezing.
Pixel-level (what we did):     "Make every frame look EXACTLY like these pixels"
Embedding-level (correct):     "Make every frame be THIS PERSON (identity embedding only)"

**Research-Backed Solutions:**

| Approach | How It Works | Implementation |
|----------|--------------|----------------|
| **Embedding-level identity** | Use ArcFace/InsightFace to extract identity-only embedding, not full face pixels | IP-Adapter FaceID uses InsightFace internally |
| **Strength parameter** | Reduce conditioning strength to 0.5-0.7 (not 1.0) | Check if face_video has weight param |
| **Keyframe-only conditioning** | Condition first/last frames strongly, let middle interpolate | Don't use RepeatImageBatch for ALL frames |
| **Multi-reference images** | Provide 3-5 images of same person with DIFFERENT expressions | Model learns identity separate from expression |
| **Dual-branch architecture** | Separate identity branch from expression/structure branch | Magic Mirror, ConsisID models |

**Key Research Findings:**

1. **Face recognition embeddings (ArcFace) are expression-invariant by design** - they encode "who" not "how they look right now"

2. **IP-Adapter FaceID sweet spot is 0.5-0.7 weight** - 1.0 freezes face, 0.5-0.6 allows expression

3. **Per-frame conditioning = "talking statue"** - every frame converges to reference

4. **ConsisID (CVPR 2025)** uses frequency decomposition: high-frequency = identity (invariant), low-frequency = pose/expression (variable)

5. **Magic Mirror** uses dual-branch: one for identity features, one for structural/expression features

**Models/Tools That Solve This:**

| Model | Approach | Availability |
|-------|----------|--------------|
| ConsisID | Frequency decomposition on CogVideoX | Open source (GitHub) |
| Magic Mirror | Dual-branch identity vs structure | Research paper (2025) |
| IP-Adapter FaceID v2 | InsightFace embedding + strength control | ComfyUI nodes exist |
| InstantID | Identity embedding + facial keypoints | ComfyUI nodes exist |
| PuLID | Tuning-free ID with weak/strong modes | ComfyUI nodes exist |

**Action Items for Continuum:**

1. **Immediate**: Check if WanAnimateToVideo face_video has strength/weight parameter
2. **Short-term**: Test IP-Adapter FaceID or InstantID nodes with Wan
3. **Medium-term**: Investigate ConsisID integration (purpose-built for this problem)
4. **Alternative**: Use post-process expression transfer (SadTalker/Wav2Lip) on identity-locked video

**The Fundamental Insight:**

> "Separating 'who' from 'how they look right now' is the guiding principle."

Our face_video approach conflated both. We need to inject identity at the **feature/embedding level**, not as a hard pixel template.

---
### 78. Identity Preservation Experiments: Comprehensive Results

| | |
|---|---|
| **Date** | 2025-12-24 |
| **Error** | Multiple approaches tested for identity + expression preservation |
| **Impact** | Wasted cycles on approaches that don't work with current models |

**The Problem:** Preserve character identity (same person) while allowing natural expressions (smiles, blinks, talking).

**Approaches Tested:**

| Approach | How It Works | Identity | Expression | Quality | Verdict |
|----------|--------------|----------|------------|---------|---------|
| **Standard WanImageToVideo + hero frame** | Hero frame (SDXL+IP-Adapter) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ I2V animation | 97% ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Natural ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Good ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | **CURRENT BEST** |
| **face_video per-frame** (Lesson #76) | RepeatImageBatch feeds face ref to every frame | 98% ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Frozen ÃƒÂ¢Ã‚ÂÃ…â€™ | Good | Reject |
| **WanFirstLastFrameToVideo** | CLIP vision encodes face at start/end frames only | ~95% | Changes ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Artifacts ÃƒÂ¢Ã‚ÂÃ…â€™ | Reject |
| **WanPhantomSubjectToVideo** (1.3B T2V) | T2V with subject identity baked into conditioning | ~70% ÃƒÂ¢Ã‚ÂÃ…â€™ | Changes ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ | Poor ÃƒÂ¢Ã‚ÂÃ…â€™ | Reject |

**Why Each Failed:**

1. **face_video**: Designed for "make every frame look EXACTLY like these pixels" - conflates identity with expression at pixel level. Great for static portraits, terrible for animation.

2. **WanFirstLastFrameToVideo**: Designed for interpolating between TWO DIFFERENT frames (AÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢B). When fed same image for both start/end, creates confusion ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ dark halo artifacts, washed out quality.

3. **WanPhantomSubjectToVideo**: Conceptually correct (embedding-level identity), but:
   - Only 1.3B T2V model available (too small for quality)
   - 14B T2V model not downloaded
   - Would need to bypass hero frame generation (architecture change)

**Current Recommendation:**
```python
# wan_renderer.py workflow selection
elif has_ipadapter:
    # Standard I2V + hero frame gives 97% identity + natural expressions
    return self.WORKFLOW_IMG2VID
```

**ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â IMPORTANT CAVEAT:**

The 97% identity score is validated on **1-second clips only**. Longer clips may experience:
- Identity drift over time
- Accumulating deviation from reference
- Need for periodic "anchor frames"

**Future Work Required (Post-MVP):**

| Priority | Approach | Notes |
|----------|----------|-------|
| High | **Character LoRA training** | Fine-tune model on specific character for persistent identity |
| High | **Hunyuan + IP-Adapter** | Hunyuan may have better IP-Adapter integration than Wan |
| Medium | **Download 14B T2V model** | Re-test Phantom with quality model |
| Medium | **ConsisID/Magic Mirror** | Purpose-built identity-expression disentanglement |
| Medium | **Other video models + IP-Adapter** | CogVideoX, Mochi, etc. may have native support |

**Not Ruled Out:**
- IP-Adapter approach is sound in principle (embedding-level identity)
- Current failure is Wan-specific (nodes designed for SD, not video diffusion)
- Different model families may have native IP-Adapter-style identity injection

**Key Insight:**

> Hero frame generation is doing the heavy lifting. SDXL + IP-Adapter creates a strong identity anchor at frame 0. WanImageToVideo then animates from that anchor. The identity preservation comes from the init frame, NOT from video-level conditioning.

> For longer clips, the solution is likely LoRA-based (train the model to "know" the character) rather than conditioning-based (tell the model who to generate each frame).

---

### 79. RunPod ComfyUI Blank Page / 502 Bad Gateway

| | |
|---|---|
| **Date** | 2025-12-29 |
| **Error** | ComfyUI shows blank white page or 502 Bad Gateway in browser |
| **Root Cause** | Missing `scikit-image` dependency causes ComfyUI to partially fail |
| **Solution** | `pip3 install scikit-image` Ã¢â‚¬â€ no restart needed |

**Symptoms:**
- Browser shows blank white page
- Or "502 Bad Gateway" Cloudflare error
- `curl http://localhost:8188/` returns HTML (server is running)
- But browser can't render

**The Fix:**
```bash
pip3 install scikit-image
```

**Why:** Impact-Pack and ControlNet-aux nodes require `skimage`. Even if you don't use those nodes, the import failure can cause frontend issues.

**Prevention:** Add to RunPod template startup script or requirements.

---

### 80. HunyuanCustom Text Encoder Downloads (Correct Sources)

| | |
|---|---|
| **Date** | 2025-12-29 |
| **Error** | 404 Not Found when downloading HunyuanCustom text encoders |
| **Root Cause** | Files not in Kijai's repo, they're in Comfy-Org repo |
| **Impact** | Wasted time searching for correct download URLs |

**Wrong (404 errors):**
```bash
# These DON'T work:
huggingface-cli download Kijai/HunyuanVideo_comfy clip_l.safetensors
huggingface-cli download Kijai/HunyuanVideo_comfy llava_llama3_fp16.safetensors
```

**Correct Sources:**
```bash
cd /workspace/runpod-slim/ComfyUI/models/text_encoders/

# CLIP-L (~235MB) - from comfyanonymous
huggingface-cli download comfyanonymous/flux_text_encoders \
  clip_l.safetensors --local-dir ./

# LLaVA-Llama3 (~16GB) - from Comfy-Org
huggingface-cli download Comfy-Org/HunyuanVideo_repackaged \
  split_files/text_encoders/llava_llama3_fp16.safetensors --local-dir ./

# Move to correct location
mv split_files/text_encoders/llava_llama3_fp16.safetensors ./
rm -rf split_files/
```

**Complete HunyuanCustom Model Checklist:**

| File | Size | Location | Source |
|------|------|----------|--------|
| `hunyuan_video_custom_720p_fp8_scaled.safetensors` | ~13 GB | `models/diffusion_models/` | `Kijai/HunyuanVideo_comfy` |
| `hunyuan_video_vae_bf16.safetensors` | ~500 MB | `models/vae/` | `Kijai/HunyuanVideo_comfy` |
| `clip_l.safetensors` | ~235 MB | `models/text_encoders/` | `comfyanonymous/flux_text_encoders` |
| `llava_llama3_fp16.safetensors` | ~16 GB | `models/text_encoders/` | `Comfy-Org/HunyuanVideo_repackaged` |

**Total storage needed:** ~30 GB for HunyuanCustom models

---

### 81. HunyuanCustom ComfyUI Extensions Required

| | |
|---|---|
| **Date** | 2025-12-29 |
| **Context** | Setting up HunyuanCustom on RunPod 4x RTX 4090 |
| **Required Extensions** | Two custom node repos needed |

**Installation:**
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes

# Kijai's HunyuanVideo wrapper (required)
git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper

# MultiGPU support (required for 4x GPU setup)
git clone https://github.com/pollockjj/ComfyUI-MultiGPU

# Install dependencies
cd ComfyUI-HunyuanVideoWrapper
pip3 install -r requirements.txt
```

**Key Nodes Provided:**
- `HunyuanVideo Model Loader`
- `HunyuanVideo Sampler`
- `HunyuanVideo TextImageEncode (IP2V)` Ã¢â‚¬â€ for identity injection
- `HunyuanVideo VAE Loader`
- `HunyuanVideo Decode`

**Example Workflows:** Located in `custom_nodes/ComfyUI-HunyuanVideoWrapper/example_workflows/`
- `hyvideo_custom_testing_01.json` Ã¢â‚¬â€ HunyuanCustom identity test

---

### 60. RunPod HunyuanVideo Starter Pack (Complete Setup Guide)

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Context** | Fresh RunPod with 4x RTX 4090 fails to run HunyuanCustom workflows |
| **Root Cause** | Missing Python dependencies: `diffusers`, `accelerate` |
| **Symptoms** | `Cannot execute because node HyVideoBlockSwap does not exist` |

**The Problem:** HunyuanVideoWrapper custom nodes exist in `/custom_nodes/` but fail to load due to missing Python packages. ComfyUI logs show:
```
ModuleNotFoundError: No module named 'diffusers'
ModuleNotFoundError: No module named 'accelerate'
IMPORT FAILED: /workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-HunyuanVideoWrapper
```

**Complete Setup Commands (Run on Fresh RunPod):**

```bash
# 1. Install missing Python dependencies
pip3 install diffusers accelerate

# 2. Restart ComfyUI
pkill -f "python3.*main.py"
sleep 2
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > comfyui.log 2>&1 &

# 3. Wait for startup (HunyuanVideo loads slowly)
sleep 45

# 4. Verify HunyuanVideo nodes loaded
curl -s http://localhost:8188/object_info | python3 -c "import sys,json; d=json.load(sys.stdin); print([k for k in d.keys() if 'HyVideo' in k])"
```

**Expected Output (should see 30+ nodes):**
```
['HyVideoSampler', 'HyVideoDecode', 'HyVideoTextEncode', 'HyVideoModelLoader', 
 'HyVideoVAELoader', 'HyVideoEncode', 'HyVideoBlockSwap', 'HyVideoTextEmbedBridge', ...]
```

**If Only 1 Node Shows (`TorchCompileModelHyVideo`):**
- Dependencies not installed or ComfyUI not restarted
- Check logs: `grep -i "error\|failed" comfyui.log | head -30`

**Debug Commands:**
```bash
# Check if extension folder exists
ls /workspace/runpod-slim/ComfyUI/custom_nodes/ | grep -i hunyuan

# Check ComfyUI startup errors
cat /workspace/runpod-slim/ComfyUI/comfyui.log | grep -i "error\|failed\|import" | head -50

# Check if ComfyUI is running
ps aux | grep python3

# Check which nodes are available
curl -s http://localhost:8188/object_info | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'nodes loaded')"
```

**Path Notes (RunPod-specific):**
- ComfyUI location: `/workspace/runpod-slim/ComfyUI/` (NOT `/workspace/ComfyUI/`)
- Custom nodes: `/workspace/runpod-slim/ComfyUI/custom_nodes/`
- Workflows: `/workspace/runpod-slim/ComfyUI/user/default/workflows/`
- Models: `/workspace/runpod-slim/ComfyUI/models/`

**Prevention:** When spinning up a new RunPod for HunyuanCustom, always run `pip3 install diffusers accelerate` before testing workflows.

---

### 82. HunyuanCustom Identity Failure: noise_aug_strength and Frame Count

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Error** | Identity scores failing (0.10-0.38) despite validated ComfyUI workflow working in UI |
| **Root Cause** | Two combined issues: (1) `noise_aug_strength: 0.025` corrupts identity, (2) insufficient frames for motion with `noise_aug_strength: 0` |

**The Problem:**

HunyuanCustom identity-preserving I2V was producing videos where the face didn't match the reference image. The validated ComfyUI workflow worked perfectly when run manually in the UI, but the Python pipeline consistently failed identity checks.

**Debugging Approach (First Principles):**

1. Created minimal bash test (`test_identity.sh`) to submit exact validated workflow via API
2. Bash test succeeded â†’ confirmed bug was in Python code, not ComfyUI/models
3. Added workflow dump (`debug_workflow.json`) to compare Python vs bash workflows
4. Identified two key differences:
   - `noise_aug_strength`: Python=0.025, Bash=0
   - `num_frames`: Python=13, Bash=25

**Root Cause 1: noise_aug_strength**
```json
// BROKEN (our default)
"NOISE_AUG_STRENGTH": 0.025

// WORKING (validated workflow)
"NOISE_AUG_STRENGTH": 0
```

This parameter adds noise to the init image latent:
- `0.025` = 2.5% noise mixed in â†’ easier motion, but **corrupts identity signal**
- `0` = pure image â†’ **identity preserved perfectly**

The official ComfyUI-HunyuanVideoWrapper default is `0.0` per source code tooltip: "Strength of noise augmentation, helpful for leapfusion I2V where some noise can add motion."

**Root Cause 2: Frame Count**

With `noise_aug_strength=0`, the model needs sufficient frames to develop motion from prompt alone:
- 13 frames (1.0s Ã— 12fps): **Frozen** video, good identity
- 25 frames (2.1s Ã— 12fps): **Motion** AND good identity

**The Fix:**

1. Changed `workflows/hunyuan_custom/pass1_img2vid.json`:
```json
   "_defaults": {
     "NOISE_AUG_STRENGTH": 0,  // was 0.025
   }
```

2. Changed `src/renderers/hunyuan_custom_renderer.py`:
```python
   DEFAULT_NOISE_AUG_STRENGTH = 0.0  # was 0.025
```

3. Increased shot duration to 2.1s to get 25 frames (workaround until fps properly passed to JobSpec)

**Additional Bug Found:**

`target_fps` in project JSON isn't passed to JobSpec - it defaults to 12fps regardless. The `frame_count` property calculates `duration_sec * fps`, so 1.0s Ã— 12fps = 12 frames even when `target_fps: 24` is set.
```python
# In base.py JobSpec
fps: int = 12  # Default, not overridden from project config

@property
def frame_count(self) -> int:
    return int(self.duration_sec * self.fps)
```

**TODO:** Fix `pass1_generator.py` to pass project's `target_fps` to JobSpec construction.

**Workflow Caching Gotcha:**

WorkflowLoader caches templates in memory:
Using cached template: pass1_img2vid

Editing workflow JSON files requires **restarting Python** (Ctrl+C, re-run) to pick up changes. The cache persists within a single Python process, including across rerolls.

**Prevention Checklist:**

1. Always compare against validated workflow when debugging identity issues
2. Check `noise_aug_strength` - default should be `0` for HunyuanCustom
3. Ensure minimum ~25 frames for motion when `noise_aug_strength=0`
4. Use bash test scripts to isolate Python code vs ComfyUI issues
5. Restart Python after editing workflow JSON files
6. Dump actual workflow JSON (`debug_workflow.json`) to verify what's being sent

**Test Script for Future Debugging:**
```bash
# test_identity.sh - submits exact workflow via curl, bypassing Python
./test_identity.sh <RUNPOD_HOST> <IMAGE_PATH>

# Compare workflows
python3 -c "
import json
with open('workspace/output/debug_workflow.json') as f:
    py = json.load(f)
print('noise_aug:', py['41']['inputs']['noise_aug_strength'])
print('num_frames:', py['62']['inputs']['num_frames'])
"
```

---

### 83. Debugging Strategy: Isolate with Minimal Reproducers

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Principle** | When Python pipeline fails but UI works, create minimal bash/curl test to isolate the issue |

**The Pattern:**

1. **Establish ground truth:** Confirm the validated workflow works in ComfyUI UI
2. **Create minimal reproducer:** Bash script that submits exact same workflow via API
3. **Test reproducer:** If it works â†’ bug is in Python code. If it fails â†’ bug is elsewhere
4. **Diff the workflows:** Dump Python's actual workflow JSON and compare node-by-node

**Bash Test Template:**
```bash
#!/bin/bash
# Upload image
UPLOADED=$(curl -s -X POST "https://$HOST/upload/image" -F "image=@$IMAGE" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")

# Submit workflow (hardcoded from validated workflow)
WORKFLOW='{"1": {...}, "41": {...}}'  # Exact validated workflow
curl -s -X POST "https://$HOST/prompt" -H "Content-Type: application/json" -d "{\"prompt\": $WORKFLOW}"
```

**Why This Works:**

- Eliminates all Python code complexity
- Tests the exact API path ComfyUI uses
- Makes A/B comparison trivial (bash vs Python output)
- Faster iteration than full pipeline runs

**When to Use:**

- Identity/quality issues where UI works but pipeline doesn't
- Mysterious failures with no clear error message
- Validating workflow templates before integration

---


### 84. CRITICAL: Bridge Frames MUST Re-Anchor to Canonical Identity

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Error** | Suggesting "skip bridge SDXL and use last_frame directly" to fix halo artifacts |
| **Why This Is Wrong** | Using last_frame directly causes CUMULATIVE identity drift across shots |

**THE CORE PRINCIPLE (DO NOT FORGET):**
WITHOUT bridge re-anchoring (WRONG):
Shot 1: hero â†’ Wan â†’ 98% identity
Shot 2: 98% â†’ Wan â†’ 94% identity (drift compounds!)
Shot 3: 94% â†’ Wan â†’ 88% identity
Shot 4: 88% â†’ Wan â†’ 80% identity
... identity degrades exponentially
WITH bridge re-anchoring (CORRECT):
Shot 1: hero â†’ Wan â†’ 98% identity
Shot 2: BRIDGE(hero) â†’ Wan â†’ 98% identity (reset to canonical!)
Shot 3: BRIDGE(hero) â†’ Wan â†’ 98% identity
Shot 4: BRIDGE(hero) â†’ Wan â†’ 98% identity
... identity stays locked

**Why Bridge Frames Exist:**

The ENTIRE PURPOSE of the bridge frame is to **re-anchor identity to the canonical hero frame** at each shot boundary. This prevents drift from accumulating across shots.

**What the Bridge Does:**
1. Takes canonical hero frame (or face_ref) as identity source
2. Takes last_frame pose via ControlNet (for continuity)
3. Regenerates a clean frame with locked identity
4. This becomes the init_frame for the next shot's I2V

**NEVER suggest:**
- "Skip bridge SDXL and use last_frame directly"
- "Just pass last_frame to next shot"
- "Remove the bridge step to avoid artifacts"

**If bridge has artifacts (halos, dots), the fix is:**
- Lower denoise further
- Adjust ControlNet/IP-Adapter strengths
- Use different bridge workflow
- Fix the SDXL bridge step itself

**NOT** skipping the re-anchoring step entirely.

**Prevention:**
Before suggesting any change to bridge logic, ask: "Does this preserve re-anchoring to canonical identity?" If no, reject the approach.

---

### 85. Hero Frame Strategy: Separate Pose Source from Identity Source

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Implementation** | Bridge frames should use hero_frame for img2img source, last_frame for pose extraction |

**The Problem:**

Bridge frames were using `last_frame` for BOTH:
1. Pose extraction (ControlNet) - correct
2. Img2img source (VAEEncode) - WRONG, causes background drift

**The Solution:**

Separate the two sources:
```python
BridgeSpec:
  source_frame: Path          # Last frame - for pose extraction
  identity_source_frame: Path # Hero frame - for img2img source (preserves background)
```

**In bridge_engine.generate():**
```python
# Pose extraction from last_frame (continuity)
spec.pose_data = await self.extract_pose(spec.source_frame)

# Img2img from hero_frame (identity/background preservation)
img2img_source = spec.identity_source_frame or spec.source_frame
```

**Data Flow:**
hero_frame (canonical) â†’ VAEEncode â†’ latent source (background/identity locked)
last_frame (drifted)   â†’ ControlNet â†’ pose conditioning (continuity preserved)
â†“
Bridge output (best of both)

**Trade-off Accepted:**
Expression may jump at cuts because ControlNet captures coarse pose, not micro-expressions. This is acceptable - real films have expression discontinuity at cuts.

---
### 86. Wan VAE Decoder "Overbaked First Frames" Fix âœ… CONFIRMED

| | |
|---|---|
| **Date** | 2026-01-02 |
| **Status** | Confirmed working |
| **Implementation** | wan_renderer.py: Request +3 frames, trim first 3 after download |

**The Problem:**

Wan's VAE decoder produces artifacts ("overbaked" pixels, circular spots) in the first 2-3 frames of I2V videos. This is a known issue in the community, documented in Civitai workflows like "Motion Forge."

Visual evidence:
- Shot 1 frame 0: Minimal artifacts (no reference to compare)
- Bridge frame: Clean (SDXL, not Wan VAE)
- Shot 2 frame 0: Heavy spots/halos (VAE overbake)
- Shot 2 frame 1-2: Fading artifacts
- Shot 2 frame 3+: Clean

**Root Cause:**

The VAE decoder "overbakes" whatever frame is in position 0 of the latent batch. This is specific to I2V because the init_frame latent interacts with generated latents. Bridge-based shots have more "tension" (blending identity + pose), amplifying artifacts.

**The Solution:**

Request extra frames, then trim post-download:
```python
# In _build_generation_params:
if job.has_init_frame:
    frame_count += VAE_ARTIFACT_FRAMES  # Request 28 instead of 25

# In generate(), after download:
if job.has_init_frame:
    output_path = await self._trim_vae_artifacts(output_path, job)
```

**Idempotency Logic (Important):**
```python
# Original (BROKEN): skipped if actual <= expected
if actual_frames <= expected_frames:  # 24 <= 25 â†’ SKIP (wrong!)

# Fixed: skip only if too short to trim
min_frames_for_trim = job.frame_count - frames_to_trim  # 25 - 3 = 22
if actual_frames < min_frames_for_trim:  # 24 < 22 â†’ NO, TRIM (correct!)
```

**Trade-off:** Videos ~0.25s shorter than requested. Acceptable given artifact removal.

**Future Optimization:** Could skip trim for Shot 1 (minimal artifacts) to preserve full duration. Low priority.

---

### 87. Wan 2.1 LoRA Training - Complete Requirements

| | |
|---|---|
| **Date** | 2026-01-03 |
| **Error** | Multiple failed attempts: wrong tools, missing dependencies, OOM errors |
| **Root Cause** | Not reading full documentation before starting; reacting to errors instead of planning |

**CORRECT TOOL: musubi-tuner (by kohya-ss)**
```bash
git clone --recursive https://github.com/kohya-ss/musubi-tuner.git
cd musubi-tuner
pip install -e .
```

**WRONG TOOLS (Do NOT use for Wan):**
- âŒ `kohya-ss/sd-scripts` - Built for SD/SDXL UNet, not DiT architecture
- âŒ `tdrussell/diffusion-pipe` - Path conflicts with ComfyUI's `utils` module
- âŒ `ostris/ai-toolkit` - bitsandbytes/triton version incompatibilities

**I2V vs T2V Training Requirements:**

| Requirement | T2V | I2V |
|-------------|-----|-----|
| VAE | âœ… | âœ… |
| T5 (original .pth format) | âœ… | âœ… |
| CLIP model | âŒ | âœ… **REQUIRED** |
| `--i2v` flag in cache | âŒ | âœ… |
| `--clip` flag in cache | âŒ | âœ… |

**T5 Model Format Matters:**
- ComfyUI uses: `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (repackaged, different key names)
- Musubi-tuner needs: `models_t5_umt5-xxl-enc-bf16.pth` (original format)

Download correct format:
```bash
python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('Wan-AI/Wan2.1-I2V-14B-480P', 'models_t5_umt5-xxl-enc-bf16.pth', local_dir='./models')"
```

**CLIP Model (Required for I2V only):**
```bash
python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('Wan-AI/Wan2.1-I2V-14B-480P', 'models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth', local_dir='./models')"
```

**Dataset Config Format (TOML):**
```toml
# CORRECT key name
[general]
resolution = [512, 512]
caption_extension = ".txt"
batch_size = 1
enable_bucket = true

[[datasets]]
image_directory = "/path/to/images"  # NOT "image_dir"
cache_directory = "/path/to/cache"
```

**Pre-caching is MANDATORY (Training fails without this):**
```bash
# Step 1: Cache latents (add --clip and --i2v for I2V models)
python3 wan_cache_latents.py \
  --dataset_config dataset.toml \
  --vae /path/to/wan_2.1_vae.safetensors \
  --clip /path/to/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth \
  --i2v

# Step 2: Cache text encoder outputs
python3 wan_cache_text_encoder_outputs.py \
  --dataset_config dataset.toml \
  --t5 /path/to/models_t5_umt5-xxl-enc-bf16.pth \
  --batch_size 4
```

**VRAM Requirements for 14B Model:**

| VRAM | blocks_to_swap | Speed |
|------|----------------|-------|
| 48GB+ | 0 | Fast |
| 24GB | 35 | ~6s/step |
| 16GB | Not feasible | - |

**Complete I2V Training Command:**
```bash
python3 wan_train_network.py \
  --task i2v-14B \
  --dit /path/to/wan2.1_i2v_480p_14B_fp16.safetensors \
  --dataset_config dataset.toml \
  --sdpa \
  --mixed_precision fp16 \
  --fp8_base \
  --optimizer_type adamw \
  --learning_rate 1e-4 \
  --gradient_checkpointing \
  --blocks_to_swap 35 \
  --max_data_loader_n_workers 2 \
  --network_module networks.lora_wan \
  --network_dim 32 \
  --network_alpha 16 \
  --timestep_sampling shift \
  --discrete_flow_shift 5.0 \
  --max_train_epochs 50 \
  --save_every_n_epochs 10 \
  --seed 42 \
  --output_dir /path/to/output \
  --output_name my_lora
```

**Key Flags:**
- `--network_module networks.lora_wan` - MUST use this for Wan (not default)
- `--blocks_to_swap 35` - Required for 24GB VRAM with 14B model
- `--fp8_base` - Reduces VRAM usage
- `--discrete_flow_shift 5.0` - Recommended for I2V (3.0 for T2V)

**Output Location:**
LoRA saves to: `/path/to/output/my_lora.safetensors`
Copy to ComfyUI: `/workspace/runpod-slim/ComfyUI/models/loras/`

**Prevention:**
1. ALWAYS read musubi-tuner docs BEFORE starting: https://github.com/kohya-ss/musubi-tuner/blob/main/docs/wan.md
2. Search for community guides on Civitai before troubleshooting blind
3. Don't guess at tool compatibility - Wan uses DiT architecture, not UNet
4. Pre-caching is not optional - training will fail with "No training items found"

---

### 88. Consistency Dict Auto-Discovery & Project/Bible Separation

| | |
|---|---|
| **Date** | 2026-01-03 |
| **Error** | `No face reference image available. Hero frame will use prompt-only generation.` followed by `Unresolved placeholders: {'FACE_REF_IMAGE', 'IPADAPTER_STRENGTH'}` |
| **Root Cause** | Embedded "bible" section in project JSON is ignored; consistency dict must be separate file |

**Architecture Principle (from ARCHITECTURE.md):**
- Scene Graph (project JSON) = WHO appears WHERE (scenes, shots, prompts)
- Consistency Dictionary (bible JSON) = WHAT they LOOK LIKE (LoRAs, face_refs, descriptions)

These are **intentionally separate** per Section 2A:
> "Maintain a Consistency Dictionary: Alice -> canonical asset IDs (LoRA, reference images, keyframes)"

**Wrong (ignored):**
```json
// project.json with embedded bible - IGNORED!
{
  "project_id": "demo",
  "bible": {
    "characters": { "alice": {...} }
  },
  "scenes": [...]
}
```

**Correct (two files):**
```bash
# Project file: scenes/shots/prompts
matrix_zero_project.json

# Consistency dict: assets/identity
matrix_zero_consistency.json
```

**Auto-Discovery (added in main.py):**

After this fix, `main.py` auto-discovers consistency dict in this order:
1. `{project_stem}_consistency.json` (e.g., `matrix_zero_consistency.json`)
2. `consistency.json` in same directory
3. `bible.json` in same directory

Or explicit: `python main.py -p project.json -c consistency.json`

**Consistency Dict Format:**
```json
{
  "characters": {
    "ayush": {
      "entity_id": "ayush",
      "entity_type": "character",
      "name": "Ayush",
      "description": "ayush, a man with black hair and beard",
      "lora_path": "/path/to/lora.safetensors",
      "lora_strength": 0.85,
      "face_refs": ["/path/to/face_ref.png"],
      "style_notes": "",
      "voice_id": null,
      "tags": []
    }
  },
  "locations": {...},
  "props": {...}
}
```

**File Placement:**
```
project_dir/
├── matrix_zero_project.json      # Scene graph
├── matrix_zero_consistency.json  # Auto-discovered!
└── ...
```

**Prevention:**
1. Always create separate consistency dict file for character assets
2. Name it `{project}_consistency.json` for auto-discovery
3. Don't embed bible in project JSON - it's ignored
4. Check logs for "Characters: 0" warning - means consistency dict not loaded

---

### 89. Remote Path Validation - Mac Orchestrator vs RunPod Assets

| | |
|---|---|
| **Date** | 2026-01-03 |
| **Error** | `Generating hero frame: identity_strength=weak (prompt only), has_face_ref=False` even though face_ref was found |
| **Root Cause** | `Path.exists()` called on RunPod paths from Mac - always returns False |

**Architecture Context:**
- Mac orchestrates (runs main.py, pass1_generator, bridge_engine)
- RunPod renders (has ComfyUI, models, assets at `/workspace/`)
- Paths like `/workspace/runpod-slim/ComfyUI/input/ayush_ref.png` exist on RunPod but NOT on Mac

**Wrong (validates locally):**
```python
@property
def has_face_ref(self) -> bool:
    return self.face_ref_path is not None and self.face_ref_path.exists()
    # /workspace/... → False on Mac!
```

**Correct (handles remote paths):**
```python
def _is_remote_path(path: Optional[Path]) -> bool:
    """Check if path exists on remote ComfyUI server."""
    if path is None:
        return False
    path_str = str(path)
    remote_prefixes = ("/workspace/", "/comfyui/", "/models/", "/root/")
    return any(path_str.startswith(prefix) for prefix in remote_prefixes)

def _path_exists_or_remote(path: Optional[Path]) -> bool:
    """Check if path exists locally OR is a remote path (assumed valid)."""
    if path is None:
        return False
    return _is_remote_path(path) or path.exists()

@property
def has_face_ref(self) -> bool:
    return self.face_ref_path is not None and _path_exists_or_remote(self.face_ref_path)
```

**Files Fixed:**
- `src/studio/bridge_engine.py` - Added `_is_remote_path()`, `_path_exists_or_remote()`, fixed `has_face_ref`
- `src/studio/pass1_generator.py` - Fixed face_ref existence check in `_get_face_ref_as_init_frame()`

**Prevention:**
1. Never use bare `path.exists()` for asset paths that might be on ComfyUI server
2. Use `_path_exists_or_remote()` helper instead
3. Remote path prefixes: `/workspace/`, `/comfyui/`, `/models/`, `/root/`
4. For uploads, use `_upload_or_use_remote()` helper - skips upload if path is already remote
5. Actual file validation happens when ComfyUI loads the file (fails there if missing)

**Related Fix - Upload Logic:**

When uploading files for workflows, remote paths should NOT be uploaded (they already exist):

```python
# Wrong (tries to open local file):
remote_ref = await self.client.upload_image(face_ref_path)

# Correct (skips upload for remote paths):
async def _upload_or_use_remote(self, file_path: Path) -> str:
    if _is_remote_path(file_path):
        return file_path.name  # Just use filename, file already on server
    else:
        return await self.client.upload_image(file_path)
```

---
*Add new entries above this line as they're discovered.*