"""Entry: python -m apps.browser_sim"""

import uvicorn

from shared.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("apps.browser_sim.server:app", host="0.0.0.0", port=settings.browser_sim_port)
