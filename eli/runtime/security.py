import os
import re
from pathlib import Path
from typing import Set, Optional, Tuple, List, Dict
import subprocess
import logging

logger = logging.getLogger(__name__)


def _sec_full_control() -> bool:
    """ELI Full Control (the GUI toggle / `full_control` setting) — single source
    of truth, no environment variable. Never raises."""
    try:
        from eli.core.full_control import is_full_control
        return bool(is_full_control())
    except Exception:
        return False

class SecurityManager:
    """Centralized security and sandboxing"""
    
    def __init__(self):
        self.project_root = self._get_project_root()
        self.allowed_roots = self._get_allowed_roots()
        self.allowed_commands = self._get_allowed_commands()
        self.allowed_apps = self._get_allowed_apps()
        if not self.allowed_commands and not _sec_full_control():
            logger.warning(
                "SecurityManager: ELI_ALLOWED_CMDS is unset — shell commands are BLOCKED (fail-closed). "
                "Enable the ELI Full Control toggle to allow all commands, or set ELI_ALLOWED_CMDS=cmd1,cmd2 to whitelist specific ones."
            )
        
    def _get_project_root(self) -> Path:
        """Get ELI project root"""
        root = os.environ.get("ELI_ROOT")
        if root:
            return Path(root).resolve()
        
        # Fallback: parent of this file
        return Path(__file__).resolve().parents[2]
    
    def _get_allowed_roots(self) -> List[Path]:
        """Get allowed filesystem roots"""
        roots = [self.project_root, Path.home().resolve()]
        
        extra = os.environ.get("ELI_ALLOW_ROOTS", "")
        for p in extra.split(":"):
            if p.strip():
                try:
                    roots.append(Path(p).expanduser().resolve())
                except Exception as e:
                    logger.warning(f"Invalid allowed root {p}: {e}")
        
        return roots
    
    def _get_allowed_commands(self) -> Set[str]:
        """Parse allowed commands with normalization"""
        raw = os.environ.get("ELI_ALLOWED_CMDS", "").strip()
        if not raw:
            return set()  # Empty means no restrictions (for now)
        
        allowed = set()
        
        # Split by commas or spaces
        parts = [p.strip() for p in re.split(r'[,\s]+', raw) if p.strip()]
        
        for cmd in parts:
            if cmd == "*":
                return {"*"}  # Wildcard
            
            # Normalize paths
            normalized = os.path.normpath(cmd)
            allowed.add(normalized)
            
            # Add common variations
            if normalized.startswith("./"):
                allowed.add(normalized[2:])
            else:
                allowed.add(f"./{normalized}")
        
        # Always allow our own venv python
        venv_py = self.project_root / ".venv" / "bin" / "python"
        if venv_py.exists():
            allowed.add(str(venv_py))
            allowed.add("./.venv/bin/python")
        
        return allowed
    
    def _get_allowed_apps(self) -> Set[str]:
        """Parse allowed applications"""
        raw = os.environ.get("ELI_ALLOWED_APPS", "").strip()
        if not raw:
            return set()  # Empty means use default safe apps
        
        apps = {a.strip().lower() for a in raw.split(",") if a.strip()}
        return apps
    
    def is_path_allowed(self, path_str: str) -> Tuple[bool, Optional[Path]]:
        """Check if a path is within allowed roots"""
        try:
            path = Path(path_str).expanduser().resolve()
            
            for root in self.allowed_roots:
                try:
                    path.relative_to(root)
                    return True, path
                except ValueError:
                    continue
            
            return False, path
            
        except Exception as e:
            logger.error(f"Path validation error for {path_str}: {e}")
            return False, None
    
    def is_command_allowed(self, command: str) -> bool:
        """Check if command is allowed to execute"""
        # ELI Full Control (the GUI toggle / `full_control` setting) bypasses all
        # restrictions. Single source of truth — no environment variable.
        try:
            from eli.core.full_control import is_full_control
            if is_full_control():
                return True
        except Exception:
            pass

        # Wildcard allows everything
        if "*" in self.allowed_commands:
            return True

        # ELI_ALLOWED_CMDS is unset and Full Control is off — fail-closed.
        # To allow all commands: enable the ELI Full Control toggle.
        # To allow specific commands: set ELI_ALLOWED_CMDS=cmd1,cmd2,...
        if not self.allowed_commands:
            return False
        
        # Check normalized command
        normalized = os.path.normpath(command)
        return normalized in self.allowed_commands
    
    def is_app_allowed(self, app_name: str) -> bool:
        """Check if application is allowed to open"""
        # ELI Full Control (toggle / setting) — single source of truth.
        if _sec_full_control():
            return True
        
        # Empty allowed list means use default safe apps
        if not self.allowed_apps:
            return self._is_default_safe_app(app_name)
        
        return app_name.lower() in self.allowed_apps
    
    def _is_default_safe_app(self, app_name: str) -> bool:
        """Default safe applications — cross-platform (Linux/macOS/Windows)."""
        safe_apps = {
            # generic / cross-platform aliases
            "settings", "files", "file manager", "filemanager", "explorer",
            "texteditor", "text editor", "editor", "calculator", "calc",
            "terminal", "console", "browser", "mail", "email",
            # Linux
            "gnome-control-center", "nautilus", "dolphin", "nemo", "thunar",
            "gedit", "kate", "gnome-calculator", "kcalc", "gnome-terminal",
            "konsole", "xterm", "firefox", "chrome", "chromium", "thunderbird",
            # macOS
            "finder", "safari", "textedit", "terminal.app", "mail.app",
            "system preferences", "system settings",
            # Windows
            "explorer.exe", "notepad", "notepad.exe", "calc.exe", "cmd",
            "cmd.exe", "powershell", "edge", "msedge", "wordpad", "control",
            "control panel", "outlook",
        }
        return app_name.lower() in safe_apps
    
    def safe_subprocess(self, command: List[str], timeout: int = 30) -> Dict:
        """Run subprocess with security checks"""
        if not command:
            return {"ok": False, "error": "Empty command"}
        
        # Check if first element is allowed
        if not self.is_command_allowed(command[0]):
            return {
                "ok": False, 
                "error": f"Command not allowed: {command[0]}",
                "suggestion": "Add to ELI_ALLOWED_CMDS env var"
            }
        
        try:
            proc = subprocess.run(
                command,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False
            )
            
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
            
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}