from __future__ import annotations

import logging
import subprocess

from shea.audio.ports import AudioSynthesizer

logger = logging.getLogger(__name__)

class WindowsAudioSynthesizer(AudioSynthesizer):
    """Text-to-Speech adapter using Windows native SAPI (via PowerShell)."""
    
    def synthesize(self, text: str) -> None:
        if not text:
            return
            
        logger.info("Synthesizing speech via Windows PowerShell System.Speech")
        try:
            # Escape single quotes for PowerShell
            escaped_text = text.replace("'", "''")
            ps_command = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{escaped_text}')"
            subprocess.run(["powershell", "-Command", ps_command], check=True)
        except Exception as e:
            logger.error(f"Failed to synthesize speech: {e}")
