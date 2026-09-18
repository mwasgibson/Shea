import datetime
from unittest.mock import MagicMock

import pytest

from shea.memory.broker import MemoryBroker
from shea.memory.contracts import (
    Memory,
    MemoryProposal,
    MemoryStatus,
    MemoryType,
    Sensitivity,
)
from shea.ports.clock import Clock


class MockClock(Clock):
    def __init__(self, current: datetime.datetime):
        self.current = current
    def now(self) -> datetime.datetime:
        return self.current


@pytest.fixture
def mock_memory_service():
    service = MagicMock()
    service.retrieve.return_value = []
    return service


@pytest.fixture
def mock_id_generator():
    generator = MagicMock()
    generator.new_id.return_value = "mem-1"
    return generator


@pytest.fixture
def mock_model_provider():
    return MagicMock()


@pytest.fixture
def broker(mock_memory_service, mock_id_generator, mock_model_provider):
    clock = MockClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    return MemoryBroker(
        memory_service=mock_memory_service,
        clock=clock,
        id_generator=mock_id_generator,
        model_provider=mock_model_provider,
    )


def test_sensitivity_upgrade_for_secrets(broker, mock_memory_service):
    # Propose something with a secret
    proposal = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="The API key is sk-12345",
        source="llm_extraction",
        task_id="task-1",
        request_id="req-1",
    )
    
    broker.propose(proposal)
    
    stored = mock_memory_service.store.call_args[0][0]
    assert stored.sensitivity == Sensitivity.RESTRICTED
    # Base confidence should be downgraded because it came from LLM extraction and is sensitive
    assert stored.confidence == 0.3  # 0.5 - 0.2


def test_sensitivity_upgrade_for_pii(broker, mock_memory_service):
    proposal = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="My phone number is 555-1234",
        source="user_explicit",
        task_id="task-1",
        request_id=None,
        base_confidence=0.9
    )
    
    broker.propose(proposal)
    
    stored = mock_memory_service.store.call_args[0][0]
    assert stored.sensitivity == Sensitivity.SENSITIVE
    assert stored.confidence == 0.9  # Not downgraded because it's not llm_extraction


def test_lifecycle_policy_ttl_calculation(broker, mock_memory_service):
    # FACTS should expire in 90 days
    fact = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="Some fact",
        source="user_explicit",
        task_id="task-1",
        request_id=None,
    )
    broker.propose(fact)
    stored_fact = mock_memory_service.store.call_args[0][0]
    assert stored_fact.expires_at == datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(days=90)
    
    # PREFERENCES should not expire
    pref = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.PREFERENCE,
        content="Some preference",
        source="user_explicit",
        task_id="task-1",
        request_id=None,
    )
    broker.propose(pref)
    stored_pref = mock_memory_service.store.call_args[0][0]
    assert stored_pref.expires_at is None


def test_provenance_is_irrevocably_bound(broker, mock_memory_service):
    proposal = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="Unrelated fact",
        source="llm_extraction",
        task_id="task-999",
        request_id="req-42",
    )
    
    broker.propose(proposal)
    
    stored = mock_memory_service.store.call_args[0][0]
    # It prefers request_id over task_id if present
    assert stored.provenance == "req-42"
    assert stored.source == "llm_extraction"


def test_conflict_resolution_duplicate(broker, mock_memory_service, mock_model_provider):
    old_mem = Memory(
        id="old-1",
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="The sky is blue",
        source="interaction",
        provenance="task-0",
        created_at=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    )
    
    # Mock retrieval to return the old memory
    retrieval_result = MagicMock()
    retrieval_result.memory = old_mem
    retrieval_result.score = 0.9
    mock_memory_service.retrieve.return_value = [retrieval_result]
    
    # Mock LLM to return DUPLICATE
    llm_resp = MagicMock()
    llm_resp.structured_data = {"resolution": "DUPLICATE"}
    mock_model_provider.generate.return_value = llm_resp
    
    proposal = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.FACT,
        content="Sky color is blue",
        source="llm_extraction",
        task_id="task-1",
        request_id="req-1",
    )
    
    broker.propose(proposal)
    
    # It should have updated the old memory timestamp rather than creating a new one
    stored = mock_memory_service.store.call_args[0][0]
    assert stored.id == "old-1"
    assert stored.updated_at == datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    assert stored.created_at == datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)


def test_conflict_resolution_update(broker, mock_memory_service, mock_model_provider):
    old_mem = Memory(
        id="old-1",
        profile_id="prof-1",
        type=MemoryType.PREFERENCE,
        content="I prefer dark mode",
        source="interaction",
        provenance="task-0",
        created_at=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        status=MemoryStatus.ACTIVE
    )
    
    retrieval_result = MagicMock()
    retrieval_result.memory = old_mem
    retrieval_result.score = 0.95
    mock_memory_service.retrieve.return_value = [retrieval_result]
    
    # Mock LLM to return UPDATE
    llm_resp = MagicMock()
    llm_resp.structured_data = {"resolution": "UPDATE"}
    mock_model_provider.generate.return_value = llm_resp
    
    proposal = MemoryProposal(
        profile_id="prof-1",
        type=MemoryType.PREFERENCE,
        content="Actually, I prefer light mode now",
        source="llm_extraction",
        task_id="task-1",
        request_id="req-1",
    )
    
    broker.propose(proposal)
    
    # It should have stored TWICE: once to expire the old, once to insert the new
    assert mock_memory_service.store.call_count == 2
    
    first_stored = mock_memory_service.store.call_args_list[0][0][0]
    assert first_stored.id == "old-1"
    assert first_stored.status == MemoryStatus.EXPIRED
    
    second_stored = mock_memory_service.store.call_args_list[1][0][0]
    assert second_stored.id == "mem-1"
    assert second_stored.content == "Actually, I prefer light mode now"
    assert second_stored.status == MemoryStatus.ACTIVE

