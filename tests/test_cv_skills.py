"""Pure preview contracts using explicit catalogues and controlled matcher support."""

from pathlib import Path

import pytest

from app.models import (
    Certification, CurrentCV, CurrentCVProjectSelection, CurrentCVSkillGroup,
    CurrentCVWorkSelection, CVSelectionDecision, Education, EvidenceItem,
    EvidenceReference, EvidenceSupport, ExperienceBank, ExperienceBankMatch,
    MatchResult, MatchingSignal, Project, RankedEvidence, RelationshipReference,
    StructuredRequirement, TailoringSettings, WorkExperience,
)
from app.services.cv_candidates import build_cv_candidates
from app.services.cv_selection import select_work_and_projects
from app.services.cv_skills import select_cv_content
from app.services.technical_relationships import TechnicalRelationshipCatalogue


def requirement(source_id="r1", options=("Python",), importance="required", **kwargs):
    text = " or ".join(options)
    return StructuredRequirement(id=source_id, text=text, source_text=text,
        category=kwargs.pop("category", "skill"), importance=importance,
        alternatives=list(options), **kwargs)


def support(evidence_id, requirement_id="r1", *, alternative="Python", status="strong",
            origin="wording", activity="technology_usage", signal=None, relationship=None):
    return EvidenceSupport(evidence_id=evidence_id, requirement_id=requirement_id,
        selected_alternative=alternative, status=status,
        signals=[MatchingSignal(signal=signal or alternative, origin=origin,
            demonstrated_activity=activity, relationship=relationship)],
        explanation="Original caveat: API development does not demonstrate maintenance.")


def matching(requirements=(), supports=(), *, skill_ids=()):
    rows = {"strong": [], "related": [], "missing": []}
    for item in requirements:
        local = [s for s in supports if s.requirement_id == item.id]
        status = "strong" if any(s.status == "strong" for s in local) else "related" if local else "missing"
        rows[status].append(MatchResult(requirement=item.text, requirement_details=item,
            status=status, evidence_support=local, explanation="Bank-wide diagnostic."))
    ranked = []
    for source_id in sorted({s.evidence_id for s in supports}):
        local = [s for s in supports if s.evidence_id == source_id]
        ranked.append(RankedEvidence(rank=len(ranked) + 1,
            evidence=EvidenceReference(evidence_id=source_id,
                source_type="skill" if source_id in skill_ids else "achievement",
                source_label="Original label", text="Original wording"),
            status="strong" if any(s.status == "strong" for s in local) else "related",
            score=sum(10 if s.status == "strong" else 3 for s in local),
            explanation="Original diagnostic.", evidence_support=local))
    return ExperienceBankMatch(job_title="Engineer", strong_matches=rows["strong"],
        related_matches=rows["related"], missing_requirements=rows["missing"], ranked_evidence=ranked)


def index(skills=(), *, groups=(), limit=None, achievements=(), projects=(),
          certifications=(), education=(), technologies=()):
    bank = ExperienceBank(skills=list(skills), work_experience=[WorkExperience(
        id="role", employer="Example", role="Engineer", technologies=list(technologies),
        achievements=list(achievements))], projects=list(projects),
        certifications=list(certifications), education=list(education))
    current = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role")],
        skill_groups=[CurrentCVSkillGroup(name=name, skill_keys=list(keys)) for name, keys in groups],
        tailoring_settings=TailoringSettings(max_skills=limit))
    return build_cv_candidates(bank, current)


def keys(result):
    return [key for group in result.proposed_cv.skill_groups for key in group.skill_keys]


def decision(result, source_id, source_type="skill"):
    return next(item for item in result.decisions if item.source_id == source_id and item.source_type == source_type)


def edge(source="azure", target="aws", kind="transferable"):
    return RelationshipReference(source=source, target=target, type=kind, confidence="high")


def test_required_explicit_declaration_is_eligible_with_honest_explanation():
    candidates = index([" Python\t", "Unrelated"])
    raw = support("skill:python", origin="standalone_skill", activity=None)
    result = select_cv_content(candidates, matching([requirement()], [raw], skill_ids=[raw.evidence_id]))
    selected = decision(result, "python")
    assert keys(result) == ["python"]
    assert selected.original_text == " Python\t"
    assert selected.reason_codes == ["required_explicit_skill"]
    assert selected.requirement_importance == {"r1": "required"}
    assert selected.supported_requirement_ids == ["r1"]
    assert selected.evidence_support == [raw]
    assert "standalone_skill" in selected.support_basis
    assert "Practical use of this skill is not established" in selected.recommendation
    assert selected.skill_relevance[0].demonstrated_evidence_ids == []
    assert not decision(result, "unrelated").selected


@pytest.mark.parametrize("importance", ["preferred", "unspecified"])
def test_nonrequired_explicit_skills_are_relevant_without_extra_evidence(importance):
    result = select_cv_content(index(["Python"]), matching([requirement(importance=importance)]))
    assert keys(result) == ["python"]
    assert decision(result, "python").reason_codes == ["relevant_explicit_skill"]
    assert decision(result, "python").requirement_importance == {"r1": importance}


def test_required_then_unspecified_then_preferred_at_equivalent_quality():
    requirements = [requirement("preferred", ["Rust"], "preferred"),
                    requirement("unspecified", ["Go"], "unspecified"), requirement("required", ["Python"])]
    result = select_cv_content(index(["Rust", "Go", "Python"], limit=2), matching(requirements))
    assert keys(result) == ["python", "go"]
    assert decision(result, "rust").reason_codes == ["limit_reached"]


def test_direct_required_skill_precedes_transferable_platform_without_upgrading_support():
    raw = support("azure-work", alternative="AWS", status="related", signal="Azure",
                  relationship=edge())
    result = select_cv_content(index(["Azure", "AWS"], limit=1), matching([requirement(options=["AWS"])], [raw]))
    assert keys(result) == ["aws"]
    assert decision(result, "azure").evidence_support == [raw]
    assert decision(result, "aws").skill_relevance[0].demonstrated_evidence_ids == []
    assert "technical_relationship" in decision(result, "aws").support_basis
    assert "Practical use" in decision(result, "aws").recommendation


def test_demonstrated_or_alternative_beats_declared_alternative():
    raw = support("python-work")
    result = select_cv_content(index(["Java", "Python"], limit=1),
        matching([requirement(options=["Python", "Java"])], [raw]))
    assert keys(result) == ["python"]
    assert decision(result, "python").skill_relevance[0].demonstrated_evidence_ids == ["python-work"]
    assert "demonstrated_wording" in decision(result, "python").support_basis
    assert "Practical use" not in decision(result, "python").recommendation
    assert decision(result, "java").reason_codes == ["limit_reached"]


def test_tag_only_support_never_becomes_demonstrated_experience():
    raw = support("tags", origin="technology_tag", activity=None, status="related")
    result = select_cv_content(index(["Python"]), matching([requirement()], [raw]))
    selected = decision(result, "python")
    assert selected.evidence_support == [raw]
    assert selected.skill_relevance[0].demonstrated_evidence_ids == []
    assert selected.support_basis == ["catalogue_declaration", "technology_tag"]
    assert "Practical use" in selected.recommendation


def test_language_relationship_does_not_prove_target_language_proficiency():
    raw = support("framework", status="related", signal="FastAPI",
                  relationship=edge("fastapi", "python", "uses_language"))
    result = select_cv_content(index(["Python", "FastAPI"]), matching([requirement()], [raw]))
    assert decision(result, "python").skill_relevance[0].demonstrated_evidence_ids == []
    assert decision(result, "fastapi").skill_relevance[0].demonstrated_evidence_ids == ["framework"]
    assert all(s.status == "related" for item in result.decisions for s in item.evidence_support)


def test_broader_demonstrated_activity_can_support_explicit_capability():
    raw = support("oracle", alternative="Relational databases", signal="Oracle Database",
                  relationship=edge("oracle database", "relational databases", "broader"))
    result = select_cv_content(index(["Oracle Database", "Relational databases"]),
        matching([requirement(options=["Relational databases"])], [raw]))
    assert keys(result) == ["relational databases", "oracle database"]
    assert decision(result, "relational databases").skill_relevance[0].demonstrated_evidence_ids == ["oracle"]


def api_requirement():
    return requirement("api", ["Develop and maintain backend APIs"], "unspecified",
                       category="responsibility", activity="api_development")


def api_support(evidence_id="api-work", origin="wording"):
    return support(evidence_id, "api", alternative="Develop and maintain backend APIs",
                   activity="api_development", signal="API development", origin=origin)


def test_supporting_framework_from_selected_meaningful_content_precedes_extra_or_option():
    achievement = EvidenceItem(id="api-work", text="Implemented Python endpoints using FastAPI.",
                               technologies=["FastAPI", "Docker"])
    candidates = index(["Java", "Python"], achievements=[achievement], limit=2)
    matches = matching([requirement(options=["Python", "Java"]), api_requirement()],
                       [support("api-work"), api_support()])
    result = select_cv_content(candidates, matches)
    assert keys(result) == ["python", "fastapi"]
    framework = decision(result, "fastapi")
    assert framework.reason_codes == ["supporting_technology"]
    assert "selected_content_association" in framework.support_basis
    assert framework.skill_relevance[0].demonstrated_evidence_ids == []
    assert all(item.status == "strong" for item in framework.evidence_support)  # Unmodified API support.
    assert "Practical use" in framework.recommendation  # Not borrowed framework proficiency.
    assert not decision(result, "docker").selected  # Tag does not occur in meaningful wording.
    assert not decision(result, "java").selected
    candidates.baseline.tailoring_settings.max_skills = None
    unlimited = select_cv_content(candidates, matches)
    assert set(keys(unlimited)) == {"python", "fastapi", "java"}
    assert len(unlimited.skill_coverage) == 2  # OR remains one obligation.


@pytest.mark.parametrize("wording,tag,selected", [
    ("Implemented endpoints using FastAPI.", "FastAPI", True),
    ("Implemented endpoints; did not use FastAPI.", "FastAPI", False),
    ("Implemented endpoints using FastAPI.", "Docker", False),
])
def test_supporting_association_requires_positive_local_wording_and_own_tag(wording, tag, selected):
    candidate = index(achievements=[EvidenceItem(id="api-work", text=wording, technologies=[tag])])
    result = select_cv_content(candidate, matching([api_requirement()], [api_support()]))
    assert decision(result, tag.lower()).selected is selected


def test_outcome_supporting_association_stays_outcome_provenance_and_keeps_bullet_original():
    original = "Original API wording.  "
    candidate = index(achievements=[EvidenceItem(id="api-work", text=original,
        outcomes=["Delivered endpoints with FastAPI."], technologies=["FastAPI"])])
    result = select_cv_content(candidate, matching([api_requirement()], [api_support(origin="outcome")]))
    assert keys(result) == ["fastapi"]
    assert "outcome" in decision(result, "fastapi").support_basis
    assert decision(result, "api-work", "achievement").original_text == original
    assert "Delivered endpoints" not in decision(result, "api-work", "achievement").original_text


def test_parent_tag_or_unselected_work_does_not_establish_supporting_association():
    candidate = index(technologies=["FastAPI"], achievements=[EvidenceItem(
        id="api-work", text="Implemented endpoints using FastAPI.")])
    result = select_cv_content(candidate, matching([api_requirement()], [api_support()]))
    assert not decision(result, "fastapi").selected
    candidate.work_experience[0].role.achievements[0].technologies = ["FastAPI"]
    candidate.baseline.tailoring_settings.max_achievements_per_role = 0
    result = select_cv_content(candidate, matching([api_requirement()], [api_support()]))
    assert not decision(result, "fastapi").selected


def test_no_skills_created_from_relationships_qualifications_names_or_wording():
    candidate = index(["Azure", "FastAPI"], projects=[Project(id="p", name="Python AWS SQL",
        description="Used Go.", evidence=[EvidenceItem(id="b", text="Used C++.")])])
    matches = matching([requirement(options=["AWS"]), requirement("python", ["Python"])], [
        support("azure", alternative="AWS", signal="Azure", status="related", relationship=edge()),
        support("fastapi", "python", signal="FastAPI", status="related", relationship=edge("fastapi", "python", "uses_language")),
    ])
    result = select_cv_content(candidate, matches)
    assert set(keys(result)) == {"azure", "fastapi"}
    assert {item.source_id for item in result.decisions if item.source_type == "skill"} == {"azure", "fastapi"}


def test_certification_is_separate_and_does_not_prove_practical_cloud_work():
    raw = support("cert", alternative="AWS", origin="credential", activity=None, status="related")
    candidate = index(certifications=[Certification(id="cert", name="AWS Certificate", skills=["AWS"])])
    result = select_cv_content(candidate, matching([requirement(options=["AWS"])], [raw]))
    assert keys(result) == ["aws"]
    assert decision(result, "aws").skill_relevance[0].demonstrated_evidence_ids == []
    assert "credential" in decision(result, "aws").support_basis
    assert "Practical use" in decision(result, "aws").recommendation
    credential = decision(result, "cert", "certification")
    assert credential.reason_codes == ["unchanged_credential"]
    assert credential.evidence_support == [raw]
    assert result.certification_ids == ["cert"]
    assert result.coverage[0].meaningful_evidence_ids == []


def test_baseline_groups_names_and_relative_order_survive_relevance_reordering():
    candidate = index(["Python", "SQL", "Testing", "Rust"],
        groups=[(" My tools ", ["testing", "sql"]), ("Languages", ["python"]), ("Empty", [])])
    result = select_cv_content(candidate, matching([requirement(), requirement("sql", ["SQL"])]))
    assert [(group.name, group.skill_keys) for group in result.proposed_cv.skill_groups] == [
        (" My tools ", ["testing", "sql"]), ("Languages", ["python"])]
    assert decision(result, "testing").reason_codes == ["baseline_retained"]
    assert not decision(result, "rust").selected


def test_new_equivalent_skill_uses_unambiguous_original_baseline_group():
    candidate = index(["JavaScript"], groups=[("Web tooling", ["js"])])
    result = select_cv_content(candidate, matching([requirement(options=["JavaScript"])]))
    assert [(g.name, g.skill_keys) for g in result.proposed_cv.skill_groups] == [("Web tooling", ["javascript"])]
    assert decision(result, "javascript").original_text == "JavaScript"
    assert not decision(result, "js").selected
    assert decision(result, "js").reason_codes == ["invalid_reference"]
    assert decision(result, "js").original_text is None
    assert "catalogue_declaration" not in decision(result, "js").support_basis
    assert result.reference_issues == candidate.reference_issues
    assert candidate.baseline.skill_groups[0].skill_keys == ["js"]


def test_ambiguous_equivalent_membership_uses_one_fallback_without_inventing_taxonomy():
    candidate = index(["API development", "Python"],
        groups=[("A", ["api design"]), ("B", ["rest api"])])
    result = select_cv_content(candidate, matching([requirement(options=["API development"]), requirement("py")]))
    assert [(g.name, g.skill_keys) for g in result.proposed_cv.skill_groups] == [
        ("Additional skills", ["api development", "python"])]


def test_existing_fallback_group_is_reused_without_renaming_it():
    candidate = index(["Python", "Testing"], groups=[("  Additional Skills\t", ["testing"])])
    result = select_cv_content(candidate, matching([requirement()]))
    assert [(g.name, g.skill_keys) for g in result.proposed_cv.skill_groups] == [
        ("  Additional Skills\t", ["testing", "python"])]


def test_equivalent_labels_select_one_original_key_and_never_duplicate_groups():
    candidate = index(["JavaScript", "JS", "javascript"], groups=[("Web", ["js"])])
    result = select_cv_content(candidate, matching([requirement(options=["JavaScript"])]))
    assert keys(result) == ["js"]  # Baseline wins equivalent declaration ties.
    assert decision(result, "js").original_text == "JS"
    assert decision(result, "javascript").reason_codes == ["equivalent_skill"]
    assert decision(result, "javascript").duplicate_of == "js"


def test_optional_preloaded_alias_catalogue_is_used_only_for_equivalent_names():
    catalogue = TechnicalRelationshipCatalogue.model_validate({"schema_version": 1,
        "concepts": {"azure": {"kind": "technology", "aliases": ["Microsoft Azure"]},
                     "aws": {"kind": "technology", "aliases": []}},
        "relationships": [{"from": "azure", "to": "aws", "type": "transferable", "confidence": "medium"}]})
    candidate = index(["Microsoft Azure"])
    result = select_cv_content(candidate, matching([requirement(options=["Azure"])]), catalogue=catalogue)
    assert keys(result) == ["microsoft azure"]
    assert not decision(result, "microsoft azure").skill_relevance[0].demonstrated_evidence_ids
    assert keys(select_cv_content(candidate, matching([requirement(options=["AWS"])]), catalogue=catalogue)) == []


def test_punctuation_preserved_for_c_cplusplus_csharp_dotnet_and_ci_variants():
    labels = ["C", "C++", "C#", ".NET", "CI/CD", "CI CD"]
    requirements = [requirement(f"r{position}", [label]) for position, label in enumerate(labels)]
    result = select_cv_content(index(labels), matching(requirements))
    assert keys(result) == [label.lower() for label in labels]
    assert [decision(result, label.lower()).original_text for label in labels] == labels


def test_ambiguous_synthetic_skill_id_is_not_attributed_to_distinct_catalogue_keys():
    raw = support("skill:ci cd", alternative="Delivery tools", origin="standalone_skill", activity=None)
    result = select_cv_content(index(["CI/CD", "CI CD"]),
        matching([requirement(options=["Delivery tools"])], [raw], skill_ids=[raw.evidence_id]))
    assert keys(result) == []
    assert "ambiguous_skill_identity" in result.warnings
    assert all(not item.evidence_support for item in result.decisions if item.source_type == "skill")


def test_unambiguous_synthetic_mapping_preserves_canonical_punctuation_key():
    raw = support("skill:ci cd", alternative="Delivery tools", origin="standalone_skill", activity=None)
    result = select_cv_content(index(["CI/CD"]),
        matching([requirement(options=["Delivery tools"])], [raw], skill_ids=[raw.evidence_id]))
    assert keys(result) == ["ci/cd"]
    assert decision(result, "ci/cd").source_id != raw.evidence_id
    assert decision(result, "ci/cd").skill_relevance[0].demonstrated_evidence_ids == []


def test_synthetic_mapping_requires_actual_skill_provenance():
    raw = support("skill:ci cd", alternative="Delivery tools", origin="standalone_skill", activity=None)
    matches = matching([requirement(options=["Delivery tools"])], [raw])
    assert keys(select_cv_content(index(["CI/CD"]), matches)) == []


@pytest.mark.parametrize("limit,expected", [(None, ["testing", "sql", "python"]),
    (0, []), (1, ["python"]), (2, ["testing", "python"]), (20, ["testing", "sql", "python"])])
def test_total_limit_is_a_ceiling_across_groups_with_baseline_retention(limit, expected):
    candidate = index(["Testing", "SQL", "Python", "Unrelated"], limit=limit,
        groups=[("Existing", ["testing", "sql"]), ("Languages", ["python"])])
    result = select_cv_content(candidate, matching([requirement()]))
    assert keys(result) == expected
    assert result.proposed_cv.tailoring_settings == candidate.tailoring_settings
    assert all(g.skill_keys for g in result.proposed_cv.skill_groups)
    assert "unrelated" not in keys(result)
    assert decision(result, "unrelated").reason_codes == ["no_relevant_support"]


def test_empty_matches_preserve_valid_baseline_without_filling_unrelated_bank_skills():
    candidate = index(["Testing", "Python", "Docker"], groups=[("Existing", ["testing"])])
    result = select_cv_content(candidate, matching())
    assert keys(result) == ["testing"]
    assert decision(result, "testing").reason_codes == ["baseline_retained"]
    assert decision(result, "docker").reason_codes == ["no_relevant_support"]
    assert result.skill_coverage == []


def test_empty_skill_catalogue_and_stale_skill_references_are_reported_without_fabrication():
    candidates = index(groups=[("Original", ["removed"])])
    result = select_cv_content(candidates, matching([requirement()]))
    assert result.proposed_cv.skill_groups == []
    assert decision(result, "removed").reason_codes == ["invalid_reference"]
    assert result.reference_issues == candidates.reference_issues
    assert result.skill_coverage[0].selected_skill_keys == []


def test_qualification_requirements_do_not_compete_for_skill_or_bullet_selection():
    raw = support("cert", alternative="AWS", origin="credential", activity=None)
    candidates = index(certifications=[Certification(id="cert", name="AWS Certificate", skills=["AWS"])])
    matches = matching([requirement(options=["AWS"], category="qualification")], [raw])
    result = select_cv_content(candidates, matches)
    assert keys(result) == []
    assert decision(result, "cert", "certification").evidence_support == [raw]
    assert decision(result, "cert", "certification").requirement_importance == {"r1": "required"}
    assert result.certification_ids == ["cert"]


def test_legacy_matching_metadata_is_used_conservatively_without_parsing_explanations():
    raw = support("skill:python", origin="standalone_skill", activity=None)
    matches = matching([requirement()], [raw], skill_ids=[raw.evidence_id])
    matches.strong_matches[0].requirement_details = None
    result = select_cv_content(index(["Python"]), matches)
    assert keys(result) == ["python"]
    assert decision(result, "python").requirement_importance == {"r1": "unspecified"}
    assert "matching_metadata_unavailable" in result.warnings
    aggregate_only = ExperienceBankMatch(job_title="Engineer", strong_matches=[MatchResult(
        requirement="Python", status="strong", explanation="Python is required.")])
    assert keys(select_cv_content(index(["Python"]), aggregate_only)) == []


def test_skill_labels_never_upgrade_selected_engineering_coverage_or_bank_status():
    raw = support("skill:python", origin="standalone_skill", activity=None)
    candidates = index(["Python"])
    matches = matching([requirement()], [raw], skill_ids=[raw.evidence_id])
    result = select_cv_content(candidates, matches)
    assert result.coverage_scope == "work_and_projects"
    assert result.coverage == select_work_and_projects(candidates, matches).coverage
    assert result.coverage[0].bank_status == "strong"
    assert result.coverage[0].selected_status == "not_selected"
    assert result.skill_coverage[0].selected_skill_keys == ["python"]
    candidates.baseline.tailoring_settings.max_skills = 0
    excluded = select_cv_content(candidates, matches)
    assert excluded.skill_coverage[0].selected_skill_keys == []
    assert excluded.coverage[0].bank_status == "strong"


def test_complete_recommendations_preserve_all_original_work_project_decisions_and_caveats():
    original = "  Implemented endpoints using FastAPI.\nKeep this wording.  "
    candidate = index(["Python"], achievements=[EvidenceItem(id="api-work", text=original,
        technologies=["FastAPI"])], projects=[Project(id="project", name="Original project",
        description="Original project description.", evidence=[EvidenceItem(id="contribution", text="Original contribution.")])],
        education=[Education(id="degree", institution="Example", qualification="BSc Computer Science")])
    candidate.baseline.projects = [CurrentCVProjectSelection(project_id="project", contribution_ids=["contribution"])]
    # Rebuild membership after changing the baseline, as a real caller must do.
    candidate.projects[0].current_cv_position = 0
    candidate.projects[0].contributions[0].current_cv_position = 0
    matches = matching([api_requirement()], [api_support()])
    before = select_work_and_projects(candidate, matches)
    result = select_cv_content(candidate, matches)
    assert result.proposed_cv.work_experience == before.proposed_cv.work_experience
    assert result.proposed_cv.projects == before.proposed_cv.projects
    assert result.proposed_cv.tailoring_settings == before.proposed_cv.tailoring_settings
    assert result.coverage == before.coverage
    old_fields = set(CVSelectionDecision.model_fields)
    assert [d.model_dump(include=old_fields) for d in result.decisions[:len(before.decisions)]] == [d.model_dump() for d in before.decisions]
    bullet = decision(result, "api-work", "achievement")
    assert bullet.original_text == original
    assert bullet.evidence_support == [api_support()]
    assert "does not demonstrate maintenance" in bullet.evidence_support[0].explanation
    assert bullet.supported_requirement_ids == ["api"]
    assert bullet.requirement_importance == {"api": "unspecified"}
    assert bullet.support_basis == ["demonstrated_wording"]
    assert all(d.recommendation and d.reason_codes for d in result.decisions)
    assert decision(result, "degree", "education").reason_codes == ["unchanged_credential"]
    assert result.education_ids == before.education_ids == ["degree"]


def test_project_bundle_requirement_metadata_never_borrows_child_support_as_own_evidence():
    candidate = index(["Python"], projects=[Project(id="p", name="Project",
        evidence=[EvidenceItem(id="child", text="Used Python to implement endpoints.", technologies=["Python"])])])
    result = select_cv_content(candidate, matching([requirement()], [support("child")]))
    parent = decision(result, "p", "project")
    assert parent.supported_requirement_ids == ["r1"]
    assert parent.evidence_support == []
    assert parent.bundle_evidence_ids == ["p", "child"]
    assert decision(result, "child", "project_evidence").evidence_support == [support("child")]


def test_selection_is_deterministic_when_candidates_and_support_rows_are_reordered():
    candidate = index(["Java", "Python", "SQL"], groups=[("Existing", ["sql"])])
    matches = matching([requirement(options=["Python", "Java"]), requirement("sql", ["SQL"], "preferred")],
                       [support("python-work"), support("java-work", alternative="Java")])
    expected = select_cv_content(candidate, matches)
    assert select_cv_content(candidate, matches) == expected
    candidate.skills.reverse()
    matches.strong_matches.reverse()
    matches.missing_requirements.reverse()
    matches.ranked_evidence.reverse()
    assert select_cv_content(candidate, matches) == expected


def test_no_input_mutation_result_aliases_or_external_calls(monkeypatch):
    candidate = index(["Python", "Testing"], groups=[("Existing", ["testing"])])
    matches = matching([requirement()], [support("skill:python", origin="standalone_skill", activity=None)],
                       skill_ids=["skill:python"])
    before_index, before_matches = candidate.model_dump(), matches.model_dump()
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure selection must not load, save, call a provider or rerun matching.")
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr("app.services.matching.match_experience_bank", forbidden)
    monkeypatch.setattr("app.services.technical_relationships.load_technical_relationships", forbidden)
    result = select_cv_content(candidate, matches)
    assert candidate.model_dump() == before_index
    assert matches.model_dump() == before_matches
    result.proposed_cv.skill_groups[0].skill_keys.clear()
    result.proposed_cv.tailoring_settings.max_skills = 0
    result.decisions[-1].original_text = "Changed output only"
    selected = decision(result, "python")
    selected.evidence_support[0].signals[0].signal = "Changed output only"
    selected.skill_relevance[0].evidence_ids.clear()
    result.coverage[0].requirement_details.alternatives.clear()
    assert candidate.model_dump() == before_index
    assert matches.model_dump() == before_matches


def test_seven_requirement_example_selects_explicit_skills_and_useful_baseline_only():
    # Reviewed extraction fixture and the existing matcher exercise the boundary;
    # this is synthetic bank data, not a saved-bank or live extraction test.
    from evaluations.extraction.harness import load_fixtures
    from app.services.job_extraction import analysis_from_extraction
    from app.services.matching import match_experience_bank

    case = load_fixtures().cases[0]
    analysis = analysis_from_extraction(case.expected_extraction(), case.job_description)
    bank = ExperienceBank.model_validate({
        "skills": ["Python", "Oracle Database", "SQL", "FastAPI", "Testing", "Unrelated"],
        "work_experience": [{"id": "role", "employer": "Example", "role": "Engineer", "achievements": [
            {"id": "oracle", "text": "Developed SQL stored procedures in Oracle to automate production data calculations, replacing manual processing with repeatable database logic",
             "technologies": ["Oracle Database", "SQL"]},
        ]}],
        "projects": [{"id": "jobmatch", "name": "JobMatch", "evidence": [
            {"id": "api", "text": "Designed and implemented REST API endpoints using Python and FastAPI for job description analysis, experience-bank management and evidence matching",
             "technologies": ["Python", "FastAPI"]},
        ]}],
        "education": [{"id": "degree", "institution": "Example", "qualification": "BSc Computer Science"}],
    })
    current = CurrentCV.model_validate({"work_experience": [{"work_experience_id": "role"}],
        "skill_groups": [{"name": "Languages", "skill_keys": ["python"]},
                         {"name": "Engineering", "skill_keys": ["testing"]}],
        "tailoring_settings": {"max_skills": 5}})
    candidates = build_cv_candidates(bank, current)
    matches = match_experience_bank(bank, analysis)
    result = select_cv_content(candidates, matches)
    assert [(g.name, g.skill_keys) for g in result.proposed_cv.skill_groups] == [
        ("Languages", ["python"]), ("Engineering", ["testing"]),
        ("Additional skills", ["oracle database", "fastapi", "sql"])]
    assert decision(result, "python").reason_codes == ["required_explicit_skill"]
    assert decision(result, "oracle database").reason_codes == ["demonstrated_skill"]
    assert decision(result, "fastapi").reason_codes == ["supporting_technology"]
    assert decision(result, "sql").reason_codes == ["supporting_technology"]
    assert decision(result, "testing").reason_codes == ["baseline_retained"]
    assert "aws" not in keys(result) and "java" not in keys(result)
    assert len(result.skill_coverage) == len(result.coverage) == 7
    before = select_work_and_projects(candidates, matches)
    assert result.proposed_cv.work_experience == before.proposed_cv.work_experience
    assert result.proposed_cv.projects == before.proposed_cv.projects
    assert result.coverage == before.coverage
