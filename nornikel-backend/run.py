"""Run the FastAPI backend with uvicorn."""

import os

import uvicorn

from settings import get_settings


def main():
    settings = get_settings()
    reload = os.getenv("API_RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run(
        "api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=reload,
        app_dir="src",
    )


if __name__ == "__main__":
    main()
