#!/usr/bin/env python3
"""Benchmark hparsec left recursion against an equivalent repetition grammar.

By default the library is loaded from the repository's src/ directory; pass
--source-dir to point at another copy of hek_parsec.py and hek_tokenize.py.

The benchmark excludes tokenization from the reported parse time and checks
that every expression token was consumed.
"""
from __future__ import annotations

import argparse
import gc
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

DEFAULT_SOURCE_DIR = Path(__file__).resolve().parent.parent / "src"


def build_grammars():
    from hek_parsec import Input, NUMBER, PLUS, ParserState, fw

    # expr ::= expr '+' NUMBER | NUMBER
    lr_expr = fw("lr_expr")
    globals()["lr_expr"] = lr_expr
    lr_expr = (lr_expr + PLUS + NUMBER) | NUMBER
    globals()["lr_expr"] = lr_expr

    # Same language, expressed without left recursion:
    # expr ::= NUMBER ('+' NUMBER)*
    flat_expr = NUMBER + (PLUS + NUMBER)[:]
    return Input, ParserState, lr_expr, flat_expr


def one_run(parser, n, Input, ParserState, measure_memory=False):
    source = "+".join(["1"] * n)
    ParserState.reset()

    start = time.perf_counter()
    stream = Input(source)
    tokenize_seconds = time.perf_counter() - start

    if measure_memory:
        tracemalloc.start()

    start = time.perf_counter()
    result = parser.parse(stream)
    parse_seconds = time.perf_counter() - start

    peak_bytes = None
    if measure_memory:
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    if not result:
        raise RuntimeError(f"parse failed for {n} terms")
    if stream.pos != 2 * n:
        raise RuntimeError(
            f"parser consumed {stream.pos} tokens; expected {2*n} expression tokens"
        )

    return {
        "tokenize": tokenize_seconds,
        "parse": parse_seconds,
        "tokens": len(stream.tokens),
        "memo_entries": len(stream.memos),
        "peak_bytes": peak_bytes,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="directory containing hparsec modules")
    ap.add_argument("--sizes", nargs="+", type=int,
                    default=[100, 1000, 5000, 10000])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--memory-at", type=int, default=5000,
                    help="also measure traced peak parse memory at this size; 0 disables")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.source_dir).resolve()))

    Input, ParserState, lr_expr, flat_expr = build_grammars()
    print("terms grammar         tokenize(s) parse median(s) memo entries peak parse memory")

    for n in args.sizes:
        for name, parser in (("left-recursive", lr_expr), ("flat-repeat", flat_expr)):
            timings = []
            last = None
            for _ in range(args.repeat):
                gc.collect()
                last = one_run(parser, n, Input, ParserState)
                timings.append(last["parse"])
            memory = "-"
            if args.memory_at == n:
                gc.collect()
                mem = one_run(parser, n, Input, ParserState, measure_memory=True)
                memory = f"{mem['peak_bytes'] / 1024 / 1024:.2f} MiB"
                last = mem
            print(
                f"{n:>5} {name:<16} {last['tokenize']:>10.4f} "
                f"{statistics.median(timings):>14.4f} "
                f"{last['memo_entries']:>12} {memory:>18}"
            )


if __name__ == "__main__":
    main()
