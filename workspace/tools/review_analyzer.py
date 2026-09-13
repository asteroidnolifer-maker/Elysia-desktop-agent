#!/usr/bin/env python3
"""Task #1457: Review analyzer for quality assessment."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

POSITIVE = set(["great", "excellent", "good", "love", "perfect", "amazing", "fast", "quality", "recommend", "best"])
NEGATIVE = set(["bad", "terrible", "poor", "broken", "slow", "cheap", "worst", "refund", "disappointed", "fake"])

def analyze_reviews(reviews):
    """Analyze product reviews for quality assessment."""
    sentiments = []
    for r in reviews:
        words = set(r.lower().split())
        pos = len(words & POSITIVE)
        neg = len(words & NEGATIVE)
        score = (pos - neg) / max(pos + neg, 1)
        sentiments.append({"review": r[:100], "score": round(score, 2), "label": "positive" if score > 0 else "negative" if score < 0 else "neutral"})
    avg_score = sum(s["score"] for s in sentiments) / len(sentiments) if sentiments else 0
    return {
        "total_reviews": len(reviews),
        "average_sentiment": round(avg_score, 3),
        "positive_pct": round(sum(1 for s in sentiments if s["label"] == "positive") / len(sentiments) * 100, 1),
        "quality_assessment": "excellent" if avg_score > 0.5 else "good" if avg_score > 0.2 else "average" if avg_score > -0.2 else "poor",
        "recommendation": "sell" if avg_score > 0.3 else "caution" if avg_score > -0.1 else "avoid"
    }

if __name__ == "__main__":
    reviews = ["Great product, works perfectly!", "Terrible quality, broke after 1 day", "Good value for money", "Fast shipping, recommend!", "Cheap material, disappointed"]
    result = analyze_reviews(reviews)
    print(f"Review Analysis: {result['quality_assessment']} ({result['average_sentiment']})")
    print(f"Positive: {result['positive_pct']}% | Recommendation: {result['recommendation']}")
    output = os.path.join(WORKSPACE, "review_analysis.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
