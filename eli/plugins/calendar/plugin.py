"""Calendar plugin: events and reminders in ELI's own agenda (eli.runtime.agenda).

The plugin used to keep a separate .ics file through the `ics` library, which is not part of a
standard install, while the executor's ADD_EVENT and LIST_EVENTS answered "not configured".
Both now go to the one local store; its events are mirrored to a standard .ics file.
"""
from eli.plugins.base import Plugin


class CalendarPlugin(Plugin):
    name = "calendar"
    description = "Calendar event management"

    def list_events(self, args: dict) -> dict:
        """What is on the calendar for the period asked about."""
        from eli.runtime import agenda
        return agenda.do_list_events(args or {})

    def add_event(self, args: dict) -> dict:
        """Add an event from words ("dentist on friday at 2pm") or from title/date/time fields."""
        from eli.runtime import agenda
        return agenda.do_add_event(args or {})

    actions = {
        "list": list_events,
        "add": add_event,
    }
