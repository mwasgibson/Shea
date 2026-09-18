from __future__ import annotations

from typing import cast

from shea.audio.ports import AudioSynthesizer
from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.registry import ToolDeclaration, ToolRegistry


def register_audio_tools(registry: ToolRegistry, synthesizer: AudioSynthesizer) -> None:
    def handle_speak(request: ToolRequest) -> ToolResponse:
        text = request.arguments.get("text")
        if not text or not isinstance(text, str):
            return ToolResponse(success=False, error="Argument 'text' must be a string.", data=None)
            
        try:
            synthesizer.synthesize(text)
            return ToolResponse(success=True, data="Speech synthesized successfully.", error=None)
        except Exception as e:
            return ToolResponse(success=False, error=str(e), data=None)
            
    declaration = cast(ToolDeclaration, {
        "tool_name": "audio.speak",
        "description": "Speak text out loud to the user using Text-to-Speech (TTS).",
        "schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to speak out loud."
                }
            },
            "required": ["text"]
        },
    })
    registry.register(
        declaration=declaration,
        handler=handle_speak,
    )
