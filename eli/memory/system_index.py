#!/usr/bin/env python3
"""
System Inventory – Auto‑discovers applications, executables, and directories.
Runs at startup and periodically.
Stores in ~/.config/eli/system_index.db (SQLite).

ELI will query this before falling back to gtk‑launch or direct commands.
"""

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Any
import time
import json

DB_PATH = Path(os.environ.get("ELI_SYSTEM_INDEX", str(Path(os.environ.get("ELI_DB_DIR", "artifacts/db")) / "system_index.sqlite3")))

class SystemIndex:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()
    
    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS desktop_apps (
                id INTEGER PRIMARY KEY,
                name TEXT,
                exec TEXT,
                desktop_id TEXT,
                categories TEXT,
                last_used REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS executables (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_dirs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS recent_files (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT,
                last_opened REAL
            )
        """)
        self.conn.commit()
    
    def scan_desktop_files(self):
        """Scan all .desktop files in standard locations."""
        paths = [
            "/usr/share/applications"  # Linux-only,
            "/usr/local/share/applications",
            str(Path.home() / ".local/share/applications"),
            str(Path.home() / ".local/share/flatpak/exports/share/applications"),
            "/var/lib/flatpak/exports/share/applications",
        ]
        for base in paths:
            if not os.path.exists(base):
                continue
            for file in Path(base).glob("*.desktop"):
                try:
                    content = file.read_text(errors="ignore")
                    name = None
                    exec_cmd = None
                    categories = None
                    for line in content.splitlines():
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1]
                        elif line.startswith("Exec="):
                            exec_cmd = line.split("=", 1)[1].split("%")[0].strip()
                        elif line.startswith("Categories="):
                            categories = line.split("=", 1)[1]
                    if name and exec_cmd:
                        self.conn.execute("""
                            INSERT OR REPLACE INTO desktop_apps (name, exec, desktop_id, categories)
                            VALUES (?, ?, ?, ?)
                        """, (name, exec_cmd, file.stem, categories))
                except Exception:
                    continue
        self.conn.commit()
    
    def scan_executables(self):
        """Scan all directories in $PATH for executables."""
        # os.pathsep so the split is correct on every OS (":" on Linux/macOS,
        # ";" on Windows) — a hard-coded ":" left Windows installs unindexed.
        paths = os.environ.get("PATH", "").split(os.pathsep)
        for p in paths:
            if not os.path.isdir(p):
                continue
            try:
                for file in os.listdir(p):
                    full = os.path.join(p, file)
                    if os.path.isfile(full) and os.access(full, os.X_OK):
                        self.conn.execute("""
                            INSERT OR IGNORE INTO executables (name, path)
                            VALUES (?, ?)
                        """, (file, full))
            except (PermissionError, FileNotFoundError):
                continue
        self.conn.commit()
    
    def _xdg_user_dirs(self) -> Dict[str, str]:
        """Linux: resolve localized user directories from ~/.config/user-dirs.dirs
        (XDG). Returns {canonical_key: real_path}. Empty on non-Linux or when the
        file is absent — so the English defaults stand on macOS/Windows."""
        mapping: Dict[str, str] = {}
        cfg = Path.home() / ".config" / "user-dirs.dirs"
        if not cfg.is_file():
            return mapping
        key_map = {
            "XDG_DESKTOP_DIR": "desktop", "XDG_DOWNLOAD_DIR": "downloads",
            "XDG_DOCUMENTS_DIR": "documents", "XDG_MUSIC_DIR": "music",
            "XDG_PICTURES_DIR": "pictures", "XDG_VIDEOS_DIR": "videos",
            "XDG_PUBLICSHARE_DIR": "public", "XDG_TEMPLATES_DIR": "templates",
        }
        try:
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in key_map:
                    continue
                v = v.strip().strip('"').replace("$HOME", str(Path.home()))
                if v:
                    mapping[key_map[k]] = v
        except Exception:
            pass
        return mapping

    def scan_user_dirs(self):
        """Add common user directories (localized where the OS exposes it)."""
        dirs = {
            "home": str(Path.home()),
            "desktop": str(Path.home() / "Desktop"),
            "downloads": str(Path.home() / "Downloads"),
            "documents": str(Path.home() / "Documents"),
            "music": str(Path.home() / "Music"),
            "pictures": str(Path.home() / "Pictures"),
            "videos": str(Path.home() / "Videos"),
            "public": str(Path.home() / "Public"),
            "templates": str(Path.home() / "Templates"),
        }
        # Overlay localized XDG paths on Linux so non-English folder names
        # ("Téléchargements", "Bilder", …) resolve under the canonical key.
        try:
            dirs.update(self._xdg_user_dirs())
        except Exception:
            pass
        for name, path in dirs.items():
            if os.path.exists(path):
                self.conn.execute("""
                    INSERT OR REPLACE INTO user_dirs (name, path)
                    VALUES (?, ?)
                """, (name, path))
        self.conn.commit()
    
    def find_app(self, query: str) -> Optional[Dict[str, Any]]:
        """Search for an app by name or desktop_id."""
        if not query:
            return None
        q = f"%{query}%"
        # Try exact match first
        cur = self.conn.execute("""
            SELECT name, exec, desktop_id FROM desktop_apps
            WHERE name = ? OR desktop_id = ?
            LIMIT 1
        """, (query, query))
        row = cur.fetchone()
        if row:
            return {"name": row[0], "cmd": row[1], "desktop_id": row[2]}
        # Then fuzzy match
        cur = self.conn.execute("""
            SELECT name, exec, desktop_id FROM desktop_apps
            WHERE name LIKE ? OR desktop_id LIKE ?
            LIMIT 1
        """, (q, q))
        row = cur.fetchone()
        if row:
            return {"name": row[0], "cmd": row[1], "desktop_id": row[2]}
        # Fallback to executables
        cur = self.conn.execute("""
            SELECT name, path FROM executables WHERE name = ? LIMIT 1
        """, (query,))
        row = cur.fetchone()
        if row:
            return {"name": row[0], "cmd": [row[1]], "desktop_id": None}
        cur = self.conn.execute("""
            SELECT name, path FROM executables WHERE name LIKE ? LIMIT 1
        """, (q,))
        row = cur.fetchone()
        if row:
            return {"name": row[0], "cmd": [row[1]], "desktop_id": None}
        return None
    
    def find_path(self, query: str) -> Optional[str]:
        """Find a user directory by name."""
        if not query:
            return None
        q = f"%{query}%"
        # Try exact match
        cur = self.conn.execute("""
            SELECT path FROM user_dirs WHERE name = ? LIMIT 1
        """, (query,))
        row = cur.fetchone()
        if row:
            return row[0]
        # Then fuzzy
        cur = self.conn.execute("""
            SELECT path FROM user_dirs WHERE name LIKE ? LIMIT 1
        """, (q,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None
    
    def refresh(self):
        """Run all scans – call this at startup and periodically."""
        self.scan_desktop_files()
        self.scan_executables()
        self.scan_user_dirs()
        # Optionally scan recent files (can be added later)
        self.conn.commit()

# ----------------------------------------------------------------------
# Singleton and public API
# ----------------------------------------------------------------------
_index = None

def get_index() -> SystemIndex:
    global _index
    if _index is None:
        _index = SystemIndex()
    return _index

def refresh_index():
    """Convenience function to refresh the index."""
    get_index().refresh()

def find_app(query: str) -> Optional[Dict[str, Any]]:
    """Public API to find an app."""
    return get_index().find_app(query)

def find_path(query: str) -> Optional[str]:
    """Public API to find a directory."""
    return get_index().find_path(query)

# If run directly, perform a scan and print summary
if __name__ == "__main__":
    print("🔍 Scanning system inventory...")
    idx = get_index()
    idx.refresh()
    
    # Counts
    _r = idx.conn.execute("SELECT COUNT(*) FROM desktop_apps").fetchone(); apps = _r[0] if _r else 0
    _r = idx.conn.execute("SELECT COUNT(*) FROM executables").fetchone(); exes = _r[0] if _r else 0
    _r = idx.conn.execute("SELECT COUNT(*) FROM user_dirs").fetchone(); dirs = _r[0] if _r else 0
    
    print(f"✅ Found {apps} desktop applications")
    print(f"✅ Found {exes} executables in PATH")
    print(f"✅ Found {dirs} user directories")
    print(f"📁 Index stored at: {DB_PATH}")
