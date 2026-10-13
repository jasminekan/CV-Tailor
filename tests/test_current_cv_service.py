import pytest
from pydantic import ValidationError

from app.models import CurrentCV, CurrentCVSkillGroup, ExperienceBank
from app.services.current_cv import build_skill_catalogue, validate_current_cv_references


@pytest.fixture
def bank():
    return ExperienceBank.model_validate({
        "skills": ["Python"],
        "work_experience": [
            {
                "id": "role-a", "employer": "Example", "role": "Engineer",
                "skills": ["Backend"], "technologies": ["FastAPI"],
                "achievements": [
                    {
                        "id": "achievement-a1", "text": "Built an API.",
                        "skills": ["API development"], "technologies": ["SQLite"],
                    },
                    {"id": "achievement-a2", "text": "Wrote tests."},
                ],
            },
            {
                "id": "role-b", "employer": "Other", "role": "Developer",
                "technologies": ["Go"],
                "achievements": [{"id": "achievement-b", "text": "Built a service."}],
            },
        ],
        "projects": [
            {
                "id": "project-a", "name": "Automation project",
                "skills": ["Automation"], "technologies": ["JavaScript"],
                "evidence": [{
                    "id": "contribution-a", "text": "Built a tool.",
                    "skills": ["Debugging"], "technologies": ["Node.js"],
                }],
            },
            {
                "id": "project-b", "name": "Other project",
                "evidence": [{"id": "contribution-b", "text": "Added tests."}],
            },
        ],
        "certifications": [{"id": "cert", "name": "Cloud certificate", "skills": ["AWS"]}],
        "additional_evidence": [{
            "id": "additional", "text": "Supported a team.",
            "skills": ["Mentoring"], "technologies": ["Docker"],
        }],
    })


@pytest.fixture
def current_cv():
    return CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-b", "achievement_ids": ["achievement-b"]},
            {"work_experience_id": "role-a", "achievement_ids": ["achievement-a2", "achievement-a1"]},
        ],
        "projects": [
            {"project_id": "project-b", "contribution_ids": ["contribution-b"]},
            {"project_id": "project-a", "contribution_ids": ["contribution-a"]},
        ],
        "skill_groups": [
            {"name": "Languages", "skill_keys": ["go", "python"]},
            {"name": "Tools", "skill_keys": ["node.js", "aws", "sqlite", "docker"]},
        ],
        "tailoring_settings": {"max_projects": 0, "max_skills": 0},
    })


@pytest.mark.parametrize("payload", [
    {"skills": ["Source Skill"]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "skills": ["Source Skill"]}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "technologies": ["Source Skill"]}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "achievements": [
        {"text": "Achievement", "skills": ["Source Skill"]},
    ]}]},
    {"work_experience": [{"employer": "Example", "role": "Engineer", "achievements": [
        {"text": "Achievement", "technologies": ["Source Skill"]},
    ]}]},
    {"projects": [{"name": "Project", "skills": ["Source Skill"]}]},
    {"projects": [{"name": "Project", "technologies": ["Source Skill"]}]},
    {"projects": [{"name": "Project", "evidence": [{"text": "Contribution", "skills": ["Source Skill"]}]}]},
    {"projects": [{"name": "Project", "evidence": [{"text": "Contribution", "technologies": ["Source Skill"]}]}]},
    {"certifications": [{"name": "Certificate", "skills": ["Source Skill"]}]},
    {"additional_evidence": [{"text": "Evidence", "skills": ["Source Skill"]}]},
    {"additional_evidence": [{"text": "Evidence", "technologies": ["Source Skill"]}]},
])
def test_catalogue_collects_each_supported_source(payload):
    catalogue = build_skill_catalogue(ExperienceBank.model_validate(payload))
    assert catalogue == {"source skill": "Source Skill"}
    # Every produced key is accepted by the existing Phase 1 skill model.
    CurrentCVSkillGroup(name="Skills", skill_keys=list(catalogue))


def test_catalogue_has_deterministic_traversal_order(bank):
    expected = [
        ("python", "Python"), ("backend", "Backend"), ("fastapi", "FastAPI"),
        ("api development", "API development"), ("sqlite", "SQLite"), ("go", "Go"),
        ("automation", "Automation"), ("javascript", "JavaScript"),
        ("debugging", "Debugging"), ("node.js", "Node.js"), ("aws", "AWS"),
        ("mentoring", "Mentoring"), ("docker", "Docker"),
    ]
    assert list(build_skill_catalogue(bank).items()) == expected
    assert list(build_skill_catalogue(bank).items()) == expected


def test_catalogue_deduplicates_case_whitespace_and_keeps_first_original_label():
    bank = ExperienceBank.model_validate({
        "skills": [" Python ", "API\t Development", "python"],
        "work_experience": [{
            "employer": "Example", "role": "Engineer",
            "skills": ["PYTHON", " API   development "],
            "technologies": [" FastAPI "],
            "achievements": [{"text": "Achievement", "technologies": ["FASTAPI"]}],
        }],
        "projects": [{"name": "Project", "technologies": ["fastapi"]}],
        "certifications": [{"name": "Certificate", "skills": ["api\u00a0development"]}],
        "additional_evidence": [{"text": "Evidence", "skills": ["PYTHON"]}],
    })
    assert list(build_skill_catalogue(bank).items()) == [
        ("python", " Python "), ("api development", "API\t Development"),
        ("fastapi", " FastAPI "),
    ]


def test_catalogue_preserves_punctuation_and_does_not_merge_matching_aliases():
    labels = ["C", "C++", "C#", ".NET", "Node.js", "JS", "JavaScript", "Postgres", "PostgreSQL", "unit testing", "testing"]
    catalogue = build_skill_catalogue(ExperienceBank(skills=labels))
    assert list(catalogue) == [
        "c", "c++", "c#", ".net", "node.js", "js", "javascript", "postgres", "postgresql", "unit testing", "testing",
    ]
    assert list(catalogue.values()) == labels


def test_catalogue_does_not_infer_from_text_outcomes_or_record_names():
    bank = ExperienceBank.model_validate({
        "work_experience": [{
            "employer": "Rust Company", "role": "Python Engineer", "summary": "Built Go services.",
            "achievements": [{"text": "Used Java.", "outcomes": ["Improved SQL performance."]}],
        }],
        "projects": [{
            "name": "JavaScript Project", "description": "Used TypeScript.",
            "evidence": [{"text": "Used Kotlin.", "outcomes": ["Deployed to AWS."]}],
        }],
        "education": [{"institution": "University", "qualification": "C++ course", "field": "C#"}],
        "certifications": [{"name": "Azure Certificate", "issuer": "Microsoft"}],
        "additional_evidence": [{"text": "Used Ruby.", "outcomes": ["Learned Docker."]}],
    })
    assert build_skill_catalogue(bank) == {}


def test_empty_bank_has_empty_catalogue_and_empty_cv_has_no_issues():
    bank = ExperienceBank()
    assert build_skill_catalogue(bank) == {}
    assert validate_current_cv_references(CurrentCV(), bank) == []


def test_valid_references_in_cv_order_pass_without_enforcing_tailoring_limits(bank, current_cv):
    assert validate_current_cv_references(current_cv, bank) == []


def test_valid_parents_without_bullets_and_empty_skill_groups_are_allowed(bank):
    cv = CurrentCV.model_validate({
        "work_experience": [{"work_experience_id": "role-a"}],
        "projects": [{"project_id": "project-a"}],
        "skill_groups": [{"name": "Empty"}],
    })
    assert validate_current_cv_references(cv, bank) == []


@pytest.mark.parametrize("payload,expected", [
    (
        {"work_experience": [{"work_experience_id": "deleted-role"}]},
        {"path": "work_experience[0].work_experience_id", "reference": "deleted-role", "reason": "Work experience does not exist in the experience bank."},
    ),
    (
        {"projects": [{"project_id": "deleted-project"}]},
        {"path": "projects[0].project_id", "reference": "deleted-project", "reason": "Project does not exist in the experience bank."},
    ),
    (
        {"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["deleted-achievement"]}]},
        {"path": "work_experience[0].achievement_ids[0]", "reference": "deleted-achievement", "reason": "Achievement does not exist in the experience bank."},
    ),
    (
        {"projects": [{"project_id": "project-a", "contribution_ids": ["deleted-contribution"]}]},
        {"path": "projects[0].contribution_ids[0]", "reference": "deleted-contribution", "reason": "Contribution does not exist in the experience bank."},
    ),
    (
        {"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["achievement-b"]}]},
        {"path": "work_experience[0].achievement_ids[0]", "reference": "achievement-b", "reason": "Achievement does not belong to the selected work experience."},
    ),
    (
        {"projects": [{"project_id": "project-a", "contribution_ids": ["contribution-b"]}]},
        {"path": "projects[0].contribution_ids[0]", "reference": "contribution-b", "reason": "Contribution does not belong to the selected project."},
    ),
    (
        {"skill_groups": [{"name": "Languages", "skill_keys": ["unavailable-skill"]}]},
        {"path": "skill_groups[0].skill_keys[0]", "reference": "unavailable-skill", "reason": "Skill key is not available in the experience bank."},
    ),
])
def test_broken_reference_reports_exact_location_reference_and_reason(bank, payload, expected):
    cv = CurrentCV.model_validate(payload)
    assert [issue.model_dump() for issue in validate_current_cv_references(cv, bank)] == [expected]


@pytest.mark.parametrize("payload", [
    {"work_experience": [{"work_experience_id": "project-a"}]},
    {"projects": [{"project_id": "role-a"}]},
    {"work_experience": [{"work_experience_id": "role-a", "achievement_ids": ["contribution-a"]}]},
    {"projects": [{"project_id": "project-a", "contribution_ids": ["achievement-a1"]}]},
    {"work_experience": [{"work_experience_id": "ROLE-A"}]},
    {"work_experience": [{"work_experience_id": " role-a "}]},
])
def test_references_require_exact_ids_of_the_correct_record_type(bank, payload):
    issues = validate_current_cv_references(CurrentCV.model_validate(payload), bank)
    assert len(issues) == 1
    assert "does not exist" in issues[0].reason


@pytest.mark.parametrize("section,child_field,selection_field,bullet_field", [
    ("work_experience", "achievements", "work_experience_id", "achievement_ids"),
    ("projects", "evidence", "project_id", "contribution_ids"),
])
def test_deleting_a_selected_parent_and_its_bullets_reports_every_reference(
    bank, current_cv, section, child_field, selection_field, bullet_field,
):
    payload = bank.model_dump()
    deleted = payload[section].pop(1)
    changed_bank = ExperienceBank.model_validate(payload)
    issues = validate_current_cv_references(current_cv, changed_bank)
    expected = [
        (f"{section}[0].{selection_field}", deleted["id"]),
        (f"{section}[0].{bullet_field}[0]", deleted[child_field][0]["id"]),
    ]
    if section == "work_experience":
        # This role also held the last explicit source of the selected Go skill.
        expected.append(("skill_groups[0].skill_keys[0]", "go"))
    assert [(issue.path, issue.reference) for issue in issues] == expected


@pytest.mark.parametrize("section,child_field,bullet_field", [
    ("work_experience", "achievements", "achievement_ids"),
    ("projects", "evidence", "contribution_ids"),
])
def test_moving_selected_bullet_to_another_parent_is_detected(
    bank, current_cv, section, child_field, bullet_field,
):
    payload = bank.model_dump()
    moved = payload[section][1][child_field].pop(0)
    payload[section][0][child_field].append(moved)
    changed_bank = ExperienceBank.model_validate(payload)
    issues = validate_current_cv_references(current_cv, changed_bank)
    assert len(issues) == 1
    assert issues[0].path == f"{section}[0].{bullet_field}[0]"
    assert issues[0].reference == moved["id"]
    assert "does not belong" in issues[0].reason


@pytest.mark.parametrize("section,child_field,bullet_field", [
    ("work_experience", "achievements", "achievement_ids"),
    ("projects", "evidence", "contribution_ids"),
])
def test_deleting_selected_bullet_is_detected(bank, current_cv, section, child_field, bullet_field):
    payload = bank.model_dump()
    deleted = payload[section][1][child_field].pop(0)
    issues = validate_current_cv_references(current_cv, ExperienceBank.model_validate(payload))
    assert len(issues) == 1
    assert issues[0].path == f"{section}[0].{bullet_field}[0]"
    assert issues[0].reference == deleted["id"]
    assert "does not exist" in issues[0].reason


def test_skill_remains_available_until_its_last_explicit_source_is_removed():
    cv = CurrentCV.model_validate({"skill_groups": [{"name": "Languages", "skill_keys": ["python"]}]})
    payload = {
        "skills": ["Python"],
        "work_experience": [{"employer": "Example", "role": "Engineer", "technologies": ["PYTHON"]}],
        "certifications": [{"name": "Certificate", "skills": [" python "]}],
    }
    assert validate_current_cv_references(cv, ExperienceBank.model_validate(payload)) == []
    payload["skills"] = []
    assert validate_current_cv_references(cv, ExperienceBank.model_validate(payload)) == []
    payload["work_experience"][0]["technologies"] = []
    assert validate_current_cv_references(cv, ExperienceBank.model_validate(payload)) == []
    payload["certifications"][0]["skills"] = []
    issues = validate_current_cv_references(cv, ExperienceBank.model_validate(payload))
    assert len(issues) == 1
    assert issues[0].reference == "python"


def test_skill_rename_changes_key_and_does_not_repair_cv():
    cv = CurrentCV.model_validate({"skill_groups": [{"name": "Languages", "skill_keys": ["js"]}]})
    assert validate_current_cv_references(cv, ExperienceBank(skills=["JS"])) == []
    issues = validate_current_cv_references(cv, ExperienceBank(skills=["JavaScript"]))
    assert len(issues) == 1
    assert issues[0].reference == "js"
    assert cv.skill_groups[0].skill_keys == ["js"]


def test_noncanonical_skill_keys_are_rejected_by_phase_one_models():
    with pytest.raises(ValidationError):
        CurrentCV.model_validate({"skill_groups": [{"name": "Languages", "skill_keys": [" Python "]}]})


def test_all_issues_are_returned_in_cv_order_with_nonzero_indices(bank):
    cv = CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-a", "achievement_ids": ["achievement-a1", "missing-achievement"]},
            {"work_experience_id": "missing-role", "achievement_ids": ["achievement-b"]},
        ],
        "projects": [
            {"project_id": "project-a", "contribution_ids": ["contribution-a"]},
            {"project_id": "missing-project", "contribution_ids": ["missing-contribution"]},
        ],
        "skill_groups": [
            {"name": "Languages", "skill_keys": ["python"]},
            {"name": "Tools", "skill_keys": ["docker", "missing-skill"]},
        ],
    })
    expected = [
        ("work_experience[0].achievement_ids[1]", "missing-achievement"),
        ("work_experience[1].work_experience_id", "missing-role"),
        ("work_experience[1].achievement_ids[0]", "achievement-b"),
        ("projects[1].project_id", "missing-project"),
        ("projects[1].contribution_ids[0]", "missing-contribution"),
        ("skill_groups[1].skill_keys[1]", "missing-skill"),
    ]
    assert [(issue.path, issue.reference) for issue in validate_current_cv_references(cv, bank)] == expected
    assert [(issue.path, issue.reference) for issue in validate_current_cv_references(cv, bank)] == expected


@pytest.mark.parametrize("broken", [False, True])
def test_catalogue_and_reference_validation_do_not_modify_either_input(bank, current_cv, broken):
    if broken:
        current_cv = CurrentCV.model_validate({
            "work_experience": [{"work_experience_id": "deleted", "achievement_ids": ["achievement-a1"]}],
            "skill_groups": [{"name": "Tools", "skill_keys": ["unknown"]}],
        })
    before_bank = bank.model_dump_json()
    before_cv = current_cv.model_dump_json()
    catalogue = build_skill_catalogue(bank)
    issues = validate_current_cv_references(current_cv, bank)
    assert bool(issues) == broken
    # Returned values are independent; editing them cannot edit the inputs.
    catalogue["python"] = "Changed display label"
    if issues:
        issues[0].reference = "changed-reference"
    assert bank.model_dump_json() == before_bank
    assert current_cv.model_dump_json() == before_cv


def test_editing_bullet_wording_with_ids_retained_does_not_break_references(bank, current_cv):
    payload = bank.model_dump()
    payload["work_experience"][0]["achievements"][0]["text"] = "Updated wording."
    payload["projects"][0]["evidence"][0]["text"] = "Updated contribution."
    assert validate_current_cv_references(current_cv, ExperienceBank.model_validate(payload)) == []
