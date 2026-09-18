from __future__ import annotations

import sys

from shea.audio.adapters.linux_tts import LinuxAudioSynthesizer
from shea.audio.adapters.mac_tts import MacOsAudioSynthesizer
from shea.audio.adapters.stub_tts import StubAudioSynthesizer
from shea.audio.adapters.windows_tts import WindowsAudioSynthesizer
from shea.audio.ports import AudioSynthesizer


def get_default_audio_synthesizer() -> AudioSynthesizer:
    """Return the correct native TTS adapter for the current OS."""
    _os = sys.platform
    if _os == "darwin":
        return MacOsAudioSynthesizer()
    elif _os.startswith("linux"):
        return LinuxAudioSynthesizer()
    elif _os == "win32":
        return WindowsAudioSynthesizer()
    else:
        return StubAudioSynthesizer()

__all__ = ["get_default_audio_synthesizer"]