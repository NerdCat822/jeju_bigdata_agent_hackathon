"""웹 API (FastAPI). React 화면이 부르는 HTTP 진입점이에요."""

from .app import create_app

__all__ = ["create_app"]
