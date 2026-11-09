"""Zsh linter — extended grammar for real-ish zsh scripts.

Design: lint methods are attached to grammar nodes through inner classes.
Argument-level expansion rules live on the explicit `argument` AST node, so
commands, assignments, declarations, and case subjects share one rule path.
"""

from hek_parsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type_node,
    as_node,
    filt,
    literal,
    nothing,
    ignore,
    shift,
)
from zsh_tokenizer import tokenize_zsh, TOKEN_TYPES, _RESERVED

def _children(node): # should be part of hek_parsec.py
    if node is None:
        return []
    if hasattr(node, "nodes") and isinstance(node.nodes, list):
        return [c for c in node.nodes if c is not None]
    if hasattr(node, "node") and node.node is not None:
        return [node.node]
    return []

def _token_of(node): # should be part of hek_parsec.py
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
    AMP = "&"
    AMP_PIPE = "&|"
    AMP_BANG = "&!"
    ASSIGN_OP = ASSIGN | PLUSEQUAL | MINEQUAL
    
    # Visible punctuation (appear in the AST)
    lbrace_vis = filt(lambda tok: tok.string == "{", shift, name="{")
    rbrace_vis = filt(lambda tok: tok.string == "}", shift, name="}")    
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
    NEWLINE = expect_type_node(TOKEN_TYPES["NEWLINE"])

    reserved = _RESERVED
    identifier = filt(lambda tok: tok.string not in reserved, expect_type_node(TOKEN_TYPES["IDENT"]))
    argument_identifier = expect_type_node(TOKEN_TYPES["IDENT"])

    STATEMENT_SEP = NEWLINE | SEMICOL | AMP | AMP_PIPE | AMP_BANG

    # Enhance argument with glob qualifiers, subscripts, and inline assignments.
    # A glob qualifier has at least one token; `()` alone is not one (it is an empty
    # argument-less function header or anonymous function).
    glob_qual = LPAREN + filt(lambda tok: tok.string not in ("(", ")"), shift)[1:] + RPAREN
    subscript = lbracket + ((~rbracket) + shift)[:] + rbracket

    # FIX 5: Added ")" to glob_suffix. This ensures that in a pattern like `(a|b) )`,
    # the first `)` is consumed as part of the pattern (since it's followed by `)`),
    # and the parser correctly stops at the second `)` which acts as the arm closer.
    glob_suffix = filt(lambda tok: tok.string in ("*", "?", "[", ")"), shift)

    _basic_arg = (backtick | cmd_subst | arith_exp | var_exp | heredoc | string
                  | number | glob_qual | subscript | argument_identifier)
    # assign_word matches `name=value` as a single argument (needed for
    # `alias ls='...'`, `export FOO=bar` inline, etc.)
    # Assignment names are plain identifiers; reserved words such as `end` are only
    # keywords in command position, so `end=$second` is a valid assignment.
    assign_name = filt(lambda tok: tok.string.isidentifier(), expect_type_node(TOKEN_TYPES["IDENT"]))
    assign_word = assign_name + ASSIGN + _basic_arg


# ============================================================
# Grammar
# ============================================================

class ZshStyleGrammar(Grammar):
    # An argument is a grammar-level AST construct, not a lexical terminal.
    # Its explicit node boundary gives it one consistent linting entry point
    # wherever the grammar accepts an argument.
    argument = as_node(assign_word | Terminals._basic_arg)

    script = statement[:]

    # and_or comes BEFORE if_stmt/assignment: `x=1 || cmd` and `cond; then`
    # both need and_or to be tried before the assignment fallback.
    statement = (
        # Try logical chains before their individual operands. Otherwise a
        # declaration such as `local x=1` succeeds as a prefix and leaves &&/||
        # behind for the top-level statement parser.
        and_or | redir_command
        | comment | declaration | declaration2
        | function_def | anon_function | case_stmt
        | if_stmt
        | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + STATEMENT_SEP[:]

    # Array literal is opaque; guard with (~LPAREN) so `((…))` still parses
    # as arith_stmt instead of being eaten as an array.
    # Elements may carry glob qualifiers, e.g. `x=("$v"(Nm-1))`, so a nested
    # `(...)` is consumed as one unit instead of closing the array early.
    array_literal = LPAREN + (argument | NEWLINE)[:] + RPAREN
    assign_rhs = array_literal | argument

    assign_target = assign_name | number   # `0=${...}` and other numeric names

    # FIX 1: The declared name may be dynamic: `typeset -ga ${cache_place}` or `"${var}"`.
    # Added `string` to allow quoted variable expansions as declaration targets.
    declaration = literal("local") + flag[:] + ((assign_name | var_exp | string) + (ASSIGN_OP + (assign_rhs | nothing))[0:1])[1:]
    declaration2 = (literal("typeset") | literal("declare")
                    | literal("export") | literal("readonly")) + flag[:] + ((assign_name | var_exp | string) + (ASSIGN_OP + (assign_rhs | nothing))[0:1])[1:]
    
    # One or more `name=value` pairs on a line: `start=$a end=$b`.
    assignment = assign_target + subscript[0:1] + ASSIGN_OP + assign_rhs + assign_word[:]

    # [ ] and [[ ]] content is opaque so test operators remain uninterpreted.
    # The legacy [ ] lint method separately checks raw expansion tokens; [[ ]]
    # intentionally suppresses ZSH002 because it does not perform word splitting.
    test_construct = lbracket + ((~rbracket) + shift)[:] + rbracket
    dbl_test_construct = dlbracket + ((~drbracket) + shift)[:] + drbracket

    redir_op = filt(
        lambda tok: tok.string in ("<", ">", ">>", "<<<", ">&", "<&", ">|", "&>", "&>>"),
        expect_type_node(TOKEN_TYPES["OP"]),
    )
    
    # FIX 3: Named file descriptor redirections: {fd}</dev/null or {1}>&-
    # A zsh descriptor can be a name or a numeric descriptor: `{myfd}` / `{1}`.
    # Try the braced form before the optional traditional numeric prefix; the
    # latter can otherwise succeed empty and prevent the braced form matching.
    named_fd = ignore(lbrace_vis + identifier + rbrace_vis)
    # Keep the target argument in the AST so argument.lint() can inspect it.
    # Only the descriptor and operator are syntactic details.
    redir = (named_fd | ignore(number[0:1])) + ignore(redir_op) + argument
    # Zsh permits redirection-only commands, e.g. `{myfd}</dev/null`.
    redir_command = redir[1:]

    
    command_head = identifier | colon | backtick | cmd_subst | arith_exp | var_exp | string | number
    command = assign_word[:] + command_head + argument[:] + redir[:]

    _two_rparen = RPAREN + RPAREN
    arith_body = ((~_two_rparen) + shift)[:]
    arith_stmt = LPAREN + LPAREN + arith_body + RPAREN + RPAREN
    
    # as_node(command) keeps each command a distinct node inside pipelines,
    # so command.lint fires per stage instead of only on bare commands.
    pipeline_item = command | grouping | subshell
    
    # Operators may be followed by a line break: `a |\n  b` and `a &&\n  b`.
    pipeline = as_node(pipeline_item) + (PIPE + NEWLINE[:] + as_node(pipeline_item))[:]
    
    # `! cmd` — command negation prefix
    # `! x=$(cmd) || ...` negates an assignment as well as a command.
    not_command = ignore(literal("!")) + (pipeline | assignment)

    inner_statement = (
        and_or | redir_command
        | comment | declaration | declaration2
        | function_def | anon_function | case_stmt
        | if_stmt
        | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + STATEMENT_SEP[:]

    # FIX 2: and_or_item now includes declarations (`local x=1 && cmd` or `typeset x=1 || echo fail`)
    # in addition to not_command (`!`), assignment (`x=1 || cmd`), and the previous items.
    and_or_item = (
        test_construct | dbl_test_construct | arith_stmt
        | not_command | grouping | subshell | assignment | pipeline
        | declaration | declaration2
    )    
    and_or = as_node(and_or_item) + ((AND_AND | OR_OR) + NEWLINE[:] + as_node(and_or_item))[:]

    # All four control-flow conditions now accept and_or chains:
    #   if [[ -f x ]] && (( i++ )); then ... fi
    #   while cmd1 && ! cmd2; do ... done
    elif_branch = (
        literal("elif") + and_or + STATEMENT_SEP[:]
        + literal("then") + STATEMENT_SEP[:] + inner_statement[:]
        + STATEMENT_SEP[:]
    )
    else_branch = (
        literal("else") + STATEMENT_SEP[:] + inner_statement[:]
        + STATEMENT_SEP[:]
    )

    if_stmt = (
        literal("if") + and_or + STATEMENT_SEP[:]
        + literal("then") + STATEMENT_SEP[:] + inner_statement[:]
        + STATEMENT_SEP[:]
        + elif_branch[:] + else_branch[0:1]
        + literal("fi")
    )

    # FIX 4: Support multiple loop variables: `for a b in ...` and `for a b; do ...`
    # Changed `identifier` to `identifier[1:]` (one or more identifiers).
    for_alt = (literal("for") + identifier[1:] + LPAREN + argument[:] + RPAREN + STATEMENT_SEP[:]
               + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
               + STATEMENT_SEP[:] + literal("done"))
    for_stmt = (literal("for") + identifier[1:] + literal("in") + argument[:] + STATEMENT_SEP[:]
                + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                + STATEMENT_SEP[:] + literal("done"))
    # `for x y; do ...` iterates over the positional parameters (no `in` list).
    for_positional = (literal("for") + identifier[1:] + STATEMENT_SEP[:]
                + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                + STATEMENT_SEP[:] + literal("done"))
    foreach_stmt = (literal("foreach") + identifier[1:] + LPAREN + argument[:] + RPAREN + STATEMENT_SEP[:]
                    + inner_statement[:] + STATEMENT_SEP[:] + literal("end"))
    select_stmt = (literal("select") + identifier + literal("in") + argument[:] + STATEMENT_SEP[:]
                   + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                   + STATEMENT_SEP[:] + literal("done"))

    while_stmt = (literal("while") + and_or + STATEMENT_SEP[:]
                  + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                  + STATEMENT_SEP[:] + literal("done"))
    until_stmt = (literal("until") + and_or + STATEMENT_SEP[:]
                  + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                  + STATEMENT_SEP[:] + literal("done"))
    repeat_stmt = (literal("repeat") + argument + STATEMENT_SEP[:]
                   + literal("do") + STATEMENT_SEP[:] + inner_statement[:]
                   + STATEMENT_SEP[:] + literal("done"))

    # Case pattern: consume tokens until we hit a `)` that is NOT followed by
    # a glob modifier (`*`, `?`, `[`). That distinguishes the pattern-closing
    # `)` in `(darwin|freebsd)*)` from the `)` inside the glob group.
    case_pattern = ((~((rparen_vis + (~glob_suffix)))) + shift)[:] + rparen_vis
    case_body = case_pattern + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:]
    # Arms that end with a terminator, then an optional final arm without one
    # (`*) cmd` directly before `esac`). The optional arm must not start at
    # `esac`: a case pattern would otherwise scan through `esac` up to the next
    # `)` in the file. The guard therefore sits after the leading separators.
    # NOTE: The guard (~literal("esac")) must be on BOTH case_arm and case_final
    # to prevent case_arm from greedily consuming `esac` and subsequent code.
    case_arm = STATEMENT_SEP[:] + (~literal("esac")) + case_body + (DSEMI | SEMI_AMP | SEMI_BAR)
    case_final = STATEMENT_SEP[:] + (~literal("esac")) + case_body
    case_stmt = (
        literal("case") + argument + literal("in") + STATEMENT_SEP[:]
        + case_arm[:] + case_final[0:1]
        + STATEMENT_SEP[:] + literal("esac")
    )

    # Function names may be dynamic: `_widget_${name}() { ... }`.
    func_name = (identifier | var_exp)[1:]
    function_def = (
        (func_name + LPAREN + RPAREN)
        | (literal("function") + func_name + (LPAREN + RPAREN)[0:1])
    ) + STATEMENT_SEP[:] + LBRACE + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:] + RBRACE

    # Anonymous function: `() { body }` — zsh-specific, defined and called
    # immediately. Must appear BEFORE subshell in the choice lists because
    # `()` alone is also a valid (empty) subshell.
    anon_function = (
        LPAREN + RPAREN
        + LBRACE + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:] + RBRACE
    )

    subshell = LPAREN + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:] + RPAREN
    grouping = LBRACE + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:] + RBRACE

    # ---------- Lint methods ----------
    class __default__:
        def lint(self):
            # this node doesnt have a lint method, but its children may have.
            issues = []
            for c in _children(self):
                if hasattr(c,"lint"): 
                    issues.extend(c.lint())
            return issues
            
    class argument:
        def lint(self):    
            """Return expansion diagnostics for the tokens inside this argument node."""
            issues = []
            seen = set()
            def walk(node):
                if node is None:
                    return
                if hasattr(node, "string") and not hasattr(node, "nodes"):
                    tok = node
                    value = getattr(tok, "string", None)
                    if not isinstance(value, str) or not value:
                        return
                    # Quoted expansions are tokenized as STRING and therefore retain
                    # their quote prefix; only unquoted token spellings match here.
                    if value.startswith("$") and not value.startswith(("${", "$((")):
                        rule = "ZSH002"
                        if value.startswith("$(") and value.endswith(")"):
                            message = f"Unquoted command substitution '{value}' detected."
                        else:
                            message = (f"Unquoted variable expansion '{value}' detected. "
                                       "Risk of word splitting and globbing.")
                    elif value.startswith("`") and value.endswith("`"):
                        rule = "ZSH003"
                        message = "Prefer modern '$(...)' over legacy backticks."
                    else:
                        return
                    marker = (rule, getattr(tok, "start", None), value)
                    if marker not in seen:
                        seen.add(marker)
                        issues.append({"rule": rule, "message": message, "token": tok})
                    return

                for child in _children(node):
                    walk(child)

            walk(self)
            return issues
    class command:
        def lint(self):
            issues = []
            idx = 0
            while idx < len(self.nodes) and type(self.nodes[idx]).__name__ == "Several_Times":
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
            # command has a custom lint method, so explicitly continue the
            # normal recursive traversal to reach its argument AST nodes.
            for child in _children(self):
                if hasattr(child, "lint"):
                    issues.extend(child.lint())
            return issues
        
    class test_construct:
        def lint(self):
            def _raw_test_expansion_issues(test_node): # should be inlined
                """Check raw tokens in legacy [ ... ]; [[ ... ]] is intentionally exempt."""
                issues = []
                for child in _children(test_node):
                    if hasattr(child, "string"):
                        value = child.string
                        if isinstance(value, str) and value.startswith("$") and not value.startswith(("${", "$((")):
                            issues.append({"rule": "ZSH002",
                                           "message": f"Unquoted variable expansion '{value}' detected. Risk of word splitting and globbing.",
                                           "token": child})
                        elif isinstance(value, str) and value.startswith("$(") and value.endswith(")"):
                            issues.append({"rule": "ZSH002",
                                           "message": f"Unquoted command substitution '{value}' detected.",
                                           "token": child})
                        elif isinstance(value, str) and value.startswith("`") and value.endswith("`"):
                            issues.append({"rule": "ZSH003",
                                           "message": "Prefer modern '$(...)' over legacy backticks.",
                                           "token": child})
                    else:
                        # Opaque test grammar can contain wrapper nodes; inspect their leaves.
                        issues.extend(_raw_test_expansion_issues(child))
                return issues            
            issues = [{"rule": "ZSH004",
                       "message": "Prefer enhanced '[[ ... ]]' over legacy POSIX '[ ... ]' test construct in zsh.",
                       "token": _token_of(self.nodes[0])}]
            issues.extend(_raw_test_expansion_issues(self))
            return issues

    class dbl_test_construct:
        # [[ ... ]] performs no word splitting — suppress ZSH002 for its args.
        # Also suppresses ZSH004 (this is the recommended form).
        def lint(self):
            return []   # [[ ]] does no word splitting; recommended form

    class case_stmt:
        # The case word (nodes[1]) is subject to splitting — check it.
        # Then recurse into bodies.
        def lint(self):
            def has_wildcard_case(case_node): 
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
            issues = []
            # check for wildcard fallback
            if not has_wildcard_case(self):
                issues.append({
                    "rule": "ZSH007",
                    "message": "case without a `*)` fallback — unexpected input silently ignored.",
                    "token": _token_of(self.nodes[1]) if len(self.nodes) > 1 else _token_of(self.nodes[0]),
                })
            for c in _children(self):
                issues.extend(c.lint())
            return issues

    class script:
        def lint(self):
            issues = []
            for c in _children(self):
                issues.extend(c.lint())                       
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
        ("blank line in while", "while true; do\n  echo a\n\n  echo b\n\ndone\n"),
        ("Function (paren)", "my_func() {\n  echo $USER_NAME\n}\n"),
        ("blank line in function", "f() {\n  echo a\n\n  echo b\n\n}\n"),
        ("Keyword function", "function cleanup {\n  echo done\n}\n"),
        ("Nested control flow", "my_func() {\n  if [ $x ]; then\n    echo yes\n  fi\n}\n"),
        ("If/elif/else", "if [ -f a ]; then\n  echo a\nelif [ -d b ]; then\n  echo b\nelse\n  echo none\nfi\n"),
        ("blank line in if", "if true; then\n  echo a\n\nfi\n"),
        ("if with &&", 'if cmd1 && cmd2; then\n  echo hi\nfi\n'),
        ("if with complex &&", 'if [[ -f a ]] && (( i++ )) && [ -d b ]; then\n  echo hi\nfi\n'),
        ("if with !", 'if ! cmd; then\n  echo hi\nfi\n'),
        ("if with ! after &&", 'if cmd1 && ! cmd2; then\n  echo hi\nfi\n'),
        ("elif with &&", 'if a; then\n  echo 1\nelif b && c; then\n  echo 2\nfi\n'),
        ("while with &&", 'while cmd1 && cmd2; do\n  echo hi\ndone\n'),
        ("until with ||", 'until a || b; do\n  echo hi\ndone\n'),
        ("assign || cmd", 'x=1 || echo failed\n'),
        ("assign && cmd", 'x=$(cmd) && echo ok\n'),
        ("Backtick pipeline", "`pwd` | grep foo\n"),
        ("Pipeline with var arg", "cat file.txt | grep $PATTERN\n"),
        ("Arithmetic only", "count=$((count + 1))\n"),
        ("Local declaration", "local name=$USER\n"),
        ("and-or chain", "cd /tmp && rm -f foo || echo failed\n"),
        ("and with grouping", "true && { echo a; echo b; }\n"),
        ("and with subshell", "true && ( cd /tmp && ls )\n"),
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
        ("Quoted declaration name", 'typeset -g "${var}"=value\n'),
        ("&& with declaration", 'local x=1 && echo ok\n'),
        ("|| with declaration", 'typeset y=2 || echo fail\n'),
        ("Named fd redirection", '{myfd}</dev/null\n'),
        ("Named fd numeric", '{1}>&-\n'),
        ("Multiple for vars", 'for a b in 1 2; do echo $a $b; done\n'),
        ("Multiple for vars positional", 'for x y; do echo $x $y; done\n'),
        ("Case parenthesized group", 'case "$OSTYPE" in\n  (darwin|freebsd)*)\n    echo b\n    ;;\n  *)\n    echo c\n    ;;\nesac\n'),
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
                print("  (no violations - parsed successfully)")
        except Exception as e:
            print(f"  Parse Error: {type(e).__name__}: {e}")
