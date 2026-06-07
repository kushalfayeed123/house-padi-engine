# app/main.py
import asyncio
from system_container import HousePadiSystem
from agent_engine.registry import AgentManifest
# app/tests/test_utils.py
import json

class MockClientWebSocket:
    """Simulates the frontend WebSocket stream for integration testing."""
    def __init__(self):
        self.messages = [
            b"\x00\x01\x02\x03", 
            json.dumps({"event": "interrupt"})
        ]
        self.index = 0

    def __aiter__(self): 
        return self

    async def __anext__(self):
        if self.index < len(self.messages):
            msg = self.messages[self.index]
            self.index += 1
            return msg
        raise StopAsyncIteration

    async def send(self, data: bytes):
        pass

async def main():
    system = HousePadiSystem()
    
    # Register agents into the system
    system.registry.register_agent(AgentManifest(
        name="discovery",
        description="Handles property search via discovery MCP.",
        system_instructions="You are Padi. Use discovery tool for searches."
    ))

    # Run the voice pipeline
    print("--- House Padi System Operational ---")
    mock_socket = MockClientWebSocket() # Your existing mock
    await system.voice_handler.handle_voice_session(mock_socket)

if __name__ == "__main__":
    asyncio.run(main())