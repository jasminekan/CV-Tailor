# Isolated extraction evaluation

Compare extraction quality without changing `/analyse`, matching or saved data.
The `current` variant imports the production prompt verbatim; `simple` uses
`simple_prompt.txt`. Both request `JobDescriptionExtraction` through the same SDK
structured parsing API. Expected answers and requirement IDs are never sent.

## Fixtures

`fixtures.json` contains three synthetic descriptions and 22 authored expectations:

| Case | Items | Coverage |
| --- | ---: | --- |
| `software_engineer_intro` | 7 | Introductory API duty, language/cloud OR groups, preferred degree, combined collaboration and separate deployment |
| `backend_independent_languages` | 7 | Python AND Java, Oracle usage, preferred FastAPI, API/testing duties and paired degree branches |
| `full_stack_search_and_cloud` | 8 | Introductory duties, JavaScript/TypeScript, Azure AI Search, preferred cloud platforms, communication, certification and deployment |

The first case preserves the manually reviewed seven-item acceptance criteria.
The other two still need domain review before use as release gates. These are
authored expectations, not an independently annotated gold-standard dataset.
Review categories, importance, activities, quotes and alternatives against the
source; do not adjust expectations merely to make an output pass.

`match_terms` identifies content using required groups of approved wording;
`option_aliases` permits equivalent options, and `accepted_alternative_sets`
permits complete alternative representations. `review_notes` explains choices.
The loader validates metadata, IDs, canonical quotes and matching anchors without
using the Experience Bank or technical relationship catalogue.

## Run comparisons

From the repository root, with the virtual environment active, inspect an offline
plan without reading credentials or calling OpenAI:

```bash
python -m evaluations.extraction --model gpt-4o-mini --repeats 3
```

This plans both prompts over three cases: 18 requests if run live. Set `--model`
explicitly to your configured production model; the CLI does not select it from
`.env`. Live runs use the existing API-key configuration and require `--live`:

```bash
python -m evaluations.extraction --live --model gpt-4o-mini --prompt current --repeats 3 --output /tmp/jobmatch-current.json
python -m evaluations.extraction --live --model gpt-4o-mini --prompt simple --repeats 3 --output /tmp/jobmatch-simple.json
# Replace COMPATIBLE_MODEL with a more capable model supporting the same parsing API.
python -m evaluations.extraction --live --model COMPATIBLE_MODEL --prompt current --repeats 3 --output /tmp/jobmatch-stronger.json
```

Each command makes nine requests. Repeat `--model` or `--prompt` to form a matrix;
two models and two prompts with three repeats make 36 requests. Use
`--case software_engineer_intro` for one case, or `--fixtures PATH` for a reviewed
custom suite of at least three cases. `--timeout` defaults to 60 seconds per request;
there are no automatic retries or repair calls. Generation uses provider defaults,
as production does; defaults can differ across models.

Output paths must be new. Without `--output`, JSON goes to stdout; progress goes
to stderr. Keep generated reports in `/tmp` or ignored
`evaluations/extraction/reports/`. Reports include descriptions and provider
output, so private-description reports must remain local. Offline tests never
make provider requests.

## Evaluate results

Reports retain requested/resolved model, prompt variant/hash, repeat, timestamp,
duration, finish reason, token usage/details, extraction and projected analysis.
Prompt/fixture snapshots, schema/fixture hashes and SDK version identify the run.
Compare equivalent cases, repeats and hashes before comparing results.

Each evaluation names missing, duplicated, unexpected and merged requirements,
and incorrect category, importance, alternatives or activity with expected/actual
values. Content identity is independent of category/importance and never uses
the source quote: quoting two duties does not establish extraction of both.

Completeness counts expected requirements identified as separate items;
duplicates do not improve it. Merged independent items remain missing in their
separate form. Split OR options are missing as a group and their fragments are
unexpected. Alternative comparison tolerates order and harmless formatting but
retains duplicate choices, degree pairings and unreviewed terminology differences.

Metadata accuracy is measured on matched items, with counts and denominators.
Read it alongside completeness. `fully_correct / attempts` requires successful
source validation and every quality check; `completeness_on_evaluated` excludes
attempts without usable output, with `evaluated_attempts` exposing that coverage.
Statuses distinguish provider errors, refusal, missing output, schema errors,
source errors and valid analysis. Source errors retain extraction and semantic
evaluation but no projected analysis or fully-correct credit. Error metadata
excludes credentials, raw provider error bodies and refusal text.

Exit code **1** means provider/validation failure, **2** means argument errors,
and **0** means evaluations completed, even when extraction quality checks fail.
JSON validity alone is not extraction correctness.

Token totals and availability counts support approximate cost comparison;
missing usage is unknown. For one model, optionally supply both
`--input-usd-per-million` and `--output-usd-per-million` using verified rates.
Reports retain those rates and estimate uncached-input cost for available usage.
Caching, service tiers and discounts are not priced automatically; no price
lookup or hardcoded pricing is used.

## Interpretation and verification

Better results from the simple prompt suggest prompt complexity merits review;
better results from a stronger model suggest capability merits review. Inspect
grouping, qualifications and activities alongside completeness, tokens and latency.
Content absent from provider extraction was omitted before Python processing;
content lost from projected lists suggests a projection issue.

Three small cases and stochastic repeats cannot prove causality or production
reliability. Conservative phrase matching can flag valid unfamiliar paraphrases;
approve variants manually. The harness does not fully check negation, invented
duration or every qualifier. Source validation establishes lexical provenance,
not semantic correctness or completeness.

```bash
python -m pytest -q tests/test_extraction_evaluation.py
```

Tests cover controlled omission/grouping failures, fixtures, comparison, usage,
source failures and opt-in execution. They do not establish live model quality.
