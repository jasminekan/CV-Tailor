from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    CurrentCV,
    CurrentCVLoadResponse,
    ExperienceBank,
    ExperienceBankMatch,
    JobDescriptionAnalysis,
    JobDescriptionRequest,
    MatchRequest,
)
from app.repositories.json_experience_bank import (
    ExperienceBankRepositoryError,
    JsonExperienceBankRepository,
)
from app.repositories.json_current_cv import CurrentCVRepositoryError, JsonCurrentCVRepository
from app.services.current_cv import validate_current_cv_references
from app.services.llm import LLMServiceError, analyse_job_description_with_llm
from app.services.matching import match_experience_bank
from app.services.technical_relationships import TechnicalRelationshipCatalogueError

app = FastAPI(title="CV Tailor API", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
EXPERIENCE_BANK_PATH = Path(
    os.getenv("EXPERIENCE_BANK_PATH", str(BASE_DIR / "data" / "experience_bank.json"))
)
experience_bank_repository = JsonExperienceBankRepository(EXPERIENCE_BANK_PATH)
CURRENT_CV_PATH = Path(
    os.getenv("CURRENT_CV_PATH", str(BASE_DIR / "data" / "current_cv.json"))
)
current_cv_repository = JsonCurrentCVRepository(CURRENT_CV_PATH)

# Neither store may overwrite the other store or its temporary save file.
bank_store_paths = {
    EXPERIENCE_BANK_PATH.resolve(),
    EXPERIENCE_BANK_PATH.with_suffix(f"{EXPERIENCE_BANK_PATH.suffix}.tmp").resolve(),
}
cv_store_paths = {
    CURRENT_CV_PATH.resolve(),
    CURRENT_CV_PATH.with_suffix(f"{CURRENT_CV_PATH.suffix}.tmp").resolve(),
}
if bank_store_paths & cv_store_paths:
    raise ValueError("Experience bank and Current CV storage paths must not overlap.")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyse", response_model=JobDescriptionAnalysis)
def analyse_job_description(
    request: JobDescriptionRequest,
) -> JobDescriptionAnalysis:
    try:
        return analyse_job_description_with_llm(request.job_description)
    except LLMServiceError as error:
        raise HTTPException(
            status_code=502,
            detail="The job description could not be analysed.",
        ) from error


@app.get("/experience-bank", response_model=ExperienceBank)
def get_experience_bank() -> ExperienceBank:
    try:
        return experience_bank_repository.load()
    except ExperienceBankRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The experience bank could not be loaded.",
        ) from error


@app.put("/experience-bank", response_model=ExperienceBank)
def save_experience_bank(bank: ExperienceBank) -> ExperienceBank:
    try:
        return experience_bank_repository.save(bank)
    except ExperienceBankRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The experience bank could not be saved.",
        ) from error


@app.get("/current-cv", response_model=CurrentCVLoadResponse)
def get_current_cv() -> CurrentCVLoadResponse:
    try:
        current_cv = current_cv_repository.load()
    except CurrentCVRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The Current CV could not be loaded.",
        ) from error
    try:
        bank = experience_bank_repository.load()
    except ExperienceBankRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The experience bank could not be loaded.",
        ) from error
    return CurrentCVLoadResponse(
        current_cv=current_cv,
        reference_issues=validate_current_cv_references(current_cv, bank),
    )


@app.put("/current-cv", response_model=CurrentCV)
def save_current_cv(current_cv: CurrentCV) -> CurrentCV:
    try:
        bank = experience_bank_repository.load()
    except ExperienceBankRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The experience bank could not be loaded.",
        ) from error
    issues = validate_current_cv_references(current_cv, bank)
    if issues:
        raise HTTPException(
            status_code=422,
            detail=[issue.model_dump() for issue in issues],
        )
    try:
        return current_cv_repository.save(current_cv)
    except CurrentCVRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The Current CV could not be saved.",
        ) from error


@app.post("/match", response_model=ExperienceBankMatch)
def match_job_against_experience_bank(
    request: MatchRequest,
) -> ExperienceBankMatch:
    try:
        bank = experience_bank_repository.load()
    except ExperienceBankRepositoryError as error:
        raise HTTPException(
            status_code=503,
            detail="The experience bank could not be loaded.",
        ) from error
    try:
        return match_experience_bank(bank, request.job_analysis)
    except TechnicalRelationshipCatalogueError as error:
        raise HTTPException(
            status_code=503,
            detail="The technical relationship catalogue could not be loaded.",
        ) from error
