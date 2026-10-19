"""Run the localhost API (uvicorn). Binds to 127.0.0.1 by default."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
