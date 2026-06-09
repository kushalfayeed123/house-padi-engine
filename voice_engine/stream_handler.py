import asyncio
import json
import logging
import websockets
import os
from typing import Any, AsyncGenerator
from langchain_core.messages import HumanMessage
from voice_engine.tts_client import CartesiaStreamingClient

logger = logging.getLogger(__name__)

class AudioStreamOrchestrator:
    def __init__(self, graph_orchestrator: Any):
        self.graph = graph_orchestrator
        self.tts_client = CartesiaStreamingClient()
        self.deepgram_url = "wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1"
        self.active_session_task = None
        
    # Add this method to your AudioStreamOrchestrator class in stream_handler.py

    async def _to_async_gen(self, text: str) -> AsyncGenerator[str, None]:
        """Helper to convert a single string into an AsyncGenerator."""
        yield text

    async def handle_voice_session(self, client_socket: Any) -> None:
        dg_headers = {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}

        async with websockets.connect(self.deepgram_url, extra_headers=dg_headers) as dg_socket:
            
            async def pipe_mic():
                async for packet in client_socket:
                    if isinstance(packet, bytes):
                        await dg_socket.send(packet)
                    elif isinstance(packet, str):
                        if json.loads(packet).get("event") == "interrupt":
                            if self.active_session_task:
                                self.active_session_task.cancel()
                                logger.warning("Barge-in: Session task cancelled.")

            async def process_stt():
                async for dg_raw in dg_socket:
                    data = json.loads(dg_raw)
                    transcript = data.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
                    
                    if transcript.strip() and data.get("is_final"):
                        if self.active_session_task:
                            self.active_session_task.cancel()
                        self.active_session_task = asyncio.create_task(
                            self.generate_and_stream(transcript, client_socket)
                        )

            await asyncio.gather(pipe_mic(), process_stt())

    async def generate_and_stream(self, text: str, client_socket: Any):
        try:
            config = {"configurable": {"thread_id": "live_voice"}}
            # Use astream for real-time token generation
            async for event in self.graph.graph.astream({"messages": [HumanMessage(content=text)]}, config=config):
                state_update = list(event.values())[0]
                if "messages" in state_update and state_update["messages"]:
                    msg = state_update["messages"][-1]
                    if hasattr(msg, "content") and msg.content:
                        async_gen = self._to_async_gen(msg.content)
                        async for audio_chunk in self.tts_client.stream_text_to_voice(async_gen):
                            await client_socket.send(audio_chunk)
        except asyncio.CancelledError:
            logger.info("Generation task cancelled.")