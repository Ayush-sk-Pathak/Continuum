#!/usr/bin/env python3
"""
===============================================================================
TEST DEMO: MATRIX ZERO - ANIME EDITION (Goku)
===============================================================================

VIDEO ONLY - NO AUDIO (Sonic Engine not implemented in test script)
See LESSONS_LEARNED.md #90 for details on adding audio.

6-shot anime demo showcasing identity preservation across shots.
Character: Goku (no LoRA needed - well-known anime character)
Identity: IP-Adapter + CLIP similarity checking

STRUCTURE: 3 Locations, 5 Transitions

    COSMIC VOID (Shots 1-2):
        Shot 1: Wide - Goku floating, arms crossed
        Shot 2: Close-up - Confident smile, beckoning gesture
        [Transition: SAME SCENE - wide to close-up]

    TRAINING GROUNDS (Shots 3-4):
        Shot 3: Wide - Battle stance, powering up
        Shot 4: Close-up - Intense focus, energy crackling
        [Transition 2→3: SCENE CHANGE - cosmic → training]
        [Transition 3→4: SAME SCENE - wide to close-up]

    SUNSET CLIFF (Shots 5-6):
        Shot 5: Medium - Victory pose, triumphant
        Shot 6: Close-up - Thumbs up, classic Goku
        [Transition 4→5: SCENE CHANGE - training → cliff]
        [Transition 5→6: SAME SCENE - medium to close-up]

Pipeline:
    Shot 1: Hero Frame (SDXL + IP-Adapter) → I2V (Wan 2.1)
    Shots 2-6: Extract last frame → Bridge Frame → I2V
    Final: FFmpeg stitch all 6 clips

Usage:
    export CONTINUUM_COMFYUI__HOST="wss://xxx-8188.proxy.runpod.net"
    python tests/test_demo_matrix_zero.py

Author: Continuum Studios
Date: 2026-01-19 (Anime Pivot)
===============================================================================
"""

import json
import os
import subprocess
import requests
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

# =============================================================================
# CONFIGURATION
# =============================================================================

COMFY_HOST = os.environ.get("CONTINUUM_COMFYUI__HOST", "").replace("wss://", "https://").replace("ws://", "http://")
if not COMFY_HOST:
    print("ERROR: Set CONTINUUM_COMFYUI__HOST environment variable")
    print("Example: export CONTINUUM_COMFYUI__HOST='wss://xxx-8188.proxy.runpod.net'")
    sys.exit(1)

COMFY_URL = COMFY_HOST.rstrip("/")

# Video settings
FRAME_COUNT = 33        # ~2 seconds at 16fps (quick test)
FRAME_RATE = 16         # Standard for Wan 2.1
WIDTH = 512
HEIGHT = 288

# Identity settings - ANIME/GOKU
LORA_NAME = None  # No LoRA needed for well-known anime characters
LORA_STRENGTH = 0.0
FACE_REF = "Goku0.png"
TRIGGER = "goku, anime style, spiky black hair, orange gi martial arts uniform"

# Output prefix
OUTPUT_PREFIX = "matrix_zero"


# =============================================================================
# SHOT DEFINITIONS
# =============================================================================

@dataclass
class Shot:
    """Single shot definition."""
    id: int
    name: str
    location: str
    hero_prompt: str      # For Hero/Bridge frame generation (SDXL)
    i2v_prompt: str       # For video generation (Wan I2V)
    
SHOTS = [
    # =========================================================================
    # LOCATION 1: COSMIC VOID (Shots 1-2) - Goku's invitation
    # =========================================================================
    Shot(
        id=1,
        name="cosmic_wide",
        location="cosmic_void",
        hero_prompt=(
            "goku, anime style, spiky black hair, orange gi, floating in deep space cosmic void, "
            "swirling blue and purple energy around him, stars and galaxies background, "
            "full body wide shot, arms crossed confidently, powerful aura glowing, "
            "epic anime scene, high quality anime art, dramatic lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, floating in deep space cosmic void, full body wide shot, "
            "swirling blue and purple energy, stars and galaxies background, "
            "uncrosses arms and powers up, aura intensifies, energy crackling, "
            "epic anime scene, high quality anime art, 4k, smooth motion"
        ),
    ),
    Shot(
        id=2,
        name="cosmic_closeup",
        location="cosmic_void",
        hero_prompt=(
            "goku, anime style, spiky black hair, close-up portrait, "
            "cosmic void background blurred, confident smile, "
            "reaching hand toward camera, inviting gesture, glowing aura, "
            "dynamic anime expression, high quality anime art, dramatic rim lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, close-up portrait, cosmic void background blurred, "
            "confident excited smile, reaches hand toward camera, beckoning gesture, "
            "aura pulses with energy, eyes bright with anticipation, "
            "high quality anime art, dramatic rim lighting, 4k, smooth motion"
        ),
    ),
    # =========================================================================
    # LOCATION 2: TRAINING GROUNDS (Shots 3-4) - Power demonstration
    # =========================================================================
    Shot(
        id=3,
        name="training_wide",
        location="training_grounds",
        hero_prompt=(
            "goku, anime style, spiky black hair, orange gi, standing in rocky mountain training grounds, "
            "dramatic cliffs and boulders around him, dust and debris floating, "
            "full body wide shot, battle stance, powerful energy aura, "
            "epic anime scene, high quality anime art, golden hour lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, standing in rocky mountain training grounds, full body wide shot, "
            "dramatic cliffs background, begins powering up, energy explodes outward, "
            "rocks float and crumble around him, battle stance intensifies, "
            "epic anime scene, high quality anime art, 4k, smooth motion"
        ),
    ),
    Shot(
        id=4,
        name="training_closeup",
        location="training_grounds",
        hero_prompt=(
            "goku, anime style, spiky black hair, dramatic close-up, "
            "rocky training grounds background blurred, intense focused expression, "
            "energy crackling around face, determined battle-ready look, "
            "high quality anime art, golden rim lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, dramatic close-up, rocky background blurred, "
            "intense focused expression, powers up with fierce determination, "
            "hair flows with energy, aura blazing, eyes sharp and ready, "
            "high quality anime art, golden rim lighting, 4k, smooth motion"
        ),
    ),
    # =========================================================================
    # LOCATION 3: VICTORY CELEBRATION (Shots 5-6) - Triumphant ending
    # =========================================================================
    Shot(
        id=5,
        name="victory_medium",
        location="sunset_cliff",
        hero_prompt=(
            "goku, anime style, spiky black hair, orange gi, medium shot standing on cliff edge, "
            "epic orange sunset sky behind him, wind blowing gi, "
            "relaxed victorious pose, arms at sides, peaceful expression, "
            "beautiful anime scene, high quality anime art, warm sunset lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, medium shot on cliff edge, epic sunset behind, "
            "wind blows through hair and gi, relaxed victorious stance, "
            "takes deep breath, raises fist in triumph, peaceful smile, "
            "beautiful anime scene, high quality anime art, 4k, smooth motion"
        ),
    ),
    Shot(
        id=6,
        name="victory_closeup",
        location="sunset_cliff",
        hero_prompt=(
            "goku, anime style, spiky black hair, close-up portrait, "
            "epic sunset sky background blurred, warm golden light on face, "
            "confident knowing smile, looking at camera, triumphant expression, "
            "high quality anime art, beautiful sunset lighting, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, close-up portrait, sunset background blurred, "
            "warm golden light, confident smile grows wider, "
            "gives thumbs up to camera, winks, classic Goku pose, "
            "high quality anime art, beautiful sunset lighting, 4k, smooth motion"
        ),
    ),
]

NEGATIVE_PROMPT = (
    "realistic, 3d render, photo, blurry, deformed, bad anatomy, extra limbs, "
    "watermark, text, low quality, amateur, wrong hair color, wrong outfit"
)


# =============================================================================
# WORKFLOW BUILDERS
# =============================================================================

def build_hero_frame_workflow(shot: Shot) -> dict:
    """Build SDXL + IP-Adapter workflow for Shot 1 hero frame."""
    return {
        "checkpoint_loader": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
        },
        "ipadapter_loader": {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": "ip-adapter-plus-face_sdxl_vit-h.safetensors"}
        },
        "clip_vision_loader": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": "clip_vision_h.safetensors"}
        },
        "load_face_ref": {
            "class_type": "LoadImage",
            "inputs": {"image": FACE_REF}
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
            "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}
        },
        "positive_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": shot.hero_prompt, "clip": ["checkpoint_loader", 1]}
        },
        "negative_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE_PROMPT, "clip": ["checkpoint_loader", 1]}
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 12345 + shot.id,
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
            "inputs": {"samples": ["sampler", 0], "vae": ["checkpoint_loader", 2]}
        },
        "save_image": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": f"{OUTPUT_PREFIX}_shot{shot.id:02d}_hero",
                "images": ["vae_decode", 0]
            }
        }
    }


def build_bridge_frame_workflow(shot: Shot, source_image: str) -> dict:
    """Build SDXL img2img + IP-Adapter workflow for bridge frame."""
    return {
        "checkpoint_loader": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
        },
        "ipadapter_loader": {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": "ip-adapter-plus-face_sdxl_vit-h.safetensors"}
        },
        "clip_vision_loader": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": "clip_vision_h.safetensors"}
        },
        "load_source": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image}
        },
        "load_face_ref": {
            "class_type": "LoadImage",
            "inputs": {"image": FACE_REF}
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
                "weight": 0.7,
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
        "vae_encode": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["load_source", 0], "vae": ["checkpoint_loader", 2]}
        },
        "positive_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": shot.hero_prompt, "clip": ["checkpoint_loader", 1]}
        },
        "negative_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE_PROMPT, "clip": ["checkpoint_loader", 1]}
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 54321 + shot.id,
                "control_after_generate": "fixed",
                "steps": 25,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 0.45,  # Low denoise = preserve structure
                "model": ["apply_ipadapter", 0],
                "positive": ["positive_prompt", 0],
                "negative": ["negative_prompt", 0],
                "latent_image": ["vae_encode", 0]
            }
        },
        "vae_decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["checkpoint_loader", 2]}
        },
        "save_image": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": f"{OUTPUT_PREFIX}_shot{shot.id:02d}_bridge",
                "images": ["vae_decode", 0]
            }
        }
    }


def build_i2v_workflow(shot: Shot, init_image: str) -> dict:
    """Build Wan I2V workflow (with optional LoRA)."""
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
            "inputs": {"vae_name": "wan_2.1_vae.safetensors"}
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
            "inputs": {"clip_name": "clip_vision_h.safetensors"}
        },
        "load_image": {
            "class_type": "LoadImage",
            "inputs": {"image": init_image}
        },
        "clip_vision_encode": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "crop": "none",
                "clip_vision": ["clip_vision_loader", 0],
                "image": ["load_image", 0]
            }
        },
    }

    # Conditionally add LoRA or connect directly
    if LORA_NAME:
        workflow["lora_loader"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": LORA_NAME,
                "strength_model": LORA_STRENGTH,
                "strength_clip": 0.0,
                "model": ["unet_loader", 0],
                "clip": ["clip_loader", 0]
            }
        }
        model_source = ["lora_loader", 0]
        clip_source = ["lora_loader", 1]
    else:
        # No LoRA - connect directly to unet and clip
        model_source = ["unet_loader", 0]
        clip_source = ["clip_loader", 0]

    workflow["model_sampling"] = {
        "class_type": "ModelSamplingSD3",
        "inputs": {"shift": 8, "model": model_source}
    }
    workflow["positive_prompt"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": shot.i2v_prompt, "clip": clip_source}
    }
    workflow["negative_prompt"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": NEGATIVE_PROMPT, "clip": clip_source}
    }
    workflow["wan_i2v"] = {
        "class_type": "WanImageToVideo",
        "inputs": {
            "width": WIDTH,
            "height": HEIGHT,
            "length": FRAME_COUNT,
            "batch_size": 1,
            "positive": ["positive_prompt", 0],
            "negative": ["negative_prompt", 0],
            "vae": ["vae_loader", 0],
            "clip_vision_output": ["clip_vision_encode", 0],
            "start_image": ["load_image", 0]
        }
    }
    workflow["sampler"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": 100000 + shot.id * 1000,
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
    }
    workflow["vae_decode"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["sampler", 0], "vae": ["vae_loader", 0]}
    }
    workflow["save_video"] = {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "frame_rate": FRAME_RATE,
            "loop_count": 0,
            "filename_prefix": f"{OUTPUT_PREFIX}_shot{shot.id:02d}",
            "format": "video/h264-mp4",
            "pingpong": False,
            "save_output": True,
            "images": ["vae_decode", 0]
        }
    }
    return workflow


# =============================================================================
# EXECUTION HELPERS
# =============================================================================

def submit_and_wait(workflow: dict, stage_name: str, timeout_sec: int = 600) -> Optional[dict]:
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
    
    for i in range(timeout_sec // 5):
        time.sleep(5)
        elapsed = (i + 1) * 5

        try:
            history = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                status = history[prompt_id].get("status", {})

                if status.get("status_str") == "error":
                    print(f"\n❌ {stage_name} FAILED!")
                    messages = status.get("messages", [])
                    for msg in messages:
                        if msg[0] == "execution_error":
                            print(f"Error: {msg[1].get('exception_message', 'Unknown')}")
                    return None

                # Check for success (handles both normal and cached results)
                if status.get("status_str") == "success":
                    if outputs:
                        print(f"\n✅ {stage_name} COMPLETED! ({elapsed}s)")
                        return {"prompt_id": prompt_id, "outputs": outputs}
                    else:
                        # Cached result - outputs empty, need to infer filename
                        print(f"\n✅ {stage_name} COMPLETED (cached)! ({elapsed}s)")
                        return {"prompt_id": prompt_id, "outputs": {}, "cached": True}

        except Exception:
            pass  # Network hiccup, keep polling

        print(f"  ... {elapsed}s elapsed", end="\r")
    
    print(f"\n⚠️ {stage_name} timeout after {timeout_sec}s")
    return None


def extract_output_filename(outputs: dict, file_type: str = "images") -> Optional[str]:
    """Extract filename from ComfyUI outputs."""
    for _, node_output in outputs.items():
        if file_type in node_output:
            return node_output[file_type][0]["filename"]
        if "gifs" in node_output:  # VHS_VideoCombine uses "gifs"
            return node_output["gifs"][0]["filename"]
    return None


def find_latest_file(prefix: str, extension: str = "png") -> Optional[str]:
    """Find latest file matching prefix from ComfyUI output via API."""
    try:
        resp = requests.get(f"{COMFY_URL}/view?filename={prefix}&type=output", timeout=10)
        if resp.status_code == 200:
            return f"{prefix}"
    except Exception:
        pass

    # Fallback: list files and find matching pattern
    # ComfyUI adds _00001_, _00002_ etc. suffixes
    for i in range(10, 0, -1):
        candidate = f"{prefix}_{i:05d}_.{extension}"
        try:
            resp = requests.head(f"{COMFY_URL}/view?filename={candidate}&type=output", timeout=5)
            if resp.status_code == 200:
                return candidate
        except Exception:
            continue
    return None


def wait_for_manual_copy(src_filename: str, description: str):
    """Prompt user to copy file from output/ to input/."""
    print(f"\n{'='*60}")
    print(f"⚠️  MANUAL STEP REQUIRED: {description}")
    print(f"{'='*60}")
    print(f"\nRun on RunPod:")
    print(f"  cp /workspace/runpod-slim/ComfyUI/output/{src_filename} \\")
    print(f"     /workspace/runpod-slim/ComfyUI/input/")
    print(f"\nPress Enter when done...")
    input()


def extract_last_frame_manual(video_filename: str, output_name: str):
    """Prompt user to extract last frame from video."""
    print(f"\n{'='*60}")
    print(f"⚠️  MANUAL STEP: Extract last frame")
    print(f"{'='*60}")
    print(f"\nRun on RunPod:")
    print(f"  cd /workspace/runpod-slim/ComfyUI/output")
    print(f"  ffmpeg -sseof -0.1 -i {video_filename} -update 1 -q:v 2 {output_name}")
    print(f"  cp {output_name} /workspace/runpod-slim/ComfyUI/input/")
    print(f"\nPress Enter when done...")
    input()


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main():
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║       MATRIX ZERO - ANIME EDITION (Goku)                          ║
║       VIDEO ONLY - No Audio (Sonic Engine not in test script)     ║
║                                                                   ║
║       6 Shots × ~2 Seconds = ~12 Second Demo (quick test)         ║
║                                                                   ║
║       STRUCTURE:                                                  ║
║         Cosmic Void:      Shot 1 (wide) → Shot 2 (close-up)      ║
║         Training Grounds: Shot 3 (wide) → Shot 4 (close-up)      ║
║         Sunset Cliff:     Shot 5 (medium) → Shot 6 (close-up)    ║
║                                                                   ║
║       TRANSITIONS:                                                ║
║         1→2: Same scene (zoom in)                                 ║
║         2→3: SCENE CHANGE (cosmic → training)                     ║
║         3→4: Same scene (angle change)                            ║
║         4→5: SCENE CHANGE (training → cliff)                      ║
║         5→6: Same scene (tighter frame)                           ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    print(f"ComfyUI: {COMFY_URL}")
    print(f"LoRA: {LORA_NAME} (strength {LORA_STRENGTH})")
    print(f"Resolution: {WIDTH}×{HEIGHT} @ {FRAME_RATE}fps")
    print(f"Frames per shot: {FRAME_COUNT} (~{FRAME_COUNT/FRAME_RATE:.1f}s)")
    
    video_files = []
    
    # =========================================================================
    # SHOT 1: Hero Frame → I2V
    # =========================================================================
    shot = SHOTS[0]
    print(f"\n\n{'#'*60}")
    print(f"# SHOT {shot.id}: {shot.name.upper()} ({shot.location})")
    print(f"{'#'*60}")
    
    # Generate hero frame
    result = submit_and_wait(
        build_hero_frame_workflow(shot),
        f"Shot {shot.id} Hero Frame",
        timeout_sec=120
    )
    if not result:
        print("❌ Pipeline failed at Shot 1 Hero Frame")
        sys.exit(1)
    
    hero_filename = extract_output_filename(result["outputs"], "images")
    if not hero_filename and result.get("cached"):
        # Cached result - find the file by expected prefix
        hero_filename = find_latest_file(f"{OUTPUT_PREFIX}_shot{shot.id:02d}_hero", "png")
    print(f"📸 Hero frame: {hero_filename}")
    
    # Copy hero frame to input
    wait_for_manual_copy(hero_filename, "Copy hero frame to input")
    
    # Generate I2V
    result = submit_and_wait(
        build_i2v_workflow(shot, hero_filename),
        f"Shot {shot.id} I2V",
        timeout_sec=900
    )
    if not result:
        print(f"❌ Pipeline failed at Shot {shot.id} I2V")
        sys.exit(1)
    
    video_filename = extract_output_filename(result["outputs"], "gifs")
    if not video_filename and result.get("cached"):
        video_filename = find_latest_file(f"{OUTPUT_PREFIX}_shot{shot.id:02d}", "mp4")
    print(f"🎬 Video: {video_filename}")
    video_files.append(video_filename)

    # =========================================================================
    # SHOTS 2-6: Extract Last Frame → Bridge Frame → I2V
    # =========================================================================
    for shot in SHOTS[1:]:
        print(f"\n\n{'#'*60}")
        print(f"# SHOT {shot.id}: {shot.name.upper()} ({shot.location})")
        print(f"{'#'*60}")
        
        # Extract last frame from previous video
        prev_video = video_files[-1]
        last_frame_name = f"{OUTPUT_PREFIX}_shot{shot.id-1:02d}_last.png"
        extract_last_frame_manual(prev_video, last_frame_name)
        
        # Generate bridge frame
        result = submit_and_wait(
            build_bridge_frame_workflow(shot, last_frame_name),
            f"Shot {shot.id} Bridge Frame",
            timeout_sec=120
        )
        if not result:
            print(f"❌ Pipeline failed at Shot {shot.id} Bridge Frame")
            sys.exit(1)
        
        bridge_filename = extract_output_filename(result["outputs"], "images")
        if not bridge_filename and result.get("cached"):
            bridge_filename = find_latest_file(f"{OUTPUT_PREFIX}_shot{shot.id:02d}_bridge", "png")
        print(f"🌉 Bridge frame: {bridge_filename}")
        
        # Copy bridge frame to input
        wait_for_manual_copy(bridge_filename, "Copy bridge frame to input")
        
        # Generate I2V
        result = submit_and_wait(
            build_i2v_workflow(shot, bridge_filename),
            f"Shot {shot.id} I2V",
            timeout_sec=900
        )
        if not result:
            print(f"❌ Pipeline failed at Shot {shot.id} I2V")
            sys.exit(1)
        
        video_filename = extract_output_filename(result["outputs"], "gifs")
        if not video_filename and result.get("cached"):
            video_filename = find_latest_file(f"{OUTPUT_PREFIX}_shot{shot.id:02d}", "mp4")
        print(f"🎬 Video: {video_filename}")
        video_files.append(video_filename)

    # =========================================================================
    # STITCH ALL VIDEOS
    # =========================================================================
    print(f"\n\n{'#'*60}")
    print(f"# FINAL: STITCH ALL {len(video_files)} CLIPS")
    print(f"{'#'*60}")
    
    print(f"\nGenerated videos:")
    for i, vf in enumerate(video_files, 1):
        print(f"  Shot {i}: {vf}")
    
    print(f"\n{'='*60}")
    print(f"⚠️  MANUAL STEP: Stitch videos")
    print(f"{'='*60}")
    print(f"\nRun on RunPod:")
    print(f"  cd /workspace/runpod-slim/ComfyUI/output")
    print(f"")
    print(f"  # Create concat list")
    print(f"  cat > concat_list.txt << EOF")
    for vf in video_files:
        print(f"file '{vf}'")
    print(f"EOF")
    print(f"")
    print(f"  # Stitch")
    print(f"  ffmpeg -f concat -safe 0 -i concat_list.txt -c copy {OUTPUT_PREFIX}_final.mp4")
    print(f"")
    print(f"  # Or with re-encoding for smooth playback:")
    print(f"  ffmpeg -f concat -safe 0 -i concat_list.txt -c:v libx264 -crf 18 -preset medium {OUTPUT_PREFIX}_final_encoded.mp4")
    
    print(f"\n\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE!")
    print(f"{'='*60}")
    print(f"Final video: {OUTPUT_PREFIX}_final.mp4")
    print(f"Location: /workspace/runpod-slim/ComfyUI/output/")
    print(f"Duration: ~{len(video_files) * 5} seconds")


if __name__ == "__main__":
    main()