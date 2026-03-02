from django.core.cache import cache


class RateLimitError(Exception):
    pass


def rate_limit(key: str, *, limit: int, window_seconds: int):
    """
    Permite no máximo `limit` ações por `window_seconds` por `key`.
    """
    cache_key = f"rl:{key}"
    current = cache.get(cache_key, 0)

    if current >= limit:
        raise RateLimitError("Muitas tentativas. Aguarde um pouco.")

    if current == 0:
        cache.set(cache_key, 1, window_seconds)
    else:
        cache.incr(cache_key, 1)