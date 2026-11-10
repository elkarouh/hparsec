#!/usr/bin/env python3
"""Count how often a lint rule fires across a codebase.

Usage:
    python count_rule.py RULE PATH [PATH ...]

RULE is a rule id such as ZSH008. Each PATH is a file, or a directory that is
searched recursively for *.zsh, *.sh and *.bash files. Prints the number of
findings per file, then a total. Files that fail to parse are listed
separately, since their findings are unknown.

Needs the library on the path, e.g. PYTHONPATH=src from the repository root.

Example, counting here-strings (ZSH008):
    PYTHONPATH=/path/to/hparsec/src python count_rule.py ZSH008 ~/dotfiles ~/projects
"""
import argparse
import os
import sys

from zsh_linter import lint_zsh_code

SUFFIXES = (".zsh", ".sh", ".bash")


def iter_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".git")]
                for name in sorted(files):
                    if name.endswith(SUFFIXES):
                        yield os.path.join(root, name)
        else:
            yield path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rule", help="rule id to count, e.g. ZSH008")
    ap.add_argument("paths", nargs="+", help="files or directories to scan")
    args = ap.parse_args()

    total = 0
    unparsed = []
    for path in iter_files(args.paths):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            issues = lint_zsh_code(source)
        except Exception as exc:  # parse failure: count is unknown
            unparsed.append((path, type(exc).__name__))
            continue
        hits = [i for i in issues if i["rule"] == args.rule]
        if hits:
            total += len(hits)
            print(f"{len(hits):5d}  {path}")

    print(f"\n{total} x {args.rule}")
    if unparsed:
        print(f"\n{len(unparsed)} file(s) could not be parsed:", file=sys.stderr)
        for path, kind in unparsed:
            print(f"  {path} ({kind})", file=sys.stderr)


if __name__ == "__main__":
    main()
