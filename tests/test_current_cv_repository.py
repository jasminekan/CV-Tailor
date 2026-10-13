import json
from pathlib import Path
import runpy

import pytest

from app.models import CurrentCV
from app.repositories.json_current_cv import CurrentCVRepositoryError, JsonCurrentCVRepository


@pytest.fixture
def current_cv():
    return CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-z", "achievement_ids": ["a-z", "a-a"]},
            {"work_experience_id": "role-a", "achievement_ids": ["a-middle"]},
        ],
        "projects": [
            {"project_id": "project-z", "contribution_ids": ["c-z", "c-a"]},
            {"project_id": "project-a", "contribution_ids": []},
        ],
        "skill_groups": [
            {"name": "  Languages  ", "skill_keys": ["python", "c++", "c#"]},
            {"name": "Backend", "skill_keys": ["fastapi", "api development"]},
        ],
        "tailoring_settings": {"max_projects": 0, "max_skills": 4},
    })


def test_save_load_round_trip_preserves_all_nested_order_and_values(tmp_path, current_cv):
    path = tmp_path / "nested" / "current_cv.json"
    repository = JsonCurrentCVRepository(path)
    assert repository.save(current_cv) == current_cv
    assert repository.load() == current_cv
    assert json.loads(path.read_text(encoding="utf-8")) == current_cv.model_dump()
    assert not path.with_suffix(".json.tmp").exists()


def test_missing_file_returns_empty_cv_without_creating_files(tmp_path):
    path = tmp_path / "missing" / "current_cv.json"
    assert JsonCurrentCVRepository(path).load() == CurrentCV()
    assert not path.parent.exists()


def test_saving_empty_cv_round_trips_defaults(tmp_path):
    repository = JsonCurrentCVRepository(tmp_path / "current_cv.json")
    repository.save(CurrentCV())
    assert repository.load().model_dump() == CurrentCV().model_dump()


def test_second_save_replaces_previous_cv(tmp_path, current_cv):
    repository = JsonCurrentCVRepository(tmp_path / "current_cv.json")
    repository.save(current_cv)
    replacement = CurrentCV.model_validate({"skill_groups": [{"name": "Empty"}]})
    repository.save(replacement)
    assert repository.load() == replacement


@pytest.mark.parametrize("stored", [
    b"not json", b"", b"\xff", b"[]", b"null",
    b'{"schema_version": 2}',
    b'{"future_field": "must not disappear"}',
    b'{"tailoring_settings": {"max_skills": true}}',
    b'{"work_experience": [{"work_experience_id": " "}]}',
    b'{"skill_groups": [{"name": "Skills", "skill_keys": ["python", "python"]}]}',
])
def test_corrupt_or_invalid_stored_data_raises_without_modification(tmp_path, stored):
    path = tmp_path / "current_cv.json"
    path.write_bytes(stored)
    with pytest.raises(CurrentCVRepositoryError, match="could not be loaded"):
        JsonCurrentCVRepository(path).load()
    assert path.read_bytes() == stored


def test_load_wraps_read_failure(tmp_path, monkeypatch):
    path = tmp_path / "current_cv.json"
    path.write_text("{}", encoding="utf-8")
    error = PermissionError("Read denied")
    original_read = Path.read_text

    def fail_read(self, *args, **kwargs):
        if self == path:
            raise error
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read)
    with pytest.raises(CurrentCVRepositoryError) as caught:
        JsonCurrentCVRepository(path).load()
    assert caught.value.__cause__ is error
    assert path.read_bytes() == b"{}"


@pytest.mark.parametrize("failure_stage", ["mkdir", "write", "replace"])
def test_failed_save_preserves_existing_data_and_cleans_temporary_file(
    tmp_path, monkeypatch, current_cv, failure_stage,
):
    path = tmp_path / "current_cv.json"
    repository = JsonCurrentCVRepository(path)
    repository.save(current_cv)
    before = path.read_bytes()
    error = OSError("Simulated save failure")
    original_write = Path.write_text

    def fail_save(*args, **kwargs):
        if failure_stage == "write":
            # Simulate failure after a partial temporary-file write.
            original_write(args[0], "partial data", encoding="utf-8")
        raise error

    if failure_stage == "mkdir":
        monkeypatch.setattr(Path, "mkdir", fail_save)
    elif failure_stage == "write":
        monkeypatch.setattr(Path, "write_text", fail_save)
    else:
        monkeypatch.setattr("app.repositories.json_current_cv.os.replace", fail_save)

    with pytest.raises(CurrentCVRepositoryError, match="could not be saved") as caught:
        repository.save(CurrentCV())
    assert caught.value.__cause__ is error
    assert path.read_bytes() == before
    assert not path.with_suffix(".json.tmp").exists()


def test_cleanup_failure_does_not_mask_save_error(tmp_path, monkeypatch, current_cv):
    path = tmp_path / "current_cv.json"
    repository = JsonCurrentCVRepository(path)
    repository.save(current_cv)
    before = path.read_bytes()
    save_error = OSError("Replace failed")
    original_unlink = Path.unlink

    def fail_replace(*args):
        raise save_error

    def fail_cleanup(self, *args, **kwargs):
        if self == path.with_suffix(".json.tmp"):
            raise PermissionError("Cleanup denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr("app.repositories.json_current_cv.os.replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(CurrentCVRepositoryError) as caught:
        repository.save(CurrentCV())
    assert caught.value.__cause__ is save_error
    assert path.read_bytes() == before


@pytest.mark.parametrize("configured", [False, True])
def test_current_cv_path_configuration_does_not_create_data(tmp_path, monkeypatch, configured):
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    if configured:
        expected = tmp_path / "custom" / "cv.json"
        monkeypatch.setenv("CURRENT_CV_PATH", str(expected))
    else:
        expected = main_path.parents[1] / "data" / "current_cv.json"
        monkeypatch.delenv("CURRENT_CV_PATH", raising=False)
    # A fresh namespace avoids reloading/mutating the app used by other tests.
    namespace = runpy.run_path(str(main_path))
    assert namespace["CURRENT_CV_PATH"] == expected
    assert namespace["current_cv_repository"].path == expected
    if configured:
        assert not expected.parent.exists()


@pytest.mark.parametrize("cv_name,bank_name", [
    ("same.json", "same.json"),
    ("nested/../same.json", "same.json"),
    ("bank.json.tmp", "bank.json"),
    ("cv.json", "cv.json.tmp"),
])
def test_overlapping_store_or_temporary_paths_are_rejected_before_writes(tmp_path, monkeypatch, cv_name, bank_name):
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    bank_path = tmp_path / bank_name
    cv_path = tmp_path / cv_name
    bank_path.write_bytes(b"unchanged existing bank")
    monkeypatch.setenv("EXPERIENCE_BANK_PATH", str(bank_path))
    monkeypatch.setenv("CURRENT_CV_PATH", str(cv_path))
    before_paths = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="storage paths must not overlap"):
        runpy.run_path(str(main_path))
    assert bank_path.read_bytes() == b"unchanged existing bank"
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before_paths
