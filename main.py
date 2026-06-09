import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

# Ensure this matches your file structure
from system_container import HousePadiSystem 

# 1. Configuration
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("house_padi_server")


# 2. Bridge Adapter
class FastAPIWebSocketAdapter:
    """
    Adapts the FastAPI WebSocket to the interface required 
    by AudioStreamOrchestrator (send + __aiter__).
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def send(self, data: bytes):
        """Sends audio data from the system to the client."""
        await self.websocket.send_bytes(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        """Receives audio data from the client, converts to stream."""
        try:
            data = await self.websocket.receive_bytes()
            return data
        except WebSocketDisconnect:
            raise StopAsyncIteration


# 3. Lifespan Manager (Modern Replacement for on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown lifecycle."""
    try:
        # Startup
        app.state.system = HousePadiSystem()
        app.state.system.run_health_check()
        logger.info("--- House Padi System Operational & Ready ---")
    except Exception as e:
        logger.error(f"System failed to initialize: {e}")
        raise e
    
    yield  # Application running
    
    # Shutdown
    logger.info("--- House Padi System Shutting Down ---")


# 4. App Initialization
app = FastAPI(lifespan=lifespan)

# 5. Routes


class UserInput(BaseModel):
    text: str
    user_id: str = "default_user"


@app.post("/api/chat")
async def handle_text_chat(input: UserInput):
    """
    Direct text input endpoint. 
    Returns the text content of the final message.
    """
    try:
        orchestrator = app.state.system.orchestrator
        payload = {
            "messages": [HumanMessage(content=input.text)],
            "transaction_context": {"property_id": None}
        }
        config = {"configurable": {"thread_id": input.user_id}}
        
        # 1. Invoke the graph
        result = await orchestrator.graph.ainvoke(payload, config=config)
        
        # 2. Extract the last message content safely
        messages = result.get("messages", [])
        if messages:
            final_message = messages[-1]
            # If it's a LangChain message object, access .content
            content = getattr(final_message, "content", str(final_message))
        else:
            content = "I'm sorry, I couldn't generate a response."
            
        return {"response": content}
        
    except Exception as e:
        # Log the full traceback to identify where '__end__' is coming from
        logger.exception("Error in text chat")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    """
    Entry point for real-time voice streaming.
    """
    await websocket.accept()
    adapter = FastAPIWebSocketAdapter(websocket)
    
    try:
        # Inject the adapter into the existing voice pipeline
        await app.state.system.voice_handler.handle_voice_session(adapter)
    except WebSocketDisconnect:
        logger.info("Client connection closed.")
    except Exception as e:
        logger.error(f"Voice session error: {e}")


if __name__ == "__main__":
    import uvicorn
    # Start the server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
