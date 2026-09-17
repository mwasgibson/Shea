from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from shea.events.bus import EventBus
from shea.events.contracts import Event, EventPriority
from shea.events.filters import EventFilter, _pattern_matches  # pyright: ignore[reportPrivateUsage]

# ── Strategies ──────────────────────────────────────────────────────

dotted_name = st.from_regex(r"[a-z]{1,8}(\.[a-z]{1,8}){0,3}", fullmatch=True)
event_priority = st.sampled_from(list(EventPriority))
source_name = st.from_regex(r"[a-z_]{1,12}", fullmatch=True)


def event_st(
    event_type: st.SearchStrategy[str] = dotted_name,
    source: st.SearchStrategy[str] = source_name,
    priority: st.SearchStrategy[EventPriority] = event_priority,
) -> st.SearchStrategy[Event]:
    return st.builds(
        Event,
        event_id=st.text(min_size=1, max_size=8),
        event_type=event_type,
        source=source,
        timestamp=st.just(datetime(2025, 1, 1, tzinfo=UTC)),
        priority=priority,
    )


# ── Pattern matching properties ─────────────────────────────────────

@given(event_type=dotted_name)
def test_global_wildcard_always_matches(event_type: str):
    assert _pattern_matches("*", event_type)


@given(event_type=dotted_name)
def test_exact_pattern_matches_self(event_type: str):
    assert _pattern_matches(event_type, event_type)


@given(prefix=st.from_regex(r"[a-z]{1,8}", fullmatch=True), suffix=dotted_name)
def test_prefix_wildcard_matches_namespace(prefix: str, suffix: str):
    event_type = f"{prefix}.{suffix}"
    pattern = f"{prefix}.*"
    assert _pattern_matches(pattern, event_type)


# ── Filter properties ──────────────────────────────────────────────

@given(event=event_st())
def test_empty_filter_accepts_everything(event: Event):
    f = EventFilter()
    assert f.matches(event)


@given(event=event_st())
def test_source_filter_rejects_non_matching(event: Event):
    f = EventFilter(sources=frozenset({"__never_matches__"}))
    assert not f.matches(event)


@given(event=event_st(priority=st.just(EventPriority.LOW)))
def test_high_min_priority_rejects_low(event: Event):
    f = EventFilter(min_priority=EventPriority.HIGH)
    assert not f.matches(event)


@given(event=event_st(priority=st.just(EventPriority.CRITICAL)))
def test_low_min_priority_accepts_critical(event: Event):
    f = EventFilter(min_priority=EventPriority.LOW)
    assert f.matches(event)


# ── Bus invariants ──────────────────────────────────────────────────

@given(event=event_st())
@settings(max_examples=50)
def test_publish_never_raises(event: Event):
    """Publishing must never raise, even with failing handlers."""
    bus = EventBus()
    bus.subscribe("*", lambda e: (_ for _ in ()).throw(RuntimeError("fail")))
    # This must not raise
    bus.publish(event)


@given(event=event_st())
@settings(max_examples=50)
def test_all_matching_handlers_receive_event(event: Event):
    """Every handler subscribed to '*' must receive every event."""
    bus = EventBus()
    received: list[Event] = []
    n_handlers = 3
    for _ in range(n_handlers):
        bus.subscribe("*", received.append)

    bus.publish(event)
    assert len(received) == n_handlers