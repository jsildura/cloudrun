"""
Server launcher for Windows.
Forces ProactorEventLoop (required for subprocess support) before
uvicorn can override it with SelectorEventLoop.
"""

import sys
import asyncio

# On Windows, uvicorn defaults to SelectorEventLoop which does NOT
# support asyncio.create_subprocess_exec(). We must force Proactor
import warnings
if sys.platform == "win32":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
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


import os
import argparse
from pathlib import Path

# Automatically add local bin/ directory to PATH
_bin_dir = Path(__file__).resolve().parent / "bin"
if _bin_dir.is_dir() and str(_bin_dir) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_bin_dir) + os.pathsep + os.environ.get("PATH", "")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gamdl server launcher")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"), help="Host to bind")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Port to bind")
    parser.add_argument("--reload", action="store_true", default=os.environ.get("RELOAD", "false").lower() in ("true", "1"))
    args = parser.parse_args()

    uvicorn.run(
        "server.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
