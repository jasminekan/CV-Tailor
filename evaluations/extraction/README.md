# Isolated extraction evaluation

This harness compares extraction quality without changing /analyse, its prompt,
its schema, matching or saved documents. It imports the current production prompt
verbatim and sends the same JobDescriptionExtraction response format for both
current and simple. The shorter prompt lives in simple_prompt.txt. No
requirements, IDs or expected results are supplied to the provider.

## Fixtures and review

fixtures.json contains three synthetic descriptions and 22 authored expectations:

| Case | Expected items | What it exercises |
| --- | ---: | --- |
| software_engineer_intro | 7 | The exact manual-review description, introductory API duty, language/cloud OR groups, preferred degree, combined collaboration and separate deployment |
| backend_independent_languages | 7 | Python AND Java, Oracle usage, preferred FastAPI, separate API/testing duties, paired degree branches |
| full_stack_search_and_cloud | 8 | Two introductory duties, JavaScript/TypeScript, Azure AI Search usage, preferred cloud platforms, communication, certification and separate deployment |

The first case preserves the user's reviewed seven-item acceptance criteria. The
two additional cases were authored and checked against their explicit wording;
they still need your domain review before becoming release gates. These are not
model-generated expectations or an independently annotated gold-standard dataset.
review_notes explains interpretive choices. Review the expected category,
importance, activity, source quote and options for each item before live runs.
Do not revise expectations merely to make a model's output pass.

Each expected item includes its complete structured content plus:

- match_terms: every group must appear in extracted display text or alternatives;
  any explicitly listed variant within a group can match.
- option_aliases: local, manually approved equivalent option wording.
- accepted_alternative_sets: additional complete valid option representations,
  such as the opaque preferred degree wording versus its two complete branches.

The fixture loader validates metadata, nonblank rules, IDs and canonical source
quotes. It checks that the authored anchors identify their canonical item. It
does not use the technical relationship catalogue, experience bank or matcher.

## Execute comparisons

Run from the repository root with the existing virtual environment. Dry runs
validate fixtures and print a plan without loading credentials or calling OpenAI:

    .venv/bin/python -B -m evaluations.extraction --model gpt-4o-mini --repeats 3

This plans both prompts over three cases: 18 requests if subsequently run live.
Use the actual configured production model for your baseline; gpt-4o-mini is
the application's default, not an automatic override of your .env selection.
Live execution uses the existing OpenAI API key configuration, but the evaluation
model is always selected explicitly with --model.

For the three comparisons, run:

    .venv/bin/python -B -m evaluations.extraction --live --model gpt-4o-mini --prompt current --repeats 3 --output /tmp/jobmatch-current.json
    .venv/bin/python -B -m evaluations.extraction --live --model gpt-4o-mini --prompt simple --repeats 3 --output /tmp/jobmatch-simple.json
    .venv/bin/python -B -m evaluations.extraction --live --model gpt-5.4-2026-03-05 --prompt current --repeats 3 --output /tmp/jobmatch-stronger.json

Each command makes nine requests. Output paths must be new; existing files are
never overwritten. Without --output, JSON goes to stdout. Progress goes to
stderr. Live comparisons require explicit execution; offline tests make no
provider requests. Keep generated reports in `/tmp` or the ignored
`evaluations/extraction/reports/` directory, creating that directory if needed.
Reports contain input descriptions and provider output; keep reports based on
private descriptions local. The harness, prompts, fixtures and regression tests
remain version-controlled source.

GPT-5.4 is an example compatible stronger-model candidate, not a production
migration recommendation. Official documentation lists [Chat Completions,
Structured Outputs and the dated snapshot](https://developers.openai.com/api/docs/models/gpt-5.4).
Access depends on your account. Use another compatible model if appropriate.
The same SDK structured parsing API is used throughout; see the [official
Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).
No new API parameters or model-specific prompt adaptations are introduced.

Repeat --model or --prompt to form a matrix. For example, both models and both
prompts with three repeats yield 36 requests and help examine interactions.
Use --case software_engineer_intro for a narrower run. --fixtures PATH
supports a reviewed custom suite of at least three cases. --timeout defaults
to 60 seconds per request; there are no automatic retries or repair calls.
Provider defaults for generation parameters match the production request, which
does not specify temperature, seed or reasoning effort. Defaults may differ
across models; that is part of this comparison, not a controlled reasoning-effort
experiment. Prefer dated model snapshots when available.

## Read results

Each record includes requested/resolved model, prompt variant and hash, repeat,
timestamp, duration, finish reason, token usage (including detailed usage fields
where supplied), provider extraction, projected legacy analysis and evaluation.
The report also contains exact prompt and fixture snapshots, SDK version and
schema/fixture hashes. Different prompt or fixture hashes are different experiments.

evaluation contains named missing requirements, incorrect fields with expected
and actual values, duplicates, unexpected extracted content and merged independent
requirements. Metadata checks identify content independently of its category and
importance, so incorrect classification cannot masquerade as a missing item.
Requirement identity never uses source_text: a quote containing two duties must
not count as extraction of both when only one appears in the actual requirement.

Completeness is the fraction of expected requirements identified as separate
items. Duplicates do not increase it. Merged independent items are reported as
missing in their expected separate form and listed under merged_requirements.
Split OR choices are missing as a group and their fragments are unexpected.
Alternative comparison ignores choice order and harmless case/punctuation but
does not discard duplicate choices, cross-pair degrees or infer unreviewed aliases.
For the reported six-item output, the named missing item is
backend_api_duty: Develop and maintain backend APIs, with completeness 6/7.

Category, importance, alternative and activity accuracy are shown for matched
items, with counts and denominators. An omitted item cannot earn metadata credit.
Always inspect completeness and errors alongside metadata accuracy. Summary
fully_correct / attempts requires successful source validation and all quality
checks, so provider refusals, malformed output and processing failures cannot
improve the apparent overall success rate. completeness_on_evaluated excludes
attempts without usable structured output; evaluated_attempts shows that coverage.

Statuses distinguish provider errors, refusal, missing output, schema error,
source error and valid analysis. Source-error records retain the provider content
and semantic checks, but no projected analysis and no fully-correct credit.
Errors use exception types and safe status/requirement IDs, without credentials,
raw provider error bodies or refusal text. JSON-valid output can still fail every
semantic check. CLI exit code is 1 for provider/validation failures, 2 for argument
errors, and 0 for completed quality evaluations even if quality checks fail.

Token totals and usage-availability counts allow cost comparisons. Missing usage
is unknown. Optionally supply both --input-usd-per-million and
--output-usd-per-million for a single selected model, using verified current
rates. Reports record the rates and calculate an approximate uncached-input cost.
They retain cached/reasoning usage detail but do not automatically price caching,
service tiers or discounts. Aggregated costs/tokens cover only attempts with
available values; availability counts expose partial totals. No pricing is
hardcoded and no price lookup occurs during evaluation.

## Interpret before production changes

Compare the same cases/repeats and inspect all per-requirement errors:

- Better completeness with the simple prompt on the same model suggests prompt
  complexity matters; ensure grouping, qualifications and activities do not regress.
- Better completeness with a stronger model on the current prompt suggests model
  capability matters; weigh tokens, latency and the other error types.
- A duty absent from provider extraction was omitted before Python processing.
  A duty present there but absent from the expected legacy list in analysis
  indicates a projection issue. A source error indicates quote-validation failure.
- Failure across both prompts and models is a reason to review the task/schema
  and fixtures; this harness alone cannot establish that the architecture is at fault.

Three small cases and a few stochastic repeats cannot prove a cause, establish
production reliability or justify a migration by themselves. Review actual JSON.
Phrase matching is deliberately conservative and may flag an unfamiliar but
correct paraphrase as missing/unexpected; do not treat it as an independent
semantic judge. Approve extra wording variants manually. It does not fully check
negation, invented duration or every qualifier; quotation validation proves
lexical provenance, not that a quotation supports an interpretation.

## Offline verification

    .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_extraction_evaluation.py
    .venv/bin/python -B -m pytest -q -p no:cacheprovider
    git diff --check

Tests cover the observed omission and metadata/grouping failures using controlled
outputs, fixture validation, deterministic comparison, punctuation boundaries,
usage/cost accounting, source failures and opt-in execution. They make no live
requests and do not prove any model's extraction quality.
