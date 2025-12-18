import requests
import json

COMFY_URL = "https://ej1785v8efhkd4-8188.proxy.runpod.net"

with open("workflows/pass1_img2vid.json", "r") as f:
    workflow_str = f.read()

params = {
    "CLIP_MODEL": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "CLIP_VISION_MODEL": "clip_vision_h.safetensors",
    "UNET_MODEL": "wan2.1_i2v_480p_14B_fp16.safetensors",
    "VAE_MODEL": "wan_2.1_vae.safetensors",
    "INIT_IMAGE": "WhatsApp Image 2025-12-15 at 2.17.36 AM.jpeg",
    "POSITIVE_PROMPT": "A woman laughs happily and turns her head to the right",
    "NEGATIVE_PROMPT": "blurry, distorted, ugly, watermark, deformed",
    "FRAMES": "49",
    "WIDTH": "848",
    "HEIGHT": "480",
    "STEPS": "20",
    "CFG_SCALE": "7.0",
    "SEED": "99999",
    "FPS": "12.0"
}

for key, value in params.items():
    workflow_str = workflow_str.replace(f"{{{{{key}}}}}", value)

workflow = json.loads(workflow_str)

response = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow})

print(f"Status: {response.status_code}")
print(json.dumps(response.json(), indent=2))
