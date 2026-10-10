import json

import pytest

from app.models import ExperienceBank, Project
from app.repositories.json_experience_bank import (
    ExperienceBankRepositoryError,
    JsonExperienceBankRepository,
)


def test_repository_round_trips_an_experience_bank(tmp_path) -> None:
    repository = JsonExperienceBankRepository(tmp_path / "experience_bank.json")
    bank = ExperienceBank(projects=[Project(name="API", technologies=["Python"])])

    repository.save(bank)

    assert repository.load() == bank


def test_repository_returns_empty_bank_when_file_is_missing(tmp_path) -> None:
    repository = JsonExperienceBankRepository(tmp_path / "missing.json")

    assert repository.load() == ExperienceBank()


def test_repository_rejects_corrupt_json(tmp_path) -> None:
    path = tmp_path / "experience_bank.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ExperienceBankRepositoryError):
        JsonExperienceBankRepository(path).load()


def test_repository_writes_valid_json(tmp_path) -> None:
    path = tmp_path / "experience_bank.json"
    JsonExperienceBankRepository(path).save(ExperienceBank())

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1