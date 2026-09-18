from datetime import UTC, datetime
from pathlib import Path

from shea.bootstrap import build_runtime
from shea.memory.contracts import Memory, MemoryType


def test_profile_memory_isolation(tmp_path: Path):
    runtime = build_runtime(tmp_path / "test.db", workspace=tmp_path / "ws")
    
    # Store memory for Profile A
    mem_a = Memory(
        id="mem_A",
        profile_id="profile_A",
        type=MemoryType.FACT,
        content="The secret code is 1234",
        source="test",
        provenance="req1",
        created_at=datetime.now(UTC)
    )
    runtime.memory_service.store(mem_a)
    
    # Store memory for Profile B
    mem_b = Memory(
        id="mem_B",
        profile_id="profile_B",
        type=MemoryType.FACT,
        content="The secret code is 5678",
        source="test",
        provenance="req2",
        created_at=datetime.now(UTC)
    )
    runtime.memory_service.store(mem_b)
    
    # Profile A should only retrieve Profile A's memory
    results_a = runtime.memory_service.retrieve("secret code", profile_id="profile_A")
    assert len(results_a) == 1
    assert results_a[0].memory.id == "mem_A"
    
    # Profile B should only retrieve Profile B's memory
    results_b = runtime.memory_service.retrieve("secret code", profile_id="profile_B")
    assert len(results_b) == 1
    assert results_b[0].memory.id == "mem_B"
    
    # Profile C should retrieve nothing
    results_c = runtime.memory_service.retrieve("secret code", profile_id="profile_C")
    assert len(results_c) == 0

