"""Controlled selection contracts, separate from live extraction and saved data."""

from pathlib import Path

import pytest

from app.models import (
    Certification, CurrentCV, CurrentCVProjectSelection, CurrentCVSkillGroup,
    CurrentCVWorkSelection, Education, EvidenceItem, EvidenceReference, EvidenceSupport,
    ExperienceBank, ExperienceBankMatch, JobDescriptionAnalysis, MatchResult, MatchingSignal,
    Project, RankedEvidence, RelationshipReference, StructuredRequirement, TailoringSettings,
    WorkExperience,
)
from app.services.cv_candidates import build_cv_candidates
from app.services.cv_selection import select_work_and_projects


def bullet(source_id, text=None, **kwargs):
    return EvidenceItem(id=source_id, text=text or f"Original content for {source_id}.", **kwargs)


def project(source_id, contributions=(), description=""):
    return Project(id=source_id, name=source_id, description=description, evidence=list(contributions))


def candidates(achievements=(), selected=(), *, achievement_limit=None, projects=(),
               baseline_projects=(), project_limit=None, contribution_limit=None):
    bank = ExperienceBank(work_experience=[WorkExperience(
        id="role", employer="Example", role="Engineer", achievements=list(achievements),
    )], projects=list(projects))
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role", achievement_ids=list(selected))],
        projects=[CurrentCVProjectSelection(project_id=source_id, contribution_ids=list(ids))
                  for source_id, ids in baseline_projects],
        tailoring_settings=TailoringSettings(max_achievements_per_role=achievement_limit,
            max_projects=project_limit, max_contributions_per_project=contribution_limit))
    return build_cv_candidates(bank, cv)


def support(evidence_id, requirement_id="r1", *, status="strong", origin="wording",
            activity="api_development", alternative="Python", relationship=None):
    return EvidenceSupport(requirement_id=requirement_id, evidence_id=evidence_id, status=status,
        selected_alternative=alternative, explanation="Diagnostic wording must not determine selection quality.",
        signals=[MatchingSignal(signal=alternative, origin=origin, demonstrated_activity=activity,
                                relationship=relationship)])


def matching(*supports, importance=None, requirements=(), missing=()):
    authored = {item.id: item for item in requirements}
    requirement_ids = sorted({item.requirement_id for item in supports} | set(missing) | set(authored))
    rows = {"strong": [], "related": [], "missing": []}
    for requirement_id in requirement_ids:
        local = [item for item in supports if item.requirement_id == requirement_id]
        status = "strong" if any(item.status == "strong" for item in local) else "related" if local else "missing"
        requirement = authored.get(requirement_id) or StructuredRequirement(
            id=requirement_id, text=requirement_id, source_text=requirement_id,
            category="skill", importance=(importance or {}).get(requirement_id, "unspecified"),
            alternatives=["Python"],
        )
        rows[status].append(MatchResult(requirement=requirement.text, status=status,
            explanation="Bank-wide status is not per-record support.", requirement_details=requirement,
            evidence_support=local))
    ranked = []
    for evidence_id in sorted({item.evidence_id for item in supports}):
        local = [item for item in supports if item.evidence_id == evidence_id]
        # Deliberately repeat OR entries here: selection must deduplicate support
        # IDs rather than trust an aggregate inflated by duplicated input records.
        ranked.append(RankedEvidence(rank=len(ranked) + 1,
            evidence=EvidenceReference(evidence_id=evidence_id, source_type="achievement",
                source_label="Example", text="Original source"),
            status="strong" if any(item.status == "strong" for item in local) else "related",
            score=sum(10 if item.status == "strong" else 3 for item in local),
            explanation="Aggregate alone is insufficient.", evidence_support=local))
    return ExperienceBankMatch(job_title="Engineer", strong_matches=rows["strong"],
        related_matches=rows["related"], missing_requirements=rows["missing"], ranked_evidence=ranked)


def work_ids(result, position=0):
    return result.proposed_cv.work_experience[position].achievement_ids


def decision(result, source_id, source_type=None):
    return next(item for item in result.decisions if item.source_id == source_id
                and (source_type is None or item.source_type == source_type))


def test_strong_alternative_replaces_weaker_baseline_when_capacity_is_limited():
    index = candidates([bullet("baseline"), bullet("alternative")], ["baseline"], achievement_limit=1)
    matches = matching(support("baseline", status="related", origin="technology_tag", activity=None),
                       support("alternative"))
    result = select_work_and_projects(index, matches)
    assert work_ids(result) == ["alternative"]
    assert not decision(result, "alternative").was_in_current_cv
    assert decision(result, "alternative").reason_codes == ["new_strong_coverage"]
    assert decision(result, "baseline").reason_codes == ["limit_reached"]
    assert decision(result, "baseline").was_in_current_cv


@pytest.mark.parametrize("limit", [None, 3, 20])
def test_useful_baseline_breadth_remains_after_job_specific_selection(limit):
    index = candidates([bullet("testing"), bullet("ownership"), bullet("api"), bullet("unrelated")],
                       ["ownership", "testing"], achievement_limit=limit)
    result = select_work_and_projects(index, matching(support("api")))
    assert work_ids(result) == ["ownership", "testing", "api"]
    assert decision(result, "ownership").reason_codes == ["baseline_retained"]
    assert decision(result, "testing").reason_codes == ["baseline_retained"]
    assert not decision(result, "unrelated").selected


def test_unbounded_limits_never_fill_with_unrelated_new_content():
    index = candidates([bullet("baseline"), bullet("new")], ["baseline"],
        projects=[project("old-project", [bullet("old-contribution"), bullet("new-contribution")]),
                  project("new-project", [bullet("unrelated-contribution")])],
        baseline_projects=[("old-project", ["old-contribution"])])
    result = select_work_and_projects(index, matching())
    assert work_ids(result) == ["baseline"]
    assert [(item.project_id, item.contribution_ids) for item in result.proposed_cv.projects] == [("old-project", ["old-contribution"])]
    assert decision(result, "new").reason_codes == ["no_relevant_support"]
    assert decision(result, "new-project").reason_codes == ["no_relevant_support"]


def test_distinct_requirement_coverage_beats_repeated_support_after_each_pick():
    index = candidates([bullet("first"), bullet("repetition"), bullet("distinct")], achievement_limit=2)
    result = select_work_and_projects(index, matching(support("first", "r1"), support("repetition", "r1"), support("distinct", "r2")))
    assert work_ids(result) == ["first", "distinct"]
    assert decision(result, "repetition").reason_codes == ["limit_reached"]
    assert decision(result, "distinct").marginal_requirement_ids == ["r2"]


@pytest.mark.parametrize("declaration_status", ["strong", "related"])
def test_demonstration_beats_declarations_even_when_bank_status_and_score_are_strong(declaration_status):
    index = candidates([bullet("tags"), bullet("demonstrated")], achievement_limit=1)
    tags = [support("tags", f"r{i}", status=declaration_status, origin="technology_tag", activity=None) for i in range(8)]
    result = select_work_and_projects(index, matching(*tags, support("demonstrated")))
    assert work_ids(result) == ["demonstrated"]
    assert decision(result, "tags").evidence_support[0].status == declaration_status


def test_tag_only_new_bullets_are_not_added_but_existing_bullets_can_be_retained():
    index = candidates([bullet("old"), bullet("new")], ["old"])
    result = select_work_and_projects(index, matching(support("old", status="related", origin="skill_tag", activity=None),
        support("new", "r2", status="related", origin="technology_tag", activity=None)))
    assert work_ids(result) == ["old"]
    assert decision(result, "new").reason_codes == ["declaration_only"]
    assert result.coverage[0].selected_status == "related"
    assert result.coverage[0].meaningful_evidence_ids == []


@pytest.mark.parametrize("first,second,winner", [
    ("preferred", "required", "second"), ("unspecified", "preferred", "first"),
    ("required", "unspecified", "first"),
])
def test_importance_is_used_within_equivalent_evidence_quality(first, second, winner):
    index = candidates([bullet("first"), bullet("second")], achievement_limit=1)
    result = select_work_and_projects(index, matching(support("first", "r1"), support("second", "r2"),
        importance={"r1": first, "r2": second}))
    assert work_ids(result) == [winner]


def test_activity_quality_precedes_importance_when_support_is_not_equivalent():
    index = candidates([bullet("wording"), bullet("activity")], achievement_limit=1)
    result = select_work_and_projects(index, matching(support("wording", "required", activity=None),
        support("activity", "preferred"), importance={"required": "required", "preferred": "preferred"}))
    assert work_ids(result) == ["activity"]


def test_related_to_strong_improvement_is_recalculated_and_reported():
    index = candidates([bullet("broad"), bullet("improvement")], achievement_limit=2)
    result = select_work_and_projects(index, matching(support("broad", "r1"),
        support("broad", "r2", status="related"), support("improvement", "r2"),
        importance={"r1": "required", "r2": "preferred"}))
    assert work_ids(result) == ["broad", "improvement"]
    assert decision(result, "improvement").reason_codes == ["stronger_coverage"]
    assert decision(result, "improvement").marginal_requirement_ids == ["r2"]
    coverage = next(item for item in result.coverage if item.requirement_id == "r2")
    assert coverage.selected_status == "strong"
    assert coverage.selected_evidence_ids == ["broad", "improvement"]


def test_or_alternatives_and_repeated_support_records_are_one_obligation_one_bullet():
    index = candidates([bullet("both"), bullet("single")], ["single"], achievement_limit=1)
    requirement = StructuredRequirement(id="or", text="Python or Java", source_text="Python or Java",
        category="skill", importance="required", alternatives=["Python", "Java"])
    result = select_work_and_projects(index, matching(
        support("both", "or", alternative="Java"), support("both", "or", alternative="Python"),
        support("both", "or", alternative="Python"), support("single", "or"), requirements=[requirement]))
    assert work_ids(result) == ["single"]  # Same real coverage/10 points: baseline wins.
    assert len(result.coverage) == 1
    assert len(decision(result, "both").evidence_support) == 1
    assert decision(result, "both").evidence_support[0].selected_alternative == "Python"
    assert len(decision(result, "single").evidence_support) == 1


def test_one_achievement_supporting_multiple_requirements_is_selected_once():
    index = candidates([bullet("multi")])
    result = select_work_and_projects(index, matching(support("multi", "r1"), support("multi", "r2")))
    assert work_ids(result) == ["multi"]
    assert decision(result, "multi").marginal_requirement_ids == ["r1", "r2"]


def test_exact_duplicates_use_safe_comparison_and_baseline_ties():
    index = candidates([bullet("alternative", "Built C++ services."), bullet("baseline", "  BUILT C++\tservices.  ")], ["baseline"])
    result = select_work_and_projects(index, matching(support("alternative"), support("baseline")))
    assert work_ids(result) == ["baseline"]
    assert decision(result, "alternative").reason_codes == ["exact_duplicate"]
    assert decision(result, "alternative").duplicate_of == "baseline"


def test_near_duplicate_rule_is_limited_to_articles_punctuation_and_same_support():
    index = candidates([bullet("first", "Developed REST API endpoints for reporting."),
        bullet("repeated", "Developed the REST API endpoints for reporting!")], ["first", "repeated"])
    result = select_work_and_projects(index, matching(support("first"), support("repeated")))
    assert work_ids(result) == ["first"]
    assert decision(result, "repeated").reason_codes == ["repetitive_evidence"]


@pytest.mark.parametrize("first,second", [
    (bullet("first", "Built C services."), bullet("second", "Built C++ services.")),
    (bullet("first", "Built C++ services."), bullet("second", "Built C# services.")),
    (bullet("first", "Reduced processing time by 20%."), bullet("second", "Reduced processing time by 50%.")),
    (bullet("first", "Changed processing time by -20%."), bullet("second", "Changed processing time by 20%.")),
    (bullet("first", "Saved the team $100 daily."), bullet("second", "Saved the team £100 daily.")),
    (bullet("first", "Built a service.", technologies=["Azure"]), bullet("second", "Built a service.", technologies=["AWS"])),
    (bullet("first", "Built a service.", outcomes=["Saved 20 hours"]), bullet("second", "Built a service.", outcomes=["Saved 50 hours"])),
    (bullet("first", "Developed reporting API endpoints."), bullet("second", "Developed API endpoints for billing.")),
])
def test_different_technologies_impacts_outcomes_and_potentially_distinct_work_are_preserved(first, second):
    index = candidates([first, second], ["first", "second"])
    result = select_work_and_projects(index, matching(support("first"), support("second")))
    assert work_ids(result) == ["first", "second"]
    assert decision(result, "second").reason_codes == ["baseline_retained"]


def test_near_wording_with_distinct_activities_is_not_suppressed():
    index = candidates([bullet("first", "Developed REST API endpoints for reporting."),
        bullet("second", "Developed the REST API endpoints for reporting.")], ["first", "second"])
    result = select_work_and_projects(index, matching(support("first"), support("second", activity="technology_usage")))
    assert work_ids(result) == ["first", "second"]


def test_roles_stay_in_baseline_order_with_separate_caps_and_no_parent_or_outside_bullets():
    bank = ExperienceBank(work_experience=[
        WorkExperience(id="a", employer="Example", role="A", summary="Parent summary", achievements=[bullet("a1"), bullet("a2")]),
        WorkExperience(id="outside", employer="Example", role="Outside", achievements=[bullet("outside-child")]),
        WorkExperience(id="b", employer="Example", role="B", achievements=[bullet("b1"), bullet("b2")]),
    ])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="b", achievement_ids=["b1"]),
        CurrentCVWorkSelection(work_experience_id="a", achievement_ids=["a1"])],
        tailoring_settings=TailoringSettings(max_achievements_per_role=1))
    result = select_work_and_projects(build_cv_candidates(bank, cv), matching(
        support("a2"), support("b2"), support("outside-child", "outside"), support("a", "parent")))
    assert [(item.work_experience_id, item.achievement_ids) for item in result.proposed_cv.work_experience] == [("b", ["b2"]), ("a", ["a2"])]
    assert next(item for item in result.coverage if item.requirement_id == "outside").bank_status == "strong"
    assert next(item for item in result.coverage if item.requirement_id == "outside").selected_status == "not_selected"
    # The summary remains visible context under its own role ID, not a bullet.
    assert next(item for item in result.coverage if item.requirement_id == "parent").selected_evidence_ids == ["a"]
    assert decision(result, "a", "work_experience").selected
    assert all("a" not in item.achievement_ids for item in result.proposed_cv.work_experience)


def test_retained_role_context_never_supplies_achievement_provenance_or_fills_zero_bullet_limit():
    index = candidates([bullet("child")], ["child"], achievement_limit=0)
    result = select_work_and_projects(index, matching(support("role")))
    assert work_ids(result) == []
    assert result.coverage[0].selected_evidence_ids == ["role"]
    assert decision(result, "child").evidence_support == []
    assert decision(result, "role", "work_experience").evidence_support[0].evidence_id == "role"


def test_stronger_new_project_replaces_weaker_baseline_project_under_cap():
    index = candidates(projects=[project("old", [bullet("old-child")]), project("new", [bullet("new-child")])],
        baseline_projects=[("old", ["old-child"])], project_limit=1)
    result = select_work_and_projects(index, matching(support("new-child")))
    assert [(item.project_id, item.contribution_ids) for item in result.proposed_cv.projects] == [("new", ["new-child"])]
    assert decision(result, "old", "project").reason_codes == ["limit_reached"]
    assert decision(result, "old-child").reason_codes == ["project_not_selected"]


def test_repetitive_tagged_contributions_cannot_inflate_project_priority():
    tagged = project("tagged", [bullet(f"tag-{i}") for i in range(20)])
    relevant = project("relevant", [bullet("real")])
    index = candidates(projects=[tagged, relevant], project_limit=1)
    result = select_work_and_projects(index, matching(
        *(support(f"tag-{i}", origin="technology_tag", status="related", activity=None) for i in range(20)), support("real")))
    assert [item.project_id for item in result.proposed_cv.projects] == ["relevant"]


def test_project_bundle_counts_each_requirement_once_not_each_contribution():
    many = project("many", [bullet(f"repeat-{i}") for i in range(10)])
    diverse = project("diverse", [bullet("one"), bullet("two")])
    index = candidates(projects=[many, diverse], project_limit=1, contribution_limit=2)
    result = select_work_and_projects(index, matching(
        *(support(f"repeat-{i}", "r1") for i in range(10)), support("one", "r1"), support("two", "r2")))
    assert [(item.project_id, item.contribution_ids) for item in result.proposed_cv.projects] == [("diverse", ["one", "two"])]
    assert decision(result, "diverse", "project").marginal_requirement_ids == ["r1", "r2"]
    assert decision(result, "diverse", "project").evidence_support == []
    assert decision(result, "diverse", "project").bundle_evidence_ids == ["diverse", "one", "two"]


def test_equivalent_project_quality_uses_baseline_membership_and_position_for_ties():
    index = candidates(projects=[project("new"), project("earlier-bank"), project("earlier-cv")],
        baseline_projects=[("earlier-cv", []), ("earlier-bank", [])], project_limit=1)
    result = select_work_and_projects(index, matching(support("new"), support("earlier-bank"), support("earlier-cv")))
    assert [item.project_id for item in result.proposed_cv.projects] == ["earlier-cv"]


def test_project_marginal_coverage_is_recomputed_after_each_bundle_selection():
    index = candidates(projects=[project("first"), project("repetition"), project("distinct")], project_limit=2)
    result = select_work_and_projects(index, matching(support("first", "r1"), support("repetition", "r1"),
        support("distinct", "r2"), importance={"r1": "required", "r2": "preferred"}))
    assert [item.project_id for item in result.proposed_cv.projects] == ["first", "distinct"]
    assert decision(result, "distinct", "project").marginal_requirement_ids == ["r2"]


def test_new_strong_project_coverage_precedes_related_to_strong_upgrade():
    index = candidates([bullet("work")], ["work"], projects=[project("upgrade"), project("new")], project_limit=1)
    result = select_work_and_projects(index, matching(support("work", "r1", status="related"),
        support("upgrade", "r1"), support("new", "r2")))
    assert [item.project_id for item in result.proposed_cv.projects] == ["new"]


def test_contribution_caps_are_independent_per_project():
    index = candidates(projects=[project("a", [bullet("a1"), bullet("a2")]),
        project("b", [bullet("b1"), bullet("b2")])], contribution_limit=1)
    result = select_work_and_projects(index, matching(support("a1", "r1"), support("a2", "r2"),
        support("b1", "r3"), support("b2", "r4")))
    assert [(item.project_id, item.contribution_ids) for item in result.proposed_cv.projects] == [("a", ["a1"]), ("b", ["b1"])]


@pytest.mark.parametrize("limit,expected", [(None, ["first", "second", "third"]), (0, []), (1, ["first"]), (2, ["first", "second"])])
def test_contribution_limits_apply_within_selected_projects(limit, expected):
    index = candidates(projects=[project("project", [bullet("first"), bullet("second"), bullet("third")], "Original description.")],
        contribution_limit=limit)
    result = select_work_and_projects(index, matching(support("project", "description"),
        support("first", "r1"), support("second", "r2"), support("third", "r3")))
    assert result.proposed_cv.projects[0].contribution_ids == expected


def test_description_support_is_never_attributed_to_an_unrelated_contribution():
    index = candidates(projects=[project("project", [bullet("child")], "Developed original APIs.")],
        baseline_projects=[("project", ["child"])])
    result = select_work_and_projects(index, matching(support("project")))
    assert result.proposed_cv.projects[0].contribution_ids == ["child"]
    assert decision(result, "project", "project").evidence_support[0].evidence_id == "project"
    assert decision(result, "child").evidence_support == []
    assert decision(result, "child").reason_codes == ["baseline_retained"]
    assert result.coverage[0].selected_evidence_ids == ["project"]


def test_zero_contribution_allowance_cannot_promote_a_child_claim_into_the_description():
    index = candidates(projects=[project("project", [bullet("child")], "An unrelated original description.")], contribution_limit=0)
    result = select_work_and_projects(index, matching(support("child")))
    assert not result.proposed_cv.projects
    assert result.coverage[0].bank_status == "strong"
    assert result.coverage[0].selected_status == "not_selected"


def test_overlapping_new_projects_lose_priority_but_useful_baseline_project_is_retained():
    index = candidates([bullet("work")], ["work"], projects=[
        project("baseline", [bullet("old-child")]), project("overlap", [bullet("overlap-child")]),
        project("novel", [bullet("novel-child")])],
        baseline_projects=[("baseline", ["old-child"])], project_limit=2)
    result = select_work_and_projects(index, matching(support("work", "r1"), support("old-child", "r1"),
        support("overlap-child", "r1"), support("novel-child", "r2")))
    assert [item.project_id for item in result.proposed_cv.projects] == ["novel", "baseline"]
    assert result.proposed_cv.projects[1].contribution_ids == ["old-child"]
    assert decision(result, "baseline", "project").reason_codes == ["baseline_retained"]
    assert not decision(result, "overlap", "project").selected


def test_related_work_coverage_can_be_improved_by_a_strong_project():
    index = candidates([bullet("work")], ["work"], projects=[project("project", [bullet("child")])], project_limit=1)
    result = select_work_and_projects(index, matching(support("work", status="related"), support("child")))
    assert decision(result, "project", "project").reason_codes == ["stronger_coverage"]
    assert result.coverage[0].selected_status == "strong"


@pytest.mark.parametrize("limit,expected", [(None, ["second", "first"]), (0, []), (1, ["first"]), (2, ["second", "first"])])
def test_achievement_limits_keep_roles_and_use_baseline_reading_order(limit, expected):
    index = candidates([bullet("first"), bullet("second")], ["second", "first"], achievement_limit=limit)
    result = select_work_and_projects(index, matching(support("first")))
    assert len(result.proposed_cv.work_experience) == 1
    assert work_ids(result) == expected


@pytest.mark.parametrize("limit,count", [(None, 2), (0, 0), (1, 1), (2, 2)])
def test_project_limit_counts_projects_and_retains_baseline_when_no_job_support(limit, count):
    index = candidates(projects=[project("a"), project("b"), project("unrelated")],
        baseline_projects=[("b", []), ("a", [])], project_limit=limit)
    result = select_work_and_projects(index, matching())
    assert [item.project_id for item in result.proposed_cv.projects] == ["b", "a"][:count]


def test_missing_and_wrong_parent_baseline_references_are_not_relocated():
    bank = ExperienceBank(work_experience=[
        WorkExperience(id="a", employer="Example", role="A", achievements=[bullet("actual-a")]),
        WorkExperience(id="b", employer="Example", role="B", achievements=[bullet("valid-b")]),
    ], projects=[project("project", [bullet("actual-child")])])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="missing-role", achievement_ids=["missing"]),
        CurrentCVWorkSelection(work_experience_id="b", achievement_ids=["actual-a", "valid-b"]),
        CurrentCVWorkSelection(work_experience_id="a")],
        projects=[CurrentCVProjectSelection(project_id="missing-project", contribution_ids=["actual-child"])])
    index = build_cv_candidates(bank, cv)
    result = select_work_and_projects(index, matching(support("actual-a"), support("actual-child")))
    assert [(item.work_experience_id, item.achievement_ids) for item in result.proposed_cv.work_experience] == [("b", ["valid-b"]), ("a", [])]
    assert not result.proposed_cv.projects
    assert "baseline_reference_issues" in result.warnings
    assert result.reference_issues == index.reference_issues
    assert decision(result, "missing-role").reason_codes == ["invalid_reference"]
    assert all(not item.selected for item in result.decisions if item.source_id == "actual-a")


def test_empty_baseline_does_not_add_roles_but_can_recommend_a_relevant_project():
    bank = ExperienceBank(work_experience=[WorkExperience(id="role", employer="Example", role="Engineer", achievements=[bullet("work")])],
        projects=[project("project", [bullet("child")])])
    result = select_work_and_projects(build_cv_candidates(bank), matching(support("work"), support("child", "r2")))
    assert not result.proposed_cv.work_experience
    assert [item.project_id for item in result.proposed_cv.projects] == ["project"]
    assert not result.proposed_cv.skill_groups


def test_empty_bank_and_matching_return_empty_proposal_without_inventions():
    result = select_work_and_projects(build_cv_candidates(ExperienceBank()), matching(missing=["r1"]))
    assert result.proposed_cv == CurrentCV()
    assert not result.decisions
    assert result.coverage[0].bank_status == "missing"
    assert result.coverage[0].selected_status == "not_selected"


def test_education_certifications_and_skill_groups_are_not_competitive_or_tailored():
    bank = ExperienceBank(skills=["Python", "Azure"], work_experience=[WorkExperience(
        id="role", employer="Example", role="Engineer", achievements=[bullet("work")])],
        education=[Education(id="degree", qualification="BSc Computer Science", institution="Example")],
        certifications=[Certification(id="cert", name="Cloud certificate")])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role", achievement_ids=["work"])],
        skill_groups=[CurrentCVSkillGroup(name="Original group", skill_keys=["azure", "python"])],
        tailoring_settings=TailoringSettings(max_skills=0))
    qualification = StructuredRequirement(id="degree-required", text="Degree", source_text="Degree", category="qualification", alternatives=["Degree"])
    result = select_work_and_projects(build_cv_candidates(bank, cv), matching(
        support("degree", "degree-required", origin="credential"), support("work", "degree-required"), requirements=[qualification]))
    assert result.proposed_cv.skill_groups == cv.skill_groups
    assert result.proposed_cv.tailoring_settings.max_skills == 0
    assert result.education_ids == ["degree"]
    assert result.certification_ids == ["cert"]
    assert work_ids(result) == ["work"]
    assert decision(result, "work").reason_codes == ["baseline_retained"]
    assert result.coverage_scope == "work_and_projects"
    assert result.coverage[0].selected_status == "not_selected"


def test_transferable_and_outcome_support_remain_related_and_keep_their_provenance():
    relationship = RelationshipReference(source="azure", target="aws", type="transferable", confidence="medium")
    index = candidates([bullet("transfer", "  Original achievement.\r\nKeep this text.  ", outcomes=["Used Azure."])])
    evidence = support("transfer", status="related", origin="outcome", activity="technology_usage", relationship=relationship)
    result = select_work_and_projects(index, matching(evidence))
    assert work_ids(result) == ["transfer"]
    selected_support = decision(result, "transfer").evidence_support[0]
    assert selected_support == evidence
    assert result.coverage[0].selected_status == "related"
    assert index.work_experience[0].achievements[0].evidence.text == "  Original achievement.\r\nKeep this text.  "


def test_legacy_analysis_is_supported_through_existing_matching_preparation():
    from app.services.matching import match_experience_bank

    bank = ExperienceBank(work_experience=[WorkExperience(id="role", employer="Example", role="Engineer",
        achievements=[bullet("python", "Built an API using Python.")])])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role")])
    index = build_cv_candidates(bank, cv)
    matches = match_experience_bank(bank, JobDescriptionAnalysis(job_title="Engineer", technical_skills=["Python or Java"]))
    result = select_work_and_projects(index, matches)
    assert work_ids(result) == ["python"]
    assert len(result.coverage) == 1
    assert result.coverage[0].requirement_id == "legacy:technical_skills:1"
    assert result.coverage[0].requirement_details.importance == "unspecified"
    assert decision(result, "python").evidence_support[0].selected_alternative == "Python"


def test_seven_requirement_fixture_combines_relevance_baseline_breadth_and_project_context():
    from app.services.job_extraction import analysis_from_extraction
    from app.services.matching import match_experience_bank
    from evaluations.extraction.harness import load_fixtures

    fixture = load_fixtures().cases[0]
    job = analysis_from_extraction(fixture.expected_extraction(), fixture.job_description)
    bank = ExperienceBank(work_experience=[WorkExperience(id="role", employer="Example", role="Engineer", achievements=[
        bullet("testing", "Wrote regression tests for reporting tools."),
        bullet("general", "Delivered planned internal tasks."),
        bullet("oracle", "Developed SQL stored procedures in Oracle to automate production data calculations, replacing manual processing with repeatable database logic"),
        bullet("api", "Developed a production API endpoint using Python and FastAPI to expose Azure AI Search index status."),
    ])], projects=[project("jobmatch", [bullet("endpoints",
        "Designed and implemented REST API endpoints for job description analysis, experience-bank management and evidence matching")])],
        education=[Education(id="degree", institution="Example", qualification="BSc Hons Computer Science", field="Computer Science")])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role", achievement_ids=["testing", "general"])],
        projects=[CurrentCVProjectSelection(project_id="jobmatch", contribution_ids=["endpoints"])],
        tailoring_settings=TailoringSettings(max_achievements_per_role=3, max_projects=1, max_contributions_per_project=1))
    matches = match_experience_bank(bank, job)
    result = select_work_and_projects(build_cv_candidates(bank, cv), matches)
    assert work_ids(result) == ["testing", "oracle", "api"]
    assert decision(result, "testing").reason_codes == ["baseline_retained"]
    assert not decision(result, "general").selected
    assert result.proposed_cv.projects[0].contribution_ids == ["endpoints"]
    assert decision(result, "jobmatch", "project").reason_codes == ["baseline_retained"]
    assert result.education_ids == ["degree"]
    coverage = {item.requirement_id: item for item in result.coverage}
    assert coverage["r2"].selected_status == "strong"
    assert coverage["r3"].selected_status == "strong"
    assert coverage["r5"].bank_status == coverage["r6"].bank_status == "missing"
    assert coverage["r7"].bank_status == "strong"
    assert coverage["r7"].selected_status == "not_selected"  # Separate credential section.


def test_matching_without_per_record_support_preserves_baseline_instead_of_guessing():
    index = candidates([bullet("old"), bullet("new")], ["old"])
    matches = ExperienceBankMatch(job_title="Engineer", strong_matches=[MatchResult(
        requirement="Python", status="strong", explanation="Claims a strong practical match",
        evidence=[EvidenceReference(evidence_id="new", source_type="achievement", source_label="Example", text="New")])])
    result = select_work_and_projects(index, matches)
    assert work_ids(result) == ["old"]
    assert result.warnings == ["matching_metadata_unavailable"]


def test_unmatched_support_ids_still_work_conservatively_without_importance_metadata():
    matches = matching(support("new"))
    matches.strong_matches[0].requirement_details = None
    result = select_work_and_projects(candidates([bullet("new")]), matches)
    assert work_ids(result) == ["new"]
    assert result.coverage[0].requirement_details is None
    assert result.coverage[0].bank_status == "strong"
    assert result.warnings == ["matching_metadata_unavailable"]


def test_deterministic_ties_and_equivalent_container_order_do_not_change_output():
    index = candidates([bullet("first"), bullet("second")], ["second"], achievement_limit=1,
        projects=[project("a", [bullet("a-child")]), project("b", [bullet("b-child")])], project_limit=1)
    matches = matching(support("first"), support("second"), support("a-child", "r2"), support("b-child", "r2"))
    expected = select_work_and_projects(index, matches).model_dump_json()
    assert work_ids(select_work_and_projects(index, matches)) == ["second"]
    index.work_experience.reverse()
    for role in index.work_experience:
        role.achievements.reverse()
    index.projects.reverse()
    for item in index.projects:
        item.contributions.reverse()
    matches.strong_matches.reverse()
    matches.ranked_evidence.reverse()
    for row in matches.strong_matches:
        row.evidence_support.reverse()
    assert select_work_and_projects(index, matches).model_dump_json() == expected
    assert select_work_and_projects(index, matches).model_dump_json() == expected


def test_proposal_has_no_aliases_back_to_index_matching_bank_or_saved_baseline():
    bank = ExperienceBank(work_experience=[WorkExperience(id="role", employer="Example", role="Engineer",
        achievements=[bullet("work", "  Original wording.\r\nUnchanged.  ")])],
        projects=[project("project", [bullet("child", " Original contribution. ")], " Original description. ")])
    cv = CurrentCV(work_experience=[CurrentCVWorkSelection(work_experience_id="role", achievement_ids=["work"])],
        skill_groups=[CurrentCVSkillGroup(name="Unchanged", skill_keys=[])])
    index = build_cv_candidates(bank, cv)
    matches = matching(support("work"), support("child", "r2"))
    before = bank.model_dump_json(), cv.model_dump_json(), index.model_dump_json(), matches.model_dump_json()
    result = select_work_and_projects(index, matches)
    assert (bank.model_dump_json(), cv.model_dump_json(), index.model_dump_json(), matches.model_dump_json()) == before
    result.proposed_cv.work_experience[0].achievement_ids.clear()
    result.proposed_cv.skill_groups[0].name = "Changed result"
    result.proposed_cv.tailoring_settings.max_projects = 0
    decision(result, "work").evidence_support[0].signals[0].signal = "Changed result"
    result.coverage[0].requirement_details.text = "Changed result"
    assert (bank.model_dump_json(), cv.model_dump_json(), index.model_dump_json(), matches.model_dump_json()) == before


def test_selector_performs_no_io_matching_or_provider_calls(monkeypatch):
    from app.repositories.json_current_cv import JsonCurrentCVRepository
    from app.repositories.json_experience_bank import JsonExperienceBankRepository
    from app.services import llm, matching as matching_service, technical_relationships
    import openai

    index, matches = candidates([bullet("work")]), matching(support("work"))
    def forbidden(*args, **kwargs):
        raise AssertionError("Selection attempted matching, I/O or a provider request")
    with monkeypatch.context() as guard:
        for repository in (JsonCurrentCVRepository, JsonExperienceBankRepository):
            guard.setattr(repository, "load", forbidden)
            guard.setattr(repository, "save", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(Path, "write_text", forbidden)
        guard.setattr(llm, "analyse_job_description_with_llm", forbidden)
        guard.setattr(llm, "OpenAI", forbidden)
        guard.setattr(openai, "OpenAI", forbidden)
        guard.setattr(matching_service, "match_experience_bank", forbidden)
        guard.setattr(technical_relationships, "load_technical_relationships", forbidden)
        result = select_work_and_projects(index, matches)
    assert work_ids(result) == ["work"]
