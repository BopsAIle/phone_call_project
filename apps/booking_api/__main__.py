"""Uvicorn entry: python -m apps.booking_api"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("apps.booking_api.main:app", host="0.0.0.0", port=8001)
