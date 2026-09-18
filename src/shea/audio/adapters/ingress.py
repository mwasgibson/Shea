from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from shea.audio.ports import AudioSource, AudioTranscriber

logger = logging.getLogger(__name__)

# Assign sys.platform to a string variable to prevent Pylance from statically 
# evaluating OS-specific branches as "structurally unreachable" on the developer's machine.
_platform: str = sys.platform

class SubprocessAudioSource(AudioSource):
    """Captures audio from the default system microphone using native tools.
    
    Relies on SoX (rec) or FFmpeg depending on the platform, natively handling
    Voice Activity Detection (recording until silence is detected).
    """

    def record_until_silence(self) -> bytes:
        logger.info("Listening for audio input...")
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            if _platform.startswith("linux") or _platform == "darwin":
                # Attempt to use SoX (`rec`) with silence detection
                # silence 1 0.1 3% 1 2.0 3% means:
                # wait for 1 period of audio > 3% volume lasting 0.1s
                # then stop after 1 period of silence < 3% lasting 2.0s
                try:
                    subprocess.run(
                        [
                            "rec", "-q", tmp_path,
                            "silence", "1", "0.1", "3%", "1", "2.0", "3%"
                        ],
                        check=True,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    # Fallback to ffmpeg for 5 seconds if SoX is missing
                    logger.warning("SoX (rec) not found, falling back to 5s ffmpeg recording")
                    # macOS uses avfoundation, linux uses alsa/pulse
                    fmt = "avfoundation" if _platform == "darwin" else "alsa"
                    dev = ":0" if _platform == "darwin" else "default"
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-f", fmt, "-i", dev,
                            "-t", "5", tmp_path
                        ],
                        check=True,
                        stderr=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                    )
            elif _platform.startswith("win"):
                # Windows fallback (ffmpeg with dshow)
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-f", "dshow", "-i", "audio=default",
                        "-t", "5", tmp_path
                    ],
                    check=True,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
            else:
                raise RuntimeError(f"Unsupported audio platform: {_platform}")

            with open(tmp_path, "rb") as f:
                return f.read()
                
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class DummyWhisperTranscriber(AudioTranscriber):
    """Stub for Whisper API transcription.
    
    In a fully configured environment, this would post the wav bytes to 
    an STT endpoint (like OpenAI's v1/audio/transcriptions).
    """

    def transcribe(self, audio_data: bytes) -> str:
        if not audio_data:
            return ""
            
        logger.info(f"Transcribing {len(audio_data)} bytes of audio data...")
        # Since we don't have an active Whisper endpoint or local model loaded in this stub,
        # we return a safe mock to satisfy the pipeline end-to-end without failing.
        return "(Audio successfully captured, but transcription endpoint is mock)"