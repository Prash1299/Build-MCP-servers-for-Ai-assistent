
from starlette.responses import JSONResponse

from mcp_servers.auth import authenticate_token, bearer_token


class MCPAuthMiddleware:
    """Protect every HTTP request to an MCP endpoint."""

    def __init__(self, app, audience: str, role: str):
        self.app = app
        self.audience = audience
        self.role = role

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            headers = {
                key.lower(): value
                for key, value in scope.get("headers", [])
            }
            token = bearer_token(headers)
            claims = authenticate_token(
                token,
                audience=self.audience,
                role=self.role,
            )
            scope.setdefault("state", {})["claims"] = claims
        except Exception:
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
