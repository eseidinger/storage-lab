from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class PortalFiles(StaticFiles):
    """Serve built assets and the SPA entry point for client-side routes."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            api_request = (b"x-storage-lab-api", b"true") in scope.get("headers", [])
            if exc.status_code != 404 or Path(path).suffix or api_request:
                raise
            return await super().get_response("index.html", scope)
