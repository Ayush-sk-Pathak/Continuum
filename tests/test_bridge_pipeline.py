"""
Continuum Engine - Bridge Frame Pipeline Test

This script demonstrates the full pipeline:
1. Generate Shot 1 (T2V) → "Woman enters coffee shop"
2. Extract last frame
3. Generate Bridge Frame (I2V) → Subtle motion continuation
4. Generate Shot 2 (I2V) → "Woman orders coffee"
5. Identity Check (ArcFace)
6. Assemble clips

Usage:
    # First, start your RunPod pod and get the ComfyUI URL
    # Then run:
    python test_pipeline.py --comfy-url "http://YOUR_POD_IP:8188"

Prerequisites:
    - RunPod pod running with ComfyUI
    - Models downloaded (wan2.1_t2v, wan2.1_i2v, etc.)
    - Workflow JSONs in ./workflows/ directory
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pipeline_test")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class PipelineConfig:
    """Pipeline configuration"""
    comfy_url: str
    workflows_dir: Path
    output_dir: Path
    
    # Generation settings
    width: int = 512  # Start small for testing
    height: int = 512
    frames: int = 33  # ~2 seconds at 16fps
    fps: int = 16
    
    # Quality settings
    t2v_steps: int = 30
    i2v_steps: int = 20
    cfg: float = 6.0
    
    # Identity threshold
    identity_threshold: float = 0.70


# =============================================================================
# SHOT DEFINITIONS
# =============================================================================

@dataclass  
class ShotSpec:
    """Specification for a single shot"""
    shot_id: str
    prompt: str
    duration_frames: int = 33
    is_first_shot: bool = False
    continue_from_image: Optional[str] = None


# Example scene for testing
TEST_SCENE = [
    ShotSpec(
        shot_id="shot_001",
        prompt="A young woman with brown hair entering a cozy coffee shop, warm lighting, cinematic, medium shot",
        is_first_shot=True,
    ),
    ShotSpec(
        shot_id="shot_002", 
        prompt="The woman walking towards the counter, warm lighting, coffee shop interior, medium shot",
    ),
    ShotSpec(
        shot_id="shot_003",
        prompt="The woman at the counter, smiling, ordering coffee, warm lighting, medium close-up",
    ),
]


# =============================================================================
# MOCK COMFY CLIENT (for testing without GPU)
# =============================================================================

class MockComfyClient:
    """
    Mock ComfyUI client for testing pipeline logic without GPU.
    
    In real usage, this would be replaced with actual HTTP calls
    to the ComfyUI API.
    """
    
    def __init__(self, base_url: str, output_dir: Path):
        self.base_url = base_url
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"MockComfyClient initialized (url={base_url})")
    
    async def upload_image(self, image_path: Path) -> str:
        """
        Upload an image to ComfyUI.
        
        Returns the filename as stored in ComfyUI.
        """
        logger.info(f"[MOCK] Uploading image: {image_path}")
        # In real implementation:
        # POST to {base_url}/upload/image
        return image_path.name
    
    async def submit_workflow(self, workflow: dict) -> str:
        """
        Submit a workflow to ComfyUI.
        
        Returns a prompt_id for tracking.
        """
        # Extract some info for logging
        nodes = workflow.get("nodes", [])
        logger.info(f"[MOCK] Submitting workflow with {len(nodes)} nodes")
        
        # In real implementation:
        # POST to {base_url}/prompt with {"prompt": api_format_workflow}
        
        import uuid
        prompt_id = str(uuid.uuid4())
        logger.info(f"[MOCK] Got prompt_id: {prompt_id}")
        return prompt_id
    
    async def wait_for_completion(
        self, 
        prompt_id: str, 
        timeout_sec: int = 600
    ) -> dict:
        """
        Wait for a job to complete.
        
        Returns the output info.
        """
        logger.info(f"[MOCK] Waiting for job {prompt_id}...")
        
        # Simulate processing time
        await asyncio.sleep(1.0)
        
        # In real implementation:
        # WebSocket connection to {base_url}/ws for progress updates
        # Then GET {base_url}/history/{prompt_id} for results
        
        # Return mock output
        return {
            "outputs": {
                "50": {  # SaveVideo node
                    "videos": [{"filename": f"mock_output_{prompt_id[:8]}.mp4"}]
                }
            }
        }
    
    async def download_output(
        self, 
        filename: str, 
        save_path: Path
    ) -> Path:
        """
        Download an output file from ComfyUI.
        """
        logger.info(f"[MOCK] Downloading {filename} to {save_path}")
        
        # In real implementation:
        # GET {base_url}/view?filename={filename}&type=output
        
        # Create mock file
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(f"MOCK VIDEO: {filename}")
        
        return save_path
    
    async def get_last_frame(self, video_path: Path) -> Path:
        """
        Extract the last frame from a video.
        
        Returns path to the extracted frame.
        """
        logger.info(f"[MOCK] Extracting last frame from {video_path}")
        
        # In real implementation:
        # Use ffmpeg: ffmpeg -sseof -1 -i video.mp4 -frames:v 1 last_frame.png
        
        frame_path = video_path.parent / f"{video_path.stem}_last_frame.png"
        frame_path.write_text("MOCK FRAME")
        
        return frame_path


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class BridgeFramePipeline:
    """
    Orchestrates the bridge frame pipeline.
    
    Flow:
    1. Generate first shot with T2V
    2. For each subsequent shot:
       a. Extract last frame of previous shot
       b. Generate bridge frame with I2V (subtle motion)
       c. Generate new shot with I2V (continues from bridge)
    3. Run identity checks
    4. Concatenate all clips
    """
    
    def __init__(
        self, 
        config: PipelineConfig,
        client: MockComfyClient,
    ):
        self.config = config
        self.client = client
        
        # Import workflow utilities
        # When running from project root: python -m tests.test_bridge_pipeline
        sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "studio"))
        from workflow_utils import WanWorkflowLoader, T2VParams, I2VParams
        
        self.workflow_loader = WanWorkflowLoader(config.workflows_dir)
        self.T2VParams = T2VParams
        self.I2VParams = I2VParams
        
        # Track generated clips
        self.clips: List[Path] = []
        self.frames: List[Path] = []
    
    async def generate_shot_t2v(self, shot: ShotSpec) -> Path:
        """Generate a shot using Text-to-Video"""
        logger.info(f"=== Generating {shot.shot_id} (T2V) ===")
        logger.info(f"Prompt: {shot.prompt}")
        
        # Build workflow
        params = self.T2VParams(
            positive_prompt=shot.prompt,
            width=self.config.width,
            height=self.config.height,
            frames=shot.duration_frames,
            steps=self.config.t2v_steps,
            cfg=self.config.cfg,
        )
        workflow = self.workflow_loader.build_t2v_workflow(params)
        
        # Submit and wait
        prompt_id = await self.client.submit_workflow(workflow)
        result = await self.client.wait_for_completion(prompt_id)
        
        # Download output
        output_filename = result["outputs"]["50"]["videos"][0]["filename"]
        output_path = self.config.output_dir / f"{shot.shot_id}.mp4"
        await self.client.download_output(output_filename, output_path)
        
        logger.info(f"✓ Generated: {output_path}")
        return output_path
    
    async def generate_shot_i2v(
        self, 
        shot: ShotSpec, 
        input_image: Path
    ) -> Path:
        """Generate a shot using Image-to-Video"""
        logger.info(f"=== Generating {shot.shot_id} (I2V) ===")
        logger.info(f"Input image: {input_image}")
        logger.info(f"Prompt: {shot.prompt}")
        
        # Upload input image
        uploaded_name = await self.client.upload_image(input_image)
        
        # Build workflow
        params = self.I2VParams(
            positive_prompt=shot.prompt,
            input_image=uploaded_name,
            width=self.config.width,
            height=self.config.height,
            frames=shot.duration_frames,
            steps=self.config.i2v_steps,
            cfg=self.config.cfg,
        )
        workflow = self.workflow_loader.build_i2v_workflow(params)
        
        # Submit and wait
        prompt_id = await self.client.submit_workflow(workflow)
        result = await self.client.wait_for_completion(prompt_id)
        
        # Download output
        output_filename = result["outputs"]["50"]["videos"][0]["filename"]
        output_path = self.config.output_dir / f"{shot.shot_id}.mp4"
        await self.client.download_output(output_filename, output_path)
        
        logger.info(f"✓ Generated: {output_path}")
        return output_path
    
    async def generate_bridge_frame(
        self, 
        from_shot_id: str,
        last_frame: Path
    ) -> Path:
        """
        Generate a bridge frame for smooth transition.
        
        This uses I2V with minimal motion to create a 
        transitional frame that helps blend shots.
        """
        logger.info(f"=== Generating bridge frame from {from_shot_id} ===")
        
        # Upload frame
        uploaded_name = await self.client.upload_image(last_frame)
        
        # Build workflow with subtle motion prompt
        params = self.I2VParams(
            positive_prompt="subtle movement, slight motion, same scene continuing",
            input_image=uploaded_name,
            width=self.config.width,
            height=self.config.height,
            frames=9,  # Short bridge, ~0.5 seconds
            steps=self.config.i2v_steps,
            cfg=self.config.cfg,
        )
        workflow = self.workflow_loader.build_i2v_workflow(params)
        
        # Submit and wait
        prompt_id = await self.client.submit_workflow(workflow)
        result = await self.client.wait_for_completion(prompt_id)
        
        # Download and extract last frame as bridge
        output_filename = result["outputs"]["50"]["videos"][0]["filename"]
        bridge_video = self.config.output_dir / f"bridge_{from_shot_id}.mp4"
        await self.client.download_output(output_filename, bridge_video)
        
        # Get the last frame of the bridge video
        bridge_frame = await self.client.get_last_frame(bridge_video)
        
        logger.info(f"✓ Bridge frame: {bridge_frame}")
        return bridge_frame
    
    async def check_identity(
        self, 
        frame1: Path, 
        frame2: Path
    ) -> tuple[bool, float]:
        """
        Check if identity is preserved between frames.
        
        Returns (passed, similarity_score)
        """
        logger.info(f"Checking identity: {frame1.name} vs {frame2.name}")
        
        # In real implementation:
        # Use ArcFace or similar to compare faces
        # from ..memory.identity_checker import IdentityChecker
        # checker = IdentityChecker()
        # similarity = checker.compare(frame1, frame2)
        
        # Mock: always pass with high similarity
        similarity = 0.85
        passed = similarity >= self.config.identity_threshold
        
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"Identity check: {status} (similarity={similarity:.2f})")
        
        return passed, similarity
    
    async def run(self, shots: List[ShotSpec]) -> dict:
        """
        Run the full pipeline for a list of shots.
        
        Returns a summary of the generation.
        """
        logger.info(f"\n{'='*60}")
        logger.info("STARTING BRIDGE FRAME PIPELINE")
        logger.info(f"{'='*60}\n")
        logger.info(f"Shots to generate: {len(shots)}")
        
        results = {
            "shots": [],
            "identity_checks": [],
            "success": True,
        }
        
        previous_frame: Optional[Path] = None
        
        for i, shot in enumerate(shots):
            shot_result = {"shot_id": shot.shot_id, "status": "pending"}
            
            try:
                if shot.is_first_shot:
                    # First shot: Use T2V
                    video_path = await self.generate_shot_t2v(shot)
                else:
                    # Subsequent shots: Use bridge frames + I2V
                    assert previous_frame is not None, "No previous frame for I2V"
                    
                    # Generate bridge frame
                    bridge_frame = await self.generate_bridge_frame(
                        shots[i-1].shot_id, 
                        previous_frame
                    )
                    
                    # Generate shot from bridge frame
                    video_path = await self.generate_shot_i2v(shot, bridge_frame)
                    
                    # Identity check
                    passed, similarity = await self.check_identity(
                        previous_frame, 
                        bridge_frame
                    )
                    results["identity_checks"].append({
                        "from_shot": shots[i-1].shot_id,
                        "to_shot": shot.shot_id,
                        "passed": passed,
                        "similarity": similarity,
                    })
                    
                    if not passed:
                        logger.warning(f"Identity drift detected in {shot.shot_id}!")
                        results["success"] = False
                
                # Store clip
                self.clips.append(video_path)
                
                # Extract last frame for next iteration
                previous_frame = await self.client.get_last_frame(video_path)
                self.frames.append(previous_frame)
                
                shot_result["status"] = "success"
                shot_result["video"] = str(video_path)
                
            except Exception as e:
                logger.error(f"Failed to generate {shot.shot_id}: {e}")
                shot_result["status"] = "failed"
                shot_result["error"] = str(e)
                results["success"] = False
            
            results["shots"].append(shot_result)
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("PIPELINE COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Total shots: {len(shots)}")
        logger.info(f"Successful: {sum(1 for s in results['shots'] if s['status'] == 'success')}")
        logger.info(f"Identity checks passed: {sum(1 for c in results['identity_checks'] if c['passed'])}/{len(results['identity_checks'])}")
        logger.info(f"Overall success: {results['success']}")
        
        return results


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Test the bridge frame pipeline")
    parser.add_argument(
        "--comfy-url",
        default="http://localhost:8188",
        help="ComfyUI server URL"
    )
    parser.add_argument(
        "--workflows-dir",
        default="./workflows",  # From project root: continuum/workflows/
        help="Directory containing workflow JSONs (t2v_wan21.json, i2v_wan21.json)"
    )
    parser.add_argument(
        "--output-dir", 
        default="./output",
        help="Output directory for generated videos"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock client (no GPU required)"
    )
    
    args = parser.parse_args()
    
    # Setup config
    config = PipelineConfig(
        comfy_url=args.comfy_url,
        workflows_dir=Path(args.workflows_dir),
        output_dir=Path(args.output_dir),
    )
    
    # Check workflows exist
    t2v_path = config.workflows_dir / "t2v_wan21.json"
    i2v_path = config.workflows_dir / "i2v_wan21.json"
    
    if not t2v_path.exists() or not i2v_path.exists():
        logger.error(f"Workflow files not found in {config.workflows_dir}")
        logger.error("Please copy t2v_wan21.json and i2v_wan21.json to that directory")
        sys.exit(1)
    
    # Create client (mock or real)
    if args.mock:
        logger.info("Using MOCK client (no GPU)")
        client = MockComfyClient(config.comfy_url, config.output_dir)
    else:
        # TODO: Real client implementation
        logger.error("Real client not implemented yet. Use --mock for testing.")
        sys.exit(1)
    
    # Create and run pipeline
    pipeline = BridgeFramePipeline(config, client)
    results = await pipeline.run(TEST_SCENE)
    
    # Save results
    results_path = config.output_dir / "pipeline_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())