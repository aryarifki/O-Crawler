"""O-Crawler Unified Two-Tier Cache Layer (In-Memory L1 + Redis L2).

Diadaptasi & disempurnakan dari arsitektur Investowl untuk O-Crawler:
- L1 In-Memory TTLCache dengan thread-safe LRU eviction (0ms latency)
- L2 Redis Cache untuk persistensi dan skalabilitas
- Fallback otomatis ke In-Memory jika Redis offline
- Dekorator @cached serbaguna untuk route sync & async FastAPI
- Invalidation berbasis pattern wildcard (misal 'stats:*', 'data:*')
- Telemetry & diagnostik hit/miss ratio
"""
from __future__ import annotations

import os
import time
import json
import inspect
import hashlib
import fnmatch
from collections import OrderedDict
from threading import Lock
from functools import wraps
from typing import Any, Optional, Callable, Dict, List

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


def _get_shared_redis() -> Optional[Any]:
    """Inisialisasi koneksi Redis dengan timeout aman & fail-soft."""
    if not REDIS_AVAILABLE:
        return None
    try:
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_DB", "0"))
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
            socket_timeout=1.5,
            socket_connect_timeout=1.5,
        )
        client.ping()
        return client
    except Exception:
        return None


class TTLCache:
    """Thread-safe In-Memory Cache dengan TTL expiration dan LRU eviction."""

    def __init__(self, maxsize: int = 512, default_ttl: float = 300.0) -> None:
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[float, float, Any]] = OrderedDict()  # key -> (expire_at, created_at, val)
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                exp, _, val = self._cache[key]
                if time.time() <= exp:
                    self._cache.move_to_end(key)
                    self.hits += 1
                    return val
                else:
                    del self._cache[key]
            self.misses += 1
            return None

    def set(self, key: str, val: Any, ttl_seconds: Optional[float] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        expire_at = now + ttl
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)  # Evict oldest (LRU)
            self._cache[key] = (expire_at, now, val)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def invalidate_by_pattern(self, pattern: str) -> int:
        with self._lock:
            keys_to_del = [k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)]
            for k in keys_to_del:
                del self._cache[k]
            return len(keys_to_del)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


class UnifiedCache:
    """Production Multi-Tier Cache Layer: L1 Memory (0ms) + L2 Redis (Distributed/Persistent)."""

    def __init__(self, prefix: str = "ocrawler") -> None:
        self.prefix = prefix
        self._l1 = TTLCache(maxsize=1024, default_ttl=300.0)
        self._redis = _get_shared_redis()
        self._redis_prefix = f"{prefix}:"

    @property
    def is_redis_available(self) -> bool:
        if self._redis is None:
            self._redis = _get_shared_redis()
        return self._redis is not None

    def get(self, key: str) -> Optional[Any]:
        # 1. Cek L1 In-Memory Cache (0ms)
        val = self._l1.get(key)
        if val is not None:
            return val

        # 2. Cek L2 Redis jika L1 Miss
        if self.is_redis_available and self._redis:
            try:
                rk = f"{self._redis_prefix}{key}"
                raw = self._redis.get(rk)
                if raw is not None:
                    parsed = json.loads(raw)
                    # Back-fill ke L1 dengan TTL 60s agar request beruntun super-cepat
                    self._l1.set(key, parsed, ttl_seconds=60.0)
                    return parsed
            except Exception:
                pass

        return None

    def set(self, key: str, val: Any, ttl_seconds: int = 300) -> bool:
        # Simpan ke L1 In-Memory
        self._l1.set(key, val, ttl_seconds=float(ttl_seconds))

        # Simpan ke L2 Redis
        if self.is_redis_available and self._redis:
            try:
                rk = f"{self._redis_prefix}{key}"
                payload = json.dumps(val, default=str)
                self._redis.set(rk, payload, ex=int(ttl_seconds))
                return True
            except Exception:
                return False
        return True

    def delete(self, key: str) -> bool:
        self._l1.delete(key)
        if self.is_redis_available and self._redis:
            try:
                rk = f"{self._redis_prefix}{key}"
                return bool(self._redis.delete(rk))
            except Exception:
                pass
        return True

    def invalidate_by_pattern(self, pattern: str) -> int:
        """Invalidasi cache L1 dan L2 berdasarkan pattern (misal 'stats:*' atau 'data:*')."""
        count = self._l1.invalidate_by_pattern(pattern)
        if self.is_redis_available and self._redis:
            try:
                full_pattern = f"{self._redis_prefix}{pattern}"
                keys = self._redis.keys(full_pattern)
                if keys:
                    self._redis.delete(*keys)
                    count = max(count, len(keys))
            except Exception:
                pass
        return count

    def clear(self) -> None:
        self._l1.clear()
        if self.is_redis_available and self._redis:
            try:
                keys = self._redis.keys(f"{self._redis_prefix}*")
                if keys:
                    self._redis.delete(*keys)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """Metrik diagnostik status dan efisiensi cache."""
        redis_keys = 0
        connected = self.is_redis_available
        if connected and self._redis:
            try:
                keys = self._redis.keys(f"{self._redis_prefix}*")
                redis_keys = len(keys)
            except Exception:
                connected = False

        total_reqs = self._l1.hits + self._l1.misses
        hit_ratio = round((self._l1.hits / total_reqs * 100), 2) if total_reqs > 0 else 0.0

        return {
            "driver": "Unified (L1 Memory + L2 Redis)" if connected else "In-Memory Fallback (L1)",
            "redis_connected": connected,
            "redis_keys_count": redis_keys,
            "memory_keys_count": len(self._l1),
            "memory_hits": self._l1.hits,
            "memory_misses": self._l1.misses,
            "hit_ratio_percent": hit_ratio,
        }


# Global singleton instance
cache = UnifiedCache(prefix="ocrawler")


def _is_cacheable_arg(v: Any) -> bool:
    """Filter argumen non-primitif (misal Request, Response, DatabaseManager)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, (list, tuple, set)):
        return all(_is_cacheable_arg(x) for x in v)
    if isinstance(v, dict):
        return all(isinstance(k, str) and _is_cacheable_arg(val) for k, val in v.items())
    return False


def build_cache_key(prefix: str, func_name: str, args: tuple, kwargs: dict) -> str:
    """Membangun cache key deterministik berbasis hash SHA-256 dari argumen request."""
    clean_args = [a for a in args if _is_cacheable_arg(a)]
    clean_kwargs = {k: v for k, v in sorted(kwargs.items()) if _is_cacheable_arg(v)}
    serialized = json.dumps({"args": clean_args, "kwargs": clean_kwargs}, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode()).hexdigest()[:12]
    p = f"{prefix}:" if prefix else ""
    return f"{p}{func_name}:{digest}"


def cached(
    ttl_seconds: int = 300,
    prefix: str = "",
    key_builder: Optional[Callable[..., str]] = None,
):
    """Dekorator caching serbaguna untuk route FastAPI (mendukung sync & async)."""
    def decorator(func: Callable):
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    k = key_builder(*args, **kwargs) if key_builder else build_cache_key(prefix, func.__name__, args, kwargs)
                    cached_val = cache.get(k)
                    if cached_val is not None:
                        return cached_val
                except Exception:
                    k = None

                result = await func(*args, **kwargs)

                if k is not None and result is not None:
                    try:
                        cache.set(k, result, ttl_seconds=ttl_seconds)
                    except Exception:
                        pass
                return result

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    k = key_builder(*args, **kwargs) if key_builder else build_cache_key(prefix, func.__name__, args, kwargs)
                    cached_val = cache.get(k)
                    if cached_val is not None:
                        return cached_val
                except Exception:
                    k = None

                result = func(*args, **kwargs)

                if k is not None and result is not None:
                    try:
                        cache.set(k, result, ttl_seconds=ttl_seconds)
                    except Exception:
                        pass
                return result

            return sync_wrapper

    return decorator


def invalidate_cache(pattern: str = "*") -> int:
    """Helper global untuk menghapus cache berdasarkan pola wildcard (misal 'stats:*')."""
    return cache.invalidate_by_pattern(pattern)
