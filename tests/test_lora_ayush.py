#!/usr/bin/env python3
"""
Quick LoRA Test - Ayush Identity
Run from Mac to test LoRA integration on RunPod ComfyUI

Usage:
    python test_lora_ayush.py
    
Requirements:
    - CONTINUUM_COMFYUI__HOST env var set to RunPod URL
    - LoRA file in ComfyUI/models/loras/
    - Reference image in ComfyUI/input/
"""

import json
import os
import requests
import time

# Get ComfyUI URL from environment or use default
COMFY_HOST = os.environ.get("CONTINUUM_COMFYUI__HOST", "").replace("wss://", "https://").replace("ws://", "http://")
if not COMFY_HOST:
    print("ERROR: Set CONTINUUM_COMFYUI__HOST environment variable")
    print("Example: export CONTINUUM_COMFYUI__HOST='wss://pqxvbl6yfyywo3-8188.proxy.runpod.net'")
    exit(1)

# Remove trailing slash if present
COMFY_URL = COMFY_HOST.rstrip("/")
print(f"Using ComfyUI at: {COMFY_URL}")

# ============================================================================
# WORKFLOW: Wan 2.1 I2V with LoRA
# ============================================================================
# Based on working pass1_img2vid.json from RunPod
# Key fix: WanImageToVideo uses "start_image" not "image"

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
    
    # LoRA loader - inject after UNET, before model_sampling
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
            "model": ["lora_loader", 0]  # Chain through LoRA
        }
    },
    "load_image": {
        "class_type": "LoadImage",
        "inputs": {
            "image": "ayush_ref.png"
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
            "text": "ayush, a man with black hair and beard, smiling warmly and nodding slightly, soft cinematic lighting, 4k quality",
            "clip": ["lora_loader", 1]  # Use LoRA-modified CLIP
        }
    },
    "negative_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, distorted, ugly, watermark, deformed face, bad anatomy, extra limbs",
            "clip": ["lora_loader", 1]  # Use LoRA-modified CLIP
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
            "start_image": ["load_image", 0]  # FIXED: start_image not image
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
            "filename_prefix": "lora_test_ayush",
            "format": "video/h264-mp4",
            "pingpong": False,
            "save_output": True,
            "images": ["vae_decode", 0]
        }
    }
}

# ============================================================================
# SUBMIT AND MONITOR
# ============================================================================

print("\n" + "="*60)
print("SUBMITTING LORA TEST JOB")
print("="*60)
print(f"Trigger: 'ayush, a man with black hair and beard'")
print(f"LoRA: ayush_wan21_i2v_v1.safetensors (strength 0.85)")
print(f"Init image: ayush_ref.png")
print(f"Output: 49 frames @ 12fps (~4 seconds)")
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
        print(f"\nMonitor at: {COMFY_URL}")
        print(f"Output will be saved as: lora_test_ayush_XXXXX.mp4")
        
        # Poll for completion
        print("\nWaiting for completion (this may take 2-5 minutes)...")
        for i in range(120):  # Max 10 minutes
            time.sleep(5)
            try:
                history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    if outputs:
                        print(f"\n✅ COMPLETED!")
                        print(f"Outputs: {json.dumps(outputs, indent=2)}")
                        break
                    status = history[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        print(f"\n❌ FAILED!")
                        print(f"Error: {status}")
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
    print("Is ComfyUI running on RunPod?")
except Exception as e:
    print(f"❌ Error: {e}")