"""
Distributed cache interface: Abstract caching layer with local and pluggable remote implementations.

Supports versioning (prompt_version, model_name) in cache keys for safe rollbacks.
"""
from abc import ABC, abstractmethod
from typing import Optional
import hashlib
import json
import time
from pathlib import Path


# Default TTL values (seconds)
DEFAULT_TTL = {
    "vision": 72 * 3600,      # 72 hours - vision outputs are expensive
    "usda": 7 * 24 * 3600,    # 7 days - USDA data is stable
    "brand_size": 30 * 24 * 3600,  # 30 days - brand portions rarely change
    "default": 24 * 3600      # 24 hours - fallback
}


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    def get(self, key: str) -> Optional[dict]:
        """Retrieve value from cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        """Store value in cache with optional TTL (seconds)."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete key from cache."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""
        pass


class LocalFileCache(CacheBackend):
    """Local filesystem cache implementation."""

    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _emit_cache_metric(self, backend: str, hit: bool, reason: str = ""):
        """Emit cache metrics for observability."""
        metric = {
            "event": "cache",
            "backend": backend,
            "hit": hit
        }
        if reason:
            metric["reason"] = reason
        print(f"METRICS: {json.dumps(metric)}")

    def _key_to_path(self, key: str) -> Path:
        """Convert cache key to filesystem path."""
        # Hash key to avoid filesystem issues with special chars
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str) -> Optional[dict]:
        """Retrieve value from local file cache with TTL check."""
        cache_path = self._key_to_path(key)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # Check TTL if present
                    ttl = data.get("ttl")
                    created_at = data.get("created_at", 0)
                    if ttl and created_at:
                        age = time.time() - created_at
                        if age > ttl:
                            print(f"DEBUG: Cache expired for key {key[:32]}... (age: {age:.0f}s, ttl: {ttl}s)")
                            cache_path.unlink()  # Delete expired entry
                            self._emit_cache_metric("local", False, "expired")
                            return None

                    self._emit_cache_metric("local", True)
                    return data.get("value")
            except Exception as e:
                print(f"WARNING: Failed to load cache for key {key[:32]}...: {e}")
                self._emit_cache_metric("local", False, "error")
                return None

        self._emit_cache_metric("local", False, "miss")
        return None

    def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        """Store value in local file cache with TTL timestamp."""
        cache_path = self._key_to_path(key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "key": key,
                    "value": value,
                    "ttl": ttl,
                    "created_at": time.time()
                }, f, indent=2)
        except Exception as e:
            print(f"WARNING: Failed to write cache for key {key[:32]}...: {e}")

    def delete(self, key: str) -> None:
        """Delete key from local file cache."""
        cache_path = self._key_to_path(key)
        if cache_path.exists():
            cache_path.unlink()

    def clear(self) -> None:
        """Clear all local cache files."""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)


class RedisCache(CacheBackend):
    """Redis cache implementation (pluggable, requires redis-py)."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, prefix: str = "calorie_estimator"):
        try:
            import redis
            self.client = redis.Redis(host=host, port=port, db=db, decode_responses=False)
            self.prefix = prefix
            print(f"INFO: Redis cache initialized at {host}:{port}")
        except ImportError:
            raise ImportError("redis-py not installed. Run: pip install redis")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Redis: {e}")

    def _emit_cache_metric(self, backend: str, hit: bool, reason: str = ""):
        """Emit cache metrics for observability."""
        metric = {
            "event": "cache",
            "backend": backend,
            "hit": hit
        }
        if reason:
            metric["reason"] = reason
        print(f"METRICS: {json.dumps(metric)}")

    def _prefixed_key(self, key: str) -> str:
        """Add prefix to cache key."""
        return f"{self.prefix}:{key}"

    def get(self, key: str) -> Optional[dict]:
        """Retrieve value from Redis."""
        try:
            data = self.client.get(self._prefixed_key(key))
            if data:
                self._emit_cache_metric("redis", True)
                return json.loads(data)
            self._emit_cache_metric("redis", False, "miss")
            return None
        except Exception as e:
            print(f"WARNING: Redis get failed for key {key[:32]}...: {e}")
            self._emit_cache_metric("redis", False, "error")
            return None

    def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        """Store value in Redis with optional TTL."""
        try:
            serialized = json.dumps(value)
            if ttl:
                self.client.setex(self._prefixed_key(key), ttl, serialized)
            else:
                self.client.set(self._prefixed_key(key), serialized)
        except Exception as e:
            print(f"WARNING: Redis set failed for key {key[:32]}...: {e}")

    def delete(self, key: str) -> None:
        """Delete key from Redis."""
        try:
            self.client.delete(self._prefixed_key(key))
        except Exception as e:
            print(f"WARNING: Redis delete failed for key {key[:32]}...: {e}")

    def clear(self) -> None:
        """Clear all keys with this prefix from Redis."""
        try:
            pattern = f"{self.prefix}:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
        except Exception as e:
            print(f"WARNING: Redis clear failed: {e}")


# Global cache instance (configurable via environment)
_cache_backend: Optional[CacheBackend] = None


def get_cache_backend() -> CacheBackend:
    """Get the configured cache backend (lazy initialization) with Redis resilience."""
    global _cache_backend
    if _cache_backend is None:
        import os
        cache_type = os.getenv("CACHE_BACKEND", "local")

        if cache_type == "redis":
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            try:
                _cache_backend = RedisCache(host=redis_host, port=redis_port)
                print(f"INFO: Redis cache backend initialized successfully")
            except (ImportError, ConnectionError) as e:
                # Auto-fallback to LocalFileCache on Redis failure
                print(f"WARNING: Redis initialization failed: {e}")
                print(f"INFO: Falling back to LocalFileCache")
                print(f"METRICS: {json.dumps({'event': 'cache_fallback', 'from': 'redis', 'to': 'local', 'reason': str(e)[:100]})}")
                _cache_backend = LocalFileCache(cache_dir="cache")
        else:
            _cache_backend = LocalFileCache(cache_dir="cache")

    return _cache_backend


def build_cache_key(prefix: str, model_name: str, prompt_version: str, **kwargs) -> str:
    """
    Build versioned cache key with model/prompt version.

    Args:
        prefix: Cache key prefix (e.g., "vision", "usda", "brand_size")
        model_name: Model name for versioning
        prompt_version: Prompt version (git hash) for versioning
        **kwargs: Additional key components

    Returns:
        Versioned cache key
    """
    # Sort kwargs for consistent key ordering
    key_parts = [prefix, model_name, prompt_version]
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")

    return ":".join(key_parts)
