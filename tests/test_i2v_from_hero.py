#!/usr/bin/env python3
"""
Stage 2 Only: I2V from Hero Frame
Uses already-generated hero_frame_ayush_00002_.png
"""

import json
import os
import requests
import time

COMFY_HOST = os.environ.get("CONTINUUM_COMFYUI__HOST", "").replace("wss://", "https://").replace("ws://", "http://")
if not COMFY_HOST:
    print("ERROR: Set CONTINUUM_COMFYUI__HOST environment variable")
    exit(1)

COMFY_URL = COMFY_HOST.rstrip("/")
print(f"Using ComfyUI at: {COMFY_URL}")

# Hero frame already in input/ folder
HERO_FRAME = "hero_frame_ayush_00002_.png"

workflow = {
    "clip_loader": {
        "class_type": "CLIPLoader",
        "inputs": {
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "wan",
            "device": "default"
        }
    },
    "vae_loader": {
        "class_type": "VAELoader",
        "inputs": {
            "vae_name": "wan_2.1_vae.safetensors"
        }
    },
    "unet_loader": {
        "class_type": "UNETLoader",
        "inputs": {
            "unet_name": "wan2.1_i2v_480p_14B_fp16.safetensors",
            "weight_dtype": "default"
        }
    },
    "clip_vision_loader": {
        "class_type": "CLIPVisionLoader",
        "inputs": {
            "clip_name": "clip_vision_h.safetensors"
        }
    },
    "lora_loader": {
        "class_type": "LoraLoader",
        "inputs": {
            "lora_name": "ayush_wan21_i2v_v1.safetensors",
            "strength_model": 0.85,
            "strength_clip": 0.0,
            "model": ["unet_loader", 0],
            "clip": ["clip_loader", 0]
        }
    },
    "model_sampling": {
        "class_type": "ModelSamplingSD3",
        "inputs": {
            "shift": 8,
            "model": ["lora_loader", 0]
        }
    },
    "load_image": {
        "class_type": "LoadImage",
        "inputs": {
            "image": HERO_FRAME
        }
    },
    "clip_vision_encode": {
        "class_type": "CLIPVisionEncode",
        "inputs": {
            "crop": "none",
            "clip_vision": ["clip_vision_loader", 0],
            "image": ["load_image", 0]
        }
    },
    "positive_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "ayush, a man with black hair and beard, walking through kitchen, picks up a coffee mug, smooth motion, cinematic lighting",
            "clip": ["lora_loader", 1]
        }
    },
    "negative_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, distorted, ugly, watermark, deformed face, bad anatomy, extra limbs",
            "clip": ["lora_loader", 1]
        }
    },
    "wan_i2v": {
        "class_type": "WanImageToVideo",
        "inputs": {
            "width": 832,
            "height": 480,
            "length": 49,
            "batch_size": 1,
            "positive": ["positive_prompt", 0],
            "negative": ["negative_prompt", 0],
            "vae": ["vae_loader", 0],
            "clip_vision_output": ["clip_vision_encode", 0],
            "start_image": ["load_image", 0]
        }
    },
    "sampler": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "control_after_generate": "fixed",
            "steps": 20,
            "cfg": 6.0,
            "sampler_name": "uni_pc",
            "scheduler": "simple",
            "denoise": 1,
            "model": ["model_sampling", 0],
            "positive": ["wan_i2v", 0],
            "negative": ["wan_i2v", 1],
            "latent_image": ["wan_i2v", 2]
        }
    },
    "vae_decode": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["sampler", 0],
            "vae": ["vae_loader", 0]
        }
    },
    "save_video": {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "frame_rate": 12,
            "loop_count": 0,
            "filename_prefix": "hero_to_i2v_ayush",
            "format": "video/h264-mp4",
            "pingpong": False,
            "save_output": True,
            "images": ["vae_decode", 0]
        }
    }
}

print(f"\n{'='*60}")
print(f"I2V FROM HERO FRAME: {HERO_FRAME}")
print(f"{'='*60}\n")

response = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=30)
print(f"Response status: {response.status_code}")

if response.status_code != 200:
    print(f"❌ Failed: {json.dumps(response.json(), indent=2)}")
    exit(1)

prompt_id = response.json().get("prompt_id")
print(f"✅ Submitted! prompt_id: {prompt_id}")
print(f"Waiting for completion (3-5 minutes)...")

for i in range(120):
    time.sleep(5)
    try:
        history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            if outputs:
                print(f"\n✅ COMPLETED!")
                print(f"Outputs: {json.dumps(outputs, indent=2)}")
                exit(0)
            status = history[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                print(f"\n❌ FAILED: {status}")
                exit(1)
    except:
        pass
    print(f"  ... {(i+1)*5}s elapsed", end="\r")

print("\n⚠️ Timeout")