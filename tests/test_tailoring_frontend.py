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
    "management_labels", "management_add_delete_role", "management_add_delete_project",
    "management_credential_edit", "management_credentials_add_remove", "management_evidence_metadata",
    "management_validation", "management_server_validation", "management_save_failure", "management_saving_lock",
    "management_navigation_drafts", "management_new_analysis", "management_stale_references",
    "management_no_analysis", "management_load_failure", "management_safe_text", "management_payload_roundtrip", "management_metadata_edges", "management_additional",
    "tailor_pregeneration", "tailor_loading", "tailor_document", "tailor_review_groups", "tailor_group_expansion", "tailor_visible_warnings",
    "tailor_disclosures", "tailor_coverage", "tailor_declaration_coverage", "tailor_credentials", "tailor_missing_credential", "tailor_empty_sections",
    "tailor_regenerate_failure", "tailor_regenerate_retry", "tailor_regenerate_invalidation",
    "tailor_regenerate_stale_failure", "tailor_regenerate_loading", "tailor_render_failure",
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
    "results_structured", "results_importance", "results_or", "results_independent",
    "results_legacy", "results_legacy_support", "results_empty_structured", "results_empty_category",
    "results_filters", "results_empty_filter", "results_selection", "results_alternative_provenance",
    "results_caveats", "results_credentials", "results_missing", "results_unknown_support",
    "results_safe_text", "results_keyboard", "results_filtered_keyboard", "results_long_keyboard", "results_reset", "results_stale_match",
    "results_new_analysis", "results_no_requests", "results_preview", "results_all_requirements",
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
    run_tailoring_frontend_scenario(tmp_path, fixture_response, scenario)


def run_tailoring_frontend_scenario(tmp_path, fixture_response, scenario):
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
    return result.stdout


@pytest.mark.parametrize("scenario", ["management_payload_roundtrip", "management_metadata_edges"])
def test_management_record_payload_uses_existing_api_and_keeps_cv_references(tmp_path, monkeypatch, fixture_response, scenario):
    output = run_tailoring_frontend_scenario(tmp_path, fixture_response, scenario)
    payload = json.loads(next(line.removeprefix("BANKDOCUMENT ") for line in output.splitlines() if line.startswith("BANKDOCUMENT ")))
    expected = ExperienceBank.model_validate(payload)
    bank_repo = JsonExperienceBankRepository(tmp_path / "roundtrip-bank.json")
    cv_repo = JsonCurrentCVRepository(tmp_path / "roundtrip-cv.json")
    bank_repo.save(ExperienceBank.model_validate(fixture_response[1]["source_bank"]))
    cv = CurrentCV.model_validate({"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["testing", "oracle"]}]})
    cv_repo.save(cv)
    before_cv = cv_repo.path.read_bytes()
    monkeypatch.setattr("app.main.experience_bank_repository", bank_repo)
    monkeypatch.setattr("app.main.current_cv_repository", cv_repo)
    client = TestClient(app)
    response = client.put("/experience-bank", json=payload)
    assert response.status_code == 200
    assert response.json() == expected.model_dump()
    assert client.get("/experience-bank").json() == expected.model_dump()
    assert bank_repo.load() == expected
    assert cv_repo.path.read_bytes() == before_cv
    assert client.get("/current-cv").json()["reference_issues"] == []
    assert expected.education[0].id == "degree"
    if scenario == "management_payload_roundtrip":
        assert expected.education[0].qualification == "Renamed | qualification"
        assert expected.certifications[0].year is None
    else:
        assert expected.education[0].qualification == "Degree\r\n(placement)"
        assert expected.education[0].institution == " "
        assert expected.certifications[0].issuer == "😀" * 200
        assert expected.certifications[0].skills == ["Cloud\nplatforms", "AWS (EC2, S3)"]
        assert expected.certifications[0].year == "" and expected.projects[0].link == ""
    assert expected.certifications[0].id == "cert"
    assert expected.work_experience[0].achievements[0].text == "  Exact achievement.\r\nKeep these spaces.  "


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
    for action in ["show-workspace", "show-bank", "show-current-cv", "new-analysis", "stage-analyse", "stage-match", "stage-tailor", "continue-to-match", "match-generate-preview", "generate-tailored-preview", "filter-all", "filter-strong", "filter-related", "filter-missing"]:
        _, attrs, parents = markup.records[action]
        assert attrs["type"] == "button"
        assert not any(tag == "form" for tag, _ in parents), "Navigation must not submit existing feature forms."
        if "aria-controls" in attrs:
            assert attrs["aria-controls"] in markup.records
    for element, parent in [("bank-form", "bank-view"), ("match-form", "analyse-stage"),
                            ("overview", "analyse-stage"), ("match-groups", "match-stage"),
                            ("requirement-list", "match-stage"), ("requirement-evidence", "match-stage"),
                            ("tailored-cv-content", "tailor-stage"), ("current-cv-form", "current-cv-view")]:
        assert any(ancestor == parent for _, ancestor in markup.records[element][2])
    _, inspector, _ = markup.records["requirement-evidence"]
    assert inspector["tabindex"] == "0", "Scrollable desktop evidence must be keyboard reachable."
    assert inspector["aria-labelledby"] in markup.records
    assert markup.records["requirement-selection-status"][1]["role"] == "status"
    assert any(tag == "details" for tag, _ in markup.records["recommendations"][2]), "Supplementary evidence stays discoverable in a disclosure."
    assert list(markup.records).index("tailored-cv-content") < list(markup.records).index("tailoring-review-title"), "The document precedes review content on mobile and for screen readers."
    for element in ["tailoring-empty", "tailoring-warnings", "tailored-cv-content", "tailoring-summary"]:
        attrs = markup.records[element][1]
        assert "aria-label" in attrs or attrs.get("aria-labelledby") in markup.records
    assert markup.records["tailoring-state"][1]["role"] == "status"
    assert markup.records["tailoring-error"][1]["role"] == "alert"
    assert markup.records["tailoring-coverage-title"][0] == "summary"
    assert not any(tag == "details" for tag, _ in markup.records["tailoring-warnings"][2]), "Preview warnings stay outside collapsed groups."
    assert list(markup.records).index("tailoring-warnings") < list(markup.records).index("tailoring-decisions"), "Warnings precede detailed recommendation groups."
    assert markup.records["tailored-cv-content"][1]["class"] == "tailored-document", "Tailor styling does not change the Current CV editor preview."
    assert markup.records["bank-message"][0] == "div", "Structured server errors need a container that can contain a list."
    assert markup.records["cv-draft-preview"][1]["tabindex"] == "0", "The scrollable desktop draft preview is keyboard reachable."
    html = (STATIC / "index.html").read_text()
    for href in re.findall(r'href="#((?:bank|cv)-[^"]+)"', html):
        assert href in markup.records, "Internal section links must resolve to actual editor sections."
    assert 'one item per line: qualification |' not in html



def test_workspace_controller_is_served_without_a_framework_or_network_side_effects():
    client = TestClient(app)
    script = (STATIC / "workspace.js").read_text()
    assert client.get("/static/workspace.js").text == script
    assert '/static/workspace.js' in client.get("/").text
    for unsafe in ["innerHTML", "outerHTML", "localStorage", "sessionStorage", "fetch(", "request(", "console."]:
        assert unsafe not in script
