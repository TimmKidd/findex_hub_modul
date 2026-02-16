import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from findex_bot.bot import main as bot_main


def load_environment():
    """
    Загружаем .env, если он существует.
    Ничего не ломаем, если файла нет (например, в проде через system env).
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    load_environment()

    asyncio.run(bot_main())