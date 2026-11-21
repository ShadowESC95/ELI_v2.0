"""
TTS (Text-to-Speech) plugin for ELI.

Its actions are ELI's own SPEAK: the text goes to ELI's voice (eli.perception.tts_router, the
voice chosen in Settings). It used to speak through pyttsx3, a second speech engine with none of
ELI's voices, and never ran, because the executor answers SPEAK first.
"""
from typing import Dict, Any
from eli.plugins.base import Plugin


class TTSPlugin(Plugin):
    name = "tts"
    description = "Text-to-speech: speaks text aloud in ELI's voice"

    def handle(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from eli.execution.executor_enhanced import execute
        return execute("SPEAK", dict(args or {}))

    actions = {"speak": handle, "say": handle, "tts": handle}
