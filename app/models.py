from uuid import uuid4

from pydantic import BaseModel, Field


class JobDescriptionRequest(BaseModel):
    job_description: str = Field(
        min_length=20,
        max_length=20_000,
        description="The job description to analyse.",
    )


class JobDescriptionAnalysis(BaseModel):
    job_title: str
    technical_skills: list[str] = Field(default_factory=list)
    other_keywords: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = Field(min_length=1, max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    outcomes: list[str] = Field(default_factory=list, max_length=10)


class WorkExperience(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    employer: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    start_date: str | None = Field(default=None, max_length=30)
    end_date: str | None = Field(default=None, max_length=30)
    summary: str = Field(default="", max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    achievements: list[EvidenceItem] = Field(default_factory=list, max_length=50)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    link: str | None = Field(default=None, max_length=500)


class Education(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    institution: str = Field(min_length=1, max_length=200)
    qualification: str = Field(min_length=1, max_length=200)
    field: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=30)


class Certification(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=30)


class ExperienceBank(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    skills: list[str] = Field(default_factory=list, max_length=100)
    work_experience: list[WorkExperience] = Field(default_factory=list, max_length=50)
    projects: list[Project] = Field(default_factory=list, max_length=50)
    education: list[Education] = Field(default_factory=list, max_length=20)
    certifications: list[Certification] = Field(default_factory=list, max_length=50)
    additional_evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)


class EvidenceReference(BaseModel):
    evidence_id: str
    source_type: str
    source_label: str
    text: str


class MatchResult(BaseModel):
    requirement: str
    status: str
    matched_signals: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    explanation: str


class RankedEvidence(BaseModel):
    rank: int
    evidence: EvidenceReference
    status: str
    matched_signals: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)
    explanation: str


class ExperienceBankMatch(BaseModel):
    job_title: str
    strong_matches: list[MatchResult] = Field(default_factory=list)
    related_matches: list[MatchResult] = Field(default_factory=list)
    missing_requirements: list[MatchResult] = Field(default_factory=list)
    ranked_evidence: list[RankedEvidence] = Field(default_factory=list)


class MatchRequest(BaseModel):
    job_analysis: JobDescriptionAnalysis