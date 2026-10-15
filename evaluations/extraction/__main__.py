"""Run with python -m evaluations.extraction; no provider calls without --live."""

import argparse
from contextlib import nullcontext
from itertools import product
import json
import math
from pathlib import Path
import sys

import openai

from app.models import JobDescriptionExtraction
from app.services.llm import Settings
from evaluations.extraction.harness import FIXTURES, PROMPTS, digest, load_fixtures, run_case, summarise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, help="Compatible Chat Completions model; repeat to compare.")
    parser.add_argument("--prompt", action="append", choices=list(PROMPTS), help="Default: current and simple.")
    parser.add_argument("--case", action="append", help="Fixture ID; default: all three.")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--live", action="store_true", help="Make paid API requests. Otherwise print an offline plan.")
    parser.add_argument("--output", type=Path, help="Create a new JSON report; existing files are never overwritten.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args(argv)
    if args.repeats < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Repeats and timeout must be positive.")
    models = list(dict.fromkeys(args.model))
    variants = list(dict.fromkeys(args.prompt or PROMPTS))
    if any(not model.strip() for model in models):
        parser.error("Model names must be nonblank.")
    rates = (args.input_usd_per_million, args.output_usd_per_million)
    prices = None
    if any(rate is not None for rate in rates):
        if any(rate is None or not math.isfinite(rate) or rate < 0 for rate in rates) or len(models) != 1:
            parser.error("Supply both nonnegative finite rates for exactly one model.")
        prices = rates
    suite = load_fixtures(args.fixtures)
    unknown = set(args.case or []) - {case.id for case in suite.cases}
    if unknown:
        parser.error(f"Unknown fixture IDs: {sorted(unknown)}")
    cases = [case for case in suite.cases if not args.case or case.id in args.case]
    report = {
        "report_version": 1, "mode": "live" if args.live else "dry_run",
        "sdk_version": openai.__version__,
        "request_count": len(models) * len(variants) * len(cases) * args.repeats,
        "models": models, "prompts": {name: PROMPTS[name] for name in variants},
        "fixtures_sha256": digest(args.fixtures.read_text(encoding="utf-8")),
        "fixtures": [case.model_dump() for case in cases],
        "schema_sha256": digest(json.dumps(JobDescriptionExtraction.model_json_schema(), sort_keys=True)),
        "request_options": {"timeout_seconds": args.timeout, "max_retries": 0,
                            "generation_parameters": "provider defaults, matching production"},
        "cost_rates_usd_per_million": None if prices is None else {"input": prices[0], "output": prices[1]},
        "cost_note": "Optional estimate uses uncached input rates; no automatic pricing lookup. Missing usage is unknown, not free.",
        "records": [], "summary": [],
    }
    # Exclusive creation also prevents accidental replacement of saved user JSON.
    try:
        output = args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout)
    except OSError as error:
        parser.error(f"Cannot create a new output file ({type(error).__name__}).")
    with output as stream:
        if args.live:
            try:
                settings = Settings()
                client = openai.OpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=args.timeout)
            except Exception as error:
                # Never let Pydantic/SDK configuration diagnostics reveal credentials.
                parser.error(f"Live configuration unavailable ({type(error).__name__}).")
            print(f"Running {report['request_count']} live requests; no automatic retries.", file=sys.stderr)
            with client:
                for model, variant, case, repeat in product(models, variants, cases, range(1, args.repeats + 1)):
                    print(f"{model} / {variant} / {case.id} / repeat {repeat}", file=sys.stderr)
                    report["records"].append(run_case(client, case, model, variant, repeat, prices))
            report["summary"] = summarise(report["records"])
        json.dump(report, stream, indent=2)
        stream.write("\n")
    # Low quality is a recorded result, not a CLI failure; provider/validation errors are failures.
    return int(any(row["status"] != "ok" for row in report["records"]))


if __name__ == "__main__":
    raise SystemExit(main())
