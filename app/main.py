from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import JobDescriptionAnalysis, JobDescriptionRequest
from app.services.llm import LLMServiceError, analyse_job_description_with_llm

app = FastAPI(title="CV Tailor API", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

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