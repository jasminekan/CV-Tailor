# Architecture and API reference

JobMatch separates model-assisted extraction from deterministic evidence matching
and CV content selection. The HTTP layer coordinates these steps; services do not
save documents or rewrite evidence. This document describes the current contracts
and engineering decisions. For setup and the browser workflow, see the
[README](../README.md).

## Responsibilities

| Location | Responsibility |
| --- | --- |
| `app/main.py` | Serve the frontend, validate HTTP inputs and orchestrate repositories/services |
| `app/models.py` | API contracts, saved documents, references, matching support and selection results |
| `app/services/llm.py` | OpenAI configuration, structured extraction and safe failure metadata |
| `app/services/job_extraction.py` | Verify original-source quotations, assign requirement IDs and project analysis fields |
| `app/services/requirements.py` | Prepare authoritative requirements and adapt legacy analyses |
| `app/services/matching.py` | Evaluate evidence and rank recognised requirement coverage |
| `app/services/matching_terms.py`, `matching_activity.py` | Bounded terminology, aliases and demonstrated-activity checks |
| `app/services/technical_relationships.py` | Validate and query the curated directional catalogue |
| `app/services/current_cv.py` | Build the explicit skill catalogue and validate CV references |
| `app/services/cv_candidates.py` | Discover original content and baseline membership |
| `app/services/cv_selection.py` | Select work achievements and project bundles |
| `app/services/cv_skills.py` | Select explicit skills and produce recommendation explanations |
| `app/repositories/` | Validate and persist the two JSON stores |
| `static/` | Render the workspace, editors, diagnostics and read-only preview |

## Extraction and requirement preparation

`POST /analyse` accepts a nonblank job description of 20–20,000 characters.
`llm.py` uses the OpenAI SDK's structured parsing API with
`JobDescriptionExtraction`: one job title and an ordered requirements list.
The provider does not produce record IDs or the legacy analysis lists.

Each structured requirement has:

| Field | Contract |
| --- | --- |
| `id` | Nonblank, unique within the analysis; assigned as `r1`, `r2`, … after extraction |
| `text` | Nonblank display wording |
| `source_text` | Nonblank supporting source quotation |
| `category` | `skill`, `other_keyword`, `responsibility` or `qualification` |
| `importance` | `required`, `preferred` or `unspecified` |
| `alternatives` | Nonempty ordered OR choices; a single option for a requirement without alternatives |
| `activity` | `technology_usage`, `api_development`, `cloud_deployment` or null |

Separate records represent independent obligations. Python OR Java is one
requirement; independently required Python and Java are two. Qualification
branches retain their level/subject pairings. The extraction prompt requests
only activities explicitly supported by that requirement's own source text.

Quotation verification compares contiguous tokens while retaining negation,
technical punctuation and order. Harmless case, Unicode or formatting differences
can resolve to an actual span of the original input. Unsupported quotations fail
analysis; there is no paraphrase fallback or invented source. This is a lexical
check, not a semantic guarantee that the requirement is correct or complete.
Requirement IDs depend on extraction order and are local to that analysis.

`JobDescriptionAnalysis` also exposes `technical_skills`, `other_keywords`,
`responsibilities` and `qualifications`, derived in order from the structured
records. Callers may omit these lists. If supplied alongside `requirements`, they
must exactly match the projection; contradictions return 422. An explicitly empty
requirements list is authoritative. Unknown structured-record fields, duplicate
IDs and blank entries are rejected.

For compatibility, `/match` and `/tailoring/preview` accept analyses containing
only the five legacy fields. `prepare_requirements()` adapts those in qualification,
skill, keyword and responsibility order. It supplies deterministic `legacy:…` IDs,
unspecified importance and null activity. Only familiar complete technology names
in a small explicit OR vocabulary are split; ambiguous qualifications and other
wording stay opaque. Source text is the available extracted string, since no
original job description is available to these routes for quote verification.

Preparation deduplicates equivalent concise requirements while preserving category,
importance, activity and substantive qualifiers. It keeps the first ID/wording;
the original analysis retains all extracted source occurrences. Preparation does
not match evidence, load relationships or mutate the analysis.

## Matching and provenance

`match_experience_bank()` evaluates prepared requirements against the full saved
bank, independent of what the baseline CV selects. Each result includes source
references and per-record `EvidenceSupport`, with the selected alternative,
signals, signal origins, activity/relationship details and an explanation.

| Status | Meaning |
| --- | --- |
| `strong` | Recognised direct evidence, or an approved broader relationship, supports the capability and any required activity |
| `related` | Partial, declared or transferable evidence provides relevance without establishing the full requested experience |
| `missing` | No recognised supporting evidence satisfies the requirement and its activity constraint |

Parent role/project tags do not propagate to achievements/contributions. Each
child's own text, tags and outcomes supply its evidence. Standalone skill labels
and technology declarations do not establish practical engineering activity.
Explicit local denials can override contradictory tags. Degree matching retains
recognised level/subject pairings; technical punctuation keeps C, C++ and C# distinct.
Bounded phrase matching and a small alias vocabulary avoid broad substring inference.

Each evidence record earns 10 points for each strong requirement and 3 for each
related requirement. A grouped OR contributes once. Equal scores prefer relevant
demonstrated activity, then descriptive support, then tag-only support; remaining
ties retain bank order. Scores measure recognised coverage, not proficiency, CV
writing quality or hiring probability. Read explanations for partial support,
such as API development without demonstrated maintenance.

### Curated technical relationships

`app/data/technical_relationships.json` is application configuration, separate from
personal JSON stores. It defines versioned concepts, equivalent aliases and
explicit directional relationships: `broader`, `transferable` or `uses_language`.
Only broader edges can specify a `strong_when` condition, checked against evidence
during matching. Transferable support stays related; language relationships do
not establish proficiency. No edge establishes deployment or production operations.

Concept resolution uses complete names, case folding and collapsed whitespace,
preserving punctuation. Relationships are neither reversed nor followed through
multiple hops. Azure-to-AWS transfer is a separate edge from AWS-to-Azure transfer.
The loader rejects duplicate JSON keys, alias collisions, invalid endpoints,
self-relationships, duplicate edges, unknown fields and unsupported versions.
Invalid configuration fails explicitly rather than becoming an empty catalogue.

## Saved documents and reference integrity

The Experience Bank and Current CV use separate version-1 JSON formats. Missing
files return empty validated models without creating files. Blank, corrupt or
invalid stored files fail to load; GET does not migrate or repair them. Saving
creates the directory, writes a sibling `.tmp` file and uses `os.replace()` to
replace the destination. Failed saves attempt temporary-file cleanup.

The bank contains work roles and achievements, projects and contributions,
standalone skills, education, certifications and additional evidence. IDs are
unique across all records, including nested evidence. PUT can generate omitted
IDs for new records, but saved bank records must already contain IDs. Reads never
generate changing references. Preserve IDs when editing existing records.
Unknown bank fields and unsupported versions are rejected; original valid text,
line endings, explicit tags and outcomes are retained.

The Current CV stores ordered role/project IDs, child IDs, named skill groups and
four tailoring settings. It stores no copied bullet text. Duplicate references,
duplicate group names and duplicate skill keys are rejected. Reference validation
distinguishes a missing child from one owned by a different parent, and reports
all issues in CV order without moving or repairing content.

`build_skill_catalogue()` collects only explicit bank labels: standalone skills,
role tags, achievement tags, project tags, contribution tags, certification skills
and additional-evidence tags. Keys use lowercase and collapsed whitespace, while
the first original label and source traversal order are retained. Punctuation
remains meaningful. Matching aliases do not change the stored key catalogue;
wording, titles and relationship targets cannot create selectable skills.

| Tailoring setting | Scope |
| --- | --- |
| `max_achievements_per_role` | Achievements for each retained work role |
| `max_contributions_per_project` | Contributions within each selected project |
| `max_projects` | Total selected projects |
| `max_skills` | Total selected skills across all groups |

Settings accept nonnegative integers or null. Null is unbounded, zero selects
none of that content, and positive values are ceilings rather than quotas. They
govern automated selection, without truncating manual baseline selections.

Storage paths are configured at application import from process environment
variables; see the [README configuration table](../README.md#run-locally).
The application rejects overlapping bank/CV destination and temporary paths at
startup. File replacement is atomic per store, but there is no cross-store
transaction, revision token, writer lock or automatic backup. Custom paths must
be kept outside tracked content or under the ignored local data directory.

## Content selection

`build_cv_candidates(bank, current_cv)` makes independent snapshots of validated
documents. It preserves original source records, bank positions, baseline
membership, settings and reference issues without ranking or applying limits.

| Candidate content | Eligibility |
| --- | --- |
| Work roles | Valid baseline roles only, in baseline order; other roles remain review-only |
| Achievements | All original children of those valid baseline roles |
| Projects/contributions | All bank projects and their own contributions |
| Skills | Existing entries from the explicit skill catalogue |
| Education/certifications | Original bank-order references, outside competitive selection |
| Additional evidence | Available to matching and review, without assignment to a CV role/project |

`select_work_and_projects()` uses individual evidence support, rather than a
requirement's bank-wide status or aggregate rank. It deduplicates repeated support
for the same evidence/requirement pair and never parses explanatory prose to
invent relevance. Formal qualifications do not become competitive bullet support.

Within each retained role, a greedy first pass prefers new strong coverage,
related-to-strong improvement, new meaningful related coverage and better evidence
quality. Demonstrated activity precedes wording-only support; required precedes
unspecified then preferred at equivalent quality. Baseline position, bank position
and source ID resolve remaining ties. A second pass retains nonduplicate baseline
bullets in remaining capacity. Unrelated or declaration-only new bullets do not
fill unused slots. Baseline bullets retain their reading order; alternatives
follow in bank order.

Role summaries stay on the role's own ID and are not treated as achievements.
Projects then compete as bundles of their description and capped contributions,
recomputing marginal coverage against selected work/projects after each choice.
New projects need meaningful coverage improvement; existing projects can remain
for context. Descriptions never become contribution claims. A project may be
supported by its description even when its contribution limit is zero.

Duplicate suppression operates within one parent. It compares normalised wording,
technical tokens, support, technologies and outcomes conservatively, preserving
meaningful punctuation, numerical changes and different outcomes. Displayed text
is never normalised or rewritten. This greedy policy preserves career breadth;
it does not claim a globally optimal combination.

`select_cv_content()` delegates work/project selection, then chooses explicit
skills. It prioritises uncovered required skill names, skill-specific demonstrated
evidence, supporting technologies associated with selected content, other relevant
skills and finally valid baseline skills. Equivalent aliases select one original
entry; they do not create another skill. A selected required declaration can still
lack practical proof, which the recommendation explains.

Original skill group names/order remain. New skills use an unambiguous existing
group when equivalent baseline membership identifies one; otherwise they use an
`Additional skills` group. No technology taxonomy is inferred. Empty proposed
groups disappear, and stale selections remain reported as issues.

Decisions expose selected state, baseline membership, source/parent IDs, original
text, reason codes, marginal requirement IDs, importance and the original support
records. Reasons distinguish coverage gains, baseline retention, limits,
duplicates, declaration-only support, unavailable references and absent relevance.
Education/certifications receive unchanged-credential decisions. No outcome is
appended to a bullet and no new CV prose is generated.

Bank matching, selected work/project coverage and selected skill labels remain
separate concepts. `coverage_scope` is `work_and_projects`; a strong qualification
can appear in Education while its work/project coverage is `not_selected`.
Limits never relabel the bank-wide matching status. Old matching results lacking
per-record metadata produce warnings rather than guessed support.

## API

Interactive request/response schemas are available at `/docs` and `/openapi.json`.

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/` | Browser frontend |
| GET | `/health` | `{"status":"ok"}` |
| POST | `/analyse` | OpenAI extraction from `{"job_description":"…"}` |
| GET | `/experience-bank` | Validated saved bank, or empty defaults if absent |
| PUT | `/experience-bank` | Validate and replace the entire configured bank |
| GET | `/current-cv` | `{"current_cv":{…},"reference_issues":[…]}` |
| PUT | `/current-cv` | Validate and replace a raw Current CV document |
| POST | `/match` | Match `{"job_analysis":{…}}` against the saved bank |
| POST | `/tailoring/preview` | Recommend original CV content using the same request wrapper |

POST/PUT bodies use JSON and `Content-Type: application/json`. Invalid request
models return 422. Caught analysis failures return 502. Repository failures or an
invalid relationship catalogue return 503 with generic messages. Internal paths
and provider error bodies are not returned in those service errors.

### Matching without OpenAI

This fictional structured analysis works with `/match` or `/tailoring/preview`
without calling the extraction service:

```bash
curl -X POST http://127.0.0.1:8000/match \
  -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{
  "job_analysis": {
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
}
JSON
```

The response contains `job_title`, `strong_matches`, `related_matches`,
`missing_requirements` and `ranked_evidence`. Requirement results retain structured
details and per-record support; ranked records reuse the same support decisions.
Results depend on the configured saved bank, which may be empty.

### Current CV reads and saves

GET reports broken references with 200 while retaining saved selections and order.
Both stores must be readable. PUT accepts the raw CV document, not the GET
envelope, and validates references against the current saved bank before saving.
Invalid references return 422 with each issue's path, reference and reason in
`detail`.

A successful PUT returns the saved document. It does not require loading the
previous CV and never updates the bank. Invalid submissions and failed saves
preserve the previous destination file.

### Preview response and snapshot boundary

The preview route loads each store once, loads one validated relationship
catalogue, builds candidates, matches the same bank snapshot and calls the
selector with that catalogue. It calls no provider and invokes no repository save.

| Field | Meaning |
| --- | --- |
| `proposed_cv` | Existing Current CV reference structure with proposed selections and unchanged settings |
| `decisions` | Original wording, source identity, selection state, reasons and provenance |
| `matching_result` | Full bank-wide matching result |
| `coverage`, `coverage_scope` | Bank status alongside selected work/project support |
| `skill_coverage` | Selected explicit skill keys relevant to each requirement |
| `source_bank` | Complete original bank snapshot, including omitted content |
| `education_ids`, `certification_ids` | Unchanged credential references |
| `reference_issues`, `warnings` | Unavailable/wrong-parent selections and controlled warnings |

The browser resolves proposed IDs against `source_bank`, without fetching a
different bank revision. `source_bank` contains all input bank content, not only
selected CV content. Existing stale references return 200 with issue metadata;
they are not repaired. An empty baseline introduces no work roles, but relevant
projects and explicit skills remain eligible. Missing stores are not created.

Repeat previews are deterministic for unchanged analysis, bank, baseline and
catalogue snapshots. Live extraction is outside that guarantee. A returned preview
does not track later edits, and its response does not establish a transaction
across both stores.

## Frontend state and verification

`app.js` owns analysis, matching and the bank editor. `current_cv.js` owns the
baseline draft and preview. `tailoring_preview.js` renders read-only selections
and explanations. `workspace.js` controls destinations and stages, with feature
events carrying readiness and request revisions. Navigation itself does not save.

Job-description edits invalidate later stages. New Analysis clears the job
session after confirmation when content would be discarded, preserving management
drafts. Request versions ignore late successes, errors and cleanup from obsolete
analysis/match/preview requests; provider work already in flight is not cancelled.
Management saves lock conflicting controls and preserve drafts after failure.

Tailored previews use saved data, excluding unsaved management edits. They never
apply proposals to My CV. Source text renders through text nodes, and project
links appear as text rather than executable URLs. Browser sessions and drafts
are held in memory rather than browser storage.

The automated suite uses fictional fixtures, temporary persistence and mocked
OpenAI responses. JavaScript harnesses execute the real scripts with mocked DOM
and network objects when Node or JavaScriptCore is available. Static safety
checks complement them. These do not verify browser layout, keyboard focus or
assistive-technology behaviour.

Run offline tests with `python -m pytest -q`. The isolated
[extraction evaluation harness](../evaluations/extraction/README.md) documents
synthetic comparison fixtures, offline dry runs and separate opt-in live runs;
its small fixture set does not establish general model quality.
