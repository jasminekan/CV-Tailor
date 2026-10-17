"""Index explicit CV content and baseline membership without selecting or ranking."""

from typing import Literal

from app.models import (
    CVCandidateIndex,
    CVBulletCandidate,
    CVProjectCandidate,
    CVSkillCandidate,
    CVWorkRoleCandidate,
    CurrentCV,
    EvidenceItem,
    ExperienceBank,
)
from app.services.current_cv import build_skill_catalogue, validate_current_cv_references


def _bullet_candidates(
    items: list[EvidenceItem],
    parent_id: str,
    source_type: Literal["achievement", "project_evidence"],
    selected_ids: list[str],
) -> list[CVBulletCandidate]:
    selected_positions = {item_id: position for position, item_id in enumerate(selected_ids)}
    # Only this parent's real children are candidates. Foreign/stale IDs remain
    # reference issues; their position cannot select a different parent's child.
    return [CVBulletCandidate(
        source_type=source_type,
        parent_id=parent_id,
        evidence=item,
        bank_position=position,
        current_cv_position=selected_positions.get(item.id),
    ) for position, item in enumerate(items)]


def build_cv_candidates(
    bank: ExperienceBank, current_cv: CurrentCV | None = None,
) -> CVCandidateIndex:
    """Build independent, deterministic snapshots from validated documents.

    Work roles follow valid baseline references in their original CV order.
    Projects, children, credentials and review-only records follow bank order;
    skills follow the existing explicit catalogue's order and normalise_skill_key
    identity rules. All positions are zero-based and keep gaps from stale refs.

    None represents an empty Current CV. The full baseline is preserved with
    reference issues, not repaired. Limits are exposed but never enforced.
    No matching, relationship loading, grouping, persistence or API calls occur.
    """
    snapshot = bank.model_copy(deep=True)
    baseline = current_cv.model_copy(deep=True) if current_cv is not None else CurrentCV()
    issues = validate_current_cv_references(baseline, snapshot)
    roles_by_id = {role.id: (position, role)
                   for position, role in enumerate(snapshot.work_experience)}
    work_candidates = []
    retained_role_ids = set()
    for cv_position, selection in enumerate(baseline.work_experience):
        entry = roles_by_id.get(selection.work_experience_id)
        if entry is None:
            continue
        bank_position, role = entry
        retained_role_ids.add(role.id)
        work_candidates.append(CVWorkRoleCandidate(
            role=role,
            bank_position=bank_position,
            current_cv_position=cv_position,
            achievements=_bullet_candidates(
                role.achievements, role.id, "achievement", selection.achievement_ids,
            ),
        ))

    selected_projects = {selection.project_id: (position, selection)
                         for position, selection in enumerate(baseline.projects)}
    project_candidates = []
    for bank_position, project in enumerate(snapshot.projects):
        entry = selected_projects.get(project.id)
        cv_position, selected_ids = (entry[0], entry[1].contribution_ids) if entry is not None else (None, [])
        project_candidates.append(CVProjectCandidate(
            project=project,
            bank_position=bank_position,
            current_cv_position=cv_position,
            contributions=_bullet_candidates(
                project.evidence, project.id, "project_evidence", selected_ids,
            ),
        ))

    skill_membership = {
        key: (group_index, group.name, position)
        for group_index, group in enumerate(baseline.skill_groups)
        for position, key in enumerate(group.skill_keys)
    }
    skill_candidates = []
    for bank_position, (key, label) in enumerate(build_skill_catalogue(snapshot).items()):
        group_index, group_name, cv_position = skill_membership.get(key, (None, None, None))
        skill_candidates.append(CVSkillCandidate(
            skill_key=key,
            label=label,
            bank_position=bank_position,
            current_cv_group_index=group_index,
            current_cv_group_name=group_name,
            current_cv_position=cv_position,
        ))

    return CVCandidateIndex(
        baseline=baseline,
        work_experience=work_candidates,
        projects=project_candidates,
        skills=skill_candidates,
        out_of_baseline_work_experience=[role for role in snapshot.work_experience
                                         if role.id not in retained_role_ids],
        education=snapshot.education,
        certifications=snapshot.certifications,
        additional_evidence=snapshot.additional_evidence,
        reference_issues=issues,
    )
