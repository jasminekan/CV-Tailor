"""Coverage/grouping contracts for controlled provider data, not live extraction."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import JobDescriptionExtraction
from app.services import llm


JOB_DESCRIPTION = (
    "We are hiring a Software Engineer to develop and maintain backend APIs.\n\n"
    "Candidates must have experience with Python or Java and relational databases.\n\n"
    "Experience with AWS or Azure is desirable but not essential.\n\n"
    "You will collaborate with engineers to design software solutions and deploy "
    "applications to cloud infrastructure.\n\n"
    "A Bachelor's degree in Computer Science or a related field is preferred."
)
EXPECTED_RESPONSIBILITIES = [
    "Develop and maintain backend APIs.",
    "Collaborate with engineers to design software solutions.",
    "Deploy applications to cloud infrastructure.",
]
DEGREE = "Bachelor's degree in Computer Science or a related field"
STATIC_SCRIPT = Path(__file__).resolve().parents[1] / "static" / "app.js"


@pytest.fixture
def provider_payload():
    def item(text, source_text, category, importance="unspecified", alternatives=None, activity=None):
        return {
            "text": text, "source_text": source_text, "category": category,
            "importance": importance, "alternatives": alternatives or [text], "activity": activity,
        }

    prior_experience = "Candidates must have experience with Python or Java and relational databases."
    future_work = (
        "You will collaborate with engineers to design software solutions and deploy "
        "applications to cloud infrastructure."
    )
    return {
        "job_title": "Software Engineer",
        "requirements": [
            item(EXPECTED_RESPONSIBILITIES[0],
                 "We are hiring a Software Engineer to develop and maintain backend APIs.",
                 "responsibility", activity="api_development"),
            item("Python or Java", prior_experience, "skill", "required", ["Python", "Java"]),
            item("Relational databases", prior_experience, "skill", "required"),
            item("AWS or Azure", "Experience with AWS or Azure is desirable but not essential.",
                 "skill", "preferred", ["AWS", "Azure"]),
            item(EXPECTED_RESPONSIBILITIES[1], future_work, "responsibility"),
            item(EXPECTED_RESPONSIBILITIES[2], future_work, "responsibility", activity="cloud_deployment"),
            # Shared degree level and subject alternatives stay opaque, not cross-paired.
            item(DEGREE, "A Bachelor's degree in Computer Science or a related field is preferred.",
                 "qualification", "preferred"),
        ],
    }


@pytest.fixture
def analyse_with_mocked_provider(monkeypatch):
    """Exercise the actual route/service/projection with a mocked SDK boundary."""
    def analyse(payload):
        calls = []

        def parse(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                parsed=payload, refusal=None,
            ))])

        monkeypatch.setattr(llm, "Settings", lambda: SimpleNamespace(
            openai_api_key="test-key", openai_model="test-model",
        ))
        monkeypatch.setattr(llm, "OpenAI", lambda api_key: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)),
        ))
        response = TestClient(app).post("/analyse", json={"job_description": JOB_DESCRIPTION})
        return response, calls

    return analyse


def test_exact_manual_description_preserves_duties_and_structured_metadata(
    provider_payload, analyse_with_mocked_provider,
):
    response, calls = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 200
    result = response.json()
    assert calls[0]["messages"][1] == {"role": "user", "content": JOB_DESCRIPTION}
    assert calls[0]["messages"][0] == {"role": "system", "content": llm.EXTRACTION_PROMPT}
    assert calls[0]["response_format"] is JobDescriptionExtraction
    assert result["job_title"] == "Software Engineer"
    assert result["responsibilities"] == EXPECTED_RESPONSIBILITIES
    assert result["technical_skills"] == ["Python or Java", "Relational databases", "AWS or Azure"]
    assert result["qualifications"] == [DEGREE]
    assert result["other_keywords"] == []
    assert [
        (item["text"], item["category"], item["importance"], item["activity"])
        for item in result["requirements"]
    ] == [
        (EXPECTED_RESPONSIBILITIES[0], "responsibility", "unspecified", "api_development"),
        ("Python or Java", "skill", "required", None),
        ("Relational databases", "skill", "required", None),
        ("AWS or Azure", "skill", "preferred", None),
        (EXPECTED_RESPONSIBILITIES[1], "responsibility", "unspecified", None),
        (EXPECTED_RESPONSIBILITIES[2], "responsibility", "unspecified", "cloud_deployment"),
        (DEGREE, "qualification", "preferred", None),
    ]

    by_text = {item["text"]: item for item in result["requirements"]}
    assert by_text["Python or Java"]["importance"] == "required"
    assert by_text["Python or Java"]["alternatives"] == ["Python", "Java"]
    assert by_text["Relational databases"]["importance"] == "required"
    assert by_text["AWS or Azure"]["importance"] == "preferred"
    assert by_text["AWS or Azure"]["alternatives"] == ["AWS", "Azure"]
    assert by_text["AWS or Azure"]["activity"] is None
    assert by_text[DEGREE]["importance"] == "preferred"
    assert by_text[DEGREE]["category"] == "qualification"
    assert by_text[DEGREE]["alternatives"] == [DEGREE]

    duties = [item for item in result["requirements"] if item["category"] == "responsibility"]
    assert [item["text"] for item in duties] == EXPECTED_RESPONSIBILITIES
    assert all(item["importance"] == "unspecified" for item in duties)
    assert [item["activity"] for item in duties] == ["api_development", None, "cloud_deployment"]
    assert all(item["source_text"] in JOB_DESCRIPTION for item in result["requirements"])
    assert [item["id"] for item in result["requirements"]] == [f"r{i}" for i in range(1, 8)]
    repeated, _ = analyse_with_mocked_provider(provider_payload)
    assert repeated.json() == result


def test_prompt_explicitly_preserves_future_duties_and_requirement_local_activities():
    prompt = " ".join(llm.EXTRACTION_PROMPT.split())
    for instruction in (
        "Extract future job responsibilities throughout the description",
        "including introductory role descriptions and 'You will' paragraphs",
        "even when they are not requirements for previous experience",
        "must not cause future responsibilities to be omitted",
        "Assign an activity only when that specific requirement's source_text explicitly supports the activity",
        "Do not borrow activities from other requirements, sentences or paragraphs",
        "not another duty mentioned in a shared source quotation",
        "it does not establish required previous deployment experience",
    ):
        assert instruction in prompt


def test_prompt_requires_sentence_coverage_and_preserves_nonessential_preferences():
    prompt = " ".join(llm.EXTRACTION_PROMPT.split())
    for instruction in (
        "Examine every paragraph and sentence for distinct responsibilities, required skills, preferred skills and qualifications",
        "including introductory role descriptions",
        "Do not omit desirable, preferred or nonessential requirements",
        "'desirable but not essential' explicitly supports preferred, not exclusion",
        "'Not essential' alone does not establish preferred importance",
        "Extract distinct responsibilities as separate items even when they appear in the same paragraph or sentence",
    ):
        assert instruction in prompt


def test_prompt_limits_multiple_alternatives_to_supported_or_choices():
    prompt = " ".join(llm.EXTRACTION_PROMPT.split())
    for instruction in (
        "Use multiple alternatives only for genuine OR choices explicitly supported by the source text",
        "For a requirement without genuine alternatives, use one complete meaningful alternative",
        "Do not turn combined actions, purposes or steps into interchangeable options",
        "Preserve actions linked by purpose as one combined responsibility",
        "'Python or Java' is one skill requirement with alternatives ['Python', 'Java']",
        "'Collaborate with engineers to design software solutions' is one combined responsibility with the single alternative ['Collaborate with engineers to design software solutions']",
    ):
        assert instruction in prompt


def test_mocked_or_groups_and_combined_duties_survive_projection_without_splitting(
    provider_payload, analyse_with_mocked_provider,
):
    """Projection preserves correct provider grouping; this cannot test model quality."""
    response, _ = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 200
    requirements = response.json()["requirements"]
    assert [
        (item["text"], item["alternatives"])
        for item in requirements if len(item["alternatives"]) > 1
    ] == [("Python or Java", ["Python", "Java"]), ("AWS or Azure", ["AWS", "Azure"])]

    duties = [item for item in requirements if item["category"] == "responsibility"]
    assert [item["alternatives"] for item in duties] == [[text] for text in EXPECTED_RESPONSIBILITIES]
    collaboration, deployment = duties[1:]
    # Two duties in the same sentence remain independent; collaboration/design
    # remains one combined action, rather than either action being an OR option.
    assert collaboration["source_text"] == deployment["source_text"]
    assert collaboration["id"] != deployment["id"]
    assert response.json()["responsibilities"] == EXPECTED_RESPONSIBILITIES


def test_corrected_cloud_extraction_keeps_preferred_platforms_separate_from_future_deployment(
    provider_payload, analyse_with_mocked_provider,
):
    before = json.dumps(provider_payload, sort_keys=True)
    response, _ = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 200
    by_text = {item["text"]: item for item in response.json()["requirements"]}
    platforms = by_text["AWS or Azure"]
    deployment = by_text[EXPECTED_RESPONSIBILITIES[2]]
    collaboration = by_text[EXPECTED_RESPONSIBILITIES[1]]
    assert (platforms["category"], platforms["importance"], platforms["activity"]) == (
        "skill", "preferred", None,
    )
    assert platforms["alternatives"] == ["AWS", "Azure"]
    assert platforms["source_text"] == "Experience with AWS or Azure is desirable but not essential."
    assert (deployment["category"], deployment["importance"], deployment["activity"]) == (
        "responsibility", "unspecified", "cloud_deployment",
    )
    assert deployment["source_text"] != platforms["source_text"]
    # Shared source wording does not transfer deployment to the collaboration duty.
    assert collaboration["source_text"] == deployment["source_text"]
    assert collaboration["activity"] is None
    assert json.dumps(provider_payload, sort_keys=True) == before


def test_noncontiguous_duty_quote_reports_its_requirement_without_private_wording(
    provider_payload, analyse_with_mocked_provider, caplog,
):
    # "You will" and "deploy" are separated by the collaboration clause in
    # the original description; joining them invents a contiguous quotation.
    provider_payload["requirements"][5]["source_text"] = "You will deploy applications to cloud infrastructure."
    response, _ = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 502
    assert response.json() == {"detail": "The job description could not be analysed."}
    assert "stage=source_validation" in caplog.text
    assert "requirement_id=r6" in caplog.text
    assert provider_payload["requirements"][5]["source_text"] not in caplog.text
    assert JOB_DESCRIPTION not in caplog.text
    assert "test-key" not in caplog.text


def test_reported_live_analysis_replays_omitted_duties_and_unsupported_cloud_activity(
    provider_payload, analyse_with_mocked_provider,
):
    """Replay only the reported analysis content, excluding personal match evidence.

    This diagnoses the current semantic-validation gap; it does not establish
    the reported cloud activity as an expected extraction interpretation.
    """
    reported = [provider_payload["requirements"][index] for index in (1, 2, 3, 6)]
    reported[0]["text"] = "experience with Python or Java"
    reported[1]["text"] = "experience with relational databases"
    reported[2]["text"] = "experience with AWS or Azure"
    reported[1]["alternatives"] = ["relational databases"]
    reported[2]["activity"] = "cloud_deployment"
    reported[3]["alternatives"] = [
        "Bachelor's degree in Computer Science", "Bachelor's degree in a related field",
    ]
    payload = {"job_title": "Software Engineer", "requirements": reported}
    response, _ = analyse_with_mocked_provider(payload)
    assert response.status_code == 200
    result = response.json()
    assert result["responsibilities"] == []
    assert result["technical_skills"] == [
        "experience with Python or Java", "experience with relational databases",
        "experience with AWS or Azure",
    ]
    assert result["other_keywords"] == []
    assert result["qualifications"] == [DEGREE]
    assert [item["id"] for item in result["requirements"]] == ["r1", "r2", "r3", "r4"]
    assert [item["importance"] for item in result["requirements"]] == [
        "required", "required", "preferred", "preferred",
    ]
    assert result["requirements"][0]["alternatives"] == ["Python", "Java"]
    assert result["requirements"][2]["alternatives"] == ["AWS", "Azure"]
    cloud = result["requirements"][2]
    assert cloud["source_text"] == "Experience with AWS or Azure is desirable but not essential."
    assert cloud["source_text"] in JOB_DESCRIPTION
    # Quote provenance and enum validation cannot detect an unsupported activity.
    assert cloud["activity"] == "cloud_deployment"
    assert not any(item["category"] == "responsibility" for item in result["requirements"])


@pytest.mark.parametrize("failure_mode", ["omitted", "miscategorised"])
def test_empty_responsibilities_can_originate_in_provider_output(
    failure_mode, provider_payload, analyse_with_mocked_provider,
):
    if failure_mode == "omitted":
        provider_payload["requirements"] = [
            item for item in provider_payload["requirements"] if item["category"] != "responsibility"
        ]
    else:
        for item in provider_payload["requirements"]:
            if item["category"] == "responsibility":
                item["category"] = "other_keyword" if item["activity"] is None else "skill"

    response, _ = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 200
    result = response.json()
    assert result["responsibilities"] == []
    assert not any(item["category"] == "responsibility" for item in result["requirements"])
    assert result["qualifications"] == [DEGREE]
    assert "Python or Java" in result["technical_skills"]
    assert "AWS or Azure" in result["technical_skills"]


@pytest.mark.parametrize("include_duties", [True, False])
def test_actual_analysis_renderer_displays_projected_duties_in_both_views(
    tmp_path, include_duties, provider_payload, analyse_with_mocked_provider,
):
    runtime = shutil.which("node") or shutil.which("jsc")
    if not runtime:
        system_jsc = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")
        if system_jsc.is_file():
            runtime = str(system_jsc)
    if not runtime:
        pytest.skip("JavaScript runtime unavailable; run with Node or JavaScriptCore.")

    if not include_duties:
        provider_payload["requirements"] = [
            item for item in provider_payload["requirements"] if item["category"] != "responsibility"
        ]
    response, _ = analyse_with_mocked_provider(provider_payload)
    assert response.status_code == 200
    source = STATIC_SCRIPT.read_text(encoding="utf-8")
    node_function = "function node(" + source.split("function node(", 1)[1].split("\nfunction disclosure", 1)[0]
    renderer = "function renderAnalysis(" + source.split("function renderAnalysis(", 1)[1].split("\nfunction requirementRow", 1)[0]
    # Execute the real renderer against a minimal DOM, without running bank/CV code.
    script = tmp_path / "analysis_renderer.js"
    script.write_text(
        """class Element {
  constructor(tag) { this.tag = tag; this.textContent = ''; this.children = []; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
}
const targets = { '#overview': new Element('div'), '#full-analysis': new Element('div') };
const document = {
  createElement: tag => new Element(tag),
  querySelector: selector => targets[selector],
};
"""
        + node_function + renderer
        + f"\nconst analysis = {json.dumps(response.json())};\n"
        + f"const expected = {json.dumps(EXPECTED_RESPONSIBILITIES if include_duties else ['None identified'])};\n"
        + """const before = JSON.stringify(analysis);
renderAnalysis(analysis);
for (const target of Object.values(targets)) {
  const card = target.children.find(item => item.children[0].textContent === 'Responsibilities');
  const displayed = card.children.find(item => item.tag === 'ul').children.map(item => item.textContent);
  if (JSON.stringify(displayed) !== JSON.stringify(expected)) throw new Error(JSON.stringify(displayed));
}
if (JSON.stringify(analysis) !== before) throw new Error('Renderer mutated analysis');
""",
        encoding="utf-8",
    )
    completed = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
