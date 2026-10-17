"""Candidate discovery only: no ranking, persistence or live provider requests."""

from pathlib import Path

import pytest

from app.models import CVCandidateIndex, CurrentCV, EvidenceItem, ExperienceBank, TailoringSettings
from app.services.current_cv import build_skill_catalogue, validate_current_cv_references
from app.services.cv_candidates import build_cv_candidates


@pytest.fixture
def bank():
    return ExperienceBank.model_validate({
        "skills": [" Python\t", "C", "C++", "C#", "JS", "JavaScript"],
        "work_experience": [
            {
                "id": "role-a", "employer": "Example", "role": "Engineer",
                "start_date": "2023", "end_date": "2025",
                "summary": "Original role summary.\r\nKeep its wording.",
                "skills": ["Parent only"], "technologies": ["Oracle Database"],
                "achievements": [
                    {"id": "a1", "text": "  Built an API.\r\nKept the original wording.  ",
                     "skills": ["API development"], "technologies": ["FastAPI"],
                     "outcomes": ["  Original outcome.  "]},
                    {"id": "a2", "text": "Developed stored procedures.", "technologies": ["SQL"]},
                    {"id": "a3", "text": "Wrote regression tests."},
                ],
            },
            {
                "id": "role-b", "employer": "Another example", "role": "Developer",
                "technologies": ["Azure AI Search"],
                "achievements": [
                    {"id": "b1", "text": "Resolved a mapping issue."},
                    {"id": "b2", "text": "Delivered a service.", "technologies": ["Go"]},
                ],
            },
            {
                "id": "role-outside", "employer": "Other example", "role": "Developer",
                "skills": ["Other role skill"], "technologies": ["Rust"],
                "achievements": [{"id": "outside", "text": "Built a separate tool."}],
            },
            {"id": "role-empty", "employer": "Example", "role": "Engineer"},
        ],
        "projects": [
            {
                "id": "project-a", "name": "API project",
                "description": "  Original project description.\nKeep spaces.  ",
                "link": "https://example.com/project-a", "technologies": ["Parent project tag"],
                "evidence": [
                    {"id": "pa1", "text": "  Implemented endpoints.\r\nPreserve this.  ",
                     "skills": ["Backend"], "technologies": ["Python"],
                     "outcomes": ["Original project outcome."]},
                    {"id": "pa2", "text": "Added validation."},
                ],
            },
            {
                "id": "project-b", "name": "Automation project",
                "description": "Automates an existing workflow.",
                "evidence": [
                    {"id": "pb1", "text": "Built an automation tool."},
                    {"id": "pb2", "text": "Added tests."},
                ],
            },
            {"id": "project-empty", "name": "Empty project"},
        ],
        "education": [
            {"id": "degree-a", "institution": "Example", "qualification": "BSc Computer Science"},
            {"id": "degree-b", "institution": "Other example", "qualification": "Another qualification"},
        ],
        "certifications": [
            {"id": "cert-a", "name": "Cloud certificate", "skills": ["Cloud foundations"]},
            {"id": "cert-b", "name": "Other certificate"},
        ],
        "additional_evidence": [
            {"id": "extra", "text": "Supported a team.", "skills": ["Mentoring"],
             "technologies": ["Docker"], "outcomes": ["Original additional outcome."]},
        ],
    })


@pytest.fixture
def current_cv():
    return CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "role-b", "achievement_ids": ["b2", "b1"]},
            {"work_experience_id": "role-a", "achievement_ids": ["a2", "a1"]},
            {"work_experience_id": "role-empty"},
        ],
        "projects": [
            {"project_id": "project-b", "contribution_ids": ["pb2", "pb1"]},
            {"project_id": "project-a", "contribution_ids": ["pa2"]},
        ],
        "skill_groups": [
            {"name": " Languages\t", "skill_keys": ["c++", "python"]},
            {"name": "Tools", "skill_keys": ["fastapi"]},
            {"name": "Empty group"},
        ],
        "tailoring_settings": {
            "max_achievements_per_role": 1, "max_projects": 0,
            "max_contributions_per_project": None, "max_skills": 0,
        },
    })


def test_valid_work_roles_keep_baseline_order_and_both_original_positions(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    assert [item.role.id for item in index.work_experience] == ["role-b", "role-a", "role-empty"]
    assert [item.current_cv_position for item in index.work_experience] == [0, 1, 2]
    assert [item.bank_position for item in index.work_experience] == [1, 0, 3]
    assert index.work_experience[1].role.summary == bank.work_experience[0].summary
    assert index.work_experience[1].role.start_date == "2023"
    assert not index.reference_issues


def test_achievements_keep_bank_order_and_baseline_membership_without_selecting_alternatives(bank, current_cv):
    role = build_cv_candidates(bank, current_cv).work_experience[1]
    assert [item.evidence.id for item in role.achievements] == ["a1", "a2", "a3"]
    assert [item.bank_position for item in role.achievements] == [0, 1, 2]
    assert [item.current_cv_position for item in role.achievements] == [1, 0, None]
    assert [item.is_currently_selected for item in role.achievements] == [True, True, False]
    assert {item.parent_id for item in role.achievements} == {"role-a"}
    assert {item.source_type for item in role.achievements} == {"achievement"}


def test_parent_context_and_tags_are_not_achievement_candidates_or_child_claims(bank, current_cv):
    role = build_cv_candidates(bank, current_cv).work_experience[1]
    assert role.source_type == "work_experience"
    assert role.role.summary not in [item.evidence.text for item in role.achievements]
    assert role.achievements[0].evidence.skills == ["API development"]
    assert role.achievements[0].evidence.technologies == ["FastAPI"]
    assert "Parent only" not in role.achievements[0].evidence.skills


def test_other_roles_are_review_only_and_never_enter_eligible_achievements(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    assert [role.id for role in index.out_of_baseline_work_experience] == ["role-outside"]
    assert index.out_of_baseline_work_experience[0].achievements[0].id == "outside"
    assert "outside" not in {item.evidence.id for role in index.work_experience for item in role.achievements}
    # Skill availability still follows the whole explicit bank, not role eligibility.
    assert "rust" in {skill.skill_key for skill in index.skills}


def test_all_projects_keep_bank_order_and_independent_baseline_positions(bank, current_cv):
    projects = build_cv_candidates(bank, current_cv).projects
    assert [item.project.id for item in projects] == ["project-a", "project-b", "project-empty"]
    assert [item.bank_position for item in projects] == [0, 1, 2]
    assert [item.current_cv_position for item in projects] == [1, 0, None]
    assert [item.is_currently_selected for item in projects] == [True, True, False]
    assert all(item.source_type == "project" for item in projects)
    assert projects[0].project.description == bank.projects[0].description
    assert projects[0].project.link == bank.projects[0].link


def test_project_contributions_keep_parent_and_existing_vs_alternative_membership(bank, current_cv):
    projects = build_cv_candidates(bank, current_cv).projects
    assert [item.evidence.id for item in projects[0].contributions] == ["pa1", "pa2"]
    assert [item.current_cv_position for item in projects[0].contributions] == [None, 0]
    assert [item.is_currently_selected for item in projects[0].contributions] == [False, True]
    assert [item.current_cv_position for item in projects[1].contributions] == [1, 0]
    for project in projects:
        assert [item.bank_position for item in project.contributions] == list(range(len(project.contributions)))
        assert all(item.parent_id == project.project.id and item.source_type == "project_evidence"
                   for item in project.contributions)
        assert project.project.description not in [item.evidence.text for item in project.contributions]
    assert projects[0].contributions[0].evidence.technologies == ["Python"]
    assert "Parent project tag" not in projects[0].contributions[0].evidence.technologies


def test_explicit_skills_reuse_catalogue_keys_labels_and_traversal_order(bank, current_cv):
    skills = build_cv_candidates(bank, current_cv).skills
    assert [(item.skill_key, item.label) for item in skills] == list(build_skill_catalogue(bank).items())
    assert skills[0].skill_key == "python"
    assert skills[0].label == " Python\t"
    assert [item.bank_position for item in skills] == list(range(len(skills)))
    assert all(item.source_type == "skill" for item in skills)
    assert len({item.skill_key for item in skills}) == len(skills)
    keys = {item.skill_key for item in skills}
    assert {"c", "c++", "c#", "js", "javascript"} <= keys


def test_skill_membership_preserves_original_groups_and_local_positions(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    skills = {item.skill_key: item for item in index.skills}
    assert skills["python"].is_currently_selected
    assert skills["python"].current_cv_group_name == " Languages\t"
    assert skills["python"].current_cv_group_index == 0
    assert skills["python"].current_cv_position == 1
    assert skills["c++"].current_cv_position == 0
    assert skills["fastapi"].current_cv_group_name == "Tools"
    assert skills["fastapi"].current_cv_group_index == 1
    assert not skills["sql"].is_currently_selected
    assert skills["sql"].current_cv_group_name is None
    assert skills["sql"].current_cv_group_index is None
    assert skills["sql"].current_cv_position is None
    assert index.baseline.skill_groups == current_cv.skill_groups
    assert index.baseline.skill_groups[-1].name == "Empty group"
    assert not index.baseline.skill_groups[-1].skill_keys
    assert all(group.name != "Additional Skills" for group in index.baseline.skill_groups)


def test_no_inferred_skills_from_relationships_titles_wording_or_outcomes():
    bank = ExperienceBank.model_validate({
        "projects": [{
            "id": "project", "name": "Python SQL AWS project",
            "description": "Used Java and Oracle Database.", "technologies": ["Azure", "FastAPI"],
            "evidence": [{"id": "bullet", "text": "Used Go.", "outcomes": ["Improved Ruby tooling."]}],
        }],
    })
    skills = build_cv_candidates(bank).skills
    assert [(item.skill_key, item.label) for item in skills] == [("azure", "Azure"), ("fastapi", "FastAPI")]


def test_explicit_alias_repeats_deduplicate_only_by_existing_skill_key_rules():
    bank = ExperienceBank.model_validate({"skills": [" Python\t", "python", "C", "c", "C++", "C#", "JS", "JavaScript"]})
    index = build_cv_candidates(bank)
    assert [(item.skill_key, item.label) for item in index.skills] == [
        ("python", " Python\t"), ("c", "C"), ("c++", "C++"), ("c#", "C#"),
        ("js", "JS"), ("javascript", "JavaScript"),
    ]


@pytest.mark.parametrize("baseline", [None, CurrentCV()])
def test_empty_or_missing_cv_does_not_add_work_roles_or_select_projects_and_skills(bank, baseline):
    index = build_cv_candidates(bank, baseline)
    assert index.baseline == CurrentCV()
    assert not index.work_experience
    assert index.out_of_baseline_work_experience == bank.work_experience
    assert len(index.projects) == len(bank.projects)
    assert index.skills
    assert all(not project.is_currently_selected for project in index.projects)
    assert all(not item.is_currently_selected for project in index.projects for item in project.contributions)
    assert all(not skill.is_currently_selected for skill in index.skills)
    assert not index.reference_issues


def test_empty_bank_and_missing_baseline_have_empty_sections_and_default_settings():
    index = build_cv_candidates(ExperienceBank())
    assert not any([index.work_experience, index.projects, index.skills, index.education,
                    index.certifications, index.additional_evidence,
                    index.out_of_baseline_work_experience, index.reference_issues])
    assert set(index.tailoring_settings.model_dump().values()) == {None}


def test_empty_bank_keeps_stale_baseline_instead_of_substituting_or_clearing_it(current_cv):
    bank = ExperienceBank()
    index = build_cv_candidates(bank, current_cv)
    assert index.baseline == current_cv
    assert index.reference_issues == validate_current_cv_references(current_cv, bank)
    assert index.reference_issues
    assert not index.work_experience and not index.projects and not index.skills


def test_stale_refs_are_reported_without_relocation_and_valid_positions_keep_gaps(bank):
    baseline = CurrentCV.model_validate({
        "work_experience": [
            {"work_experience_id": "missing-role", "achievement_ids": ["a1"]},
            {"work_experience_id": "role-a", "achievement_ids": ["missing-achievement", "b1", "a2"]},
            {"work_experience_id": "role-b", "achievement_ids": ["a3"]},
        ],
        "projects": [
            {"project_id": "missing-project", "contribution_ids": ["pa1"]},
            {"project_id": "project-a", "contribution_ids": ["pb1", "missing-contribution", "pa2"]},
            {"project_id": "project-b", "contribution_ids": ["pb2"]},
        ],
        "skill_groups": [{"name": "Original group", "skill_keys": ["missing-skill", "python"]}],
    })
    index = build_cv_candidates(bank, baseline)
    assert index.baseline == baseline
    assert index.reference_issues == validate_current_cv_references(baseline, bank)
    assert [(issue.path, issue.reference) for issue in index.reference_issues] == [
        ("work_experience[0].work_experience_id", "missing-role"),
        ("work_experience[0].achievement_ids[0]", "a1"),
        ("work_experience[1].achievement_ids[0]", "missing-achievement"),
        ("work_experience[1].achievement_ids[1]", "b1"),
        ("work_experience[2].achievement_ids[0]", "a3"),
        ("projects[0].project_id", "missing-project"),
        ("projects[0].contribution_ids[0]", "pa1"),
        ("projects[1].contribution_ids[0]", "pb1"),
        ("projects[1].contribution_ids[1]", "missing-contribution"),
        ("skill_groups[0].skill_keys[0]", "missing-skill"),
    ]
    assert [role.current_cv_position for role in index.work_experience] == [1, 2]
    assert [item.current_cv_position for item in index.work_experience[0].achievements] == [None, 2, None]
    assert all(not item.is_currently_selected for item in index.work_experience[1].achievements)
    assert [item.current_cv_position for item in index.projects[0].contributions] == [None, 2]
    assert [item.current_cv_position for item in index.projects[1].contributions] == [None, 0]
    python = next(skill for skill in index.skills if skill.skill_key == "python")
    assert python.current_cv_position == 1
    assert "missing-skill" not in {skill.skill_key for skill in index.skills}


def test_baseline_parent_ids_of_the_wrong_record_type_cannot_adopt_children(bank):
    baseline = CurrentCV.model_validate({
        "work_experience": [{"work_experience_id": "project-a", "achievement_ids": ["a1"]}],
        "projects": [{"project_id": "role-a", "contribution_ids": ["pa1"]}],
    })
    index = build_cv_candidates(bank, baseline)
    assert not index.work_experience
    assert all(not item.is_currently_selected for item in index.projects)
    assert all(not child.is_currently_selected for item in index.projects for child in item.contributions)
    assert len(index.reference_issues) == 4


def test_empty_parent_selections_stay_empty_but_own_children_remain_alternatives(bank):
    baseline = CurrentCV.model_validate({
        "work_experience": [{"work_experience_id": "role-a"}, {"work_experience_id": "role-empty"}],
        "projects": [{"project_id": "project-empty"}],
    })
    index = build_cv_candidates(bank, baseline)
    assert len(index.work_experience[0].achievements) == 3
    assert not any(item.is_currently_selected for item in index.work_experience[0].achievements)
    assert not index.work_experience[1].achievements
    assert index.projects[2].is_currently_selected
    assert not index.projects[2].contributions
    assert not index.reference_issues


def test_credentials_and_additional_evidence_are_separate_original_records(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    assert index.education == bank.education
    assert [item.id for item in index.education] == ["degree-a", "degree-b"]
    assert index.certifications == bank.certifications
    assert [item.id for item in index.certifications] == ["cert-a", "cert-b"]
    assert index.additional_evidence == bank.additional_evidence
    bullet_ids = {item.evidence.id for role in index.work_experience for item in role.achievements}
    bullet_ids |= {item.evidence.id for project in index.projects for item in project.contributions}
    assert not bullet_ids & {"degree-a", "degree-b", "cert-a", "cert-b", "extra"}


def test_text_tags_and_outcomes_are_preserved_exactly(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    assert index.work_experience[1].achievements[0].evidence.model_dump() == bank.work_experience[0].achievements[0].model_dump()
    assert index.work_experience[1].achievements[0].evidence.text == "  Built an API.\r\nKept the original wording.  "
    assert index.projects[0].contributions[0].evidence.model_dump() == bank.projects[0].evidence[0].model_dump()
    assert index.projects[0].contributions[0].evidence.text == "  Implemented endpoints.\r\nPreserve this.  "


def test_identical_bullet_text_with_distinct_ids_is_not_semantically_deduplicated(bank, current_cv):
    bank.work_experience[0].achievements.append(EvidenceItem(id="same-text", text=bank.work_experience[0].achievements[0].text))
    achievements = build_cv_candidates(bank, current_cv).work_experience[1].achievements
    assert [item.evidence.id for item in achievements] == ["a1", "a2", "a3", "same-text"]
    assert achievements[0].evidence.text == achievements[-1].evidence.text


@pytest.mark.parametrize("limit", [None, 0, 1, 99])
def test_all_four_settings_are_preserved_without_enforcing_any_limits(bank, current_cv, limit):
    payload = current_cv.model_dump()
    payload["tailoring_settings"] = dict.fromkeys(TailoringSettings.model_fields, limit)
    baseline = CurrentCV.model_validate(payload)
    index = build_cv_candidates(bank, baseline)
    assert index.tailoring_settings.model_dump() == payload["tailoring_settings"]
    assert len(index.work_experience[1].achievements) == 3
    assert len(index.projects) == 3
    assert len(index.projects[0].contributions) == 2
    assert len(index.skills) == len(build_skill_catalogue(bank))
    assert index.baseline == baseline


def test_ids_ordering_and_serialization_are_deterministic_without_generated_candidate_ids(bank, current_cv):
    first = build_cv_candidates(bank, current_cv)
    second = build_cv_candidates(bank, current_cv)
    assert first.model_dump_json() == second.model_dump_json()
    restored = CVCandidateIndex.model_validate_json(first.model_dump_json())
    assert restored == first
    assert restored.work_experience[0].achievements[0].is_currently_selected
    assert not restored.work_experience[1].achievements[-1].is_currently_selected
    work_ids = [item.evidence.id for role in first.work_experience for item in role.achievements]
    project_ids = [item.evidence.id for project in first.projects for item in project.contributions]
    assert len(set(work_ids + project_ids)) == len(work_ids + project_ids)
    assert set(work_ids + project_ids) == {"a1", "a2", "a3", "b1", "b2", "pa1", "pa2", "pb1", "pb2"}


def test_indexing_and_mutating_the_result_cannot_change_either_input(bank, current_cv):
    before = bank.model_dump_json(), current_cv.model_dump_json()
    index = build_cv_candidates(bank, current_cv)
    assert (bank.model_dump_json(), current_cv.model_dump_json()) == before
    index.work_experience[0].role.summary = "Edited snapshot"
    index.work_experience[1].achievements[0].evidence.text = "Edited snapshot"
    index.work_experience[1].achievements[0].evidence.technologies.append("Another tag")
    index.projects[0].project.description = "Edited snapshot"
    index.projects[0].contributions[0].evidence.outcomes.append("Another outcome")
    index.out_of_baseline_work_experience[0].achievements[0].text = "Edited snapshot"
    index.education[0].qualification = "Edited snapshot"
    index.certifications[0].skills.append("Another tag")
    index.additional_evidence[0].text = "Edited snapshot"
    index.baseline.work_experience[0].achievement_ids.clear()
    index.baseline.skill_groups[0].name = "Edited snapshot"
    index.tailoring_settings.max_skills = 99
    assert (bank.model_dump_json(), current_cv.model_dump_json()) == before


def test_later_input_edits_cannot_change_the_built_snapshot(bank, current_cv):
    index = build_cv_candidates(bank, current_cv)
    before = index.model_dump_json()
    bank.work_experience[0].achievements[0].text = "Changed bank"
    bank.projects[0].evidence[0].text = "Changed bank"
    bank.skills.clear()
    current_cv.work_experience.reverse()
    current_cv.skill_groups[0].name = "Changed baseline"
    current_cv.tailoring_settings.max_projects = 99
    assert index.model_dump_json() == before


def test_returned_reference_issues_do_not_alias_a_future_build(bank, current_cv):
    current_cv.work_experience[0].achievement_ids.append("missing")
    first = build_cv_candidates(bank, current_cv)
    first.reference_issues[0].reference = "Changed result"
    assert build_cv_candidates(bank, current_cv).reference_issues[0].reference == "missing"


def test_builder_never_uses_repositories_matching_relationships_or_network(bank, current_cv, monkeypatch):
    from app.repositories.json_current_cv import JsonCurrentCVRepository
    from app.repositories.json_experience_bank import JsonExperienceBankRepository
    from app.services import llm, matching, technical_relationships
    import openai

    def forbidden(*args, **kwargs):
        raise AssertionError("Candidate building attempted I/O, matching or relationship inference")

    with monkeypatch.context() as guard:
        for repository in (JsonCurrentCVRepository, JsonExperienceBankRepository):
            guard.setattr(repository, "load", forbidden)
            guard.setattr(repository, "save", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(Path, "write_text", forbidden)
        guard.setattr(llm, "analyse_job_description_with_llm", forbidden)
        guard.setattr(llm, "OpenAI", forbidden)
        guard.setattr(openai, "OpenAI", forbidden)
        guard.setattr(matching, "match_experience_bank", forbidden)
        guard.setattr(technical_relationships, "load_technical_relationships", forbidden)
        index = build_cv_candidates(bank, current_cv)
    assert index.work_experience
    assert index.projects
    assert index.skills
