"""ORACLE CLI — Typer application."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from oracle import __version__
from oracle.core.banner import print_banner
from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.db.database import Database

app = typer.Typer(
    name="oracle",
    help="ORACLE — Offline Research Assistant for Component-Level Exploitation Analysis",
    no_args_is_help=True,
)
console = Console()


def _load_config() -> OracleConfig:
    return OracleConfig.load()


@app.command()
def status():
    """Show ORACLE system status."""
    print_banner(console)
    config = _load_config()
    config.ensure_dirs()

    # Database
    db = Database(config.db_path)
    stats = db.get_stats()
    db.close()

    # Ollama
    ollama = OllamaClient(config.ollama)
    model_status = ollama.model_status()
    ollama.close()

    table = Table(title="System Status", border_style="green")
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    # Ollama
    avail = model_status.get("ollama_available", False)
    table.add_row(
        "Ollama",
        "[green]Running[/]" if avail else "[red]Not Running[/]",
        config.ollama.base_url,
    )

    # Models
    for key in ("reasoning_model", "vision_model", "embedding_model"):
        m = model_status.get(key, {})
        name = m.get("name", "?")
        s = m.get("status", "unknown")
        style = "[green]Loaded[/]" if s == "loaded" else "[yellow]Missing[/]"
        table.add_row(f"  {key.replace('_', ' ').title()}", style, name)

    # Database
    table.add_row(
        "Database",
        "[green]Connected[/]",
        f"{stats['sessions']} sessions, {stats['documents']} docs, {stats['queries']} queries",
    )

    # Config
    table.add_row("Config Dir", "", str(config.config_dir))
    table.add_row("Documents Dir", "", str(config.documents_dir))

    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8200, help="Port"),
):
    """Start the ORACLE API server."""
    print_banner(console)
    console.print(f"Starting ORACLE API on {host}:{port}", style="bold green")
    uvicorn.run(
        "oracle.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )


@app.command()
def init():
    """Initialise ORACLE configuration and directories."""
    print_banner(console)
    config = OracleConfig()
    config.ensure_dirs()
    config.save()
    console.print(f"Configuration saved to {config.config_dir / 'config.json'}", style="green")
    console.print(f"Database: {config.db_path}", style="dim")
    console.print(f"Documents: {config.documents_dir}", style="dim")
    console.print(f"Vector store: {config.chroma_dir}", style="dim")
    console.print("ORACLE initialised.", style="bold green")


@app.command()
def sessions():
    """List research sessions."""
    config = _load_config()
    db = Database(config.db_path)
    sess_list = db.list_sessions()
    db.close()

    if not sess_list:
        console.print("No sessions found. Create one with: oracle new-session <name>", style="yellow")
        return

    table = Table(title="Research Sessions", border_style="green")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Created")

    for s in sess_list:
        from datetime import datetime
        created = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M")
        table.add_row(
            s["session_id"][:12] + "...",
            s["name"],
            s["status"],
            created,
        )
    console.print(table)


@app.command(name="new-session")
def new_session(name: str = typer.Argument(..., help="Session name")):
    """Create a new research session."""
    config = _load_config()
    config.ensure_dirs()
    db = Database(config.db_path)
    session = db.create_session(name)
    db.close()
    console.print(f"Session created: {session['session_id']}", style="bold green")
    console.print(f"Name: {name}", style="dim")


@app.command()
def query(
    session_id: str = typer.Argument(..., help="Session ID"),
    text: str = typer.Argument(..., help="Query text"),
):
    """Submit a test query to Ollama (Sprint 1 — basic connectivity test)."""
    config = _load_config()
    ollama = OllamaClient(config.ollama)

    if not ollama.is_available():
        console.print("Ollama is not running.", style="bold red")
        raise typer.Exit(1)

    console.print(f"Querying: {text}", style="dim")
    result = ollama.generate(
        prompt=text,
        system="You are ORACLE, a research assistant for security researchers. This is a test query.",
    )
    ollama.close()

    response = result.get("response", "No response")
    console.print(f"\n{response}", style="green")


@app.command()
def models():
    """Show Ollama model status."""
    config = _load_config()
    ollama = OllamaClient(config.ollama)
    status = ollama.model_status()
    ollama.close()
    console.print_json(json.dumps(status, indent=2))
