from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "shea"


def test_no_module_shadows_a_package_of_the_same_name() -> None:
    """`ports.py` next to `ports/__init__.py` is silently dead code:
    Python imports the package and never the module, so edits to the
    module look like they do something and don't. This has been
    re-introduced more than once; it must fail loudly instead."""
    shadowed = sorted(
        str(module.relative_to(SRC))
        for module in SRC.rglob("*.py")
        if module.name != "__init__.py" and (module.with_suffix("") / "__init__.py").exists()
    )
    assert shadowed == [], f"module(s) shadowed by a same-named package: {shadowed}"


def test_the_guard_actually_detects_a_shadowing_module(tmp_path: Path) -> None:
    (tmp_path / "ports").mkdir()
    (tmp_path / "ports" / "__init__.py").write_text("")
    (tmp_path / "ports.py").write_text("")
    found = [
        m.name
        for m in tmp_path.rglob("*.py")
        if m.name != "__init__.py" and (m.with_suffix("") / "__init__.py").exists()
    ]
    assert found == ["ports.py"]