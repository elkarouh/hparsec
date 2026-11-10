"""Line-level style rules ported from the ksh checker scripts.

Each rule is a regular expression, or a small function, that runs on the script with
comments blanked out. Comments are found with the tokenizer, so line and column numbers
still match the original file. Findings use the same issue shape as the AST rules, so
zsh_linter.main() prints them the same way.

Rules that duplicate an existing rule (ksh [ ] and <<< and backticks) or that conflict
with an auto-fix (ZSH009 braces for variables) are not here. Rules that need data
flow across lines (variables assigned before use, return codes) are not here either.
"""

import re

from zsh_tokenizer import tokenize_zsh, TOKEN_TYPES


class _Pos:
    """A token-like object: main() reads only .start for the location."""
    __slots__ = ("start",)

    def __init__(self, line, col):
        self.start = (line, col)


def _code_lines(source):
    """Source lines with every comment replaced by blanks (line numbers kept)."""
    lines = source.split("\n")
    for tok in tokenize_zsh(source):
        if tok.type == TOKEN_TYPES["COMMENT"]:
            line, col = tok.start
            text = lines[line - 1]
            lines[line - 1] = text[:col] + " " * len(tok.string) + text[col + len(tok.string):]
    return lines


def _regex_rule(rule, pattern, message, flags=0, skip=None):
    compiled = re.compile(pattern, flags)

    def run(lines, source):
        found = []
        for n, text in enumerate(lines, 1):
            if skip and skip(text, source):
                continue
            for m in compiled.finditer(text):
                found.append((rule, message, n, m.start()))
                break
        return found
    return run


def _not_awk_perl(text, source):
    return bool(re.search(r"awk|perl", text))


def _trailing_blank(lines, source):
    # Uses the original text: a blank before a comment is still a trailing blank.
    return [("ZSH021", "Remove the trailing blank(s).", n, len(t.rstrip(" \t")))
            for n, t in enumerate(source.split("\n"), 1) if t != t.rstrip(" \t")]


def _tab_char(lines, source):
    return [("ZSH044", "Use spaces, not a tab character.", n, t.index("\t"))
            for n, t in enumerate(lines, 1) if "\t" in t]


def _dollar_star(lines, source):
    return [("ZSH023", "Use $@ instead of $*, unless this is documented.", n, m.start())
            for n, t in enumerate(lines, 1) for m in re.finditer(r"\$\*|\$\{\*\}", t)]


def _nf_shell_var(lines, source):
    found = [("ZSH029", "Do not use ${NF} as a shell variable; NF is an awk field.", n, m.start())
             for n, t in enumerate(lines, 1) for m in re.finditer(r"\$\{NF\}", t)]
    if not re.search(r"\bawk\b", source):
        found += [("ZSH029", "Do not use $NF in a script that does not call awk.", n, m.start())
                  for n, t in enumerate(lines, 1) for m in re.finditer(r"\$NF\b", t)]
    return found


def _tee_stderr(lines, source):
    return [("ZSH030", "Redirect stderr before tee (e.g. cmd 2>&1 | tee f), so the file holds it.",
             n, m.start())
            for n, t in enumerate(lines, 1) for m in re.finditer(r"tee.*2>&1", t)][:1]


def _cd_dash(lines, source):
    return [("ZSH042", "Use cd \"${OLDPWD}\" instead of cd -; cd - prints the directory.",
             n, m.start())
            for n, t in enumerate(lines, 1) for m in re.finditer(r"(?<![\w-])cd\s+-", t)]


def _tr_unquoted(lines, source):
    found = []
    for n, t in enumerate(lines, 1):
        if "-tr" in t:
            continue
        m = re.search(r"(?<!\w)tr\s+(?:(?:-d|-s)\s+)*\s*([^-\"'\s])", t)
        if m:
            found.append(("ZSH043", "Quote the arguments of tr so the shell does not expand them.",
                          n, m.start()))
    return found


def _ftps_unquoted(lines, source):
    found = []
    for n, t in enumerate(lines, 1):
        if any(w in t for w in ("-sequence", "-period", "-free_text", "-source_key")):
            continue
        for cmd, skip in (("cfmu_ftps_list", 1), ("cfmu_ftps_get", 3)):
            m = re.search(cmd + r"(\s+\S+){%d}\s+([^\"'\s\\])" % skip, t)
            if m:
                found.append(("ZSH045",
                              f"Quote the file mask of {cmd}, or it is resolved locally.",
                              n, m.start()))
                break
    return found


def _bmw_awk(lines, source):
    return [("ZSH046", "Use bmw -V VAR instead of bmw VAR | awk to read a value.", n, m.start())
            for n, t in enumerate(lines, 1)
            for m in re.finditer(r"bmw\s.*\|\s*awk\s.*print \$[2N]", t)]


RULES = (
    # test constructs
    _regex_rule("ZSH010", r"\b(if|while|elif)\s+test\s",
                "Use [[ ... ]] instead of test in a condition."),
    _regex_rule("ZSH011", r"\[\[.*[=!]=?\s*(\"\"|'')|\[\[.*(\"\"|'')\s*!?=",
                "Use -z or -n instead of comparing with an empty string."),
    _regex_rule("ZSH012", r"\bif\b.*!\s*-[nz]\s",
                "Use -z instead of ! -n, or -n instead of ! -z."),
    _regex_rule("ZSH013", r"\[.*!\s\$.*\s(-eq|-ne|!=|=)\s",
                "Use the opposite operator instead of negating a comparison."),
    _regex_rule("ZSH014", r"\[\[.*\s(-[nz])\s+\w",
                "Put $ before the variable name in this -n or -z test."),
    _regex_rule("ZSH015", r"(?<![$@:=,])\{[A-Za-z]", "Put $ before the variable name in braces.",
                skip=_not_awk_perl),
    _regex_rule("ZSH016", r"\$\{[A-Za-z0-9_]*\s+[^\s}]*\}",
                "No whitespace is allowed in a variable name in ${...}."),
    _regex_rule("ZSH017", r"[<>=]\s+\d+\s+\]\]",
                "Use -lt, -le, -gt, -ge, -eq or -ne to compare numbers."),
    _regex_rule("ZSH018", r"typeset\s+-i\s+.*=$",
                "Give typeset -i an explicit value, e.g. typeset -i N=0."),
    _regex_rule("ZSH019", r">>\s*&", "Use >& to duplicate a file descriptor; one > is enough."),
    _regex_rule("ZSH020", r"\bwc\s+\|\s*awk\b", "Use wc -l, wc -w or wc -c instead of wc | awk."),
    _trailing_blank,
    _regex_rule("ZSH022", r"\$\{[0-9?@#*$!-]\}(?![A-Za-z0-9_])",
                "Write $0, $1, $?, $@, $* and the like without braces."),
    _dollar_star,
    _nf_shell_var,
    _tee_stderr,
    _regex_rule("ZSH031", r"^\s*\$\{[A-Za-z_]\w*\}\s*=",
                "${VAR}=value is not a valid shell assignment; write VAR=value.",
                skip=lambda t, s: "&&" in t or "||" in t or "]]" in t),
    _regex_rule("ZSH032", r"\]\]\s+(&&|\|\|)\s+\[\[",
                "Combine the tests into one [[ ... ]] with && or ||."),
    _regex_rule("ZSH033", r"^\s*[A-Za-z]\w*\s*\(\s*\)",
                "Declare a function with the function keyword: function NAME."),
    _regex_rule("ZSH034", r"/.*\.\$\(cm_where", "Use ! instead of . to separate SUBSYSTEM and VERSION in a path."),
    _regex_rule("ZSH035", r"2>&1\s*>", "Redirect 2>&1 after > file, not before it."),
    _regex_rule("ZSH036", r"Log\b[^|]*>\s*&2", "Log already writes to stderr; remove >&2."),
    _regex_rule("ZSH037", r"Log\s.*\b(INFO|WARNING|SEVERE|ERROR|FATAL)\b",
                "Pass a level to Log with -i, -w, -s or -f.",
                skip=lambda t, s: bool(re.search(r"Log\s+-[iwsf]|Log\s+-t\s+\d*\s*-[iwsf]", t))),
    _regex_rule("ZSH038", r"\by/n\b", "Use the confirm script instead of asking y/n.",
                flags=re.IGNORECASE),
    _cd_dash,
    _tr_unquoted,
    _ftps_unquoted,
    _bmw_awk,
    _regex_rule("ZSH040", r"Log\s.*\s[\"']$", "Remove the trailing blank(s) from the Log message."),
    _regex_rule("ZSH041", r"alias_get.*Value", "Use alias_get -q."),
    _regex_rule("ZSH047", r"\.LATEST(?!_)", "Use .LATEST_GOOD instead of .LATEST."),
    _tab_char,
    _regex_rule("ZSH048", r"CFMU_OS", "CFMU_OS is probably obsolete."),
)


def style_issues(source):
    """Issues from every line-level rule, in file order within each rule."""
    lines = _code_lines(source)
    issues = []
    for rule in RULES:
        for code, message, line, col in rule(lines, source):
            issues.append({"rule": code, "message": message, "token": _Pos(line, col)})
    return issues
