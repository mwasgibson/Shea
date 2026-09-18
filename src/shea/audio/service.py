from __future__ import annotations

import logging

from shea.audio.ports import AudioSource, AudioTranscriber, WakeWordDetector
from shea.bootstrap import SheaRuntime

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
                    
                    # 4. Process Request
                    # Follows the unified pipeline: Text -> Intent -> Plan -> Execute
                    self.runtime.interaction_service.handle_text(
                        text=text,
                        session_id="audio_session",
                        actor="local_user",
                        explicit_user_ack=False, # Audio is usually hands-free
                    )
                    
        except KeyboardInterrupt:
            logger.info("Audio loop terminated by user.")