"""Run the zsh linter over a corpus, printing context on failure."""
import glob, os, re, sys, traceback
from zsh_linter import lint_zsh_code


def run_corpus(directory="corpus", verbose=False):
    paths = sorted(
        glob.glob(os.path.join(directory, "*.zsh"))
        + glob.glob(os.path.join(directory, "*.sh"))
        + glob.glob(os.path.join(directory, ".zsh*"))
    )
    if not paths:
        print(f"No files in {directory}/")
        return

    ok = 0
    fail_paths = []
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except Exception as e:
            print(f"READ FAIL {path}: {e}")
            continue
        lines = src.splitlines()
        try:
            issues = lint_zsh_code(src)
            ok += 1
            print(f"OK   {path}  ({len(issues)} warnings)")
            if verbose:
                for v in issues:
                    pos = getattr(v["token"], "start", "?")
                    print(f"       [{v['rule']}] {pos}: {v['message'][:70]}")
        except SyntaxError as e:
            fail_paths.append((path, str(e)))
            print(f"\nFAIL {path}")
            print(f"     {e}")
            m = re.search(r"position \((\d+), (\d+)\)", str(e))
            if m:
                ln, col = int(m.group(1)), int(m.group(2))
                start = max(0, ln - 5)
                end = min(len(lines), ln + 3)
                print(f"     --- lines {start+1}-{end} (>> marks failure) ---")
                for i in range(start, end):
                    marker = ">>" if i == ln - 1 else "  "
                    print(f"     {marker} {i+1:5d} | {lines[i]}")
            print()
        except Exception as e:
            fail_paths.append((path, f"{type(e).__name__}: {e}"))
            print(f"\nFAIL {path}: {type(e).__name__}: {e}")
            if verbose:
                traceback.print_exc()

    print(f"\n=== {ok}/{len(paths)} parsed ({100*ok//len(paths) if paths else 0}%) ===")
    if fail_paths:
        print("\nFirst-token summary:")
        buckets = {}
        for path, msg in fail_paths:
            mm = re.search(r"Unexpected token '([^']*)'", msg)
            tok = mm.group(1) if mm else "?"
            buckets.setdefault(tok, []).append(os.path.basename(path))
        for tok, files in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(files):3d}  {tok!r:15}  e.g. {files[0]}")


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "corpus"
    verbose = "-v" in sys.argv
    run_corpus(directory, verbose=verbose)