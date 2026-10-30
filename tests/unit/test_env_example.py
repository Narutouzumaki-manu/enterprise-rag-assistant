from pathlib import Path

from app.core.config import Settings


def _keys() -> set[str]:
    keys = set()
    for line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            keys.add(line.split("=", 1)[0].strip())
    return keys


def test_every_setting_is_listed_in_env_example():
    missing = [name.upper() for name in Settings.model_fields if name.upper() not in _keys()]
    assert not missing, f"missing from .env.example: {missing}"


def test_env_example_has_no_unknown_settings():
    known = {name.upper() for name in Settings.model_fields}
    unknown = [key for key in _keys() if key not in known and not key.startswith("OPENROUTER_")]
    assert not unknown, f"not in Settings: {unknown}"