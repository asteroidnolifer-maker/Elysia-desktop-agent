#!/usr/bin/env python3
"""Task #23: Sentiment analyzer from news."""
import json, os, re

WORKSPACE = "/data/elysia/workspace/tools"

POSITIVE_WORDS = set(["surge", "rally", "gain", "profit", "growth", "beat", "exceed", "upgrade", "buy", "bullish", "strong", "record", "high", "boom", "soar", "jump", "rise", "outperform", "breakout", "momentum"])
NEGATIVE_WORDS = set(["crash", "drop", "fall", "loss", "decline", "miss", "downgrade", "sell", "bearish", "weak", "low", "bust", "plunge", "sink", "tumble", "underperform", "breakdown", "recession", "default", "bankruptcy"])

def analyze_sentiment(text):
    """Analyze sentiment of financial news text."""
    words = re.findall(r'\w+', text.lower())
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        score = 0
    else:
        score = (pos - neg) / total
    return {
        "score": round(score, 3),
        "label": "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral",
        "positive_words": pos,
        "negative_words": neg,
        "confidence": round(abs(score), 3)
    }

def analyze_headlines(headlines):
    """Analyze sentiment of multiple headlines."""
    results = [analyze_sentiment(h) for h in headlines]
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    return {
        "individual": results,
        "average_score": round(avg_score, 3),
        "overall": "positive" if avg_score > 0.15 else "negative" if avg_score < -0.15 else "neutral",
        "bullish_count": sum(1 for r in results if r["label"] == "positive"),
        "bearish_count": sum(1 for r in results if r["label"] == "negative"),
    }

if __name__ == "__main__":
    headlines = [
        "Stock surges to record high on strong earnings beat",
        "Company reports unexpected loss, shares tumble",
        "Analyst upgrades stock to buy with bullish outlook",
        "Market crashes amid recession fears",
        "Revenue growth exceeds expectations, stock rallies",
    ]
    result = analyze_headlines(headlines)
    print("News Sentiment Analysis:")
    for i, h in enumerate(headlines):
        print(f"  {result['individual'][i]['label']:>8}: {h[:60]}")
    print(f"\n  Overall: {result['overall']} (score: {result['average_score']})")
    print(f"  Bullish: {result['bullish_count']}, Bearish: {result['bearish_count']}")
    output = os.path.join(WORKSPACE, "sentiment_analysis.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
