import json
import logging

from shea.observability.context import active_context, get_correlation_id
from shea.observability.tracer import configure_tracing


def test_contextvars_flow():
    with active_context(correlation_id="req-123", task_id="task-456", profile_id="prof-789"):
        assert get_correlation_id() == "req-123"
        
        # Test nested
        with active_context(correlation_id="req-nested"):
            assert get_correlation_id() == "req-nested"
            
        assert get_correlation_id() == "req-123"
        
    assert get_correlation_id() is None

def test_tracer_json(caplog):
    configure_tracing(logging.INFO)
    logger = logging.getLogger("test_logger")
    
    with active_context(correlation_id="trace-123", task_id="tsk-99", profile_id="prof-1"):
        logger.info("Hello world")
        
    # Since caplog captures before formatters in some cases, we just test the ContextVar binding directly.
    # To truly test the formatter we can construct a LogRecord.
    from shea.observability.tracer import JsonFormatter, StructuredTracer
    
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
    tracer = StructuredTracer()
    
    with active_context(correlation_id="trace-abc"):
        tracer.filter(record)
        
    assert record.correlation_id == "trace-abc"
    
    formatter = JsonFormatter()
    out = formatter.format(record)
    data = json.loads(out)
    assert data["correlation_id"] == "trace-abc"
    assert data["message"] == "msg"
