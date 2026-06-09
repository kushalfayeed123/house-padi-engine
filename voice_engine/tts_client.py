import os
import json
import logging
import websockets
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

class CartesiaStreamingClient:
    def __init__(self):
        self.api_key = os.getenv("CARTESIA_API_KEY")
        self.voice_id = os.getenv("CARTESIA_VOICE_ID")
        
        if not self.api_key or not self.voice_id:
            raise ValueError("CARTESIA_API_KEY and CARTESIA_VOICE_ID must be set.")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Cartesia-Version": "2024-06-10"
        }
        self.uri = "wss://api.cartesia.ai/tts/websocket"

    async def stream_text_to_voice(self, text_generator: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        async with websockets.connect(self.uri, extra_headers=self.headers) as ws:
            # 1. Handshake/Setup
            setup_payload = {
                "action": "setup",
                "model_id": "sonic-english",
                "voice": {"mode": "id", "id": self.voice_id},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000
                }
            }
            await ws.send(json.dumps(setup_payload))

            # 2. Stream tokens
            async for text_token in text_generator:
                if not text_token.strip():
                    continue
                
                await ws.send(json.dumps({"action": "send", "transcript": text_token, "continue": True}))

                # 3. Yield audio chunks as they arrive
                # Note: Adjust protocol parsing based on Cartesia's specific message format
                async for message in ws:
                    if isinstance(message, bytes):
                        yield message
                    else:
                        response = json.loads(message)
                        if response.get("type") == "done":
                            break