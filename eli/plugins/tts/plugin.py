"""
TTS (Text-to-Speech) plugin for ELI.
Uses pyttsx3 for offline TTS.
"""
from typing import Dict, Any
from eli.plugins.base import Plugin

try:
    import pyttsx3
    _engine = None

    def _get_engine():
        global _engine
        if _engine is None:
            _engine = pyttsx3.init()
        return _engine

except ImportError:
    pyttsx3 = None
    _get_engine = None


class TTSPlugin(Plugin):
    name = "tts"
    description = "Text-to-speech: speaks text aloud using pyttsx3"

    def handle(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = args.get("text") or args.get("content") or args.get("message") or ""
        if not text:
            return {"ok": False, "content": "No text provided to speak"}

        if pyttsx3 is None:
            return {"ok": False, "content": "pyttsx3 not installed — TTS unavailable"}

        try:
            engine = _get_engine()
            engine.say(text)
            engine.runAndWait()
            return {"ok": True, "content": f"Spoke: {text[:60]}"}
        except Exception as e:
            return {"ok": False, "content": f"TTS error: {e}"}

    actions = {"speak": handle, "say": handle, "tts": handle}
