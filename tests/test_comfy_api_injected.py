import requests
import json
import re

COMFY_URL = "https://ej1785v8efhkd4-8188.proxy.runpod.net"

# Load workflow template
with open("workflows/pass1_structural.json", "r") as f:
    workflow_str = f.read()

# Inject actual values (this is what workflow_loader.py does)
params = {
    "CLIP_MODEL": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "UNET_MODEL": "wan2.1_t2v_1.3B_fp16.safetensors",
    "VAE_MODEL": "wan_2.1_vae.safetensors",
    "PROMPT": "A woman walks through a sunlit garden, cinematic lighting",
    "NEGATIVE_PROMPT": "blurry, distorted, ugly, watermark",
    "FRAMES": "49",
    "WIDTH": "848",
    "HEIGHT": "480",
    "STEPS": "20",
    "CFG_SCALE": "7.0",
    "SEED": "42",
    "FPS": "12.0"
}

for key, value in params.items():
    workflow_str = workflow_str.replace(f"{{{{{key}}}}}", value)

workflow = json.loads(workflow_str)

# Submit to ComfyUI
response = requests.post(
    f"{COMFY_URL}/prompt",
    json={"prompt": workflow}
)

print(f"Status: {response.status_code}")
print(json.dumps(response.json(), indent=2))
