from typing import Literal
from uuid import uuid4

from pydantic import (
    BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler,
    field_validator, model_serializer, model_validator,
)


class JobDescriptionRequest(BaseModel):
    job_description: str = Field(
        min_length=20,
        max_length=20_000,
        description="The job description to analyse.",
    )

    @field_validator("job_description")
    @classmethod
    def reject_blank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Job description must contain non-whitespace text.")
        return value


RequirementCategory = Literal["skill", "other_keyword", "responsibility", "qualification"]
RequirementImportance = Literal["required", "preferred", "unspecified"]
RequirementActivity = Literal["technology_usage", "api_development", "cloud_deployment"]

REQUIREMENT_CATEGORY_FIELDS = {
    "skill": "technical_skills",
    "other_keyword": "other_keywords",
    "responsibility": "responsibilities",
    "qualification": "qualifications",
}


class _RequirementContent(BaseModel):
    """Shared validation for extracted and analysis-local requirement records."""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: str
    source_text: str
    category: RequirementCategory
    importance: RequirementImportance = "unspecified"
    alternatives: list[str] = Field(min_length=1)
    activity: RequirementActivity | None = None

    @field_validator("text", "source_text")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Requirement wording must contain non-whitespace text.")
        return value

    @field_validator("alternatives")
    @classmethod
    def reject_blank_alternatives(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Requirement alternatives must contain non-whitespace text.")
        return values


class StructuredRequirement(_RequirementContent):
    """One obligation: alternatives are OR; separate records are independent."""

    id: str

    @field_validator("id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Requirement IDs must contain non-whitespace text.")
        return value


class ExtractedRequirement(_RequirementContent):
    """Provider content only: Python assigns IDs; metadata must be explicit."""

    importance: RequirementImportance
    activity: RequirementActivity | None


class JobDescriptionExtraction(BaseModel):
    """A single authoritative provider response, without legacy lists or IDs."""

    model_config = ConfigDict(extra="forbid", strict=True)

    job_title: str
    requirements: list[ExtractedRequirement]

    @field_validator("job_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Job title must contain non-whitespace text.")
        return value


class LegacyJobDescriptionAnalysis(BaseModel):
    """The retained five-field representation for older analysis consumers."""

    job_title: str
    technical_skills: list[str] = Field(default_factory=list)
    other_keywords: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)

    @field_validator("job_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Job title must contain non-whitespace text.")
        return value

    @field_validator(
        "technical_skills", "other_keywords", "responsibilities", "qualifications"
    )
    @classmethod
    def reject_blank_entries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Analysis entries must contain non-whitespace text.")
        return values


class JobDescriptionAnalysis(LegacyJobDescriptionAnalysis):
    requirements: list[StructuredRequirement] | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def project_structured_requirements(self) -> "JobDescriptionAnalysis":
        if self.requirements is None:
            return self
        projected: dict[str, list[str]] = {
            field: [] for field in REQUIREMENT_CATEGORY_FIELDS.values()
        }
        seen: set[str] = set()
        for requirement in self.requirements:
            # Whitespace around an ID must not evade duplicate detection.
            key = requirement.id.strip()
            if key in seen:
                raise ValueError(f"Duplicate requirement ID: {requirement.id!r}")
            seen.add(key)
            projected[REQUIREMENT_CATEGORY_FIELDS[requirement.category]].append(requirement.text)
        for field, values in projected.items():
            if field in self.model_fields_set and getattr(self, field) != values:
                raise ValueError(
                    f"{field} contradicts structured requirements; omit it or supply "
                    "the exact ordered requirement text for its category."
                )
            setattr(self, field, values)
        return self

    @model_serializer(mode="wrap")
    def omit_absent_requirements(self, handler: SerializerFunctionWrapHandler):
        """Legacy responses retain their exact five-field shape, not a new null."""
        # An explicit dict return type would erase field details in output schemas.
        result = handler(self)
        if self.requirements is None:
            result.pop("requirements", None)
        return result


class _BankModel(BaseModel):
    """Bank validation only; unrelated API models retain their existing rules."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("id", "text", check_fields=False)
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("IDs and evidence text must contain non-whitespace text.")
        return value

    @field_validator("skills", "technologies", "outcomes", check_fields=False)
    @classmethod
    def reject_blank_entries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Bank list entries must contain non-whitespace text.")
        return values


class EvidenceItem(_BankModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = Field(min_length=1, max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    outcomes: list[str] = Field(default_factory=list, max_length=10)


class WorkExperience(_BankModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    employer: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    start_date: str | None = Field(default=None, max_length=30)
    end_date: str | None = Field(default=None, max_length=30)
    summary: str = Field(default="", max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    achievements: list[EvidenceItem] = Field(default_factory=list, max_length=50)


class Project(_BankModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    link: str | None = Field(default=None, max_length=500)


class Education(_BankModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    institution: str = Field(min_length=1, max_length=200)
    qualification: str = Field(min_length=1, max_length=200)
    field: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=30)


class Certification(_BankModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=30)


class ExperienceBank(_BankModel):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    skills: list[str] = Field(default_factory=list, max_length=100)
    work_experience: list[WorkExperience] = Field(default_factory=list, max_length=50)
    projects: list[Project] = Field(default_factory=list, max_length=50)
    education: list[Education] = Field(default_factory=list, max_length=20)
    certifications: list[Certification] = Field(default_factory=list, max_length=50)
    additional_evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)


    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "ExperienceBank":
        # Evidence references identify records by ID across the entire bank.
        records = [
            *self.work_experience, *self.projects, *self.education,
            *self.certifications, *self.additional_evidence,
        ]
        for role in self.work_experience:
            records.extend(role.achievements)
        for project in self.projects:
            records.extend(project.evidence)
        seen: set[str] = set()
        for record in records:
            if record.id in seen:
                raise ValueError(f"Duplicate experience-bank ID: {record.id}")
            seen.add(record.id)
        return self


class EvidenceReference(BaseModel):
    evidence_id: str
    source_type: str
    source_label: str
    text: str


class RelationshipReference(BaseModel):
    source: str
    target: str
    type: Literal["broader", "transferable", "uses_language"]
    confidence: Literal["high", "medium"]


class MatchingSignal(BaseModel):
    signal: str
    origin: Literal["wording", "outcome", "standalone_skill", "skill_tag", "technology_tag", "credential"]
    relationship: RelationshipReference | None = None
    demonstrated_activity: RequirementActivity | None = None


class EvidenceSupport(BaseModel):
    requirement_id: str
    evidence_id: str
    status: Literal["strong", "related"]
    selected_alternative: str
    signals: list[MatchingSignal] = Field(default_factory=list)
    explanation: str


class MatchResult(BaseModel):
    requirement: str
    status: str
    matched_signals: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    explanation: str
    requirement_details: StructuredRequirement | None = None
    selected_alternative: str | None = None
    evidence_support: list[EvidenceSupport] = Field(default_factory=list)


class RankedEvidence(BaseModel):
    rank: int
    evidence: EvidenceReference
    status: str
    matched_signals: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)
    explanation: str
    evidence_support: list[EvidenceSupport] = Field(default_factory=list)


class ExperienceBankMatch(BaseModel):
    job_title: str
    strong_matches: list[MatchResult] = Field(default_factory=list)
    related_matches: list[MatchResult] = Field(default_factory=list)
    missing_requirements: list[MatchResult] = Field(default_factory=list)
    ranked_evidence: list[RankedEvidence] = Field(default_factory=list)


class MatchRequest(BaseModel):
    job_analysis: JobDescriptionAnalysis


def normalise_skill_key(value: str) -> str:
    """Canonical skill identity, also used for skill group name comparisons."""
    return " ".join(value.split()).lower()


def _reject_current_cv_duplicates(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Duplicate {label}: {value}")
        seen.add(value)


class _CurrentCVModel(BaseModel):
    """Current CV rules only; existing experience-bank models are unchanged."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("work_experience_id", "project_id", "name", check_fields=False)
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("IDs and skill group names must contain non-whitespace text.")
        return value

    @field_validator("achievement_ids", "contribution_ids", check_fields=False)
    @classmethod
    def validate_bullet_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Bullet IDs must contain non-whitespace text.")
        _reject_current_cv_duplicates(values, "bullet ID")
        return values


class CurrentCVWorkSelection(_CurrentCVModel):
    work_experience_id: str
    achievement_ids: list[str] = Field(default_factory=list)


class CurrentCVProjectSelection(_CurrentCVModel):
    project_id: str
    contribution_ids: list[str] = Field(default_factory=list)


class CurrentCVSkillGroup(_CurrentCVModel):
    name: str
    skill_keys: list[str] = Field(default_factory=list)

    @field_validator("skill_keys")
    @classmethod
    def validate_skill_keys(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.strip():
                raise ValueError("Skill keys must contain non-whitespace text.")
            if value != normalise_skill_key(value):
                raise ValueError("Skill keys must be lowercase with normalised whitespace.")
        _reject_current_cv_duplicates(values, "skill key")
        return values


class TailoringSettings(_CurrentCVModel):
    max_achievements_per_role: int | None = Field(default=None, strict=True, ge=0)
    max_contributions_per_project: int | None = Field(default=None, strict=True, ge=0)
    max_projects: int | None = Field(default=None, strict=True, ge=0)
    max_skills: int | None = Field(default=None, strict=True, ge=0)


class CurrentCV(_CurrentCVModel):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    work_experience: list[CurrentCVWorkSelection] = Field(default_factory=list)
    projects: list[CurrentCVProjectSelection] = Field(default_factory=list)
    skill_groups: list[CurrentCVSkillGroup] = Field(default_factory=list)
    tailoring_settings: TailoringSettings = Field(default_factory=TailoringSettings)

    @model_validator(mode="after")
    def reject_duplicate_selections(self) -> "CurrentCV":
        _reject_current_cv_duplicates(
            [item.work_experience_id for item in self.work_experience], "work experience ID"
        )
        _reject_current_cv_duplicates(
            [item.project_id for item in self.projects], "project ID"
        )
        _reject_current_cv_duplicates(
            [bullet_id for item in self.work_experience for bullet_id in item.achievement_ids]
            + [bullet_id for item in self.projects for bullet_id in item.contribution_ids],
            "bullet ID",
        )
        _reject_current_cv_duplicates(
            [normalise_skill_key(group.name) for group in self.skill_groups],
            "skill group name",
        )
        _reject_current_cv_duplicates(
            [key for group in self.skill_groups for key in group.skill_keys], "skill key"
        )
        return self


class CurrentCVReferenceIssue(BaseModel):
    """A bank reference issue reported separately from the saved CV document."""

    model_config = ConfigDict(extra="forbid")

    path: str
    reference: str
    reason: str


class CurrentCVLoadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_cv: CurrentCV
    reference_issues: list[CurrentCVReferenceIssue] = Field(default_factory=list)
