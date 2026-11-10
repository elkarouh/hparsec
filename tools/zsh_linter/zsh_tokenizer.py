"""Zsh tokenizer — hand-written character-level scanner.

Handles quoting, escapes, and *balanced* delimiters, which a single regex
cannot. Inspired by CPython's tokenize module design.
"""

import re


class Token:
    __slots__ = ("type", "string", "start", "end", "line", "glued")

    def __init__(self, type, string, start=(1, 0), end=(1, 0), line="", glued=False):
        self.type = type
        self.string = string
        self.start = start
        self.end = end
        self.line = line
        # True when no whitespace separates this token from the previous one: `${a}${b}`.
        self.glued = glued

    def __repr__(self):
        return f"Token({self.type!r}, {self.string!r}, {self.start!r})"


TOKEN_TYPES = {
    "COMMENT":     1,
    "BACKTICK":    2,
    "ARITH_EXP":   3,
    "VAR_EXP":     4,
    "CMD_SUBST":   5,
    "HEREDOC":     6,
    "STRING":      7,
    "IDENT":       8,
    "NUMBER":      9,
    "OP":         10,
    "NEWLINE":    11,
    "ASSIGN_EMPTY": 12,
}

_OP_TOKENS = (
    "<<<", "<<-", "<<", ">>", ">&", "<&", ">|", "&>>", "&>",
    "&|", "&!",
    "&&", "||", "|&", "==", "!=", "=~", ";;", ";|", ";&",
    "++", "--", "+=", "-=",
    "[[", "]]",
    "=", ";", "(", ")", "{", "}", "|", "[", "]", "<", ">", "!", "&", "$",
    "+", "-", ":", "^",
)

_RESERVED = {
    "if", "then", "elif", "else", "fi",
    "for", "foreach", "in", "do", "done", "end", "select",
    "while", "until", "repeat",
    "case", "esac",
    "local", "typeset", "declare", "export", "readonly",
    "function", "time", "coproc",
}

# characters that may start or continue an IDENT
_IDENT_CHARS = "_-./*?~,%@"   # note: comma, percent, at-sign for paths/emails/format strings


def _case_keyword(source, j):
    """Return +1 if `case` starts a command at source[j], -1 for `esac`, else 0.

    Only a keyword in command position counts, so `echo case` or `x=esac` do not
    change the nesting of case statements inside a command substitution.
    """
    word = source[j:j + 4]
    if word not in ("case", "esac"):
        return 0
    if j + 4 < len(source) and source[j + 4] not in " \t\r\n;|&()":
        return 0
    k = j - 1
    while k >= 0 and source[k] in " \t":
        k -= 1
    if k >= 0 and source[k] not in "(;|&\n":
        return 0
    return 1 if word == "case" else -1


def _first_odd_quote_line(source):
    """Line number of the first non-comment line with an odd count of quote characters.

    A hint for an unterminated quote: the scan of quotes goes wrong at the line
    that holds the unbalanced one. A legitimate multi-line string can also show here.
    """
    for number, line in enumerate(source.split("\n"), 1):
        if line.lstrip().startswith("#"):
            continue
        doubles = sum(1 for i, c in enumerate(line) if c == '"' and (i == 0 or line[i - 1] != "\\"))
        singles = line.count("'")
        if doubles % 2 or singles % 2:
            return number
    return "unknown"


def _skip_paren_group(source, j):
    """Return the index just past the parenthesized group that starts at source[j] == '('.

    Quotes and backslash escapes inside the group are skipped, so `$(echo "a)")` closes
    at the right parenthesis. An unclosed group runs to the end of the source.
    """
    n = len(source)
    depth = 0
    while j < n:
        c = source[j]
        if c == "\\":
            j += 2
            continue
        if c == "#" and (j == 0 or source[j - 1] in " \t\r\n;|&("):
            # A comment inside the group runs to the end of the line: it may hold a ")".
            nl = source.find("\n", j)
            j = n if nl == -1 else nl
            continue
        if c in ("'", '"'):
            j += 1
            while j < n and source[j] != c:
                j += 2 if (source[j] == "\\" and c == '"') else 1
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def tokenize_zsh(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1
    col = 0
    lines = source.splitlines() or [""]

    def line_text(ln):
        return lines[ln - 1] if 0 < ln <= len(lines) else ""

    brace_stack = []

    def push(kind, value, start_pos):
        nonlocal col, line
        end = (start_pos[0], start_pos[1] + len(value))
        glued = bool(tokens) and tokens[-1].end == start_pos
        # `( a = b )]]` closes a double-bracket test: the `]]` is not a glued word part.
        if glued and value == "]]" and tokens[-1].string == ")" and tokens[-1].type == TOKEN_TYPES["OP"]:
            glued = False
        # Braces: a standalone { opens a group, a glued { opens a brace expansion such as
        # {a,b}. A glued } after a word closes a group only while a group is open; it
        # closes an expansion when one is open, and is literal text otherwise.
        if kind in ("IDENT", "OP") and value == "{":
            brace_stack.append("word" if glued else "group")
        elif kind in ("IDENT", "OP") and value == "}":
            if glued and tokens and tokens[-1].type in (TOKEN_TYPES["VAR_EXP"], TOKEN_TYPES["IDENT"]) \
                    and brace_stack and brace_stack[-1] == "group":
                glued = False
            if brace_stack:
                brace_stack.pop()
        tokens.append(Token(TOKEN_TYPES[kind], value, start_pos, end, line_text(start_pos[0]), glued))
        nl_count = value.count("\n")
        if nl_count:
            line += nl_count
            last_nl = value.rfind("\n")
            col = len(value) - last_nl - 1
        else:
            col += len(value)

    while i < n:
        ch = source[i]
        start = (line, col)

        if ch == "\n":
            tokens.append(Token(TOKEN_TYPES["NEWLINE"], "\n", start, (line, col + 1), line_text(line)))
            line += 1
            col = 0
            i += 1
            continue

        # line continuation: \<newline> or \<CR><newline>
        if ch == "\\" and i + 1 < n and source[i + 1] == "\n":
            i += 2
            line += 1
            col = 0
            continue
        if ch == "\\" and i + 2 < n and source[i + 1] == "\r" and source[i + 2] == "\n":
            i += 3
            line += 1
            col = 0
            continue

        if ch in " \t\r":
            i += 1
            col += 1
            continue

        if (ch == "#" and tokens and tokens[-1].end == start
                and (tokens[-1].type != TOKEN_TYPES["OP"] or tokens[-1].string in ("}", "]", "]]"))):
            # A # inside a word is literal in zsh: `${NAME#*.}` after an unquoted part.
            # After a metacharacter such as `;` it still starts a comment: `x=1;# note`.
            push("IDENT", "#", start)
            i += 1
            continue

        # A # right after an opening `((` is arithmetic, not a comment: `(( #$ != 0 ))`.
        if (ch == "#" and len(tokens) >= 2 and tokens[-1].string == "(" and tokens[-2].string == "("
                and tokens[-2].end == tokens[-1].start):
            push("IDENT", "#", start)
            i += 1
            continue

        if ch == "#":
            j = source.find("\n", i)
            if j == -1:
                j = n
            push("COMMENT", source[i:j], start)
            i = j
            continue

        if ch == "`":
            j = i + 1
            while j < n:
                if source[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if source[j] == "`":
                    j += 1
                    break
                j += 1
            push("BACKTICK", source[i:j], start)
            i = j
            continue

        if ch == "$":
            nxt = source[i + 1] if i + 1 < n else ""

            # --- $(( ... )) arithmetic ---
            if source[i:i + 3] == "$((":
                # Both parens of "$((" are open: the scan starts after them with depth 2,
                # and stops after the second ")" that closes them, never past it.
                depth = 2
                j = i + 3
                while j < n:
                    c2 = source[j]
                    if c2 == "(":
                        depth += 1
                    elif c2 == ")":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                push("ARITH_EXP", source[i:j], start)
                i = j
                continue

            # --- $( ... ) command substitution ---
            if source[i:i + 2] == "$(":
                depth = 1
                case_depth = 0
                j = i + 2
                while j < n and depth > 0:
                    if source[j] == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if source[j] == "#" and source[j - 1] in " \t\r\n;|&(":
                        # A comment inside $( ) runs to the end of the line.
                        nl = source.find("\n", j)
                        j = n if nl == -1 else nl
                        continue
                    kw = _case_keyword(source, j)
                    if kw and (kw > 0 or case_depth > 0):
                        case_depth = max(0, case_depth + kw)
                        j += 4
                        continue
                    if source[j] in ("'", '"'):
                        q = source[j]
                        j += 1
                        while j < n:
                            if source[j] == "\\" and q == '"' and j + 1 < n:
                                j += 2
                                continue
                            if source[j] == q:
                                j += 1
                                break
                            j += 1
                        continue
                    if case_depth:
                        pass  # the ")" of a case pattern does not close the substitution
                    elif source[j] == "(":
                        depth += 1
                    elif source[j] == ")":
                        depth -= 1
                    j += 1
                push("CMD_SUBST", source[i:j], start)
                i = j
                continue

            # --- ${ ... } parameter expansion ---
            if source[i:i + 2] == "${":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if source[j] == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if source[j] == "{":
                        depth += 1
                    elif source[j] == "}":
                        depth -= 1
                    j += 1
                push("VAR_EXP", source[i:j], start)
                i = j
                continue

            # --- $'...' ANSI-C quoting: one STRING token ---
            if nxt == "'":
                j = i + 2
                while j < n and source[j] != "'":
                    j += 2 if source[j] == "\\" and j + 1 < n else 1
                j = min(j + 1, n)
                push("STRING", source[i:j], start)
                i = j
                continue

            # --- $VAR, optionally with a subscript: $m[1], $m[$k] ---
            if nxt.isalpha() or nxt == "_":
                j = i + 2
                while j < n and (source[j].isalnum() or source[j] == "_"):
                    j += 1
                if j < n and source[j] == "[":
                    depth = 0
                    while j < n:
                        if source[j] == "[":
                            depth += 1
                        elif source[j] == "]":
                            depth -= 1
                            if depth == 0:
                                j += 1
                                break
                        j += 1
                push("VAR_EXP", source[i:j], start)
                i = j
                continue
            # --- $1, $@, $?, $#, etc. (positional and special) ---
            if nxt in ("@", "*", "#", "?", "!", "$", "-", "+", "~",
                       "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
                push("VAR_EXP", source[i:i + 2], start)
                i += 2
                continue

            push("OP", "$", start)
            i += 1
            continue

        # process substitution: <( ... ) or >( ... )
        if ch in ("<", ">") and i + 1 < n and source[i + 1] == "(":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if source[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if source[j] in ("'", '"'):
                    q = source[j]
                    j += 1
                    while j < n:
                        if source[j] == "\\" and q == '"' and j + 1 < n:
                            j += 2
                            continue
                        if source[j] == q:
                            j += 1
                            break
                        j += 1
                    continue
                if source[j] == "(":
                    depth += 1
                elif source[j] == ")":
                    depth -= 1
                j += 1
            push("CMD_SUBST", source[i:j], start)
            i = j
            continue

        if ch in ('"', "'"):
            q = ch
            j = i + 1
            closed = False
            while j < n:
                if source[j] == "\\" and q == '"' and j + 1 < n:
                    j += 2
                    continue
                # Inside "...", a $( ... ) may hold its own quotes: "a $(f "x") b".
                if q == '"' and source[j:j + 2] == "$(":
                    j = _skip_paren_group(source, j + 1)
                    continue
                if source[j] == q:
                    j += 1
                    closed = True
                    break
                j += 1
            if not closed:
                # Report the quote that never closes, where it opens, not at end of file.
                raise SyntaxError(f"unterminated {q} quote near {start}; "
                                  f"the first line with an odd number of quotes is {_first_odd_quote_line(source)}")
            push("STRING", source[i:j], start)
            i = j
            continue

        # `<<<` is a here-string, not the start of a here-document.
        # Leave it to the generic longest-match operator scanner below.
        if source[i:i + 3] != "<<<" and (source[i:i + 3] == "<<-" or source[i:i + 2] == "<<"):
            op_len = 3 if source[i:i + 3] == "<<-" else 2
            j = i + op_len
            while j < n and source[j] in " \t":
                j += 1
            q = None
            if j < n and source[j] in ("'", '"'):
                q = source[j]
                j += 1
            k = j
            # Any word characters may make up the delimiter: `<<!eof` is delimited by `!eof`.
            while k < n and source[k] not in " \t\r\n;|&<>()'\"":
                k += 1
            delim = source[j:k]
            if not delim:
                push("OP", source[i:i + op_len], start)
                i += op_len
                continue
            if q:
                k += 1
            # `<<-` lets the closing delimiter be indented with tabs.
            lead = r"\t*" if op_len == 3 else ""
            close_re = re.compile(rf"^{lead}{re.escape(delim)}\s*$", re.MULTILINE)
            m = close_re.search(source, k)
            if not m:
                raise SyntaxError(f"Unterminated here-doc {delim!r} at line {line}")
            body = source[i:m.end()]
            nl_count = body.count("\n")
            if nl_count:
                line += nl_count
                last_nl = body.rfind("\n")
                col = len(body) - last_nl - 1
            else:
                col += len(body)
            tokens.append(Token(TOKEN_TYPES["HEREDOC"], body, start, (line, col), line_text(start[0])))
            i = m.end()
            continue

        # generic escape: \<char> (line continuations already handled above)
        if ch == "\\" and i + 1 < n:
            j = i + 2
            # An escaped dollar before a parenthesis is literal text: `\$(cmd)` is one word.
            if source[i + 1] == "$" and j < n and source[j] == "(":
                depth = 0
                while j < n:
                    if source[j] == "(":
                        depth += 1
                    elif source[j] == ")":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
            # An escaped dollar before a brace is literal text too: `\${name}` is one word.
            if source[i + 1] == "$" and j < n and source[j] == "{":
                # Match nested braces: `\${X_${I}_R}` is one word.
                depth = 0
                k = j
                while k < n and source[k] != "\n":
                    if source[k] == "{":
                        depth += 1
                    elif source[k] == "}":
                        depth -= 1
                        if depth == 0:
                            j = k + 1
                            break
                    k += 1
            while j < n and (source[j].isalnum() or source[j] in _IDENT_CHARS):
                j += 1
            push("IDENT", source[i:j], start)
            i = j
            continue

        # `++` and `+=` must be OPs, not idents — check before ident-start
        if source[i:i + 2] in ("++", "+="):
            push("OP", source[i:i + 2], start)
            i += 2
            continue
        # single `-` alone (stdin, `cd -`, end-of-options marker) is an IDENT
        if ch == "-" and (i + 1 >= n or source[i + 1].isspace()
                          or source[i + 1] in "\n;|&()"):
            push("IDENT", "-", start)
            i += 1
            continue
        # negative number: -1, -3.14
        if ch == "-" and i + 1 < n and source[i + 1].isdigit():
            j = i + 2
            while j < n and (source[j].isdigit() or source[j] == "."):
                j += 1
            push("NUMBER", source[i:j], start)
            i = j
            continue

        # ident start: includes . @ / * ? ~ , % and '-' followed by a word-continuation char
        if (ch.isalpha() or ch == "_" or ch in "/*?~,%.@"
                or ((ch == "-" or ch == "+") and i + 1 < n
                    and not source[i + 1].isspace()
                    and source[i + 1] not in ";(){}|[]<>&")):
            j = i + 1
            starts_dash = (ch == "-" or ch == "+")
            while j < n:
                c = source[j]
                if c.isalnum() or c in _IDENT_CHARS:
                    j += 1
                elif starts_dash and c == "=":
                    j += 1
                else:
                    break
            push("IDENT", source[i:j], start)
            i = j
            continue

        if ch.isdigit():
            j = i + 1
            while j < n and (source[j].isdigit() or source[j] == "."):
                j += 1
            push("NUMBER", source[i:j], start)
            i = j
            continue

        matched = False
        for op in _OP_TOKENS:
            if source.startswith(op, i):
                # `=~` is the regex match operator only after whitespace: `[[ $x =~ re ]]`.
                # In `PATH=~/bin` it is an assignment followed by a tilde.
                if op == "=~" and not (i > 0 and source[i - 1] in " \t"):
                    continue
                # A bare `=` followed by whitespace or a separator is an empty
                # assignment (`IFS= read`); `x=y` has no space and stays OP.
                if op == "=" and (i + 1 >= len(source) or source[i + 1] in " \t\r\n;&|)"):
                    push("ASSIGN_EMPTY", op, start)
                elif op == "]]" and i > 0 and source[i - 1] == ":":
                    # The ]] of a [:class:] bracket inside [[ ]]: `[[ $x =~ [[:alpha:]] ]]`.
                    push("IDENT", op, start)
                else:
                    push("OP", op, start)
                i += len(op)
                matched = True
                break
        if matched:
            continue

        raise SyntaxError(f"Invalid character {ch!r} at line {line}, column {col}")

    return tokens
