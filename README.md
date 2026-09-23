# CV Tailor

CV Tailor is a lightweight FastAPI application that analyses a job description and extracts the key signals a candidate needs to match the role. The goal is to help a user understand the strongest requirements in a role and then tailor a CV around those signals.

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

## Project structure

```text
.
├── app/
│   ├── main.py
│   ├── models.py
│   └── services/
│       └── llm.py
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

## v1 feature summary

Version 1 delivers the core CV tailoring workflow as a focused, usable MVP:

- job description parsing
- LLM-based extraction of skills and role requirements
- structured analysis output for downstream CV tailoring
- simple browser-based interface for quick evaluation
- API endpoint with validation and error handling
- test coverage for app health, frontend serving, and LLM response handling

## Notes

This project is intentionally scoped as a v1 MVP. It focuses on extracting useful role information from job descriptions and exposing that in a structured, reusable format. Later versions can extend this into full CV tailoring workflows, matching, recommendations, and user-facing editing tools.
