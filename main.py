import logging
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from middleware.auth_gateway import AuthGatewayMiddleware
from system_container import HousePadiSystem

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("house_padi_server")


class FastAPIWebSocketAdapter:

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def send(self, data: bytes):
        await self.websocket.send_bytes(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.websocket.receive_bytes()
        except WebSocketDisconnect:
            raise StopAsyncIteration


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.system = HousePadiSystem()
        app.state.system.run_health_check()
        logger.info("--- House Padi System Operational & Ready ---")
    except Exception as e:
        logger.error(f"System failed to initialize: {e}")
        raise e
    yield
    logger.info("--- House Padi System Shutting Down ---")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    AuthGatewayMiddleware,
)


class UserInput(BaseModel):
    text: str
    session_id: str = "default_session"

    
class RoleUpdateRequest(BaseModel):
    target_user_id: str
    role: Literal['landlord', 'renter', 'admin']
    action: str  # "grant" or "revoke"
    expires_at: str | None = None  # ISO datetime string, optional
    

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    phone: str | None = None
    role: Literal['landlord', 'renter', 'admin']


async def resolve_user_context(user_id: str | None, supabase) -> dict:
    """
    No user_id = unauthenticated request.
    We don't assign 'guest' — we just return no user_id and no roles.
    The permission check handles this by only allowing tools that are
    explicitly open to unauthenticated callers.
    """
    if not user_id:
        return {"current_user_id": None, "user_role": None, "user_roles": []}

    try:
        resp = (
            supabase.table("user_roles")
            .select("roles(name)")
            .eq("user_id", user_id)
            .execute()
        )
        roles = [row["roles"]["name"] for row in (resp.data or []) if row.get("roles")]
        if "admin" in roles:
            primary_role = "admin"
        elif "landlord" in roles and "renter" in roles:
            primary_role = "landlord"
        elif roles:
            primary_role = roles[0]
        else:
            primary_role = None
        return {"current_user_id": user_id, "user_role": primary_role, "user_roles": roles}
    except Exception as e:
        logger.error(f"Failed to resolve roles for user_id={user_id}: {e}")
        primary_role = None
        return {"current_user_id": user_id, "user_role": primary_role, "user_roles": []}
    
    
    
class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
async def login_user(body: LoginRequest):
    supabase = app.state.system.supabase
    try:
        # Supabase handles password verification
        auth_response = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password
        })
        
        # Return the session details to the client
        return {
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token,
            "user": {
                "id": auth_response.user.id,
                "email": auth_response.user.email
            }
        }
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid email or password.")


@app.post("/api/auth/register")
async def register_user(body: RegisterRequest):
    supabase = app.state.system.supabase

    # 1. Just call sign_up
    # If this fails, NOTHING happens. No need to delete.
    try:
        auth_response = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {
                "data": {
                    "full_name": body.full_name,
                    "phone": body.phone,
                    "role": body.role
                }
            }
        })
    except Exception as e:
        # The database trigger failure will bubble up here.
        # Just log it and tell the user it failed.
        logger.error(f"Signup failed: {e}")
        raise HTTPException(status_code=400, detail="Registration failed.")

    return {"message": "Success"}


@app.post("/api/admin/users/roles")
async def update_user_role(body: RoleUpdateRequest, request: Request):
    """
    Grant or revoke a role for a user.
    Caller must be an admin — role is verified from DB, not the request.
    """
    admin_user_id = request.headers.get("X-User-ID")
    supabase = app.state.system.supabase

    # Verify the caller is actually an admin
    caller_ctx = await resolve_user_context(admin_user_id, supabase)
    if caller_ctx["user_role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update roles.")

    # Validate the role exists
    role_resp = supabase.table("roles").select("id").eq("name", body.role).maybe_single().execute()
    if not role_resp or not role_resp.data:
        raise HTTPException(status_code=400, detail=f"Role '{body.role}' does not exist.")
    role_id = role_resp.data["id"]

    if body.action == "grant":
        payload = {
            "user_id": body.target_user_id,
            "role_id": role_id,
            "granted_by": admin_user_id,
        }
        if body.expires_at:
            payload["expires_at"] = body.expires_at

        supabase.table("user_roles").upsert(payload, on_conflict="user_id,role_id").execute()

        # Refresh the materialized view so permissions take effect immediately
        supabase.rpc("refresh_user_permissions").execute()
        return {"status": "SUCCESS", "message": f"Role '{body.role}' granted to user."}

    elif body.action == "revoke":
        supabase.table("user_roles").delete()\
            .eq("user_id", body.target_user_id)\
            .eq("role_id", role_id)\
            .execute()

        supabase.rpc("refresh_user_permissions").execute()
        return {"status": "SUCCESS", "message": f"Role '{body.role}' revoked from user."}

    else:
        raise HTTPException(status_code=400, detail="action must be 'grant' or 'revoke'.")


@app.post("/api/chat")
async def handle_text_chat(input: UserInput, request: Request):
    """
    Text chat endpoint.

    Expected headers
    ----------------
    X-User-ID : UUID of the authenticated user (set by your auth middleware/gateway).
                Role is resolved from the database — never from the client.
    """
    try:
        user_id = getattr(request.state, "user_id", None)
        supabase = app.state.system.supabase

        # Role is always fetched from DB — client cannot spoof it
        user_context = await resolve_user_context(user_id, supabase)

        orchestrator = app.state.system.orchestrator
        config = {"configurable": {"thread_id": input.session_id}}

        # Fetch existing checkpoint state and merge so context survives multi-turn
        existing_state = await orchestrator.graph.aget_state(config)
        existing_ctx = {}
        if existing_state and existing_state.values:
            existing_ctx = existing_state.values.get("transaction_context", {}) or {}

        merged_context = {
            **existing_ctx,
            **user_context,
        }

        payload = {
            "messages": [HumanMessage(content=input.text)],
            "transaction_context": merged_context,
        }

        result = await orchestrator.graph.ainvoke(payload, config=config)

        messages = result.get("messages", [])
        content = getattr(messages[-1], "content", "I'm sorry, I couldn't generate a response.") if messages else "I'm sorry, I couldn't generate a response."

        return {"response": content}

    except Exception as e:
        logger.exception("Error in text chat")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    adapter = FastAPIWebSocketAdapter(websocket)
    try:
        await app.state.system.voice_handler.handle_voice_session(adapter)
    except WebSocketDisconnect:
        logger.info("Client connection closed.")
    except Exception as e:
        logger.error(f"Voice session error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
