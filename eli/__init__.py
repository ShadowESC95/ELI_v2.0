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


def _no_outside_reporting() -> None:
    """Libraries ELI carries must not report to their makers. onnxruntime (the speech model's voice
    detection) sends usage telemetry to Microsoft's collector from native code, which the network
    guard cannot see; Hugging Face Hub, Gradio, OpenTelemetry, Chroma and Scarf-instrumented packages
    have their own switches. Set here, before any of them can load. Hosts that only collect telemetry
    are also refused by name in eli.core.netguard, whatever the network setting."""
    import os
    for name, value in (("ORT_DISABLE_TELEMETRY", "1"), ("HF_HUB_DISABLE_TELEMETRY", "1"),
                        ("GRADIO_ANALYTICS_ENABLED", "False"), ("DO_NOT_TRACK", "1"),
                        ("OTEL_SDK_DISABLED", "true"), ("ANONYMIZED_TELEMETRY", "False"),
                        ("SCARF_NO_ANALYTICS", "true")):
        os.environ[name] = value


_no_outside_reporting()
