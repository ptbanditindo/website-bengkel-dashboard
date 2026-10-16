"""AI Bengkel Telegram Bot - entry point."""

import logging

from dotenv import load_dotenv

# Load .env before importing bot.* (which reads env vars at import time).
load_dotenv()

from bot.application import run  # noqa: E402


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    run()


if __name__ == "__main__":
    main()