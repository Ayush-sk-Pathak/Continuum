# RunPod Operations Guide

> **READ THIS FIRST** every session before connecting to RunPod.
> 
> **Last Updated:** 2025-12-22

---

## 🚨 COMMON MISTAKES (Check These First)

| Mistake | Example | Fix |
|---------|---------|-----|
| **Typo in Pod ID** | `1yh...` vs `lyh...` (one vs lowercase L) | Copy-paste from browser URL, don't type manually |
| **ComfyUI not restarted** | Nodes show "NOT FOUND" | Run restart commands after fresh pod start |
| **Wrong path** | `/workspace/ComfyUI/` | Correct: `/workspace/runpod-slim/ComfyUI/` |
| **Wrong env var format** | `COMFYUI_HOST=...` | Correct: `CONTINUUM_COMFYUI__HOST=...` |
| **Missing dependencies** | `No module named 'skimage'` | Run `pip3 install scikit-image` |

---

## 1. Connection Setup (From Mac)

### Step 1: Get Pod ID from Browser

1. Open RunPod dashboard
2. Click **"ComfyUI"** link (Port 8188)
3. **Copy the URL from browser address bar** — don't type it manually

Example URL: `lyhiozmwkjopf7-8188.proxy.runpod.net`

Pod ID is: `lyhiozmwkjopf7`

### Step 2: Set Environment Variable

```bash
# Format: wss://<POD_ID>-8188.proxy.runpod.net
export CONTINUUM_COMFYUI__HOST="wss://lyhiozmwkjopf7-8188.proxy.runpod.net"
```

⚠️ **Critical:** 
- Double underscore `__` between COMFYUI and HOST
- Prefix is `CONTINUUM_` not `COMFYUI_`
- Use `wss://` not `ws://` or `https://`

### Step 3: Verify Before Running

```bash
# Quick test that URL is reachable
curl -s "https://lyhiozmwkjopf7-8188.proxy.runpod.net/system_stats" | head -c 100
```

Should return JSON. If not, check pod is running and Pod ID is correct.

### Step 4: Run Pipeline

```bash
# Without audit (faster)
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --no-audit

# With audit
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json
```

---

## 2. After Fresh Pod Start (ALWAYS DO THIS)

Custom nodes don't auto-load. **Every time** you start or restart a pod:

```bash
# In RunPod Web Terminal:

# 1. Kill any existing ComfyUI
pkill -f "python.*main.py.*8188"

# 2. Start ComfyUI
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &

# 3. Wait for startup
sleep 15

# 4. Verify running
curl -s http://localhost:8188/system_stats | head -5
```

---

## 3. Required Dependencies (Install After Fresh Pod)

Some Python packages are needed but not pre-installed:

```bash
# For pose extraction (OpenPose) - REQUIRED
pip3 install scikit-image

# For DWPose (currently broken, use OpenPose instead)
pip3 install onnxruntime-gpu

# Then restart ComfyUI
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &
```

---

## 4. Directory Paths

| Path | Purpose |
|------|---------|
| `/workspace/` | Persistent storage (survives restarts) |
| `/workspace/runpod-slim/ComfyUI/` | **ComfyUI installation** |
| `/workspace/runpod-slim/ComfyUI/custom_nodes/` | Custom node packages |
| `/workspace/runpod-slim/ComfyUI/models/` | Model files |
| `/workspace/runpod-slim/comfyui.log` | ComfyUI log file |

⚠️ **NOT** `/workspace/ComfyUI/` — that path doesn't exist!

---

## 5. Check Node Availability

```bash
# Check specific node
curl -s http://localhost:8188/object_info | python3 -c "
import sys,json
d=json.load(sys.stdin)
node='OpenposePreprocessor'  # Change this
print(f'{node}: FOUND' if node in d else f'{node}: NOT FOUND')
"

# List all pose nodes
curl -s http://localhost:8188/object_info | python3 -c "
import sys,json
d=json.load(sys.stdin)
nodes=[k for k in d.keys() if 'pose' in k.lower()]
print('\n'.join(nodes) if nodes else 'None found')
"

# List all preprocessors
curl -s http://localhost:8188/object_info | python3 -c "
import sys,json
d=json.load(sys.stdin)
nodes=[k for k in d.keys() if 'preprocessor' in k.lower()]
print('\n'.join(sorted(nodes)))
"
```

---

## 6. Node Status (As of 2025-12-22)

| Node | Status | Notes |
|------|--------|-------|
| `OpenposePreprocessor` | ✅ Works | **Use this** for pose extraction (needs scikit-image) |
| `DWPreprocessor` | ❌ Broken | Models won't download, use OpenPose |
| `KSamplerBatch` | ❌ Broken | KJNodes installed but won't load |
| `RIFE VFI` | ✅ Works | Frame interpolation |
| `IPAdapterAdvanced` | ✅ Works | Identity conditioning |
| `DepthAnythingV2Preprocessor` | ✅ Works | Depth extraction |

---

## 7. Installed Custom Nodes

```
/workspace/runpod-slim/ComfyUI/custom_nodes/
├── Civicomfy
├── ComfyUI-Frame-Interpolation    # RIFE VFI ✅
├── ComfyUI-KJNodes                # KSamplerBatch ❌
├── ComfyUI-Manager
├── ComfyUI-RunpodDirect
├── ComfyUI-VideoHelperSuite
├── ComfyUI_IPAdapter_plus         # IP-Adapter ✅
└── comfyui_controlnet_aux         # OpenPose ✅, DWPose ❌
```

---

## 8. Troubleshooting

### "404 Invalid response status" from Mac

1. **Check Pod ID** — Copy from browser, don't type (watch for `1` vs `l`)
2. **Check pod is running** — Green status in RunPod dashboard
3. **Check ComfyUI is running** — `curl localhost:8188/system_stats` in Web Terminal
4. **Restart ComfyUI** — See Section 2

### "Node does not exist"

1. **Restart ComfyUI** — Nodes only load on startup
2. **Check logs** — `tail -100 /workspace/runpod-slim/comfyui.log | grep -i error`
3. **Check dependencies** — See Section 3
4. **Use alternative** — DWPreprocessor → OpenposePreprocessor

### "No module named 'skimage'"

```bash
pip3 install scikit-image
# Then restart ComfyUI (Section 2)
```

### Connection works but job fails

1. **Check models exist** — Workflow may reference missing model files
2. **Check logs** — `tail -f /workspace/runpod-slim/comfyui.log`
3. **Test in UI** — Load workflow in ComfyUI browser interface first

### Files not found by workflow

Local paths don't exist on RunPod. Files must be uploaded via `client.upload_file()` before referencing in workflows.

---

## 9. GPU Specs (Typical Pod)

| Spec | Value |
|------|-------|
| GPU | RTX 4090 |
| VRAM | 24GB |
| ComfyUI | 0.4.0 |
| PyTorch | 2.6.0+cu124 |
| Python | 3.12 |

---

## 10. Quick Reference Commands

```bash
# === ON RUNPOD ===

# Check if ComfyUI running
ps aux | grep main.py

# View logs
tail -100 /workspace/runpod-slim/comfyui.log

# Full restart
pkill -f "python.*main.py.*8188"
cd /workspace/runpod-slim/ComfyUI
nohup python3 main.py --listen 0.0.0.0 --port 8188 > /workspace/runpod-slim/comfyui.log 2>&1 &

# Check node exists
curl -s http://localhost:8188/object_info | python3 -c "import sys,json; d=json.load(sys.stdin); print('FOUND' if 'NodeName' in d else 'NOT FOUND')"

# Install missing dependencies
pip3 install scikit-image


# === ON MAC ===

# Set connection (COPY POD ID FROM BROWSER)
export CONTINUUM_COMFYUI__HOST="wss://<POD_ID>-8188.proxy.runpod.net"

# Test connection
curl -s "https://<POD_ID>-8188.proxy.runpod.net/system_stats" | head -c 100

# Run pipeline
python main.py --project tests/bridge_quick_test.json --consistency tests/bible.json --no-audit
```

---

## 11. Session Checklist

Before every session:

- [ ] Pod is running (green status)
- [ ] ComfyUI restarted after pod start
- [ ] Dependencies installed (`pip3 install scikit-image`)
- [ ] Pod ID copied from browser (not typed)
- [ ] `CONTINUUM_COMFYUI__HOST` set correctly
- [ ] Quick curl test returns JSON

---

*Keep this file updated as we discover more gotchas.*