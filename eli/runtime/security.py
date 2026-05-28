import os
import re
from pathlib import Path
from typing import Set, Optional, Tuple, List, Dict
import subprocess
import logging

logger = logging.getLogger(__name__)

class SecurityManager:
    """Centralized security and sandboxing"""
    
    def __init__(self):
        self.project_root = self._get_project_root()
        self.allowed_roots = self._get_allowed_roots()
        self.allowed_commands = self._get_allowed_commands()
        self.allowed_apps = self._get_allowed_apps()
        if not self.allowed_commands and os.environ.get("ELI_FULL_CONTROL", "0") != "1":
            logger.warning(
                "SecurityManager: ELI_ALLOWED_CMDS is unset — all shell commands are permitted. "
                "Set ELI_ALLOWED_CMDS=<cmd1,cmd2,...> to restrict, or ELI_FULL_CONTROL=1 to silence this warning."
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
        # Full control mode bypasses all restrictions
        if os.environ.get("ELI_FULL_CONTROL", "0") == "1":
            return True
        
        # Wildcard allows everything
        if "*" in self.allowed_commands:
            return True
        
        # ELI_ALLOWED_CMDS is unset — pass-through mode, all shell commands are permitted.
        # Set ELI_ALLOWED_CMDS to a comma-separated list to enforce a whitelist.
        # Set ELI_FULL_CONTROL=1 to explicitly bypass all command restrictions.
        if not self.allowed_commands:
            return True
        
        # Check normalized command
        normalized = os.path.normpath(command)
        return normalized in self.allowed_commands
    
    def is_app_allowed(self, app_name: str) -> bool:
        """Check if application is allowed to open"""
        # Full control mode
        if os.environ.get("ELI_FULL_CONTROL", "0") == "1":
            return True
        
        # Empty allowed list means use default safe apps
        if not self.allowed_apps:
            return self._is_default_safe_app(app_name)
        
        return app_name.lower() in self.allowed_apps
    
    def _is_default_safe_app(self, app_name: str) -> bool:
        """Default safe applications"""
        safe_apps = {
            "settings", "gnome-control-center",
            "nautilus", "files",
            "gedit", "texteditor",
            "calculator", "gnome-calculator",
            "terminal", "gnome-terminal", "xterm",
            "browser", "firefox", "chrome",
            "thunderbird", "mail",
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