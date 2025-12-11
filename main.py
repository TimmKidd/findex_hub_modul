import asyncio
import logging

from findex_bot.bot import main as bot_main


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(bot_main())

