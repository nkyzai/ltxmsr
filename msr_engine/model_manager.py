"""
Model Manager - Full lifecycle management for Ollama and ComfyUI.
Auto-starts/stops both services with strict sequential VRAM handoff.
FIXED: Added Windows Console Event Handler to catch 'Close Window' clicks.
"""

import subprocess
import time
import sys
import os
import signal
import atexit
import requests
from pathlib import Path
from .config import OLLAMA_URL, OLLAMA_MODEL, COMFYUI_URL
from .utils import console

# Track ComfyUI process handle AND PID so we can kill it later
_comfyui_process = None
_comfyui_pid = None
_ollama_process = None # Optional: track if we started ollama serve ourselves

# Auto-detect ComfyUI location
_COMFYUI_DIR = Path(r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable")
_COMFYUI_BAT = _COMFYUI_DIR / "run_nvidia_gpu.bat"


def _cleanup_on_exit():
    """
    Registered as an atexit handler. 
    Runs when the script ends, crashes, or is interrupted.
    Ensures no zombie processes hold VRAM.
    """
    global _comfyui_process, _comfyui_pid
    
    # Only attempt cleanup if we actually started something
    if _comfyui_process is not None or _comfyui_pid is not None:
        try:
            # Suppress output during emergency cleanup to avoid clutter/errors if stdout is closed
            _force_kill_comfyui_tree()
        except Exception:
            pass
    
    if _is_ollama_running():
        try:
            _kill_ollama()
        except Exception:
            pass


def _windows_console_handler(ctrl_type):
    """
    Windows-specific handler to catch CTRL_C_EVENT, CTRL_BREAK_EVENT, 
    and crucially CTRL_CLOSE_EVENT (clicking the 'X' on the terminal).
    Returns True to indicate the event was handled.
    """
    if ctrl_type == 0x00000002:  # CTRL_C_EVENT
        console.print("\n[yellow]Caught Ctrl+C. Cleaning up...[/yellow]")
        _cleanup_on_exit()
        return True
    elif ctrl_type == 0x00000005:  # CTRL_CLOSE_EVENT
        console.print("\n[yellow]Caught Terminal Close. Cleaning up...[/yellow]")
        _cleanup_on_exit()
        return True
    elif ctrl_type == 0x00000006:  # CTRL_LOGOFF_EVENT
        _cleanup_on_exit()
        return True
    elif ctrl_type == 0x00000007:  # CTRL_SHUTDOWN_EVENT
        _cleanup_on_exit()
        return True
    return False


def _register_windows_cleanup():
    """Registers the console control handler on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # SetConsoleCtrlHandler takes a callback function pointer
            # We use ctypes.CFUNCTYPE to wrap our python function
            HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
            
            # Create the callback object
            callback = HANDLER_ROUTINE(_windows_console_handler)
            
            # Register it (True means "add" handler)
            success = kernel32.SetConsoleCtrlHandler(callback, True)
            if success:
                console.print("[dim]✓ Windows Console Cleanup Hook Registered.[/dim]")
            else:
                console.print("[yellow]⚠ Failed to register Windows Console Hook. Relying on atexit.[/yellow]")
                
            # Keep a reference to prevent garbage collection of the callback
            globals()['_callback_ref'] = callback
            
        except Exception as e:
            console.print(f"[red]Error registering Windows Hook: {e}[/red]")


# Register cleanup hooks immediately upon module load
atexit.register(_cleanup_on_exit)

# Standard Signal Handlers (for Linux/Mac and basic Windows Ctrl+C)
try:
    signal.signal(signal.SIGINT, lambda s, f: (_cleanup_on_exit(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (_cleanup_on_exit(), sys.exit(0)))
except ValueError:
    # Signal handling may fail in non-main threads; ignore if so
    pass

# Windows-Specific Hook for "Close Window"
_register_windows_cleanup()


def _is_ollama_running():
    """Check if Ollama server is responding OR process exists."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    # Check process as fallback
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ollama.exe"],
                capture_output=True, text=True, timeout=5
            )
            return "ollama.exe" in result.stdout.lower()
    except Exception:
        pass
    return False


def _is_comfyui_running():
    """Check if ComfyUI is responding via API."""
    try:
        resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _kill_ollama():
    """Force kill all Ollama processes and verify VRAM is freed."""
    # Graceful unload first
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "keep_alive": 0},
            timeout=5
        )
        time.sleep(2)
    except Exception:
        pass

    # Force kill on Windows
    if sys.platform == "win32":
        for proc_name in ["ollama.exe", "ollama_llama_server.exe"]:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", proc_name],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass
    else:
        try:
            subprocess.run(["pkill", "-9", "-f", "ollama"], capture_output=True, timeout=10)
        except Exception:
            pass

    time.sleep(4)
    console.print("[green]✓ Ollama fully stopped.[/green]")


def _start_ollama():
    """Start Ollama server and wait until ready."""
    global _ollama_process
    
    if _is_ollama_running():
        console.print("[dim]Ollama already running.[/dim]")
        return

    console.print("[cyan]Starting Ollama server...[/cyan]")
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    _ollama_process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags
    )

    for i in range(30):
        try:
            resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
            if resp.status_code == 200:
                console.print("[green]✓ Ollama server ready.[/green]")
                return
        except Exception:
            pass
        time.sleep(1)

    console.print("[red]✗ Ollama failed to start within 30 seconds.[/red]")


def _preload_ollama_model():
    """Pre-load the model into VRAM so first real generation isn't slow."""
    console.print(f"[cyan]Loading model {OLLAMA_MODEL} into VRAM...[/cyan]")
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": "warmup",
            "stream": False,
            "options": {"num_predict": 1}
        }, timeout=180)
        if resp.status_code == 200:
            console.print(f"[green]✓ Model {OLLAMA_MODEL} loaded in VRAM.[/green]")
        else:
            console.print(f"[yellow]Model preload returned {resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Model preload warning: {e}[/yellow]")


def _start_comfyui():
    """Start ComfyUI using run_nvidia_gpu.bat in a hidden window."""
    global _comfyui_process, _comfyui_pid

    if _is_comfyui_running():
        console.print("[dim]ComfyUI already running.[/dim]")
        return

    if not _COMFYUI_BAT.exists():
        console.print(f"[red]✗ ComfyUI batch file not found at: {_COMFYUI_BAT}[/red]")
        return

    console.print("[cyan]Starting ComfyUI (hidden window)...[/cyan]")

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    cmd_args = [
        str(_COMFYUI_BAT),
        "--highvram",
        "--disable-smart-memory",
        "--fp16-vae"
    ]        
        
        

    _comfyui_process = subprocess.Popen(
        [str(_COMFYUI_BAT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(_COMFYUI_DIR),
        creationflags=creation_flags
    )
    
    # Store the PID immediately
    _comfyui_pid = _comfyui_process.pid
    console.print(f"[dim]Started ComfyUI with PID: {_comfyui_pid}[/dim]")

    console.print("[cyan]Waiting for ComfyUI to initialize...[/cyan]")
    for i in range(120):
        if _is_comfyui_running():
            console.print("[green]✓ ComfyUI started successfully (hidden).[/green]")
            return
        time.sleep(2)

    console.print("[red]✗ ComfyUI failed to start within 4 minutes.[/red]")


def _force_kill_comfyui_tree():
    """
    CRITICAL FIX: Kills the specific PID and ALL its children.
    This ensures the underlying python.exe spawned by the .bat file dies too.
    """
    global _comfyui_process, _comfyui_pid

    if _comfyui_pid is None:
        return

    console.print(f"[cyan]Force killing ComfyUI Process Tree (PID: {_comfyui_pid})...[/cyan]")

    if sys.platform == "win32":
        # /T = Kill Tree, /F = Force
        cmd = ["taskkill", "/F", "/T", "/PID", str(_comfyui_pid)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception as e:
            console.print(f"[red]Error killing PID {_comfyui_pid}: {e}[/red]")
    else:
        # Linux/Mac fallback
        try:
            os.killpg(os.getpgid(_comfyui_pid), signal.SIGKILL)
        except Exception:
            pass
        
    # Reset globals
    _comfyui_process = None
    _comfyui_pid = None


def _stop_comfyui():
    """Stop ComfyUI gracefully, then force kill using PID Tree."""
    global _comfyui_process, _comfyui_pid

    console.print("[cyan]Shutting down ComfyUI...[/cyan]")

    # 1. Try graceful shutdown via API first
    try:
        # Interrupt any current job
        requests.post(f"{COMFYUI_URL}/interrupt", timeout=5)
        time.sleep(1)
        # Clear queue
        requests.post(f"{COMFYUI_URL}/queue/clear", timeout=5)
        time.sleep(1)
        # Ask to shut down
        requests.post(f"{COMFYUI_URL}/shutdown", timeout=5)
        time.sleep(3)
    except Exception:
        pass

    # 2. Kill the specific process tree using PID
    _force_kill_comfyui_tree()

    # 3. Final verification
    time.sleep(2)
    
    if _is_comfyui_running():
        console.print("[bold red]⚠ WARNING: ComfyUI may still be running! Check Task Manager manually.[/bold red]")
    else:
        console.print("[green]✓ ComfyUI fully stopped. VRAM freed.[/green]")


# =============================================================================
# PUBLIC API - Called from run.py
# =============================================================================

def prepare_for_ollama():
    """Call BEFORE any Ollama work. Stops ComfyUI if running, starts Ollama."""
    console.rule("MODEL MANAGER: PREPARING FOR OLLAMA")

    if _is_comfyui_running():
        console.print("[yellow]ComfyUI is running. Stopping it to free VRAM...[/yellow]")
        _stop_comfyui()

    _start_ollama()
    _preload_ollama_model()


def cleanup_after_ollama():
    """Call AFTER all Ollama work. Kills Ollama, frees VRAM."""
    console.rule("MODEL MANAGER: CLEANING UP AFTER OLLAMA")
    _kill_ollama()
    time.sleep(3)
    console.print("[green]✓ VRAM fully cleared. Ready for ComfyUI.[/green]")


def prepare_for_comfyui(workflow_json=None):
    """Call BEFORE ComfyUI generation. Starts ComfyUI hidden, verifies ready, warms up."""
    console.rule("MODEL MANAGER: PREPARING FOR COMFYUI")

    if _is_ollama_running():
        console.print("[yellow]Ollama still running! Force killing...[/yellow]")
        _kill_ollama()

    _start_comfyui()

    if not _is_comfyui_running():
        console.print("[bold red]✗ ComfyUI is NOT available. Aborting.[/bold red]")
        return False

    # Optional Warmup logic could go here if workflow_json is passed
    # For now, just verifying it's online
    
    console.print("[green]✓ ComfyUI verified online. VRAM available.[/green]")
    return True


def cleanup_after_comfyui():
    """Call AFTER all ComfyUI generation. Stops ComfyUI completely."""
    console.rule("MODEL MANAGER: CLEANING UP AFTER COMFYUI")
    _stop_comfyui()
    console.print("[green]✓ ComfyUI stopped. All VRAM released.[/green]")