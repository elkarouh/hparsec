"""Checks that follow variables and return codes across lines, ported from the ksh checkers.

ZSH052  a variable is used but never assigned in the file (ksh rule 16)
ZSH053  a variable is assigned but never used (ksh rule 17)
ZSH054  a read-only or environment-owned variable is assigned (ksh rule 20)
ZSH055  $? is tested right after a pipe into tee (ksh rule 23)
ZSH056  $? is tested right after typeset VAR=$(...) (ksh rule 24)
ZSH057  $? is tested after a call to a function that uses exit (ksh rule 25)

These are heuristics, as in the ksh checkers: a name counts as assigned if it appears
in any assignment form anywhere in the file, whatever the order. Comments are blanked
with the tokenizer, so line and column numbers match the file.
"""

import re

from style_rules import _code_lines, _Pos

# Names the environment, the shell or the site sets before the script runs (ksh rule 21).
EXEMPT = frozenset({
    "APPLICATION_INSTANCE_KEY", "CFMU_TEMP_DIR", "CM_ROOT", "CM_SYSTEM", "PATCHES_DIR", "PATH",
    "PWD", "TMP_ROOT", "WORK_DIR", "WORK_ROOT", "DATA_FILES", "SHARED_AREA", "SVLOGS",
    "CMA_WORKSPACE_ROOT", "CMA_WORKSPACE_DATA_DIRECTORY", "CMA_WORKSPACE",
    "CMA_WORKSPACE_NM_REPOSITORY_DIRECTORY", "GCOV_PREFIX", "CLEARCASE_ROOT",
    "SCRIPT", "DISPLAY", "ENABLE_UPDATE_STATISTICS", "TZ", "PS1", "PS2", "IFS", "SECONDS",
    "OPTARG", "OPTIND", "REPLY", "PS3", "NF",
})

# zsh adaptation, not in the ksh checker: variables that a login shell or a terminal normally
# provides. Without this list most zsh configs would report HOME, OSTYPE and the like.
LOGIN_ENV = frozenset({
    "HOME", "USER", "LOGNAME", "SHELL", "TERM", "OSTYPE", "MACHTYPE", "HOST", "HOSTNAME", "EDITOR",
    "VISUAL", "PAGER", "LANG", "LC_ALL", "LC_CTYPE", "LESS", "TMUX", "TMPDIR", "TTY", "DISPLAY",
    "WAYLAND_DISPLAY", "SSH_CONNECTION", "SSH_TTY", "COLUMNS", "LINES", "ZSH_VERSION", "ZDOTDIR",
    "BASH_VERSION", "HISTFILE", "HISTSIZE", "SAVEHIST", "USERNAME", "PWD", "OLDPWD",
})
_PREFIXES = ("XDG_", "LC_", "ZSH", "ZPLUG", "ANTIGEN")


def _is_env(name):
    return name in LOGIN_ENV or name.startswith(_PREFIXES)


# Set by define_configuration; they may be assigned only in a file whose name has that word.
DEFINE_CONFIGURATION = frozenset({
    "PHYSICAL_SERVERS", "SYSTEM_LOCATION", "LOCAL_STATIONS", "SYSTEM_TEMPLATE", "OTHER_INSTANCE",
    "CONFIGURATION_SYSTEM", "CONFIGURATION_TYPE", "APPLICATION", "DB_FUNCTION", "ENTERPRISE_ID",
    "ENV_UPDATE_USER", "ENV_UPDATE_USER_PASSWD", "EXER_TITLE", "REFERENCE_INSTANCE",
    "PHYSICAL_HOSTS_ALL", "PACKAGE_NAME", "HOSTS_ALL", "SYSTEM_PAIR",
})

# ksh read-only variables, and the ones a sudo login sets (ksh rule 20).
KSH_READ_ONLY = frozenset({
    "EGID", "ENV", "EUID", "GID", "HISTCMD", "LINENO", "PPID", "RANDOM", "TTYIDLE", "UID",
    "USERNAME", "SUDO_COMMAND", "SUDO_USER", "SUDO_UID", "SUDO_GID",
})

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
# Forms that assign a name: NAME=, export NAME=, read [-opt] NAME, for NAME in, select NAME in,
# getopts STRING NAME, set -A NAME, typeset -A|-a NAME, NAME[i]=, and inline NAME=after a space.
_ASSIGN = [
    re.compile(r"(?:^|(?<=[\s;(&|{]))(" + _NAME + r")(?=\[[^\]]*\])?=", re.M),
    re.compile(r"\bfor\s+(" + _NAME + r")\s+in\b"),
    re.compile(r"\bselect\s+(" + _NAME + r")\s+in\b"),
    re.compile(r"\bread\s+(?:-\w+\s+(?:\S+\s+)?)*(" + _NAME + r")"),
    re.compile(r"\bgetopts\s+\S+\s+(" + _NAME + r")"),
    re.compile(r"\bset\s+-[aA]\s+(" + _NAME + r")"),
    re.compile(r"\b(?:typeset|integer|local)\s+(?:-\w+\s+)*(" + _NAME + r")"),
]
_USE = [
    re.compile(r"\$(" + _NAME + r")"),
    re.compile(r"\$\{(" + _NAME + r")(?=[}#%:/\-+=?,^])"),
]
_ARITH = re.compile(r"\(\((.*?)\)\)")
# A bare name in arithmetic. $+name and name[...] are lookups in an associative or hash array.
_IDENT = re.compile(r"(?<![\w$+])(" + _NAME + r")(?![\w\[(])")
_NO_ASSIGN_LINE = re.compile(r"^\s*(alias|zstyle|bindkey|setopt|unsetopt|compdef|autoload|zmodload)\b")
_EXPORT = re.compile(r"\bexport\s+((?:\w+(?:=\S*)?\s*)+)")


def _assigned_names(text):
    if _NO_ASSIGN_LINE.match(text):
        return set()
    names = set()
    for pat in _ASSIGN:
        for m in pat.finditer(text):
            # A name after an option word is an option value, as in --build-arg NAME=value.
            if re.search(r"(^|\s)--[\w-]+\s+$", text[:m.start(1)]):
                continue
            names.add(m.group(1))
    return names


def _used_names(text):
    names = set()
    for pat in _USE:
        for m in pat.finditer(text):
            names.add(m.group(1))
    # Names inside (( )) and $(( )) are read as numbers, without a $.
    for arith in _ARITH.finditer(text):
        inside = re.sub(r"\[[^\]]*\]", "", arith.group(1))  # subscripts are keys, not variables
        names.update(_IDENT.findall(inside))
    return names


def _exported_names(lines):
    names = set()
    for text in lines:
        for m in _EXPORT.finditer(text):
            names.update(w.split("=")[0] for w in m.group(1).split())
    return names


def _variable_issues(lines, source, filename):
    assigned_at, used_at = {}, {}
    exported = _exported_names(lines)
    for n, text in enumerate(lines, 1):
        for name in _assigned_names(text):
            assigned_at.setdefault(name, (n, text.find(name)))
        for name in _used_names(text):
            used_at.setdefault(name, (n, text.find("$" + name)))
    found = []
    for name, (n, col) in sorted(used_at.items(), key=lambda kv: kv[1]):
        if (name in assigned_at or name in EXEMPT or name in KSH_READ_ONLY or name in DEFINE_CONFIGURATION
                or _is_env(name)):
            continue
        found.append(("ZSH052", f"'{name}' is used but not assigned in this file; it may be set elsewhere.",
                      n, max(col, 0)))
    for name, (n, col) in sorted(assigned_at.items(), key=lambda kv: kv[1]):
        if name not in used_at and name not in EXEMPT and name not in exported and not _is_env(name):
            found.append(("ZSH053", f"'{name}' is assigned but never used; remove it or check it is exported.",
                          n, max(col, 0)))
        if name in KSH_READ_ONLY:
            found.append(("ZSH054", f"'{name}' is a read-only shell variable; assigning it is likely a bug.",
                          n, max(col, 0)))
        elif name in DEFINE_CONFIGURATION and not re.search(r"define_configuration", filename):
            found.append(("ZSH054", f"'{name}' is set by define_configuration; do not assign it here.",
                          n, max(col, 0)))
    return found


def _return_code_issues(lines):
    found = []
    previous = None
    for n, text in enumerate(lines, 1):
        if text.strip():
            if "$?" in text and previous is not None:
                _, prev_n, prev_text = previous
                if re.search(r"[|]\s*tee\s", prev_text):
                    found.append(("ZSH055", f"Testing $? after a pipe into tee (line {prev_n}); "
                                            "it is the return code of tee, not of the command.", n, text.find("$?")))
                if re.search(r"typeset.*=\$\(", prev_text):
                    found.append(("ZSH056", f"Testing $? after typeset VAR=$(...) (line {prev_n}); "
                                            "it is the return code of typeset. Assign, then typeset.",
                                  n, text.find("$?")))
                for fn in _exit_functions:
                    if re.search(r"(^|[^\w-])" + re.escape(fn) + r"($|[^\w-])", prev_text):
                        found.append(("ZSH057", f"'{fn}' calls exit, which ends the script; use return "
                                                f"in functions, or do not test $? after it.",
                                      n, text.find("$?")))
                        break
            previous = (text, n, text)
    return found


def _exit_functions_in(lines):
    """Names of functions whose body contains exit (brace depth tracked, as in the ksh checker)."""
    names, depth, current, start = set(), 0, None, 0
    for text in lines:
        m = re.match(r"\s*function\s+(" + _NAME + r")", text) or re.match(r"\s*(" + _NAME + r")\s*\(\s*\)", text)
        if m and current is None:
            current, start = m.group(1), depth
        if current and re.search(r"\bexit\b", text):
            names.add(current)
        depth += text.count("{") - text.count("}")
        if current and depth <= start and "}" in text:
            current = None
    return names


_exit_functions = frozenset()


def flow_issues(source, filename=""):
    """Issues from the variable and return-code checks."""
    global _exit_functions
    lines = _code_lines(source)
    _exit_functions = frozenset(_exit_functions_in(lines))
    issues = []
    for code, message, line, col in _variable_issues(lines, source, filename) + _return_code_issues(lines):
        issues.append({"rule": code, "message": message, "token": _Pos(line, col)})
    return issues
