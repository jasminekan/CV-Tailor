# JobMatch CV Tailor

JobMatch CV Tailor is a locally runnable application for comparing job requirements
with recorded experience and choosing relevant CV content. It helps keep a focused
CV grounded in evidence: OpenAI extracts the job requirements, then deterministic
Python services match and select content from a structured Experience Bank.
Original achievements, contributions and skill labels retain their wording.

## What it does

- **Experience Bank:** maintain work roles, achievements, projects, contributions,
  skills, education, certifications and additional evidence.
- **My CV:** build an ordered baseline CV by selecting existing records, organising
  skills into groups and setting optional tailoring limits.
- **Job analysis:** extract structured requirements with source quotations,
  required/preferred importance and grouped alternatives.
- **Evidence matching:** review strong, related and missing requirements, ranked
  evidence and explanations tied to source records.
- **Tailored preview:** review recommended content, omissions and requirement
  coverage without changing the saved bank or baseline CV.

## Workflow

**Job description → structured requirement extraction → Experience Bank matching
→ evidence-based content selection → read-only tailored preview**

Start by adding evidence to **Experience Bank** and selecting your baseline work
roles in **My CV**. In **Tailor CV**, use the Analyse, Match and Tailor stages to
review a job and generate a preview. Navigation preserves drafts and the current
job session; saving management changes is explicit.

Only `/analyse` sends the supplied job description to OpenAI. Matching and preview
selection run locally against saved data. Structured output constrains the model's
response; Python verifies source quotations, assigns analysis-local requirement
IDs and derives the display lists. Matching and selection are deterministic for
unchanged inputs and catalogue data. Live extraction can vary and needs review.

## Screenshots

Local application shown with fictional fixture data and controlled analysis
responses.

| Analyse requirements | Match evidence | Review the tailored preview |
| --- | --- | --- |
| ![Analyse stage with grouped job requirements](docs/images/analyse.png) | ![Match stage with evidence and requirement details](docs/images/match.png) | ![Read-only tailored CV and selection explanations](docs/images/tailor.png) |

## Stack and architecture

**Backend:** Python, FastAPI, Pydantic, OpenAI Python SDK and Uvicorn.
**Frontend:** HTML, CSS and vanilla JavaScript.
**Storage:** two local JSON documents. **Tests:** pytest, HTTPX and JavaScript
behaviour harnesses. No database or frontend build step is required.

```text
app/
  main.py                 HTTP routes and service orchestration
  models.py               Request, response and saved-document validation
  services/               Extraction, matching, provenance and CV selection
  repositories/           Experience Bank and Current CV JSON persistence
  data/                   Curated technical relationship catalogue
static/                   Browser workspace and editors
tests/                    API, service, persistence and frontend tests
examples/                 Fictional Experience Bank
evaluations/extraction/   Isolated extraction evaluation harness
```

Extraction, requirement preparation, matching, candidate discovery and content
selection have separate responsibilities. CV selections store stable record IDs
and skill keys rather than copied bullet text. Preview responses include the
source snapshot used for selection, so the browser can display the original
wording with its provenance. See the [architecture and API reference](docs/architecture.md).

## Run locally

Use Python 3.11 or newer. Run commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1`.

If you do not already have a `.env`, copy `.env.example` to `.env`. Set your own
`OPENAI_API_KEY` to enable job analysis; never commit a configured `.env`.

| Variable | Default | Read from |
| --- | --- | --- |
| `OPENAI_API_KEY` | Required for `/analyse` | Process environment or `.env` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Process environment or `.env` |
| `EXPERIENCE_BANK_PATH` | `data/experience_bank.json` | Process environment only |
| `CURRENT_CV_PATH` | `data/current_cv.json` | Process environment only |

Default data paths are relative to the repository root. Export custom store paths
before starting the server; placing them only in `.env` does not configure them.
Keep both paths and their `.tmp` save paths distinct. Use the ignored `data/`
directory or a location outside the checkout for personal stores; arbitrary
custom filenames are not automatically ignored by Git.

```bash
python -m uvicorn app.main:app --reload
```

Open [the application](http://127.0.0.1:8000/) or the
[interactive API documentation](http://127.0.0.1:8000/docs).
The schema is available at `/openapi.json` and `/health` returns `{"status":"ok"}`.
Missing stores load as empty documents; an explicit save creates the directory
and JSON file. The editors, matching API and preview API work without an OpenAI
key. The browser's job-analysis step requires one.

### Try fictional data

[The example bank](examples/experience_bank.example.json) contains fictional
records. To try it without replacing a personal bank, start a separate server
session with these store paths (stop any existing server on port 8000 first):

```bash
export EXPERIENCE_BANK_PATH="$PWD/data/example_bank.json"
export CURRENT_CV_PATH="$PWD/data/example_current_cv.json"
python -m uvicorn app.main:app --reload
```

In another terminal, from the repository root:

```bash
curl -X PUT http://127.0.0.1:8000/experience-bank \
  -H 'Content-Type: application/json' \
  --data-binary @examples/experience_bank.example.json
```

`PUT` replaces the entire configured bank. Confirm the server uses the example
paths before importing. Use **My CV** to select baseline roles and bullets.
The [API reference](docs/architecture.md#api) includes a fictional matching request
that works without calling OpenAI.

## Tests

```bash
python -m pytest -q
git diff --check
```

The suite uses fictional fixtures, temporary stores and mocked provider responses;
it requires neither credentials nor live OpenAI requests. It covers validation,
matching semantics, evidence provenance, selection policies, persistence, frontend
state, stale responses and read-only previews.

JavaScript behaviour tests run with Node.js or JavaScriptCore (`jsc`, including
the macOS system runtime where available). Those tests skip if neither runtime is
installed. Their DOM/network mocks complement manual browser checks; they do not
verify layout or assistive-technology behaviour.

The [extraction evaluation harness](evaluations/extraction/README.md) has an offline
dry run for inspecting its synthetic fixtures and comparison plan. Live evaluation
is separate, opt-in and uses OpenAI requests.

## Current limitations

- The application is intended for local, single-user use. It has no authentication,
  multi-user isolation or coordinated concurrent writes across its JSON stores.
- Extraction can omit or misinterpret requirements. Quotation validation checks
  lexical provenance, not the correctness or completeness of an interpretation.
- Matching uses curated relationships and conservative phrase/activity rules.
  A missing match means no recognised evidence was found; it does not establish
  that someone lacks the experience. Scores describe evidence coverage, not a
  hiring prediction or overall compatibility percentage.
- Tailoring is a greedy selection process with configurable ceilings. It keeps
  baseline work roles, can recommend other bank projects and explicit skills,
  and leaves education/certifications in bank order. Human review remains useful.
- Tailored previews are read-only. There is no automatic application of
  recommendations, generated CV prose or downloadable PDF/DOCX export.
- Job sessions and unsaved drafts live in memory. Refreshing the page loses them;
  saved bank/CV changes require an explicit save. A preview describes its returned
  snapshot and does not automatically follow later saved edits.
