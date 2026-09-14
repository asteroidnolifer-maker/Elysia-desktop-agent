#!/usr/bin/env python3
"""
YouTube Comment Moderation for Elysia
Auto-moderate and manage video comments.
"""
import json
import re
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class CommentModerator:
    """Auto-moderate YouTube comments."""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or Path(__file__).parent / "moderation_config.json"
        self.config = self._load_config()
        self.log_path = Path(__file__).parent / "moderation_log.json"

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {
            "blocked_words": ["spam", "scam", "buy now", "click here", "free money"],
            "blocked_patterns": [r"https?://\S+", r"\b\d{10,}\b", r"DM me"],
            "auto_approve": True,
            "max_links": 3,
            "min_length": 5,
            "response_templates": {
                "spam": "Comment removed: spam detected",
                "promotional": "Comment removed: promotional content",
                "toxic": "Comment removed: violates community guidelines"
            }
        }

    def moderate_comment(self, comment_text: str, author: str = "") -> Dict[str, Any]:
        result = {
            "text": comment_text, "author": author, "action": "approve",
            "reasons": [], "timestamp": datetime.now().isoformat()
        }

        text_lower = comment_text.lower()
        for word in self.config.get("blocked_words", []):
            if word in text_lower:
                result["action"] = "reject"
                result["reasons"].append(f"blocked_word: {word}")

        for pattern in self.config.get("blocked_patterns", []):
            if re.search(pattern, comment_text):
                result["action"] = "reject"
                result["reasons"].append(f"blocked_pattern: {pattern}")

        link_count = len(re.findall(r'https?://\S+', comment_text))
        if link_count > self.config.get("max_links", 3):
            result["action"] = "reject"
            result["reasons"].append(f"too_many_links: {link_count}")

        if len(comment_text) < self.config.get("min_length", 5):
            result["action"] = "reject"
            result["reasons"].append("too_short")

        self._log_moderation(result)
        return result

    def batch_moderate(self, comments: List[Dict[str, str]]) -> Dict[str, Any]:
        results = {"approved": 0, "rejected": 0, "details": []}
        for comment in comments:
            result = self.moderate_comment(comment.get("text", ""), comment.get("author", ""))
            results["details"].append(result)
            if result["action"] == "approve":
                results["approved"] += 1
            else:
                results["rejected"] += 1
        return results

    def _log_moderation(self, result: Dict[str, Any]):
        log = []
        if self.log_path.exists():
            log = json.loads(self.log_path.read_text())
        log.append(result)
        self.log_path.write_text(json.dumps(log[-1000:], indent=2))

    def generate_response(self, comment_text: str, tone: str = "friendly") -> str:
        templates = {
            "friendly": ["Thanks for watching!", "Great comment!", "Appreciate the feedback!"],
            "professional": ["Thank you for your comment.", "We appreciate your feedback."],
            "casual": ["Thanks!", "Glad you liked it!", "Appreciate it!"]
        }
        import random
        return random.choice(templates.get(tone, templates["friendly"]))

    def get_stats(self) -> Dict[str, Any]:
        if not self.log_path.exists():
            return {"total": 0, "approved": 0, "rejected": 0}
        log = json.loads(self.log_path.read_text())
        approved = sum(1 for l in log if l.get("action") == "approve")
        return {"total": len(log), "approved": approved, "rejected": len(log) - approved}


class ResponseTemplates:
    """Pre-built response templates for common comments."""

    TEMPLATES = {
        "thank_you": ["Thanks for watching!", "Glad you enjoyed it!", "Appreciate the support!"],
        "question": ["Great question! I'll cover this in a future video.", "Thanks for asking! Check the description for more info."],
        "feedback": ["Thanks for the feedback!", "Really appreciate your thoughts!"],
        "negative": ["Sorry to hear that. What could I improve?", "Thanks for the honest feedback."]
    }

    @classmethod
    def get_response(cls, category: str) -> str:
        import random
        templates = cls.TEMPLATES.get(category, cls.TEMPLATES["thank_you"])
        return random.choice(templates)


def main():
    import sys
    mod = CommentModerator()

    if len(sys.argv) < 2:
        print("Comment Moderation")
        print("=" * 40)
        print("\nCommands:")
        print("  check <text>   - Moderate a comment")
        print("  stats          - Moderation stats")
        print("  response <category> - Get response template")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "check" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        result = mod.moderate_comment(text)
        print(f"Action: {result['action']}")
        if result["reasons"]:
            print(f"Reasons: {', '.join(result['reasons'])}")
    elif cmd == "stats":
        stats = mod.get_stats()
        print(f"Total: {stats['total']}, Approved: {stats['approved']}, Rejected: {stats['rejected']}")
    elif cmd == "response" and len(sys.argv) >= 3:
        print(ResponseTemplates.get_response(sys.argv[2]))
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
