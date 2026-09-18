from __future__ import annotations

import logging
import subprocess

from shea.audio.ports import AudioSynthesizer

logger = logging.getLogger(__name__)

class LinuxAudioSynthesizer(AudioSynthesizer):
    """Text-to-Speech adapter using Linux native spd-say (Speech Dispatcher) or espeak."""
    
    def synthesize(self, text: str) -> None:
        if not text:
            return
            
        logger.info("Synthesizing speech via Linux native TTS")
        try:
            # Try spd-say first (standard on desktop environments)
            try:
                subprocess.run(["spd-say", "-w", text], check=True)
                return
            except FileNotFoundError:
                pass
                
            # Fallback to espeak
            subprocess.run(["espeak", text], check=True)
        except Exception as e:
            logger.error(f"Failed to synthesize speech: {e}")
