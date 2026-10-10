# CV Tailor

CV Tailor is a lightweight FastAPI application built around a manually maintained experience bank. The bank is the source of truth; job analysis and matching select the strongest evidence for a role without rewriting the user's underlying experience.

## v1 capabilities

This first version focuses on the core analysis workflow:

- Accepts a raw job description text via a simple API
- Uses an LLM to extract structured insights from the role
- Returns a structured JSON payload containing:
  - job title
  - technical skills
  - other relevant keywords and capabilities
  - responsibilities
  - qualifications
- Serves a small frontend that lets a user paste a job description and view the analysis
- Includes health-check and API smoke-test coverage for the FastAPI app

## v2 capabilities

- Maintains structured work experience, achievement bullets, skills, projects, education, certifications, and additional evidence
- Persists the experience bank in a local versioned JSON file
- Preserves the existing job-description analysis endpoint
- Matches explicit experience-bank evidence against analyzed job requirements
- Ranks relevant evidence and reports strong, related, and missing requirements

The local JSON store is intended for a single-user development workflow. It is not a multi-user database, does not provide authentication or concurrent editing, and should be backed up manually. Matching results are computed per request and are not persisted.

## Project structure

```text
.
├── app/
│   ├── main.py
│   ├── models.py
│   ├── repositories/
│   │   └── json_experience_bank.py
│   └── services/
│       ├── llm.py
│       └── matching.py
├── static/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── tests/
│   ├── test_api.py
│   └── test_llm.py
├── .env.example
├── .gitignore
├── job_description.txt
├── requirements.txt
└── README.md
```

## Tech stack

- Python 3.11+
- FastAPI
- Pydantic v2
- OpenAI Python SDK
- Static HTML/CSS/JavaScript frontend
- pytest for automated tests

No PDF/DOCX parsing or database dependency is required for V2. The experience bank is entered and maintained as structured data by the user.

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure your environment:

Copy `.env.example` to `.env` and add your API key and model:

```bash
cp .env.example .env
```

Example:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

4. Run the API locally:

```bash
uvicorn app.main:app --reload
```

The app will be available at:

- http://127.0.0.1:8000/
- Swagger docs: http://127.0.0.1:8000/docs

## API usage

Send a job description to the analysis endpoint:

```bash
curl -X POST "http://127.0.0.1:8000/analyse" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "We are seeking a Python engineer with FastAPI and SQL experience..."
  }'
```

Example response:

```json
{
  "job_title": "Python Engineer",
  "technical_skills": ["Python", "FastAPI", "SQL"],
  "other_keywords": ["teamwork", "problem solving"],
  "responsibilities": ["Build and maintain APIs", "Collaborate with cross-functional teams"],
  "qualifications": ["Bachelor's degree in Computer Science"]
}
```

### Experience bank

Read the current local bank:

```bash
curl "http://127.0.0.1:8000/experience-bank"
```

Replace it with a validated structured bank using `PUT /experience-bank`. The storage path defaults to `data/experience_bank.json` and can be changed with `EXPERIENCE_BANK_PATH`.

Run matching by sending the result of `/analyse` to `POST /match`:

```json
{
  "job_analysis": {
    "job_title": "Backend Engineer",
    "technical_skills": ["Python", "FastAPI"],
    "other_keywords": [],
    "responsibilities": [],
    "qualifications": []
  }
}
```

## v1 feature summary

Version 1 delivers the core CV tailoring workflow as a focused, usable MVP:

- job description parsing
- LLM-based extraction of skills and role requirements
- structured analysis output for downstream CV tailoring
- simple browser-based interface for quick evaluation
- API endpoint with validation and error handling
- test coverage for app health, frontend serving, and LLM response handling

## Roadmap

V2 deliberately stops at evidence selection. Tailored one-page CV generation, user review of generated drafts, PDF/DOCX export, authentication, multi-user storage, PostgreSQL, cloud backups, and saved job history are candidates for V3/V4. A future CV generator should consume selected bank item IDs and produce a separate draft; it should never replace the experience bank.
