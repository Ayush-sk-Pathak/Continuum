# Handoff: Wan 2.1 I2V LoRA Training Session
**Date:** 2026-01-03
**Session Duration:** ~3 hours
**Status:** ✅ LoRA Training COMPLETED

---

## 🎯 What Was Achieved

### Successfully Started Wan 2.1 I2V LoRA Training
- **Tool:** musubi-tuner (kohya-ss) - the ONLY correct tool for Wan LoRA training
- **Model:** Wan 2.1 I2V 14B (480p)
- **Dataset:** 19 images of "ayush" (man with black hair and beard)
- **Training Status:** 34% complete, loss dropped from 0.00627 → 0.00086 (excellent)

### Training Command (For Reference)
```bash
python3 wan_train_network.py \
  --task i2v-14B \
  --dit /workspace/runpod-slim/ComfyUI/models/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors \
  --dataset_config /workspace/musubi-tuner/dataset/dataset.toml \
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
  --output_dir /workspace/lora_output \
  --output_name ayush_wan21_i2v_v1
```

---

## 📁 Key File Locations (RunPod)

### Training Infrastructure
| Item | Path |
|------|------|
| Training tool | `/workspace/musubi-tuner/` |
| Dataset config | `/workspace/musubi-tuner/dataset/dataset.toml` |
| Training images | `/workspace/ayush/` (19 images + captions) |
| Latent cache | `/workspace/ayush_cache/` |
| T5 model (correct format) | `/workspace/musubi-tuner/models/models_t5_umt5-xxl-enc-bf16.pth` |
| CLIP model (I2V required) | `/workspace/musubi-tuner/models/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth` |

### Output Locations
| Item | Path |
|------|------|
| LoRA output dir | `/workspace/lora_output/` |
| Final LoRA | `/workspace/lora_output/ayush_wan21_i2v_v1.safetensors` |
| Checkpoint (epoch 10) | `/workspace/lora_output/ayush_wan21_i2v_v1-step000190.safetensors` |
| ComfyUI LoRA folder | `/workspace/runpod-slim/ComfyUI/models/loras/` |

### Existing Models (Already on RunPod)
| Model | Path |
|-------|------|
| Wan 2.1 I2V 14B | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors` |
| Wan VAE | `/workspace/runpod-slim/ComfyUI/models/vae/wan_2.1_vae.safetensors` |
| T5 (ComfyUI format) | `/workspace/runpod-slim/ComfyUI/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` |

---

## ⚠️ Critical Lessons Learned (Added to LESSONS_LEARNED.md #87)

### Wrong Tools (DO NOT USE for Wan)
- ❌ `kohya-ss/sd-scripts` - Built for SD/SDXL UNet, not DiT
- ❌ `tdrussell/diffusion-pipe` - Path conflicts with ComfyUI
- ❌ `ostris/ai-toolkit` - bitsandbytes/triton issues

### I2V vs T2V Training Requirements
| Requirement | T2V | I2V |
|-------------|-----|-----|
| VAE | ✅ | ✅ |
| T5 (original .pth) | ✅ | ✅ |
| CLIP model | ❌ | ✅ **REQUIRED** |
| `--i2v` flag | ❌ | ✅ |
| `--clip` flag | ❌ | ✅ |

### VRAM Requirements for 14B
| VRAM | --blocks_to_swap | Works? |
|------|------------------|--------|
| 48GB+ | 0 | ✅ Fast |
| 24GB | 35 | ✅ ~7s/step |
| 24GB | 20 | ❌ OOM |

### T5 Model Format
- **ComfyUI uses:** `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (repackaged)
- **Musubi-tuner needs:** `models_t5_umt5-xxl-enc-bf16.pth` (original)
- They are the SAME weights, different formats - both can coexist

---

## 🏛️ Architecture Updates Made This Session

### Progressive Identity System (NEW)
Added to both `ARCHITECTURE.md` and `ARCHITECTURE_SUMMARY.md`:

- **Section 3A.1** in ARCHITECTURE.md - Complete rewrite
- **Identity Tiers** based on REAL image count (not augmentation)
- **Key insight:** Augmenting 1 image causes drift to compound - quality cannot be faked
- **InstantID/PuLID** for instant onboarding (zero-shot, 1 image)
- **Business model alignment** - users self-select tier by effort invested

| Tier | Images | Method | Identity | Price |
|------|--------|--------|----------|-------|
| Instant | 1 | InstantID/PuLID | ~85% | Free |
| Quick | 1-4 | LoRA (epoch 10-15) | ~88-90% | $5 |
| Standard | 5-10 | LoRA (epoch 30) | ~92-94% | $10 |
| Premium | 15-20 | LoRA (epoch 50) | ~95%+ | $20 |

### New Glossary Terms
- InstantID, PuLID, Identity Tier, Progressive Identity

### Updated MVP Priorities
- Added InstantID/PuLID as #3 priority (after Shot 1 Pipeline and Bridge Frame)

---

### Code EXISTS and is Implemented
| Component | File | Status |
|-----------|------|--------|
| Hero Frame workflow | `hero_frame.json` | ✅ Written |
| Hero Frame generation | `bridge_engine.py` | ✅ `generate_hero_frame()` |
| Shot1Strategy routing | `pass1_generator.py` | ✅ HERO_FRAME/USER_KEYFRAME/EXPLORATION |
| Bridge Frame workflow | `bridge_full.json` | ✅ Written |
| Bridge Engine | `bridge_engine.py` | ✅ Full implementation |
| Pass1 Generator | `pass1_generator.py` | ✅ Full pipeline |
| Identity Checker | `identity_checker.py` | ⚠️ Interface only (ArcFace stubbed) |

### NOT Yet Done
| Task | Status |
|------|--------|
| LoRA integrated into workflows | ❌ Pending |
| Hero frame tested with LoRA | ❌ Pending |
| Bridge frame tested with LoRA | ❌ Pending |
| ArcFace real implementation | ❌ Stubbed |
| DWPreprocessor node on RunPod | ❌ Missing |
| Director Agent (LLM parsing) | ❌ Manual JSON only |
| End-to-end multi-shot test | ❌ Pending |

---

## 📋 Next Steps (Priority Order)

### IMMEDIATE (Next Session - Start RunPod Pod)

**Step 1: Copy LoRA to ComfyUI (RunPod)**
```bash
cp /workspace/lora_output/ayush_wan21_i2v_v1.safetensors \
   /workspace/runpod-slim/ComfyUI/models/loras/

ls -la /workspace/runpod-slim/ComfyUI/models/loras/
```

**Step 2: Test LoRA with Simple I2V (RunPod)**
- Modify `pass1_img2vid.json` to include LoRA loader node
- Generate 5-second test video with prompt containing "ayush"
- Visually verify identity matches training images

**Step 3: Test Hero Frame Pipeline (RunPod)**
- Use `hero_frame.json` with IP-Adapter + LoRA
- Verify Shot 1 init frame has correct identity

**Step 4: Test Bridge Frame Pipeline (RunPod)**
- Use `bridge_full.json` with ControlNet + IP-Adapter
- Verify identity re-anchoring works across shots

**Step 5: Run 3-Shot End-to-End Test (RunPod)**
- Shot 1: Hero Frame → I2V
- Shot 2: Bridge Frame → I2V
- Shot 3: Bridge Frame → I2V
- Measure identity consistency across all shots

### LATER (Mac + RunPod)

**Step 6: Implement Real ArcFace Audit (RunPod)**
- Replace stubbed identity_checker with real ArcFace
- Set threshold to 0.70 (currently relaxed to 0.50)

**Step 7: Director Agent Integration (Mac)**
- Wire LLM API calls for script → scene graph parsing
- Currently manual JSON, needs automation

---

## 🔧 Hardware Context

| Layer | Hardware | What Runs There |
|-------|----------|-----------------|
| Brain (Local) | MacBook Air M4 | Python orchestration, job dispatch |
| Brain (Cloud) | LLM APIs | Director Agent (Claude/GPT/Gemini) |
| Muscle (Cloud) | RunPod 4090 | ComfyUI, Video Inference, LoRA Training |

**Current RunPod Pod:**
- URL: `64fmyf01qtfmij-8888.proxy.runpod.net` (JupyterLab)
- GPU: RTX 4090 (24GB)
- Cost: ~$2.38/hr
- Persistent storage at `/workspace/`

---

## 📊 Training Results (COMPLETED)

```
Epoch 50/50 ✅
Steps: 950/950 (100%)
Final Loss: 0.00122
Total Time: ~1h 52min
```

**Checkpoints saved (all in /workspace/lora_output/):**
- `ayush_wan21_i2v_v1-step000190.safetensors` (epoch 10)
- `ayush_wan21_i2v_v1-000030.safetensors` (epoch 30) 
- `ayush_wan21_i2v_v1-000040.safetensors` (epoch 40)
- `ayush_wan21_i2v_v1.safetensors` (epoch 50) ← **FINAL**

**Note on loss:** Final loss 0.00122 is healthy. Epoch 30 checkpoint (loss ~0.0005) may be slightly overfit - test both if needed.

---

## 📖 Key Documentation

| Doc | Purpose |
|-----|---------|
| `ARCHITECTURE.md` | Full system design |
| `ARCHITECTURE_SUMMARY.md` | Dev-facing implementation guide |
| `LESSONS_LEARNED.md` | Error log and fixes (entry #87 = LoRA training) |
| `MODEL_PIVOT.md` | Model selection strategy |
| `/workspace/musubi-tuner/docs/wan.md` | Official Wan training guide |

---

## ✅ Summary

**This session achieved:**
1. ✅ Successfully trained Wan 2.1 I2V LoRA (50 epochs, loss 0.00122)
2. ✅ Documented complete training pipeline in LESSONS_LEARNED.md (#87)
3. ✅ Added Progressive Identity System to architecture docs
4. ✅ All checkpoints saved to persistent storage (/workspace/)

**The LoRA enables identity-locked video generation** - the core capability needed for the Continuum Engine's consistency promise.

**Next session should:**
1. Start RunPod pod (files persist in /workspace/)
2. Copy LoRA to ComfyUI models folder
3. Test LoRA with simple I2V generation
4. Test hero frame → I2V → bridge frame pipeline
5. Run multi-shot consistency test

**Mac project location:** `~/Projects/Continuum`

---

*End of Handoff*