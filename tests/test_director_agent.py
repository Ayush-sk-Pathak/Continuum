#!/usr/bin/env python3
"""
Test script for the Director Agent.

This script demonstrates parsing a screenplay into a project.json
using the LLM-powered Director Agent.

Usage:
    python tests/test_director_agent.py [script_file]

    If no script file provided, uses a sample screenplay.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.director import (
    DirectorAgent,
    DirectorConfig,
    LLMProvider,
    save_project,
)


# =============================================================================
# SAMPLE SCREENPLAY
# =============================================================================

SAMPLE_SCREENPLAY = """
TITLE: THE LAST GUARDIAN

FADE IN:

INT. ANCIENT TEMPLE - NIGHT

A vast temple interior, illuminated by floating blue crystals. Stone pillars
stretch toward a vaulted ceiling lost in darkness. Ancient runes glow faintly
on the walls.

ARIA (20s, silver hair, wearing ornate armor with glowing blue patterns)
stands before a massive stone door. She carries a crystalline sword that
pulses with inner light.

ARIA
(determined)
This is it. The final seal.

She places her hand on the door. The runes pulse brighter.

KAI (voice, ethereal)
Aria... are you certain? Once opened, there's no going back.

ARIA
(resolute)
I've come too far to turn back now.

The door begins to rumble and slowly opens, revealing blinding white light.

EXT. CRYSTAL GARDEN - CONTINUOUS

Aria steps through into an impossibly beautiful garden. Crystal flowers bloom
in every color. A gentle mist floats between towering crystal trees.

In the center, KAI (ageless, translucent form, flowing robes made of light)
hovers above a pedestal containing a pulsing orb of pure energy - THE HEART
OF ETERNITY.

ARIA
(in awe)
You're... beautiful.

KAI
(sad smile)
And you're brave. Few mortals have made it this far.

Aria approaches slowly, sword lowered.

ARIA
I didn't come to fight. I came to understand.

KAI
Then perhaps... there is hope after all.

Kai extends a hand. The Heart of Eternity floats toward Aria, bathing her
in golden light.

FADE TO WHITE.

THE END
"""


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Main entry point."""

    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║              DIRECTOR AGENT - SCRIPT TO PROJECT                   ║
║              Screenplay → Scene Graph → project.json              ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    # Check for script file argument
    if len(sys.argv) > 1:
        script_path = Path(sys.argv[1])
        if script_path.exists():
            print(f"Loading script from: {script_path}")
            with open(script_path, "r") as f:
                script_text = f.read()
        else:
            print(f"Script file not found: {script_path}")
            print("Using sample screenplay instead.")
            script_text = SAMPLE_SCREENPLAY
    else:
        print("No script file provided. Using sample screenplay.")
        script_text = SAMPLE_SCREENPLAY

    print(f"\nScript length: {len(script_text)} characters")
    print("-" * 60)

    # Configure the Director Agent
    config = DirectorConfig.for_anime()

    # Use OpenAI if ANTHROPIC_API_KEY not available
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        config.provider = LLMProvider.CLAUDE
        config.model = "claude-sonnet-4-20250514"
    else:
        print("ANTHROPIC_API_KEY not set, using OpenAI GPT-4o-mini")
        config.provider = LLMProvider.OPENAI
        config.model = "gpt-4o-mini"

    config.temperature = 0.3

    print(f"\nConfiguration:")
    print(f"  Provider: {config.provider.value}")
    print(f"  Model: {config.model}")
    print(f"  Style: {config.style}")
    print(f"  Resolution: {config.target_resolution}")
    print(f"  FPS: {config.target_fps}")

    # Initialize Director Agent
    director = DirectorAgent(config=config)

    # Parse the script
    print(f"\n{'='*60}")
    print("PARSING SCRIPT")
    print(f"{'='*60}")

    try:
        project = await director.parse_script(
            script_text=script_text,
            project_id="last_guardian",
            title="The Last Guardian",
            description="A short anime film about a warrior seeking the Heart of Eternity",
        )

        # Print summary
        print(f"\n{'='*60}")
        print("PARSING COMPLETE")
        print(f"{'='*60}")

        num_scenes = len(project.get("scenes", []))
        num_shots = sum(len(s.get("shots", [])) for s in project.get("scenes", []))
        num_chars = len(project.get("bible", {}).get("characters", {}))
        num_locs = len(project.get("bible", {}).get("locations", {}))

        print(f"\nProject Summary:")
        print(f"  Title: {project.get('title')}")
        print(f"  Style: {project.get('style')}")
        print(f"  Scenes: {num_scenes}")
        print(f"  Shots: {num_shots}")
        print(f"  Characters: {num_chars}")
        print(f"  Locations: {num_locs}")

        # Print characters
        print(f"\nCharacters:")
        for char_id, char in project.get("bible", {}).get("characters", {}).items():
            print(f"  - {char.get('name')} ({char_id})")
            print(f"    {char.get('description', '')[:80]}...")

        # Print locations
        print(f"\nLocations:")
        for loc_id, loc in project.get("bible", {}).get("locations", {}).items():
            print(f"  - {loc.get('name')} ({loc_id})")

        # Print scene/shot breakdown
        print(f"\nScene/Shot Breakdown:")
        for scene in project.get("scenes", []):
            print(f"\n  Scene {scene.get('index')}: {scene.get('title')}")
            print(f"    Location: {scene.get('location', {}).get('display_name')}")
            print(f"    Time: {scene.get('time_of_day')}")
            for shot in scene.get("shots", []):
                print(f"    - Shot {shot.get('index')}: {shot.get('description')[:50]}...")
                if shot.get("dialogue"):
                    for line in shot.get("dialogue", []):
                        print(f"      [{line.get('character_id')}]: \"{line.get('text')[:40]}...\"")

        # Save project
        output_path = Path(f"projects/last_guardian/project.json")
        save_project(project, output_path)

        print(f"\n{'='*60}")
        print("PROJECT SAVED")
        print(f"{'='*60}")
        print(f"\nOutput: {output_path}")
        print(f"\nTo render this project:")
        print(f"  python tests/test_demo_full_pipeline.py projects/last_guardian/project.json")

        # Also save the full JSON for inspection
        pretty_json_path = Path(f"projects/last_guardian/project_pretty.json")
        with open(pretty_json_path, "w") as f:
            json.dump(project, f, indent=2)
        print(f"\nPretty JSON: {pretty_json_path}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
