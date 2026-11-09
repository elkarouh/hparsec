"""Zsh tokenizer — hand-written character-level scanner.

Handles quoting, escapes, and *balanced* delimiters, which a single regex
cannot. Inspired by CPython's tokenize module design.
"""

import re


class Token:
    __slots__ = ("type", "string", "start", "end", "line")

    def __init__(self, type, string, start=(1, 0), end=(1, 0), line=""):
        self.type = type
        self.string = string
        self.start = start
        self.end = end
        self.line = line

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
}

_OP_TOKENS = (
    "<<<", "<<-", "<<", ">>", ">&", "<&", ">|", "&>>", "&>",
    "&&", "||", "==", "!=", ";;", ";|", ";&",
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


def tokenize_zsh(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1
    col = 0
    lines = source.splitlines() or [""]

    def line_text(ln):
        return lines[ln - 1] if 0 < ln <= len(lines) else ""

    def push(kind, value, start_pos):
        nonlocal col
        end = (start_pos[0], start_pos[1] + len(value))
        tokens.append(Token(TOKEN_TYPES[kind], value, start_pos, end, line_text(start_pos[0])))
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
                depth = 1
                j = i + 2
                while j < n:
                    c2 = source[j]
                    if c2 == "(":
                        depth += 1
                    elif c2 == ")":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            if j < n and source[j] == ")":
                                j += 1
                            break
                    j += 1
                push("ARITH_EXP", source[i:j], start)
                i = j
                continue

            # --- $( ... ) command substitution ---
            if source[i:i + 2] == "$(":
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

            # --- $VAR ---
            if nxt.isalpha() or nxt == "_":
                j = i + 2
                while j < n and (source[j].isalnum() or source[j] == "_"):
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
            while j < n:
                if source[j] == "\\" and q == '"' and j + 1 < n:
                    j += 2
                    continue
                if source[j] == q:
                    j += 1
                    break
                j += 1
            push("STRING", source[i:j], start)
            i = j
            continue

        if source[i:i + 3] == "<<-" or source[i:i + 2] == "<<":
            op_len = 3 if source[i:i + 3] == "<<-" else 2
            j = i + op_len
            while j < n and source[j] in " \t":
                j += 1
            q = None
            if j < n and source[j] in ("'", '"'):
                q = source[j]
                j += 1
            k = j
            while k < n and (source[k].isalnum() or source[k] == "_"):
                k += 1
            delim = source[j:k]
            if not delim:
                push("OP", source[i:i + op_len], start)
                i += op_len
                continue
            if q:
                k += 1
            close_re = re.compile(rf"^{re.escape(delim)}\s*$", re.MULTILINE)
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
            while j < n and (source[j].isalnum() or source[j] in _IDENT_CHARS):
                j += 1
            push("IDENT", source[i:j], start)
            i = j
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
                or (ch == "-" and i + 1 < n
                    and not source[i + 1].isspace()
                    and source[i + 1] not in ";(){}|[]<>&")):
            j = i + 1
            starts_dash = (ch == "-")
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
                push("OP", op, start)
                i += len(op)
                matched = True
                break
        if matched:
            continue

        raise SyntaxError(f"Invalid character {ch!r} at line {line}, column {col}")

    return tokens
