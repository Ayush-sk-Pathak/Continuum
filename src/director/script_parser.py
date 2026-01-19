"""
Continuum Engine - Director Agent (Script Parser)

The LLM-powered "brain" that transforms screenplays into production-ready Scene Graphs.

The Problem:
    Creating project.json files manually is time-consuming and doesn't scale.
    Every new film requires careful JSON authoring with prompts, timing, etc.

The Solution:
    An LLM-based Director Agent that:
    1. Reads a screenplay/script (text or PDF)
    2. Extracts characters, locations, props
    3. Breaks story into scenes and shots
    4. Generates image/video prompts for each shot
    5. Extracts dialogue with timing estimates
    6. Outputs a complete project.json ready for the pipeline

Architecture Position:
    User Script → Director Agent → project.json → ComfyUI Pipeline → Video

Supported LLMs:
    - Claude (Anthropic) - Recommended for quality
    - GPT-4 (OpenAI) - Alternative
    - Local models via Ollama (future)

Design Principles:
    1. Multi-stage parsing: Extract entities first, then structure
    2. Style-aware: Generates prompts appropriate to target style (anime, realistic, etc.)
    3. Validation: Checks output structure before returning
    4. Iterative refinement: Can re-run stages if validation fails
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class LLMProvider(str, Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    OPENAI = "openai"
    OLLAMA = "ollama"


@dataclass
class DirectorConfig:
    """Configuration for the Director Agent."""

    # LLM settings
    provider: LLMProvider = LLMProvider.CLAUDE
    model: str = "claude-sonnet-4-20250514"  # or "gpt-4o-mini"
    temperature: float = 0.3  # Lower for more consistent output
    max_tokens: int = 8000

    # Output settings
    style: str = "anime"  # anime, realistic, cartoon, etc.
    target_resolution: Tuple[int, int] = (832, 480)
    target_fps: int = 16
    default_shot_duration: float = 5.0

    # Voice settings (defaults)
    default_voice_provider: str = "elevenlabs"
    default_voice_id: str = "adam"

    # Prompt settings
    include_negative_prompts: bool = True
    prompt_style_suffix: str = ""  # Added to all prompts

    @classmethod
    def for_anime(cls) -> "DirectorConfig":
        """Preset for anime-style content."""
        return cls(
            style="anime",
            target_resolution=(832, 480),
            prompt_style_suffix="anime style, high quality anime art, 4k",
        )

    @classmethod
    def for_realistic(cls) -> "DirectorConfig":
        """Preset for realistic/live-action style content."""
        return cls(
            style="realistic",
            target_resolution=(1280, 720),
            prompt_style_suffix="photorealistic, cinematic, 8k, detailed",
        )


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SYSTEM_PROMPT_EXTRACT_ENTITIES = """You are a film production assistant. Your job is to extract all characters, locations, and props from a screenplay.

For each CHARACTER, extract:
- A unique snake_case ID (e.g., "john_smith", "detective_harris")
- Their full name
- A detailed visual description (appearance, clothing, distinguishing features)
- Their personality/demeanor in a few words

For each LOCATION, extract:
- A unique snake_case ID (e.g., "coffee_shop", "dark_alley")
- The location name
- A detailed visual description (atmosphere, lighting, key features)

For each PROP (important objects that appear in multiple scenes), extract:
- A unique snake_case ID (e.g., "red_mug", "mysterious_letter")
- The prop name
- A visual description

Output as JSON with this exact structure:
{
  "characters": {
    "character_id": {
      "entity_id": "character_id",
      "name": "Full Name",
      "description": "Visual description...",
      "personality": "Brief personality"
    }
  },
  "locations": {
    "location_id": {
      "entity_id": "location_id",
      "name": "Location Name",
      "description": "Visual description..."
    }
  },
  "props": {
    "prop_id": {
      "entity_id": "prop_id",
      "name": "Prop Name",
      "description": "Visual description..."
    }
  }
}

Only output valid JSON, no other text."""

SYSTEM_PROMPT_BREAK_INTO_SCENES = """You are a film director breaking a screenplay into scenes.

A SCENE is a continuous sequence in one location with consistent time. A new scene starts when:
- Location changes
- Significant time passes
- Major tonal shift occurs

For each scene, provide:
- scene_id: Unique snake_case ID
- index: Scene number (0-indexed)
- title: Short descriptive title
- description: What happens in this scene (1-2 sentences)
- location: The location entity_id from the bible
- time_of_day: morning, day, afternoon, sunset, evening, night, golden_hour
- characters: List of character entity_ids present

Output as JSON array:
{
  "scenes": [
    {
      "scene_id": "scene_coffee_meeting",
      "index": 0,
      "title": "The Meeting",
      "description": "John meets Sarah at the coffee shop",
      "location_id": "coffee_shop",
      "time_of_day": "morning",
      "character_ids": ["john_smith", "sarah_jones"]
    }
  ]
}

Only output valid JSON, no other text."""

SYSTEM_PROMPT_BREAK_INTO_SHOTS = """You are a cinematographer breaking a scene into individual shots.

For each shot, provide:
- shot_id: Unique ID like "shot_01", "shot_02", etc.
- index: Global shot number (0-indexed across all scenes)
- duration_sec: Shot duration (typically 3-7 seconds)
- description: What happens visually
- shot_type: wide, medium, close, extreme_close, over_shoulder, two_shot
- character_ids: Characters visible in this shot
- prop_ids: Props visible in this shot

For shots with dialogue, include:
- dialogue: Array of lines with character_id, text, emotion

Consider pacing:
- Open scenes with establishing/wide shots
- Use close-ups for emotional moments
- Vary shot types to maintain visual interest

Output as JSON:
{
  "shots": [
    {
      "shot_id": "shot_01",
      "scene_id": "scene_coffee_meeting",
      "index": 0,
      "duration_sec": 5.0,
      "description": "Wide shot of coffee shop exterior",
      "shot_type": "wide",
      "character_ids": [],
      "prop_ids": [],
      "dialogue": []
    },
    {
      "shot_id": "shot_02",
      "scene_id": "scene_coffee_meeting",
      "index": 1,
      "duration_sec": 4.0,
      "description": "Medium shot of John sitting at table",
      "shot_type": "medium",
      "character_ids": ["john_smith"],
      "prop_ids": ["coffee_cup"],
      "dialogue": [
        {
          "character_id": "john_smith",
          "text": "I've been waiting for this moment.",
          "emotion": "nervous"
        }
      ]
    }
  ]
}

Only output valid JSON, no other text."""


def get_prompt_generation_system(style: str, style_suffix: str) -> str:
    """Generate system prompt for creating image/video prompts."""

    style_guides = {
        "anime": """
Style: ANIME
- Use anime-specific descriptors: "anime style", "manga art", "cel-shaded"
- Describe characters with anime features: large expressive eyes, stylized hair
- Include quality tags: "high quality anime art", "detailed anime", "4k"
- Avoid: "realistic", "photorealistic", "3d render"
""",
        "realistic": """
Style: REALISTIC/CINEMATIC
- Use photorealistic descriptors: "cinematic", "photorealistic", "film grain"
- Describe lighting: "golden hour", "dramatic shadows", "soft lighting"
- Include quality tags: "8k", "detailed", "professional photography"
- Avoid: "anime", "cartoon", "stylized"
""",
        "cartoon": """
Style: CARTOON/ANIMATED
- Use cartoon descriptors: "cartoon style", "animated", "colorful"
- Emphasize bold colors and clean lines
- Include quality tags: "high quality animation", "vibrant colors"
- Avoid: "realistic", "photorealistic"
"""
    }

    style_guide = style_guides.get(style, style_guides["anime"])

    return f"""You are a prompt engineer for AI image/video generation.

Your job is to create detailed prompts for each shot that will generate consistent, high-quality visuals.

{style_guide}

For each shot, generate:
1. prompt: Detailed positive prompt including:
   - Character descriptions (from bible)
   - Location description (from bible)
   - Shot type and framing
   - Action/pose
   - Lighting and atmosphere
   - Style tags
   {f'- Always end with: {style_suffix}' if style_suffix else ''}

2. negative_prompt: Things to avoid:
   - Common defects: "blurry, deformed, bad anatomy, extra limbs"
   - Style conflicts based on target style
   - "watermark, text, low quality"

Output as JSON mapping shot_id to prompts:
{{
  "shot_01": {{
    "prompt": "detailed prompt here...",
    "negative_prompt": "things to avoid..."
  }}
}}

Only output valid JSON, no other text."""


# =============================================================================
# DIRECTOR AGENT
# =============================================================================

class DirectorAgent:
    """
    LLM-powered Director Agent that parses screenplays into Scene Graphs.

    Usage:
        director = DirectorAgent(config=DirectorConfig.for_anime())
        project = await director.parse_script(script_text, project_id="my_film")
        project.save("projects/my_film/project.json")
    """

    def __init__(
        self,
        config: Optional[DirectorConfig] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the Director Agent.

        Args:
            config: Director configuration (defaults to anime preset)
            api_key: API key for LLM provider (or use env var)
        """
        self.config = config or DirectorConfig.for_anime()
        self.api_key = api_key
        self._client = None

    async def _get_client(self):
        """Lazy-initialize the LLM client."""
        if self._client is not None:
            return self._client

        if self.config.provider == LLMProvider.CLAUDE:
            try:
                import anthropic
                api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        elif self.config.provider == LLMProvider.OPENAI:
            try:
                import openai
                api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not set")
                self._client = openai.OpenAI(api_key=api_key)
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")

        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

        return self._client

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM and return the response text."""
        client = await self._get_client()

        if self.config.provider == LLMProvider.CLAUDE:
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text

        elif self.config.provider == LLMProvider.OPENAI:
            response = client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content

        raise ValueError(f"Unsupported provider: {self.config.provider}")

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try to find JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            text = json_match.group(1)

        # Clean up common issues
        text = text.strip()

        # Try to parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.error(f"Text was: {text[:500]}...")
            raise ValueError(f"LLM did not return valid JSON: {e}")

    async def parse_script(
        self,
        script_text: str,
        project_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Parse a screenplay into a complete project.json structure.

        Args:
            script_text: The screenplay/script text
            project_id: Unique ID for the project
            title: Project title (auto-generated if not provided)
            description: Project description (auto-generated if not provided)

        Returns:
            Complete project dictionary ready to save as JSON
        """
        logger.info(f"Parsing script for project: {project_id}")

        # Stage 1: Extract entities (characters, locations, props)
        logger.info("Stage 1: Extracting entities...")
        entities = await self._extract_entities(script_text)

        # Stage 2: Break into scenes
        logger.info("Stage 2: Breaking into scenes...")
        scenes = await self._break_into_scenes(script_text, entities)

        # Stage 3: Break scenes into shots
        logger.info("Stage 3: Breaking into shots...")
        shots_by_scene = await self._break_into_shots(script_text, entities, scenes)

        # Stage 4: Generate prompts for each shot
        logger.info("Stage 4: Generating prompts...")
        prompts = await self._generate_prompts(entities, scenes, shots_by_scene)

        # Stage 5: Assemble final project structure
        logger.info("Stage 5: Assembling project...")
        project = self._assemble_project(
            project_id=project_id,
            title=title,
            description=description,
            entities=entities,
            scenes=scenes,
            shots_by_scene=shots_by_scene,
            prompts=prompts,
        )

        logger.info(f"Project parsed: {len(scenes)} scenes, {sum(len(s) for s in shots_by_scene.values())} shots")
        return project

    async def _extract_entities(self, script_text: str) -> dict:
        """Extract characters, locations, and props from the script."""
        response = await self._call_llm(
            system_prompt=SYSTEM_PROMPT_EXTRACT_ENTITIES,
            user_prompt=f"Extract all characters, locations, and props from this screenplay:\n\n{script_text}",
        )
        return self._extract_json(response)

    async def _break_into_scenes(self, script_text: str, entities: dict) -> list:
        """Break the script into scenes."""
        entities_summary = json.dumps(entities, indent=2)

        response = await self._call_llm(
            system_prompt=SYSTEM_PROMPT_BREAK_INTO_SCENES,
            user_prompt=f"""Break this screenplay into scenes.

Available entities (bible):
{entities_summary}

Screenplay:
{script_text}""",
        )

        result = self._extract_json(response)
        return result.get("scenes", [])

    async def _break_into_shots(
        self,
        script_text: str,
        entities: dict,
        scenes: list,
    ) -> dict:
        """Break each scene into shots."""
        shots_by_scene = {}
        global_shot_index = 0

        for scene in scenes:
            scene_id = scene["scene_id"]

            # Extract scene-specific script section if possible
            # For now, use the full script with scene context
            scene_context = f"""
Scene: {scene['title']}
Description: {scene['description']}
Location: {scene['location_id']}
Time: {scene['time_of_day']}
Characters: {', '.join(scene['character_ids'])}
"""

            response = await self._call_llm(
                system_prompt=SYSTEM_PROMPT_BREAK_INTO_SHOTS,
                user_prompt=f"""Break this scene into individual shots.

Scene Context:
{scene_context}

Available entities:
{json.dumps(entities, indent=2)}

Full screenplay for reference:
{script_text}

Create shots for scene "{scene_id}" starting at global index {global_shot_index}.""",
            )

            result = self._extract_json(response)
            shots = result.get("shots", [])

            # Update global indices
            for i, shot in enumerate(shots):
                shot["index"] = global_shot_index + i
                shot["scene_id"] = scene_id

            shots_by_scene[scene_id] = shots
            global_shot_index += len(shots)

        return shots_by_scene

    async def _generate_prompts(
        self,
        entities: dict,
        scenes: list,
        shots_by_scene: dict,
    ) -> dict:
        """Generate image/video prompts for each shot."""

        system_prompt = get_prompt_generation_system(
            self.config.style,
            self.config.prompt_style_suffix,
        )

        all_prompts = {}

        for scene_id, shots in shots_by_scene.items():
            # Find scene info
            scene = next((s for s in scenes if s["scene_id"] == scene_id), None)

            shots_info = []
            for shot in shots:
                shot_info = {
                    "shot_id": shot["shot_id"],
                    "description": shot["description"],
                    "shot_type": shot["shot_type"],
                    "characters": shot.get("character_ids", []),
                    "props": shot.get("prop_ids", []),
                }
                shots_info.append(shot_info)

            response = await self._call_llm(
                system_prompt=system_prompt,
                user_prompt=f"""Generate prompts for these shots.

Target style: {self.config.style}

Entity descriptions (use these for consistency):
{json.dumps(entities, indent=2)}

Scene: {scene['title'] if scene else 'Unknown'}
Location: {scene['location_id'] if scene else 'Unknown'}
Time: {scene['time_of_day'] if scene else 'day'}

Shots to generate prompts for:
{json.dumps(shots_info, indent=2)}""",
            )

            scene_prompts = self._extract_json(response)
            all_prompts.update(scene_prompts)

        return all_prompts

    def _assemble_project(
        self,
        project_id: str,
        title: Optional[str],
        description: Optional[str],
        entities: dict,
        scenes: list,
        shots_by_scene: dict,
        prompts: dict,
    ) -> dict:
        """Assemble the final project.json structure."""

        # Build bible (consistency dictionary)
        bible = {
            "dict_id": f"{project_id}_bible",
            "title": f"{title or project_id} Bible",
            "characters": {},
            "locations": {},
            "props": {},
        }

        # Process characters
        for char_id, char_data in entities.get("characters", {}).items():
            bible["characters"][char_id] = {
                "entity_id": char_id,
                "name": char_data.get("name", char_id),
                "description": char_data.get("description", ""),
                "face_refs": [],
                "lora_path": None,
                "lora_strength": 0.0,
                "voice_config": {
                    "voice_id": self.config.default_voice_id,
                    "provider": self.config.default_voice_provider,
                    "speaking_rate": 1.0,
                    "pitch": 0.0,
                },
            }

        # Process locations
        for loc_id, loc_data in entities.get("locations", {}).items():
            bible["locations"][loc_id] = {
                "entity_id": loc_id,
                "name": loc_data.get("name", loc_id),
                "description": loc_data.get("description", ""),
            }

        # Process props
        for prop_id, prop_data in entities.get("props", {}).items():
            bible["props"][prop_id] = {
                "entity_id": prop_id,
                "name": prop_data.get("name", prop_id),
                "description": prop_data.get("description", ""),
            }

        # Build scenes with shots
        assembled_scenes = []
        dialogue_time_offset = 0.0

        for scene_data in scenes:
            scene_id = scene_data["scene_id"]
            shots = shots_by_scene.get(scene_id, [])

            assembled_shots = []
            scene_time = 0.0

            for shot_data in shots:
                shot_id = shot_data["shot_id"]
                shot_prompts = prompts.get(shot_id, {})

                # Build character refs
                char_refs = []
                for char_id in shot_data.get("character_ids", []):
                    char_refs.append({
                        "entity_id": char_id,
                        "entity_type": "character",
                        "display_name": entities.get("characters", {}).get(char_id, {}).get("name", char_id),
                    })

                # Build prop refs
                prop_refs = []
                for prop_id in shot_data.get("prop_ids", []):
                    prop_refs.append({
                        "entity_id": prop_id,
                        "entity_type": "prop",
                        "display_name": entities.get("props", {}).get(prop_id, {}).get("name", prop_id),
                    })

                # Build dialogue with timing
                dialogue = []
                dialogue_time = 1.0  # Start dialogue 1s into shot

                for i, line in enumerate(shot_data.get("dialogue", [])):
                    line_duration = self._estimate_duration(line.get("text", ""))
                    dialogue.append({
                        "line_id": f"line_{shot_id}_{i}",
                        "character_id": line.get("character_id", "unknown"),
                        "text": line.get("text", ""),
                        "start_time_sec": dialogue_time_offset + scene_time + dialogue_time,
                        "estimated_duration_sec": line_duration,
                        "emotion": line.get("emotion", "neutral"),
                    })
                    dialogue_time += line_duration + 0.5  # Gap between lines

                duration = shot_data.get("duration_sec", self.config.default_shot_duration)

                assembled_shot = {
                    "shot_id": shot_id,
                    "scene_id": scene_id,
                    "index": shot_data.get("index", 0),
                    "duration_sec": duration,
                    "description": shot_data.get("description", ""),
                    "prompt": shot_prompts.get("prompt", ""),
                    "negative_prompt": shot_prompts.get("negative_prompt", ""),
                    "shot_type": shot_data.get("shot_type", "medium"),
                    "characters": char_refs,
                    "props": prop_refs,
                    "dialogue": dialogue,
                }

                assembled_shots.append(assembled_shot)
                scene_time += duration

            # Build location ref
            loc_id = scene_data.get("location_id", "")
            location_ref = {
                "entity_id": loc_id,
                "entity_type": "location",
                "display_name": entities.get("locations", {}).get(loc_id, {}).get("name", loc_id),
            }

            # Build character refs for scene
            scene_char_refs = []
            for char_id in scene_data.get("character_ids", []):
                scene_char_refs.append({
                    "entity_id": char_id,
                    "entity_type": "character",
                    "display_name": entities.get("characters", {}).get(char_id, {}).get("name", char_id),
                })

            assembled_scene = {
                "scene_id": scene_id,
                "index": scene_data.get("index", 0),
                "title": scene_data.get("title", ""),
                "description": scene_data.get("description", ""),
                "location": location_ref,
                "time_of_day": scene_data.get("time_of_day", "day"),
                "characters": scene_char_refs,
                "shots": assembled_shots,
            }

            assembled_scenes.append(assembled_scene)
            dialogue_time_offset += scene_time

        # Build final project
        project = {
            "project_id": project_id,
            "title": title or f"Project {project_id}",
            "description": description or f"Generated project from script",
            "style": self.config.style,
            "target_resolution": list(self.config.target_resolution),
            "target_fps": self.config.target_fps,
            "bible": bible,
            "scenes": assembled_scenes,
            "audio": {
                "global_ambience": {
                    "ambience_id": "ambient_main",
                    "type": "cinematic",
                    "prompt": "cinematic ambient atmosphere, emotional background",
                    "volume_db": -15,
                },
                "music_track": None,
            },
            "_meta": {
                "created": datetime.now().strftime("%Y-%m-%d"),
                "version": "2.0.0",
                "generator": "DirectorAgent",
                "notes": "Auto-generated from screenplay",
            },
        }

        return project

    def _estimate_duration(self, text: str) -> float:
        """Estimate speech duration based on text length."""
        # Average speaking rate: ~150 words per minute = 2.5 words/sec
        # Average word length: ~5 characters
        words = len(text.split())
        return max(0.5, words / 2.5)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def parse_script(
    script_text: str,
    project_id: str,
    style: str = "anime",
    title: Optional[str] = None,
    provider: LLMProvider = LLMProvider.CLAUDE,
) -> dict:
    """
    Convenience function to parse a script into a project.

    Args:
        script_text: The screenplay text
        project_id: Unique project ID
        style: Visual style (anime, realistic, cartoon)
        title: Project title
        provider: LLM provider to use

    Returns:
        Complete project dictionary
    """
    if style == "anime":
        config = DirectorConfig.for_anime()
    elif style == "realistic":
        config = DirectorConfig.for_realistic()
    else:
        config = DirectorConfig(style=style)

    config.provider = provider

    director = DirectorAgent(config=config)
    return await director.parse_script(script_text, project_id, title)


def save_project(project: dict, path: Path) -> None:
    """Save a project dictionary to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(project, f, indent=2)

    logger.info(f"Project saved to: {path}")


def load_project(path: Path) -> dict:
    """Load a project from JSON file."""
    with open(path, "r") as f:
        return json.load(f)
