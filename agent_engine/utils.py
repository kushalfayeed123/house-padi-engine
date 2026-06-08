import json
from pathlib import Path

def load_agent_prompts(filename="prompts.json"):
    path = Path(__file__).parent / filename
    with open(path, "r") as f:
        return json.load(f)