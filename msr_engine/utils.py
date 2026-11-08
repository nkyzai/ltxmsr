import os
import re
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console

# DO NOT IMPORT CONFIG AT THE TOP LEVEL. 
# This prevents circular dependencies and silent load failures.
console = Console()

def ensure_dependencies():
    """Check if required packages are installed."""
    try:
        import requests
        import rich
        import bs4
    except ImportError as e:
        console.print(f"[bold red]Missing dependency: {e}[/bold red]")
        raise SystemExit(1)

def create_directories():
    """Creates the base Projects Root if it doesn't exist."""
    # LAZY IMPORT: Import config only when this function is called
    import msr_engine.config as cfg
    
    if hasattr(cfg, 'PROJECTS_ROOT'):
        cfg.PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓ Projects Root ensured: {cfg.PROJECTS_ROOT}[/green]")
    else:
        console.print("[red]ERROR: PROJECTS_ROOT not defined in config.[/red]")
        raise SystemExit(1)

def archive_previous_outputs():
    """
    Placeholder for future cleanup logic.
    Currently does nothing as projects are isolated.
    """
    pass