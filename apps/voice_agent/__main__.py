"""Uvicorn entry: python -m apps.voice_agent"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("apps.voice_agent.server:app", host="0.0.0.0", port=8000)
