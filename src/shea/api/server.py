from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from shea.api.routes import interaction, memory, observability
from shea.bootstrap import build_runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the lifecycle of the SheaRuntime."""
    # Build the runtime when the server starts
    db_path = os.environ.get("SHEA_DB_PATH", "shea.db")
    workspace = os.environ.get("SHEA_WORKSPACE", "./workspace")
    
    runtime = build_runtime(db_path=db_path, workspace=workspace)
    app.state.runtime = runtime
    
    yield  # Server runs here
    
    # Optional cleanup on shutdown
    pass


def create_app() -> FastAPI:
    """Factory to create the FastAPI application."""
    app = FastAPI(
        title="Shea Agent API",
        description="Unified backend for the Shea Web and Desktop GUIs.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS for local development UI access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    app.include_router(interaction.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(observability.router, prefix="/api")

    # Mount the static GUI files at the root
    # Note: we will create this directory in Phase G1
    gui_path = os.path.join(os.path.dirname(__file__), "..", "gui", "web")
    if os.path.exists(gui_path):
        app.mount("/", StaticFiles(directory=gui_path, html=True), name="gui")

    return app


if __name__ == "__main__":
    import uvicorn
    # When run directly, start the server
    uvicorn.run(
        "shea.api.server:create_app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        factory=True
    )