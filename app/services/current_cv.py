"""Explicit skill selection and non-destructive Current CV reference checks."""

from app.models import (
    CurrentCV,
    CurrentCVReferenceIssue,
    ExperienceBank,
    normalise_skill_key,
)


def build_skill_catalogue(bank: ExperienceBank) -> dict[str, str]:
    """Map canonical keys to the first original label, in bank traversal order."""
    catalogue: dict[str, str] = {}

    def collect(labels: list[str]) -> None:
        for label in labels:
            catalogue.setdefault(normalise_skill_key(label), label)

    collect(bank.skills)
    for work in bank.work_experience:
        collect(work.skills)
        collect(work.technologies)
        for achievement in work.achievements:
            collect(achievement.skills)
            collect(achievement.technologies)
    for project in bank.projects:
        collect(project.skills)
        collect(project.technologies)
        for contribution in project.evidence:
            collect(contribution.skills)
            collect(contribution.technologies)
    for certification in bank.certifications:
        collect(certification.skills)
    for evidence in bank.additional_evidence:
        collect(evidence.skills)
        collect(evidence.technologies)
    return catalogue


def validate_current_cv_references(
    current_cv: CurrentCV, bank: ExperienceBank,
) -> list[CurrentCVReferenceIssue]:
    """Report all bank reference issues; inputs must already pass model validation.

    Neither document is modified. Future GET handlers can return these issues
    alongside the CV; PUT handlers can reject saving when the list is nonempty.
    """
    work_ids = {work.id for work in bank.work_experience}
    achievement_parents = {
        achievement.id: work.id
        for work in bank.work_experience
        for achievement in work.achievements
    }
    project_ids = {project.id for project in bank.projects}
    contribution_parents = {
        contribution.id: project.id
        for project in bank.projects
        for contribution in project.evidence
    }
    catalogue = build_skill_catalogue(bank)
    issues: list[CurrentCVReferenceIssue] = []

    for work_index, selection in enumerate(current_cv.work_experience):
        path = f"work_experience[{work_index}]"
        if selection.work_experience_id not in work_ids:
            issues.append(CurrentCVReferenceIssue(
                path=f"{path}.work_experience_id",
                reference=selection.work_experience_id,
                reason="Work experience does not exist in the experience bank.",
            ))
        for bullet_index, achievement_id in enumerate(selection.achievement_ids):
            reason = None
            if achievement_id not in achievement_parents:
                reason = "Achievement does not exist in the experience bank."
            elif achievement_parents[achievement_id] != selection.work_experience_id:
                reason = "Achievement does not belong to the selected work experience."
            if reason is not None:
                issues.append(CurrentCVReferenceIssue(
                    path=f"{path}.achievement_ids[{bullet_index}]",
                    reference=achievement_id,
                    reason=reason,
                ))

    for project_index, selection in enumerate(current_cv.projects):
        path = f"projects[{project_index}]"
        if selection.project_id not in project_ids:
            issues.append(CurrentCVReferenceIssue(
                path=f"{path}.project_id",
                reference=selection.project_id,
                reason="Project does not exist in the experience bank.",
            ))
        for bullet_index, contribution_id in enumerate(selection.contribution_ids):
            reason = None
            if contribution_id not in contribution_parents:
                reason = "Contribution does not exist in the experience bank."
            elif contribution_parents[contribution_id] != selection.project_id:
                reason = "Contribution does not belong to the selected project."
            if reason is not None:
                issues.append(CurrentCVReferenceIssue(
                    path=f"{path}.contribution_ids[{bullet_index}]",
                    reference=contribution_id,
                    reason=reason,
                ))

    for group_index, group in enumerate(current_cv.skill_groups):
        for skill_index, key in enumerate(group.skill_keys):
            if key not in catalogue:
                issues.append(CurrentCVReferenceIssue(
                    path=f"skill_groups[{group_index}].skill_keys[{skill_index}]",
                    reference=key,
                    reason="Skill key is not available in the experience bank.",
                ))
    return issues
