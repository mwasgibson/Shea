from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from shea.audio.ports import AudioSource, AudioTranscriber, WakeWordDetector
from shea.bootstrap import SheaRuntime
from shea.contracts.models import Intent
from shea.events.contracts import Event

logger = logging.getLogger(__name__)


class MockWakeWordDetector:
    def __init__(self, trigger_word: str = "hey shea"):
        self.trigger = trigger_word

    def listen_for_wake_word(self) -> bool:
        print(
            f"\n[Audio] Listening for wake word ('{self.trigger}')... "
            "(Press Enter to simulate wake)"
        )
        input()
        return True


class MockAudioSource:
    def record_until_silence(self) -> bytes:
        print("[Audio] *BEEP* Recording... (Type your simulated speech and press Enter)")
        text = input("> ")
        return text.encode("utf-8")


class MockTranscriber:
    def transcribe(self, audio_data: bytes) -> str:
        return audio_data.decode("utf-8")


class AudioInteractionService:
    """The main loop for audio interaction.
    
    Coordinates wake-word detection, recording, transcription, and intent broadcasting.
    """

    def __init__(
        self,
        runtime: SheaRuntime,
        detector: WakeWordDetector | None = None,
        source: AudioSource | None = None,
        transcriber: AudioTranscriber | None = None,
    ):
        self.runtime = runtime
        self.detector = detector or MockWakeWordDetector()
        self.source = source or MockAudioSource()
        self.transcriber = transcriber or MockTranscriber()

    def start_loop(self) -> None:
        """Starts the infinite listen/transcribe/dispatch loop."""
        logger.info("AudioInteractionService loop started.")
        try:
            while True:
                # 1. Block until wake word
                if self.detector.listen_for_wake_word():
                    logger.info("Wake word detected!")
                    
                    # 2. Record until silence
                    audio_buffer = self.source.record_until_silence()
                    
                    # 3. Transcribe
                    text = self.transcriber.transcribe(audio_buffer)
                    if not text.strip():
                        continue
                        
                    logger.info(f"Transcribed: {text}")
                    
                    # 4. Dispatch Intent
                    now = datetime.now(UTC)
                    intent_id = uuid4().hex
                    intent = Intent(
                        id=intent_id,
                        task_id=uuid4().hex,
                        type="chat",
                        goal=text,
                        source="audio",
                        created_at=now,
                    )
                    self.runtime.event_bus.publish(
                        Event(
                            event_id=uuid4().hex,
                            event_type="interaction.intent_received",
                            source="audio",
                            timestamp=now,
                            payload={
                                "intent_id": intent.id,
                                "task_id": intent.task_id,
                                "goal": intent.goal,
                            },
                            correlation_id=intent.id,
                        )
                    )
                    
        except KeyboardInterrupt:
            logger.info("Audio loop terminated by user.")