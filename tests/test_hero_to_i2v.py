#!/usr/bin/env python3
"""
Hero Frame â†’ I2V Pipeline Test

Tests the full Shot 1 flow:
1. Generate Hero Frame (SDXL + IP-Adapter) - identity-locked init image
2. Feed Hero Frame to Wan I2V + LoRA - generate video

This validates the architecture claim:
    "Shot 1 uses Hero Frame (SDXL + IP-Adapter) --> I2V"

Usage:
    python test_hero_to_i2v.py
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

# ============================================================================
# STAGE 1: Hero Frame (SDXL + IP-Adapter)
# ============================================================================

hero_frame_workflow = {
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
            "text": "a man with black hair and beard, standing in a modern kitchen, soft natural lighting, cinematic composition, 4k, high quality portrait",
            "clip": ["checkpoint_loader", 1]
        }
    },
    "negative_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, distorted, ugly, watermark, deformed face, bad anatomy, extra limbs, low quality",
            "clip": ["checkpoint_loader", 1]
        }
    },
    "sampler": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
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
# STAGE 2: I2V with LoRA (uses hero frame as init)
# ============================================================================

def create_i2v_workflow(hero_frame_filename: str) -> dict:
    """Create I2V workflow using the generated hero frame."""
    return {
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
                "image": hero_frame_filename  # Use hero frame!
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


def submit_and_wait(workflow: dict, stage_name: str, timeout_sec: int = 600) -> dict:
    """Submit workflow and wait for completion."""
    print(f"\n{'='*60}")
    print(f"STAGE: {stage_name}")
    print(f"{'='*60}")
    
    response = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=30)
    
    if response.status_code != 200:
        print(f"âŒ Failed to submit: {response.json()}")
        return None
    
    prompt_id = response.json().get("prompt_id")
    print(f"âœ… Submitted! prompt_id: {prompt_id}")
    print(f"Waiting for completion...")
    
    for i in range(timeout_sec // 5):
        time.sleep(5)
        try:
            history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if outputs:
                    print(f"\nâœ… {stage_name} COMPLETED!")
                    return {"prompt_id": prompt_id, "outputs": outputs}
                    
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    print(f"\nâŒ {stage_name} FAILED!")
                    print(f"Error: {status}")
                    return None
        except Exception:
            pass  # Network hiccup, keep polling
        print(f"  ... {(i+1)*5}s elapsed", end="\r")
    
    print(f"\nâš ï¸ {stage_name} timeout after {timeout_sec}s")
    return None


# ============================================================================
# MAIN EXECUTION
# ============================================================================

print("\n" + "="*60)
print("HERO FRAME â†’ I2V PIPELINE TEST")
print("="*60)
print("Stage 1: Generate Hero Frame (SDXL + IP-Adapter)")
print("Stage 2: Generate Video (Wan I2V + LoRA) from Hero Frame")
print("="*60)

# Stage 1: Hero Frame
result1 = submit_and_wait(hero_frame_workflow, "HERO FRAME GENERATION", timeout_sec=120)

if not result1:
    print("\nâŒ Pipeline failed at Stage 1")
    exit(1)

# Extract hero frame filename from outputs
# SaveImage outputs: {"images": [{"filename": "...", "subfolder": "...", "type": "output"}]}
try:
    hero_outputs = result1["outputs"]
    # Find the save_image node output
    for node_id, node_output in hero_outputs.items():
        if "images" in node_output:
            hero_filename = node_output["images"][0]["filename"]
            hero_subfolder = node_output["images"][0].get("subfolder", "")
            print(f"\nðŸ“¸ Hero Frame saved: {hero_filename}")
            break
    else:
        print("âŒ Could not find hero frame in outputs")
        exit(1)
except Exception as e:
    print(f"âŒ Error parsing hero frame output: {e}")
    print(f"Raw outputs: {result1['outputs']}")
    exit(1)

# Stage 2: I2V from Hero Frame
# ComfyUI SaveImage saves to output/, LoadImage reads from input/
# We need to copy or reference correctly
# For now, use the full path that ComfyUI understands
if hero_subfolder:
    hero_path = f"{hero_subfolder}/{hero_filename}"
else:
    hero_path = hero_filename

print(f"\nðŸŽ¬ Using hero frame for I2V: {hero_path}")

i2v_workflow = create_i2v_workflow(hero_path)
result2 = submit_and_wait(i2v_workflow, "I2V FROM HERO FRAME", timeout_sec=300)

if not result2:
    print("\nâŒ Pipeline failed at Stage 2")
    exit(1)

print("\n" + "="*60)
print("âœ… FULL PIPELINE COMPLETED!")
print("="*60)
print(f"Hero Frame: {hero_filename}")
print(f"Video outputs: {json.dumps(result2['outputs'], indent=2)}")
print("="*60)