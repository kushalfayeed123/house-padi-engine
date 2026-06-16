# middleware/auth_gateway.py
# Add this to your existing FastAPI app — no separate service needed

import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from starlette.requests import Request


# Routes that don't require authentication
# Updated routes
STRICT_PUBLIC_ROUTES = {
    "/api/auth/register",
    "/api/auth/login",
    "/docs",
    "/openapi.json",
}

OPTIONAL_AUTH_ROUTES = {
    "/api/chat",
}


class AuthGatewayMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 1. Strictly Public: Ignore auth entirely
        if path in STRICT_PUBLIC_ROUTES:
            return await call_next(request)

        # 2. Extract header with explicit typing
        auth_header: str | None = request.headers.get("Authorization")

        # 3. Handle Optional Auth (e.g., /api/chat)
        if path in OPTIONAL_AUTH_ROUTES and auth_header is None:
            return await call_next(request)  # Guest access allowed

        # 4. Mandatory Auth Check (either required route or provided header)
        if not auth_header:
            raise HTTPException(status_code=401, detail="Authentication required.")

        # 5. Format Validation
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization format. Must be Bearer token.")

        token = auth_header.split(" ")[1] 
        
        # 6. Verification
        try:
            supabase_client = request.app.state.system.supabase
            user_response = supabase_client.auth.get_user(token)
            
            if not user_response or not user_response.user:
                raise HTTPException(status_code=401, detail="Invalid or expired token.")

            request.state.user_id = user_response.user.id
            
        except Exception as e:
            # Differentiate between Auth failure and internal errors if needed
            raise HTTPException(status_code=401, detail="Authentication failed.")

        return await call_next(request)
