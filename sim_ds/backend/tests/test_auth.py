from pathlib import Path

import pytest
from backend.shared.config import Settings, TokenPrincipal


def test_production_refuses_unauthenticated_startup(tmp_path: Path) -> None:
    settings = Settings(env="production", auth_mode="dev", data_dir=tmp_path, database_url="postgresql+asyncpg://x/y")
    with pytest.raises(SystemExit):
        settings.validate()


def test_production_requires_tokens(tmp_path: Path) -> None:
    settings = Settings(
        env="production",
        auth_mode="required",
        data_dir=tmp_path,
        tokens={},
        database_url="postgresql+asyncpg://x/y",
    )
    with pytest.raises(SystemExit):
        settings.validate()


def test_production_with_token_is_valid(tmp_path: Path) -> None:
    settings = Settings(
        env="production",
        auth_mode="required",
        data_dir=tmp_path,
        tokens={"secret": TokenPrincipal(user="ops", projects=("default",))},
        database_url="postgresql+asyncpg://x/y",
    )
    settings.validate()
