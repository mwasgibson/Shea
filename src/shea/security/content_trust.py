from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UntrustedExternalData:
    """Wraps external content fetched from outside the isolation boundary.
    
    This structural wrapper ensures that external content (DOM, HTTP responses)
    remains strictly DATA and is never treated as INSTRUCTION by the prompt parser
    when fed back to an LLM.
    """
    source_url: str
    content_type: str
    payload: str
    
    def to_safe_prompt_block(self) -> str:
        """Escapes the payload and wraps it in a non-executable XML-like structure."""
        # Escape characters that might prematurely close the block or trigger markdown/HTML execution
        escaped = self.payload.replace("```", "\\`\\`\\`").replace("<", "&lt;").replace(">", "&gt;")
        
        return (
            f"<UNTRUSTED_DATA source='{self.source_url}' type='{self.content_type}'>\n"
            f"{escaped}\n"
            f"</UNTRUSTED_DATA>"
        )

    def to_dict(self) -> dict[str, str]:
        """Serialize for inclusion in an ExecutionReceipt evidence payload."""
        return {
            "source_url": self.source_url,
            "content_type": self.content_type,
            "safe_block": self.to_safe_prompt_block(),
            "raw_payload_length": str(len(self.payload)),
        }