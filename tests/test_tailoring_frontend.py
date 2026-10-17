"""Actual vanilla scripts with mocked DOM/network and an isolated API fixture.

These are behaviour/contract tests, not visual browser or live extraction tests.
"""

import json
from pathlib import Path
from html.parser import HTMLParser
import re
import shutil
import subprocess
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import CurrentCV, ExperienceBank
from app.repositories.json_current_cv import JsonCurrentCVRepository
from app.repositories.json_experience_bank import JsonExperienceBankRepository
from app.services.job_extraction import analysis_from_extraction
from evaluations.extraction.harness import load_fixtures


STATIC = Path(__file__).resolve().parents[1] / "static"
SCENARIOS = [
    "initial", "explicit_request", "exact_work", "project_text", "skills", "credentials", "order",
    "indicators", "omissions", "explanations", "coverage", "loading_duplicate", "api_error", "retry",
    "analysis_error", "match_error_after_analysis", "empty", "missing_baseline", "stale_refs",
    "missing_destinations", "unsupported_destination", "safe_text", "new_analysis_pending_preview",
    "old_preview_failure", "old_preview_finally", "edit_during_analyse", "edit_during_match",
    "edit_during_preview", "analysis_duplicate", "regenerate", "no_mutation", "snapshot_use",
    "empty_requirements", "limited_coverage", "related_only", "stale_analysis_failure", "edit_back_to_original",
    "workspace_navigation", "workspace_stages", "workspace_return_stage", "workspace_pregeneration",
    "workspace_generate_action", "workspace_drafts", "workspace_preserve_session", "workspace_new_empty",
    "workspace_new_cancel", "workspace_new_confirm", "workspace_cancel_preview", "workspace_reset_analysis",
    "workspace_reset_match", "workspace_reset_preview", "workspace_mobile_menu", "workspace_accessibility",
    "workspace_match_loading", "workspace_match_failure", "workspace_navigation_while_matching", "workspace_cv_save_lock",
    "workspace_new_cleared_source",
    "workspace_new_management_only",
]


@pytest.fixture
def fixture_response(tmp_path, monkeypatch):
    case = load_fixtures().cases[0]
    analysis = analysis_from_extraction(case.expected_extraction(), case.job_description)
    bank = ExperienceBank.model_validate({
        "skills": [" Python\t", "SQL", "Oracle Database", "FastAPI", "Azure AI Search", "Testing"],
        "work_experience": [
            {"id": "role-a", "employer": "Example & Co", "role": "Engineer", "start_date": "2023",
             "summary": "  Original role context.\nPreserve spacing.  ", "achievements": [
                {"id": "testing", "text": "Wrote regression tests for reporting tools."},
                {"id": "old", "text": "Helped with an internal database task.", "technologies": ["Oracle Database"]},
                {"id": "oracle", "text": "  Developed SQL stored procedures in Oracle to automate production data calculations, replacing manual processing with repeatable database logic\n",
                 "technologies": ["Oracle Database", "SQL"]},
            ]},
            {"id": "role-b", "role": "Earlier Developer", "employer": "Earlier employer", "achievements": [
                {"id": "general", "text": "Original earlier role achievement."},
            ]},
        ],
        "projects": [{"id": "jobmatch", "name": "  JobMatch  ", "description": "Original project description.\nKeep this.",
            "link": "https://example.com/project", "evidence": [
                {"id": "api", "text": "  Designed and implemented REST API endpoints using Python and FastAPI for job description analysis, experience-bank management and evidence matching, exposing Azure AI Search index status.\n",
                 "technologies": ["Python", "FastAPI", "Azure AI Search"]},
                {"id": "unselected", "text": "Unselected project documentation."},
            ]}],
        "education": [{"id": "degree", "qualification": "BSc Hons Computer Science", "institution": "Example University", "field": "Computer Science", "year": "2024"}],
        "certifications": [{"id": "cert", "name": "Original certificate", "issuer": "Example issuer", "year": "2025", "skills": ["Testing"]}],
    })
    cv = CurrentCV.model_validate({
        "work_experience": [{"work_experience_id": "role-b", "achievement_ids": ["general"]},
                            {"work_experience_id": "role-a", "achievement_ids": ["testing", "old"]}],
        "skill_groups": [{"name": "  Languages  ", "skill_keys": ["python"]},
                         {"name": "Engineering", "skill_keys": ["testing"]}],
        "tailoring_settings": {"max_achievements_per_role": 2, "max_projects": 1,
                               "max_contributions_per_project": 1, "max_skills": 6},
    })
    bank_repo = JsonExperienceBankRepository(tmp_path / "bank.json")
    cv_repo = JsonCurrentCVRepository(tmp_path / "cv.json")
    bank_repo.save(bank)
    cv_repo.save(cv)
    before = bank_repo.path.read_bytes(), cv_repo.path.read_bytes()
    monkeypatch.setattr("app.main.experience_bank_repository", bank_repo)
    monkeypatch.setattr("app.main.current_cv_repository", cv_repo)
    forbidden = Mock(side_effect=AssertionError("No persistence or OpenAI in preview tests."))
    monkeypatch.setattr(bank_repo, "save", forbidden)
    monkeypatch.setattr(cv_repo, "save", forbidden)
    monkeypatch.setattr("app.services.llm.OpenAI", forbidden)
    response = TestClient(app).post("/tailoring/preview", json={"job_analysis": analysis.model_dump()})
    assert response.status_code == 200
    assert before == (bank_repo.path.read_bytes(), cv_repo.path.read_bytes())
    return analysis.model_dump(), response.json(), case.job_description


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_tailoring_frontend_behaviour(tmp_path, fixture_response, scenario):
    runtime = shutil.which("node") or shutil.which("jsc")
    if not runtime:
        system_jsc = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")
        if system_jsc.is_file():
            runtime = str(system_jsc)
    if not runtime:
        pytest.skip("JavaScript runtime unavailable; use Node or JavaScriptCore.")
    analysis, response, description = fixture_response
    html = (STATIC / "index.html").read_text()
    identifiers = re.findall(r'\bid="([^"]+)"', html)
    prelude, assertions = Path(__file__).with_name("tailoring_frontend_harness.js").read_text().split("// INSERT APPLICATION HERE", 1)
    script = tmp_path / "tailoring_frontend_test.js"
    script.write_text(
        f"const scenario = {json.dumps(scenario)};\n"
        f"const fixtureAnalysis = {json.dumps(analysis)};\n"
        f"const fixturePreview = {json.dumps(response)};\n"
        f"const fixtureDescription = {json.dumps(description)};\n"
        f"const htmlIds = {json.dumps(identifiers)};\n"
        + prelude + (STATIC / "workspace.js").read_text() + "\n" + (STATIC / "app.js").read_text() + "\n"
        + (STATIC / "current_cv.js").read_text() + "\n"
        + (STATIC / "tailoring_preview.js").read_text() + assertions,
        encoding="utf-8",
    )
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS {scenario}" in result.stdout


def test_preview_assets_are_served_and_use_safe_read_only_dom():
    client = TestClient(app)
    script = (STATIC / "tailoring_preview.js").read_text()
    html = client.get("/").text
    assert '/static/tailoring_preview.js' in html
    assert client.get("/static/tailoring_preview.js").text == script
    assert re.search(r'<button[^>]*id="generate-tailored-preview"[^>]*disabled', html)
    for unsafe in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "localStorage", "sessionStorage", "console."]:
        assert unsafe not in script
    assert 'request("/tailoring/preview"' in script
    assert script.count("await request(") == 1
    assert 'method: "POST"' in script and 'method: "PUT"' not in script
    assert 'id="diagnostics"' in html and 'id="current-cv-view"' in html


def test_workspace_shell_preserves_semantic_panels_and_non_submitting_navigation():
    class Markup(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.records = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                assert attrs["id"] not in self.records, "Duplicate DOM IDs break feature references."
                self.records[attrs["id"]] = (tag, attrs, list(self.stack))
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self.stack.append((tag, attrs.get("id")))

        def handle_endtag(self, tag):
            assert self.stack and self.stack[-1][0] == tag, f"Mismatched {tag} closes a view or form."
            self.stack.pop()

    markup = Markup()
    markup.feed((STATIC / "index.html").read_text())
    assert markup.stack == []
    for action in ["show-workspace", "show-bank", "show-current-cv", "new-analysis", "stage-analyse", "stage-match", "stage-tailor", "continue-to-match", "match-generate-preview"]:
        _, attrs, parents = markup.records[action]
        assert attrs["type"] == "button"
        assert not any(tag == "form" for tag, _ in parents), "Navigation must not submit existing feature forms."
        if "aria-controls" in attrs:
            assert attrs["aria-controls"] in markup.records
    for element, parent in [("bank-form", "bank-view"), ("match-form", "analyse-stage"),
                            ("overview", "analyse-stage"), ("match-groups", "match-stage"),
                            ("tailored-cv-content", "tailor-stage"), ("current-cv-form", "current-cv-view")]:
        assert any(ancestor == parent for _, ancestor in markup.records[element][2])


def test_workspace_controller_is_served_without_a_framework_or_network_side_effects():
    client = TestClient(app)
    script = (STATIC / "workspace.js").read_text()
    assert client.get("/static/workspace.js").text == script
    assert '/static/workspace.js' in client.get("/").text
    for unsafe in ["innerHTML", "outerHTML", "localStorage", "sessionStorage", "fetch(", "request(", "console."]:
        assert unsafe not in script
