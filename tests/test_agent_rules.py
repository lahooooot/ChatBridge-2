import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from desktop.config import ConfigStore, DEFAULT_RULES


def test_defaults_and_random_persisted_provider_keys(tmp_path):
    store = ConfigStore(tmp_path / "one")
    config = store.get()
    assert config["ws_port"] == 8787
    assert config["full_access"] is True
    assert config["approval_timeout"] == 120
    assert config["provider_enabled"] is False
    assert config["provider_port"] == 8788
    assert config["provider_timeout"] == 600
    assert config["custom_models"] == []
    assert "browser_mode" not in config
    assert len(config["provider_key"]) >= 40
    assert ConfigStore(tmp_path / "one").get()["provider_key"] == config["provider_key"]
    assert ConfigStore(tmp_path / "two").get()["provider_key"] != config["provider_key"]


def test_legacy_partial_custom_models_are_migrated_on_startup(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "custom_models": [
            {"id": "c_good", "name": "Good", "home": "https://example.com"},
            {"name": "Legacy", "title": "Ignored title", "url": "https://legacy.example"},
            {"id": "partial", "name": "Missing home"},
            None,
        ]
    }), encoding="utf-8")
    store = ConfigStore(tmp_path)
    models = store.get()["custom_models"]
    assert models == [
        {"id": "c_good", "name": "Good", "home": "https://example.com"},
        {"id": "c_legacy", "name": "Legacy", "home": "https://legacy.example"},
    ]
    # The repair is persisted, so a frozen EXE does not repeat the failure.
    assert json.loads(path.read_text(encoding="utf-8"))["custom_models"] == models


def test_builtin_rules_are_first_person_and_natural():
    for rule in DEFAULT_RULES:
        assert rule["text"].startswith("I ")
        narrative = rule["text"].replace("chatbridge-tool-call", "tool-call")
        assert "chatbridge" not in narrative.lower()
        assert "YOU MUST" not in narrative
        assert "SYSTEM" not in narrative
        assert not any(line.isupper() for line in narrative.splitlines() if line.strip())
    combined = "\n".join(row["text"] for row in DEFAULT_RULES)
    for tool in ("read_file", "write_file", "list_dir", "search_files", "run_command"):
        assert tool in combined
    assert '```chatbridge-tool-call\n{"tool":"read_file"' in combined


def test_edit_toggle_custom_add_delete_reset_and_persistence(tmp_path):
    store = ConfigStore(tmp_path)
    rows = store.rules_get()["rules"]
    rows[0]["text"] = "I prefer short explanations."
    rows[1]["enabled"] = False
    rows.pop()
    rows.append({"id": "custom", "text": "I prefer tests first.", "enabled": True, "builtin": False})
    saved = store.rules_set(rows, True)
    assert saved["rules"] == rows
    assert ConfigStore(tmp_path).rules_get() == saved
    assert store.rules_preview("My request", workspace=tmp_path).startswith("My request\n\nMy working folder")
    assert "I prefer short explanations." in store.rules_preview(workspace=tmp_path)
    assert rows[1]["text"] not in store.rules_preview(workspace=tmp_path)
    assert store.rules_preview("plain", workspace=None) == "plain"
    store.rules_set(rows, False)
    assert store.rules_preview("plain", workspace=tmp_path) == "plain"
    reset = store.rules_reset()
    assert reset == {"rules": DEFAULT_RULES, "on": True}


def test_upgrade_only_updates_untouched_builtin_and_preserves_deletion(tmp_path):
    store = ConfigStore(tmp_path)
    data = store.get()
    first, second = data["agent_rules"][:2]
    first["text"] = "I use an older built-in default."
    data["agent_rules_defaults"][first["id"]] = first["text"]
    first["enabled"] = False
    second["text"] = "I have carefully edited this rule."
    deleted = data["agent_rules"].pop()["id"]
    data["agent_rules_version"] = "2.49.0"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    upgraded = ConfigStore(tmp_path).rules_get()["rules"]
    assert upgraded[0]["text"] == DEFAULT_RULES[0]["text"]
    assert upgraded[0]["enabled"] is False
    assert upgraded[1]["text"] == second["text"]
    assert deleted not in {row["id"] for row in upgraded}


def test_unknown_legacy_rules_are_not_overwritten(tmp_path):
    store = ConfigStore(tmp_path)
    data = store.get()
    data.pop("agent_rules_defaults")
    data["agent_rules"][0]["text"] = "I wrote this before migration snapshots existed."
    data["browser_mode"] = "extension"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    fresh = ConfigStore(tmp_path).get()
    assert fresh["agent_rules"][0]["text"] == data["agent_rules"][0]["text"]
    assert "browser_mode" not in fresh


def test_no_mutable_aliases(tmp_path):
    store = ConfigStore(tmp_path)
    rules = store.rules_get()
    rules["rules"][0]["text"] = "changed outside store"
    assert store.rules_get()["rules"][0]["text"] == DEFAULT_RULES[0]["text"]
    state = {"chats": [{"name": "first"}]}
    store.save_state(state)
    state["chats"][0]["name"] = "mutated"
    assert store.load_state()["chats"][0]["name"] == "first"


@pytest.mark.parametrize("patch", [
    {"ws_port": 0}, {"provider_port": 70000}, {"provider_enabled": "yes"},
    {"approval_timeout": -1}, {"provider_key": ""}, {"custom_models": {}},
    {"agent_rules_on": 1}, {"browser_mode": "internal"}, {"agent_rules_defaults": {}},
    {"custom_models": [{"id": "c_bad", "name": "Bad", "home": "javascript:alert(1)"}]},
])
def test_invalid_update_does_not_damage_persisted_config(tmp_path, patch):
    store = ConfigStore(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.update(patch)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("rows", [None, ["text"], [{"id": "x", "text": 123}],
    [{"id": "x", "text": "a"}, {"id": "x", "text": "b"}],
    [{"id": "", "text": "a"}], [{"id": "x", "text": "a", "enabled": "yes"}]])
def test_invalid_rule_rows_rejected(tmp_path, rows):
    with pytest.raises(ValueError):
        ConfigStore(tmp_path).rules_set(rows, True)


def test_cross_instance_concurrent_atomic_updates_and_state(tmp_path):
    stores = [ConfigStore(tmp_path) for _ in range(4)]

    def update(index):
        store = stores[index % 4]
        store.update({f"test_{index}": index})
        store.save_state({"owner": index, "text": "x" * 2000})
        assert isinstance(store.load_state()["owner"], int)
        assert isinstance(json.loads(store.path.read_text()), dict)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(update, range(60)))
    config = stores[0].get()
    assert all(config[f"test_{index}"] == index for index in range(60))
    assert len(stores[0].load_state()["text"]) == 2000
    assert not list(tmp_path.glob("*.tmp"))


def test_malformed_existing_config_and_state_are_not_silently_replaced(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken")
    with pytest.raises(ValueError, match="Invalid JSON"):
        ConfigStore(tmp_path)
    assert config_path.read_text() == "{broken"
    config_path.unlink()
    store = ConfigStore(tmp_path)
    store.state_path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        store.load_state()


def test_default_data_dir_is_versioned():
    from desktop.config import DATA_DIR_NAME, default_data_dir
    assert DATA_DIR_NAME == '.chatbridge-2.50.0'
    assert default_data_dir().name == DATA_DIR_NAME
