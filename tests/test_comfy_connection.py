# test_comfy_connection.py
import requests

COMFY_URL = "https://ej1785v8efhkd4-8188.proxy.runpod.net"

# Test basic connectivity
response = requests.get(f"{COMFY_URL}/system_stats")
print(response.status_code)
print(response.json())