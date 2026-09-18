from __future__ import annotations

import logging
import subprocess

from shea.audio.ports import AudioSynthesizer

logger = logging.getLogger(__name__)

class MacOsAudioSynthesizer(AudioSynthesizer):
    """Text-to-Speech adapter using the native macOS `say` command."""
    
    def synthesize(self, text: str) -> None:
        if not text:
            return
            
        logger.info("Synthesizing speech via macOS 'say'")
        try:
            # -v Fiona is a good female voice on macOS, or Alex for male.
            # We'll just use the default voice to avoid missing voice errors.
            subprocess.run(["say", text], check=True)
        except Exception as e:
            logger.error(f"Failed to synthesize speech: {e}")