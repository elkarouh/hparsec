"""Lint every script in a corpus directory and report how many parse.

Usage:
    python corpus_test.py [DIR] [-v]

-v lists each finding. The exit status is 1 if any script fails to parse.
"""
import argparse
import glob
import os
import sys

from zsh_linter import lint_zsh_code

DEFAULT_CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def corpus_files(directory):
    patterns = ("*.zsh", "*.sh", ".zsh*")
    return sorted(p for pat in patterns for p in glob.glob(os.path.join(directory, pat)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?", default=DEFAULT_CORPUS)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    paths = corpus_files(args.directory)
    if not paths:
        print(f"No files in {args.directory}/")
        return 1

    parsed = 0
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        try:
            issues = lint_zsh_code(source)
        except Exception as exc:
            print(f"FAIL {path}: {type(exc).__name__}: {exc}")
            continue
        parsed += 1
        print(f"OK   {path}  ({len(issues)} warnings)")
        if args.verbose:
            for issue in issues:
                start = getattr(issue["token"], "start", None)
                print(f"       {issue['rule']} {start}: {issue['message'][:70]}")

    print(f"\n=== {parsed}/{len(paths)} parsed ({100 * parsed // len(paths)}%) ===")
    return 0 if parsed == len(paths) else 1


if __name__ == "__main__":
    sys.exit(main())
