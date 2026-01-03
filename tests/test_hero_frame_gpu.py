#!/usr/bin/env python3
"""
Hero Frame Test - Shot 1 Identity-Locked Init Frame
Run from Mac to test SDXL + IP-Adapter hero frame generation

This is Step 1 of the Shot 1 pipeline:
  Hero Frame (SDXL + IP-Adapter) → generates IMAGE
  Then: IMAGE → Wan I2V + LoRA → generates VIDEO

Usage:
    python test_hero_frame_gpu.py
    
Requirements:
    - CONTINUUM_COMFYUI__HOST env var set
    - SDXL checkpoint in ComfyUI/models/checkpoints/
    - IP-Adapter model in ComfyUI/models/ipadapter/
    - Face reference image in ComfyUI/input/
"""

import json
import os
import requests
import time

# Get ComfyUI URL from environment
COMFY_HOST = os.environ.get("CONTINUUM_COMFYUI__HOST", "").replace("wss://", "https://").replace("ws://", "http://")
if not COMFY_HOST:
    print("ERROR: Set CONTINUUM_COMFYUI__HOST environment variable")
    exit(1)

COMFY_URL = COMFY_HOST.rstrip("/")
print(f"Using ComfyUI at: {COMFY_URL}")

# ============================================================================
# WORKFLOW: Hero Frame (SDXL + IP-Adapter)
# ============================================================================
# Based on hero_frame.json - txt2img with identity injection

workflow = {
    "checkpoint_loader": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": "sd_xl_base_1.0.safetensors"
        }
    },

    "ipadapter_loader": {
        "class_type": "IPAdapterModelLoader",
        "inputs": {
            "ipadapter_file": "ip-adapter-plus-face_sdxl_vit-h.safetensors"
        }
    },

    "clip_vision_loader": {
        "class_type": "CLIPVisionLoader",
        "inputs": {
            "clip_name": "clip_vision_h.safetensors"
        }
    },

    "load_face_ref": {
        "class_type": "LoadImage",
        "inputs": {
            "image": "ayush_ref.png"
        }
    },

    "prep_face_ref": {
        "class_type": "PrepImageForClipVision",
        "inputs": {
            "interpolation": "LANCZOS",
            "crop_position": "center",
            "sharpening": 0,
            "image": ["load_face_ref", 0]
        }
    },

    "apply_ipadapter": {
        "class_type": "IPAdapterAdvanced",
        "inputs": {
            "weight": 0.85,
            "weight_type": "linear",
            "combine_embeds": "concat",
            "start_at": 0,
            "end_at": 1,
            "embeds_scaling": "V only",
            "model": ["checkpoint_loader", 0],
            "ipadapter": ["ipadapter_loader", 0],
            "clip_vision": ["clip_vision_loader", 0],
            "image": ["prep_face_ref", 0]
        }
    },

    "empty_latent": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 832,
            "height": 480,
            "batch_size": 1
        }
    },

    "positive_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "ayush, a man with black hair and beard, portrait photo, looking at camera, soft cinematic lighting, neutral background, high quality, detailed face",
            "clip": ["checkpoint_loader", 1]
        }
    },

    "negative_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, distorted, ugly, watermark, deformed face, bad anatomy, extra limbs, cartoon, anime, illustration",
            "clip": ["checkpoint_loader", 1]
        }
    },

    "sampler": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "control_after_generate": "fixed",
            "steps": 25,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["apply_ipadapter", 0],
            "positive": ["positive_prompt", 0],
            "negative": ["negative_prompt", 0],
            "latent_image": ["empty_latent", 0]
        }
    },

    "vae_decode": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["sampler", 0],
            "vae": ["checkpoint_loader", 2]
        }
    },

    "save_image": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "hero_frame_ayush",
            "images": ["vae_decode", 0]
        }
    }
}

# ============================================================================
# SUBMIT AND MONITOR
# ============================================================================

print("\n" + "="*60)
print("SUBMITTING HERO FRAME JOB")
print("="*60)
print("Purpose: Generate identity-locked init frame for Shot 1")
print("Method: SDXL + IP-Adapter (txt2img from noise)")
print(f"Face ref: ayush_ref.png")
print(f"IP-Adapter weight: 0.85")
print(f"Output: hero_frame_ayush_XXXXX.png")
print("="*60 + "\n")

try:
    response = requests.post(
        f"{COMFY_URL}/prompt",
        json={"prompt": workflow},
        timeout=30
    )
    
    print(f"Response status: {response.status_code}")
    result = response.json()
    
    if response.status_code == 200:
        prompt_id = result.get("prompt_id", "unknown")
        print(f"✅ Job submitted! prompt_id: {prompt_id}")
        print(f"\nWaiting for completion (usually 15-30 seconds)...")
        
        for i in range(60):  # Max 5 minutes
            time.sleep(5)
            try:
                history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    if outputs:
                        print(f"\n✅ COMPLETED!")
                        print(f"Outputs: {json.dumps(outputs, indent=2)}")
                        
                        # Extract filename
                        for node_id, node_output in outputs.items():
                            if "images" in node_output:
                                for img in node_output["images"]:
                                    print(f"\n📸 Hero frame saved: {img.get('filename', 'unknown')}")
                                    print(f"   Location: /workspace/runpod-slim/ComfyUI/output/{img.get('filename', '')}")
                        break
                    status = history[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        print(f"\n❌ FAILED!")
                        print(f"Error: {json.dumps(status, indent=2)}")
                        break
            except Exception as e:
                pass
            print(f"  ... {(i+1)*5}s elapsed", end="\r")
        else:
            print("\n⚠️ Timeout - check ComfyUI manually")
            
    else:
        print(f"❌ Failed to submit job!")
        print(f"Error: {json.dumps(result, indent=2)}")

except requests.exceptions.ConnectionError:
    print(f"❌ Cannot connect to {COMFY_URL}")
except Exception as e:
    print(f"❌ Error: {e}")