# JobMatch CV Tailor — V3.1

JobMatch CV Tailor is a local FastAPI application for maintaining an experience
bank, manually assembling a Current CV, and analysing job descriptions against
the entire bank. V3.1 adds ordered CV selections, skills groups, future tailoring
preferences and a live preview. Original achievements and contributions are
selected by reference; the application does not generate or rewrite their text.

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

## V3.1 limitations and release checks

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

## Retained V2 matching/editor limitations

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
