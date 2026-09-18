import json
import logging
from datetime import UTC, datetime
from typing import Any

from .context import get_correlation_id, get_profile_id, get_task_id


class StructuredTracer(logging.Filter):
    """Injects correlation_id, task_id, and profile_id into standard log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "unknown"
        record.task_id = get_task_id() or "unknown"
        record.profile_id = get_profile_id() or "system"
        return True

class JsonFormatter(logging.Formatter):
    """Formats log records as JSON including observability context."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "unknown"),
            "task_id": getattr(record, "task_id", "unknown"),
            "profile_id": getattr(record, "profile_id", "system"),
        }
        
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_obj)

def configure_tracing(level: int = logging.INFO) -> None:
    """Initialize the global structured tracer for the application."""
    root_logger = logging.getLogger()
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(StructuredTracer())
    
    root_logger.addHandler(handler)
    root_logger.setLevel(level)