# app/voice_engine/stream_handler.py
import asyncio
import json
import os
import logging
import websockets
from typing import Any, AsyncGenerator
from langchain_core.messages import HumanMessage
from agent_engine.graph import PadiGraphOrchestrator
from voice_engine.tts_client import CartesiaStreamingClient

logger = logging.getLogger(__name__)

class AudioStreamOrchestrator:
    """
    Manages asynchronous full-duplex communication channels, 
    bridging the client frontend to Deepgram and Padi's LangGraph system.
    """
    def __init__(self, graph_orchestrator: PadiGraphOrchestrator):
        self.graph = graph_orchestrator
        self.tts_client = CartesiaStreamingClient()
        # Deepgram live transcription websocket URL targeting raw 16kHz mono audio streams
        self.deepgram_url = "wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1"

    async def handle_voice_session(self, client_socket: Any) -> None:
        """
        Runs full duplex routing tasks concurrently to process live voice 
        interactions without locking the main thread framework execution.
        """
        logger.info("A new live voice session has connected to House Padi Gateway.")
        dg_headers = {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY', 'mock_dg_key')}"}

        try:
            # FIX: Swapped out 'extra_headers' for the correct 'additional_headers' keyword parameter
            async with websockets.connect(self.deepgram_url, additional_headers=dg_headers) as dg_socket:
                
                async def pipe_microphone_to_stt():
                    """Listens continuously to incoming frontend mic packets and forwards them to Deepgram."""
                    async for packet in client_socket:
                        if isinstance(packet, bytes):
                            await dg_socket.send(packet)
                        elif isinstance(packet, str):
                            # Intercept text control commands from frontend (e.g. interruption event triggers)
                            payload = json.loads(packet)
                            if payload.get("event") == "interrupt":
                                logger.warning("User verbal interruption signal intercepted. Flushing text queues.")

                async def process_transcripts_and_reply():
                    """Captures finalized text tokens from Deepgram, updates Padi, and returns audio."""
                    async for dg_raw_response in dg_socket:
                        response_data = json.loads(dg_raw_response)
                        alternatives = response_data.get("channel", {}).get("alternatives", [{}])
                        transcript = alternatives[0].get("transcript", "")
                        is_final = response_data.get("is_final", False)

                        if transcript.strip() and is_final:
                            logger.info(f"[Deepgram Live Transcript]: '{transcript}'")
                            
                            session_config = {"configurable": {"thread_id": "live_voice_session_active"}}
                            
                            input_payload = {
                                "messages": [HumanMessage(content=transcript)],
                                "transaction_context": {}
                            }
                            
                            output_state = self.graph.graph.invoke(input_payload, config=session_config)
                            padi_response_text = output_state["messages"][-1].content
                            logger.info(f"[Padi Outbound Voice Text]: '{padi_response_text}'")

                            async def text_token_stream() -> AsyncGenerator[str, None]:
                                for word in padi_response_text.split():
                                    yield word + " "
                                    await asyncio.sleep(0.04)

                            audio_stream = self.tts_client.stream_text_to_voice(text_token_stream())

                            async def send_audio_chunks():
                                async for audio_packet in audio_stream:
                                    if audio_packet:
                                        await client_socket.send(audio_packet)
                                        
                            asyncio.create_task(send_audio_chunks())

                # Bind both transport pipes concurrently using asyncio tasks loops
                await asyncio.gather(
                    pipe_microphone_to_stt(),
                    process_transcripts_and_reply()
                )

        except websockets.exceptions.ConnectionClosed:
            logger.info("House Padi client voice connection closed normally.")
        except Exception as e:
            logger.error(f"Critical error triggered in voice pipeline loop: {str(e)}")