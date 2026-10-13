"""JavaScript behavior checks with a small DOM mock, plus static safety guards.

These tests do not replace manual checks in an actual browser.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import ExperienceBank
from app.services.current_cv import build_skill_catalogue
from app.repositories.json_current_cv import JsonCurrentCVRepository
from app.repositories.json_experience_bank import JsonExperienceBankRepository


STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("current_cv_frontend_harness.js")
SCENARIOS = [
    "navigation", "parent_dropdowns", "bullet_dropdowns", "duplicates",
    "add_remove_reorder", "round_trip", "missing_placeholders", "replace_broken",
    "failed_cv_load", "failed_bank_load", "failed_save", "structural_error",
    "fresh_bank", "saving_lock", "refresh_preserves_draft", "bank_saved_event",
    "beforeunload", "safe_text", "server_load_issues", "replace_project",
    "empty_defaults", "empty_bank",
    "groups_actions", "groups_validation", "skills_actions", "skills_duplicates",
    "skills_replace_missing", "skills_remove_missing", "settings_values",
    "settings_invalid", "settings_bad_input", "settings_unsafe_loaded", "phase5_failed_save",
    "preview_order", "preview_exact_text", "preview_education", "preview_missing",
    "phase5_saving_lock", "skills_bank_refresh", "phase5_edit_isolation", "phase5_reload",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_current_cv_javascript_behavior(tmp_path, scenario):
    run_frontend_scenario(tmp_path, scenario)


def run_frontend_scenario(tmp_path, scenario, extra_setup=""):
    runtime = shutil.which("node") or shutil.which("jsc")
    if not runtime:
        system_jsc = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")
        if system_jsc.is_file():
            runtime = str(system_jsc)
    if not runtime:
        pytest.skip("JavaScript runtime unavailable; run with Node or JavaScriptCore.")
    harness = HARNESS.read_text(encoding="utf-8")
    setup, assertions = harness.split("// INSERT BUILDER HERE", 1)
    source = (STATIC / "current_cv.js").read_text(encoding="utf-8")
    restart = "globalThis.recreateBuilder = () => {\n" + source + "\n};\n" if scenario == "phase5_reload" else ""
    script = tmp_path / "frontend_test.js"
    script.write_text(
        f"const scenario = {json.dumps(scenario)};\n"
        + extra_setup + setup + source + restart + assertions,
        encoding="utf-8",
    )
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS {scenario}" in result.stdout, result.stdout + result.stderr
    return result.stdout


def test_frontend_selection_payload_passes_real_api_and_persistence(tmp_path, monkeypatch):
    output = run_frontend_scenario(tmp_path, "release_round_trip")
    document = json.loads(next(line.removeprefix("DOCUMENT ") for line in output.splitlines() if line.startswith("DOCUMENT ")))
    bank_payload = json.loads(next(line.removeprefix("BANK ") for line in output.splitlines() if line.startswith("BANK ")))
    bank_repository = JsonExperienceBankRepository(tmp_path / "bank.json")
    cv_repository = JsonCurrentCVRepository(tmp_path / "cv.json")
    bank_repository.save(ExperienceBank.model_validate(bank_payload))
    before_bank = bank_repository.path.read_bytes()
    monkeypatch.setattr("app.main.experience_bank_repository", bank_repository)
    monkeypatch.setattr("app.main.current_cv_repository", cv_repository)
    client = TestClient(app)
    response = client.put("/current-cv", json=document)
    assert response.status_code == 200
    assert response.json() == document
    assert client.get("/current-cv").json() == {"current_cv": document, "reference_issues": []}
    assert cv_repository.load().model_dump() == document
    assert bank_repository.path.read_bytes() == before_bank


def test_bank_evidence_editor_preserves_original_and_explicitly_edited_text(tmp_path):
    source = (STATIC / "app.js").read_text()
    reader = "function readEvidence(" + source.split("function readEvidence(", 1)[1].split("\nfunction parseLines", 1)[0]
    split_values = "function splitValues(" + source.split("function splitValues(", 1)[1].split("\n// Keep each item's metadata", 1)[0]
    run_frontend_scenario(tmp_path, "bank_text_preservation", split_values + reader)


def test_bank_editor_preserves_unchanged_education_and_certification_rows(tmp_path):
    source = (STATIC / "app.js").read_text()
    parser = "function parseLines(" + source.split("function parseLines(", 1)[1].split("\nfunction readBank", 1)[0]
    split_values = "function splitValues(" + source.split("function splitValues(", 1)[1].split("\n// Keep each item's metadata", 1)[0]
    run_frontend_scenario(tmp_path, "bank_rows_preservation", "const loadedBank = {};\n" + split_values + parser)


def test_frontend_skill_catalogue_matches_backend_sources_labels_keys_and_order(tmp_path):
    bank = ExperienceBank.model_validate({
        "skills": [" Python ", "API\t Development", "C", "C++", "C#", "2", "10", "1", "\u0085Unit\u001cTesting\u0085", "\ufeffBOM\ufeff", "İ", "ΟΣ"],
        "work_experience": [{
            "employer": "Example", "role": "TypeScript Engineer",
            "skills": ["PYTHON", "Backend"], "technologies": ["FastAPI", " API   Development "],
            "achievements": [{"text": "Rust is not a tag.", "skills": ["Testing"], "technologies": ["SQLite"], "outcomes": ["Lua is not a tag."]}],
        }],
        "projects": [{
            "name": "Ruby project", "skills": ["Automation"], "technologies": ["JS", "JavaScript"],
            "evidence": [{"text": "Swift is not a tag.", "skills": ["Debugging"], "technologies": ["Node.js", ".NET"]}],
        }],
        "certifications": [{"name": "Certificate", "skills": ["AWS", "api\u00a0development"]}],
        "additional_evidence": [{"text": "Evidence", "skills": ["Mentoring"], "technologies": ["Docker", "Postgres", "PostgreSQL"]}],
    })
    setup = (
        f"const parityBank = {json.dumps(bank.model_dump())};\n"
        f"const expectedSkills = {json.dumps(list(build_skill_catalogue(bank).items()))};\n"
    )
    run_frontend_scenario(tmp_path, "catalogue_contract", setup)


def test_current_cv_uses_safe_dom_and_keeps_builder_separate():
    script = (STATIC / "current_cv.js").read_text()
    html = (STATIC / "index.html").read_text()
    assert "/static/current_cv.js" in html
    assert not any(unsafe in script for unsafe in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"])
    assert "result.textContent = text" in script
    assert 'id="workspace-view"' in html
    assert 'id="current-cv-view"' in html
    assert 'id="save-current-cv" type="submit" disabled' in html
    assert 'id="current-cv-fields" disabled' in html
    assert "loadedBank" not in script
    assert "readBank(" not in script
    assert 'fetchJSON("/experience-bank",' not in script  # No writes to the bank.


def test_successful_bank_save_notifies_builder_after_request():
    script = (STATIC / "app.js").read_text()
    handler = script.split('bankForm.addEventListener("submit"', 1)[1].split('matchForm.addEventListener', 1)[0]
    notification = 'window.dispatchEvent(new CustomEvent("experience-bank-saved", { detail: saved }));'
    assert handler.index(notification) > handler.index('await request("/experience-bank"')
    assert handler.index(notification) < handler.index("catch (error)")


def test_current_cv_view_and_script_are_served_by_existing_static_routes():
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "My Current CV" in page.text
    script = client.get("/static/current_cv.js")
    assert script.status_code == 200
    assert script.text == (STATIC / "current_cv.js").read_text()
