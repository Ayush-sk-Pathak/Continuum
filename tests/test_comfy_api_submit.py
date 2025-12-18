import requests
import json

COMFY_URL = "https://ej1785v8efhkd4-8188.proxy.runpod.net"

# Load local T2V workflow
with open("workflows/pass1_structural.json", "r") as f:
    workflow = json.load(f)

# Submit to ComfyUI
response = requests.post(
    f"{COMFY_URL}/prompt",
    json={"prompt": workflow}
)

print(f"Status: {response.status_code}")
print(json.dumps(response.json(), indent=2))
