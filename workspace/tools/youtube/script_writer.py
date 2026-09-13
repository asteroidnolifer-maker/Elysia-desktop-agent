#!/usr/bin/env python3
"""
YouTube Script Writer for Elysia
Generate video scripts using templates.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class ScriptWriter:
    """Generate video scripts from templates."""

    def __init__(self, templates_path: str = None):
        self.templates_path = templates_path or Path(__file__).parent / "script_templates.json"
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[str, Any]:
        if self.templates_path.exists():
            return json.loads(self.templates_path.read_text())
        return {
            "tutorial": {
                "sections": [
                    {"name": "Hook", "duration": "0:00-0:30", "prompt": "Grab attention with a compelling opening"},
                    {"name": "Intro", "duration": "0:30-1:00", "prompt": "Introduce yourself and the topic"},
                    {"name": "Prerequisites", "duration": "1:00-1:30", "prompt": "List what viewers need to know/have"},
                    {"name": "Main Content", "duration": "1:30-8:00", "prompt": "Step-by-step tutorial content"},
                    {"name": "Summary", "duration": "8:00-9:00", "prompt": "Recap key points"},
                    {"name": "CTA", "duration": "9:00-9:30", "prompt": "Call to action - subscribe, like, comment"},
                    {"name": "Outro", "duration": "9:30-10:00", "prompt": "End screen and goodbye"}
                ]
            },
            "review": {
                "sections": [
                    {"name": "Hook", "duration": "0:00-0:20", "prompt": "What are we reviewing?"},
                    {"name": "Overview", "duration": "0:20-1:00", "prompt": "Product/topic overview"},
                    {"name": "Pros", "duration": "1:00-3:00", "prompt": "Positive aspects"},
                    {"name": "Cons", "duration": "3:00-4:00", "prompt": "Negative aspects"},
                    {"name": "Verdict", "duration": "4:00-5:00", "prompt": "Final recommendation"},
                    {"name": "CTA", "duration": "5:00-5:30", "prompt": "Call to action"}
                ]
            },
            "listicle": {
                "sections": [
                    {"name": "Hook", "duration": "0:00-0:15", "prompt": "Tease the list"},
                    {"name": "Items", "duration": "0:15-8:00", "prompt": "The numbered list items"},
                    {"name": "Conclusion", "duration": "8:00-9:00", "prompt": "Wrap up and CTA"}
                ]
            }
        }

    def generate_script(self, topic: str, template_type: str = "tutorial",
                        duration: int = 10) -> Dict[str, Any]:
        template = self.templates.get(template_type, self.templates["tutorial"])
        script_sections = []
        for section in template["sections"]:
            script_sections.append({
                "name": section["name"],
                "duration": section["duration"],
                "prompt": section["prompt"],
                "script": f"[Write {section['name'].lower()} content for: {topic}]"
            })

        return {
            "topic": topic, "type": template_type, "estimated_duration": f"{duration} min",
            "sections": script_sections, "created": datetime.now().isoformat()
        }

    def format_script(self, script: Dict[str, Any]) -> str:
        lines = [f"# Video Script: {script['topic']}", f"Type: {script['type']}", f"Duration: {script['estimated_duration']}", ""]
        for section in script.get("sections", []):
            lines.append(f"## {section['name']} ({section['duration']})")
            lines.append(f"Prompt: {section['prompt']}")
            lines.append(f"Script: {section['script']}")
            lines.append("")
        return "\n".join(lines)

    def generate_outline(self, topic: str, template_type: str = "tutorial") -> Dict[str, Any]:
        template = self.templates.get(template_type, self.templates["tutorial"])
        outline = {"topic": topic, "type": template_type, "points": []}
        for section in template["sections"]:
            outline["points"].append({"section": section["name"], "key_points": [section["prompt"]]})
        return outline


def main():
    import sys
    writer = ScriptWriter()

    if len(sys.argv) < 2:
        print("Script Writer")
        print("=" * 40)
        print("\nCommands:")
        print("  script <topic> [type]  - Generate script")
        print("  outline <topic> [type] - Generate outline")
        print("  types                  - Script types")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "script" and len(sys.argv) >= 3:
        stype = sys.argv[3] if len(sys.argv) > 3 else "tutorial"
        script = writer.generate_script(sys.argv[2], stype)
        print(writer.format_script(script))
    elif cmd == "outline" and len(sys.argv) >= 3:
        stype = sys.argv[3] if len(sys.argv) > 3 else "tutorial"
        outline = writer.generate_outline(sys.argv[2], stype)
        for point in outline["points"]:
            print(f"  {point['section']}: {point['key_points'][0]}")
    elif cmd == "types":
        for t in writer.templates:
            print(f"  {t}: {len(writer.templates[t]['sections'])} sections")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
