from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass

MetricEvent = dict[str, str | float]


@dataclass
class MetricSnapshot:
    total_intents: int
    total_tools_executed: int
    tool_success_rate: float
    security_blocks: int
    active_tasks: int
    avg_tool_duration_ms: float
    recent_events: list[MetricEvent]


class MetricsRegistry:
    """A lightweight, in-memory sliding window for operational metrics.
    
    In a heavy production environment this would be replaced with an
    OpenTelemetry metrics exporter (e.g. to Prometheus).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        
        # Counters
        self.total_intents = 0
        self.total_tools_executed = 0
        self.tool_successes = 0
        self.security_blocks = 0
        self.active_tasks = 0
        
        # Sliding windows (last 100 entries)
        self.tool_durations: collections.deque[float] = collections.deque(maxlen=100)
        
        # Simple recent events log for quick UI updates (last 50)
        self.recent_events: collections.deque[MetricEvent] = collections.deque(maxlen=50)

    def record_intent(self) -> None:
        with self._lock:
            self.total_intents += 1

    def record_tool_execution(self, duration_ms: float, success: bool) -> None:
        with self._lock:
            self.total_tools_executed += 1
            if success:
                self.tool_successes += 1
            self.tool_durations.append(duration_ms)

    def record_security_block(self, reason: str) -> None:
        with self._lock:
            self.security_blocks += 1
            self._add_event("security_block", f"Blocked: {reason}")

    def task_started(self) -> None:
        with self._lock:
            self.active_tasks += 1

    def task_completed(self) -> None:
        with self._lock:
            self.active_tasks = max(0, self.active_tasks - 1)

    def _add_event(self, event_type: str, message: str) -> None:
        self.recent_events.append({
            "timestamp": time.time(),
            "type": event_type,
            "message": message
        })

    def get_snapshot(self) -> MetricSnapshot:
        with self._lock:
            success_rate = (
                self.tool_successes / self.total_tools_executed
            ) if self.total_tools_executed > 0 else 1.0
            avg_duration = sum(
                self.tool_durations
            ) / len(self.tool_durations) if self.tool_durations else 0.0
            
            return MetricSnapshot(
                total_intents=self.total_intents,
                total_tools_executed=self.total_tools_executed,
                tool_success_rate=success_rate,
                security_blocks=self.security_blocks,
                active_tasks=self.active_tasks,
                avg_tool_duration_ms=avg_duration,
                recent_events=list(self.recent_events),
            )

# Global singleton for simplicity in the MVP observability setup
global_metrics = MetricsRegistry()