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

## V2 matching rules and existing-bank cleanup

Evidence is matched locally: role/project tags never propagate to child bullets.
A direct phrase in a description or outcome, or an explicit child tag, supports a
strong match. Standalone skills and role/project tags without direct wording are
related. Degree matches require both an accepted degree level and an explicitly
matching subject; named certifications can match directly. The small alias map
and whole-token boundaries are deliberately conservative. Specific unit or
automated testing evidence supports generic testing, but not vice versa.

Sentence responsibilities with only recognised concept overlap are related, not
proof of every obligation. Equivalent skill aliases are deduplicated. Each
unique requirement contributes 10 points for direct support or 3 for related
support, with stable bank-order ties. Requirement status and evidence status
both use the best support available; ranked explanations show the status for
each requirement when an item has mixed support.

The editor now keeps separate child tags, outcomes, and IDs. New evidence starts
with empty tags; saving does not copy role/project metadata into it. Existing
child tags are retained because the bank has no provenance flag distinguishing
intentional tags from old frontend copies.

Banks saved with the old editor may contain copied parent tags on child bullets.
Until reviewed, those tags can still cause false strong matches. Do not delete
all parent/child overlaps: some are legitimate.

A safe review workflow:

1. Copy `data/experience_bank.json` to a dated backup outside the active store.
2. Make a second review copy, retaining every ID, text, outcome, and parent tag.
3. Review each child's `skills` and `technologies`. Lists identical to the
   parent's are cleanup candidates, not proof that each tag is incorrect.
   Keep only tags specifically supported by that bullet or known to be true of
   that contribution. For example, the Python/FastAPI API endpoint supports
   those technologies and API/backend development; the responsive frontend
   bullet does not establish Python or backend development. The unit-test
   bullet supports unit testing and testing; do not assume a testing framework
   or language absent from its evidence.
4. Preview the review copy with `match_experience_bank` in memory, or run a
   separate local instance with `EXPERIENCE_BANK_PATH` pointing to that copy.
   Do not PUT the review copy into the original instance while still reviewing.
5. Compare selected IDs, statuses, and rankings. Adopt the reviewed copy only
   after inspection and retain the backup.

For `job_description.txt` (Checkout.com), manually inspect the extracted analysis
as well as matches: Agile environment and testing evidence should be found;
BSc/MSc Computer Science should support the stated degree alternatives; mentoring
should select the additional mentoring record. Sentence responsibilities may
remain related because leadership, deadlines, resilience, and scale are separate
claims. Go, payments knowledge, and microservices must not be inferred from
unrelated technology tags. LLM extraction wording can vary; unsupported wording
can remain missing until a justified alias or explicit local tag is added.

Related support also includes same-record C# plus .NET declarations, testing
practice as support for testable code, and demonstrated LLM integration as
support for AI proficiency. These directional rules do not establish clean code,
AI expertise, or system design. Partial responsibility explanations identify the
supported activity and state that other requested claims remain unestablished.
Explicit project leadership, system ownership, and delivery evidence can support
those responsibilities; ordinary feature implementation cannot. Equal-score
ranking prefers demonstrated practical activity, then descriptive support, then
tag-only declarations, retaining bank order for remaining ties. Scores and
classifications are unchanged by these tie-breaks.

Qualification extraction preserves alternative degree levels and subjects as one
requirement string while keeping independent qualifications separate. Grouping
still depends on LLM output; the matcher does not merge separately extracted
qualifications. Narrow aliases cover team mentorship and full-stack application
wording, with support kept on the individual record describing that experience.
