#!/bin/bash
#
# Minimal HunyuanCustom Identity Test
# Tests the validated workflow directly via API - no Python involved
#
# Usage: ./test_identity.sh <RUNPOD_HOST> <IMAGE_PATH>
# Example: ./test_identity.sh 8gsp074fx2q6p3-8188.proxy.runpod.net workspace/assets/alice/alice_01.png
#

set -e

HOST="${1:-8gsp074fx2q6p3-8188.proxy.runpod.net}"
IMAGE="${2:-workspace/assets/alice/alice_01.png}"
HTTP_URL="https://${HOST}"

echo "========================================"
echo "HUNYUAN IDENTITY TEST (Bash)"
echo "========================================"
echo "Host: $HTTP_URL"
echo "Image: $IMAGE"
echo ""

# Step 1: Upload image
echo "[1/3] Uploading image..."
UPLOAD_RESULT=$(curl -s -X POST "${HTTP_URL}/upload/image" \
  -F "image=@${IMAGE}" \
  -F "overwrite=true")

UPLOADED_NAME=$(echo "$UPLOAD_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])" 2>/dev/null || echo "FAILED")

if [ "$UPLOADED_NAME" = "FAILED" ]; then
  echo "ERROR: Upload failed. Response: $UPLOAD_RESULT"
  exit 1
fi
echo "      Uploaded as: $UPLOADED_NAME"

# Step 2: Build workflow JSON (exact copy of validated workflow)
echo "[2/3] Building workflow..."

# This is the EXACT workflow from hyvideo_custom_testing_01_validated.json
# converted to API format, with only the image name substituted
WORKFLOW=$(cat << WORKFLOW_EOF
{
  "60": {
    "class_type": "HyVideoBlockSwap",
    "inputs": {
      "double_blocks_to_swap": 20,
      "single_blocks_to_swap": 0,
      "offload_txt_in": false,
      "offload_img_in": false
    }
  },
  "7": {
    "class_type": "HyVideoVAELoader",
    "inputs": {
      "model_name": "hunyuan_video_vae_bf16.safetensors",
      "precision": "bf16"
    }
  },
  "1": {
    "class_type": "HyVideoModelLoader",
    "inputs": {
      "block_swap_args": ["60", 0],
      "model": "hunyuan_video_custom_720p_fp8_scaled.safetensors",
      "base_precision": "bf16",
      "quantization": "fp8_scaled",
      "load_device": "offload_device",
      "attention_mode": "sdpa",
      "auto_cpu_offload": false,
      "upcast_rope": true
    }
  },
  "42": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "${UPLOADED_NAME}"
    }
  },
  "43": {
    "class_type": "ImageResizeKJv2",
    "inputs": {
      "image": ["42", 0],
      "width": 720,
      "height": 480,
      "upscale_method": "lanczos",
      "keep_proportion": "pad",
      "pad_color": "255,255,255",
      "crop_position": "center",
      "divisible_by": 16,
      "device": "cpu"
    }
  },
  "54": {
    "class_type": "DualCLIPLoader",
    "inputs": {
      "clip_name1": "clip_l.safetensors",
      "clip_name2": "llava_llama3_fp16.safetensors",
      "type": "hunyuan_video",
      "device": "default"
    }
  },
  "56": {
    "class_type": "CLIPVisionLoader",
    "inputs": {
      "clip_name": "llava_llama3_vision.safetensors"
    }
  },
  "55": {
    "class_type": "CLIPVisionEncode",
    "inputs": {
      "clip_vision": ["56", 0],
      "image": ["43", 0],
      "crop": "center"
    }
  },
  "51": {
    "class_type": "TextEncodeHunyuanVideo_ImageToVideo",
    "inputs": {
      "clip": ["54", 0],
      "clip_vision_output": ["55", 0],
      "prompt": "Realistic, High-quality. <image> is turning her head slightly and smiles warmly at the camera.",
      "image_interleave": 2
    }
  },
  "52": {
    "class_type": "TextEncodeHunyuanVideo_ImageToVideo",
    "inputs": {
      "clip": ["54", 0],
      "clip_vision_output": ["55", 0],
      "prompt": "Aerial view, overexposed, low quality, deformation, bad composition, bad hands, bad teeth, bad eyes, bad limbs, distortion, blurring, text, subtitles, static, picture, black border.",
      "image_interleave": 2
    }
  },
  "41": {
    "class_type": "HyVideoEncode",
    "inputs": {
      "vae": ["7", 0],
      "image": ["43", 0],
      "enable_vae_tiling": false,
      "temporal_tiling_sample_size": 64,
      "spatial_tile_sample_min_size": 256,
      "auto_tile_size": true,
      "noise_aug_strength": 0,
      "latent_strength": 1,
      "latent_dist": "sample"
    }
  },
  "74": {
    "class_type": "HyVideoTextEmbedBridge",
    "inputs": {
      "positive": ["51", 0],
      "negative": ["52", 0],
      "cfg": 7.5,
      "start_percent": 0,
      "end_percent": 1,
      "batched_cfg": false,
      "use_cfg_zero_star": true
    }
  },
  "62": {
    "class_type": "HyVideoSampler",
    "inputs": {
      "model": ["1", 0],
      "hyvid_embeds": ["74", 0],
      "image_cond_latents": ["41", 0],
      "width": ["43", 1],
      "height": ["43", 2],
      "num_frames": 25,
      "steps": 25,
      "embedded_guidance_scale": 0,
      "flow_shift": 13.0,
      "seed": 12345,
      "force_offload": true,
      "denoise_strength": 1,
      "scheduler": "FlowMatchDiscreteScheduler",
      "riflex_freq_index": 0,
      "i2v_mode": "dynamic"
    }
  },
  "5": {
    "class_type": "HyVideoDecode",
    "inputs": {
      "vae": ["7", 0],
      "samples": ["62", 0],
      "enable_vae_tiling": true,
      "temporal_tiling_sample_size": 64,
      "spatial_tile_sample_min_size": 256,
      "auto_tile_size": true,
      "skip_latents": 0,
      "balance_brightness": false
    }
  },
  "34": {
    "class_type": "VHS_VideoCombine",
    "inputs": {
      "images": ["5", 0],
      "frame_rate": 24,
      "loop_count": 0,
      "filename_prefix": "bash_identity_test",
      "format": "video/h264-mp4",
      "pingpong": false,
      "save_output": true,
      "pix_fmt": "yuv420p",
      "crf": 19,
      "save_metadata": true,
      "trim_to_audio": false
    }
  }
}
WORKFLOW_EOF
)

# Save for inspection
echo "$WORKFLOW" > /tmp/test_workflow.json
echo "      Workflow saved to /tmp/test_workflow.json"
echo "      Key params: noise_aug_strength=0, attention_mode=sdpa"

# Step 3: Submit to ComfyUI
echo "[3/3] Submitting to ComfyUI..."

PROMPT_RESULT=$(curl -s -X POST "${HTTP_URL}/prompt" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": $WORKFLOW}")

PROMPT_ID=$(echo "$PROMPT_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt_id', 'ERROR'))" 2>/dev/null)

if [ "$PROMPT_ID" = "ERROR" ] || [ -z "$PROMPT_ID" ]; then
  echo "ERROR: Submit failed. Response: $PROMPT_RESULT"
  exit 1
fi

echo "      Prompt ID: $PROMPT_ID"
echo ""
echo "========================================"
echo "SUCCESS! Job submitted."
echo "========================================"
echo ""
echo "Watch ComfyUI for output: bash_identity_test_*.mp4"
echo ""
echo "NEXT STEPS:"
echo "1. Wait for job to complete (~3-5 min)"
echo "2. Check output video in ComfyUI"
echo "3. Compare identity with the UI-generated video"
echo ""
echo "If this produces GOOD identity:"
echo "   -> Bug is in our Python code (workflow building/params)"
echo ""
echo "If this produces BAD identity:"
echo "   -> Bug is elsewhere (models, ComfyUI, image itself)"
echo ""