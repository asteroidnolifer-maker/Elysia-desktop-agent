#!/usr/bin/env python3
"""
Composio Manager for Elysia
Core Composio infrastructure: auth, rate limiting, retry, caching, logging.
"""
import os
import json
import time
import hashlib
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("composio_manager")


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_calls: int = 60, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls: List[float] = []

    def wait_if_needed(self):
        now = time.time()
        self.calls = [c for c in self.calls if now - c < self.period]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0]) + 0.1
            logger.info(f"Rate limit hit, sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self.calls.append(time.time())


class ComposioCache:
    """Simple file-based cache for API responses."""

    def __init__(self, cache_dir: Path = None, ttl: int = 300):
        self.cache_dir = cache_dir or Path(__file__).parent / ".cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl = ttl

    def _key(self, namespace: str, params: Dict[str, Any]) -> str:
        raw = f"{namespace}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, namespace: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = self._key(namespace, params)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if time.time() - data.get("time", 0) < self.ttl:
                    return data.get("result")
            except Exception:
                pass
        return None

    def set(self, namespace: str, params: Dict[str, Any], result: Any):
        key = self._key(namespace, params)
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps({"time": time.time(), "result": result}))

    def clear(self):
        for f in self.cache_dir.glob("*.json"):
            f.unlink()


class RetryHandler:
    """Exponential backoff retry handler."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def execute_with_retry(self, func, *args, **kwargs):
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s")
                time.sleep(delay)
        raise last_exception


class TokenManager:
    """OAuth token management with automatic refresh."""

    def __init__(self, token_path: Path = None):
        self.token_path = token_path or Path(__file__).parent / ".tokens.json"
        self.tokens: Dict[str, Dict[str, Any]] = self._load_tokens()

    def _load_tokens(self) -> Dict[str, Any]:
        if self.token_path.exists():
            return json.loads(self.token_path.read_text())
        return {}

    def _save_tokens(self):
        self.token_path.write_text(json.dumps(self.tokens, indent=2))

    def store_token(self, service: str, access_token: str, refresh_token: str = None, expires_in: int = 3600):
        self.tokens[service] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (datetime.now() + timedelta(seconds=expires_in)).isoformat(),
            "stored_at": datetime.now().isoformat()
        }
        self._save_tokens()
        logger.info(f"Token stored for {service}")

    def get_token(self, service: str) -> Optional[str]:
        token_data = self.tokens.get(service)
        if not token_data:
            return None
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        if datetime.now() >= expires_at:
            logger.warning(f"Token expired for {service}")
            return None
        return token_data.get("access_token")

    def is_valid(self, service: str) -> bool:
        return self.get_token(service) is not None

    def revoke_token(self, service: str):
        if service in self.tokens:
            del self.tokens[service]
            self._save_tokens()
            logger.info(f"Token revoked for {service}")


class ComposioErrorHandler:
    """Centralized error handling for Composio operations."""

    ERROR_MESSAGES = {
        401: "Authentication failed - check API key",
        403: "Permission denied - check integration scope",
        404: "Resource not found",
        429: "Rate limit exceeded",
        500: "Server error - try again later",
        503: "Service unavailable",
    }

    @staticmethod
    def handle_error(error: Exception, context: str = "") -> Dict[str, Any]:
        error_str = str(error)
        logger.error(f"Composio error [{context}]: {error_str}")

        if "401" in error_str:
            return {"success": False, "error": "Authentication failed", "action": "check_api_key"}
        elif "429" in error_str:
            return {"success": False, "error": "Rate limited", "action": "wait_and_retry"}
        elif "timeout" in error_str.lower():
            return {"success": False, "error": "Request timed out", "action": "retry"}
        else:
            return {"success": False, "error": error_str, "action": "check_logs"}


class ComposioManager:
    """Main Composio configuration and management class."""

    def __init__(self):
        self.api_key = COMPOSIO_API_KEY
        self.rate_limiter = RateLimiter(max_calls=60, period=60)
        self.cache = ComposioCache(ttl=300)
        self.retry = RetryHandler(max_retries=3)
        self.token_manager = TokenManager()
        self.error_handler = ComposioErrorHandler()
        self._toolset = None

    def get_toolset(self):
        if self._toolset is None:
            try:
                from composio import ComposioToolSet
                self._toolset = ComposioToolSet(api_key=self.api_key)
                logger.info("Composio toolset initialized")
            except ImportError:
                logger.error("composio-core not installed")
                return None
            except Exception as e:
                logger.error(f"Failed to initialize: {e}")
                return None
        return self._toolset

    def execute_with_protection(self, tool_name: str, params: Dict[str, Any],
                                 use_cache: bool = False) -> Dict[str, Any]:
        """Execute a tool call with rate limiting, retry, caching, and error handling."""
        self.rate_limiter.wait_if_needed()

        if use_cache:
            cached = self.cache.get(tool_name, params)
            if cached is not None:
                logger.info(f"Cache hit for {tool_name}")
                return {"success": True, "result": cached, "cached": True}

        toolset = self.get_toolset()
        if not toolset:
            return {"success": False, "error": "Toolset not initialized"}

        def _execute():
            return toolset.execute_tool(tool=tool_name, params=params)

        try:
            result = self.retry.execute_with_retry(_execute)
            if use_cache:
                self.cache.set(tool_name, params, result)
            logger.info(f"Executed {tool_name} successfully")
            return {"success": True, "result": result}
        except Exception as e:
            return self.error_handler.handle_error(e, context=tool_name)

    def get_available_apps(self) -> List[str]:
        return ["github", "slack", "notion", "google", "discord", "twitter", "linkedin"]

    def validate_config(self) -> Dict[str, Any]:
        status = {"api_key_set": bool(self.api_key), "apps": {}}
        toolset = self.get_toolset()
        if toolset:
            for app in self.get_available_apps():
                try:
                    tools = toolset.get_tools(app=[app])
                    status["apps"][app] = {"available": True, "tools_count": len(tools)}
                except Exception as e:
                    status["apps"][app] = {"available": False, "error": str(e)}
        return status

    def get_usage_stats(self) -> Dict[str, Any]:
        cache_files = list(self.cache.cache_dir.glob("*.json"))
        return {
            "cache_entries": len(cache_files),
            "rate_limit_remaining": self.rate_limiter.max_calls - len(self.rate_limiter.calls),
            "tokens_stored": list(self.token_manager.tokens.keys()),
            "validated_apps": self.validate_config().get("apps", {})
        }


def get_manager():
    return ComposioManager()


if __name__ == "__main__":
    manager = ComposioManager()
    print("Composio Manager")
    print("=" * 40)
    print(f"API Key: {'SET' if manager.api_key else 'NOT SET'}")
    print(f"Available apps: {', '.join(manager.get_available_apps())}")
    print(f"\nUsage stats: {json.dumps(manager.get_usage_stats(), indent=2)}")
