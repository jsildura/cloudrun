"""
Server launcher for Windows.
Forces ProactorEventLoop (required for subprocess support) before
uvicorn can override it with SelectorEventLoop.
"""

import sys
import asyncio

# On Windows, uvicorn defaults to SelectorEventLoop which does NOT
# support asyncio.create_subprocess_exec(). We must force Proactor
# BEFORE uvicorn initializes, and patch its setup to prevent override.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from uvicorn.config import Config

# Prevent uvicorn from resetting the event loop policy
_original_setup = Config.setup_event_loop
def _patched_setup(self):
    """Skip uvicorn's event loop setup to keep ProactorEventLoop on Windows."""
    if sys.platform == "win32":
        return  # Already set above
    _original_setup(self)
Config.setup_event_loop = _patched_setup


if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
