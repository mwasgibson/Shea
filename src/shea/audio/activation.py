from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from shea.audio.ports import AudioSource, AudioTranscriber


class ActivationState(StrEnum):
    IDLE = "IDLE"
    VAD = "VAD"
    LISTENING = "LISTENING"
    STT = "STT"
    HANDOFF = "HANDOFF"
    INTENT = "INTENT"
    SPEAKING = "SPEAKING"  # TTS; barge-in can return to LISTENING
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


_TRANSITIONS: dict[ActivationState, frozenset[ActivationState]] = {
    ActivationState.IDLE: frozenset({ActivationState.VAD, ActivationState.SHUTDOWN}),
    ActivationState.VAD: frozenset({ActivationState.LISTENING, ActivationState.IDLE, ActivationState.ERROR}),
    ActivationState.LISTENING: frozenset({ActivationState.STT, ActivationState.IDLE, ActivationState.ERROR}),
    ActivationState.STT: frozenset({ActivationState.HANDOFF, ActivationState.ERROR, ActivationState.IDLE}),
    ActivationState.HANDOFF: frozenset({ActivationState.INTENT, ActivationState.ERROR}),
    ActivationState.INTENT: frozenset({ActivationState.SPEAKING, ActivationState.IDLE, ActivationState.ERROR}),
    ActivationState.SPEAKING: frozenset({ActivationState.LISTENING, ActivationState.IDLE, ActivationState.ERROR}),  # barge-in
    ActivationState.ERROR: frozenset({ActivationState.IDLE, ActivationState.SHUTDOWN}),
    ActivationState.SHUTDOWN: frozenset(),
}


class IllegalActivationTransition(Exception):
    pass


@dataclass
class ActivationEvent:
    name: str
    payload: dict[str, Any]


class ActivationController:
    """Research activation pipeline (mic → VAD → STT → intent handoff)."""

    def __init__(
        self,
        *,
        source: AudioSource,
        transcriber: AudioTranscriber,
        on_intent: Callable[[str], None],
        wake_word: str | None = None,
    ) -> None:
        self._source = source
        self._stt = transcriber
        self._on_intent = on_intent
        self._wake_word = (wake_word or "").lower() or None
        self.state = ActivationState.IDLE

    def _advance(self, new: ActivationState) -> None:
        allowed = _TRANSITIONS[self.state]
        if new not in allowed:
            raise IllegalActivationTransition(f"{self.state} → {new}")
        self.state = new

    def run_once(self) -> str | None:
        """One utterance cycle. Returns transcript or None."""
        self._advance(ActivationState.VAD)
        self._advance(ActivationState.LISTENING)
        audio = self._source.record_until_silence()
        self._advance(ActivationState.STT)
        text = self._stt.transcribe(audio).strip()
        if not text:
            self._advance(ActivationState.IDLE)
            return None
        if self._wake_word and self._wake_word not in text.lower():
            self._advance(ActivationState.IDLE)
            return None
        self._advance(ActivationState.HANDOFF)
        self._advance(ActivationState.INTENT)
        self._on_intent(text)
        self._advance(ActivationState.IDLE)
        return text

    def barge_in_from_speaking(self) -> None:
        if self.state is ActivationState.SPEAKING:
            self._advance(ActivationState.LISTENING)

    def shutdown(self) -> None:
        self.state = ActivationState.SHUTDOWN