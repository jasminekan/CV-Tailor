from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
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
from app.services.llm import LLMServiceError, analyse_job_description_with_llm
from app.services.matching import match_experience_bank

app = FastAPI(title="CV Tailor API", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
EXPERIENCE_BANK_PATH = Path(
    os.getenv("EXPERIENCE_BANK_PATH", str(BASE_DIR / "data" / "experience_bank.json"))
)
experience_bank_repository = JsonExperienceBankRepository(EXPERIENCE_BANK_PATH)

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
    return match_experience_bank(bank, request.job_analysis)