"""
Continuum Engine - ComfyUI WebSocket Client

Manages connection to a remote ComfyUI server running on cloud GPUs.
Handles job submission, status polling, and result retrieval.

Design Principles:
1. Async-first (WebSocket is inherently async)
2. Connection resilience (auto-reconnect on disconnect)
3. Clean separation: client handles transport, workflow_loader handles content
4. Comprehensive logging for debugging remote issues
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, AsyncIterator
from urllib.parse import urljoin, urlparse

import aiohttp

from ..core.config import get_config, ComfyUIConfig
from ..core.error_recovery import retry_async, RetryConfig, ErrorCategory, CategorizedError

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & DATA STRUCTURES
# =============================================================================

class ComfyJobStatus(str, Enum):
    """Status of a job submitted to ComfyUI."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ComfyJob:
    """
    Represents a job submitted to ComfyUI.
    
    Attributes:
        prompt_id: Unique ID assigned by ComfyUI
        client_id: Our client session ID
        workflow: The workflow JSON that was submitted
        status: Current job status
        progress: Progress info (current_step, total_steps)
        outputs: Output file paths when completed
        error: Error message if failed
    """
    prompt_id: str
    client_id: str
    workflow: Dict[str, Any]
    status: ComfyJobStatus = ComfyJobStatus.QUEUED
    progress: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, list] = field(default_factory=dict)
    error: Optional[str] = None
    
    def is_terminal(self) -> bool:
        """Check if job has reached a terminal state."""
        return self.status in (
            ComfyJobStatus.COMPLETED,
            ComfyJobStatus.FAILED,
            ComfyJobStatus.CANCELLED
        )


@dataclass
class ComfyConnectionInfo:
    """Connection details for a ComfyUI server."""
    host: str
    ws_url: str
    http_url: str
    client_id: str
    connected: bool = False
    server_info: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ComfyError(Exception):
    """Base exception for ComfyUI errors."""
    pass


class ComfyConnectionError(ComfyError):
    """Failed to connect to ComfyUI server."""
    pass


class ComfyTimeoutError(ComfyError):
    """Operation timed out."""
    pass


class ComfyJobError(ComfyError):
    """Job execution failed."""
    def __init__(self, message: str, job: Optional[ComfyJob] = None):
        super().__init__(message)
        self.job = job


# =============================================================================
# COMFY CLIENT
# =============================================================================

class ComfyClient:
    """
    Async WebSocket client for ComfyUI.
    
    Usage:
        async with ComfyClient("ws://gpu-server:8188") as client:
            job = await client.submit_workflow(workflow_dict)
            result = await client.wait_for_completion(job.prompt_id)
            files = await client.download_outputs(result)
    
    Or manually:
        client = ComfyClient("ws://gpu-server:8188")
        await client.connect()
        try:
            # ... use client ...
        finally:
            await client.disconnect()
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        config: Optional[ComfyUIConfig] = None,
        client_id: Optional[str] = None
    ):
        """
        Initialize the client.
        
        Args:
            host: WebSocket URL (e.g., "ws://localhost:8188")
            config: ComfyUIConfig object (alternative to host)
            client_id: Unique client ID (auto-generated if not provided)
        """
        if config is None:
            config = get_config().comfyui
        
        self.host = host or config.host
        self.timeout_sec = config.timeout_sec
        self.poll_interval_sec = config.poll_interval_sec
        
        # Generate unique client ID for this session
        self.client_id = client_id or str(uuid.uuid4())
        
        # Parse URLs
        parsed = urlparse(self.host)
        if parsed.scheme in ("ws", "wss"):
            self.ws_url = self.host
            http_scheme = "https" if parsed.scheme == "wss" else "http"
            self.http_url = f"{http_scheme}://{parsed.netloc}"
        else:
            # Assume http(s) URL, derive WebSocket URL
            self.http_url = self.host.rstrip("/")
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            self.ws_url = f"{ws_scheme}://{parsed.netloc}"
        
        # Connection state
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected = False
        self._message_handlers: Dict[str, Callable] = {}
        self._pending_jobs: Dict[str, ComfyJob] = {}
        
        # Background task for message processing
        self._listener_task: Optional[asyncio.Task] = None
    
    # -------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def connect(self) -> ComfyConnectionInfo:
        """
        Establish connection to ComfyUI server.
        
        Returns:
            ComfyConnectionInfo with server details
            
        Raises:
            ComfyConnectionError: If connection fails
        """
        if self._connected:
            logger.debug("Already connected to ComfyUI")
            return self._get_connection_info()
        
        try:
            # Create HTTP session
            self._session = aiohttp.ClientSession()
            
            # Test HTTP endpoint first
            server_info = await self._get_server_info()
            logger.info(f"ComfyUI server info: {server_info}")
            
            # Connect WebSocket
            ws_url_with_client = f"{self.ws_url}/ws?clientId={self.client_id}"
            self._ws = await self._session.ws_connect(
                ws_url_with_client,
                heartbeat=30.0,  # Send ping every 30s
                receive_timeout=self.timeout_sec
            )
            
            self._connected = True
            
            # Start background listener
            self._listener_task = asyncio.create_task(self._message_listener())
            
            logger.info(f"Connected to ComfyUI at {self.host}")
            return self._get_connection_info(server_info)
            
        except aiohttp.ClientError as e:
            await self._cleanup()
            raise ComfyConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except Exception as e:
            await self._cleanup()
            raise ComfyConnectionError(f"Unexpected error connecting to {self.host}: {e}") from e
    
    async def disconnect(self) -> None:
        """Gracefully disconnect from ComfyUI server."""
        logger.info("Disconnecting from ComfyUI...")
        await self._cleanup()
    
    async def _cleanup(self) -> None:
        """Clean up all resources."""
        self._connected = False
        
        # Cancel listener task
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        
        # Close WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        
        # Close HTTP session
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
    
    async def __aenter__(self) -> "ComfyClient":
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
    
    def _get_connection_info(self, server_info: Optional[Dict] = None) -> ComfyConnectionInfo:
        """Build connection info object."""
        return ComfyConnectionInfo(
            host=self.host,
            ws_url=self.ws_url,
            http_url=self.http_url,
            client_id=self.client_id,
            connected=self._connected,
            server_info=server_info or {}
        )
    
    # -------------------------------------------------------------------------
    # HTTP API METHODS
    # -------------------------------------------------------------------------
    
    async def _get_server_info(self) -> Dict[str, Any]:
        """Get server system info via HTTP."""
        async with self._session.get(f"{self.http_url}/system_stats") as resp:
            if resp.status == 200:
                return await resp.json()
            return {}
    
    async def _post_prompt(self, workflow: Dict[str, Any]) -> str:
        """
        Submit a workflow via HTTP API.
        
        Args:
            workflow: The workflow JSON (prompt format)
            
        Returns:
            prompt_id assigned by ComfyUI
        """
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }
        
        async with self._session.post(
            f"{self.http_url}/prompt",
            json=payload
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise ComfyError(f"Failed to submit prompt: {resp.status} - {error_text}")
            
            data = await resp.json()
            return data["prompt_id"]
    
    async def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """Get execution history for a prompt."""
        async with self._session.get(
            f"{self.http_url}/history/{prompt_id}"
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get(prompt_id, {})
            return {}
    
    async def get_queue(self) -> Dict[str, Any]:
        """Get current queue status."""
        async with self._session.get(f"{self.http_url}/queue") as resp:
            if resp.status == 200:
                return await resp.json()
            return {"queue_running": [], "queue_pending": []}
    
    async def cancel_job(self, prompt_id: str) -> bool:
        """
        Cancel a queued or running job.
        
        Returns:
            True if cancellation was accepted
        """
        payload = {"delete": [prompt_id]}
        async with self._session.post(
            f"{self.http_url}/queue",
            json=payload
        ) as resp:
            return resp.status == 200
    
    async def upload_file(
        self,
        file_path: Path,
        subfolder: str = "",
        file_type: str = "input"
    ) -> Dict[str, str]:
        """
        Upload a file to ComfyUI server.
        
        Args:
            file_path: Local path to file
            subfolder: Subfolder on server (optional)
            file_type: "input", "output", or "temp"
            
        Returns:
            Dict with "name", "subfolder", "type"
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        data = aiohttp.FormData()
        data.add_field(
            "image",  # ComfyUI expects "image" field name
            open(file_path, "rb"),
            filename=file_path.name
        )
        if subfolder:
            data.add_field("subfolder", subfolder)
        data.add_field("type", file_type)
        
        async with self._session.post(
            f"{self.http_url}/upload/image",
            data=data
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise ComfyError(f"Failed to upload file: {resp.status} - {error_text}")
            
            return await resp.json()
    
    async def upload_image(
        self,
        image_path: Path,
        subfolder: str = "",
    ) -> str:
        """
        Upload an image to ComfyUI server and return the remote filename.
        
        This is a convenience wrapper around upload_file for image uploads.
        
        Args:
            image_path: Local path to image file
            subfolder: Subfolder on server (optional)
            
        Returns:
            Remote filename (e.g., "image_001.png")
        """
        result = await self.upload_file(image_path, subfolder=subfolder, file_type="input")
        return result.get("name", image_path.name)
    
    async def download_output(
        self,
        filename: str,
        subfolder: str = "",
        file_type: str = "output",
        save_path: Optional[Path] = None
    ) -> bytes:
        """
        Download an output file from ComfyUI server.
        
        Args:
            filename: Name of file on server
            subfolder: Subfolder on server
            file_type: "output", "input", or "temp"
            save_path: If provided, save to this path
            
        Returns:
            File contents as bytes
        """
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": file_type
        }
        
        async with self._session.get(
            f"{self.http_url}/view",
            params=params
        ) as resp:
            if resp.status != 200:
                raise ComfyError(f"Failed to download {filename}: {resp.status}")
            
            content = await resp.read()
            
            if save_path:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(content)
                logger.debug(f"Saved output to {save_path}")
            
            return content
    
    # -------------------------------------------------------------------------
    # JOB MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def submit_workflow(self, workflow: Dict[str, Any]) -> ComfyJob:
        """
        Submit a workflow for execution.
        
        Args:
            workflow: ComfyUI workflow in API format (node_id -> node_config)
            
        Returns:
            ComfyJob object for tracking
        """
        if not self._connected:
            raise ComfyConnectionError("Not connected to ComfyUI")
        
        prompt_id = await self._post_prompt(workflow)
        
        job = ComfyJob(
            prompt_id=prompt_id,
            client_id=self.client_id,
            workflow=workflow,
            status=ComfyJobStatus.QUEUED
        )
        
        self._pending_jobs[prompt_id] = job
        logger.info(f"Submitted job: {prompt_id}")
        
        return job
    
    async def submit(self, workflow: Dict[str, Any]) -> ComfyJob:
        """Alias for submit_workflow for backward compatibility."""
        return await self.submit_workflow(workflow)
    
    async def wait_for_completion(
        self,
        prompt_id: str,
        timeout_sec: Optional[float] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None
    ) -> ComfyJob:
        """
        Wait for a job to complete.
        
        Args:
            prompt_id: The job ID to wait for
            timeout_sec: Timeout (uses config default if not specified)
            progress_callback: Called with progress updates
            
        Returns:
            Completed ComfyJob with outputs
            
        Raises:
            ComfyTimeoutError: If job doesn't complete in time
            ComfyJobError: If job fails
        """
        timeout = timeout_sec or self.timeout_sec
        start_time = asyncio.get_event_loop().time()
        
        job = self._pending_jobs.get(prompt_id)
        if not job:
            # Job wasn't submitted through us, create a tracking object
            job = ComfyJob(
                prompt_id=prompt_id,
                client_id=self.client_id,
                workflow={}
            )
            self._pending_jobs[prompt_id] = job
        
        while not job.is_terminal():
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise ComfyTimeoutError(
                    f"Job {prompt_id} timed out after {timeout}s"
                )
            
            # Poll history for completion
            history = await self.get_history(prompt_id)
            if history:
                # Job has history = it's done
                if "outputs" in history:
                    job.status = ComfyJobStatus.COMPLETED
                    job.outputs = history.get("outputs", {})
                elif "error" in history:
                    job.status = ComfyJobStatus.FAILED
                    job.error = str(history.get("error"))
            
            # Report progress if callback provided
            if progress_callback and job.progress:
                progress_callback(job.progress)
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval_sec)
        
        # Remove from pending
        self._pending_jobs.pop(prompt_id, None)
        
        if job.status == ComfyJobStatus.FAILED:
            raise ComfyJobError(f"Job {prompt_id} failed: {job.error}", job)
        
        logger.info(f"Job {prompt_id} completed successfully")
        return job
    
    async def run_workflow(
        self,
        workflow: Dict[str, Any],
        timeout_sec: Optional[float] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None
    ) -> ComfyJob:
        """
        Submit a workflow and wait for completion (convenience method).
        
        Args:
            workflow: ComfyUI workflow dict
            timeout_sec: Timeout in seconds
            progress_callback: Progress update callback
            
        Returns:
            Completed ComfyJob with outputs
        """
        job = await self.submit_workflow(workflow)
        return await self.wait_for_completion(
            job.prompt_id,
            timeout_sec=timeout_sec,
            progress_callback=progress_callback
        )
    
    # -------------------------------------------------------------------------
    # WEBSOCKET MESSAGE HANDLING
    # -------------------------------------------------------------------------
    
    async def _message_listener(self) -> None:
        """Background task that listens for WebSocket messages."""
        logger.debug("WebSocket listener started")
        
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(json.loads(msg.data))
                    
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    # Binary messages are typically preview images
                    await self._handle_binary(msg.data)
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self._ws.exception()}")
                    break
                    
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("WebSocket closed by server")
                    break
                    
        except asyncio.CancelledError:
            logger.debug("WebSocket listener cancelled")
            raise
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}")
        finally:
            self._connected = False
            logger.debug("WebSocket listener stopped")
    
    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Handle a parsed WebSocket message."""
        msg_type = message.get("type")
        data = message.get("data", {})
        
        logger.debug(f"WS message: {msg_type}")
        
        if msg_type == "status":
            # Queue status update
            queue_remaining = data.get("status", {}).get("exec_info", {}).get("queue_remaining", 0)
            logger.debug(f"Queue remaining: {queue_remaining}")
            
        elif msg_type == "execution_start":
            prompt_id = data.get("prompt_id")
            if prompt_id in self._pending_jobs:
                self._pending_jobs[prompt_id].status = ComfyJobStatus.RUNNING
                logger.info(f"Job {prompt_id} started executing")
                
        elif msg_type == "executing":
            prompt_id = data.get("prompt_id")
            node_id = data.get("node")
            
            if prompt_id in self._pending_jobs:
                job = self._pending_jobs[prompt_id]
                job.progress["current_node"] = node_id
                
                if node_id is None:
                    # Execution finished
                    logger.debug(f"Job {prompt_id} execution finished")
                    
        elif msg_type == "progress":
            prompt_id = data.get("prompt_id")
            if prompt_id in self._pending_jobs:
                job = self._pending_jobs[prompt_id]
                job.progress["value"] = data.get("value", 0)
                job.progress["max"] = data.get("max", 100)
                
        elif msg_type == "executed":
            prompt_id = data.get("prompt_id")
            node_id = data.get("node")
            output = data.get("output", {})
            
            if prompt_id in self._pending_jobs:
                job = self._pending_jobs[prompt_id]
                job.outputs[node_id] = output
                logger.debug(f"Job {prompt_id} node {node_id} output received")
                
        elif msg_type == "execution_error":
            prompt_id = data.get("prompt_id")
            if prompt_id in self._pending_jobs:
                job = self._pending_jobs[prompt_id]
                job.status = ComfyJobStatus.FAILED
                job.error = data.get("exception_message", "Unknown error")
                logger.error(f"Job {prompt_id} failed: {job.error}")
                
        elif msg_type == "execution_cached":
            # Node outputs were cached, no new execution needed
            prompt_id = data.get("prompt_id")
            logger.debug(f"Job {prompt_id} using cached results")
    
    async def _handle_binary(self, data: bytes) -> None:
        """Handle binary WebSocket message (usually preview images)."""
        # First 4 bytes are message type, next 4 are format
        # Rest is the image data
        if len(data) > 8:
            # msg_type = int.from_bytes(data[:4], "big")
            # Could emit preview images to a callback here
            pass
    
    # -------------------------------------------------------------------------
    # HEALTH CHECK
    # -------------------------------------------------------------------------
    
    async def health_check(self) -> bool:
        """
        Check if the ComfyUI server is reachable and healthy.
        
        Returns:
            True if server is healthy
        """
        try:
            if not self._session:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.http_url}/system_stats",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        return resp.status == 200
            else:
                info = await self._get_server_info()
                return bool(info)
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def get_comfy_client() -> ComfyClient:
    """
    Get a connected ComfyClient using global config.
    
    Usage:
        client = await get_comfy_client()
        try:
            job = await client.run_workflow(workflow)
        finally:
            await client.disconnect()
    
    Or better, use as context manager:
        async with ComfyClient() as client:
            job = await client.run_workflow(workflow)
    """
    client = ComfyClient()
    await client.connect()
    return client


@retry_async(max_attempts=3, base_delay_sec=2.0)
async def submit_with_retry(
    client: ComfyClient,
    workflow: Dict[str, Any],
    timeout_sec: Optional[float] = None
) -> ComfyJob:
    """
    Submit a workflow with automatic retry on transient failures.
    
    Use this instead of client.run_workflow() when you want retry behavior.
    """
    return await client.run_workflow(workflow, timeout_sec=timeout_sec)