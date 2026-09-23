from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT, Settings
from app.core.database import build_engine


def test_env_file_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///data/from-file.db\nCANVAS_ACCESS_TOKEN=unused\n", encoding="utf-8")
    assert Settings(_env_file=dotenv).database_url == "sqlite:///data/from-file.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert Settings(_env_file=dotenv).database_url == "sqlite:///:memory:"


def test_relative_database_path_does_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = build_engine("sqlite:///data/path-check.db")
    try:
        assert Path(engine.url.database) == PROJECT_ROOT / "data" / "path-check.db"
        assert not Path(engine.url.database).exists()  # no connection yet
    finally:
        engine.dispose()


def test_non_sqlite_configuration_is_rejected():
    with pytest.raises(ValueError, match="only sqlite"):
        build_engine("postgresql://localhost/example")


def test_backend_env_fallback_and_root_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
    assert Settings.model_config["env_file"] == (
        PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env"
    )
    backend_env = tmp_path / "backend.env"
    root_env = tmp_path / "root.env"
    backend_env.write_text("CANVAS_BASE_URL=https://backend.example.test\n", encoding="utf-8")
    assert Settings(_env_file=(backend_env, root_env)).canvas_base_url == "https://backend.example.test"
    root_env.write_text("CANVAS_BASE_URL=https://root.example.test\n", encoding="utf-8")
    assert Settings(_env_file=(backend_env, root_env)).canvas_base_url == "https://root.example.test"
    monkeypatch.setenv("CANVAS_BASE_URL", "https://environment.example.test")
    assert Settings(_env_file=(backend_env, root_env)).canvas_base_url == "https://environment.example.test"
