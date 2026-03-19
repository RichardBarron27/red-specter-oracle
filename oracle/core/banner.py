"""ORACLE CLI banner."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

EMERALD = "#00C853"
DARK = "#0A0A0A"


def print_banner(console: Console | None = None) -> None:
    """Print the ORACLE banner."""
    c = console or Console()
    banner_text = Text()
    banner_text.append("RED SPECTER ", style=f"bold {EMERALD}")
    banner_text.append("ORACLE", style=f"bold white on {DARK}")
    banner_text.append(" v1.0.0\n", style="dim")
    banner_text.append("Offline Research Assistant for Component-Level Exploitation Analysis\n", style=EMERALD)
    banner_text.append('"ORACLE sees what others miss."', style="italic dim")
    c.print(Panel(banner_text, border_style=EMERALD, expand=False))
