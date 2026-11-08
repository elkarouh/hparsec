"""Zsh linter — extended grammar for real-ish zsh scripts."""

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

    # Visible punctuation (appear in the AST)
    lbracket = filt(lambda tok: tok.string == "[", shift, name="[")
    rbracket = filt(lambda tok: tok.string == "]", shift, name="]")
    dlbracket = filt(lambda tok: tok.string == "[[", shift, name="[[")
    drbracket = filt(lambda tok: tok.string == "]]", shift, name="]]")
    lparen_vis = filt(lambda tok: tok.string == "(", shift, name="(")
    rparen_vis = filt(lambda tok: tok.string == ")", shift, name=")")

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

    identifier = filt(
        lambda tok: tok.string not in reserved,
        expect_type_node(TOKEN_TYPES["IDENT"]),
    )
    argument_identifier = expect_type_node(TOKEN_TYPES["IDENT"])

    argument = backtick | cmd_subst | arith_exp | var_exp | heredoc | string | number | argument_identifier
    statement_sep = newline | SEMICOL


# ============================================================
# Helpers
# ============================================================

def _token_of(node):
    if node is None:
        return None
    if hasattr(node, "string"):
        return node
    if hasattr(node, "node"):
        return _token_of(node.node)
    return None


def _children(node):
    if node is None:
        return []
    if hasattr(node, "nodes") and isinstance(node.nodes, list):
        return [c for c in node.nodes if c is not None]
    if hasattr(node, "node") and node.node is not None:
        return [node.node]
    return []


def _first_token_string(node):
    n = node
    for _ in range(10):
        if n is None:
            return None
        if isinstance(n, str):
            return n
        if hasattr(n, "string"):
            return getattr(n, "string", None)
        if hasattr(n, "node"):
            n = n.node
            continue
        if hasattr(n, "nodes") and isinstance(n.nodes, list) and n.nodes:
            n = n.nodes[0]
            continue
        return None
    return None


def _is_leaf(node):
    if node is None:
        return False
    if isinstance(node, str):
        return True
    if hasattr(node, "string") and not hasattr(node, "nodes"):
        return True
    if type(node).__name__ in ("Sequence_Parser", "Several_Times", "Choice_Parser"):
        return False
    return True


def _is_several_times(node):
    return type(node).__name__ == "Several_Times"


def _is_sequence(node):
    return type(node).__name__ == "Sequence_Parser"


def check_argument_issues(arg_node, skip_split=False):
    """Emit ZSH002 (unquoted expansion) / ZSH003 (backtick) for arguments.

    When `skip_split` is True (e.g. inside `[[ ... ]]`), ZSH002 is NOT
    emitted for `$var` / `$(...)` because `[[ ]]` performs no word
    splitting — the expansion is safe unquoted there. ZSH003 still fires
    because backticks are a style issue regardless of context.
    """
    issues = []
    for arg in _children(arg_node) or [arg_node]:
        tok = _token_of(arg)
        if tok is None:
            continue
        val = getattr(tok, "string", str(tok))
        if not isinstance(val, str):
            continue
        if val.startswith("$") and not val.startswith("${") and not val.startswith("$(("):
            if val.startswith("$(") and val.endswith(")"):
                if not skip_split:
                    issues.append({
                        "rule": "ZSH002",
                        "message": f"Unquoted command substitution '{val}' detected.",
                        "token": tok,
                    })
            else:
                if not skip_split:
                    issues.append({
                        "rule": "ZSH002",
                        "message": f"Unquoted variable expansion '{val}' detected. "
                                   f"Risk of word splitting and globbing.",
                        "token": tok,
                    })
        elif val.startswith("`") and val.endswith("`"):
            issues.append({
                "rule": "ZSH003",
                "message": "Prefer modern '$(...)' command substitution over legacy backticks.",
                "token": tok,
            })
    return issues


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
        | function_def | case_stmt
        | subshell | grouping
        | and_or
    ) + statement_sep[:]

    declaration = literal("local") + identifier + ASSIGN + argument
    declaration2 = (literal("typeset") | literal("declare")
                    | literal("export") | literal("readonly")) + identifier + ASSIGN + argument
    assignment = identifier + ASSIGN + argument

    test_construct = lbracket + argument[:] + rbracket
    dbl_test_construct = dlbracket + argument[:] + drbracket

    redir_op = filt(
        lambda tok: tok.string in ("<", ">", ">>", "<<<", ">&", "<&"),
        expect_type_node(TOKEN_TYPES["OP"]),
    )
    redir = ignore(redir_op + argument)

    command_head = identifier | backtick | cmd_subst | arith_exp | var_exp | string | number
    command = command_head + argument[:] + redir[:]
    pipeline = command + (PIPE + command)[:]
    and_or = pipeline + ((AND_AND | OR_OR) + pipeline)[:]

    inner_statement = (
        comment | declaration | declaration2 | assignment
        | if_stmt
        | for_alt | for_stmt | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | function_def | case_stmt
        | subshell | grouping
        | and_or
    ) + statement_sep[:]

    elif_branch = literal("elif") + (test_construct | dbl_test_construct | command) + statement_sep[:] + literal("then") + statement_sep[:] + inner_statement[:]
    else_branch = literal("else") + statement_sep[:] + inner_statement[:]

    if_stmt = (
        literal("if") + (test_construct | dbl_test_construct | command) + statement_sep[:]
        + literal("then") + statement_sep[:]
        + inner_statement[:]
        + elif_branch[:]
        + else_branch[0:1]
        + literal("fi")
    )

    for_alt = (
        literal("for") + identifier + LPAREN + argument[:] + RPAREN + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )
    for_stmt = (
        literal("for") + identifier + literal("in") + argument[:] + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )
    foreach_stmt = (
        literal("foreach") + identifier + LPAREN + argument[:] + RPAREN + statement_sep[:]
        + inner_statement[:]
        + literal("end")
    )
    select_stmt = (
        literal("select") + identifier + literal("in") + argument[:] + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )

    while_stmt = (
        literal("while") + (test_construct | dbl_test_construct | command) + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )
    until_stmt = (
        literal("until") + (test_construct | dbl_test_construct | command) + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )
    repeat_stmt = (
        literal("repeat") + argument + statement_sep[:]
        + literal("do") + statement_sep[:]
        + inner_statement[:]
        + literal("done")
    )

    case_pattern = lparen_vis[0:1] + argument[:] + rparen_vis
    case_body = case_pattern + statement_sep[:] + inner_statement[:]
    case_stmt = (
        literal("case") + argument + literal("in") + statement_sep[:]
        + (statement_sep[:] + case_body + (DSEMI | SEMI_AMP | SEMI_BAR))[:]
        + statement_sep[:]
        + literal("esac")
    )

    function_def = (
        (identifier + LPAREN + RPAREN)
        | (literal("function") + identifier + (LPAREN + RPAREN)[0:1])
    ) + statement_sep[:] + LBRACE + statement_sep[:] + inner_statement[:] + RBRACE

    subshell = LPAREN + statement_sep[:] + inner_statement[:] + RPAREN
    grouping = LBRACE + statement_sep[:] + inner_statement[:] + RBRACE

    class script:
        def lint(self):
            all_issues = []

            def visit(node, in_dbl_test):
                if node is None:
                    return
                is_dbl_test = _looks_like_dbl_test_construct(node)
                for child in _children(node):
                    visit(child, in_dbl_test or is_dbl_test)
                all_issues.extend(_classify_and_lint(node, in_dbl_test=in_dbl_test))

            visit(self, False)
            return all_issues


# ============================================================
# Shape classifiers
# ============================================================

def _looks_like_test_construct(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) != 3:
        return False
    return _first_token_string(kids[0]) == "[" and _first_token_string(kids[2]) == "]"


def _looks_like_dbl_test_construct(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) != 3:
        return False
    return _first_token_string(kids[0]) == "[[" and _first_token_string(kids[2]) == "]]"


def _looks_like_declaration(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) < 2:
        return False
    if not _is_leaf(kids[0]):
        return False
    return _first_token_string(kids[0]) in ("local", "typeset", "declare", "export", "readonly")


def _looks_like_assignment(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) != 2:
        return False
    if not _is_leaf(kids[0]):
        return False
    return not _is_several_times(kids[1])


def _looks_like_pipeline(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) != 3:
        return False
    if not _is_leaf(kids[0]):
        return False
    return _is_several_times(kids[2])


def _looks_like_command(node):
    if not _is_sequence(node):
        return False
    kids = _children(node)
    if len(kids) < 2:
        return False
    if not _is_leaf(kids[0]):
        return False
    return _first_token_string(kids[0]) is not None


def _lint_command_head_and_args(kids, skip_split=False):
    issues = []
    head_tok = _token_of(kids[0])
    head_name = getattr(head_tok, "string", None) if head_tok else _first_token_string(kids[0])

    if head_name == "echo":
        issues.append({
            "rule": "ZSH001",
            "message": "Prefer native 'print' or 'printf' over legacy 'echo'.",
            "token": head_tok,
        })
    elif head_name in ("grep", "sed", "awk"):
        issues.append({
            "rule": "ZSH005",
            "message": f"External tool '{head_name}' used; prefer native zsh equivalents where possible.",
            "token": head_tok,
        })
    elif isinstance(head_name, str) and head_name.startswith("`") and head_name.endswith("`"):
        issues.append({
            "rule": "ZSH003",
            "message": "Prefer modern '$(...)' command substitution over legacy backticks.",
            "token": head_tok,
        })

    if len(kids) > 1:
        issues.extend(check_argument_issues(kids[1], skip_split=skip_split))
    return issues


def _classify_and_lint(node, in_dbl_test=False):
    if _looks_like_test_construct(node):
        open_tok = _token_of(_children(node)[0])
        return [{
            "rule": "ZSH004",
            "message": "Prefer enhanced '[[ ... ]]' over legacy POSIX '[ ... ]' test construct in zsh.",
            "token": open_tok,
        }]

    if _looks_like_dbl_test_construct(node):
        # [[ ... ]] is not a warn target — its whole point is to avoid the
        # word-splitting issues of [ ... ].
        return []

    if _looks_like_declaration(node):
        kids = _children(node)
        if len(kids) >= 3:
            return check_argument_issues(kids[2])
        return []

    if _looks_like_assignment(node):
        return check_argument_issues(_children(node)[1])

    if _looks_like_pipeline(node):
        return _lint_command_head_and_args(_children(node)[:2], skip_split=in_dbl_test)

    if _looks_like_command(node):
        return _lint_command_head_and_args(_children(node), skip_split=in_dbl_test)

    return []


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
    print("TOKENIZER FILE:", _tk.__code__.co_filename)
    _arith = [(t.type, t.string) for t in _tk("count=$((count + 1))")]
    print("arith tokens:", _arith)
    assert any(k == 3 and s == "$((count + 1))" for k, s in _arith), (
        "Tokenizer is STALE: $((...)) must be a single ARITH_EXP token."
    )
    _case = [(t.type, t.string) for t in _tk("case $1 in\n a) x;;\nesac\n")]
    print("case tokens:", _case)
    assert any(k == 4 and s == "$1" for k, s in _case), (
        "Tokenizer is STALE: $1 must be a single VAR_EXP token."
    )
    print()

    test_scripts = [
        ("While loop",
         "while [ $count -lt 5 ]; do\n  echo $count\n  count=$((count + 1))\ndone\n"),
        ("Function (paren)",
         "my_func() {\n  echo $USER_NAME\n}\n"),
        ("Keyword function",
         "function cleanup {\n  echo done\n}\n"),
        ("Nested control flow",
         "my_func() {\n  if [ $x ]; then\n    echo yes\n  fi\n}\n"),
        ("If/elif/else",
         "if [ -f a ]; then\n  echo a\nelif [ -d b ]; then\n  echo b\nelse\n  echo none\nfi\n"),
        ("Backtick pipeline",
         "`pwd` | grep foo\n"),
        ("Pipeline with var arg",
         "cat file.txt | grep $PATTERN\n"),
        ("Arithmetic only",
         "count=$((count + 1))\n"),
        ("Local declaration",
         "local name=$USER\n"),
        ("and-or chain",
         "cd /tmp && rm -f foo || echo failed\n"),
        ("cmd subst assignment",
         "x=$(date)\n"),
        ("nested cmd subst",
         "y=$(echo $(date))\n"),
        ("case simple",
         "case $1 in\n  start) echo starting;;\n  stop) echo stopping;;\n  *) echo unknown;;\nesac\n"),
        ("dbl bracket",
         "if [[ -f $x ]]; then\n  echo yes\nfi\n"),
        ("redirection",
         "echo hello > /tmp/x\n"),
        ("subshell",
         "( cd /tmp && ls )\n"),
        ("grouping",
         "{ echo a; echo b; }\n"),
        ("for-alt",
         "for f (*.txt) do\n  echo $f\ndone\n"),
        ("select",
         "select opt in a b c; do\n  echo $opt\ndone\n"),
        ("heredoc",
         "cat <<EOF\nhello\nEOF\n"),
    ]

    print("--- Extended Zsh Linter Tests ---")
    for name, code in test_scripts:
        print(f"\nTest Case: [{name}]")
        print(f"Code:\n{code.rstrip()}")
        try:
            violations = lint_zsh_code(code)
            if violations:
                print("Linter Warnings Found:")
                for v in violations:
                    pos = getattr(v['token'], 'start', 'unknown')
                    print(f"  [{v['rule']}] Line {pos}: {v['message']}")
            else:
                print("  No violations found!")
        except Exception as e:
            print(f"  Parse Error: {type(e).__name__}: {e}")