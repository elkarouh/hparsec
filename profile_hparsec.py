#!/usr/bin/env python3
"""Profile hparsec's direct left-recursive expression parser.

Usage:
    python profile_hparsec.py --source-dir . --terms 3000

The source directory must contain hparsec.py and ady_tokenizer.py.
Tokenization is deliberately excluded from the cProfile measurements.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", default=".",
                    help="directory containing hparsec.py and ady_tokenizer.py")
    ap.add_argument("--terms", type=int, default=3000,
                    help="number of numeric terms in the expression")
    ap.add_argument("--limit", type=int, default=30,
                    help="number of profile entries to display")
    args = ap.parse_args()
    if args.terms < 1:
        ap.error("--terms must be at least 1")

    sys.path.insert(0, str(Path(args.source_dir).resolve()))
    from hparsec import Input, NUMBER, PLUS, ParserState, fw

    # expr ::= expr '+' NUMBER | NUMBER
    expr = fw("expr")
    globals()["expr"] = expr
    expr = (expr + PLUS + NUMBER) | NUMBER
    globals()["expr"] = expr

    source = "+".join(["1"] * args.terms)
    ParserState.reset()
    stream = Input(source)  # Keep tokenization outside the profile.

    profiler = cProfile.Profile()
    profiler.enable()
    result = expr.parse(stream)
    profiler.disable()

    if not result or stream.pos != 2 * args.terms:
        raise SystemExit(
            f"parse failed or input not fully consumed: position={stream.pos}, "
            f"expected={2 * args.terms}"
        )

    print(f"Parsed {args.terms:,} terms ({len(stream.tokens):,} tokens).")
    print(f"Memo entries: {len(stream.memos):,}\n")
    for sort_key in ("cumtime", "tottime"):
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats(
            sort_key
        ).print_stats(args.limit)
        print(f"--- Sorted by {sort_key} ---")
        print(output.getvalue())


if __name__ == "__main__":
    main()
