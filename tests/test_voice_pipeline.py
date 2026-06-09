# tests/test_voice_pipeline.py
import asyncio
import json
import unittest.mock as mock

from system_container import HousePadiSystem


# 1. Mock Socket to simulate Deepgram's behavior
class MockDeepgramSocket:

    def __init__(self, prompt):
        self.prompt = prompt
        self.closed = False
    
    async def __aenter__(self): return self

    async def __aexit__(self, *args): pass
    
    async def send(self, data):
        # We don't care about the raw audio bytes here, 
        # just simulating the server sending audio to Deepgram
        pass

    async def __aiter__(self):
        # Simulate Deepgram sending back a transcript
        yield json.dumps({
            "channel": {"alternatives": [{"transcript": self.prompt}]},
            "is_final": True
        })
        # Keep open briefly then close
        await asyncio.sleep(1) 
        raise ConnectionError("Mock socket closed")


# 2. Mock Client Socket to capture audio output
class MockClientSocket:

    def __init__(self):
        self.received_audio = []
        
    async def send(self, data):
        if isinstance(data, bytes):
            self.received_audio.append(data)
            print(f"✅ Received {len(data)} bytes of audio data.")
            
    def __aiter__(self): return self

    async def __anext__(self): raise StopAsyncIteration  # Stop input


async def run_e2e_test():
    # 1. Patch the client where it is imported (stream_handler)
    # This prevents the real code from even trying to connect
    with mock.patch("voice_engine.stream_handler.CartesiaStreamingClient") as MockTTS:
        
        # Configure the mock instance to return a generator
        mock_instance = MockTTS.return_value
        
        async def mock_audio_stream(*args, **kwargs):
            yield b"\x00" * 1024  # Simulate 1KB of valid audio data
        
        mock_instance.stream_text_to_voice = mock_audio_stream
        
        # 2. Now initialize the system. It will use the MockTTS.
        system = HousePadiSystem()
        client_socket = MockClientSocket()
        
        # 3. Run the test with a mock socket for Deepgram as well
        with mock.patch("websockets.connect", return_value=MockDeepgramSocket("Find me a 3 bedroom house in Wuse 2")):
            print("🚀 Starting E2E Voice Pipeline Test (using Mocks)...")
            try:
                await system.voice_handler.handle_voice_session(client_socket)
            except Exception as e:
                # We expect the mock to raise a ConnectionError eventually
                pass
            
        # Allow the background task to complete
        await asyncio.sleep(1) 
            
        # Verification
        if len(client_socket.received_audio) > 0:
            print(f"\n🎉 SUCCESS: Pipeline generated {len(client_socket.received_audio)} audio chunks.")
        else:
            print("\n❌ FAILURE: No audio data generated.")


if __name__ == "__main__":
    asyncio.run(run_e2e_test())
