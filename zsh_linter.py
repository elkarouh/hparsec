"""Zsh linter — extended grammar for real-ish zsh scripts.

Design: one lint method per rule, attached via inner classes. Recursion is
implicit — each rule's `lint(self)` is responsible for its own subtree,
including calling `_recurse_lint` on any child that doesn't have its own
lint method.

`as_node(p)` wraps a parser in a one-alternative Choice_Parser so that `+`
doesn't flatten its contents into the parent. This is what makes `command`
appear as a distinct node inside `pipeline` (and `pipeline` inside `and_or`),
so `command.lint` fires on every command, piped or not.
"""

from hek_parsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type_node,
    filt,
    literal,
    nothing,
    ignore,
    shift,
)
from zsh_tokenizer import tokenize_zsh, TOKEN_TYPES, _RESERVED


# ============================================================
# Terminals
# ============================================================

class Terminals(Terminals):
    ASSIGN = "="
    SEMICOL = ";"
    PIPE = "|"
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    AND_AND = "&&"
    OR_OR = "||"
    DSEMI = ";;"
    SEMI_AMP = ";&"
    SEMI_BAR = ";|"
    PLUSEQUAL = "+="
    MINEQUAL = "-="

    # Visible punctuation (appear in the AST)
    lbracket = filt(lambda tok: tok.string == "[", shift, name="[")
    rbracket = filt(lambda tok: tok.string == "]", shift, name="]")
    dlbracket = filt(lambda tok: tok.string == "[[", shift, name="[[")
    drbracket = filt(lambda tok: tok.string == "]]", shift, name="]]")
    lparen_vis = filt(lambda tok: tok.string == "(", shift, name="(")
    rparen_vis = filt(lambda tok: tok.string == ")", shift, name=")")
    colon = filt(lambda tok: tok.string == ":", shift, name=":")
    flag = filt(
        lambda tok: isinstance(tok.string, str) and len(tok.string) > 1
                    and tok.string.startswith("-") and not tok.string.startswith("--"),
        expect_type_node(TOKEN_TYPES["IDENT"]),
        name="-flag",
    )

    number = expect_type_node(TOKEN_TYPES["NUMBER"])
    string = expect_type_node(TOKEN_TYPES["STRING"])
    var_exp = expect_type_node(TOKEN_TYPES["VAR_EXP"])
    arith_exp = expect_type_node(TOKEN_TYPES["ARITH_EXP"])
    cmd_subst = expect_type_node(TOKEN_TYPES["CMD_SUBST"])
    backtick = expect_type_node(TOKEN_TYPES["BACKTICK"])
    heredoc = expect_type_node(TOKEN_TYPES["HEREDOC"])
    comment = expect_type_node(TOKEN_TYPES["COMMENT"])
    newline = expect_type_node(TOKEN_TYPES["NEWLINE"])

    reserved = _RESERVED
    identifier = filt(lambda tok: tok.string not in reserved, expect_type_node(TOKEN_TYPES["IDENT"]))
    argument_identifier = expect_type_node(TOKEN_TYPES["IDENT"])

    argument = backtick | cmd_subst | arith_exp | var_exp | heredoc | string | number | argument_identifier
    statement_sep = newline | SEMICOL


# Enhance argument with glob qualifiers, subscripts, and inline assignments.
glob_qual = LPAREN + filt(lambda tok: tok.string not in ("(", ")"), shift)[:] + RPAREN
subscript = lbracket + ((~rbracket) + shift)[:] + rbracket
# glob suffix used inside case patterns: distinguishes `)` inside `(a|b)*`
# from the pattern-closing `)`.
glob_suffix = filt(lambda tok: tok.string in ("*", "?", "["), shift)

_basic_arg = (backtick | cmd_subst | arith_exp | var_exp | heredoc | string
              | number | glob_qual | subscript | argument_identifier)
# assign_word matches `name=value` as a single argument (needed for
# `alias ls='...'`, `export FOO=bar` inline, etc.)
assign_word = identifier + ignore(ASSIGN) + _basic_arg
argument = assign_word | _basic_arg

def _children(node):
    if node is None:
        return []
    if hasattr(node, "nodes") and isinstance(node.nodes, list):
        return [c for c in node.nodes if c is not None]
    if hasattr(node, "node") and node.node is not None:
        return [node.node]
    return []

def _is_several_times(node):
    return type(node).__name__ == "Several_Times"

def _token_of(node):
    """Return the deepest token/str that `node` wraps."""
    n = node
    for _ in range(20):
        if n is None:
            return None
        if isinstance(n, str):
            return n
        if hasattr(n, "string") and not hasattr(n, "nodes"):
            return n
        if hasattr(n, "node") and n.node is not n:
            n = n.node
            continue
        kids = _children(n)
        if kids:
            n = kids[0]
            continue
        return None
    return None


def _check_args(arg_node):
    """ZSH002 / ZSH003 for every leaf argument under arg_node."""
    issues = []

    def walk(node):
        if node is None:
            return
        kids = _children(node)
        if kids:
            for c in kids:
                walk(c)
            return
        tok = node if hasattr(node, "string") else _token_of(node)
        if tok is None:
            return
        val = getattr(tok, "string", None)
        if not isinstance(val, str) or not val:
            return
        if val.startswith("$") and not val.startswith("${") and not val.startswith("$(("):
            if val.startswith("$(") and val.endswith(")"):
                issues.append({"rule": "ZSH002",
                               "message": f"Unquoted command substitution '{val}' detected.",
                               "token": tok})
            else:
                issues.append({"rule": "ZSH002",
                               "message": f"Unquoted variable expansion '{val}' detected. "
                                          f"Risk of word splitting and globbing.",
                               "token": tok})
        elif val.startswith("`") and val.endswith("`"):
            issues.append({"rule": "ZSH003",
                           "message": "Prefer modern '$(...)' over legacy backticks.",
                           "token": tok})

    walk(arg_node)
    return issues


def _recurse_lint(node):
    """If `node` has a `lint` method, call it (it owns its subtree).
    Otherwise, descend into children and recurse."""
    if node is None:
        return []
    if hasattr(node, "lint"):
        return list(node.lint())
    issues = []
    for c in _children(node):
        issues.extend(_recurse_lint(c))
    return issues


def _has_wildcard_case(case_node):
    seq = []

    def walk(node):
        if node is None:
            return
        kids = _children(node)
        if kids:
            for c in kids:
                walk(c)
            return
        tok = _token_of(node)
        if tok is None:
            return
        s = tok if isinstance(tok, str) else getattr(tok, "string", None)
        if s is not None:
            seq.append(s)

    walk(case_node)
    for i in range(len(seq) - 1):
        if seq[i] == "*" and seq[i + 1] == ")":
            return True
    return False


def as_node(p):
    """Wrap parser `p` in a one-alternative Choice_Parser.

    The Choice wrapper prevents `ParserMeta.__add__` from flattening `p`'s
    `.parsers` into the parent. The wrapper returns the matched alternative's
    node directly (Choice_Parser.parse returns `m` from `p.parse`), so the AST
    contains a node of `p`'s class, not the wrapper's.
    """
    return p | p


# ============================================================
# Grammar
# ============================================================

class ZshStyleGrammar(Grammar):
    script = statement[:]

    statement = (
        comment | declaration | declaration2 | assignment
        | if_stmt
        | for_alt | for_stmt | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | function_def | anon_function | case_stmt
        | subshell | grouping
        | and_or
    ) + statement_sep[:]

    assign_op = ignore(ASSIGN) | ignore(PLUSEQUAL) | ignore(MINEQUAL)
    array_literal = LPAREN + argument[:] + RPAREN
    assign_rhs = array_literal | argument

    assign_target = identifier | number   # `0=${...}` and other numeric names

    declaration = literal("local") + flag[:] + identifier + (assign_op + assign_rhs)[0:1]
    declaration2 = (literal("typeset") | literal("declare")
                    | literal("export") | literal("readonly")) + flag[:] + identifier + (assign_op + assign_rhs)[0:1]
    assignment = assign_target + subscript[0:1] + assign_op + assign_rhs

    # [ ] and [[ ]] content is opaque — anything inside (including `=` `==`
    # `!=` `=~` `&&` `||` `<` `>`) is treated as raw tokens. ZSH004 still
    # fires on the whole node; _check_args still walks individual leaves.
    test_construct = lbracket + ((~rbracket) + shift)[:] + rbracket
    dbl_test_construct = dlbracket + ((~drbracket) + shift)[:] + drbracket

    redir_op = filt(
        lambda tok: tok.string in ("<", ">", ">>", "<<<", ">&", "<&", ">|", "&>", "&>>"),
        expect_type_node(TOKEN_TYPES["OP"]),
    )
    redir = ignore(redir_op + argument)
    command_head = identifier | colon | backtick | cmd_subst | arith_exp | var_exp | string | number
    command = assign_word[:] + command_head + argument[:] + redir[:]    
    _two_rparen = RPAREN + RPAREN
    arith_body = ((~_two_rparen) + shift)[:]
    arith_stmt = LPAREN + LPAREN + arith_body + RPAREN + RPAREN
    # as_node(command) keeps each command a distinct node inside pipelines,
    # so command.lint fires per stage instead of only on bare commands.
    pipeline = as_node(command) + (PIPE + as_node(command))[:]
    and_or_item = test_construct | dbl_test_construct | arith_stmt | pipeline
    and_or = as_node(and_or_item) + ((AND_AND | OR_OR) + as_node(and_or_item))[:]

    inner_statement = (
        comment | declaration | declaration2 | assignment
        | if_stmt
        | for_alt | for_stmt | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | function_def | anon_function | case_stmt
        | subshell | grouping
        | and_or
    ) + statement_sep[:]

    elif_branch = (
        literal("elif") + (test_construct | dbl_test_construct | arith_stmt | command) + statement_sep[:]
        + literal("then") + statement_sep[:] + inner_statement[:]
    )
    else_branch = literal("else") + statement_sep[:] + inner_statement[:]

    if_stmt = (
        literal("if") + (test_construct | dbl_test_construct | arith_stmt | command) + statement_sep[:]
        + literal("then") + statement_sep[:] + inner_statement[:]
        + elif_branch[:] + else_branch[0:1]
        + literal("fi")
    )

    for_alt = (literal("for") + identifier + LPAREN + argument[:] + RPAREN + statement_sep[:]
               + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))
    for_stmt = (literal("for") + identifier + literal("in") + argument[:] + statement_sep[:]
                + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))
    foreach_stmt = (literal("foreach") + identifier + LPAREN + argument[:] + RPAREN + statement_sep[:]
                    + inner_statement[:] + literal("end"))
    select_stmt = (literal("select") + identifier + literal("in") + argument[:] + statement_sep[:]
                   + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))

    while_stmt = (literal("while") + (test_construct | dbl_test_construct | arith_stmt | command) + statement_sep[:]
                  + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))
    until_stmt = (literal("until") + (test_construct | dbl_test_construct | arith_stmt | command) + statement_sep[:]
                  + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))
    repeat_stmt = (literal("repeat") + argument + statement_sep[:]
                   + literal("do") + statement_sep[:] + inner_statement[:] + literal("done"))

    # Case pattern: consume tokens until we hit a `)` that is NOT followed by
    # a glob modifier (`*`, `?`, `[`). That distinguishes the pattern-closing
    # `)` in `(darwin|freebsd)*)` from the `)` inside the glob group.
    case_pattern = ((~((rparen_vis + (~glob_suffix)))) + shift)[:] + rparen_vis
    case_body = case_pattern + statement_sep[:] + inner_statement[:]
    case_stmt = (
        literal("case") + argument + literal("in") + statement_sep[:]
        + (statement_sep[:] + case_body + (DSEMI | SEMI_AMP | SEMI_BAR))[:]
        + statement_sep[:] + literal("esac")
    )

    function_def = (
        (identifier + LPAREN + RPAREN)
        | (literal("function") + identifier + (LPAREN + RPAREN)[0:1])
    ) + statement_sep[:] + LBRACE + statement_sep[:] + inner_statement[:] + RBRACE

    # Anonymous function: `() { body }` — zsh-specific, defined and called
    # immediately. Must appear BEFORE subshell in the choice lists because
    # `()` alone is also a valid (empty) subshell.
    anon_function = (
        LPAREN + RPAREN
        + LBRACE + statement_sep[:] + inner_statement[:] + RBRACE
    )

    subshell = LPAREN + statement_sep[:] + inner_statement[:] + RPAREN
    grouping = LBRACE + statement_sep[:] + inner_statement[:] + RBRACE

    # ---------- Lint methods ----------
    class command:
        def lint(self):
            issues = []
            idx = 0
            while idx < len(self.nodes) and _is_several_times(self.nodes[idx]):
                idx += 1
            if idx >= len(self.nodes):
                return []
            head_tok = _token_of(self.nodes[idx])
            if head_tok is None:
                return []
            head_name = getattr(head_tok, "string", None)
            if head_name == "echo":
                issues.append({"rule": "ZSH001",
                               "message": "Prefer native 'print' or 'printf' over legacy 'echo'.",
                               "token": head_tok})
            elif head_name in ("grep", "sed", "awk"):
                issues.append({"rule": "ZSH005",
                               "message": f"External tool '{head_name}' used; prefer native zsh equivalents where possible.",
                               "token": head_tok})
            elif isinstance(head_name, str) and head_name.startswith("`") and head_name.endswith("`"):
                issues.append({"rule": "ZSH003",
                               "message": "Prefer modern '$(...)' over legacy backticks.",
                               "token": head_tok})
            if idx + 1 < len(self.nodes) and self.nodes[idx+1] is not None:
                issues.extend(_check_args(self.nodes[idx+1]))
            return issues
        
    class test_construct:
        def lint(self):
            issues = [{"rule": "ZSH004",
                       "message": "Prefer enhanced '[[ ... ]]' over legacy POSIX '[ ... ]' test construct in zsh.",
                       "token": _token_of(self.nodes[0])}]
            if len(self.nodes) > 1 and self.nodes[1] is not None:
                issues.extend(_check_args(self.nodes[1]))
            return issues

    class dbl_test_construct:
        # [[ ... ]] performs no word splitting — suppress ZSH002 for its args.
        # Also suppresses ZSH004 (this is the recommended form).
        def lint(self):
            return []   # [[ ]] does no word splitting; recommended form

    class assignment:
        def lint(self):
            if len(self.nodes) > 1 and self.nodes[-1] is not None:
                return _check_args(self.nodes[-1])
            return []

    class declaration:
        def lint(self):
            # nodes = [flag_several, ident, assign_several?]
            for n in self.nodes[1:]:
                if n is not None:
                    issues = _check_args(n)
                    if issues:
                        return issues
            return []

    class declaration2:
        def lint(self):
            for n in self.nodes[1:]:
                if n is not None:
                    issues = _check_args(n)
                    if issues:
                        return issues
            return []

    class case_stmt:
        # The case word (nodes[1]) is subject to splitting — check it.
        # Then recurse into bodies.
        def lint(self):
            issues = []
            if len(self.nodes) > 1 and self.nodes[1] is not None:
                issues.extend(_check_args(self.nodes[1]))
            # check for wildcard fallback
            if not _has_wildcard_case(self):
                issues.append({
                    "rule": "ZSH007",
                    "message": "case without a `*)` fallback — unexpected input silently ignored.",
                    "token": _token_of(self.nodes[1]) if len(self.nodes) > 1 else _token_of(self.nodes[0]),
                })
            for c in _children(self):
                issues.extend(_recurse_lint(c))
            return issues

    class script:
        def lint(self):
            issues = []
            for c in _children(self):
                issues.extend(_recurse_lint(c))
            return issues


# ============================================================
# Public entry point
# ============================================================

def lint_zsh_code(source):
    ParserState.reset()
    tokens = tokenize_zsh(source)

    result = script.parse(tokens)
    if not result:
        raise SyntaxError(f"Invalid zsh script: {source}")

    ast, stream = result
    while stream.pos < len(stream.tokens) and stream.tokens[stream.pos].type == TOKEN_TYPES["NEWLINE"]:
        stream.pos += 1

    if stream.pos < len(stream.tokens):
        tok = stream.tokens[stream.pos]
        raise SyntaxError(f"Unexpected token {tok.string!r} at position {tok.start}")

    return ast.lint()


# ============================================================
# Tests
# ============================================================

if __name__ == "__main__":
    from zsh_tokenizer import tokenize_zsh as _tk
    _arith = [(t.type, t.string) for t in _tk("count=$((count + 1))")]
    assert any(k == 3 and s == "$((count + 1))" for k, s in _arith), "ARITH_EXP split"
    _case = [(t.type, t.string) for t in _tk("case $1 in\n a) x;;\nesac\n")]
    assert any(k == 4 and s == "$1" for k, s in _case), "$1 split"
    _esc = [(t.type, t.string) for t in _tk("git log --format=%h\\ %s\n")]
    assert not any(t == 10 and s == "\\" for t, s in _esc), "escape leaked"
    _fmt = [(t.type, t.string) for t in _tk("git log --format=%h\n")]
    assert any(s == "--format=%h" for _, s in _fmt), "--format not IDENT"
    _glob = [(t.type, t.string) for t in _tk('x=("$v"(Nm-1))\n')]
    assert any(s == "Nm-1" for _, s in _glob), "glob qual tokens missing"
    _proc = [(t.type, t.string) for t in _tk("source <(dircolors -b)\n")]
    assert any(k == 5 for k, s in _proc), "process subst not CMD_SUBST"
    print("Tokenizer OK")

    test_scripts = [
        ("While loop", "while [ $count -lt 5 ]; do\n  echo $count\n  count=$((count + 1))\ndone\n"),
        ("Function (paren)", "my_func() {\n  echo $USER_NAME\n}\n"),
        ("Keyword function", "function cleanup {\n  echo done\n}\n"),
        ("Nested control flow", "my_func() {\n  if [ $x ]; then\n    echo yes\n  fi\n}\n"),
        ("If/elif/else", "if [ -f a ]; then\n  echo a\nelif [ -d b ]; then\n  echo b\nelse\n  echo none\nfi\n"),
        ("Backtick pipeline", "`pwd` | grep foo\n"),
        ("Pipeline with var arg", "cat file.txt | grep $PATTERN\n"),
        ("Arithmetic only", "count=$((count + 1))\n"),
        ("Local declaration", "local name=$USER\n"),
        ("and-or chain", "cd /tmp && rm -f foo || echo failed\n"),
        ("cmd subst assignment", "x=$(date)\n"),
        ("nested cmd subst", "y=$(echo $(date))\n"),
        ("case simple", "case $1 in\n  start) echo starting;;\n  stop) echo stopping;;\n  *) echo unknown;;\nesac\n"),
        ("case no wildcard", "case $1 in\n  a) echo a;;\n  b) echo b;;\nesac\n"),
        ("dbl bracket", "if [[ -f $x ]]; then\n  echo yes\nfi\n"),
        ("dbl bracket !=", '[[ "$DISABLE" != true ]] || return 0\n'),
        ("dbl bracket =~", '[[ $x =~ ^foo ]]\n'),
        ("redirection", "echo hello > /tmp/x\n"),
        ("subshell", "( cd /tmp && ls )\n"),
        ("grouping", "{ echo a; echo b; }\n"),
        ("anon function", "() {\n  echo hi\n}\n"),
        ("for-alt", "for f (*.txt) do\n  echo $f\ndone\n"),
        ("select", "select opt in a b c; do\n  echo $opt\ndone\n"),
        ("heredoc", "cat <<EOF\nhello\nEOF\n"),
        ("line continuation", "echo a \\\n     b\n"),
        ("append assignment", "arr+=foo\n"),
        ("negative number", "x=-1\n"),
        ("colon no-op", ":\n"),
        ("colon with args", ": ${FOO:=bar}\n"),
        ("escape space", "git log --format=%h\\ %s\n"),
        ("typeset with flag", "typeset -g foo=bar\n"),
        ("declare array", "declare -A map\n"),
        ("comma in ident", "echo a,b\n"),
        ("dot source", ". /etc/profile\n"),
        ("glob qualifier", 'x=("$v"(Nm-1))\n'),
        ("alias with = arg", "alias ls='gls --color=tty'\n"),
        ("process subst", "source <(dircolors -b)\n"),
        ("zero assign", "0=${(%):-%N}\n"),
        ("prefix cmd", 'GIT_OPTIONAL_LOCKS=0 command git "$@"\n'),        
        ("case glob pattern", 'case "$OSTYPE" in\n  netbsd*)\n    echo a\n    ;;\n  (darwin|freebsd)*)\n    echo b\n    ;;\n  *)\n    echo c\n    ;;\nesac\n'),
    ]

    print("\n--- Path X tests ---")
    for name, code in test_scripts:
        print(f"\n[{name}]")
        try:
            violations = lint_zsh_code(code)
            if violations:
                for v in violations:
                    pos = getattr(v['token'], 'start', '?')
                    print(f"  [{v['rule']}] {pos}: {v['message']}")
            else:
                print("  (no violations)")
        except Exception as e:
            print(f"  Parse Error: {type(e).__name__}: {e}")
