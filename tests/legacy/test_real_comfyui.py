#!/usr/bin/env python3
"""
Real ComfyUI Integration Test

Tests our actual code against a live ComfyUI instance.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.comfy_client.client import ComfyClient
from src.comfy_client.workflow_loader import WorkflowLoader

# Configuration
COMFYUI_HOST = "wss://9a1e00x6nvbwaf-8188.proxy.runpod.net"
WORKFLOW_PATH = Path("workflows/t2v_wan21_api.json")


async def test_workflow_loader():
    """Test that we can load and parse the workflow."""
    print("\n" + "="*60)
    print("TEST 1: Workflow Loader")
    print("="*60)
    
    try:
        loader = WorkflowLoader(workflows_dir=Path("workflows"))
        template = loader.load("t2v_wan21_api.json")
        workflow = template.workflow  # Get the actual workflow dict
        
        print(f"✅ Loaded workflow: {WORKFLOW_PATH}")
        print(f"   Nodes: {len(workflow)}")
        
        # Show some node types
        node_types = set()
        for node_id, node in workflow.items():
            if isinstance(node, dict) and 'class_type' in node:
                node_types.add(node['class_type'])
        
        print(f"   Node types: {', '.join(list(node_types)[:5])}...")
        return True
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


async def test_client_connection():
    """Test that our client can connect to ComfyUI."""
    print("\n" + "="*60)
    print("TEST 2: Client Connection")
    print("="*60)
    
    try:
        # Convert wss:// to https:// for REST calls
        http_host = COMFYUI_HOST.replace("wss://", "https://").replace("ws://", "http://")
        
        client = ComfyClient(host=http_host)
        # await client.connect()
        
        # Test connection
        is_connected = await client.health_check()
        
        if is_connected:
            print(f"✅ Connected to ComfyUI")
            print(f"   Host: {http_host}")
            return True
        else:
            print(f"❌ Connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_submit_workflow():
    """Test submitting an actual workflow."""
    print("\n" + "="*60)
    print("TEST 3: Submit Workflow")
    print("="*60)
    
    try:
        http_host = COMFYUI_HOST.replace("wss://", "https://").replace("ws://", "http://")
        
        # Load workflow
        loader = WorkflowLoader(workflows_dir=Path("workflows"))
        template = loader.load("t2v_wan21_api.json")
        workflow = template.workflow

        
        # Create client
        client = ComfyClient(host=http_host)
        await client.connect()
        
        # Submit job
        print("   Submitting workflow...")
        prompt_id = await client.submit_workflow(workflow)
        
        print(f"✅ Job submitted!")
        print(f"   Prompt ID: {prompt_id}")
        
        # Poll for completion (with timeout)
        print("   Waiting for completion (this may take 2-5 min)...")
        
        for i in range(150):  # 5 min timeout
            await asyncio.sleep(2)
            
            status = await client.get_history(prompt_id)
            
            if status.get('completed'):
                print(f"✅ Generation complete!")
                outputs = status.get('outputs', {})
                print(f"   Outputs: {outputs}")
                return True
            
            if status.get('error'):
                print(f"❌ Error: {status.get('error')}")
                return False
            
            if i % 15 == 0:
                print(f"   Still processing... ({i*2}s)")
        
        print("⏳ Timeout - check ComfyUI UI")
        return False
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n" + "="*60)
    print("  REAL COMFYUI INTEGRATION TEST")
    print("="*60)
    print(f"\nHost: {COMFYUI_HOST}")
    print(f"Workflow: {WORKFLOW_PATH}")
    
    results = []
    
    # Test 1: Workflow loader
    results.append(await test_workflow_loader())
    
    # Test 2: Client connection
    results.append(await test_client_connection())
    
    # Test 3: Submit workflow (only if previous tests passed)
    if all(results):
        print("\n⚠️  Test 3 will generate a video (~2-5 min)")
        response = input("   Run generation test? (y/n): ")
        if response.lower() == 'y':
            results.append(await test_submit_workflow())
        else:
            print("   Skipped generation test")
    
    # Summary
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"  Tests passed: {passed}/{total}")
    
    if passed == total:
        print("  🎉 All tests passed!")
    else:
        print("  ⚠️  Some tests failed")


if __name__ == "__main__":
    asyncio.run(main())
