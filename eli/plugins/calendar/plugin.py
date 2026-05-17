from eli.core.paths import get_paths
"""
Calendar plugin for ELI – read and create events.
Supports:
- Local ICS files (simple)
- Google Calendar via API (requires credentials)
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from eli.plugins.base import Plugin
from eli.core import config

try:
    import ics
    ICS_AVAILABLE = True
except ImportError:
    ICS_AVAILABLE = False

class CalendarPlugin(Plugin):
    name = "calendar"
    description = "Calendar event management"

    def _get_ics_path(self) -> Path:
        """Get the path to the local ICS file."""
        path = config.get("calendar_ics_path")
        if path:
            return Path(path).expanduser()
        # Default: ~/.config/eli/calendar.ics
        default = Path(os.environ.get("ELI_CALENDAR_FILE", str(get_paths().config_dir / "calendar.ics")))
        default.parent.mkdir(parents=True, exist_ok=True)
        if not default.exists():
            default.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//ELI//EN\nEND:VCALENDAR\n")
        return default

    def list_events(self, args: dict) -> dict:
        """List upcoming events from the calendar."""
        if not ICS_AVAILABLE:
            return {"ok": False, "error": "ics library not installed. Run: pip install ics"}

        days = int(args.get("days", 7))
        path = self._get_ics_path()
        try:
            with open(path) as f:
                calendar = ics.Calendar(f.read())
            now = datetime.now().astimezone()
            events = []
            for event in calendar.events:
                if event.begin.datetime > now:
                    events.append(event)
            events.sort(key=lambda e: e.begin.datetime)
            events = events[:10]  # limit to 10
            if not events:
                return {"ok": True, "content": "No upcoming events."}
            lines = ["Upcoming events:"]
            for e in events:
                dt = e.begin.datetime.strftime("%Y-%m-%d %H:%M")
                lines.append(f"- {dt}: {e.name}")
            return {"ok": True, "content": "\n".join(lines)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_event(self, args: dict) -> dict:
        """Add an event to the calendar."""
        if not ICS_AVAILABLE:
            return {"ok": False, "error": "ics library not installed."}

        summary = args.get("summary", args.get("name", args.get("title", "Event")))
        date_str = args.get("date", args.get("start", ""))
        time_str = args.get("time", "09:00")
        duration = int(args.get("duration", 60))

        if not date_str:
            return {"ok": False, "error": "No date specified."}

        try:
            # Parse date and time
            dt_str = f"{date_str} {time_str}"
            for fmt in ["%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"]:
                try:
                    start = datetime.strptime(dt_str, fmt)
                    break
                except:
                    continue
            else:
                return {"ok": False, "error": "Could not parse date/time. Use YYYY-MM-DD HH:MM."}

            end = start + timedelta(minutes=duration)
            event = ics.Event()
            event.name = summary
            event.begin = start
            event.end = end

            path = self._get_ics_path()
            with open(path) as f:
                calendar = ics.Calendar(f.read())
            calendar.events.add(event)
            with open(path, "w") as f:
                f.write(str(calendar))

            return {"ok": True, "content": f"Event '{summary}' added for {start.strftime('%Y-%m-%d %H:%M')}."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    actions = {
        "list": list_events,
        "add": add_event
    }
