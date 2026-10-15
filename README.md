# JobMatch CV Tailor — V3.2

JobMatch CV Tailor is a local FastAPI application for maintaining an experience
bank, manually assembling a Current CV, and analysing job descriptions against
the entire bank. V3.2 adds structured extraction, curated technical relationships
and matching with evidence provenance. The Current CV builder retains ordered
selections, skills groups, tailoring preferences and a live preview.
Original achievements and contributions are
selected by reference; the application does not generate or rewrite their text.

## Completed functionality

- OpenAI extraction of structured job requirements, with Python-derived legacy
  fields for job title, technical skills, other keywords, responsibilities and
  qualifications. Requirement metadata includes importance, alternatives and
  verified original source wording.
- A browser editor for skills, work roles and achievements, projects and
  contributions, education, certifications, and additional evidence.
- Validated, versioned JSON storage with an atomic file replacement on save.
- Deterministic strong, related, and missing requirement classifications, plus
  ranked evidence with source IDs, signal origins, activity checks and explanations.
- Explicit directional technical relationships, grouped OR alternatives and
  required/preferred metadata, without a candidate compatibility score.
- An isolated extraction evaluation harness with reviewed expectation fixtures,
  prompt/model comparisons and opt-in live execution.
- Nonblank input/output validation, bank ID uniqueness, rejection of unknown bank
  fields and unsupported versions, safe rendering of stored values, and a guard
  against saving before the bank has loaded.
- A separate My Current CV view for selecting, removing and ordering work roles,
  projects and their original bullet points using up/down buttons.
- Custom skills groups with unique headings and skill selection across all
  explicit bank tags, plus recovery from unavailable references.
- Four saved tailoring maximums (preferences only) and a read-only draft preview
  showing all existing education and certifications from the saved bank.
- Separate JSON persistence and GET/PUT endpoints for the Current CV, with
  structural validation, parent ownership checks and broken-reference reporting.

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
| `CURRENT_CV_PATH` | Optional process environment variable overriding the Current CV path |

`EXPERIENCE_BANK_PATH` is read by `app/main.py` from the process environment, so
export it before starting the server; putting it only in `.env` does not configure
that path. The default is `data/experience_bank.json` under the repository root.

V3.1 Phases 1–5 add Current CV models, JSON persistence, a skill catalogue,
reference validation services, GET/PUT endpoints, work/project selections,
custom skills groups, tailoring preferences, and a read-only preview.
`CURRENT_CV_PATH` follows the same process environment convention
and defaults to `data/current_cv.json`. Creating a repository does not load or
create either data file. Keep both store paths and their `.tmp` save paths
distinct; overlapping configured paths are rejected at startup before writes.
For example, the bank's `experience_bank.json.tmp` must not be your CV path.

The Current CV builder, JSON storage and deterministic matching work without an
OpenAI key. Only job-description analysis calls OpenAI. Keep custom stores under
the ignored `data/` directory or outside the checkout; arbitrary custom filenames
are not automatically excluded by Git.

The Current CV stores ordered record IDs and skill keys, without copied bullet
text. IDs and group names retain their original spelling. Skill keys must already
be lowercase, with outer whitespace removed and internal whitespace collapsed;
punctuation is preserved (`c`, `c++`, and `c#` are distinct). Duplicate group names
are compared using the same case/whitespace normalisation. Tailoring maximums
accept nonnegative integers or null and do not restrict manual selections.

`build_skill_catalogue(bank)` in `app/services/current_cv.py` returns a mapping
of canonical keys to original bank labels. It visits standalone skills, then
each role's skills/technologies and achievements, each project's skills/technologies
and contributions, certification skills, and additional-evidence skills/technologies.
List order is retained and the first label for a key wins. It does not infer from
text, use matching aliases, or assign skills to CV categories.

`validate_current_cv_references(current_cv, bank)` accepts validated models and
returns all issues in CV order, each with `path`, `reference`, and `reason`.
It distinguishes missing bullets from bullets under the wrong parent, and checks
skill keys against the full bank catalogue. Even when a parent is missing, its
selected bullets are checked. Neither input is modified and nothing is saved.
The API returns these issues alongside a loaded CV or rejects a save when
issues exist. A skill becomes unavailable only when its key disappears from all
explicit sources; a substantive rename changes the key and can break a selection.

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
`PUT /experience-bank` only against separate example stores:

```bash
export EXPERIENCE_BANK_PATH="$PWD/data/example_bank.json"
export CURRENT_CV_PATH="$PWD/data/example_current_cv.json"
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
| GET | `/current-cv` | Loads the Current CV and reports reference issues |
| PUT | `/current-cv` | Validates structure and bank references, then replaces the Current CV |
| POST | `/match` | Matches an analysis against the saved bank; no OpenAI call |

For Postman, use raw JSON bodies and `Content-Type: application/json`.

### Current CV

`GET /current-cv` returns `{"current_cv": {...}, "reference_issues": [...]}`.
A missing CV file returns an empty document with default settings; GET does not
create a file. Broken references are reported with HTTP 200 while the saved
selections and their order remain intact. Both the CV and saved bank must load
successfully; corrupt or invalid stored data returns HTTP 503.

`PUT /current-cv` accepts the raw Current CV document, not the GET envelope.
It validates against the current saved bank before saving and returns the saved
document with HTTP 200. Invalid structure returns FastAPI's standard HTTP 422
validation response. Invalid references return HTTP 422 with all reference issues:

```json
{
  "detail": [
    {
      "path": "work_experience[0].achievement_ids[1]",
      "reference": "missing-achievement",
      "reason": "Achievement does not exist in the experience bank."
    }
  ]
}
```

Repository failures return HTTP 503 with a generic message, without internal
diagnostics or filesystem paths. Invalid submissions and failed saves preserve
the previous CV. Saving a CV never updates the bank. PUT replaces the complete
CV, and does not load or require a valid previous CV file.

### Analyse

```json
{
  "job_description": "Software Engineer. Python or Java experience is required. AWS experience is preferred. Build APIs."
}
```

The description must contain 20–20,000 characters and must not be whitespace-only.
The response has a nonblank `job_title`, four compatible string lists, and an
authoritative structured `requirements` list:

```json
{
  "job_title": "Software Engineer",
  "technical_skills": ["Python or Java", "AWS"],
  "other_keywords": [],
  "responsibilities": ["Build APIs"],
  "qualifications": [],
  "requirements": [
    {
      "id": "r1",
      "text": "Python or Java",
      "source_text": "Python or Java experience is required.",
      "category": "skill",
      "importance": "required",
      "alternatives": ["Python", "Java"],
      "activity": null
    },
    {
      "id": "r2",
      "text": "AWS",
      "source_text": "AWS experience is preferred.",
      "category": "skill",
      "importance": "preferred",
      "alternatives": ["AWS"],
      "activity": null
    },
    {
      "id": "r3",
      "text": "Build APIs",
      "source_text": "Build APIs.",
      "category": "responsibility",
      "importance": "unspecified",
      "alternatives": ["Build APIs"],
      "activity": "api_development"
    }
  ]
}
```

This is illustrative; live extraction wording varies. Individual list entries
cannot be blank, but empty lists are valid. The prompt preserves qualification
alternatives together and keeps independently required qualifications separate.
The provider generates only job title and structured requirements. Python assigns
IDs, verifies quotations and derives the legacy lists. Unsupported source wording
fails analysis with the existing generic 502 response. Legacy five-field analysis
payloads remain accepted by `/match`; V3.2.4 adapts them through the same
preparation service used for structured analyses.

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
explanation. V3.2 additionally returns `requirement_details` (including ID,
importance, source wording, alternatives and activity), `selected_alternative`
and per-record `evidence_support`. Ranked records reuse those support decisions.
Each support includes signal origin and, where relevant, the explicit directional
relationship and demonstrated activity. Existing response fields remain available.
There is no overall match percentage or hiring prediction.

Invalid request bodies return 422. Caught analysis failures return 502. Bank
read/write failures, including invalid stored bank data, return 503. An invalid
technical relationship catalogue also causes `/match` to return a clear 503.

## Bank and matching rules

The bank accepts only integer `schema_version: 1`. Unknown fields are rejected at
all bank levels. Record IDs must be nonblank and unique across the bank, including
nested evidence. PUT generates omitted IDs for new records and persists them.
Stored JSON records must contain IDs; a hand-edited/imported file with missing
IDs returns 503 on load instead of generating different references on every GET.
Keep existing IDs when editing stored records. Back up and explicitly re-import
an ID-less bank through PUT if necessary; reads never migrate or repair files.
Evidence text and skill, technology,
and outcome entries must be nonblank; valid text is preserved unchanged. Optional
empty lists and descriptive fields remain allowed. Files are not automatically
migrated or cleaned.

Bank-editor saves preserve unchanged wording, line endings, tags and education/
certification rows. An unrelated save does not split an existing comma-containing
tag or regenerate IDs for an untouched row. Explicit edits still use the V2
comma/pipe text-entry formats; review edits containing embedded delimiters.

Roles/projects have their own tags. Child achievements/contributions use only
their own tags, text, and outcomes; parent tags never propagate to children.
Demonstrated technical use can support strong matches. Standalone skills and
local technology tags without demonstrated use are related, including child tags.
Local capability tags may be backed by actual same-record activity. Explicit
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

- **Strong**: direct evidence or an approved broader relationship supports the
  requested capability, with any explicit activity constraint demonstrated.
  The explanation identifies partial aspects such as unproven API maintenance.
- **Related**: transferable technology, declared knowledge or partial evidence
  provides relevance without establishing the full requested experience.
- **Missing**: no recognised supporting evidence satisfies the requirement and
  its activity constraint. This does not prove the person lacks that experience.

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

Current CV frontend behavior tests execute `static/current_cv.js` with a small
DOM mock and mocked API responses. They cover selections, ordering, safe text,
load/save failures, broken references, editing locks, skill groups, numeric settings,
preview wording/order, education/certifications, and save/reload preservation.
A contract test compares the frontend's skill catalogue with the Python service,
including all tag sources, original labels, punctuation, and Unicode whitespace.
They use Node when available or macOS's system JavaScriptCore;
these runtime tests are skipped if neither runtime is installed. They do not
exercise browser layout, native controls, keyboard focus or accessibility.

## My Current CV builder (Phase 5)

Use the workspace navigation to open **My Current CV**. The builder loads the
saved bank and CV separately and keeps its draft independent from bank-editor
edits. Choose a role or project, then select its original achievements or
contributions. Duplicate selections are excluded. Use Remove, Move Up and Move
Down controls to change selections and order; unavailable selections remain
visible. Bullet dropdowns allow replacing an unavailable bullet in place.
Replacing a missing role/project explicitly clears its old bullet selections.

Create skills groups with your own headings and rename them directly in the
heading fields. Groups and selected skills can be removed and moved up/down.
Headings must be nonblank and unique after case/whitespace normalisation. Skill
dropdowns combine all explicit bank tags using the backend catalogue's source
order and first-label rule. They show original labels, keep C/C++/C# distinct,
and exclude skills already selected anywhere in the CV. Unavailable skills stay
visible and can be removed or replaced in place; grouping never changes the bank.

Tailoring settings accept nonnegative whole numbers or a blank input for null
(no limit). Zero means exclude that content from future automated tailoring.
These preferences do not truncate or otherwise change manual selections or the
preview. Invalid input blocks saving until corrected; valid numbers must be
representable exactly as JavaScript integers.

The read-only preview follows draft order and resolves labels, metadata and
bullet wording from the saved bank, with placeholders for unavailable references.
Education and certifications display all bank records in bank order. Preview
text is never stored in the CV document. It is a simple screen preview, without
PDF/Word formatting, export or automated tailoring.

**Save Current CV** refreshes the saved bank, then submits the entire CV to PUT
for final reference validation. Editing is locked during saving. Failed saves
preserve the draft; failed loads disable saving and never create an empty replacement. Retry
loading reads data only and does not repair or overwrite corrupt files. A saved
bank change refreshes the builder's labels/options without resetting its draft.

Manually check the following using separate temporary stores:

```bash
cv_check_dir=$(mktemp -d)
EXPERIENCE_BANK_PATH="$cv_check_dir/experience_bank.json" \
CURRENT_CV_PATH="$cv_check_dir/current_cv.json" \
  .venv/bin/python -m uvicorn app.main:app --port 8001
```

- At `http://127.0.0.1:8001`, save fictional roles/projects with several bullets
  in the bank editor. In My Current CV, add selections, check parent-specific
  options and duplicates, reorder them, save and reload the browser.
- Check both navigation buttons, keyboard controls, focus after moves, long
  bullet text, and the layout on a narrow screen.
- Save a CV, return to the bank editor, and delete or move a selected record.
  Return to the builder: selections must remain visible with warnings. Remove
  or replace them and save again.
- Use developer tools to block `/current-cv` before a fresh page load. Saving
  must remain disabled. Unblock the request and retry loading.
- Make an unsaved CV edit, go offline and attempt to save. The draft must remain
  intact. Restore networking and retry loading before saving again.
- In the bank editor, change one unrelated field and save. Check that untouched
  achievements, contribution text, tags and education/certification IDs remain
  unchanged, including multiline wording and comma-containing skill labels.
- Add, rename, remove and reorder skills groups; move and replace skills. Check
  duplicate prevention across groups, then save and reload to verify ordering.
- Delete a selected skill from every bank source and save the bank. Confirm
  builder and preview placeholders persist until you remove or replace it.
- Try blank, zero and positive settings; try negative, fractional and incomplete
  numeric input. Invalid values must block saving, and zero must not remove any
  manually selected content from the builder or preview.
- Check preview order, multiline bullet wording, skills labels, all education
  and certifications, and safe literal display of HTML-like source text.

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

## Local storage and Current CV limitations

- Intended for local, single-user use with one editing tab/process. Multiple
  tabs or concurrent API writes can overwrite each other's edits; there is no
  locking, revision check or transaction spanning the bank and CV files.
- Atomic replacement protects against failed writes before replacement, but is
  not a backup or power-loss durability guarantee. Back up both files manually.
- The bank is the live source of truth: editing text under the same ID updates
  the preview; deleting/moving records breaks references until explicitly fixed.
  Skill keys are normalised names, so substantive renames can break selections.
- The browser accepts exactly representable integers up to 9,007,199,254,740,991;
  the API accepts larger nonnegative integers. Unsafe imported limits block UI
  saving until corrected instead of being silently rounded and re-saved.
- Drafts are held in memory until an explicit save. Reloading/closing after
  dismissing the unsaved-changes warning loses those edits. Navigation between
  the application's views preserves drafts.
- The preview has a fixed section order and displays all bank education and
  certifications. There is no PDF/Word export or automated tailoring.

Automated coverage includes a frontend-generated selection document validated
by the actual FastAPI endpoints and persisted/reloaded through temporary JSON
repositories. The browser checklist above is still required before calling the
release fully verified: mocked DOM tests do not verify native controls, layout,
keyboard behavior or screen-reader announcements. Optional UI improvements,
such as denser layouts or additional focus polish, are separate from correctness.

Before committing, run `python -m pytest -q`, `git diff --check` and
`git status --short --untracked-files=all`. Confirm `data/`, `.env*`, caches and
temporary files are ignored and none are already tracked. The standard
`experience_bank.json` and `current_cv.json` filenames are ignored anywhere;
fictional `examples/experience_bank.example.json` remains eligible for Git.
Commit source, tests and documentation only; do not force-add private files.

## Matching and editor limitations

- Intended for local, single-user use. No authentication or concurrent-edit
  protection. Atomic replacement is not a backup or power-loss durability guarantee.
- PUT is a full replacement. Education/certification renaming in the text editor
  can regenerate IDs. Dates and links have no semantic validation.
- Qualification extraction is probabilistic. Structured alternatives and
  importance are preserved; ambiguous legacy alternatives remain conservative.
- Complex negation, ambiguous degree wording, and joint multi-degree requirements
  are intentionally not fully interpreted. Phrase rules can miss valid evidence.
- Strong support describes supported CV relevance, not measured proficiency.
  Explicit activity constraints require demonstrated activity; unconstrained
  capability wording can remain lexical. Missing evidence does not prove missing experience.
- Match references omit dates and separate outcomes; the original bank retains them.
- Dependency versions are currently unpinned; installations may differ over time.

Automated CV content selection, CV rewriting, PDF/DOCX export, and multi-user
storage remain outside V3.2.

## Technical relationship catalogue — V3.2.1

`app/data/technical_relationships.json` is curated application configuration,
independent of the user's experience bank and Current CV. The matcher loads and
validates it before evaluating relationships; Current CV skill selection remains
independent.
The Git ignore rules allow this specific catalogue file while keeping other
`app/data/` contents and saved user JSON files ignored.

The JSON has three required sections: integer `schema_version: 1`, a `concepts`
object keyed by stable identifiers, and a `relationships` list. The initial
catalogue contains 11 concepts and 10 directed relationships covering Azure,
Azure AI Search, AWS, cloud technologies, FastAPI, Python, API/backend development,
Oracle Database, relational databases and SQL.

Concept IDs are lowercase names with single spaces; letters, digits, `+`, `#`
and `.` are supported so technologies such as C, C++ and C# remain distinct.
Each concept has a `kind` of `technology` or `capability` and optional equivalent
`aliases`. Resolution compares complete names with case-insensitive, collapsed
whitespace while retaining punctuation and original alias text. Bare `Oracle`
is deliberately not an alias for Oracle Database.

Each relationship contains `from` and `to` concept IDs, `type` (`broader`,
`transferable` or `uses_language`), `confidence` (`high` or `medium`) and optional
`strong_when` (`technology_usage`, `api_development` or null). Confidence describes
the curated relationship, not candidate proficiency or a compatibility score.
`strong_when` records a condition for strong support during matching; null or omission
means the relationship cannot establish strong support by itself. Conditions
are permitted only for `broader` relationships and are never evaluated on load.
No edge establishes deployment, cloud architecture or production operations.

Use `load_technical_relationships()` from `app/services/technical_relationships.py`
to load the checked-in catalogue, or supply a path to validate another file.
`resolve_concept(name)` resolves exact IDs/aliases; `relationships_from(id)`
returns only explicit outgoing edges in file order. Unknown IDs raise `KeyError`.
Reverse edges and multi-hop relationships are never inferred. Azure-to-AWS and
AWS-to-Azure are separately recorded transferable relationships, not aliases.
For JSON serialization, use `catalogue.model_dump(by_alias=True)`.

The loader raises `TechnicalRelationshipCatalogueError` with the path and cause
for missing/unreadable files, malformed JSON, duplicate JSON keys, unsupported
versions or values, alias collisions (including collisions with IDs), invalid
endpoints, self-relationships and duplicate `(from, to, type)` edges. Changing
confidence or conditions does not make a duplicate edge valid. Unknown fields
are rejected at every level. Nothing silently falls back to an empty catalogue.

Current CV skill keys and labels continue to come exclusively from explicit bank
tags through `build_skill_catalogue()` and its frontend counterpart. Loading or
querying technical relationships does not add inferred selectable skills, read
user JSON stores or write either document. V3.2.4 evaluates the activity conditions
against local bank evidence during matching.

## Structured requirement preparation — V3.2.2

`JobDescriptionAnalysis` still accepts and returns the original five fields.
It additionally accepts an optional `requirements` list of `StructuredRequirement`
records. An absent or null list preserves legacy behavior and is omitted from
serialized responses; an explicitly empty list means there are no requirements.

Each structured record has a nonblank `id`, `text` and `source_text`, a category
(`skill`, `other_keyword`, `responsibility` or `qualification`), importance
(`required`, `preferred` or `unspecified`), a nonempty ordered `alternatives` list
and an optional controlled `activity`. Importance defaults to `unspecified`;
activity defaults to null. Supported activities are `technology_usage`,
`api_development` and `cloud_deployment`. Activities are constraints evaluated
against evidence during matching; preparation does not infer them.

For example, one grouped requirement can be supplied without legacy lists:

```json
{
  "job_title": "Backend Engineer",
  "requirements": [
    {
      "id": "r1",
      "text": "Python or Java",
      "source_text": "Experience with Python or Java is required.",
      "category": "skill",
      "importance": "required",
      "alternatives": ["Python", "Java"],
      "activity": null
    }
  ]
}
```

Structured records are authoritative. Omitted legacy lists are derived by taking
each record's `text` in order into its category's list. A grouped OR remains one
display string; alternatives are never expanded into independent obligations.
Explicitly supplied legacy lists must match this exact projection, including
order, wording and empty categories, or validation fails. Separate Python and
Java requirements use separate records. Unknown record fields, blank wording,
empty alternatives, duplicate IDs (including whitespace variants), invalid
categories/importance and unsupported activities are rejected. Source wording is
preserved verbatim; this model alone cannot verify it against a job description.

`prepare_requirements(job)` in `app/services/requirements.py` returns independent
structured records without mutating the analysis. When the structured list is
present, legacy lists are not prepared again. Equivalent concise aliases and
flat OR groups are deduplicated, retaining the first record's ID, wording and
alternative order. Category, importance, activity and substantive display
qualifiers remain part of identity. Required/preferred AWS and AWS usage/deployment
therefore remain distinct. The original analysis retains all source occurrences,
including those whose prepared records were deduplicated.

For legacy input, preparation follows V2 order: qualifications, technical skills,
other keywords, then responsibilities. It reuses the matcher's existing exact
alias canonicalisation and qualification-first, cross-category deduplication.
IDs such as `legacy:technical_skills:1` are deterministic within that analysis.
Importance is `unspecified`, activity is null and `source_text` is the available
extracted string; the original job-description quote cannot be recovered.

Only an explicit OR between complete names from a small technology allowlist is
split (for example, Python or Java, or JS or TS). Unknown alternatives, slashes,
conjunctions, qualifiers, responsibilities and qualifications retain their whole
string as one opaque option. Degree alternatives and C#/.NET compounds retain
their existing V2 interpretation. This is not a Boolean-expression parser.

The matcher consumes prepared requirements for both structured and legacy
requests, supplying catalogue-aware equivalent names.
Preparation itself does not load or traverse relationships. Shared V2 terminology
is in `app/services/matching_terms.py`, avoiding a circular matcher import.
Current CV skill selection and saved
JSON stores remain unaffected.

## Structured job extraction — V3.2.3

An isolated [extraction evaluation harness](evaluations/extraction/README.md)
compares the current prompt, a shorter prompt and explicitly selected compatible
models against three reviewed expectation fixtures. It defaults to an offline
plan; live requests require --live. Reports include named requirement errors,
provider content, Python projection, model/prompt metadata and token usage.
This tooling does not change production extraction or matching.

`analyse_job_description_with_llm()` now requests `JobDescriptionExtraction`,
containing only `job_title` and `requirements`. Each `ExtractedRequirement` shares
the existing requirement content validation, has explicit importance and nullable
activity, and contains no ID. Unknown fields, including independently generated
legacy lists or IDs, are rejected. The existing OpenAI model configuration and
Chat Completions parsing API are retained.

The prompt marks required/preferred only from explicit wording or a clear
requirements-section heading; otherwise importance is unspecified. Duties remain
responsibilities rather than invented required prior experience. Simple OR options
stay grouped; independent AND obligations are separate. Complete degree branches
retain their level/subject pairs. Shared or nested ambiguous alternatives retain
full original wording as one opaque option. Activities must be explicitly
expressed; a bare Azure or cloud mention cannot imply cloud deployment. If a job
title is not stated, the prompt uses `Unspecified role`.

Following manual extraction review, the prompt asks for coverage of every
paragraph and sentence, including future duties in introductory role descriptions
and `You will` paragraphs. Desirable or nonessential requirements must not be
omitted; explicit preference wording determines preferred importance. Distinct
duties in a shared sentence stay separate, while actions linked by purpose stay
combined. Multiple alternatives require genuine source-supported OR choices;
each other requirement has one complete meaningful option. A concise example
contrasts Python/Java choices with collaborating to design software solutions.
Activities must describe the specific requirement's own action and be supported
by its own `source_text`; another sentence, paragraph or duty in a shared quotation
cannot supply an activity. Preferred AWS/Azure experience retains null activity
when its quote does not express an activity; separately stated cloud deployment
is a responsibility, without inventing required previous deployment experience.
These are prompt instructions, not a new semantic validator; mocked regression
tests verify application contracts, and live model quality still needs manual
verification.

`analysis_from_extraction()` in `app/services/job_extraction.py` verifies quotations,
assigns `r1`, `r2`, etc. in provider order, and constructs `JobDescriptionAnalysis`.
Its existing projection derives the four legacy lists using each requirement's
display text and category, preserving order and grouped alternatives. There is
no separate legacy generation or source-occurrence deduplication. Extraction does
not evaluate bank evidence.
IDs are deterministic for the same ordered extraction, not guaranteed across
different model interpretations of the same description.

Source verification requires a contiguous sequence of original-input tokens.
Case, whitespace, typographic apostrophes and separating punctuation can differ;
technical punctuation such as C/C++/C#, .NET, Node.js and version numbers is retained.
Words cannot be reordered or omitted inside a quotation, OR cannot become AND,
and paraphrases or fabricated quotations have no fuzzy fallback. Exact quotes
are preserved; formatting-tolerant matches return an actual original-input span.
An unverified quote fails the whole analysis through `LLMServiceError` and the
existing generic 502 response; no partial response or guessed quotation is saved.

This check establishes lexical provenance, not whether the model interpreted
importance, category, alternatives or activities correctly, or captured enough
context around a quoted fragment. Repeated wording under different headings can
still be ambiguous. The extraction prompt asks for sufficient context, but manual
review of representative real descriptions remains necessary. Automated tests use
mocked OpenAI outputs; they do not assess live model extraction quality or make
provider calls. Matching evaluates the resulting analysis separately from
extraction and does not change the Current CV or frontend.

### Diagnosing analysis failures

The HTTP response remains the generic 502 message. The server now emits a
`Job analysis failed` warning identifying configuration, provider, provider-response,
structured-validation or source-validation failures. Provider status and known
error codes/parameter names, schema field paths/error types, or an analysis-local
requirement ID identify the failed step. The warnings exclude job-description
text, extracted quotations, keys, provider bodies and exception tracebacks.

For example, `stage=source_validation ... requirement_id=r6` means the sixth
extracted quotation failed the existing contiguous-source check. It does not
prove a provider outage or justify accepting invented wording. After a 502,
inspect the accompanying warning rather than only the Uvicorn access-log line.
No retry, partial-analysis fallback or relaxed validation is introduced.

## Matching integration — V3.2.4

match_experience_bank() loads the validated catalogue and calls
prepare_requirements(). A present structured list, including an empty one, is
authoritative; legacy lists are never matched independently as extra obligations.
Legacy five-field requests are adapted conservatively. Qualifications keep their
legacy precedence, and aliases still deduplicate without collapsing different
importance, category, activity or substantive display qualifiers.

Each requirement is evaluated per evidence record and per OR alternative. The
strongest supported alternative is retained for that record. Demonstrated,
relevant activity takes precedence over declarations within the same status;
otherwise ties keep option order. One result is returned for the whole group, with no missing results for
unused choices. Separate AND records remain independent. Each evidence record
earns at most one existing 10/3-point reward per prepared requirement. Importance
is metadata and does not change the weights. Scores are internal evidence
coverage, not a candidate/job compatibility score.

_direct_decision() preserves V2 phrase aliases, token boundaries, denials,
testing/testability, LLM-integration and compound/qualification protections.
Technology wording without actual use, and explicit local technology tags
without supporting wording, are related rather than strong. Tags are retained
unchanged. This intentionally tightens the old child-tag classification.
Capability tags can have strong support when the same record actually demonstrates
the capability; a backend tag on a frontend-only bullet remains related.

_relationship_decision() follows only explicit outgoing edges from observed
concepts to the requested concept. Transferable and uses-language edges are
always related. A broader edge becomes strong only with its approved same-record
activity condition. Relationship confidence remains catalogue metadata. No edge
establishes deployment, architecture or production operations.

Azure AI Search is not an alias for Azure. The Azure name inside that service can
provide scoped, related wording support for an Azure alternative. Practical
service use supports general cloud technologies through the explicit broader
edge. The catalogue has no Azure AI Search → Azure → AWS traversal: service usage
alone does not establish AWS relevance via an invented chain.

matching_activity.py splits positive local action/object clauses and checks the
three controlled activities. Technology use needs the specific name in positive
usage wording. API development requires building/designing/implementing/maintaining
APIs, rather than consuming an API, building a client or maintaining documentation.
Cloud deployment requires a completed application/service deployment and an
explicit cloud destination. Activity and technology/destination cannot be borrowed
from separate clauses, outcomes or unrelated records. A named-platform deployment
can supply related activity relevance through an explicit transferable edge,
without claiming that the requested platform was used.

An explicit activity constraint with no supporting activity is missing, even
when a technology tag exists. Credentials provide knowledge relevance for
unconstrained technical requirements and suitable support for formal qualification
requirements; they cannot establish engineering activity. Degree alternatives
retain their level/subject pairings and require education evidence; named
professional certifications require certification evidence.

Signal origins distinguish original wording, outcomes, standalone skills, local
skill/technology tags and credentials. Evidence references retain source type,
record ID and label, distinguishing achievements, project contributions, parent
descriptions, education and certifications. Parent claims never propagate to
children. EvidenceSupport is reused in requirement and ranked-evidence outputs,
so scores and explanations follow the same per-requirement decisions.

The controlled seven-requirement GPT-5.4 regression uses fictional bank records.
It verifies Python OR Java, practical Oracle Database → relational database support,
Azure as the selected cloud alternative, separate future duties and the existing
BSc Computer Science qualification match. Tests exercise weaker declarations,
credentials, unsupported activities, directionality and multi-hop rejection too.
No live provider call or saved-user-data migration is involved.

Limits remain explicit: phrase/activity rules are deliberately conservative,
unfamiliar phrasing can be missed, only curated relationships apply, and complex
Boolean requirements, general qualification equivalence and natural-language
negation are not fully parsed. No CV content selection, rewriting, exports,
frontend redesign, new persistence or inferred selectable CV skills are included.

### Matching-quality improvements — V3.2.5

Completed SQL stored-procedure development in Oracle is recognised as explicit
database work even when the sentence uses the shorter vendor name. This narrow
contextual rule requires a development action, a database artifact and Oracle
in the same positive clause. It supplies wording provenance for the existing
Oracle Database → relational databases edge and its technology_usage condition.
It does not add a global Oracle alias or promote tag-only or credential evidence.
SQL itself is direct language evidence only when stated in the development wording;
the uses-language edge alone remains related.

For a simple development-and-maintenance API responsibility, demonstrated API
development provides strong CV relevance to the main development capability.
The explanation explicitly says when API maintenance is not established, and
the supporting signal records API development rather than the complete unproven
duty. Maintenance-only requirements and extra quality claims are not upgraded.
The same behavior applies to structured responsibilities and legacy strings.
Production API endpoints are recognised as API objects; this does not imply
cloud deployment.

Collaboration and software design in separate records are not combined into
collaborative design. Generic Agile wording, job titles and team membership
cannot establish that combined responsibility. Local Python technology tags
remain related discovery signals. Future CV selection must distinguish those
declarations from demonstrated achievements and avoid repetitive tag-driven
content; this review does not change ranking weights or implement selection.

The completed manual review of the seven-requirement description against the
reviewed Experience Bank produced 4 strong, 1 related and 2 missing requirements.
That result depends on the recorded bank evidence; it is not a universal expected
result for other banks or a guarantee of future live extraction quality.
