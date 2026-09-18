from shea.security.content_trust import UntrustedExternalData


def test_untrusted_external_data_escaping() -> None:
    data = UntrustedExternalData(
        source_url="https://evil.com",
        content_type="text/html",
        payload="<script>alert(1)</script> ```python\nprint(1)\n```"
    )
    
    safe = data.to_safe_prompt_block()
    
    assert "<UNTRUSTED_DATA source='https://evil.com' type='text/html'>" in safe
    assert "</UNTRUSTED_DATA>" in safe
    assert "<script>" not in safe
    assert "&lt;script&gt;" in safe
    assert "```python" not in safe
    assert "\\`\\`\\`python" in safe

def test_untrusted_external_data_to_dict() -> None:
    data = UntrustedExternalData(
        source_url="https://evil.com",
        content_type="text/html",
        payload="12345"
    )
    
    d = data.to_dict()
    assert d["source_url"] == "https://evil.com"
    assert d["content_type"] == "text/html"
    assert d["raw_payload_length"] == "5"
    assert "<UNTRUSTED_DATA" in d["safe_block"]

