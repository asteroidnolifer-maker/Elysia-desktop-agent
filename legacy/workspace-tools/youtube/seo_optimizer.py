#!/usr/bin/env python3
"""
YouTube SEO Optimizer for Elysia
Title, description, and tag optimization for YouTube videos.
"""
import json
import re
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class SEOOptimizer:
    """Optimize YouTube video metadata for search."""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or Path(__file__).parent / "seo_config.json"
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {
            "max_title_length": 60,
            "max_description_length": 5000,
            "max_tags": 15,
            "power_words": ["ultimate", "complete", "guide", "tutorial", "how to", "step by step", "beginner", "advanced", "2024", "2025", "2026"],
            "avoid_words": ["clickbait", "shocking", "you won't believe"],
            "keyword_patterns": ["{topic} tutorial", "how to {topic}", "{topic} for beginners", "learn {topic}"]
        }

    def optimize_title(self, title: str, topic: str = "") -> Dict[str, Any]:
        suggestions = []
        optimized = title

        if len(title) > self.config["max_title_length"]:
            optimized = title[:self.config["max_title_length"] - 3] + "..."

        for pattern in self.config.get("keyword_patterns", []):
            if topic:
                suggestions.append(pattern.format(topic=topic))

        has_power = any(w in title.lower() for w in self.config.get("power_words", []))
        has_number = bool(re.search(r'\d', title))
        has_brackets = bool(re.search(r'[\[\(\{]', title))

        score = 0
        if has_power: score += 20
        if has_number: score += 15
        if has_brackets: score += 10
        if len(title) <= self.config["max_title_length"]: score += 15
        if topic and topic.lower() in title.lower(): score += 20
        score = min(score, 100)

        return {
            "original": title, "optimized": optimized, "suggestions": suggestions,
            "score": score, "checks": {
                "length_ok": len(title) <= self.config["max_title_length"],
                "has_power_words": has_power, "has_number": has_number,
                "has_brackets": has_brackets
            }
        }

    def optimize_description(self, description: str, links: List[str] = None) -> Dict[str, Any]:
        optimized = description
        if len(description) > self.config["max_description_length"]:
            optimized = description[:self.config["max_description_length"] - 3] + "..."

        sections = []
        if description:
            first_150 = description[:150]
            sections.append({"name": "Hook", "content": first_150, "purpose": "First impression"})
            sections.append({"name": "Timestamps", "content": "00:00 - Introduction", "purpose": "Navigation"})
            if links:
                links_section = "\n".join(links)
                sections.append({"name": "Links", "content": links_section, "purpose": "Engagement"})

        return {"original_length": len(description), "optimized": optimized, "sections": sections}

    def optimize_tags(self, topic: str, existing_tags: List[str] = None) -> Dict[str, Any]:
        tags = list(existing_tags or [])
        suggested = [
            topic, f"{topic} tutorial", f"how to {topic}",
            f"{topic} 2026", f"{topic} for beginners", f"learn {topic}",
            f"{topic} guide", f"{topic} tips", f"{topic} tricks"
        ]
        tags.extend([t for t in suggested if t not in tags])
        return {"tags": tags[:self.config["max_tags"]], "total": len(tags), "suggested": suggested}

    def generate_metadata(self, topic: str, title: str, description: str) -> Dict[str, Any]:
        return {
            "title": self.optimize_title(title, topic),
            "description": self.optimize_description(description),
            "tags": self.optimize_tags(topic),
            "timestamp": datetime.now().isoformat()
        }


class TagResearch:
    """Research trending tags and keywords."""

    def __init__(self):
        self.niche_tags = {
            "tech": ["programming", "coding", "software", "developer", "python", "javascript", "ai", "machine learning"],
            "finance": ["investing", "stocks", "crypto", "trading", "budget", "money", "financial freedom"],
            "security": ["cybersecurity", "hacking", "ethical hacking", "pentesting", "infosec", "privacy"],
            "youtube": ["youtube tips", "grow youtube", "youtube algorithm", "content creation", "video editing"]
        }

    def get_tags_for_niche(self, niche: str) -> List[str]:
        return self.niche_tags.get(niche, self.niche_tags["tech"])

    def get_trending_format(self) -> List[Dict[str, str]]:
        return [
            {"format": "How to {topic}", "example": "How to Build a Website"},
            {"format": "{topic} in {time}", "example": "Python in 30 Minutes"},
            {"format": "Why {topic}", "example": "Why I Switched to Linux"},
            {"format": "{topic} vs {topic2}", "example": "React vs Vue"},
            {"format": "I Tried {topic} for {time}", "example": "I Tried Fasting for 30 Days"}
        ]


def main():
    import sys
    optimizer = SEOOptimizer()

    if len(sys.argv) < 2:
        print("YouTube SEO Optimizer")
        print("=" * 40)
        print("\nCommands:")
        print("  title <topic> <title>  - Optimize title")
        print("  desc <description>     - Optimize description")
        print("  tags <topic>           - Generate tags")
        print("  full <topic> <title> <desc> - Full metadata")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "title" and len(sys.argv) >= 4:
        result = optimizer.optimize_title(sys.argv[3], sys.argv[2])
        print(f"Score: {result['score']}/100")
        print(f"Suggestions: {result['suggestions'][:3]}")

    elif cmd == "tags" and len(sys.argv) >= 3:
        result = optimizer.optimize_tags(sys.argv[2])
        print(f"Tags ({result['total']}): {', '.join(result['tags'][:10])}")

    elif cmd == "full" and len(sys.argv) >= 5:
        result = optimizer.generate_metadata(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Title score: {result['title']['score']}/100")
        print(f"Tags: {', '.join(result['tags']['tags'][:5])}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
