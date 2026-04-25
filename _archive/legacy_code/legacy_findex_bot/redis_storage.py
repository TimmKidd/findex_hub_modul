import logging
from redis import Redis, RedisError

# Инициализация Redis с обработкой ошибок
try:
    redis = Redis(host="localhost", port=6379)
    redis.ping()  # Пингуем Redis, чтобы проверить соединение
    logging.info("Redis подключён")
except RedisError as e:
    logging.error(f"Не удалось подключиться к Redis: {e}")
    redis = None

__all__ = ['redis']
