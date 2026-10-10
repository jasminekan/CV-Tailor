# JobMatch CV Tailor — V2

JobMatch CV Tailor is a local FastAPI application for analysing job descriptions
and finding supporting evidence in a manually maintained experience bank. V2
selects and ranks original evidence; it does not generate or rewrite a CV.

## Completed functionality

- OpenAI extraction into five fields: job title, technical skills, other keywords,
  responsibilities, and qualifications.
- A browser editor for skills, work roles and achievements, projects and
  contributions, education, certifications, and additional evidence.
- Validated, versioned JSON storage with an atomic file replacement on save.
- Deterministic strong, related, and missing requirement classifications, plus
  ranked evidence with source IDs and explanations.
- Nonblank input/output validation, bank ID uniqueness, rejection of unknown bank
  fields and unsupported versions, safe rendering of stored values, and a guard
  against saving before the bank has loaded.

## Requirements and setup

Python 3.11+ and the packages in `requirements.txt` are required. The frontend uses
HTML, CSS, and vanilla JavaScript. No database or Node build is required.

Run commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

If you do not already have a `.env`, copy `.env.example` to `.env` and fill in
`OPENAI_API_KEY`. Do not overwrite an existing configured file.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for `/analyse`; read from the environment or `.env` |
| `OPENAI_MODEL` | Extraction model; defaults to `gpt-4o-mini` |
| `EXPERIENCE_BANK_PATH` | Optional process environment variable overriding the bank path |

`EXPERIENCE_BANK_PATH` is read by `app/main.py` from the process environment, so
export it before starting the server; putting it only in `.env` does not configure
that path. The default is `data/experience_bank.json` under the repository root.

```bash
python -m uvicorn app.main:app --reload
```

Open the frontend at `http://127.0.0.1:8000/`, interactive API documentation at
`http://127.0.0.1:8000/docs`, or the schema at `/openapi.json`.

A fresh checkout starts with an empty bank when the configured file is absent.
Saving creates the directory and JSON file. Local `.env` and `data/` files are
ignored by Git. No personal bank or configured credentials are needed to run the
mocked test suite or deterministic matching; live analysis requires your own key.

## Fictional example bank

`examples/experience_bank.example.json` contains fictional data, not a real CV.
You can inspect it without changing your bank. To try it through the editor, use
`PUT /experience-bank` only against a separate example store:

```bash
export EXPERIENCE_BANK_PATH="$PWD/data/example_bank.json"
python -m uvicorn app.main:app --reload
```

In another terminal, send the fictional example:

```bash
curl -X PUT http://127.0.0.1:8000/experience-bank \
  -H 'Content-Type: application/json' \
  --data-binary @examples/experience_bank.example.json
```

PUT replaces the entire configured bank. Check the server's configured path
before sending it. Back up existing banks manually.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/` | Browser frontend |
| GET | `/health` | Returns `{"status":"ok"}` |
| POST | `/analyse` | Extracts a structured job analysis using OpenAI |
| GET | `/experience-bank` | Loads the validated saved bank |
| PUT | `/experience-bank` | Validates and replaces the entire bank |
| POST | `/match` | Matches an analysis against the saved bank; no OpenAI call |

For Postman, use raw JSON bodies and `Content-Type: application/json`.

### Analyse

```json
{
  "job_description": "Software Engineer. Python and FastAPI experience. Work in an Agile team, build APIs, and write unit tests."
}
```

The description must contain 20–20,000 characters and must not be whitespace-only.
The response has a nonblank `job_title` and four string lists:

```json
{
  "job_title": "Software Engineer",
  "technical_skills": ["Python", "FastAPI", "unit testing"],
  "other_keywords": ["Agile"],
  "responsibilities": ["Build APIs"],
  "qualifications": []
}
```

This is illustrative; live extraction wording varies. Individual list entries
cannot be blank, but empty lists are valid. The prompt preserves qualification
alternatives together and keeps independently required qualifications separate.

### Match

Wrap the analysis response in `job_analysis`:

```json
{
  "job_analysis": {
    "job_title": "Software Engineer",
    "technical_skills": ["Python", "testable code", "Go"],
    "other_keywords": ["Agile"],
    "responsibilities": [],
    "qualifications": []
  }
}
```

The response contains `job_title`, `strong_matches`, `related_matches`,
`missing_requirements`, and `ranked_evidence`. Requirement results contain their
status, matching signals, evidence references, and explanation. Ranked records
contain a rank, source reference, status, matched requirements, score, and
explanation. There is no overall match percentage or hiring prediction.

Invalid request bodies return 422. Caught analysis failures return 502. Bank
read/write failures, including invalid stored bank data, return 503.

## Bank and matching rules

The bank accepts only integer `schema_version: 1`. Unknown fields are rejected at
all bank levels. Record IDs must be nonblank and unique across the bank, including
nested evidence. Omitted IDs are generated. Evidence text and skill, technology,
and outcome entries must be nonblank; valid text is preserved unchanged. Optional
empty lists and descriptive fields remain allowed. Files are not automatically
migrated or cleaned.

Roles/projects have their own tags. Child achievements/contributions use only
their own tags, text, and outcomes; parent tags never propagate to children.
Direct wording or explicit child tags can support strong matches. Standalone
skills and parent declarations without direct wording are related. Explicit
local capability denials override contradictory tags for that record.

Matching uses bounded phrases and a small alias map, including API terminology,
Agile, mentoring, and full-stack variants. Equivalent known aliases are counted
once. Specific testing evidence supports generic testing, and supports testable
code as related evidence. Demonstrated LLM integration provides related support
for AI proficiency. C#/.NET requires both signals on one record. Degree matching
preserves recognised level-and-subject pairings within alternatives.

Each evidence record earns 10 points per strong requirement and 3 per related
requirement. Equal scores use relevant practical-activity priority, then
descriptive support, then tag-only support, with bank order retained for remaining
ties. Scores measure recognised coverage, not CV bullet quality or proficiency.

Banks saved with the earlier editor may contain copied parent tags. Review a
backup copy and retain only child tags actually supported by that contribution.
Do not automatically remove every parent/child overlap: some are legitimate.

## Tests

```bash
python -m pytest -q
```

Tests cover API validation and error handling, mocked OpenAI responses, JSON
persistence using temporary files, bank integrity, matching boundaries, degree
pairings, contradictions, aliases, and ranking. Frontend safety tests inspect
source code; they do not execute a browser. Automated tests do not call OpenAI or
write the user's saved bank. Manual browser testing complements them.

## Postman and repository privacy

Sanitised collections and request definitions can be committed as API examples.
The existing `postman/collections/` request is a localhost bank read and contains
no saved response or bank body. `.resources/definition.yaml` is its collection
metadata. Review any future request bodies, headers, scripts, and saved responses
before committing them.

Keep `.postman/` workspace bindings, `postman/globals/`, `postman/environments/`,
and exported environment/global value files local. They may contain personal
workspace identifiers or credentials. The ignore rules deliberately do not
exclude request collections. `.env.example` contains no key and is safe to commit.

## Known V2 limitations

- Intended for local, single-user use. No authentication or concurrent-edit
  protection. Atomic replacement is not a backup or power-loss durability guarantee.
- PUT is a full replacement. Education/certification renaming in the text editor
  can regenerate IDs. Dates and links have no semantic validation.
- Qualification extraction is probabilistic. Matching does not interpret general
  technology alternatives, required/preferred importance, or semantic duplicates.
- Complex negation, ambiguous degree wording, and joint multi-degree requirements
  are intentionally not fully interpreted. Phrase rules can miss valid evidence.
- Strong support can be lexical or tag-based; it does not always demonstrate
  practical proficiency. Missing evidence does not prove missing experience.
- Match references omit dates and separate outcomes; the original bank retains them.
- Dependency versions are currently unpinned; installations may differ over time.

Overall evidence coverage, richer requirement relationships, CV generation,
PDF/DOCX export, and multi-user storage are outside completed V2.
