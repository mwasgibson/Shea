import json
from pathlib import Path

import pytest

from shea.config.lifecycle import backup_config, migrate_config, restore_config, safe_save_config
from shea.config.resolver import ConfigLayer, build_default_resolver
from shea.config.schema import validate_config
from shea.config.trust import ProjectTrustManager


def test_schema_validation() -> None:
    data = {
        "_version": 1,
        "allow_unsigned_plugins": True,
        "max_tool_privilege_level": "standard",
        "unknown_key": "some_value",
        "sandbox_required": "this is a string, not a bool",  # Invalid type
    }
    
    validated = validate_config(data)
    
    assert validated["_version"] == 1
    assert validated["allow_unsigned_plugins"] is True
    assert validated["max_tool_privilege_level"] == "standard"
    assert "unknown_key" in validated
    assert "sandbox_required" not in validated


def test_lifecycle_backup_and_restore(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    with open(config_file, "w") as f:
        f.write('{"test": 123}')
        
    backup_file = backup_config(config_file)
    assert backup_file is not None
    assert backup_file.exists()
    
    with open(config_file, "w") as f:
        f.write('{"test": 456}')
        
    restore_config(config_file, backup_file)
    
    with open(config_file) as f:
        content = f.read()
    assert content == '{"test": 123}'


def test_migrate_config() -> None:
    data = {"old_setting": True}
    migrated = migrate_config(data, to_version=2)
    assert migrated["_version"] == 2
    assert migrated["old_setting"] is True


def test_safe_save_config(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    data = {"my_key": "value"}
    
    safe_save_config(config_file, data)
    assert config_file.exists()
    
    with open(config_file) as f:
        saved = json.load(f)
    assert saved["my_key"] == "value"
    assert saved["_version"] == 1
    
    # Check that a backup was created if we modify it
    data["my_key"] = "new_value"
    safe_save_config(config_file, data)
    
    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1


def test_project_trust_manager(tmp_path: Path) -> None:
    trust_file = tmp_path / "trusted_projects.json"
    manager = ProjectTrustManager(storage_path=trust_file)
    
    test_project = tmp_path / "my_project"
    
    assert not manager.is_trusted(test_project)
    
    manager.trust_project(test_project)
    assert manager.is_trusted(test_project)
    
    manager.untrust_project(test_project)
    assert not manager.is_trusted(test_project)


def test_build_resolver_with_trust(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set cwd to a temporary project directory
    project_dir = tmp_path / "fake_project"
    project_dir.mkdir()
    shea_dir = project_dir / ".shea"
    shea_dir.mkdir()
    
    project_config = shea_dir / "config.json"
    with open(project_config, "w") as f:
        json.dump({"test_key": "project_value"}, f)
        
    monkeypatch.chdir(project_dir)
    
    # We also need a fake trust manager storage path
    monkeypatch.setattr("shea.config.trust.Path.home", lambda: tmp_path)
    
    # At this point, the project is NOT trusted
    resolver_untrusted = build_default_resolver()
    assert resolver_untrusted.layers.get(ConfigLayer.PROJECT) is None
    
    # Now trust it
    manager = ProjectTrustManager()
    manager.trust_project(project_dir)
    
    resolver_trusted = build_default_resolver()
    assert resolver_trusted.layers[ConfigLayer.PROJECT] == {"test_key": "project_value"}

