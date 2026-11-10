"""Zsh linter — extended grammar for real-ish zsh scripts.

Design: check methods are attached to grammar nodes through inner classes.
Each method reads the children of its node from `self.nodes`; the docstring of
each class lists them. Argument-level expansion rules live on the `argument`
node, so commands, assignments, declarations, and case subjects share one rule
path.
"""

import re
import sys

from hparsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type_node,
    filt,
    nothing,
    ignore,
    shift,
    Parser,
    children,
    token_of,
)
from zsh_tokenizer import tokenize_zsh, TOKEN_TYPES, _RESERVED

# Rules that `--format --fix` fixes while rendering the tree. Each entry is (rule code,
# what the fix does). A fix must not change what the script does, and findings of
# rules without an entry here are only reported.
AUTO_FIXES = (
    ("ZSH002", "quote an expansion used as an assignment value"),
    ("ZSH004", "[ ... ] becomes [[ ... ]] where [[ ]] reads the words the same way"),
    ("ZSH009", "$name becomes ${name}"),
    ("ZSH010", "test ... becomes [[ ... ]] where [[ ]] reads the words the same way"),
    ("ZSH018", "typeset -i N= becomes typeset -i N=0"),
    ("ZSH022", "${1} becomes $1"),
    ("ZSH033", "NAME () { becomes function NAME {"),
)

# ============================================================
# Terminals
# ============================================================

class ZshTerminals(Terminals):
    assign = filt(lambda tok: tok.string == "=" and tok.type in (TOKEN_TYPES["OP"], TOKEN_TYPES["ASSIGN_EMPTY"]), shift)
    SEMICOL = ";"
    pipe = "|"
    pipe_amp = "|&"
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    and_and = "&&"
    or_or = "||"
    dsemi = ";;"
    semi_amp = ";&"
    semi_bar = ";|"
    plusequal = filt(lambda tok: tok.string == "+=", expect_type_node(TOKEN_TYPES["OP"]))
    minequal = filt(lambda tok: tok.string == "-=", expect_type_node(TOKEN_TYPES["OP"]))
    amp = "&"
    amp_pipe = "&|"
    amp_bang = "&!"

    # Reserved words, kept in the tree as kw_<word> nodes.
    kw_always = "always"
    kw_case = "case"
    kw_declare = "declare"
    kw_do = "do"
    kw_done = "done"
    kw_elif = "elif"
    kw_else = "else"
    kw_end = "end"
    kw_esac = "esac"
    kw_export = "export"
    kw_fi = "fi"
    kw_for = "for"
    kw_foreach = "foreach"
    kw_function = "function"
    kw_if = "if"
    kw_in = "in"
    kw_local = "local"
    kw_readonly = "readonly"
    kw_repeat = "repeat"
    kw_select = "select"
    kw_then = "then"
    kw_time = "time"
    kw_typeset = "typeset"
    kw_until = "until"
    kw_while = "while"
    BANG = "!"
    assign_op = assign | plusequal | minequal
    
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
    ) + (expect_type_node(TOKEN_TYPES["ARITH_EXP"]) | expect_type_node(TOKEN_TYPES["NUMBER"]))[0:1]

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

    STATEMENT_SEP = NEWLINE | SEMICOL
    # Any run of separators. It leaves nothing in the tree.
    SEPS = STATEMENT_SEP[:]
    # `cmd &` runs in the background; `&|` and `&!` also disown the job. They end a
    # statement like a separator, but they are kept in the tree.
    background = amp | amp_pipe | amp_bang

    # Enhance argument with glob qualifiers, subscripts, and inline assignments.
    # A glob qualifier has at least one token; `()` alone is not one (it is an empty
    # argument-less function header or anonymous function).
    glob_qual = lparen_vis + filt(lambda tok: tok.string not in ("(", ")"), shift)[1:] + rparen_vis
    subscript = lbracket + ((~rbracket) + shift)[:] + rbracket

    # FIX 5: Added ")" to glob_suffix. This ensures that in a pattern like `(a|b) )`,
    # the first `)` is consumed as part of the pattern (since it's followed by `)`),
    # and the parser correctly stops at the second `)` which acts as the arm closer.
    glob_suffix = filt(lambda tok: tok.string in ("*", "?", "[", ")"), shift)

    # A bare `=` followed by a space is ASSIGN_EMPTY; as an argument it is just a word
    # (`test $x = 0`).
    # A brace group in argument position is a brace-expansion word: `{01..$N}`, `{a,b}`.
    # Ignored in the AST, so its contents are not linted as expansions.
    brace_word = lbrace_vis + ((~rbrace_vis) + shift)[0:] + rbrace_vis
    # A `[[ ... ]]` test passed as an argument: `eval [[ -n $x ]]`.
    dbl_bracket_word = (filt(lambda tok: tok.string == "[[", expect_type_node(TOKEN_TYPES["OP"]))
                              + ((~filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"]))) + shift)[0:]
                              + filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"])))
    # A word may start with a colon: `getopts :ho SWITCH`.
    colon_word = filt(lambda tok: tok.string == ":", expect_type_node(TOKEN_TYPES["OP"]), shift) + argument_identifier[1:]
    _basic_arg = (backtick | cmd_subst | arith_exp | var_exp | heredoc | string | brace_word | dbl_bracket_word | colon_word
                  | number
                  # Extended glob: an operator before a group is one word, `+([0-9])` or `!(*.log)`.
                  | (filt(lambda tok: tok.string in ("+", "*", "?", "!", "@"), expect_type_node(TOKEN_TYPES["OP"])) + glob_qual)
                  | glob_qual | subscript | argument_identifier | expect_type_node(TOKEN_TYPES["ASSIGN_EMPTY"])
                  # A "}" glued to a word is a literal: `echo x}.log`. A separate "}" still closes a group.
                  | filt(lambda tok: tok.glued and tok.string == "}", expect_type_node(TOKEN_TYPES["OP"]))
                  # Bare pattern characters are word parts in zsh: `fd -tx remove$ dir`,
                  # `grep -v ^N_`, `grep .+%U.+`, `cmd 08:00:00`. Ignored so they are not mistaken for expansions.
                  | filt(lambda tok: tok.string in ("$", "^", "+", "!", ".", ":"), expect_type_node(TOKEN_TYPES["OP"]))
                  # `test "x$a" != x`: comparison operators are plain words to test(1).
                  | filt(lambda tok: tok.string in ("!=", "=="), expect_type_node(TOKEN_TYPES["OP"]))
                  # `]]` closes a test only after `[[`; elsewhere it is a word: `is_a_server ${X} ]]`.
                  | filt(lambda tok: tok.string == "]]", expect_type_node(TOKEN_TYPES["OP"])))
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
    # The same name=value as an argument, with its own value rule: the value of an argument is
    # word-split, while an assignment's value is not, so the two rules check different things.
    argument_value = (_basic_arg | assign_value_colon) + ((assign_eq + _basic_arg) | glued_part)[0:]
    argument_word = (assign_name + subscript[0:1] + assign_eq + argument_value) | (assign_name + assign_eq + argument_value) | (assign_name + assign_eq_empty)

# HELPERS
# The nodes that hold one expansion each: a variable, a command substitution, a backtick.
# A word of a [ ] test is a shift node holding a token.
_EXPANSION_NODES = ("var_exp", "cmd_subst", "backtick", "shift")


def _expansion_issues(words, backticks_only=False):
    """Find unquoted expansions and legacy backticks among the words of a node.

    A rule passes the children that are its own words. A word that is one expansion
    (see _EXPANSION_NODES) or a bare token is checked; a composite word (loose_word,
    argument_value, assign_value, array_literal) is skipped here, because its own
    check reports its words.
    With backticks_only, report only ZSH003 (used where word splitting does not apply).
    """
    issues = []
    for word in words:
        if _is_leaf(word):
            value, tok = word.string, word
        elif type(word).__name__ in _EXPANSION_NODES:
            value, tok = word.to_source(), token_of(word)
        else:
            continue
        issue = _expansion_issue(value, tok, backticks_only)
        if issue:
            issues.append(issue)
    return issues


def _expansion_issue(value, tok, backticks_only):
    """The ZSH002 or ZSH003 finding for one word's text, or None."""
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("`") and value.endswith("`"):
        return {"rule": "ZSH003", "message": "Use $( ) instead of backticks; backticks are hard to read and cannot be nested.",
                "token": tok}
    if backticks_only:
        return None
    if value.startswith("$(") and value.endswith(")") and not value.startswith("$(("):
        return {"rule": "ZSH002", "message": f"Unquoted command substitution '{value}' detected.", "token": tok}
    if value.startswith("$") and len(value) > 1 and not value.startswith(("${", "$((")):
        return {"rule": "ZSH002", "message": (f"Unquoted variable expansion '{value}' detected. "
                                               "Risk of word splitting and globbing."), "token": tok}
    return None


# ============================================================
# Source rendering (to_source)
# ============================================================
# Each parse node renders itself back to shell text with to_source(). Keywords
# and statement separators are rebuilt from the tree, so the output is formatted
# rather than byte-identical.

def _is_leaf(node):
    return not isinstance(node, (Parser, str))


# One level of indentation in the formatted output.
_INDENT = "    "


def _render(node, indent=""):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if _is_leaf(node):
        # With --fix, a token may have a new text (see format_zsh_code).
        if id(node) in _FIX_TOKENS:
            return _FIX_TOKENS[id(node)]
        # A heredoc token carries the newline that ends its terminator line; the
        # statement joiner supplies that newline, so it is dropped here.
        if getattr(node, "type", None) == TOKEN_TYPES["HEREDOC"]:
            return node.string.rstrip("\n")
        return node.string
    return node.to_source(indent)


def _last_leaf(node):
    """Return the last token (or str) under node, skipping empty branches."""
    if node is None or isinstance(node, str) or _is_leaf(node):
        return node
    for c in reversed(children(node)):
        leaf = _last_leaf(c)
        if leaf is not None:
            return leaf
    return None


def _join_source(nodes, indent=""):
    """Join rendered pieces with a space, except where the next token is glued.

    A comment runs to the end of its line, so a line break follows it.
    """
    out = ""
    after_comment = False
    for c in nodes:
        piece = _render(c, indent)
        if not piece:
            continue
        if _is_leaf(c) or isinstance(c, str):
            glued = bool(getattr(c, "glued", False))
        else:
            glued = c.is_glued()
        if after_comment:
            out += "\n" + indent
        elif out and not glued:
            out += " "
        out += piece
        after_comment = getattr(_last_leaf(c), "type", None) == TOKEN_TYPES["COMMENT"]
    return out


# ============================================================
# Grammar
# ============================================================

class ZshStyleGrammar(Grammar):
    # How the methods below read the tree: a rule's node has one child per kept part
    # of the rule, in self.nodes (self.node is the first). SEPS, the uppercase
    # punctuation and the lookaheads leave no child. An optional or repeated part is
    # written X[0:1] or X[0:], so it always has its child (with no nodes when absent)
    # and every part keeps its position: `keyword, names, words, header, body = self.nodes`.

    # Leading blank lines are allowed; each statement consumes its own trailing separators.
    script = SEPS + statement[0:]

    # and_or comes BEFORE if_stmt/assignment: `x=1 || cmd` and `cond; then`
    # both need and_or to be tried before the assignment fallback.
    statement = (
        # Try logical chains before their individual operands. Otherwise a
        # declaration such as `local x=1` succeeds as a prefix and leaves &&/||
        # behind for the top-level statement parser.
        try_always | function_def | anon_function
        | and_or | redir_command
        | comment | declaration | declaration2
        | case_stmt
        | if_stmt
        | for_arith | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + background[0:1] + SEPS

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
    # An argument is a grammar-level construct, not a lexical terminal: one word of a
    # command, a loop list, a case subject or a redirection target. `* 1` gives the word
    # its own node, so it has one linting entry point wherever the grammar accepts it.
    argument = (argument_word | loose_word | ZshTerminals._basic_arg) * 1

    command_head = identifier | colon | backtick | cmd_subst | arith_exp | var_exp | string | number

    # Redirections and arguments may interleave: `cat >&2 <<EOF` has a redirect
    # before the heredoc word. redir is tried first so `2>&1` is not read as the word `2`.
    # A leading `name=value` is a prefix assignment of the command: `IFS=, read x`.
    command = (
        assign_word[0:]
        + command_head
        + (redir | argument)[0:]
    )

    # Array literal is opaque; guard with (~LPAREN) so `((…))` still parses
    # as arith_stmt instead of being eaten as an array.
    # Elements may carry glob qualifiers, e.g. `x=("$v"(Nm-1))`, so a nested
    # `(...)` is consumed as one unit instead of closing the array early.
    # Assignment values and array elements are not word-split by zsh, so they are
    # parsed as plain expansions (not `argument` nodes) and are not linted.
    array_literal = LPAREN + (ZshTerminals._basic_arg | NEWLINE)[0:] + RPAREN
    assign_rhs = array_literal | ZshTerminals.assign_value

    assign_target = assign_name | number   # `0=${...}` and other numeric names

    # A declared name may be an array element: `export NAME[$i]=$x`.
    # FIX 1: The declared name may be dynamic: `typeset -ga ${cache_place}` or `"${var}"`.
    # Added `string` to allow quoted variable expansions as declaration targets.
    declared_name = assign_name + subscript[0:1]
    declared = (declared_name | var_exp | string) + (assign_op + (assign_rhs | nothing))[0:1]
    declaration = kw_local + flag[0:] + declared[1:]
    declaration2 = (kw_typeset | kw_declare
                    | kw_export | kw_readonly) + flag[0:] + declared[0:]

    # One or more `name=value` pairs on a line: `start=$a end=$b`.
    assignment = (
        assign_target + subscript[0:1]
        + (((assign_eq | plusequal | minequal) + assign_rhs)
           # `IFS= read` is a prefix assignment, not this. `A= B=` is two empty assignments.
           | (assign_eq_empty + (~argument | assign_word))
           | plusequal | minequal)
        + assign_word[:]
    )

    # [ ] and [[ ]] content is opaque so test operators remain uninterpreted.
    # The legacy [ ] lint method separately checks raw expansion tokens; [[ ]]
    # intentionally suppresses ZSH002 because it does not perform word splitting.
    # The closing ] of [ ] is a separate word: a glued one is part of a glob class such as
    # `[0-9]*` in the test and does not end it.
    test_rbracket = filt(lambda tok: tok.string == "]" and not tok.glued, shift, name="]")
    test_construct = lbracket + ((~test_rbracket) + shift)[0:] + test_rbracket
    dbl_test_construct = dlbracket + ((~drbracket) + shift)[0:] + drbracket

    redir_op = filt(
        lambda tok: tok.string in ("<", ">", ">>", "<<<", ">&", "<&", ">|", "&>", "&>>"),
        expect_type_node(TOKEN_TYPES["OP"]),
    )

    # FIX 3: Named file descriptor redirections: {fd}</dev/null or {1}>&-
    # A zsh descriptor can be a name or a numeric descriptor: `{myfd}` / `{1}`.
    # Try the braced form before the optional traditional numeric prefix; the
    # latter can otherwise succeed empty and prevent the braced form matching.
    named_fd = lbrace_vis + identifier + rbrace_vis
    # Keep the target argument in the AST so argument.check() can inspect it.
    # Only the descriptor and operator are syntactic details.
    # The here-string operator is kept in the AST so its use can be linted (ZSH008).
    here_string_op = filt(lambda tok: tok.string == "<<<", expect_type_node(TOKEN_TYPES["OP"]))
    # A redirect target may continue with glued word parts: `>${DIR}/x.log` is one word.
    redir = (named_fd | number[0:1]) + (here_string_op | redir_op) + argument + ZshTerminals.glued_part[0:]
    # Zsh permits redirection-only commands, e.g. `{myfd}</dev/null`.
    redir_command = redir[1:]

    _two_rparen = RPAREN + RPAREN
    # Parentheses nest inside arithmetic: `((A = B - (C)))`. A nested group is one unit.
    arith_nested = LPAREN + ((~RPAREN) + shift)[0:] + RPAREN
    arith_word = (~_two_rparen) + shift
    arith_body = (arith_nested | arith_word)[0:]
    arith_stmt = LPAREN + LPAREN + arith_body + RPAREN + RPAREN

    # What ends a compound command's header before its keyword: `;`, line breaks and
    # comments. A comment there stays before the keyword: `if a # why` NEWLINE `then`.
    header_end = (STATEMENT_SEP | comment)[0:]

    # The statements of a compound command, and the comments directly after its
    # opening keyword. The three bodies a loop can have share them.
    comments = (STATEMENT_SEP | comment)[0:]
    block = inner_statement[0:]
    do_body = kw_do + comments + block + SEPS + kw_done
    brace_body = LBRACE + comments + block + SEPS + RBRACE
    end_body = block + SEPS + kw_end

    # C-style loop: `for ((i=0; i<3; i++)); do ... done`
    # zsh also takes a brace body: `for ((i=0; i<n; i++)) { ... }`.
    for_arith = (kw_for + LPAREN + LPAREN + arith_body + RPAREN + RPAREN + header_end
                 + (do_body | brace_body))

    # Compound commands can sit on either side of a pipe: `echo x | while read a; do ...; done`.
    # A compound command may carry redirections: `while ...; done < f | sort`.
    # A bare `export` or `typeset` with no names can start a pipeline: `export | grep ^CC_`.
    # A declaration may be followed by redirections: `typeset -p x >/dev/null 2>&1`.
    # A compound command may take a heredoc after its redirections: `done <<EOF`.
    declared_stage = declaration2 + redir[0:]
    compound_stage = (grouping | subshell | while_stmt | until_stmt | for_stmt | if_stmt | case_stmt) + (redir | heredoc)[0:]
    pipeline_item = command | declared_stage | compound_stage

    # Operators may be followed by a line break: `a |\n  b` and `a &&\n  b`.
    # `time` is a reserved word that may prefix a pipeline: `time ./job.ksh args`.
    pipeline = kw_time[0:1] + pipeline_item + ((pipe | pipe_amp) + (NEWLINE | comment)[0:] + pipeline_item)[0:]

    # `! cmd` — command negation prefix
    # `! x=$(cmd) || ...` negates an assignment as well as a command.
    # `if ! [[ ... ]]` negates a test construct as well.
    not_command = BANG + (pipeline | assignment | dbl_test_construct | test_construct)

    inner_statement = (
        try_always | function_def | anon_function
        | and_or | redir_command
        | comment | declaration | declaration2
        | case_stmt
        | if_stmt
        | for_arith | for_alt | for_stmt | for_positional | foreach_stmt | select_stmt
        | while_stmt | until_stmt | repeat_stmt
        | subshell | grouping
    ) + background[0:1] + SEPS

    # FIX 2: and_or_item now includes declarations (`local x=1 && cmd` or `typeset x=1 || echo fail`)
    # in addition to not_command (`!`), assignment (`x=1 || cmd`), and the previous items.
    and_or_item = (
        test_construct | dbl_test_construct | arith_stmt
        # `x=$(cmd) | tr a b`: an assignment may be the left side of a pipe, tried first.
        | not_command | (assignment + ((pipe | pipe_amp) + (NEWLINE | comment)[:] + pipeline_item)[1:])
        # An assignment that a command follows is a prefix assignment of that command:
        # `IFS=\, read -r x`. The lookahead lets the pipeline take it; a plain assignment
        # is tried first so `x+=(...)` is not cut short.
        | (assignment + (~command_head)) | pipeline | assignment
        # grouping and subshell come through pipeline_item, which also accepts a pipe
        # after them: `{ a; } | tee`. Listing them here first would stop the choice early.
        | declaration | declaration2
    )
    # zsh accepts `&&` at the end of a line before a closing or branch keyword: `echo x &&` NEWLINE `fi` or `else`.
    and_or_closer = filt(lambda tok: tok.string in ("fi", "done", "esac", "else", "elif"), shift)
    and_or = and_or_item + ((and_and | or_or) + (NEWLINE | comment)[0:]
                            + (and_or_item | ~(~and_or_closer)))[0:]

    # All four control-flow conditions now accept and_or chains:
    #   if [[ -f x ]] && (( i++ )); then ... fi
    #   while cmd1 && ! cmd2; do ... done
    # The condition may be a sequence that ends before `then`: `if diff a b; [[ $? != 0 ]]`.
    if_condition = and_or + ((STATEMENT_SEP | comment)[1:] + ~kw_then + and_or)[0:]
    then_part = header_end + kw_then + comments + block + SEPS
    elif_branch = kw_elif + if_condition + then_part
    else_branch = kw_else + SEPS + block + SEPS
    if_stmt = kw_if + if_condition + then_part + elif_branch[0:] + else_branch[0:1] + kw_fi

    # FIX 4: Support multiple loop variables: `for a b in ...` and `for a b; do ...`
    # Loop variables are plain names, so reserved words are allowed: `for repeat in ...`.
    # The first name may be any word; later names must not be the keywords `in` or `do`.
    loop_names = assign_name + filt(lambda tok: tok.string not in ("in", "do"), assign_name)[:]
    for_alt = kw_for + loop_names + LPAREN + argument[0:] + RPAREN + header_end + do_body
    for_stmt = kw_for + loop_names + kw_in + argument[0:] + header_end + do_body
    # `for x y; do ...` iterates over the positional parameters (no `in` list).
    for_positional = kw_for + loop_names + header_end + do_body
    # zsh accepts both `foreach x (...) ... end` and the `do ... done` form.
    foreach_stmt = (kw_foreach + identifier[1:] + LPAREN + argument[0:] + RPAREN + header_end
                    + (end_body | do_body))
    select_stmt = kw_select + identifier + kw_in + argument[0:] + header_end + do_body

    while_stmt = kw_while + and_or[0:1] + header_end + do_body
    until_stmt = kw_until + and_or[0:1] + header_end + do_body
    repeat_loop = kw_repeat + argument + header_end + do_body
    # one-line form: `repeat 3 echo hi`
    repeat_line = kw_repeat + argument + command
    repeat_stmt = repeat_loop | repeat_line

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
    _pattern_group = lparen_vis + ((~rparen_vis) + _pattern_tok)[:] + rparen_vis + (~_pattern_break)
    case_pattern = (_pattern_group | ((~rparen_vis) + _pattern_tok))[:] + rparen_vis
    case_body = case_pattern + SEPS + block + SEPS
    # Arms that end with a terminator, then an optional final arm without one
    # (`*) cmd` directly before `esac`). The optional arm must not start at
    # `esac`: a case pattern would otherwise scan through `esac` up to the next
    # `)` in the file. The guard therefore sits after the leading separators.
    # NOTE: The guard (~kw_esac) must be on BOTH case_arm and case_final
    # to prevent case_arm from greedily consuming `esac` and subsequent code.
    # A comment may follow the terminator: `;; # Invalid option`.
    case_terminator = (dsemi | semi_amp | semi_bar) + comment[0:1]
    case_arm = comments + (~kw_esac) + case_body + case_terminator
    case_final = comments + (~kw_esac) + case_body
    case_stmt = (
        kw_case + argument + ZshTerminals.glued_part[0:] + SEPS + kw_in + SEPS
        + case_arm[0:] + case_final[0:1]
        + comments + kw_esac
    )

    # Function names may be dynamic: `_widget_${name}() { ... }`.
    # `= () { ... }` defines a function named "=": the bare `=` is an ASSIGN_EMPTY token.
    func_name = (identifier | var_exp | ZshTerminals.assign_eq_empty)[1:]
    paren_header = func_name + lparen_vis + rparen_vis
    keyword_header = kw_function + func_name + (lparen_vis + rparen_vis)[0:1]
    # A comment may sit on the header line: `function f # $1 user`.
    function_def = (paren_header | keyword_header) + header_end + LBRACE + SEPS + block + SEPS + RBRACE

    # Anonymous function: `() { body }` — zsh-specific, defined and called
    # immediately. Must appear BEFORE subshell in the choice lists because
    # `()` alone is also a valid (empty) subshell.
    anon_function = lparen_vis + rparen_vis + LBRACE + SEPS + block + SEPS + RBRACE

    subshell = lparen_vis + SEPS + block + SEPS + rparen_vis
    grouping = LBRACE + SEPS + block + SEPS + RBRACE
    # zsh try/always: `{ body } always { cleanup }`. The two groups share one line
    # with `always`.
    try_always = grouping + kw_always + grouping

    # ---------- Node methods ----------
    # One class per rule: to_source() renders the node from its rule, check() reports
    # its own findings, variables() the names it assigns or uses. A method a rule does
    # not define comes from __default__. The docstring gives the node's children.

    class __default__:
        """Fallback for every rule: how a node renders, lints and reports its names.

        The recursion over the tree lives here. A rule adds only what is its own:
        check() for its findings, variables() for the names it assigns or uses.
        """
        def to_source(self, indent=""):
            return _join_source(children(self), indent)

        def is_glued(self):
            """True when the node touches the text before it, as its first token does."""
            for child in children(self):
                if not isinstance(child, Parser):
                    return bool(getattr(child, "glued", False))
                if token_of(child) is not None:
                    return child.is_glued()
            return False

        def check(self):
            """The findings of this node's children, which check themselves the same way."""
            return self.child_issues()

        def child_issues(self):
            """The findings of every child that checks itself, in source order."""
            issues = []
            for child in children(self):
                if isinstance(child, Parser):
                    issues.extend(child.check())
            return issues

        def tests_status(self):
            """True when what this node runs first reads $?."""
            return bool(re.search(r"\$\{?\?", self.to_source()))

        def last_status(self):
            """What sets $? after this node runs: ("tee",), ("declaration",), ("command", name) or None."""
            return None

        def variables(self):
            """(event, name, token) for each name this node assigns, uses or exports."""
            found = []
            for c in children(self):
                if isinstance(c, str):
                    continue
                if _is_leaf(c):
                    found.extend(("use", name, c) for name in _uses_in(c))
                else:
                    found.extend(c.variables())
            return found

        def calls_exit(self):
            """True when running this node runs exit in the current shell."""
            return any(c.calls_exit() for c in children(self) if not isinstance(c, str) and not _is_leaf(c))

        def exit_functions(self):
            """Names of the functions defined under this node that call exit."""
            names = set()
            for c in children(self):
                if not isinstance(c, str) and not _is_leaf(c):
                    names |= c.exit_functions()
            return names

    class script:
        """script ::= statement*
        nodes: [statements]"""
        def to_source(self, indent=""):
            return "".join(statement.to_source(indent) + "\n" for statement in self.node.nodes)

        def check(self):
            return _status_issues(self.node.nodes) + self.child_issues()

    class statement:
        """statement ::= (try_always | function_def | anon_function | and_or | redir_command | comment
            | declaration | declaration2 | case_stmt | if_stmt | for_arith | for_alt | for_stmt
            | for_positional | foreach_stmt | select_stmt | while_stmt | until_stmt | repeat_stmt
            | subshell | grouping) background?
        nodes: [what it runs, background?]"""
        def tests_status(self):
            return self.node.tests_status()

        def last_status(self):
            return self.node.last_status()

    class inner_statement:
        """inner_statement ::= the same as statement, inside a compound command
        nodes: [what it runs, background?]"""
        def tests_status(self):
            return self.node.tests_status()

        def last_status(self):
            return self.node.last_status()

    class block:
        """block ::= inner_statement*
        nodes: the statements"""
        def to_source(self, indent=""):
            """One line per statement, each starting with indent."""
            return "".join(indent + statement.to_source(indent) + "\n" for statement in self.nodes)

        def check(self):
            return _status_issues(self.nodes) + self.child_issues()

    class comments:
        """comments ::= (';' | NEWLINE | comment)*
        nodes: the comments, and None for each separator"""
        def to_source(self, indent=""):
            """One line per comment, each starting with indent."""
            return "".join(indent + comment.to_source(indent) + "\n" for comment in children(self))

    class header_end:
        """header_end ::= (';' | NEWLINE | comment)*
            What ends a header line before its keyword. Kept only for its comments.
        nodes: the comments, and None for each separator"""
        def before(self, keyword, indent, separator="; "):
            """The text from the end of the header up to and including keyword.

            Without a comment it is separator + keyword: `; then`. Comments stay on the
            header line and the lines after it, and keyword starts a new line.
            """
            comments = [comment.to_source(indent) for comment in children(self)]
            if not comments:
                return separator + keyword
            output = " " + ("\n" + indent).join(comments)
            return output + "\n" + indent + keyword if keyword else output

    class do_body:
        """do_body ::= 'do' comments block 'done'
        nodes: [do, comments, block, done]"""
        def after(self, header, indent):
            """The loop's text from the end of its header to `done`."""
            _do, comments, block, _done = self.nodes
            body = indent + _INDENT
            return (header.before("do", indent) + "\n" + comments.to_source(body) + block.to_source(body)
                    + indent + "done")

    class brace_body:
        """brace_body ::= '{' comments block '}'
        nodes: [comments, block]"""
        def after(self, header, indent):
            comments, block = self.nodes
            body = indent + _INDENT
            return (header.before("{", indent, " ") + "\n" + comments.to_source(body) + block.to_source(body)
                    + indent + "}")

    class end_body:
        """end_body ::= block 'end'
        nodes: [block, end]"""
        def after(self, header, indent):
            return header.before("", indent, "") + "\n" + self.node.to_source(indent + _INDENT) + indent + "end"

    class anon_function:
        """anon_function ::= '(' ')' '{' block '}'
        nodes: [(, ), block]"""
        def to_source(self, indent=""):
            return "() {\n" + self.nodes[2].to_source(indent + _INDENT) + indent + "}"

    class paren_header:
        """paren_header ::= func_name '(' ')'
        nodes: [name, (, )]"""
        def name(self):
            return self.nodes[0]

        def has_keyword(self):
            return False

        def has_parens(self):
            return True

    class keyword_header:
        """keyword_header ::= 'function' func_name ('(' ')')?
        nodes: [function, name, parens?]"""
        def name(self):
            return self.nodes[1]

        def has_keyword(self):
            return True

        def has_parens(self):
            return bool(self.nodes[2].nodes)

    class function_def:
        """function_def ::= (paren_header | keyword_header) header_end '{' block '}'
        nodes: [header, header_end, block]"""
        def to_source(self, indent=""):
            header, header_end, block = self.nodes
            fixed = _fixing(self, "ZSH033")
            output = "function " if header.has_keyword() or fixed else ""
            output += header.name().to_source(indent)
            if header.has_parens() and not fixed:
                output += " ()"
            output += header_end.before("{", indent, " ") + "\n"
            return output + block.to_source(indent + _INDENT) + indent + "}"

        def check(self):
            header = self.node
            if header.has_keyword():
                return self.child_issues()
            # ksh rule 33. Fixed by writing `function NAME {`; in zsh both forms behave the same.
            return [_issue("ZSH033", "Declare a function with the function keyword: function NAME.",
                           token_of(header.name()), node=self)] + self.child_issues()

        def exit_functions(self):
            names = ZshStyleGrammar.__default__.exit_functions(self)
            if self.calls_exit():
                names.add(self.node.name().to_source())
            return names

    class try_always:
        """try_always ::= grouping 'always' grouping
        nodes: [body, always, cleanup]"""
        def to_source(self, indent=""):
            body, _always, cleanup = self.nodes
            return body.to_source(indent) + " always " + cleanup.to_source(indent)

    class brace_word:
        """brace_word ::= '{' word* '}'
        nodes: [{, words, }]"""
        def words(self):
            return [item.node for item in self.nodes[1].nodes]

        def to_source(self, indent=""):
            opening, _words, closing = self.nodes
            return "".join(part.to_source(indent) for part in [opening] + self.words() + [closing])

        def check(self):
            issues = _expansion_issues(self.words())
            # ksh rule 6: {NAME} with no comma or range is a variable that lost its $.
            if re.match(r"^\{[A-Za-z_][A-Za-z0-9_]*\}$", self.to_source()):
                issues.append(_issue("ZSH015", "Put $ before the variable name in braces.", token_of(self)))
            return issues + self.child_issues()

    class grouping:
        """grouping ::= '{' block '}'
        nodes: [block]"""
        def to_source(self, indent=""):
            return "{\n" + self.node.to_source(indent + _INDENT) + indent + "}"

    class subshell:
        """subshell ::= '(' block ')'
        nodes: [(, block, )]"""
        def to_source(self, indent=""):
            return "(\n" + self.nodes[1].to_source(indent + _INDENT) + indent + ")"

        def calls_exit(self):
            # exit in ( ... ) ends only the subshell.
            return False

    class case_stmt:
        """case_stmt ::= 'case' argument glued_part* 'in' case_arm* case_final? comments 'esac'
        nodes: [case, subject, glued parts, in, arms, final?, comments, esac]"""
        def to_source(self, indent=""):
            _case, subject, glued_parts, _in, arms, final, comments, _esac = self.nodes
            inner = indent + _INDENT
            output = "case " + subject.to_source(indent)
            for glued in glued_parts.nodes:
                output += glued.to_source(indent)
            output += " in\n"
            for arm in arms.nodes + final.nodes:
                output += inner + arm.to_source(inner) + "\n"
            return output + comments.to_source(inner) + indent + "esac"

        def check(self):
            _case, subject, _glued, _in, arms, final, _comments, _esac = self.nodes
            # A `*)` arm is the fallback; without one, unexpected input is silently ignored.
            if any(re.search(r"(^|[^\w.])\*\)$", arm.body().to_source().split("\n")[0])
                   for arm in arms.nodes + final.nodes):
                return self.child_issues()
            return [_issue("ZSH007", "case without a `*)` fallback — unexpected input silently ignored.",
                           token_of(subject))] + self.child_issues()

    class case_body:
        """case_body ::= case_pattern block
        nodes: [pattern, block]"""
        def to_source(self, indent=""):
            pattern, block = self.nodes
            body = indent + _INDENT
            return pattern.to_source(indent) + "".join("\n" + body + statement.to_source(body)
                                                       for statement in block.nodes)

    class case_arm:
        """case_arm ::= comments case_body case_terminator
        nodes: [comments, body, terminator]"""
        def body(self):
            return self.nodes[1]

        def to_source(self, indent=""):
            comments, body, terminator = self.nodes
            output = "".join(comment.to_source(indent) + "\n" + indent for comment in children(comments))
            inner = indent + _INDENT
            return output + body.to_source(indent) + "\n" + inner + terminator.to_source(inner)

    class case_final:
        """case_final ::= comments case_body
        nodes: [comments, body]"""
        def body(self):
            return self.nodes[1]

        def to_source(self, indent=""):
            comments, body = self.nodes
            output = "".join(comment.to_source(indent) + "\n" + indent for comment in children(comments))
            return output + body.to_source(indent)

    class named_fd:
        """named_fd ::= '{' identifier '}'
        nodes: [{, name, }]"""
        def to_source(self, indent=""):
            return "{" + self.nodes[1].to_source(indent) + "}"

    class not_command:
        """not_command ::= '!' (pipeline | assignment | dbl_test_construct | test_construct)
        nodes: [what it negates]"""
        def to_source(self, indent=""):
            return "! " + self.node.to_source(indent)

    class array_literal:
        """array_literal ::= '(' word* ')'
        nodes: [words], with None for each line break"""
        def words(self):
            return children(self.node)

        def check(self):
            return _expansion_issues(self.words(), backticks_only=True) + self.child_issues()

        def to_source(self, indent=""):
            return "(" + _join_source(self.words(), indent) + ")"

        def is_glued(self):
            # The ( that is not kept always follows = or += directly.
            return True

    class arith_stmt:
        """arith_stmt ::= '((' arith_body '))'
        nodes: [body]"""
        def to_source(self, indent=""):
            body = self.node.to_source(indent)
            return "(( " + body + " ))" if body else "(( ))"

        def is_glued(self):
            # Its first token follows the `((` that is not kept, not the text before it.
            return False

    class arith_body:
        """arith_body ::= (arith_nested | arith_word)*
        nodes: the nested groups and the words"""
        def to_source(self, indent=""):
            return _join_source(self.nodes, indent)

    class arith_word:
        """arith_word ::= one token of an arithmetic expression
        nodes: [token]"""
        def variables(self):
            # Arithmetic reads and assigns names without a $.
            found = ZshStyleGrammar.__default__.variables(self)
            tok = token_of(self)
            if _is_bare_name(tok):
                found += [("use", tok.string, tok), ("assign", tok.string, tok)]
            return found

    class arith_nested:
        """arith_nested ::= '(' token* ')'
        nodes: [tokens]"""
        def to_source(self, indent=""):
            return "(" + _join_source(self.node.nodes, indent) + ")"

    class for_arith:
        """for_arith ::= 'for' '((' arith_body '))' header_end (do_body | brace_body)
        nodes: [for, arithmetic, header_end, body]"""
        def to_source(self, indent=""):
            _for, arithmetic, header, body = self.nodes
            return "for ((" + arithmetic.to_source(indent) + "))" + body.after(header, indent)

    class for_alt:
        """for_alt ::= 'for' loop_names '(' argument* ')' header_end do_body
        nodes: [for, names, words, header_end, body]"""
        def to_source(self, indent=""):
            _for, names, words, header, body = self.nodes
            return ("for " + names.to_source(indent) + " (" + _join_source(words.nodes, indent) + ")"
                    + body.after(header, indent))

    class for_positional:
        """for_positional ::= 'for' loop_names header_end do_body
        nodes: [for, names, header_end, body]"""
        def to_source(self, indent=""):
            _for, names, header, body = self.nodes
            return "for " + names.to_source(indent) + body.after(header, indent)

    class for_stmt:
        """for_stmt ::= 'for' loop_names 'in' argument* header_end do_body
        nodes: [for, names, in, words, header_end, body]"""
        def to_source(self, indent=""):
            _for, names, _in, words, header, body = self.nodes
            output = "for " + names.to_source(indent) + " in"
            for word in words.nodes:
                output += " " + word.to_source(indent)
            return output + body.after(header, indent)

    class foreach_stmt:
        """foreach_stmt ::= 'foreach' identifier+ '(' argument* ')' header_end (end_body | do_body)
        nodes: [foreach, names, words, header_end, body]"""
        def to_source(self, indent=""):
            _foreach, names, words, header, body = self.nodes
            output = "foreach " + " ".join(name.to_source(indent) for name in names.nodes)
            output += " (" + _join_source(words.nodes, indent) + ")"
            return output + body.after(header, indent)

        def variables(self):
            found = ZshStyleGrammar.__default__.variables(self)
            return found + [("assign", name.to_source(), token_of(name)) for name in self.nodes[1].nodes]

    class select_stmt:
        """select_stmt ::= 'select' identifier 'in' argument* header_end do_body
        nodes: [select, name, in, words, header_end, body]"""
        def to_source(self, indent=""):
            _select, name, _in, words, header, body = self.nodes
            output = "select " + name.to_source(indent) + " in"
            for word in words.nodes:
                output += " " + word.to_source(indent)
            return output + body.after(header, indent)

        def variables(self):
            found = ZshStyleGrammar.__default__.variables(self)
            name = self.nodes[1]
            return found + [("assign", name.to_source(), token_of(name))]

    class repeat_loop:
        """repeat_loop ::= 'repeat' argument header_end do_body
        nodes: [repeat, count, header_end, body]"""
        def to_source(self, indent=""):
            _repeat, count, header, body = self.nodes
            return "repeat " + count.to_source(indent) + body.after(header, indent)

    class repeat_line:
        """repeat_line ::= 'repeat' argument command
        nodes: [repeat, count, command]"""
        def to_source(self, indent=""):
            _repeat, count, command = self.nodes
            return "repeat " + count.to_source(indent) + " " + command.to_source(indent)

    class while_stmt:
        """while_stmt ::= 'while' and_or? header_end do_body
        nodes: [while, condition?, header_end, body]"""
        def to_source(self, indent=""):
            keyword, condition, header, body = self.nodes
            output = keyword.to_source()
            for and_or in condition.nodes:
                output += " " + and_or.to_source(indent)
            return output + body.after(header, indent)

        def tests_status(self):
            return any(and_or.tests_status() for and_or in self.nodes[1].nodes)

    class until_stmt:
        """until_stmt ::= 'until' and_or? header_end do_body
        nodes: [until, condition?, header_end, body]"""
        def to_source(self, indent=""):
            return while_stmt.to_source(self, indent)

        def tests_status(self):
            return while_stmt.tests_status(self)

    class then_part:
        """then_part ::= header_end 'then' comments block
        nodes: [header_end, then, comments, block]"""
        def to_source(self, indent=""):
            header, _then, comments, block = self.nodes
            body = indent + _INDENT
            return header.before("then", indent) + "\n" + comments.to_source(body) + block.to_source(body)

    class if_stmt:
        """if_stmt ::= 'if' if_condition then_part elif_branch* else_branch? 'fi'
        nodes: [if, condition, then_part, elif branches, else branch?, fi]"""
        def to_source(self, indent=""):
            _if, condition, then_part, elif_branches, else_branch, _fi = self.nodes
            output = "if " + condition.to_source(indent) + then_part.to_source(indent)
            for branch in elif_branches.nodes + else_branch.nodes:
                output += indent + branch.to_source(indent)
            return output + indent + "fi"

        def tests_status(self):
            return self.nodes[1].tests_status()

    class elif_branch:
        """elif_branch ::= 'elif' if_condition then_part
        nodes: [elif, condition, then_part]"""
        def to_source(self, indent=""):
            _elif, condition, then_part = self.nodes
            return "elif " + condition.to_source(indent) + then_part.to_source(indent)

    class else_branch:
        """else_branch ::= 'else' block
        nodes: [else, block]"""
        def to_source(self, indent=""):
            return "else\n" + self.nodes[1].to_source(indent + _INDENT)

    class if_condition:
        """if_condition ::= and_or ((STATEMENT_SEP | comment)[1:] ~'then' and_or)*
        nodes: [first, more]; each item of more is [comments and separators, and_or]

            The chained conditions are joined with `; `. A comment between two of them
            ends its line, so the next condition starts on the following line.
        """
        def to_source(self, indent=""):
            first, more = self.nodes
            parts = [first]
            for item in more.nodes:
                between, and_or = item.nodes
                parts += children(between) + [and_or]
            output = ""
            after_comment = False
            for part in parts:
                if getattr(token_of(part), "type", None) == TOKEN_TYPES["COMMENT"]:
                    output += " " + part.to_source() + "\n" + indent
                    after_comment = True
                else:
                    output += ("" if after_comment or not output else "; ") + part.to_source(indent)
                    after_comment = False
            return output

        def tests_status(self):
            return self.node.tests_status()

    class loose_word:
        """loose_word ::= (assign_name | string | var_exp | cmd_subst | ...)+ assign_eq _basic_arg
        nodes: [name pieces, =, value]"""
        def check(self):
            pieces, equals, value = self.nodes
            return _expansion_issues(children(pieces) + [equals, value]) + self.child_issues()

    class dbl_bracket_word:
        """dbl_bracket_word ::= '[[' shift* ']]'
        nodes: [[[, words, ]]]"""
        def check(self):
            return _expansion_issues([item.node for item in self.nodes[1].nodes]) + self.child_issues()

    class argument_value:
        """argument_value ::= (_basic_arg | ':') ((assign_eq _basic_arg) | glued_part)*
        nodes: [first, more]; an item of more is [=, word] or a glued part"""
        def words(self):
            """The words of the value. A glued part is plain text and is not one of them."""
            first, more = self.nodes
            return [first] + [word for item in more.nodes if type(item).__name__ != "glued_part"
                              for word in item.nodes]

        def check(self):
            return _expansion_issues(self.words()) + self.child_issues()

    class assign_value:
        """assign_value ::= (_basic_arg | ':') ((assign_eq _basic_arg) | glued_part)*
        nodes: [first, more]; an item of more is [=, word] or a glued part"""
        def check(self):
            # An assigned value is not word-split: only backticks apply.
            return _expansion_issues(argument_value.words(self), backticks_only=True) + self.child_issues()

    class argument:
        """argument ::= argument_word | loose_word | _basic_arg
        nodes: [the word]"""
        def check(self):
            return _expansion_issues(self.nodes) + self.child_issues()

        def variables(self):
            # NAME=value as an argument (alias, env, make) assigns no shell variable.
            return [v for v in ZshStyleGrammar.__default__.variables(self) if v[0] == "use"]

    class assign_name:
        """assign_name ::= IDENT, where the text is a plain identifier"""
        def variables(self):
            return [("assign", self.to_source(), token_of(self))]

    class declared:
        """declared ::= (declared_name | var_exp | string) (assign_op (assign_rhs | nothing))?
        nodes: [name, value?]; the value is [operator] or [operator, right side]"""
        def empty_value(self):
            """The `=` of a plain NAME= with nothing after it, or None."""
            name, value = self.nodes
            if type(name).__name__ != "declared_name" or name.nodes[1].nodes or not value.nodes:
                return None
            operator = value.node.node
            if type(operator).__name__ == "assign" and token_of(operator).type == TOKEN_TYPES["ASSIGN_EMPTY"]:
                return token_of(operator)
            return None

    class declaration:
        """declaration ::= 'local' flag* declared+
        nodes: [local, flags, names]"""
        def check(self):
            return declaration2.check(self)

        def variables(self):
            return declaration2.variables(self)

        def last_status(self):
            return declaration2.last_status(self)

    class declaration2:
        """declaration2 ::= ('typeset' | 'declare' | 'export' | 'readonly') flag* declared*
        nodes: [keyword, flags, names]"""
        def check(self):
            _keyword, flags, names = self.nodes
            issues = []
            if any("i" in flag.to_source()[1:] for flag in flags.nodes):
                # ksh rule 11: `typeset -i N=` gets an explicit value. The fix writes N=0,
                # which is what N= means.
                for declared in names.nodes:
                    equals = declared.empty_value()
                    if equals is not None:
                        issues.append(_issue("ZSH018", "Give typeset -i an explicit value, e.g. typeset -i N=0.",
                                             equals, replace="=0"))
            return issues + self.child_issues()

        def last_status(self):
            return ("declaration",) if re.search(r"\$\(|`", self.to_source()) else None

        def variables(self):
            keyword, flags, _names = self.nodes
            found = ZshStyleGrammar.__default__.variables(self)
            # `export NAME` and `typeset -x NAME` also export the name.
            if type(keyword).__name__ == "kw_export" or any("x" in flag.to_source()[1:] for flag in flags.nodes):
                found += [("export", name, tok) for event, name, tok in found if event == "assign"]
            return found

    class declared_stage:
        """declared_stage ::= declaration2 redir*
        nodes: [declaration, redirections]"""
        def last_status(self):
            return self.node.last_status()

    class compound_stage:
        """compound_stage ::= (grouping | subshell | while_stmt | until_stmt | for_stmt | if_stmt | case_stmt)
            (redir | heredoc)*
        nodes: [compound command, redirections]"""
        def last_status(self):
            return self.node.last_status()

    class command:
        """command ::= assign_word* command_head (redir | argument)*
        nodes: [prefix assignments, head, redirections and arguments]"""
        def head(self):
            return self.nodes[1]

        def name(self):
            """The command name when it is a plain word, else None."""
            head = self.head()
            return head.to_source() if type(head).__name__ == "identifier" else None

        def arguments(self):
            return [node for node in self.nodes[2].nodes if type(node).__name__ == "argument"]

        def redirs(self):
            return [node for node in self.nodes[2].nodes if type(node).__name__ == "redir"]

        def words(self):
            return [a.to_source() for a in self.arguments()]

        def check(self):
            """Rules on one simple command: its name, its arguments and its redirections."""
            prefixes, head, rest = self.nodes
            # The command word is word-split like an argument.
            child_issues = prefixes.check() + _expansion_issues([head]) + rest.check()
            name = self.name()
            if name is None:
                return child_issues
            issues = []
            head = token_of(head)
            args = self.arguments()
            words = self.words()
            redirs = self.redirs()

            if name == "test":
                # ksh rule 2. Fixed only where [[ ]] reads the words the same way.
                safe = not redirs and _same_in_double_brackets(words)
                issues.append(_issue("ZSH010", "Use [[ ... ]] instead of test.", head, node=self if safe else None))

            if name == "Log":
                if not any(re.match(r"-[iwsf]$", w) for w in words[:3]) and any(_LOG_LEVEL.search(w) for w in words):
                    issues.append(_issue("ZSH037", "Pass a level to Log with -i, -w, -s or -f.", head))
                if args and _is_quoted(args[-1]) and re.search(r"\s[\"']$", words[-1]):
                    issues.append(_issue("ZSH040", "Remove the trailing blank(s) from the Log message.",
                                         token_of(args[-1])))
                for r in redirs:
                    if r.operator() == ">&" and r.descriptor() in (None, "1") and r.target() == "2":
                        issues.append(_issue("ZSH036", "Log already writes to stderr; remove >&2.", token_of(r)))

            if name == "cd" and words[:1] == ["-"]:
                issues.append(_issue("ZSH042", "Use cd \"${OLDPWD}\" instead of cd -; cd - prints the directory.", head))

            operands = [a for a, w in zip(args, words) if not w.startswith("-")]
            if name == "tr" and operands and not _is_quoted(operands[0]):
                issues.append(_issue("ZSH043", "Quote the arguments of tr so the shell does not expand them.",
                                     token_of(operands[0])))

            if name in ("cfmu_ftps_list", "cfmu_ftps_get") and not any(
                    w in ("-sequence", "-period", "-free_text", "-source_key") for w in words):
                position = 1 if name == "cfmu_ftps_list" else 3
                if len(operands) > position and not _is_quoted(operands[position]):
                    issues.append(_issue("ZSH045", f"Quote the file mask of {name}, or the shell resolves it locally.",
                                         token_of(operands[position])))

            if name == "alias_get" and "Value" in words:
                issues.append(_issue("ZSH041", "Use alias_get -q.", head))

            # ksh rule 38: `2>&1 >file` sends stderr to the old stdout. Moving it changes what
            # the command does, so this is reported, not fixed.
            dup = None
            for r in redirs:
                if r.descriptor() == "2" and r.operator() == ">&" and r.target() == "1":
                    dup = r
                elif dup is not None and r.operator() in (">", ">>", ">|") and r.descriptor() in (None, "1"):
                    issues.append(_issue("ZSH035", "Redirect 2>&1 after > file, not before it.", token_of(dup)))
                    break
            return issues + child_issues

        def variables(self):
            prefixes, head, rest = self.nodes
            found = []
            for prefix in prefixes.nodes:
                # VAR=x cmd sets the variable in the command's environment.
                assigned = prefix.variables()
                found += assigned + [("export", name, tok) for event, name, tok in assigned if event == "assign"]
            found += head.variables() + rest.variables()
            words = self.words()
            if self.name() == "export":
                found += [("export", w.split("=")[0], token_of(self)) for w in words]
            found += [("assign", name, token_of(self)) for name in _assigned_by(self.name(), words)]
            return found

        def calls_exit(self):
            return self.name() == "exit"

        def last_status(self):
            return ("command", self.name())

        def to_source(self, indent=""):
            if _fixing(self, "ZSH010"):
                return "[[ " + _join_source(self.arguments(), indent) + " ]]"
            return _join_source(children(self), indent)

    class pipeline:
        """pipeline ::= 'time'? pipeline_item (('|' | '|&') (NEWLINE | comment)* pipeline_item)*
        nodes: [time?, first stage, more]; each item of more is [operator, comments, stage]"""
        def stages(self):
            _time, first, more = self.nodes
            return [first] + [item.nodes[2] for item in more.nodes]

        def check(self):
            stages = [stage for stage in self.stages() if type(stage).__name__ == "command"]
            issues = []
            for left, right in zip(stages, stages[1:]):
                program = " ".join(right.words())
                if left.name() == "wc" and right.name() == "awk" and not any(re.match(r"-[lwcm]+$", w) for w in left.words()):
                    issues.append(_issue("ZSH020", "Use wc -l, wc -w or wc -c instead of wc | awk.",
                                         token_of(left)))
                if left.name() == "bmw" and right.name() == "awk" and re.search(r"print \$(2|NF)\b", program):
                    issues.append(_issue("ZSH046", "Use bmw -V VAR instead of bmw VAR | awk to read a value.",
                                         token_of(left)))
            for stage in stages[1:]:
                if stage.name() == "tee" and any(r.descriptor() == "2" and r.operator() == ">&" for r in stage.redirs()):
                    issues.append(_issue("ZSH030", "Redirect stderr before tee (e.g. cmd 2>&1 | tee f), so the file holds it.",
                                         token_of(stage.head())))
            return issues + self.child_issues()

        def tests_status(self):
            return self.stages()[0].tests_status()

        def last_status(self):
            stages = self.stages()
            if len(stages) > 1 and type(stages[-1]).__name__ == "command" and stages[-1].name() == "tee":
                return ("tee",)
            return stages[-1].last_status()

    class and_or:
        """and_or ::= and_or_item (('&&' | '||') (NEWLINE | comment)* and_or_item?)*
        nodes: [first item, more]; each item of more is [operator, comments] or [operator, comments, item]"""
        def chain(self):
            """The items, the operators and the comments between them, in source order."""
            first, more = self.nodes
            chain = [first]
            for item in more.nodes:
                operator, comments, *following = item.nodes
                chain += [operator] + children(comments) + following
            return chain

        def check(self):
            issues = []
            chain = self.chain()
            for left, op, right in zip(chain, chain[1:], chain[2:]):
                if (type(op).__name__ in ("and_and", "or_or")
                        and type(left).__name__ == type(right).__name__ == "dbl_test_construct"):
                    # ksh rule 32.
                    issues.append(_issue("ZSH032", "Combine the tests into one [[ ... ]] with && or ||.",
                                         token_of(right)))
            return issues + self.child_issues()

        def tests_status(self):
            return self.node.tests_status()

        def last_status(self):
            items = [part for part in self.chain() if type(part).__name__ not in ("and_and", "or_or")]
            return items[-1].last_status()

    class test_construct:
        """test_construct ::= '[' shift* ']'
        nodes: [[, words, ]]"""
        def words(self):
            """The tokens between [ and ]."""
            return [token_of(item) for item in self.nodes[1].nodes]

        def check(self):
            issues = [_issue(
                "ZSH004",
                "Use [[ ... ]] instead of [ ... ] in a test; [[ ]] is the enhanced test construct.",
                token_of(self.nodes[0]),
                # Fixed only where [[ ]] reads the words the same way.
                node=self if _same_in_double_brackets([t.string for t in self.words()]) else None,
            )]
            issues.extend(_expansion_issues([item.node for item in self.nodes[1].nodes]))
            issues.extend(_test_issues(self.words(), single=True))
            return issues + self.child_issues()

        def to_source(self, indent=""):
            if _fixing(self, "ZSH004"):
                return "[[ " + _join_tokens(self.words()) + " ]]"
            return _join_source(children(self), indent)

    class redir:
        """redir ::= (named_fd | number?) ('<<<' | redir_op) argument glued_part*
        nodes: [descriptor, operator, target, glued parts]"""
        def descriptor(self):
            """The number before the operator, or None: `2` in 2>&1."""
            descriptor = self.nodes[0]
            if type(descriptor).__name__ == "named_fd" or not descriptor.nodes:
                return None
            return descriptor.node.to_source()

        def operator(self):
            return self.nodes[1].to_source()

        def target(self):
            return self.nodes[2].to_source()

        def check(self):
            operator = self.nodes[1]
            if type(operator).__name__ == "here_string_op":
                return [_issue("ZSH008", "Do not use the here-string '<<<'; use a pipe or a here-document.",
                               token_of(operator))] + self.child_issues()
            return self.child_issues()

    class dbl_test_construct:
        """dbl_test_construct ::= '[[' shift* ']]'
        nodes: [[[, words, ]]]"""
        # [[ ... ]] performs no word splitting, so ZSH002 does not apply.
        def check(self):
            words = [token_of(item) for item in self.nodes[1].nodes]
            return _test_issues(words, single=False) + self.child_issues()


# ============================================================
# Style rules from the ksh checkers (docs/ksh-style-rules.md)
# ============================================================
# The grammar's check methods above call these helpers with their own node. A finding
# that names a node in "node" can be fixed: with --fix, that node's to_source asks
# _fixing() and writes the fixed form. A finding with "replace" fixes its one token.

_T = TOKEN_TYPES
_EXPANSIONS = (_T["VAR_EXP"], _T["CMD_SUBST"], _T["BACKTICK"], _T["ARITH_EXP"])
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_NAME_RE = re.compile(r"^" + _NAME + r"$")

# Set by format_zsh_code(fix=True): (id(node), rule) pairs to fix, and new token texts.
_FIX_NODES = set()
_FIX_TOKENS = {}


def _issue(rule, message, token, node=None, replace=None):
    issue = {"rule": rule, "message": message, "token": token}
    if node is not None:
        issue["node"] = node
    if replace is not None:
        issue["replace"] = replace
    return issue


def _status_issues(statements):
    """What $? holds when one of these statements tests it (ksh rules 23 to 25)."""
    issues = []
    for prev, cur in zip(statements, statements[1:]):
        if not cur.tests_status():
            continue
        status = prev.last_status()
        where = token_of(cur)
        if status == ("tee",):
            issues.append(_issue("ZSH055", "This $? is the status of tee, not of the command piped into it.",
                                 where))
        elif status == ("declaration",):
            issues.append(_issue("ZSH056", "This $? is the status of the declaration, not of the command "
                                           "substitution; assign first, then declare.", where))
        elif status and status[0] == "command" and status[1] in _EXIT_FUNCTIONS:
            issues.append(_issue("ZSH057", f"'{status[1]}' calls exit, which ends the script; use return "
                                           "in functions, or do not test $? after it.", where))
    return issues


def _fixing(node, rule):
    """True when --fix is on and this node's own finding for rule is to be fixed."""
    return (id(node), rule) in _FIX_NODES


def _join_tokens(toks):
    """Token texts joined as the source joined them: glued tokens touch."""
    out = ""
    for tok in toks:
        out += ("" if not out or tok.glued else " ") + tok.string
    return out


def _is_quoted(node):
    text = node.to_source()
    return len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]


# ---------- [ ], test and [[ ]] ----------

_FILE_TESTS = {"-a", "-b", "-c", "-d", "-e", "-f", "-g", "-h", "-k", "-p", "-r", "-s", "-t", "-u", "-w",
               "-x", "-L", "-O", "-G", "-N", "-S", "-o", "-v", "-nt", "-ot", "-ef"}
_COMPARE = {"=", "==", "!="}
_OPPOSITE = {"-eq": "-ne", "-ne": "-eq", "-lt": "-ge", "-ge": "-lt", "-gt": "-le", "-le": "-gt",
             "=": "!=", "==": "!=", "!=": "=="}


def _same_in_double_brackets(words):
    """True when [[ ]] reads these [ ] or test words the same way.

    [[ ]] does not split or glob its words, has no -a or -o, compares strings with < and >
    and reads the right side of =, == and != as a pattern, so a word with an expansion, a
    glob character or one of those operators would change the result.
    """
    for w in words:
        if w in ("-a", "-o", "(", ")", "\\(", "\\)", "<", ">", "\\<", "\\>"):
            return False
        if "$" in w or "`" in w:
            return False
        if w[:1] not in ("'", '"') and re.search(r"[*?\[]", w):
            return False
    return bool(words)


def _is_bare_name(tok):
    return tok.type == _T["IDENT"] and bool(_NAME_RE.match(tok.string))


def _is_number(tok):
    return tok.type == _T["NUMBER"] or bool(re.match(r"^[0-9]+$", tok.string))


def _test_issues(words, single):
    """Rules on the clauses of one test; single is True for [ ], False for [[ ]]."""
    issues = []
    has_expansion = any(t.type in _EXPANSIONS or (t.type == _T["STRING"] and "$" in t.string) for t in words)
    no_dollar = bool(words) and not has_expansion and not any(t.string in _FILE_TESTS for t in words)
    if no_dollar and not single:
        # ksh rule 7.
        issues.append(_issue("ZSH050", "Put $ before the variable name in this [[ ]] test.", words[0]))
    separators = {"&&", "||"} | ({"-a", "-o"} if single else set())
    clauses, clause = [], []
    for t in words:
        if t.string in separators and clause:
            clauses.append(clause)
            clause = []
        elif t.string not in ("(", ")", "\\(", "\\)"):
            clause.append(t)
    if clause:
        clauses.append(clause)
    for index, clause in enumerate(clauses):
        negated = clause[0].string == "!"
        body = clause[1:] if negated else clause
        if not body:
            continue
        if negated and body[0].string in ("-n", "-z"):
            other = "-z" if body[0].string == "-n" else "-n"
            issues.append(_issue("ZSH012", f"Use {other} instead of ! {body[0].string}.", clause[0]))
        if negated and len(body) == 3 and body[1].string in _OPPOSITE:
            issues.append(_issue("ZSH013", f"Use {_OPPOSITE[body[1].string]} instead of negating "
                                           f"{body[1].string}.", clause[0]))
        if len(body) == 2 and body[0].string in ("-n", "-z") and _is_bare_name(body[1]):
            issues.append(_issue("ZSH014", "Put $ before the variable name in this -n or -z test.", body[1]))
        if len(body) == 3 and body[1].string in _COMPARE and {body[0].string, body[2].string} & {'""', "''"}:
            issues.append(_issue("ZSH011", "Use -z or -n instead of comparing with an empty string.", body[1]))
        if (len(body) == 3 and body[1].string in _COMPARE | {"<", ">"}
                and (_is_number(body[0]) or _is_number(body[2]))):
            issues.append(_issue("ZSH017", "Use -lt, -le, -gt, -ge, -eq or -ne to compare numbers.", body[1]))
        if index > 0 and not no_dollar and not single and _is_bare_name(body[0]):
            # ksh rule 34.
            issues.append(_issue("ZSH051", "Put $ before the variable name after && or || in this test.",
                                 body[0]))
    return issues


# ---------- commands, pipelines and declarations ----------

_LOG_LEVEL = re.compile(r"\b(INFO|WARNING|SEVERE|ERROR|FATAL)\b")


# ---------- single tokens and source lines ----------

_SPECIAL_BRACED = re.compile(r"^\$\{([0-9]|[?@#*$!-])\}$")
# The same inside a double-quoted string, where no name character follows.
_SPECIAL_BRACED_IN_STRING = re.compile(r"(?<!\\)\$\{([0-9]|[?@#*$!-])\}(?![A-Za-z0-9_])")


def _special_brace_tokens(toks):
    """ksh rule 27: ${1}, ${?} and the like, where no name character follows."""
    found = []
    for i, tok in enumerate(toks):
        if tok.type == _T["STRING"] and tok.string.startswith('"') and _SPECIAL_BRACED_IN_STRING.search(tok.string):
            found.append(tok)
        elif tok.type == _T["VAR_EXP"] and _SPECIAL_BRACED.match(tok.string):
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if not (nxt is not None and nxt.glued and re.match(r"^[A-Za-z0-9_]", nxt.string)):
                found.append(tok)
    return found


def _word_issues(toks):
    """Rules on single words: expansions, double-quoted strings and plain words."""
    issues = []
    for tok in _special_brace_tokens(toks):
        issues.append(_issue("ZSH022", "Write $0, $1, $?, $@, $* and the like without braces.", tok))
    for i, tok in enumerate(toks):
        s = tok.string
        if tok.type == _T["COMMENT"]:
            continue
        # Text the shell expands. Single-quoted strings, such as awk programs, are not.
        shell = s if tok.type in (_T["VAR_EXP"], _T["CMD_SUBST"]) or (
            tok.type == _T["STRING"] and s.startswith('"')) else ""
        if shell:
            if re.search(r"(?<!\\)\$\*|\$\{\*\}", shell):
                issues.append(_issue("ZSH023", "Use $@ instead of $*, unless this is documented.", tok))
            if re.search(r"(?<!\\)\$(\{NF\}|NF\b)", shell):
                issues.append(_issue("ZSH029", "NF is an awk field; do not expand it in the shell.", tok))
            if re.search(r"\$\{OPC_(SERVICE_NAME|USER)(?![A-Za-z0-9_])", shell):
                issues.append(_issue("ZSH049", "Write $OPC_USER and $OPC_SERVICE_NAME without braces; "
                                               "OML/OBM reads them literally.", tok))
            if re.search(r"\$\{[A-Za-z0-9_]*\s+[^\s}]*\}", shell):
                issues.append(_issue("ZSH016", "No whitespace is allowed in a variable name in ${...}.", tok))
        if tok.type == _T["CMD_SUBST"] and s.startswith("$(cm_where") and tok.glued and i:
            if toks[i - 1].string.endswith(".") and "/" in _join_tokens(toks[max(0, i - 4):i]):
                issues.append(_issue("ZSH034", "Use ! instead of . to separate SUBSYSTEM and VERSION in a path.",
                                     toks[i - 1]))
        if tok.type in (_T["IDENT"], _T["STRING"], _T["VAR_EXP"]):
            if re.search(r"\by/n\b", s, re.IGNORECASE):
                issues.append(_issue("ZSH038", "Use the confirm script instead of asking y/n.", tok))
            if re.search(r"\.LATEST(?!_)", s):
                issues.append(_issue("ZSH047", "Use .LATEST_GOOD instead of .LATEST.", tok))
            if "CFMU_OS" in s:
                issues.append(_issue("ZSH048", "CFMU_OS is probably obsolete.", tok))
    return issues


class _Pos:
    """A location for a finding that comes from the source text rather than a token."""
    __slots__ = ("start",)

    def __init__(self, line, col):
        self.start = (line, col)


def _whitespace_issues(source, toks):
    """Trailing blanks and tabs. The tree drops whitespace, so these read the source lines.

    Here-document bodies are data and are skipped.
    """
    skip = set()
    for tok in toks:
        if tok.type == _T["HEREDOC"]:
            skip.update(range(tok.start[0], tok.start[0] + tok.string.count("\n") + 1))
    issues = []
    for n, line in enumerate(source.split("\n"), 1):
        if n in skip:
            continue
        if line != line.rstrip(" \t"):
            issues.append(_issue("ZSH021", "Remove the trailing blank(s).", _Pos(n, len(line.rstrip(" \t")))))
        if "\t" in line:
            issues.append(_issue("ZSH044", "Use spaces, not a tab character.", _Pos(n, line.index("\t"))))
    return issues


def _token_fixes(toks):
    """New texts, by id(token), for the fixes made on single tokens: ZSH009, ZSH002 and ZSH022."""
    fixes = {}
    spans = {}
    for tok, start, end, name in _bare_spans(toks):
        spans.setdefault(id(tok), (tok, []))[1].append((start, end, name))
    for tok, found in spans.values():
        s = tok.string
        for start, end, name in sorted(found, reverse=True):
            s = s[:start] + "${" + name + "}" + s[end:]
        fixes[id(tok)] = s
    # ZSH002: an unquoted $name or $(cmd) as an assignment value is quoted. zsh does not
    # split assignment values, so this only changes the style.
    for prev, tok in zip(toks, toks[1:]):
        flagged = (tok.string.startswith("$") and len(tok.string) > 1
                   and not tok.string.startswith(("${", "$((")))
        if flagged and prev.type == _T["OP"] and prev.string == "=" and prev.end == tok.start:
            fixes[id(tok)] = '"' + fixes.get(id(tok), tok.string) + '"'
    for tok in _special_brace_tokens(toks):
        fixes[id(tok)] = _SPECIAL_BRACED_IN_STRING.sub(r"$\1", fixes.get(id(tok), tok.string))
    return fixes


# ---------- variables and return codes ----------

# Names the environment, the shell or the site sets before the script runs (ksh rule 21).
EXEMPT = frozenset({
    "APPLICATION_INSTANCE_KEY", "CFMU_TEMP_DIR", "CLEARCASE_ROOT", "CMA_WORKSPACE",
    "CMA_WORKSPACE_DATA_DIRECTORY", "CMA_WORKSPACE_NM_REPOSITORY_DIRECTORY", "CMA_WORKSPACE_ROOT",
    "CM_ROOT", "CM_SYSTEM", "DATA_FILES", "DISPLAY", "ENABLE_UPDATE_STATISTICS", "GCOV_PREFIX", "IFS",
    "NF", "OPTARG", "OPTIND", "PATCHES_DIR", "PATH", "PS1", "PS2", "PS3", "PWD", "REPLY", "SCRIPT",
    "SECONDS", "SHARED_AREA", "SVLOGS", "TMP_ROOT", "TZ", "WORK_DIR", "WORK_ROOT",
})
# zsh adaptation, not in the ksh checker: variables a login shell or a terminal provides.
LOGIN_ENV = frozenset({
    "BASH_VERSION", "COLUMNS", "DISPLAY", "EDITOR", "HISTFILE", "HISTSIZE", "HOME", "HOST", "HOSTNAME",
    "LANG", "LC_ALL", "LC_CTYPE", "LESS", "LINES", "LOGNAME", "MACHTYPE", "OLDPWD", "OSTYPE", "PAGER",
    "PWD", "SAVEHIST", "SHELL", "SSH_CONNECTION", "SSH_TTY", "TERM", "TMPDIR", "TMUX", "TTY", "USER",
    "USERNAME", "VISUAL", "WAYLAND_DISPLAY", "ZDOTDIR", "ZSH_VERSION",
})
_ENV_PREFIXES = ("XDG_", "LC_", "ZSH", "ZPLUG", "ANTIGEN")
# Set by define_configuration; they may be assigned only in a file whose name has that word.
DEFINE_CONFIGURATION = frozenset({
    "APPLICATION", "CONFIGURATION_SYSTEM", "CONFIGURATION_TYPE", "DB_FUNCTION", "ENTERPRISE_ID",
    "ENV_UPDATE_USER", "ENV_UPDATE_USER_PASSWD", "EXER_TITLE", "HOSTS_ALL", "LOCAL_STATIONS",
    "OTHER_INSTANCE", "PACKAGE_NAME", "PHYSICAL_HOSTS_ALL", "PHYSICAL_SERVERS", "REFERENCE_INSTANCE",
    "SYSTEM_LOCATION", "SYSTEM_PAIR", "SYSTEM_TEMPLATE",
})
# ksh read-only variables, and the ones a sudo login sets (ksh rule 20).
KSH_READ_ONLY = frozenset({
    "EGID", "ENV", "EUID", "GID", "HISTCMD", "LINENO", "PPID", "RANDOM", "SUDO_COMMAND", "SUDO_GID",
    "SUDO_UID", "SUDO_USER", "TTYIDLE", "UID", "USERNAME",
})

# $NAME, ${NAME...}, ${#NAME}, ${+NAME}, ${(flags)NAME}.
_USE = re.compile(r"(?<!\\)\$(?:\{[#+^=~]*(?:\([^)]*\))?)?(" + _NAME + r")")
# A bare name in arithmetic; $+name and name[...] are lookups in an associative array.
_ARITH_NAME = re.compile(r"(?<![\w$+])(" + _NAME + r")(?![\w\[(])")


def _is_env(name):
    return name in EXEMPT or name in LOGIN_ENV or name.startswith(_ENV_PREFIXES)


def _uses_in(tok):
    s = tok.string
    if tok.type == _T["COMMENT"] or (tok.type == _T["STRING"] and not s.startswith('"')):
        return []
    names = [m.group(1) for m in _USE.finditer(s)]
    if tok.type == _T["ARITH_EXP"] or (tok.type == _T["CMD_SUBST"] and s.startswith("$((")):
        names += _ARITH_NAME.findall(re.sub(r"\[[^\]]*\]", "", s[3:-2]))
    return names


def _assigned_by(name, words):
    """Names a command assigns through its arguments: read, getopts, set -A and print -v."""
    if name == "read":
        targets, skip = [], False
        for i, w in enumerate(words):
            if skip:
                skip = False
            elif w.startswith("-"):
                if "A" in w[1:] and i + 1 < len(words):
                    targets.append(words[i + 1])
                    skip = True
                elif w in ("-d", "-k", "-t", "-u"):
                    skip = True
            else:
                targets.append(w.split("?", 1)[0])
        return targets
    if name == "getopts":
        return words[1:2] + ["OPTARG"]
    if name == "set" and words[:1] in (["-A"], ["-a"]):
        return words[1:2]
    if name in ("print", "printf") and words[:1] == ["-v"]:
        return words[1:2]
    return []


# Functions of the script being linted that call exit; set by lint_zsh_code.
_EXIT_FUNCTIONS = set()


def _variable_issues(ast, filename=""):
    """ksh rules 16, 17 and 20: names used and not assigned, assigned and not used, read-only."""
    assigned, used, exported = {}, {}, set()
    for event, name, tok in ast.variables():
        if not _NAME_RE.match(name):
            continue
        if event == "export":
            exported.add(name)
            continue
        table = assigned if event == "assign" else used
        if name not in table or tok.start < table[name].start:
            table[name] = tok
    issues = []
    for name, tok in sorted(used.items(), key=lambda kv: kv[1].start):
        if name in assigned or _is_env(name) or name in KSH_READ_ONLY or name in DEFINE_CONFIGURATION:
            continue
        issues.append(_issue("ZSH052", f"'{name}' is used but not assigned in this file; it may be set elsewhere.",
                             tok))
    for name, tok in sorted(assigned.items(), key=lambda kv: kv[1].start):
        if name not in used and name not in exported and not _is_env(name):
            issues.append(_issue("ZSH053", f"'{name}' is assigned but never used; remove it or check it is exported.",
                                 tok))
        if name in KSH_READ_ONLY:
            issues.append(_issue("ZSH054", f"'{name}' is a read-only shell variable; assigning it is likely a bug.",
                                 tok))
        elif name in DEFINE_CONFIGURATION and "define_configuration" not in filename:
            issues.append(_issue("ZSH054", f"'{name}' is set by define_configuration; do not assign it here.", tok))
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


_PLAIN_NAME = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")
# A bare name inside a double-quoted string: not escaped, not followed by a name
# character or a subscript.
_STRING_NAME = re.compile(r"(?<!\\)\$([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_\[])")


# Names that OML/OBM reads as literals, so they must stay bare: $OPC_USER, not ${OPC_USER}.
# The ksh style check ZSH049 reports the braced form.
UNBRACED_NAMES = frozenset({"OPC_SERVICE_NAME", "OPC_USER"})


def _bare_spans(tokens):
    """(token, start, end, name) for each bare name that should be written ${name}.

    start and end are offsets inside token.string. A bare $name token is the whole
    token; inside a double-quoted string each match is found with a regex. $1-style
    positionals, special parameters, a name followed by a subscript and the names in
    UNBRACED_NAMES are skipped.
    """
    spans = []
    for i, tok in enumerate(tokens):
        if tok.type == TOKEN_TYPES["VAR_EXP"] and _PLAIN_NAME.match(tok.string):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.glued and nxt.string.startswith("["):
                continue
            if tok.string[1:] in UNBRACED_NAMES:
                continue
            spans.append((tok, 0, len(tok.string), tok.string[1:]))
        elif tok.type == TOKEN_TYPES["STRING"] and tok.string.startswith('"'):
            for m in _STRING_NAME.finditer(tok.string):
                if m.group(1) in UNBRACED_NAMES:
                    continue
                spans.append((tok, m.start(), m.end(), m.group(1)))
    return spans


def _bare_variable_issues(tokens):
    """ZSH009 findings for each bare name, inside a token or a double-quoted string."""
    return [
        {
            "rule": "ZSH009",
            "message": f"Write '${{{name}}}' instead of '${name}'.",
            "token": tok,
        }
        for tok, _start, _end, name in _bare_spans(tokens)
    ]


def _parse(source):
    """Parse a script; return (ast, tokens) or raise SyntaxError."""
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
    return ast, tokens


def format_zsh_code(source, fix=False):
    """Return the script rendered from its parse tree (see each rule's to_source).

    With fix, the findings of the AUTO_FIXES rules are fixed as the tree is rendered.
    """
    ast, tokens = _parse(source)
    if not fix:
        return ast.to_source()
    fixed = {rule for rule, _how in AUTO_FIXES}
    _FIX_TOKENS.update(_token_fixes(tokens))
    for issue in ast.check():
        if issue["rule"] not in fixed:
            continue
        if "node" in issue:
            _FIX_NODES.add((id(issue["node"]), issue["rule"]))
        if "replace" in issue:
            _FIX_TOKENS[id(issue["token"])] = issue["replace"]
    try:
        return ast.to_source()
    finally:
        _FIX_NODES.clear()
        _FIX_TOKENS.clear()


def lint_zsh_code(source, filename=""):
    ast, tokens = _parse(source)
    global _EXIT_FUNCTIONS
    _EXIT_FUNCTIONS = ast.exit_functions()
    issues = (ast.check() + _bare_variable_issues(tokens) + _word_issues(tokens)
              + _whitespace_issues(source, tokens) + _variable_issues(ast, filename))
    # A finding without a fix carries node=None; drop the keys main() does not print.
    for issue in issues:
        issue.pop("node", None)
        issue.pop("replace", None)
    return issues


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

        # Rules from the ksh checkers: each one fires on its example and not on the corrected form.
        def _style(code):
            return lint_zsh_code(code)
        _style_cases = [
            ("ZSH010", "if test -f x; then\n  :\nfi\n", "if [[ -f x ]]; then\n  :\nfi\n"),
            ("ZSH011", '[[ $a == "" ]]\n', "[[ -z $a ]]\n"),
            ("ZSH013", "[[ ! $x -eq 1 ]]\n", "[[ $x -ne 1 ]]\n"),
            ("ZSH016", "echo ${MY VAR}\n", "echo ${MY_VAR}\n"),
            ("ZSH017", "[[ $x < 3 ]]\n", "[[ $x -lt 3 ]]\n"),
            ("ZSH018", "typeset -i N=\n", "typeset -i N=0\n"),
            ("ZSH020", "wc | awk '{print $1}'\n", "wc -l f\n"),
            ("ZSH021", "echo a  \n", "echo a\n"),
            ("ZSH022", "echo ${1}\n", "echo $1\n"),
            ("ZSH023", "echo $*\n", "echo $@\n"),
            ("ZSH029", "echo ${NF}\n", "echo ${x}\n"),
            ("ZSH030", "cmd | tee f 2>&1\n", "cmd 2>&1 | tee f\n"),
            ("ZSH032", "[[ -n $a ]] && [[ -n $b ]]\n", "[[ -n $a && -n $b ]]\n"),
            ("ZSH033", "f ()\n{\n:\n}\n", "function f\n{\n:\n}\n"),
            ("ZSH034", "x=/a.$(cm_where)\n", "x=/a!$(cm_where)\n"),
            ("ZSH035", "cmd 2>&1 >f\n", "cmd >f 2>&1\n"),
            ("ZSH036", "Log msg >&2\n", "Log msg\n"),
            ("ZSH037", 'Log "ERROR x"\n', 'Log -i "x"\n'),
            ("ZSH038", "echo y/n\n", "confirm\n"),
            ("ZSH040", 'Log "done "\n', 'Log "done"\n'),
            ("ZSH041", "alias_get X Value\n", "alias_get -q X\n"),
            ("ZSH042", "cd -\n", 'cd "${OLDPWD}"\n'),
            ("ZSH043", "tr a-z A-Z\n", 'tr "a-z" "A-Z"\n'),
            ("ZSH044", "echo\ta\n", "echo a\n"),
            ("ZSH045", "cfmu_ftps_list SVC *.txt\n", 'cfmu_ftps_list SVC "*.txt"\n'),
            ("ZSH046", "bmw VAR | awk '{print $2}'\n", "bmw -V VAR\n"),
            ("ZSH047", "x=$VAR.LATEST\n", "x=$VAR.LATEST_GOOD\n"),
            ("ZSH048", "echo $CFMU_OS\n", "echo $OSTYPE\n"),
        ]
        _style_cases.append(("ZSH050", "[[ a = b ]]\n", "[[ $a = b ]]\n"))
        _style_cases.append(("ZSH051", "if [[ -n $a && x ]]; then :; fi\n", "if [[ -n $a && -n $x ]]; then :; fi\n"))
        _style_cases.append(("ZSH049", "echo ${OPC_USER}\n", "echo $OPC_USER\n"))
        for _code, _bad, _good in _style_cases:
            assert any(i["rule"] == _code for i in _style(_bad)), f"{_code} not reported"
            assert not any(i["rule"] == _code for i in _style(_good)), f"{_code} reported on the fix"
        assert not any(i["rule"] == "ZSH009" for i in lint_zsh_code("echo $OPC_USER\n")), "OPC_USER still braced"
        # Variable and return-code checks.
        _flow = _style
        _flow_cases = [
            ("ZSH052", "echo $NOT_SET_ANYWHERE_X\n", "NOT_SET_ANYWHERE_X=1\necho $NOT_SET_ANYWHERE_X\n"),
            ("ZSH053", "unused_var_q=1\n", "unused_var_q=1\necho $unused_var_q\n"),
            ("ZSH054", "UID=5\n", "myuid=5\n"),
            ("ZSH055", "cmd | tee f\necho $?\n", "cmd | tee f\necho done\n"),
            ("ZSH056", "typeset -i N=$(cmd)\necho $?\n", "N=$(cmd)\necho $?\n"),
            ("ZSH057", "f() {\n  exit 1\n}\nf\necho $?\n", "f() {\n  return 1\n}\nf\necho $?\n"),
        ]
        for _code, _bad, _good in _flow_cases:
            assert any(i["rule"] == _code for i in _flow(_bad)), f"{_code} not reported"
            assert not any(i["rule"] == _code for i in _flow(_good)), f"{_code} reported on the fix"
        print("Flow rules OK")
        # --format --fix: the fixed script parses, and lint no longer reports the fixed findings.
        _fix_cases = [
            ("ZSH002", "env x=$a\n"),
            ("ZSH004", "if [ -f x ]; then\n  :\nfi\n"),
            ("ZSH009", "echo \"$HOME\"\n"),
            ("ZSH010", "if test -f x; then\n  :\nfi\n"),
            ("ZSH018", "typeset -i N=\necho \"${N}\"\n"),
            ("ZSH022", "x=${1}\n"),
            ("ZSH033", "f () {\n  :\n}\n"),
        ]
        _fixed_rules = {rule for rule, _how in AUTO_FIXES}
        for _code, _bad in _fix_cases:
            assert any(i["rule"] == _code for i in lint_zsh_code(_bad)), f"{_code} not reported before the fix"
            _out = format_zsh_code(_bad, fix=True)
            _left = [i["rule"] for i in lint_zsh_code(_out) if i["rule"] in _fixed_rules]
            assert not _left, f"{_code}: {_left} still reported after --fix: {_out!r}"
        # Unsafe forms are reported but left as they are.
        for _code, _bad in (("ZSH004", "[ $x = a ]\n"), ("ZSH004", "[ -f a -a -f b ]\n"), ("ZSH010", "test a* = b\n")):
            assert _code in [i["rule"] for i in lint_zsh_code(format_zsh_code(_bad, fix=True))], f"{_code} fixed unsafely"
        # Each word reports its own expansions, by the context it is in: an argument is
        # word-split (ZSH002 and ZSH003), an assignment value only reports backticks (ZSH003).
        for _bad, _want, _not in (("alias g=$b\n", "ZSH002", None), ("[ $(c) = x ]\n", "ZSH002", None),
                                  ("eval $(echo a)=$!\n", "ZSH002", None), ("for r in {01..$N}; do :; done\n", "ZSH002", None),
                                  ("x=$a\n", None, "ZSH002"), ("typeset z=`e`\n", "ZSH003", None)):
            _rules = [i["rule"] for i in lint_zsh_code(_bad)]
            assert _want is None or _want in _rules, f"{_bad!r}: {_want} not reported: {_rules}"
            assert _not is None or _not not in _rules, f"{_bad!r}: {_not} reported"
        # Formatting keeps what the script does: background jobs and a flag's number.
        _kept = "sleep 1 &\nwl-copy &>/dev/null &|\nfoo &!\ntypeset -F 2 SECONDS\ntypeset -L$(( N * 2 )) X\n"
        assert format_zsh_code(_kept) == _kept, format_zsh_code(_kept)
        # Bodies are indented, and a comment before a keyword stays before it.
        _nested = ("if [[ -n ${HOME}/x(#qN.mh+24) ]] # stale\nthen\n    for f in a b; do\n"
                   "        echo \"${f}\"\n    done\nfi\n"
                   "if diff a b; [[ $? != 0 ]]; then\n    :\nfi\n")
        assert format_zsh_code(_nested) == _nested, format_zsh_code(_nested)
        print("Fixes OK")
        print("Style rules OK")

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
        python zsh_linter.py --format script.zsh         print the reformatted script
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
    ap.add_argument("--format", action="store_true",
                    help="print each script reformatted to stdout instead of linting it")
    ap.add_argument("--fix", action="store_true",
                    help="fix the AUTO_FIXES findings while formatting (use with --format)")
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
            if args.format:
                sys.stdout.write(format_zsh_code(source, fix=args.fix))
                continue
            issues = lint_zsh_code(source, filename=name)
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
