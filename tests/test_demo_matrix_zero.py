#!/usr/bin/env python3
"""
===============================================================================
TEST DEMO: MATRIX ZERO - "Welcome to Continuum"
===============================================================================

6-shot, 30-second demo showcasing identity preservation across shots.
Each shot: 5 seconds (81 frames @ 16fps)

STRUCTURE: 3 Locations, 5 Transitions
    
    OFFICE (Shots 1-2):
        Shot 1: Wide - Standing, begins raising hand
        Shot 2: Close-up - Hand rises toward camera
        [Transition: SAME SCENE - wide to close-up]
    
    DESERT (Shots 3-4):
        Shot 3: Wide - Standing in desert, walks forward
        Shot 4: Close-up - Reaches toward camera
        [Transition 2→3: SCENE CHANGE - hand rises → desert]
        [Transition 3→4: SAME SCENE - wide to close-up]
    
    BEACH (Shots 5-6):
        Shot 5: Medium - Sitting, sips cocktail
        Shot 6: Close-up - Lowers drink, knowing nod
        [Transition 4→5: SCENE CHANGE - hand grabs → beach]
        [Transition 5→6: SAME SCENE - medium to close-up]

FILM CUTS FRAMEWORK:
    - Same-scene cuts use framing changes (wide/medium/close-up)
    - Scene changes use action continuity (hand motion → new world)
    - Tests identity preservation HARD (same background exposes drift)

Pipeline:
    Shot 1: Hero Frame → I2V
    Shots 2-6: Extract last frame → Bridge Frame → I2V
    Final: FFmpeg stitch all 6 clips

Usage:
    export CONTINUUM_COMFYUI__HOST="wss://xxx-8188.proxy.runpod.net"
    python tests/test_demo_matrix_zero.py

Author: Continuum Studios
Date: 2026-01-03
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
FRAME_COUNT = 81        # ~5 seconds at 16fps
FRAME_RATE = 16         # Standard for Wan 2.1
WIDTH = 832
HEIGHT = 480

# Identity settings
LORA_NAME = "ayush_wan21_i2v_v1.safetensors"
LORA_STRENGTH = 0.85
FACE_REF = "ayush_ref.png"
TRIGGER = "ayush, a man with black hair and beard"

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
    # LOCATION 1: OFFICE (Shots 1-2) - Establish mystery, zoom in on invitation
    # Transition 1→2: SAME SCENE - Wide to Close-up
    # =========================================================================
    Shot(
        id=1,
        name="office_wide",
        location="office",
        hero_prompt=(
            "a man with black hair and beard, standing in modern minimalist office, "
            "full body wide shot, centered in frame, soft window lighting, "
            "hands at sides, looking at camera with mysterious expression, "
            "cinematic wide angle, 4k, clean background"
        ),
        i2v_prompt=(
            f"{TRIGGER}, standing in modern minimalist office, full body wide shot, "
            "soft window lighting, looks directly at camera with mysterious expression, "
            "slowly begins raising right hand toward camera, weight shifts forward, "
            "cinematic wide angle, 4k, smooth motion"
        ),
    ),
    Shot(
        id=2,
        name="office_closeup",
        location="office",
        hero_prompt=(
            "a man with black hair and beard, close-up portrait in modern office, "
            "face and raised hand visible in frame, soft window lighting from side, "
            "mysterious intense expression, shallow depth of field, "
            "cinematic close-up, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, close-up portrait in modern office, face and hand in frame, "
            "soft window lighting, intense mysterious gaze at camera, "
            "hand rises up toward camera lens, fingers spread open, offering gesture, "
            "shallow depth of field, cinematic close-up, 4k, smooth motion"
        ),
    ),
    # =========================================================================
    # LOCATION 2: DESERT (Shots 3-4) - New reality revealed
    # Transition 2→3: SCENE CHANGE - Hand rises → Cut to desert wide
    # Transition 3→4: SAME SCENE - Wide to Close-up
    # =========================================================================
    Shot(
        id=3,
        name="desert_wide",
        location="matrix_desert",
        hero_prompt=(
            "a man with black hair and beard, standing in vast orange desert, "
            "full body wide shot, geometric grid pattern on horizon, "
            "confident stance, golden hour lighting, "
            "epic cinematic wide shot, matrix aesthetic, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, standing in vast orange desert, full body wide shot, "
            "geometric grid on horizon, confident powerful stance, "
            "walks forward toward camera, extends arm in beckoning follow-me gesture, "
            "golden hour lighting, matrix aesthetic, epic cinematic wide, 4k, smooth motion"
        ),
    ),
    Shot(
        id=4,
        name="desert_closeup",
        location="matrix_desert",
        hero_prompt=(
            "a man with black hair and beard, dramatic close-up in desert, "
            "face and extended arm filling frame, orange desert background blurred, "
            "intense focused expression, golden rim lighting, "
            "cinematic close-up, matrix style, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, dramatic close-up in orange desert, face and arm in frame, "
            "blurred desert background, reaches hand dramatically toward camera lens, "
            "fingers spread wide grabbing at reality, intense focused expression, "
            "golden rim lighting, cinematic close-up, matrix style, 4k, smooth motion"
        ),
    ),
    # =========================================================================
    # LOCATION 3: BEACH (Shots 5-6) - Paradise payoff
    # Transition 4→5: SCENE CHANGE - Hand grabs camera → Cut to beach medium
    # Transition 5→6: SAME SCENE - Medium to Close-up
    # =========================================================================
    Shot(
        id=5,
        name="beach_medium",
        location="tropical_beach",
        hero_prompt=(
            "a man with black hair and beard, medium shot sitting in beach lounge chair, "
            "upper body and chair visible, tropical paradise background, "
            "crystal blue water, colorful cocktail on side table, "
            "relaxed confident posture, golden sunset lighting, cinematic, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, medium shot in beach lounge chair, upper body visible, "
            "tropical paradise background, crystal blue water, "
            "reaches for colorful cocktail drink, picks it up, brings to lips, takes sip, "
            "relaxed satisfied expression, golden sunset lighting, cinematic, 4k, smooth motion"
        ),
    ),
    Shot(
        id=6,
        name="beach_closeup",
        location="tropical_beach",
        hero_prompt=(
            "a man with black hair and beard, close-up portrait on tropical beach, "
            "face filling frame, holding cocktail glass near chin, "
            "knowing confident smile, warm golden sunset lighting on face, "
            "blurred ocean background, shallow depth of field, cinematic, 4k"
        ),
        i2v_prompt=(
            f"{TRIGGER}, close-up portrait on tropical beach, face filling frame, "
            "warm sunset lighting, lowers cocktail glass from lips, "
            "looks directly at camera with knowing confident expression, "
            "slight approving nod, the look says welcome to my world, "
            "shallow depth of field, cinematic, 4k, smooth motion"
        ),
    ),
]

NEGATIVE_PROMPT = (
    "blurry, distorted, ugly, watermark, deformed face, bad anatomy, extra limbs, "
    "low quality, amateur, shaky camera, text, subtitles"
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
    """Build Wan I2V + LoRA workflow."""
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
        "lora_loader": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": LORA_NAME,
                "strength_model": LORA_STRENGTH,
                "strength_clip": 0.0,
                "model": ["unet_loader", 0],
                "clip": ["clip_loader", 0]
            }
        },
        "model_sampling": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"shift": 8, "model": ["lora_loader", 0]}
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
        "positive_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": shot.i2v_prompt, "clip": ["lora_loader", 1]}
        },
        "negative_prompt": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE_PROMPT, "clip": ["lora_loader", 1]}
        },
        "wan_i2v": {
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
        },
        "sampler": {
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
        },
        "vae_decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["vae_loader", 0]}
        },
        "save_video": {
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
    }


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
                if outputs:
                    print(f"\n✅ {stage_name} COMPLETED! ({elapsed}s)")
                    return {"prompt_id": prompt_id, "outputs": outputs}
                    
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    print(f"\n❌ {stage_name} FAILED!")
                    messages = status.get("messages", [])
                    for msg in messages:
                        if msg[0] == "execution_error":
                            print(f"Error: {msg[1].get('exception_message', 'Unknown')}")
                    return None
                    
        except Exception:
            pass  # Network hiccup, keep polling
            
        print(f"  ... {elapsed}s elapsed", end="\r")
    
    print(f"\n⚠️ {stage_name} timeout after {timeout_sec}s")
    return None


def extract_output_filename(outputs: dict, file_type: str = "images") -> Optional[str]:
    """Extract filename from ComfyUI outputs."""
    for node_id, node_output in outputs.items():
        if file_type in node_output:
            return node_output[file_type][0]["filename"]
        if "gifs" in node_output:  # VHS_VideoCombine uses "gifs"
            return node_output["gifs"][0]["filename"]
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
║       MATRIX ZERO - "Welcome to Continuum" Demo                   ║
║                                                                   ║
║       6 Shots × 5 Seconds = 30 Second Demo                        ║
║                                                                   ║
║       STRUCTURE:                                                  ║
║         Office:  Shot 1 (wide) → Shot 2 (close-up)               ║
║         Desert:  Shot 3 (wide) → Shot 4 (close-up)               ║
║         Beach:   Shot 5 (medium) → Shot 6 (close-up)             ║
║                                                                   ║
║       TRANSITIONS:                                                ║
║         1→2: Same scene (zoom in)                                 ║
║         2→3: SCENE CHANGE (office → desert)                       ║
║         3→4: Same scene (angle change)                            ║
║         4→5: SCENE CHANGE (desert → beach)                        ║
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