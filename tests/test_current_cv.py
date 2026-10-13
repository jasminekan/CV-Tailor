import pytest
from pydantic import ValidationError

from app.models import (
    CurrentCV,
    CurrentCVProjectSelection,
    CurrentCVSkillGroup,
    CurrentCVWorkSelection,
    TailoringSettings,
)


def test_empty_cv_has_independent_defaults():
    first = CurrentCV()
    second = CurrentCV()
    assert first.model_dump() == {
        "schema_version": 1,
        "work_experience": [],
        "projects": [],
        "skill_groups": [],
        "tailoring_settings": {
            "max_achievements_per_role": None,
            "max_contributions_per_project": None,
            "max_projects": None,
            "max_skills": None,
        },
    }
    first.work_experience.append(CurrentCVWorkSelection(work_experience_id="role"))
    first.projects.append(CurrentCVProjectSelection(project_id="project"))
    first.skill_groups.append(CurrentCVSkillGroup(name="Languages"))
    first.tailoring_settings.max_projects = 1
    assert second == CurrentCV()
    group = CurrentCVSkillGroup(name="Empty")
    other = CurrentCVSkillGroup(name="Other")
    group.skill_keys.append("python")
    assert other.skill_keys == []


def test_valid_document_preserves_names_ids_keys_and_nested_order():
    payload = {
        "schema_version": 1,
        "work_experience": [
            {"work_experience_id": " Role-Z ", "achievement_ids": ["a-z", "a-a"]},
            {"work_experience_id": "role-a", "achievement_ids": []},
        ],
        "projects": [
            {"project_id": "project-z", "contribution_ids": ["c-z", "c-a"]},
            {"project_id": "project-a", "contribution_ids": []},
        ],
        "skill_groups": [
            {"name": "  Backend\tTools  ", "skill_keys": ["fastapi", "api development"]},
            {"name": "Languages", "skill_keys": ["c++", "c#", "c"]},
            {"name": "Empty", "skill_keys": []},
        ],
        "tailoring_settings": {
            "max_achievements_per_role": 0,
            "max_contributions_per_project": 1,
            "max_projects": 0,
            "max_skills": None,
        },
    }
    # Limits are preferences; records need not exist in a bank in Phase 1.
    assert CurrentCV.model_validate(payload).model_dump() == payload


def test_parent_selections_and_groups_can_omit_empty_lists():
    cv = CurrentCV.model_validate({
        "work_experience": [{"work_experience_id": "role"}],
        "projects": [{"project_id": "project"}],
        "skill_groups": [{"name": "Languages"}],
    })
    assert cv.work_experience[0].achievement_ids == []
    assert cv.projects[0].contribution_ids == []
    assert cv.skill_groups[0].skill_keys == []


@pytest.mark.parametrize("blank", ["", " ", "\t\n", "\u00a0"])
@pytest.mark.parametrize("model,payload,field,is_list", [
    (CurrentCVWorkSelection, {"work_experience_id": "role"}, "work_experience_id", False),
    (CurrentCVWorkSelection, {"work_experience_id": "role"}, "achievement_ids", True),
    (CurrentCVProjectSelection, {"project_id": "project"}, "project_id", False),
    (CurrentCVProjectSelection, {"project_id": "project"}, "contribution_ids", True),
    (CurrentCVSkillGroup, {"name": "Languages"}, "name", False),
    (CurrentCVSkillGroup, {"name": "Languages"}, "skill_keys", True),
])
def test_blank_ids_names_and_keys_are_rejected(model, payload, field, is_list, blank):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: [blank] if is_list else blank})


@pytest.mark.parametrize("payload", [
    {"work_experience": [{}]},
    {"projects": [{}]},
    {"skill_groups": [{}]},
    {"work_experience": [{"work_experience_id": 123}]},
    {"projects": [{"project_id": None}]},
    {"work_experience": [{"work_experience_id": "role", "achievement_ids": [123]}]},
    {"projects": [{"project_id": "project", "contribution_ids": [None]}]},
    {"skill_groups": [{"name": "Languages", "skill_keys": [123]}]},
    {"work_experience": None},
    {"tailoring_settings": None},
])
def test_missing_required_fields_and_invalid_types_are_rejected(payload):
    with pytest.raises(ValidationError):
        CurrentCV.model_validate(payload)


@pytest.mark.parametrize("payload", [
    {"work_experience": [{"work_experience_id": "same"}, {"work_experience_id": "same"}]},
    {"projects": [{"project_id": "same"}, {"project_id": "same"}]},
    {"work_experience": [{"work_experience_id": "role", "achievement_ids": ["same", "same"]}]},
    {"projects": [{"project_id": "project", "contribution_ids": ["same", "same"]}]},
    {"work_experience": [
        {"work_experience_id": "one", "achievement_ids": ["same"]},
        {"work_experience_id": "two", "achievement_ids": ["same"]},
    ]},
    {"projects": [
        {"project_id": "one", "contribution_ids": ["same"]},
        {"project_id": "two", "contribution_ids": ["same"]},
    ]},
    {
        "work_experience": [{"work_experience_id": "role", "achievement_ids": ["same"]}],
        "projects": [{"project_id": "project", "contribution_ids": ["same"]}],
    },
    {"skill_groups": [{"name": "Languages", "skill_keys": ["python", "python"]}]},
    {"skill_groups": [
        {"name": "Languages", "skill_keys": ["python"]},
        {"name": "Backend", "skill_keys": ["python"]},
    ]},
])
def test_duplicate_selections_are_rejected(payload):
    with pytest.raises(ValidationError, match="Duplicate"):
        CurrentCV.model_validate(payload)


@pytest.mark.parametrize("other_name", ["backend tools", " BACKEND TOOLS ", "Backend\tTools", "Backend\u00a0 Tools"])
def test_group_names_are_unique_after_case_and_whitespace_normalisation(other_name):
    with pytest.raises(ValidationError, match="Duplicate skill group name"):
        CurrentCV(skill_groups=[
            CurrentCVSkillGroup(name="Backend Tools"),
            CurrentCVSkillGroup(name=other_name),
        ])


@pytest.mark.parametrize("key", ["Python", " python", "python ", "unit  testing", "unit\ttesting"])
def test_skill_keys_must_already_be_normalised(key):
    with pytest.raises(ValidationError, match="normalised whitespace"):
        CurrentCVSkillGroup(name="Skills", skill_keys=[key])


@pytest.mark.parametrize("field", list(TailoringSettings.model_fields))
@pytest.mark.parametrize("invalid", [-1, True, False, "3", 3.0, 1.5, [], {}])
def test_tailoring_limits_require_strict_nonnegative_integers_or_null(field, invalid):
    with pytest.raises(ValidationError):
        TailoringSettings.model_validate({field: invalid})


@pytest.mark.parametrize("value", [None, 0, 1, 100])
def test_valid_tailoring_limits_are_preserved(value):
    payload = dict.fromkeys(TailoringSettings.model_fields, value)
    assert TailoringSettings.model_validate(payload).model_dump() == payload


@pytest.mark.parametrize("version", [0, -1, 2, 999, "1", True, 1.0, None])
def test_only_strict_integer_schema_version_one_is_supported(version):
    with pytest.raises(ValidationError):
        CurrentCV(schema_version=version)


@pytest.mark.parametrize("payload", [
    {"future_field": "data"},
    {"work_experience": [{"work_experience_id": "role", "text": "Copied text"}]},
    {"projects": [{"project_id": "project", "future_field": "data"}]},
    {"skill_groups": [{"name": "Languages", "future_field": "data"}]},
    {"tailoring_settings": {"future_field": 1}},
])
def test_unknown_fields_are_rejected_at_every_level(payload):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CurrentCV.model_validate(payload)
