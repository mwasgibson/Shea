from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import click
import uvicorn

from shea.audio.service import AudioInteractionService
from shea.bootstrap import build_runtime
from shea.contracts.models import Intent
from shea.events.contracts import Event


@click.group()
def cli() -> None:
    """Shea Agent - Unified Command Line Interface"""
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--port", default=8000, help="Port to bind to.", type=int)
def serve(host: str, port: int) -> None:
    """Start the Shea unified web server."""
    click.secho(f"Starting Shea API and Web GUI on http://{host}:{port}", fg="green")
    uvicorn.run("shea.api.server:create_app", host=host, port=port, factory=True, reload=True)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Internal host for the background API.")
@click.option("--port", default=8000, help="Internal port for the background API.", type=int)
def desktop(host: str, port: int) -> None:
    """Launch the Shea desktop native application."""
    from shea.gui.desktop import start_desktop_app
    
    click.secho("Starting Shea Desktop App...", fg="blue")
    start_desktop_app(host=host, port=port)


@cli.command()
@click.option("--db-path", default="shea.db", help="Path to SQLite database.")
@click.option("--workspace", default="./workspace", help="Path to workspace directory.")
def chat(db_path: str, workspace: str) -> None:
    """Start an interactive terminal chat session with the agent."""

    click.secho("Booting Shea Runtime...", fg="yellow")
    runtime = build_runtime(db_path=db_path, workspace=workspace)

    click.secho("System ready. Type 'exit' to quit.", fg="green", bold=True)

    while True:
        try:
            user_input = input("\n\033[1mYou>\033[0m ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break

            now = datetime.now(UTC)
            intent = Intent(
                id=uuid4().hex,
                task_id=uuid4().hex,
                type="chat",
                goal=user_input,
                parameters={"profile_id": "cli_user"},
                source="cli",
                created_at=now,
            )

            click.secho(
                f"\n[Agent] Intent matched! Planning execution for: {intent.id}...\n",
                fg="cyan",
            )
            runtime.event_bus.publish(
                Event(
                    event_id=uuid4().hex,
                    event_type="interaction.intent_received",
                    source="cli",
                    timestamp=now,
                    payload={
                        "intent_id": intent.id,
                        "task_id": intent.task_id,
                        "goal": intent.goal,
                        "profile_id": "cli_user",
                    },
                    correlation_id=intent.id,
                )
            )

        except (KeyboardInterrupt, EOFError):
            break

    click.echo("\nGoodbye!")


if __name__ == "__main__":
    cli()
@cli.command(name="listen")
@click.option("--db-path", default="shea.db", help="Path to SQLite database.")
def listen_cmd(db_path: str) -> None:
    """Start the audio wake-word interaction loop."""
    
    runtime = build_runtime(db_path=db_path)
    
    # We need to run the runtime event bus in the background if it has async listeners,
    # but the audio loop is strictly synchronous right now (mock input).
    # Since event_bus.publish is sync and handles it via MemoryChannel directly, it works.
    
    click.secho("Starting Audio Interaction Service...", fg="cyan", bold=True)
    audio_service = AudioInteractionService(runtime)
    audio_service.start_loop()
