from __future__ import annotations

import collections
import os
import shutil
import threading
import time
from dataclasses import dataclass

MetricEvent = dict[str, str | float]


@dataclass
class MetricSnapshot:
    # Agent / execution
    total_intents: int
    total_tools_executed: int
    tool_success_rate: float
    security_blocks: int
    active_tasks: int
    avg_tool_duration_ms: float
    recent_events: list[MetricEvent]

    # Host (process + machine)
    cpu_percent: float
    load_1m: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float

    # Rate limits / provider pressure
    requests_per_minute: float
    provider_calls_per_minute: float
    rate_limit_hits: int
    rate_limit_remaining: float  # 0–1 fraction of budget still free
    provider_health: float  # 0–100


@dataclass
class MetricsRegistry:
    """In-memory sliding window for operational + host metrics."""

    def __init__(self, *, rpm_budget: int = 60) -> None:
        self._lock = threading.Lock()
        self._rpm_budget = max(1, rpm_budget)

        self.total_intents = 0
        self.total_tools_executed = 0
        self.tool_successes = 0
        self.security_blocks = 0
        self.active_tasks = 0
        self.rate_limit_hits = 0
        self.provider_failures = 0
        self.provider_successes = 0

        self.tool_durations: collections.deque[float] = collections.deque(maxlen=100)
        self.recent_events: collections.deque[MetricEvent] = collections.deque(maxlen=50)

        # timestamps (monotonic) for rate windows
        self._request_ts: collections.deque[float] = collections.deque(maxlen=2000)
        self._provider_ts: collections.deque[float] = collections.deque(maxlen=2000)

        # CPU sample state
        self._last_cpu = os.times()
        self._last_cpu_wall = time.monotonic()

    def record_intent(self) -> None:
        with self._lock:
            self.total_intents += 1
            self._request_ts.append(time.monotonic())

    def record_tool_execution(self, duration_ms: float, success: bool) -> None:
        with self._lock:
            self.total_tools_executed += 1
            if success:
                self.tool_successes += 1
            self.tool_durations.append(duration_ms)
            self._request_ts.append(time.monotonic())

    def record_provider_call(self, *, success: bool, rate_limited: bool = False) -> None:
        with self._lock:
            self._provider_ts.append(time.monotonic())
            self._request_ts.append(time.monotonic())
            if success:
                self.provider_successes += 1
            else:
                self.provider_failures += 1
            if rate_limited:
                self.rate_limit_hits += 1
                self._add_event("rate_limit", "Provider rate limit hit")

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
        self.recent_events.append(
            {
                "timestamp": time.time(),
                "type": event_type,
                "message": message,
            }
        )

    def _window_rate(self, series: collections.deque[float], window_s: float = 60.0) -> float:
        now = time.monotonic()
        while series and now - series[0] > window_s:
            series.popleft()
        if not series:
            return 0.0
        return len(series) * (60.0 / window_s)

    def _cpu_percent(self) -> float:
        """Process CPU % since last sample (stdlib only)."""
        try:
            cur = os.times()
            wall = time.monotonic()
            elapsed = wall - self._last_cpu_wall
            if elapsed <= 0:
                return 0.0
            user = cur.user - self._last_cpu.user
            system = cur.system - self._last_cpu.system
            self._last_cpu = cur
            self._last_cpu_wall = wall
            # Approximate vs one core; clamp
            return max(0.0, min(100.0, 100.0 * (user + system) / elapsed))
        except Exception:
            return 0.0

    def _load_1m(self) -> float:
        try:
            return float(os.getloadavg()[0])
        except (AttributeError, OSError):
            return 0.0

    def _ram(self) -> tuple[float, float, float]:
        """Return (percent, used_mb, total_mb). Linux /proc; else zeros."""
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] in {"MemTotal:", "MemAvailable:"}:
                        info[parts[0]] = int(parts[1])  # kB
            total = info.get("MemTotal:", 0)
            avail = info.get("MemAvailable:", 0)
            if total <= 0:
                return 0.0, 0.0, 0.0
            used = total - avail
            pct = 100.0 * used / total
            return pct, used / 1024.0, total / 1024.0
        except OSError:
            return 0.0, 0.0, 0.0

    def _disk(self) -> tuple[float, float, float]:
        try:
            usage = shutil.disk_usage(os.getcwd())
            pct = 100.0 * usage.used / usage.total if usage.total else 0.0
            return pct, usage.used / (1024**3), usage.total / (1024**3)
        except OSError:
            return 0.0, 0.0, 0.0

    def get_snapshot(self) -> MetricSnapshot:
        with self._lock:
            success_rate = (
                self.tool_successes / self.total_tools_executed
                if self.total_tools_executed > 0
                else 1.0
            )
            avg_duration = (
                sum(self.tool_durations) / len(self.tool_durations)
                if self.tool_durations
                else 0.0
            )
            rpm = self._window_rate(self._request_ts)
            ppm = self._window_rate(self._provider_ts)
            remaining = max(0.0, min(1.0, 1.0 - (rpm / self._rpm_budget)))
            prov_total = self.provider_successes + self.provider_failures
            if prov_total == 0:
                health = 100.0
            else:
                health = 100.0 * self.provider_successes / prov_total
                health = max(0.0, health - min(30.0, self.rate_limit_hits * 2.0))

            cpu = self._cpu_percent()
            load = self._load_1m()
            ram_pct, ram_used, ram_total = self._ram()
            disk_pct, disk_used, disk_total = self._disk()

            return MetricSnapshot(
                total_intents=self.total_intents,
                total_tools_executed=self.total_tools_executed,
                tool_success_rate=success_rate,
                security_blocks=self.security_blocks,
                active_tasks=self.active_tasks,
                avg_tool_duration_ms=avg_duration,
                recent_events=list(self.recent_events),
                cpu_percent=round(cpu, 1),
                load_1m=round(load, 2),
                ram_percent=round(ram_pct, 1),
                ram_used_mb=round(ram_used, 1),
                ram_total_mb=round(ram_total, 1),
                disk_percent=round(disk_pct, 1),
                disk_used_gb=round(disk_used, 2),
                disk_total_gb=round(disk_total, 2),
                requests_per_minute=round(rpm, 1),
                provider_calls_per_minute=round(ppm, 1),
                rate_limit_hits=self.rate_limit_hits,
                rate_limit_remaining=round(remaining, 3),
                provider_health=round(health, 1),
            )


global_metrics = MetricsRegistry()