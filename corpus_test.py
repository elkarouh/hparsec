"""Run the zsh linter over a corpus of real scripts and report coverage."""

import glob
import os
import sys
import traceback

from zsh_linter5 import lint_zsh_code


def run_corpus(directory="corpus", verbose=False):
    paths = sorted(
        glob.glob(os.path.join(directory, "*.zsh"))
        + glob.glob(os.path.join(directory, ".zsh*"))
        + glob.glob(os.path.join(directory, "*.sh"))
    )
    if not paths:
        print(f"No files found in {directory}/")
        print("Create a corpus/ directory and drop .zsh/.zshrc files into it.")
        return

    ok = 0
    parse_fail = 0
    lint_ok = 0
    fail_paths = []

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as e:
            print(f"READ FAIL {path}: {e}")
            continue

        try:
            issues = lint_zsh_code(source)
            ok += 1
            lint_ok += 1
            if verbose and issues:
                print(f"OK   {path}  ({len(issues)} warning(s))")
                for v in issues:
                    pos = getattr(v["token"], "start", "?")
                    print(f"       [{v['rule']}] {pos}: {v['message'][:60]}")
            else:
                print(f"OK   {path}  ({len(issues)} warning(s))")
        except SyntaxError as e:
            parse_fail += 1
            fail_paths.append((path, str(e)))
            if verbose:
                print(f"FAIL {path}: {e}")
        except Exception as e:
            parse_fail += 1
            fail_paths.append((path, f"{type(e).__name__}: {e}"))
            if verbose:
                print(f"FAIL {path}: {type(e).__name__}: {e}")
                traceback.print_exc()

    total = ok + parse_fail
    print()
    print(f"=== {ok}/{total} parsed ({100*ok//total if total else 0}%) ===")
    print(f"    {lint_ok} of those produced lint output")

    if fail_paths:
        print()
        print("=== First-token failure summary ===")
        buckets = {}
        for path, msg in fail_paths:
            # extract "Unexpected token 'X'" or "Invalid character 'X'"
            token = "?"
            if "Unexpected token" in msg:
                token = msg.split("Unexpected token")[1].split(" ")[1].strip("'\"")
            elif "Invalid character" in msg:
                token = msg.split("Invalid character")[1].split(" ")[1].strip("'\"")
            buckets.setdefault(token, []).append(os.path.basename(path))
        for token, files in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(files):3d}  {token!r:20}  e.g. {files[0]}")


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "corpus"
    verbose = "-v" in sys.argv
    run_corpus(directory, verbose=verbose)