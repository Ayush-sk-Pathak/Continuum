#!/usr/bin/env python3
"""
Bridge Frame → Shot 2 I2V Pipeline Test

Tests the Shot 2+ flow:
1. Generate Bridge Frame (SDXL img2img + IP-Adapter) from Shot 1's last frame
2. Feed Bridge Frame to Wan I2V + LoRA → Shot 2 video

This validates:
    "Bridge Frame re-anchors identity at every shot boundary"

Usage:
    python test_bridge_to_i2v.py
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
# STAGE 1: Bridge Frame (SDXL img2img + IP-Adapter)
# ============================================================================
# Takes last frame of Shot 1, re-anchors identity via IP-Adapter

bridge_frame_workflow = {
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
    # Source = last frame of Shot 1 (preserves pose/composition)
    "load_source": {
        "class_type": "LoadImage",
        "inputs": {
            "image": "shot1_last_frame.png"
        }
    },
    # Face ref = canonical identity reference
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
            "weight": 0.7,  # Lower than hero frame - preserve more of source pose
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
    # img2img: encode source frame to latent
    "vae_encode": {
        "class_type": "VAEEncode",
        "inputs": {
            "pixels": ["load_source", 0],
            "vae": ["checkpoint_loader", 2]
        }
    },
    "positive_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "a man with black hair and beard, turning to look at camera, kitchen background, soft cinematic lighting, high quality",
            "clip": ["checkpoint_loader", 1]
        }
    },
    "negative_prompt": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, distorted, ugly, watermark, deformed face, bad anatomy",
            "clip": ["checkpoint_loader", 1]
        }
    },
    "sampler": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 54321,
            "control_after_generate": "fixed",
            "steps": 25,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 0.45,  # Low denoise = preserve source structure
            "model": ["apply_ipadapter", 0],
            "positive": ["positive_prompt", 0],
            "negative": ["negative_prompt", 0],
            "latent_image": ["vae_encode", 0]
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
            "filename_prefix": "bridge_frame_ayush",
            "images": ["vae_decode", 0]
        }
    }
}

# ============================================================================
# STAGE 2: Shot 2 I2V from Bridge Frame
# ============================================================================

def create_shot2_workflow(bridge_frame_filename: str) -> dict:
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
                "image": bridge_frame_filename
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
                # Different action for Shot 2
                "text": "ayush, a man with black hair and beard, turns and smiles at camera, reaches for door handle, smooth natural motion, cinematic",
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
                "seed": 99999,  # Different seed for Shot 2
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
                "filename_prefix": "shot2_from_bridge",
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
        print(f"❌ Failed to submit: {response.json()}")
        return None
    
    prompt_id = response.json().get("prompt_id")
    print(f"✅ Submitted! prompt_id: {prompt_id}")
    print(f"Waiting...")
    
    for i in range(timeout_sec // 5):
        time.sleep(5)
        try:
            history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if outputs:
                    print(f"\n✅ {stage_name} COMPLETED!")
                    return {"prompt_id": prompt_id, "outputs": outputs}
                    
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    print(f"\n❌ {stage_name} FAILED!")
                    messages = status.get("messages", [])
                    for msg in messages:
                        if msg[0] == "execution_error":
                            print(f"Error: {msg[1].get('exception_message', 'Unknown')}")
                    return None
        except:
            pass
        print(f"  ... {(i+1)*5}s elapsed", end="\r")
    
    print(f"\n⚠️ {stage_name} timeout")
    return None


# ============================================================================
# MAIN
# ============================================================================

print("\n" + "="*60)
print("BRIDGE FRAME → SHOT 2 I2V PIPELINE TEST")
print("="*60)
print("Stage 1: Generate Bridge Frame (SDXL img2img + IP-Adapter)")
print("         Source: shot1_last_frame.png (preserves pose)")
print("         Face ref: ayush_ref.png (re-anchors identity)")
print("Stage 2: Generate Shot 2 Video (Wan I2V + LoRA)")
print("="*60)

# Stage 1: Bridge Frame
result1 = submit_and_wait(bridge_frame_workflow, "BRIDGE FRAME GENERATION", timeout_sec=120)

if not result1:
    print("\n❌ Pipeline failed at Stage 1")
    exit(1)

# Extract bridge frame filename
try:
    for node_id, node_output in result1["outputs"].items():
        if "images" in node_output:
            bridge_filename = node_output["images"][0]["filename"]
            print(f"\n🌉 Bridge Frame saved: {bridge_filename}")
            break
    else:
        print("❌ Could not find bridge frame")
        exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# Copy bridge frame to input (via API would be better, but manual for now)
print(f"\n⚠️  MANUAL STEP REQUIRED:")
print(f"    Run on RunPod:")
print(f"    cp /workspace/runpod-slim/ComfyUI/output/{bridge_filename} /workspace/runpod-slim/ComfyUI/input/")
print(f"\n    Then press Enter to continue...")
input()

# Stage 2: Shot 2 I2V
shot2_workflow = create_shot2_workflow(bridge_filename)
result2 = submit_and_wait(shot2_workflow, "SHOT 2 I2V FROM BRIDGE", timeout_sec=300)

if not result2:
    print("\n❌ Pipeline failed at Stage 2")
    exit(1)

print("\n" + "="*60)
print("✅ BRIDGE → SHOT 2 PIPELINE COMPLETED!")
print("="*60)
print(f"Bridge Frame: {bridge_filename}")
print(f"Shot 2 Video: {json.dumps(result2['outputs'], indent=2)}")
print("\nFiles to compare for identity consistency:")
print("  - Shot 1: hero_to_i2v_ayush_00001.mp4")
print("  - Shot 2: shot2_from_bridge_00001.mp4")
print("="*60)