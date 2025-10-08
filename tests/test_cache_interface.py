"""
Unit tests for cache interface (P2-C).

Tests local and Redis cache backends, TTL handling, metrics, and resilience.
"""
import pytest
import json
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from core.cache_interface import (
    LocalFileCache,
    RedisCache,
    get_cache_backend,
    build_cache_key,
    DEFAULT_TTL
)


class TestLocalFileCache:
    """Test LocalFileCache implementation."""

    def setup_method(self):
        """Setup temp cache dir for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = LocalFileCache(cache_dir=self.temp_dir)

    def teardown_method(self):
        """Cleanup temp cache dir."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_set_and_get_basic(self):
        """Test basic set and get operations."""
        test_data = {"foo": "bar", "count": 42}
        self.cache.set("test_key", test_data)

        result = self.cache.get("test_key")
        assert result == test_data

    def test_get_nonexistent_key(self):
        """Test getting non-existent key returns None."""
        result = self.cache.get("nonexistent")
        assert result is None

    def test_ttl_expiration(self):
        """Test TTL expiration with LocalFileCache."""
        test_data = {"temp": "data"}
        # Set with 1 second TTL
        self.cache.set("expiring_key", test_data, ttl=1)

        # Should exist immediately
        result = self.cache.get("expiring_key")
        assert result == test_data

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired now
        result = self.cache.get("expiring_key")
        assert result is None

    def test_delete_key(self):
        """Test deleting a key."""
        self.cache.set("delete_me", {"data": "value"})
        assert self.cache.get("delete_me") is not None

        self.cache.delete("delete_me")
        assert self.cache.get("delete_me") is None

    def test_clear_cache(self):
        """Test clearing all cache entries."""
        self.cache.set("key1", {"val": 1})
        self.cache.set("key2", {"val": 2})

        self.cache.clear()

        assert self.cache.get("key1") is None
        assert self.cache.get("key2") is None

    def test_cache_hit_metrics(self, capsys):
        """Test cache hit metrics emission."""
        self.cache.set("metrics_key", {"test": "data"})
        self.cache.get("metrics_key")

        captured = capsys.readouterr()
        assert "METRICS:" in captured.out
        assert '"event": "cache"' in captured.out
        assert '"hit": true' in captured.out

    def test_cache_miss_metrics(self, capsys):
        """Test cache miss metrics emission."""
        self.cache.get("missing_key")

        captured = capsys.readouterr()
        assert "METRICS:" in captured.out
        assert '"event": "cache"' in captured.out
        assert '"hit": false' in captured.out


class TestRedisCache:
    """Test RedisCache implementation (with mocking)."""

    @patch('redis.Redis')
    def test_redis_set_and_get(self, mock_redis_class):
        """Test Redis set and get operations."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client

        cache = RedisCache()
        test_data = {"redis": "test"}

        # Test set
        cache.set("redis_key", test_data)
        mock_client.set.assert_called()

        # Test get (mock return value)
        mock_client.get.return_value = json.dumps(test_data).encode()
        result = cache.get("redis_key")
        assert result == test_data

    @patch('redis.Redis')
    def test_redis_ttl_handling(self, mock_redis_class):
        """Test Redis TTL is passed to setex."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client

        cache = RedisCache()
        cache.set("ttl_key", {"data": "value"}, ttl=3600)

        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[1] == 3600  # TTL in seconds

    @patch('redis.Redis')
    def test_redis_connection_failure(self, mock_redis_class):
        """Test Redis connection failure raises ConnectionError."""
        mock_redis_class.side_effect = ConnectionError("Redis unreachable")

        with pytest.raises(ConnectionError):
            RedisCache()


class TestCacheBackendFactory:
    """Test cache backend factory and resilience."""

    def teardown_method(self):
        """Reset global cache backend."""
        import core.cache_interface
        core.cache_interface._cache_backend = None

    @patch.dict('os.environ', {'CACHE_BACKEND': 'local'})
    def test_local_backend_selection(self):
        """Test local backend is selected from env."""
        backend = get_cache_backend()
        assert isinstance(backend, LocalFileCache)

    @patch.dict('os.environ', {'CACHE_BACKEND': 'redis', 'REDIS_HOST': 'localhost'})
    @patch('redis.Redis')
    def test_redis_backend_selection(self, mock_redis):
        """Test Redis backend is selected from env."""
        mock_redis.return_value = MagicMock()
        backend = get_cache_backend()
        assert isinstance(backend, RedisCache)

    @patch.dict('os.environ', {'CACHE_BACKEND': 'redis'})
    @patch('redis.Redis')
    def test_redis_fallback_on_failure(self, mock_redis, capsys):
        """Test auto-fallback to LocalFileCache when Redis fails."""
        mock_redis.side_effect = ConnectionError("Can't connect")

        backend = get_cache_backend()

        # Should fallback to LocalFileCache
        assert isinstance(backend, LocalFileCache)

        # Should emit fallback metric
        captured = capsys.readouterr()
        assert "cache_fallback" in captured.out
        assert '"from": "redis"' in captured.out
        assert '"to": "local"' in captured.out


class TestCacheKeyBuilder:
    """Test cache key building with versioning."""

    def test_basic_key_building(self):
        """Test basic cache key construction."""
        key = build_cache_key(
            prefix="vision",
            model_name="gemini-2.5-flash",
            prompt_version="abc123"
        )
        assert "vision" in key
        assert "gemini-2.5-flash" in key
        assert "abc123" in key

    def test_key_with_kwargs(self):
        """Test cache key with additional parameters."""
        key = build_cache_key(
            prefix="usda",
            model_name="gemini-2.5-flash",
            prompt_version="abc123",
            image_hash="deadbeef",
            query="chicken"
        )
        assert "usda" in key
        assert "image_hash=deadbeef" in key
        assert "query=chicken" in key

    def test_key_ordering_consistency(self):
        """Test that kwargs are sorted for consistent keys."""
        key1 = build_cache_key(
            prefix="test",
            model_name="model",
            prompt_version="v1",
            param_a="foo",
            param_b="bar"
        )
        key2 = build_cache_key(
            prefix="test",
            model_name="model",
            prompt_version="v1",
            param_b="bar",
            param_a="foo"
        )
        assert key1 == key2


class TestTTLDefaults:
    """Test TTL default values."""

    def test_ttl_defaults_exist(self):
        """Test that TTL defaults are defined."""
        assert "vision" in DEFAULT_TTL
        assert "usda" in DEFAULT_TTL
        assert "brand_size" in DEFAULT_TTL
        assert "default" in DEFAULT_TTL

    def test_ttl_values_reasonable(self):
        """Test TTL values are in reasonable ranges."""
        assert DEFAULT_TTL["vision"] == 72 * 3600  # 72 hours
        assert DEFAULT_TTL["usda"] == 7 * 24 * 3600  # 7 days
        assert DEFAULT_TTL["brand_size"] == 30 * 24 * 3600  # 30 days
        assert DEFAULT_TTL["default"] == 24 * 3600  # 24 hours
