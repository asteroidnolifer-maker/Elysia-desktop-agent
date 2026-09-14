#!/usr/bin/env python3
"""Scenario engine - handles thousands of different task types automatically."""
import json
import os
import sqlite3
import requests
import subprocess
from datetime import datetime

WORKSPACE = "/data/elysia/workspace/tools"
SCENARIOS_DB = "/data/elysia/workspace/scenarios.sqlite"


SCENARIO_HANDLERS = {
    # Stock & Finance
    "stock_analysis": {"module": "web_research", "action": "search_and_fetch", "template": "{ticker} stock analysis today"},
    "stock_price": {"module": "web_research", "action": "search_and_fetch", "template": "{ticker} current stock price"},
    "earnings_report": {"module": "web_research", "action": "search_and_fetch", "template": "{company} earnings report {quarter}"},
    "crypto_price": {"module": "web_research", "action": "search_and_fetch", "template": "{coin} cryptocurrency price today"},
    "market_news": {"module": "web_research", "action": "search_and_fetch", "template": "stock market news today"},
    # YouTube
    "youtube_trending": {"module": "youtube_research", "action": "search_youtube_trending", "template": "{category}"},
    "youtube_ideas": {"module": "youtube_research", "action": "generate_shorts_ideas", "template": "{niche}"},
    "youtube_script": {"module": "video_generator", "action": "generate_script", "template": "{topic}"},
    "youtube_video": {"module": "video_generator", "action": "create_video_pipeline", "template": "{topic}"},
    # Web Research
    "web_search": {"module": "web_research", "action": "search_and_fetch", "template": "{query}"},
    "competitor_research": {"module": "web_research", "action": "search_and_fetch", "template": "competitors of {company} analysis"},
    "product_research": {"module": "web_research", "action": "search_and_fetch", "template": "{product} review and price comparison"},
    # Content Creation
    "blog_post": {"module": "agent_commander", "action": "call_local_llm", "template": "Write a blog post about {topic}"},
    "social_post": {"module": "agent_commander", "action": "call_local_llm", "template": "Write a social media post about {topic}"},
    "email_campaign": {"module": "agent_commander", "action": "call_local_llm", "template": "Write a marketing email about {topic}"},
    # Automation
    "auto_video_pipeline": {"module": "video_generator", "action": "create_video_pipeline", "template": "{topic}"},
    "bulk_youtube": {"module": "youtube_scheduler", "action": "bulk_schedule", "template": "{topics}"},
    # Code & Dev
    "code_review": {"module": "agent_commander", "action": "call_local_llm", "template": "Review this code: {code}"},
    "code_generate": {"module": "agent_commander", "action": "call_local_llm", "template": "Write code for: {description}"},
    "debug_code": {"module": "agent_commander", "action": "call_local_llm", "template": "Debug this error: {error}"},
}


def init_scenarios_db():
    """Initialize scenarios database."""
    conn = sqlite3.connect(SCENARIOS_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scenarios (
        id INTEGER PRIMARY KEY, scenario_type TEXT, params TEXT,
        status TEXT DEFAULT 'pending', result TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS scenario_log (
        id INTEGER PRIMARY KEY, scenario_id INTEGER, action TEXT,
        details TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn


def detect_scenario_type(user_input):
    """Detect what type of scenario this is from natural language."""
    input_lower = user_input.lower()
    patterns = {
        "stock_analysis": ["analyze", "analysis", "stock", "ticker", "buy", "sell"],
        "stock_price": ["price", "current price", "how much", "trading at"],
        "youtube_trending": ["trending", "youtube trending", "what's popular"],
        "youtube_ideas": ["ideas", "youtube ideas", "shorts ideas", "video ideas"],
        "youtube_script": ["script", "youtube script", "write script"],
        "youtube_video": ["create video", "make video", "generate video", "produce video"],
        "web_search": ["search", "find", "look up", "google", "research"],
        "competitor_research": ["competitor", "competition", "rival"],
        "product_research": ["product", "review", "comparison", "best"],
        "blog_post": ["blog", "article", "write about", "post about"],
        "social_post": ["social media", "tweet", "instagram", "facebook post"],
        "code_review": ["review code", "code review", "check code"],
        "code_generate": ["write code", "create script", "code for", "program"],
    }
    detected = []
    for scenario_type, keywords in patterns.items():
        if any(kw in input_lower for kw in keywords):
            detected.append(scenario_type)
    return detected[0] if detected else "web_search"


def extract_params(user_input, scenario_type):
    """Extract parameters from user input."""
    params = {}
    # Try to extract stock tickers
    import re
    tickers = re.findall(r'\b[A-Z]{2,5}\b', user_input)
    if tickers and "stock" in scenario_type:
        params["ticker"] = tickers[0]
    # Try to extract topics
    words = user_input.split()
    for stop in ["about", "for", "on", "of", "the", "a", "an", "to", "in", "is"]:
        if stop in words:
            idx = words.index(stop)
            params["topic"] = " ".join(words[idx+1:idx+4])
            break
    if "topic" not in params:
        params["topic"] = user_input[:50]
    # Specific extractions
    if "query" in str(SCENARIO_HANDLERS.get(scenario_type, {})):
        params["query"] = user_input
    return params


def execute_scenario(scenario_type, params):
    """Execute a scenario with given parameters."""
    handler = SCENARIO_HANDLERS.get(scenario_type)
    if not handler:
        return {"error": f"Unknown scenario type: {scenario_type}"}
    try:
        if handler["module"] == "web_research":
            from web_research import search_and_fetch
            query = handler["template"].format(**params)
            return search_and_fetch(query, 5)
        elif handler["module"] == "youtube_research":
            from youtube_research import search_youtube_trending, generate_shorts_ideas
            if "trending" in handler["action"]:
                return search_youtube_trending(params.get("category", "general"))
            else:
                trending = search_youtube_trending(params.get("niche", "general"))
                return generate_shorts_ideas(trending, params.get("niche", "general"))
        elif handler["module"] == "video_generator":
            from video_generator import generate_script, create_video_pipeline
            topic = params.get("topic", "general topic")
            if "script" in handler["action"]:
                return generate_script(topic)
            else:
                return create_video_pipeline(topic)
        elif handler["module"] == "agent_commander":
            from agent_commander import call_local_llm
            prompt = handler["template"].format(**params)
            return call_local_llm(prompt)
        elif handler["module"] == "youtube_scheduler":
            from youtube_scheduler import bulk_schedule
            return bulk_schedule(params.get("channel_ids", [1]), [params.get("topic", "General")])
    except Exception as e:
        return {"error": str(e), "scenario": scenario_type}


def process_natural_request(user_input):
    """Process a natural language request end-to-end."""
    scenario_type = detect_scenario_type(user_input)
    params = extract_params(user_input, scenario_type)
    conn = init_scenarios_db()
    c = conn.cursor()
    c.execute("INSERT INTO scenarios (scenario_type, params) VALUES (?, ?)",
              (scenario_type, json.dumps(params)))
    scenario_id = c.lastrowid
    conn.commit()
    result = execute_scenario(scenario_type, params)
    c.execute("UPDATE scenarios SET status='done', result=?, completed_at=? WHERE id=?",
              (json.dumps(result, default=str), datetime.now().isoformat(), scenario_id))
    conn.commit()
    conn.close()
    return {"scenario_id": scenario_id, "type": scenario_type, "params": params, "result": result}


if __name__ == "__main__":
    print("=== Scenario Engine Test ===")
    test_requests = [
        "What's Apple stock price right now?",
        "Find trending YouTube Shorts ideas for tech",
        "Search for best AI tools 2026",
        "Create a video about making money online",
    ]
    for req in test_requests:
        print(f"\n> {req}")
        result = process_natural_request(req)
        print(f"  Type: {result['type']}")
        print(f"  Params: {result['params']}")
        if 'error' in result['result']:
            print(f"  Error: {result['result']['error']}")
        else:
            print(f"  Results: {len(result['result'].get('search_results', result['result'].get('trending_videos', result['result'].get('ideas', []))))} items")
    output = os.path.join(WORKSPACE, "scenario_results.json")
    with open(output, "w") as f:
        json.dump({"test_results": [process_natural_request(r) for r in test_requests]}, f, indent=2, default=str)
    print(f"\n[+] Saved to {output}")
