# HANDOFF DOCUMENT: HunyuanCustom Model Pivot

**Date:** December 29, 2025  
**Status:** Phase 4 VALIDATED ✅ — Identity Preservation WORKING  
**RunPod Pod:** Active (many_apricot_mastodon / wgd210t4whoc3b)

---

## 1. PROJECT CONTEXT

### What is Continuum Engine?
A neuro-symbolic AI filmmaking system that allows writers to generate consistent, multi-shot videos. The system uses:
- **Director Agent** (Local Brain): Parses scripts, manages consistency
- **Visual Pipeline** (Cloud Muscle): Renders video via ComfyUI on RunPod
- **Sonic Engine**: Generates audio, dialogue, lip sync

### Key Architecture Files
- `/mnt/project/ARCHITECTURE.md` — Master blueprint
- `/mnt/project/MODEL_PIVOT.md` — Migration guide (Wan → HunyuanCustom)
- `/mnt/project/LESSONS_LEARNED.md` — Error patterns and solutions
- `/mnt/project/src/renderers/` — Renderer implementations

---

## 2. WHY WE'RE SWITCHING MODELS

### The Problem with Wan 2.1
- **Identity drift**: Characters change appearance across shots
- **ArcFace score**: Only 0.204 (poor identity preservation)
- **Requires IP-Adapter**: Complex workaround for face consistency
- **Bridge Engine required**: Extra complexity for shot continuity

### Why HunyuanCustom is Better

| Metric | HunyuanCustom | Wan 2.1 (VACE) | Improvement |
|--------|---------------|----------------|-------------|
| ArcFace Score | **0.627** | 0.204 | **3× better** |
| External face reference | ✅ Native via `<image>` token | ❌ Requires IP-Adapter | Simpler |
| Multi-subject | ✅ Up to 2 characters | ❌ No | New capability |
| Bridge Engine needed | **Optional** | Required | Simpler pipeline |

### Design Constraint (Critical)
Switching models must be a single environment variable:
```bash
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom  # or "wan"
```
No code changes required.

---

## 3. IMPLEMENTATION STATUS

### Phases Overview

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Pre-flight validation on RunPod | ✅ **COMPLETE** |
| Phase 1 | Infrastructure (config, loaders) | ✅ **COMPLETE** |
| Phase 2 | HunyuanCustomRenderer implementation | ✅ **COMPLETE** |
| Phase 3 | main.py integration | ✅ **COMPLETE** |
| Phase 4 | Identity preservation testing | 🔄 **NEXT** |
| Phase 5 | Performance optimization | ⏳ Pending |

---

## 4. PHASE 0 VALIDATION RESULTS (Completed Earlier)

### What We Tested
- 4x RTX 4090 on RunPod ($2.00/hr, 96GB VRAM total)
- HunyuanCustom 13B FP8 model
- Kijai's ComfyUI-HunyuanVideoWrapper

### Results
✅ **Models load correctly** — No OOM errors  
✅ **Video generates** — 25 frames at 512x512  
✅ **All dependencies work** — After installing missing packages  

---

## 5. PHASE 4 IDENTITY TESTING RESULTS (Just Completed)

### Key Discovery: Two Workflows, Different Results

| Workflow | Identity Quality | Why |
|----------|------------------|-----|
| `hyvideo_custom_testing_01.json` | ❌ Poor | Uses basic CLIP Vision only |
| `hyvideo_ip2v_experimental_dango.json` | ✅ **Good** | Uses full LLaVA vision-language model |

### Critical Model Requirements for Identity

The **full HunyuanCustom identity pipeline** requires:

1. **Video model**: `hunyuan_video_custom_720p_fp8_scaled.safetensors` (13GB) ✅
2. **Full LLaVA LLM**: `xtuner/llava-llama-3-8b-v1_1-transformers` (16GB) ✅ **CRITICAL**
3. **CLIP Vision**: `llava_llama3_vision.safetensors` (650MB) ✅
4. **Text encoders**: `clip_l.safetensors` + `llava_llama3_fp16.safetensors` ✅

**Without the full LLaVA LLM (16GB), you only get CLIP-level identity — similar to Wan with IP-Adapter.**

### LLaVA Model Location
```
/workspace/runpod-slim/ComfyUI/models/LLM/llava-llama-3-8b-v1_1-transformers/
├── model-00001-of-00004.safetensors (5.0 GB)
├── model-00002-of-00004.safetensors (4.9 GB)
├── model-00003-of-00004.safetensors (5.0 GB)
├── model-00004-of-00004.safetensors (1.8 GB)
└── [config files]
Total: 16 GB
```

### Identity Test Results

**Test: Beach running scene with Alice reference**

| Attempt | Workflow | CLIP Vision Model | LLM Model | Result |
|---------|----------|-------------------|-----------|--------|
| 1 | custom_testing_01 | clip_vision_h | None | ❌ Wrong person (man boxing panda) |
| 2 | custom_testing_01 | llava_llama3_vision | None | ⚠️ Similar hair/clothing, face distorted |
| 3 | custom_testing_01 | llava_llama3_vision | None | ⚠️ Better, but still basic CLIP |
| 4 | custom_testing_01 | llava_llama3_vision | xtuner/llava-llama-3-8b | ✅ **Good identity match!** |

### Final Working Configuration

**Workflow:** `hyvideo_custom_testing_01.json` (simpler, works)

**Node Settings:**
- **Load CLIP Vision**: `llava_llama3_vision.safetensors`
- **DualCLIPLoader**: `clip_l.safetensors` + `llava_llama3_fp16.safetensors`
- **Model Loader**: `hunyuan_video_custom_720p_fp8_scaled.safetensors`
- **Attention mode**: `sdpa` (not sageattn)

**Prompt format:**
```
Realistic, High-quality. <image> is [action], [scene description].
```

**Fast test settings:**
- width: 512, height: 512
- num_frames: 25
- steps: 15

### Remaining Issues (Not Blockers)

1. **Reference image bleeds into scene** — Indoor photo causes indoor→outdoor transition
2. **Limited motion in 25 frames** — Need 49+ frames for significant movement
3. **Flickering** — Expected, needs Pass 2 refinement

### Why This Matters

The `<image>` token + LLaVA fusion is what gives HunyuanCustom its **0.627 ArcFace score** (3× better than Wan's 0.204). Without the full LLaVA model, you're just using CLIP embeddings.

---

## 5. RUNPOD SETUP GUIDE (Validated)

### Required Models (Total ~30GB)

| File | Size | Location | Source |
|------|------|----------|--------|
| `hunyuan_video_custom_720p_fp8_scaled.safetensors` | ~13 GB | `models/diffusion_models/` | `Kijai/HunyuanVideo_comfy` |
| `hunyuan_video_vae_bf16.safetensors` | ~500 MB | `models/vae/` | `Kijai/HunyuanVideo_comfy` |
| `clip_l.safetensors` | ~235 MB | `models/text_encoders/` | `comfyanonymous/flux_text_encoders` |
| `llava_llama3_fp16.safetensors` | ~16 GB | `models/text_encoders/` | `Comfy-Org/HunyuanVideo_repackaged` |
| `llava_llama3_vision.safetensors` | ~650 MB | `models/clip_vision/` | `Comfy-Org/HunyuanVideo_repackaged` |

### Required Extensions
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper
git clone https://github.com/pollockjj/ComfyUI-MultiGPU
cd ComfyUI-HunyuanVideoWrapper && pip3 install -r requirements.txt
```

### Required Python Packages
```bash
pip3 install scikit-image    # Fixes blank page issue
pip3 install sageattention   # For sageattn mode (optional, can use sdpa instead)
```

### Download Commands
```bash
cd /workspace/runpod-slim/ComfyUI/models

# Main model
huggingface-cli download Kijai/HunyuanVideo_comfy \
  hunyuan_video_custom_720p_fp8_scaled.safetensors \
  --local-dir diffusion_models/

# VAE
huggingface-cli download Kijai/HunyuanVideo_comfy \
  hunyuan_video_vae_bf16.safetensors \
  --local-dir vae/

# Text encoders
cd text_encoders/
huggingface-cli download comfyanonymous/flux_text_encoders \
  clip_l.safetensors --local-dir ./

huggingface-cli download Comfy-Org/HunyuanVideo_repackaged \
  split_files/text_encoders/llava_llama3_fp16.safetensors --local-dir ./
mv split_files/text_encoders/llava_llama3_fp16.safetensors ./
rm -rf split_files/

# CLIP Vision
cd ../clip_vision/
huggingface-cli download Comfy-Org/HunyuanVideo_repackaged \
  split_files/clip_vision/llava_llama3_vision.safetensors --local-dir ./
mv split_files/clip_vision/llava_llama3_vision.safetensors ./
rm -rf split_files/
```

---

## 6. ISSUES ENCOUNTERED & SOLUTIONS

### Issue 1: Blank ComfyUI Page / 502 Bad Gateway
**Cause:** Missing `scikit-image` package  
**Fix:** `pip3 install scikit-image`

### Issue 2: 404 Errors Downloading Text Encoders
**Cause:** Files not in Kijai's repo  
**Fix:** Use `Comfy-Org/HunyuanVideo_repackaged` and `comfyanonymous/flux_text_encoders`

### Issue 3: "Can't import SageAttention"
**Cause:** Missing sageattention package  
**Fix:** Either `pip3 install sageattention` OR change `attention_mode` to `sdpa` in Model Loader node

### Issue 4: "Value not in list" Validation Errors
**Cause:** Workflow had wrong paths like `Hyvid\model.safetensors`  
**Fix:** Select correct model from dropdown (without `Hyvid\` prefix)

---

## 7. FILES CREATED/MODIFIED IN THIS SESSION

### New Files (in /mnt/user-data/outputs/)
These need to be copied to the project:

| Output File | Destination in Project |
|-------------|----------------------|
| `hunyuan_custom_renderer.py` | `src/renderers/hunyuan_custom_renderer.py` |
| `__init__.py` (renderers) | `src/renderers/__init__.py` |
| `pass1_img2vid.json` | `workflows/hunyuan_custom/pass1_img2vid.json` |
| `base.py` | `src/renderers/base.py` |
| `config.py` | `src/core/config.py` |
| `model_loader.py` | `src/comfy_client/model_loader.py` |
| `workflow_loader.py` | `src/comfy_client/workflow_loader.py` |
| `models.json` | `models.json` |
| `main.py` | `main.py` |

### Modified Files
- `LESSONS_LEARNED.md` — Added entries 79-81 (RunPod issues, download sources, extensions)

---

## 8. NEXT STEPS (Post-Identity Validation)

### Immediate Priority: Integration into Continuum Pipeline

Now that identity is validated, integrate HunyuanCustom into the main codebase:

1. **Update `hunyuan_custom_renderer.py`** to use the correct workflow with LLaVA
2. **Create proper workflow JSON** (`pass1_img2vid_hunyuan.json`) with all correct node connections
3. **Test via Python API** (not just ComfyUI UI)

### Workflow Integration Checklist

- [ ] Ensure `llm_model` parameter is set to `xtuner/llava-llama-3-8b-v1_1-transformers`
- [ ] Ensure `clip_vision` uses `llava_llama3_vision.safetensors`
- [ ] Prompt template includes `<image>` token
- [ ] Test with `client.py` WebSocket connection

### Quality Improvements (Later)

1. **More frames** — 49-97 for 2-4 second clips
2. **Higher resolution** — 720x480 or 720p
3. **Pass 2 refinement** — Vid2vid for flicker reduction
4. **Better reference images** — Neutral headshots without background context

---

## 9. KEY ARCHITECTURAL DECISIONS

### Renderer Factory Pattern
```python
# main.py now uses factory, not hardcoded WanRenderer
from src.renderers.base import get_renderer_for_config
self.renderer = get_renderer_for_config(self.config)
```

### Model Selection via Environment
```bash
# Default (Wan)
python main.py --project my_project.json

# HunyuanCustom
CONTINUUM_VIDEO_MODEL__MODEL_FAMILY=hunyuan_custom python main.py --project my_project.json
```

### Workflow Directory Structure
```
workflows/
├── wan/                    # Wan-specific workflows
├── hunyuan_custom/         # HunyuanCustom-specific workflows
└── shared/                 # Model-agnostic (bridge, hero_frame, etc.)
```

---

## 10. CRITICAL REMINDERS

1. **Don't run HunyuanCustom on single RTX 4090** — needs 60-80GB VRAM (use 4x 4090 or H100)

2. **Workflow JSON paths matter** — select models from dropdown, don't type paths manually

3. **The `<image>` token is key** — without it, HunyuanCustom is just a regular I2V model

4. **Bridge Engine may be optional** — HunyuanCustom's native identity preservation might eliminate need for bridge frames

5. **Check LESSONS_LEARNED.md** — entries 79-81 have RunPod-specific gotchas

---

## 11. TRANSCRIPT LOCATION

Full conversation transcript available at:
```
/mnt/transcripts/2025-12-29-07-49-43-model-pivot-phase1-3-complete.txt
```

Previous session transcript:
```
/mnt/transcripts/2025-12-29-07-17-51-model-pivot-phase1-complete.txt
```

---

## 12. STATUS SUMMARY

| Component | Status | Notes |
|-----------|--------|-------|
| Hardware | ✅ Ready | 4x RTX 4090, 101.2 GB VRAM |
| Storage | ✅ Sufficient | 125 GB volume (expanded from 100) |
| ComfyUI | ✅ Running | Use `nohup` to keep alive! |
| Video Model | ✅ Working | `hunyuan_video_custom_720p_fp8_scaled.safetensors` |
| LLaVA LLM | ✅ Downloaded | `xtuner/llava-llama-3-8b-v1_1-transformers` (16GB) |
| CLIP Vision | ✅ Correct | `llava_llama3_vision.safetensors` |
| Text Encoders | ✅ Working | CLIP-L + LLaVA FP16 |
| Identity Test | ✅ **PASSED** | Face matches reference with `<image>` token |
| Phase 4 | ✅ **COMPLETE** | Identity preservation validated |

---

## 13. CRITICAL LESSONS FROM THIS SESSION

### Lesson 82: Keep ComfyUI Alive with nohup
```bash
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```
Without `nohup`, process dies when terminal disconnects.

### Lesson 83: Full LLaVA Model Required for Identity
- `llava_llama3_vision.safetensors` (650MB) = just vision encoder = basic CLIP-level identity
- `xtuner/llava-llama-3-8b-v1_1-transformers` (16GB) = full vision-language model = **true identity preservation**

### Lesson 84: The `<image>` Token is Critical
Prompt MUST include `<image>` for identity injection:
```
✅ "Realistic, High-quality. <image> is running on a beach."
❌ "Realistic, High-quality. A woman is running on a beach."
```

### Lesson 85: CLIP Vision Model Selection
- ❌ `clip_vision_h.safetensors` — generic CLIP, poor identity
- ✅ `llava_llama3_vision.safetensors` — LLaVA vision encoder, good identity

---

## 14. QUICK START FOR NEXT SESSION

```bash
# 1. Start ComfyUI (if not running)
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &

# 2. Verify running
sleep 15
curl -s http://localhost:8188/system_stats | head -5

# 3. View logs if needed
tail -f /workspace/runpod-slim/comfyui.log
```

**Browser URL:** `https://wgd210t4whoc3b-8188.proxy.runpod.net`

**Working Workflow:** `hyvideo_custom_testing_01.json`

**Key Node Settings:**
- Load CLIP Vision: `llava_llama3_vision.safetensors`
- DualCLIPLoader: `clip_l.safetensors` + `llava_llama3_fp16.safetensors`
- Model: `hunyuan_video_custom_720p_fp8_scaled.safetensors`
- Prompt: Must include `<image>` token

**Fast Test:** 512x512, 25 frames, 15 steps

---

## 15. TOTAL MODEL INVENTORY (After Phase 4)

```
/workspace/runpod-slim/ComfyUI/models/
├── diffusion_models/
│   └── hunyuan_video_custom_720p_fp8_scaled.safetensors (13 GB)
├── vae/
│   └── hunyuan_video_vae_bf16.safetensors (471 MB)
├── text_encoders/
│   ├── clip_l.safetensors (235 MB)
│   ├── llava_llama3_fp16.safetensors (15 GB)
│   └── umt5_xxl_fp8_e4m3fn_scaled.safetensors (6.3 GB) [Wan]
├── clip_vision/
│   ├── clip_vision_h.safetensors (1.2 GB) [Don't use]
│   └── llava_llama3_vision.safetensors (649 MB) [Use this!]
└── LLM/
    └── llava-llama-3-8b-v1_1-transformers/ (16 GB) [CRITICAL for identity]
```

**Total HunyuanCustom models:** ~46 GB  
**Total storage used:** ~107 GB / 125 GB

---

**END OF HANDOFF**