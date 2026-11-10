"""Zsh linter — extended grammar for real-ish zsh scripts.

Design: lint methods are attached to grammar nodes through inner classes.
Argument-level expansion rules live on the explicit `argument` AST node, so
commands, assignments, declarations, and case subjects share one rule path.
"""

import sys

from hparsec import (
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
    children, 
    token_of
)
from zsh_tokenizer import tokenize_zsh, TOKEN_TYPES, _RESERVED

# ============================================================
# Terminals
# ============================================================

class ZshTerminals(Terminals):
    ASSIGN = "="
    SEMICOL = ";"
    PIPE = "|"
    PIPE_AMP = "|&"
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
    # Only the operator closes [[ ]]; the ]] of a [[:alpha:]] class is an IDENT token.
    drbracket = filt(lambda tok: tok.string == "]]" and tok.type == TOKEN_TYPES["OP"] and not tok.glued, shift, name="]]")
    lparen_vis = filt(lambda tok: tok.string == "(", shift, name="(")
    rparen_vis = filt(lambda tok: tok.string == ")", shift, name=")")
    colon = filt(lambda tok: tok.string == ":", shift, name=":")
    # An arithmetic expansion may be glued on to a flag: `typeset -L$(( n )) x`.
    # Only $((...)) is taken: a following ${...} is the declared name.
    flag = filt(
        lambda tok: isinstance(tok.string, str) and len(tok.string) > 1
                    and tok.string.startswith("-") and not tok.string.startswith("--"),
        expect_type_node(TOKEN_TYPES["IDENT"]),
        name="-flag",
    # A numeric argument may follow a flag: `typeset -F 2 SECONDS`, `typeset -i 3 X`.
    ) + ignore(expect_type_node(TOKEN_TYPES["ARITH_EXP"]) | expect_type_node(TOKEN_TYPES["NUMBER"]))[0:1]

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

    # A bare `=` followed by a space is ASSIGN_EMPTY; as an argument it is just a word
    # (`test $x = 0`).
    # A brace group in argument position is a brace-expansion word: `{01..$N}`, `{a,b}`.
    # Ignored in the AST, so its contents are not linted as expansions.
    brace_word = ignore(LBRACE + ((~RBRACE) + shift)[:] + RBRACE)
    # A `[[ ... ]]` test passed as an argument: `eval [[ -n $x ]]`.
    dbl_bracket_word = ignore(filt(lambda tok: tok.string == "[[", expect_type_node(TOKEN_TYPES["OP"]))
                              + ((~filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"]))) + shift)[:]
                              + filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"])))
    # A word may start with a colon: `getopts :ho SWITCH`.
    colon_word = ignore(filt(lambda tok: tok.string == ":", expect_type_node(TOKEN_TYPES["OP"]))) + argument_identifier[1:]
    _basic_arg = (backtick | cmd_subst | arith_exp | var_exp | heredoc | string | brace_word | dbl_bracket_word | colon_word
                  | number
                  # Extended glob: an operator before a group is one word, `+([0-9])` or `!(*.log)`.
                  | (ignore(filt(lambda tok: tok.string in ("+", "*", "?", "!", "@"), expect_type_node(TOKEN_TYPES["OP"]))) + glob_qual)
                  | glob_qual | subscript | argument_identifier | expect_type_node(TOKEN_TYPES["ASSIGN_EMPTY"])
                  # A "}" glued to a word is a literal: `echo x}.log`. A separate "}" still closes a group.
                  | ignore(filt(lambda tok: tok.glued and tok.string == "}", expect_type_node(TOKEN_TYPES["OP"])))
                  # Bare pattern characters are word parts in zsh: `fd -tx remove$ dir`,
                  # `grep -v ^N_`, `grep .+%U.+`, `cmd 08:00:00`. Ignored so they are not mistaken for expansions.
                  | ignore(filt(lambda tok: tok.string in ("$", "^", "+", "!", ".", ":"), expect_type_node(TOKEN_TYPES["OP"])))
                  # `test "x$a" != x`: comparison operators are plain words to test(1).
                  | ignore(filt(lambda tok: tok.string in ("!=", "=="), expect_type_node(TOKEN_TYPES["OP"])))
                  # `]]` closes a test only after `[[`; elsewhere it is a word: `is_a_server ${X} ]]`.
                  | ignore(filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"]))))
    # assign_word matches `name=value` as a single argument (needed for
    # `alias ls='...'`, `export FOO=bar` inline, etc.)
    # Assignment names are plain identifiers; reserved words such as `end` are only
    # keywords in command position, so `end=$second` is a valid assignment.
    assign_name = filt(lambda tok: tok.string.isidentifier(), expect_type_node(TOKEN_TYPES["IDENT"]))
    # The value may be empty: `RPROMPT=` is a valid assignment.
    # `=` directly followed by a value is an assignment; `=` followed by whitespace
    # is an empty assignment (ASSIGN_EMPTY), so `IFS= read` never takes `read` as a value.
    assign_eq = filt(lambda tok: tok.string == "=", expect_type_node(TOKEN_TYPES["OP"]))
    assign_eq_empty = expect_type_node(TOKEN_TYPES["ASSIGN_EMPTY"])
    # `FS=: read` — a bare `:` is a valid assignment value.
    assign_value_colon = filt(lambda tok: tok.string == ":", expect_type_node(TOKEN_TYPES["OP"]))
    # A value may itself contain `=`: `PP=dumpfile=${DMP}` is one word with the value
    # `dumpfile=${DMP}`. Only `=` continues the value, so the next argument is not taken.
    # A value may also be followed by glued word parts: `x=${a}${b}.txt`. Only tokens
    # touching the previous one continue the value, so `x=a b` still ends at `a`.
    glued_part = filt(lambda tok: tok.glued and (tok.type != TOKEN_TYPES["OP"]
                                                 or tok.string in (".", "$", "^", "+", "-", "!", ",", "%", "*", "?", "/", "@", "~", ":", "[", "]", "{", "}", "=", "=="))
                      and tok.type not in (TOKEN_TYPES["NEWLINE"], TOKEN_TYPES["COMMENT"]), shift)
    assign_value = (_basic_arg | assign_value_colon) + ((assign_eq + _basic_arg) | glued_part)[0:]
    assign_word = (assign_name + subscript[0:1] + assign_eq + assign_value) | (assign_name + assign_eq + assign_value) | (assign_name + assign_eq_empty)

# HELPERS
def _expansion_issues(node, backticks_only=False):
    """Find unquoted expansions and legacy backticks below an AST node.

    With backticks_only, report only ZSH003 (used where word splitting does not apply).
    """
    issues = []
    seen = set()

    def walk(current):
        if current is None:
            return

        # A token is a leaf: it has a string attribute but no AST children.
        if hasattr(current, "string") and not hasattr(current, "nodes"):
            tok = current
            value = getattr(tok, "string", None)

            if not isinstance(value, str) or not value:
                return

            if value.startswith("`") and value.endswith("`"):
                rule = "ZSH003"
                message = "Prefer modern '$(...)' over legacy backticks."

            elif (
                value.startswith("$(")
                and value.endswith(")")
                and not value.startswith("$((")
            ):
                rule = "ZSH002"
                message = (
                    f"Unquoted command substitution '{value}' detected."
                )
                if backticks_only:
                    return

            elif value.startswith("$") and not value.startswith(
                ("${", "$((")
            ):
                rule = "ZSH002"
                message = (
                    f"Unquoted variable expansion '{value}' detected. "
                    "Risk of word splitting and globbing."
                )
                if backticks_only:
                    return

            else:
                return

            marker = (rule, getattr(tok, "start", None), value)

            if marker not in seen:
                seen.add(marker)
                issues.append({
                    "rule": rule,
                    "message": message,
                    "token": tok,
                })

            return

        for child in children(current):
            walk(child)

    walk(node)
    return issues
# ============================================================
# Grammar
# ============================================================

class ZshStyleGrammar(Grammar):

    # Leading blank lines are allowed; each statement consumes its own trailing separators.
    script = STATEMENT_SEP[:] + statement[:]

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
        | for_arith | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + STATEMENT_SEP[:]

    # An argument is a grammar-level AST construct, not a lexical terminal.
    # Its explicit node boundary gives it one consistent linting entry point
    # wherever the grammar accepts an argument.
    # A word such as `alias rg.="..."` or `foo-x=1`: the name is not a plain identifier,
    # so it can only be an argument, never an assignment.
    # A quoted name may also be the left side: `alias -g '${1+"$@"}'='"$@"'`.
    # The name may be built from pieces: `GENERATED_${TYPE}=...`, `"x"=...`, `$(cmd)=...`.
    loose_word = (
        (ZshTerminals.assign_name
         | filt(lambda tok: not tok.string.isidentifier(), expect_type_node(TOKEN_TYPES["IDENT"]))
         | ZshTerminals.string | ZshTerminals.var_exp | ZshTerminals.cmd_subst
         | ignore(filt(lambda tok: tok.string == ":", expect_type_node(TOKEN_TYPES["OP"]))))[1:]
        + ZshTerminals.assign_eq + ZshTerminals._basic_arg
    )
    argument = as_node(assign_word | loose_word | ZshTerminals._basic_arg)

    prefix_assignment = as_node(assign_word)

    command_head = as_node(
        identifier
        | colon
        | backtick
        | cmd_subst
        | arith_exp
        | var_exp
        | string
        | number
    )

    # Redirections and arguments may interleave: `cat >&2 <<EOF` has a redirect
    # before the heredoc word. redir is tried first so `2>&1` is not read as the word `2`.
    command = (
        prefix_assignment[:]
        + command_head
        + (redir | argument)[:]
    )    
    ############################################ NEW

    # Array literal is opaque; guard with (~LPAREN) so `((…))` still parses
    # as arith_stmt instead of being eaten as an array.
    # Elements may carry glob qualifiers, e.g. `x=("$v"(Nm-1))`, so a nested
    # `(...)` is consumed as one unit instead of closing the array early.
    # Assignment values and array elements are not word-split by zsh, so they are
    # parsed as plain expansions (not `argument` nodes) and are not linted.
    array_literal = LPAREN + (ZshTerminals._basic_arg | NEWLINE)[:] + RPAREN
    assign_rhs = array_literal | ZshTerminals.assign_value

    assign_target = assign_name | number   # `0=${...}` and other numeric names

    # A declared name may be an array element: `export NAME[$i]=$x`.
    # FIX 1: The declared name may be dynamic: `typeset -ga ${cache_place}` or `"${var}"`.
    # Added `string` to allow quoted variable expansions as declaration targets.
    declaration = literal("local") + flag[:] + (((assign_name + subscript[0:1]) | var_exp | string) + (ASSIGN_OP + (assign_rhs | nothing))[0:1])[1:]
    declaration2 = (literal("typeset") | literal("declare")
                    | literal("export") | literal("readonly")) + flag[:] + (((assign_name + subscript[0:1]) | var_exp | string) + (ASSIGN_OP + (assign_rhs | nothing))[0:1])[0:]
    
    # One or more `name=value` pairs on a line: `start=$a end=$b`.
    assignment = (
        assign_target + subscript[0:1]
        + (((assign_eq | PLUSEQUAL | MINEQUAL) + assign_rhs)
           | (assign_eq_empty + (~argument))  # `IFS= read` is a prefix assignment, not this
           | PLUSEQUAL | MINEQUAL)
        + assign_word[:]
    )

    # [ ] and [[ ]] content is opaque so test operators remain uninterpreted.
    # The legacy [ ] lint method separately checks raw expansion tokens; [[ ]]
    # intentionally suppresses ZSH002 because it does not perform word splitting.
    # The closing ] of [ ] is a separate word: a glued one is part of a glob class such as
    # `[0-9]*` in the test and does not end it.
    test_rbracket = filt(lambda tok: tok.string == "]" and not tok.glued, shift, name="]")
    test_construct = lbracket + ((~test_rbracket) + shift)[:] + test_rbracket
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
    # The here-string operator is kept in the AST so its use can be linted (ZSH008).
    here_string_op = filt(lambda tok: tok.string == "<<<", expect_type_node(TOKEN_TYPES["OP"]))
    # A redirect target may continue with glued word parts: `>${DIR}/x.log` is one word.
    redir = (named_fd | ignore(number[0:1])) + (here_string_op | ignore(redir_op)) + argument + ZshTerminals.glued_part[0:]
    # Zsh permits redirection-only commands, e.g. `{myfd}</dev/null`.
    redir_command = redir[1:]

    _two_rparen = RPAREN + RPAREN
    # Parentheses nest inside arithmetic: `((A = B - (C)))`. A nested group is one unit.
    arith_nested = LPAREN + ((~RPAREN) + shift)[:] + RPAREN
    arith_body = (arith_nested | ((~_two_rparen) + shift))[:]
    arith_stmt = LPAREN + LPAREN + arith_body + RPAREN + RPAREN

    # C-style loop: `for ((i=0; i<3; i++)); do ... done`
    # zsh also takes a brace body: `for ((i=0; i<n; i++)) { ... }`.
    for_arith = (literal("for") + LPAREN + LPAREN + arith_body + RPAREN + RPAREN + (STATEMENT_SEP | comment)[:]
                 + ((literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                     + STATEMENT_SEP[:] + literal("done"))
                    | (LBRACE + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                       + STATEMENT_SEP[:] + RBRACE)))
    
    # as_node(command) keeps each command a distinct node inside pipelines,
    # so command.lint fires per stage instead of only on bare commands.
    # Compound commands can sit on either side of a pipe: `echo x | while read a; do ...; done`.
    # A compound command may carry redirections: `while ...; done < f | sort`.
    # A bare `export` or `typeset` with no names can start a pipeline: `export | grep ^CC_`.
    # A declaration may be followed by redirections: `typeset -p x >/dev/null 2>&1`.
    # A compound command may take a heredoc after its redirections: `done <<EOF`.
    pipeline_item = command | (declaration2 + redir[0:]) | ((grouping | subshell | while_stmt | until_stmt | for_stmt | if_stmt | case_stmt) + (redir | heredoc)[:])
    
    # Operators may be followed by a line break: `a |\n  b` and `a &&\n  b`.
    # `time` is a reserved word that may prefix a pipeline: `time ./job.ksh args`.
    pipeline = literal("time")[0:1] + as_node(pipeline_item) + ((PIPE | PIPE_AMP) + (NEWLINE | comment)[:] + as_node(pipeline_item))[:]
    
    # `! cmd` — command negation prefix
    # `! x=$(cmd) || ...` negates an assignment as well as a command.
    # `if ! [[ ... ]]` negates a test construct as well.
    not_command = ignore(literal("!")) + (pipeline | assignment | dbl_test_construct | test_construct)

    inner_statement = (
        and_or | redir_command
        | comment | declaration | declaration2
        | function_def | anon_function | case_stmt
        | if_stmt
        | for_arith | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + STATEMENT_SEP[:]

    # FIX 2: and_or_item now includes declarations (`local x=1 && cmd` or `typeset x=1 || echo fail`)
    # in addition to not_command (`!`), assignment (`x=1 || cmd`), and the previous items.
    and_or_item = (
        test_construct | dbl_test_construct | arith_stmt
        # `x=$(cmd) | tr a b`: an assignment may be the left side of a pipe, tried first.
        | not_command | (assignment + ((PIPE | PIPE_AMP) + (NEWLINE | comment)[:] + as_node(pipeline_item))[1:])
        # An assignment that a command follows is a prefix assignment of that command:
        # `IFS=\, read -r x`. The lookahead lets the pipeline take it; a plain assignment
        # is tried first so `x+=(...)` is not cut short.
        | (assignment + (~command_head)) | pipeline | assignment
        # grouping and subshell come through pipeline_item, which also accepts a pipe
        # after them: `{ a; } | tee`. Listing them here first would stop the choice early.
        | declaration | declaration2
    )    
    and_or = as_node(and_or_item) + ((AND_AND | OR_OR) + (NEWLINE | comment)[:] + as_node(and_or_item))[:]

    # All four control-flow conditions now accept and_or chains:
    #   if [[ -f x ]] && (( i++ )); then ... fi
    #   while cmd1 && ! cmd2; do ... done
    # The condition may be a sequence that ends before `then`: `if diff a b; [[ $? != 0 ]]`.
    if_condition = and_or + ((STATEMENT_SEP | comment)[1:] + ~literal("then") + and_or)[:]
    elif_branch = (
        literal("elif") + if_condition + (STATEMENT_SEP | comment)[:]
        + literal("then") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
        + STATEMENT_SEP[:]
    )
    else_branch = (
        literal("else") + STATEMENT_SEP[:] + inner_statement[:]
        + STATEMENT_SEP[:]
    )

    if_stmt = (
        literal("if") + if_condition + (STATEMENT_SEP | comment)[:]
        + literal("then") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
        + STATEMENT_SEP[:]
        + elif_branch[:] + else_branch[0:1]
        + literal("fi")
    )

    # FIX 4: Support multiple loop variables: `for a b in ...` and `for a b; do ...`
    # Loop variables are plain names, so reserved words are allowed: `for repeat in ...`.
    # The first name may be any word; later names must not be the keywords `in` or `do`.
    loop_names = assign_name + filt(lambda tok: tok.string not in ("in", "do"), assign_name)[:]
    for_alt = (literal("for") + loop_names + LPAREN + argument[:] + RPAREN + (STATEMENT_SEP | comment)[:]
               + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
               + STATEMENT_SEP[:] + literal("done"))
    for_stmt = (literal("for") + loop_names + literal("in") + argument[:] + (STATEMENT_SEP | comment)[:]
                + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                + STATEMENT_SEP[:] + literal("done"))
    # `for x y; do ...` iterates over the positional parameters (no `in` list).
    for_positional = (literal("for") + loop_names + (STATEMENT_SEP | comment)[:]
                + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                + STATEMENT_SEP[:] + literal("done"))
    # zsh accepts both `foreach x (...) ... end` and the `do ... done` form.
    foreach_stmt = (literal("foreach") + identifier[1:] + LPAREN + argument[:] + RPAREN + (STATEMENT_SEP | comment)[:]
                    + ((inner_statement[:] + STATEMENT_SEP[:] + literal("end"))
                       | (literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                          + STATEMENT_SEP[:] + literal("done"))))
    select_stmt = (literal("select") + identifier + literal("in") + argument[:] + (STATEMENT_SEP | comment)[:]
                   + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                   + STATEMENT_SEP[:] + literal("done"))

    while_stmt = (literal("while") + and_or[0:1] + (STATEMENT_SEP | comment)[:]
                  + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                  + STATEMENT_SEP[:] + literal("done"))
    until_stmt = (literal("until") + and_or[0:1] + (STATEMENT_SEP | comment)[:]
                  + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
                  + STATEMENT_SEP[:] + literal("done"))
    repeat_stmt = (
        (literal("repeat") + argument + (STATEMENT_SEP | comment)[:]
         + literal("do") + (STATEMENT_SEP | comment)[:] + inner_statement[:]
         + STATEMENT_SEP[:] + literal("done"))
        # one-line form: `repeat 3 echo hi`
        | (literal("repeat") + argument + command)
    )

    # Case pattern: a `( ... )` group inside the pattern is one unit, so `-?(no_)tacot`
    # and `(darwin|freebsd)*` keep their groups. Only a `)` outside every group ends it.
    # A group continues the pattern only when the next word is glued to it (`-?(no_)tacot`).
    # `(GZIP)  echo ...`, `("0 0 fg=red")` followed by a line break or `;&`, and any group
    # followed by a space are the whole arm head, so the group's `)` is the arm closer.
    # A `)` may follow a group after a space: `+([0-9]) )` closes the arm with that `)`.
    _pattern_break = filt(lambda tok: (not tok.glued and tok.string != ")")
                          or tok.type in (TOKEN_TYPES["NEWLINE"], TOKEN_TYPES["COMMENT"])
                          or tok.string in (";", ";;", ";&", ";|"), shift)
    # A case pattern sits on one line: it never takes a newline or a comment, so an
    # arm that starts at a comment cannot scan on through `esac` to a later `)`.
    _pattern_tok = filt(lambda tok: tok.type not in (TOKEN_TYPES["NEWLINE"], TOKEN_TYPES["COMMENT"]), shift)
    _pattern_group = LPAREN + ((~RPAREN) + _pattern_tok)[:] + RPAREN + (~_pattern_break)
    case_pattern = (_pattern_group | ((~rparen_vis) + _pattern_tok))[:] + rparen_vis
    case_body = case_pattern + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:]
    # Arms that end with a terminator, then an optional final arm without one
    # (`*) cmd` directly before `esac`). The optional arm must not start at
    # `esac`: a case pattern would otherwise scan through `esac` up to the next
    # `)` in the file. The guard therefore sits after the leading separators.
    # NOTE: The guard (~literal("esac")) must be on BOTH case_arm and case_final
    # to prevent case_arm from greedily consuming `esac` and subsequent code.
    # A comment may follow the terminator: `;; # Invalid option`.
    case_arm = (STATEMENT_SEP | comment)[:] + (~literal("esac")) + case_body + (DSEMI | SEMI_AMP | SEMI_BAR) + comment[0:1]
    case_final = (STATEMENT_SEP | comment)[:] + (~literal("esac")) + case_body
    case_stmt = (
        literal("case") + argument + ZshTerminals.glued_part[0:] + STATEMENT_SEP[:] + literal("in") + STATEMENT_SEP[:]
        + case_arm[:] + case_final[0:1]
        + (STATEMENT_SEP | comment)[:] + literal("esac")
    )

    # Function names may be dynamic: `_widget_${name}() { ... }`.
    # `= () { ... }` defines a function named "=": the bare `=` is an ASSIGN_EMPTY token.
    func_name = (identifier | var_exp | ZshTerminals.assign_eq_empty)[1:]
    function_def = (
        (func_name + LPAREN + RPAREN)
        | (literal("function") + func_name + (LPAREN + RPAREN)[0:1])
    # A comment may sit on the header line: `function f # $1 user`.
    ) + (STATEMENT_SEP | comment)[:] + LBRACE + STATEMENT_SEP[:] + inner_statement[:] + STATEMENT_SEP[:] + RBRACE

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
        """Fallback for any rule without its own lint: lints the children."""
        def lint(self):
            # this node doesnt have a lint method, but its children may have.
            issues = []
            for c in children(self):
                if hasattr(c,"lint"): 
                    issues.extend(c.lint())
            return issues
            
    class argument:
        """argument ::= assign_word | _basic_arg"""
        def lint(self):
            return _expansion_issues(self)


    class prefix_assignment:
        """prefix_assignment ::= assign_word"""
        def lint(self):
            # `VAR=$x cmd` assigns without word splitting: only backticks apply.
            return _expansion_issues(self, backticks_only=True)

    class assignment:
        """assignment ::= assign_target subscript? ASSIGN_OP (assign_rhs | nothing) assign_word*"""
        def lint(self):
            return _expansion_issues(self, backticks_only=True)

    class declaration:
        """declaration ::= 'local' flag* ((assign_name | var_exp | string) (ASSIGN_OP (assign_rhs | nothing))?)+"""
        def lint(self):
            return _expansion_issues(self, backticks_only=True)

    class declaration2:
        """declaration2 ::= ('typeset' | 'declare' | 'export' | 'readonly') flag* ((assign_name | var_exp | string) (ASSIGN_OP (assign_rhs | nothing))?)+"""
        def lint(self):
            return _expansion_issues(self, backticks_only=True)


    class command_head:
        """command_head ::= identifier | colon | backtick | cmd_subst | arith_exp | var_exp | string | number"""
        def lint(self):
            return _expansion_issues(self)

        
    class test_construct:
        """test_construct ::= lbracket (~rbracket shift)* rbracket"""
        def lint(self):
            issues = [{
                "rule": "ZSH004",
                "message": (
                    "Prefer enhanced '[[ ... ]]' over legacy POSIX "
                    "'[ ... ]' test construct in zsh."
                ),
                "token": token_of(self.nodes[0]),
            }]

            issues.extend(_expansion_issues(self))
            return issues

    class redir:
        """redir ::= (named_fd | number)? ('<<<' | redir_op) argument"""
        def lint(self):
            issues = []
            for c in children(self):
                tok = token_of(c)
                if getattr(tok, "string", None) == "<<<":
                    issues.append({
                        "rule": "ZSH008",
                        "message": "Here-string '<<<' used; consider a pipe or a file.",
                        "token": tok,
                    })
                elif hasattr(c, "lint"):
                    issues.extend(c.lint())
            return issues

    class dbl_test_construct:
        """dbl_test_construct ::= dlbracket (~drbracket shift)* drbracket"""
        # [[ ... ]] performs no word splitting — suppress ZSH002 for its args.
        # Also suppresses ZSH004 (this is the recommended form).
        def lint(self):
            return []   # [[ ]] does no word splitting; recommended form

    class case_stmt:
        """case_stmt ::= 'case' argument 'in' STATEMENT_SEP* case_arm* case_final? STATEMENT_SEP* 'esac'"""
        # The case word (nodes[1]) is subject to splitting — check it.
        # Then recurse into bodies.
        def lint(self):
            def has_wildcard_case(case_node): 
                seq = []
                def walk(node):
                    if node is None:
                        return
                    kids = children(node)
                    if kids:
                        for c in kids:
                            walk(c)
                        return
                    tok = token_of(node)
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
                    "token": token_of(self.nodes[1]) if len(self.nodes) > 1 else token_of(self.nodes[0]),
                })
            for c in children(self):
                issues.extend(c.lint())
            return issues

    class script:
        """script ::= statement*"""
        def lint(self):
            issues = []
            for c in children(self):
                issues.extend(c.lint())                       
            return issues


# ============================================================
# Public entry point
# ============================================================

def _unclosed_construct(tokens):
    """Name the construct that is still open at the end of a failed parse.

    Only keywords and braces in command position count. Returns a message for the
    innermost unclosed opener, or for the first closer that does not match the
    innermost opener. Returns None when the brackets balance, so the caller can
    fall back to the farthest-token report.
    """
    openers = {"if": "fi", "case": "esac", "while": "done", "until": "done",
               "for": "done", "select": "done", "{": "}"}
    closers = {"fi", "esac", "done", "}"}
    after_ident = {"then", "do", "else", "elif"}
    # `)` ends a case pattern, so a command may start after it: `pat) if ...`.
    after_op = {";", ";;", ";&", ";|", "&&", "||", "|", "|&", "&", "(", "{", "!", ")"}
    stack = []
    prev = None
    for tok in tokens:
        if tok.type == TOKEN_TYPES["COMMENT"]:
            continue
        in_word = tok.type in (TOKEN_TYPES["IDENT"], TOKEN_TYPES["OP"])
        at_command = (prev is None or prev.type == TOKEN_TYPES["NEWLINE"]
                      or (prev.type == TOKEN_TYPES["OP"] and prev.string in after_op)
                      or (prev.type == TOKEN_TYPES["IDENT"] and prev.string in after_ident))
        if in_word and at_command:
            if tok.string in openers:
                stack.append(tok)
            elif tok.string in closers and stack:
                top = stack[-1]
                if openers[top.string] != tok.string:
                    return (f"{tok.string!r} at {tok.start} does not close "
                            f"{top.string!r} opened at {top.start}")
                stack.pop()
        prev = tok
    if stack:
        top = stack[-1]
        return f"unclosed {top.string!r} opened at {top.start}, expected {openers[top.string]!r}"
    return None


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
        # An unclosed or mismatched construct is the real problem; report it first.
        construct = _unclosed_construct(stream.tokens)
        if construct:
            raise SyntaxError(construct)
        # The statement parser stops at the first statement it cannot finish, so
        # stream.pos is that statement's first token. The farthest token any rule
        # examined is usually where the real problem is.
        index = max(stream.pos, getattr(stream, "farthest", stream.pos))
        index = min(index, len(stream.tokens) - 1)
        tok = stream.tokens[index]
        raise SyntaxError(f"Unexpected token {tok.string!r} at position {tok.start}")

    return ast.lint()


# ============================================================
# Tests
# ============================================================


def _run_self_tests():
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
        # AST helper and lint-boundary regression tests.

        _sample = lint_zsh_code(
            "GIT_OPTIONAL_LOCKS=$LOCK command git $ARGS\n"
        )
        assert any(
            issue["rule"] == "ZSH002"
            for issue in _sample
        ), "prefix/head/argument expansion not linted"


        _cmd_subst = lint_zsh_code("echo $(date)\n")
        assert any(
            issue["rule"] == "ZSH002"
            and "command substitution" in issue["message"]
            for issue in _cmd_subst
        ), "command substitution not linted"


        _backtick = lint_zsh_code("echo `date`\n")
        assert any(
            issue["rule"] == "ZSH003"
            for issue in _backtick
        ), "backtick not linted"


        _double_test = lint_zsh_code("[[ $value == $(cmd) ]]\n")
        assert not any(
            issue["rule"] == "ZSH002"
            for issue in _double_test
        ), "[[ ]] expansion exemption regressed"

        # Here-strings: every one is a mild ZSH008; an unquoted word is also ZSH002.
        _herestring_bare = lint_zsh_code("cat <<< $line\n")
        assert any(
            issue["rule"] == "ZSH008"
            for issue in _herestring_bare
        ), "here-string not counted by ZSH008"
        assert any(
            issue["rule"] == "ZSH002"
            for issue in _herestring_bare
        ), "unquoted here-string word not linted"

        _herestring_quoted = lint_zsh_code('cat <<< "$line"\n')
        assert not any(
            issue["rule"] == "ZSH002"
            for issue in _herestring_quoted
        ), "quoted here-string word wrongly linted"

        # Constructs that must parse (a failure raises SyntaxError).
        for _src in (
            "for ((i=0; i<3; i++)); do echo $i; done\n",
            "cmd1 |& cmd2 | cmd3\n",
            "repeat 3 echo hi\n",
            "cat <<-EOF\n\thi\n\tEOF\n",
        ):
            lint_zsh_code(_src)

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
            ("while IFS= read", "while IFS= read -r line; do echo $line; done\n"),
            ("IFS= read in function", "f() {\n  while IFS= read -r line; do files+=(\"$line\"); done\n}\n"),
            ("IFS= read prefix", "IFS= read -r x\n"),
            ("IFS=read no space", "IFS=read\n"),
            ("empty assign before space", "RPROMPT= \n"),
            ("empty local", "local a=\n"),
            ("function named =", "= () {\n  bc -l <<< \"$*\"\n}\n"),
            ("leading blank line then comment", "\n# header\necho a\n"),
            ("alias with dotted name", "alias fd.='fd -H -d1'\n"),
            ("test with bare equals", "test $x = 0 && echo y\n"),
            ("assign colon value", "FS=: read -ra s\n"),
            ("colon as argument", "sd : '\\n'\n"),
            ("pipe into while", "echo x | while read p; do echo $p; done\n"),
            ("pipe from redirected while", "while read d; do echo $d; done < f | sort\n"),
            ("bare dollar in word", "fd -tx remove$ /cm\n"),
            ("comment after brace", "rtd() { # remove\n  echo a\n}\n"),
            ("group before pipe", "{ echo a; } | tee -a f\n"),
            ("subshell before pipe", "( echo a ) | tee\n"),
            ("caret word argument", "grep -v ^N_.*$ file\n"),
            ("export array element", "export NAME[$i]=$INSTANCE\n"),
            ("heredoc after redirect", "cat >&2 <<EOF\nhi\nEOF\n"),
            ("redirect between arguments", "cmd 2>&1 arg\n"),
            ("comment between if condition and then", "if a\n# c\nthen\n  :\nfi\n"),
            ("comment after then", "if a; then # x\n  :\nfi\n"),
            ("= inside assignment value", "PP=dumpfile=${DMP_FILE}\n"),
            ("time prefixes a pipeline", "time ./job.ksh args | tee\n"),
            ("comment on function header line", "function f # $1 user\n{\n  echo\n}\n"),
            ("heredoc with punctuation delimiter", "sqlplus -s / <<!eof\nselect 1;\n!eof\n"),
            ("plus inside a pattern argument", "grep -E -e .+%U.+ -e .+%u.+ file\n"),
            ("assignment piped", "P=$(echo a | tr a b) |tr a b\n"),
            ("brace range word", "for r in {01..$N}; do echo $r; done\n"),
            ("reserved word as loop variable", "for repeat in x; do echo; done\n"),
            ("positional for loop", "for i do echo $i; done\n"),
            ("comment before do in while", "while [[ $c -lt 3 ]]  # limit\ndo\n  echo\ndone\n"),
            ("double bracket as argument", "eval [[ -n $x ]]\n"),
            ("quoted alias name", "alias -g 'x'='y'\n"),
            ("comparison word in test argument", "test \"x$a\" != x\n"),
            ("escaped dollar before parenthesis", "eval a=\\${b:-\\$(c \\${d})}\n"),
            ("name built from expansion before equals", "eval G_${TYPE}=\\${G_${TYPE}:-x}\n"),
            ("command substitution before equals", "eval $(echo a)=$!\n"),
            ("prefix assignment then command", "IFS=\\, read -r a b\n"),
            ("array append", "FAILED+=(\"$name\")\n"),
            ("nested parentheses in arithmetic", "((A=B-(C)))\n"),
            ("colon-led argument", "while getopts :ho SWITCH; do echo; done\n"),
            ("arithmetic glued to a flag", "typeset -L$(( N * 2 )) X\n"),
            ("assignment value then argument", "x=a b\n"),
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


def main(argv=None):
    """Lint the given zsh scripts, or run the built-in self-tests.

    Usage:
        python zsh_linter.py script.zsh [more.zsh ...]   lint files
        python zsh_linter.py -                           lint standard input
        python zsh_linter.py                             run the self-tests
    Exits 0 when clean, 1 when findings were reported, 2 on a parse error.
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="Lint zsh scripts. With no paths, run the built-in self-tests.")
    ap.add_argument("paths", nargs="*", help="script files to lint, or '-' for stdin")
    ap.add_argument("--self-test", action="store_true", help="run the built-in self-tests")
    ap.add_argument("--check-syntax", action="store_true",
                    help="only report parse errors; lint findings are not printed")
    args = ap.parse_args(argv)

    if args.self_test or not args.paths:
        _run_self_tests()
        return 0

    status = 0
    checked = failed = 0
    for path in args.paths:
        name = "<stdin>" if path == "-" else path
        checked += 1
        try:
            if path == "-":
                source = sys.stdin.read()
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            issues = lint_zsh_code(source)
        except Exception as exc:
            print(f"{name}: parse error: {type(exc).__name__}: {exc}", file=sys.stderr)
            status = 2
            failed += 1
            continue
        if args.check_syntax:
            continue
        for issue in issues:
            start = getattr(issue["token"], "start", None)
            where = f"{name}:{start[0]}:{start[1]}" if start else name
            print(f"{where}: {issue['rule']} {issue['message']}")
        if issues and status == 0:
            status = 1
    if args.check_syntax:
        print(f"checked {checked} file(s): {failed} with syntax errors")
        return 2 if failed else 0
    return status


if __name__ == "__main__":
    sys.exit(main())
