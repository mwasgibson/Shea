from __future__ import annotations

import multiprocessing
import sys
import time

import uvicorn
import webview

from shea.api.server import create_app


def run_api_server(host: str, port: int) -> None:
    """Run the FastAPI server in a separate process."""
    uvicorn.run(create_app, host=host, port=port, log_level="error")


def start_desktop_app(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Launch the native desktop window and the backend server."""
    # Ensure multiprocessing works nicely on macOS/Windows
    if sys.platform.startswith("darwin") or sys.platform.startswith("win"):
        multiprocessing.set_start_method("spawn", force=True)

    server_process = multiprocessing.Process(
        target=run_api_server, args=(host, port), daemon=True
    )
    server_process.start()

    # Give the server a moment to bind to the port
    time.sleep(1.0)

    url = f"http://{host}:{port}/"
    
    # Create the native window and confirm it was initialized before starting the loop.
    window = webview.create_window(  # pyright: ignore[reportUnknownMemberType]
        title="Shea Agent",
        url=url,
        width=1024,
        height=768,
        min_size=(800, 600),
        text_select=True,
    )
    if window is None:
        raise RuntimeError("Failed to create the Shea desktop window.")

    try:
        # Start the native event loop
        webview.start(debug=False)
    finally:
        # Ensure server is torn down when the window closes
        server_process.terminate()
        server_process.join()


if __name__ == "__main__":
    start_desktop_app()