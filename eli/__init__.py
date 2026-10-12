"""ELI. Importing the package makes printing safe (see _streams_take_any_text)."""
import sys as _sys


def _streams_take_any_text() -> None:
    """A print never stops the program. ELI prints arrows, ticks and emoji, and a stream that is
    not Unicode raised UnicodeEncodeError on the first one. On Windows that is every redirected
    or piped output (it uses the legacy code page): the installer's last step died on an arrow
    whenever something was reading its output. What such a stream cannot show is written as "?".
    The packaged apps do this earlier, in their start-up hook."""
    for stream in (_sys.stdout, _sys.stderr):
        encoding = str(getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if (stream is None or encoding.startswith("utf") or getattr(stream, "errors", "") != "strict"
                or not hasattr(stream, "reconfigure")):
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            import logging
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)


_streams_take_any_text()
