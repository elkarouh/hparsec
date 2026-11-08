import re
from hek_parsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type_node,
    filt,
    literal,
    nothing,
)

# ============================================================
# 1. Enhanced Zsh Tokenizer
# ============================================================

class Token:
    def __init__(self, type, string, start=(1, 0), end=(1, 0), line=""):
        self.type = type
        self.string = string
        self.start = start
        self.end = end
        self.line = line

    def __repr__(self):
        return f"Token({self.type!r}, {self.string!r}, {self.start!r})"

TOKEN_SPEC = [
    ("COMMENT",    r"#[^\n]*"),
    ("BACKTICK",   r"`[^`]*`"),
    ("VAR_EXP",    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*"),
    ("STRING",     r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
    ("IDENT",      r"-?[A-Za-z_][A-Za-z0-9_\-\.]*"),
    ("NUMBER",     r"\d+(?:\.\d+)?"),
    ("OP",         r"==|!=|&&|\|\||<<|>>|[=;(){}|\[\]]"),
    ("SKIP",       r"[ \t\r]+"),
    ("NEWLINE",    r"\n"),
]

TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC)
)

TOKEN_TYPES = {
    "COMMENT": 1,
    "BACKTICK": 2,
    "VAR_EXP": 3,
    "STRING": 4,
    "IDENT": 5,
    "NUMBER": 6,
    "OP": 7,
    "NEWLINE": 8,
}

def tokenize_zsh(source):
    tokens = []
    line = 1
    column = 0
    lines = source.splitlines()
    current_line_text = lines[0] if lines else ""

    for match in TOKEN_RE.finditer(source):
        kind = match.lastgroup
        value = match.group()

        if kind == "SKIP":
            column += len(value)
            continue

        if kind == "NEWLINE":
            line += 1
            column = 0
            current_line_text = lines[line - 1] if line <= len(lines) else ""
            tokens.append(Token(TOKEN_TYPES[kind], value, (line - 1, column), (line - 1, column + 1), current_line_text))
            continue

        if kind is None:
            raise SyntaxError(f"Invalid token at line {line}, column {column}")

        start = (line, column)
        end = (line, column + len(value))
        tokens.append(Token(TOKEN_TYPES[kind], value, start, end, current_line_text))
        column += len(value)

    return tokens


# ============================================================
# 2. Terminals
# ============================================================

class Terminals(Terminals):
    ASSIGN = "="
    SEMICOL = ";"
    LPAREN = "("
    RPAREN = ")"
    PIPE = "|"

    number = expect_type_node(TOKEN_TYPES["NUMBER"])
    string = expect_type_node(TOKEN_TYPES["STRING"])
    var_exp = expect_type_node(TOKEN_TYPES["VAR_EXP"])
    backtick = expect_type_node(TOKEN_TYPES["BACKTICK"])
    comment = expect_type_node(TOKEN_TYPES["COMMENT"])
    newline = expect_type_node(TOKEN_TYPES["NEWLINE"])

    l_bracket = filt(lambda tok: tok.string == "[", expect_type_node(TOKEN_TYPES["OP"]), name="[")
    r_bracket = filt(lambda tok: tok.string == "]", expect_type_node(TOKEN_TYPES["OP"]), name="]")

    reserved = {"if", "fi", "for", "in", "do", "done", "case", "esac", "while", "local", "typeset", "declare", "function", "then", "else", "elif"}

    identifier = filt(
        lambda tok: tok.string not in reserved,
        expect_type_node(TOKEN_TYPES["IDENT"]),
    )

    argument = backtick | var_exp | string | number | identifier
    statement_sep = newline | SEMICOL


# ============================================================
# 3. Helper for Checking Expression/Argument Issues
# ============================================================

def check_argument_issues(arg_node):
    issues = []
    arg_list = arg_node.nodes if hasattr(arg_node, "nodes") else [arg_node]
    for arg in arg_list:
        arg_token = arg.node if hasattr(arg, "node") else arg
        val = arg_token.string if hasattr(arg_token, "string") else str(arg_token)
        
        if isinstance(val, str):
            if val.startswith("$") and not val.startswith("${"):
                issues.append({
                    "rule": "ZSH002",
                    "message": f"Unquoted variable expansion '{val}' detected. Risk of word splitting and globbing.",
                    "token": arg_token
                })
            elif val.startswith("`") and val.endswith("`"):
                issues.append({
                    "rule": "ZSH003",
                    "message": "Prefer modern '$(...)' command substitution over legacy backticks.",
                    "token": arg_token
                })
    return issues


# ============================================================
# 4. Grammar & Style Linting Rules
# ============================================================

class ZshStyleGrammar(Grammar):
    script = statement[:]
    statement = (comment | declaration | assignment | if_stmt | for_stmt | pipeline | command) + statement_sep[:]

    declaration = literal("local") + identifier + ASSIGN + argument
    assignment = identifier + ASSIGN + argument
    test_construct = l_bracket + argument[:] + r_bracket
    
    command = identifier + argument[:]
    pipeline = command + (PIPE + command)[:]

    inner_statement = (comment | declaration | assignment | command) + statement_sep[:]
    
    # Added statement_sep[:] after 'then' and 'do' to handle leading newlines gracefully
    if_stmt = literal("if") + (test_construct | command) + statement_sep[:] + literal("then") + statement_sep[:] + inner_statement[:] + literal("fi")
    for_stmt = literal("for") + identifier + literal("in") + argument[:] + statement_sep[:] + literal("do") + statement_sep[:] + inner_statement[:] + literal("done")

    # --------------------------------------------------------
    # Style Linting Methods via Inner Classes
    # --------------------------------------------------------

    class command:
        def lint(self):
            issues = []
            cmd_parser = self.nodes[0]
            cmd_token = cmd_parser.node if hasattr(cmd_parser, "node") else cmd_parser
            cmd_name = cmd_token.string if hasattr(cmd_token, "string") else str(cmd_token)
            
            if cmd_name == "echo":
                issues.append({
                    "rule": "ZSH001",
                    "message": "Prefer native 'print' or 'printf' over legacy 'echo'.",
                    "token": cmd_token
                })

            if len(self.nodes) > 1 and self.nodes[1] is not None:
                issues.extend(check_argument_issues(self.nodes[1]))
            return issues

    class assignment:
        def lint(self):
            issues = []
            if len(self.nodes) > 1 and self.nodes[1] is not None:
                issues.extend(check_argument_issues(self.nodes[1]))
            return issues

    class declaration:
        def lint(self):
            issues = []
            if len(self.nodes) > 2 and self.nodes[2] is not None:
                issues.extend(check_argument_issues(self.nodes[2]))
            return issues

    class test_construct:
        def lint(self):
            open_bracket = self.nodes[0]
            tok = open_bracket.node if hasattr(open_bracket, "node") else open_bracket
            return [{
                "rule": "ZSH004",
                "message": "Prefer enhanced '[[ ... ]]'' over legacy POSIX '[ ... ]' test construct in zsh.",
                "token": tok
            }]

    class pipeline:
        def lint(self):
            return []

    class if_stmt:
        def lint(self):
            return []

    class for_stmt:
        def lint(self):
            return []

    class comment:
        def lint(self):
            return []

    class script:
        def lint(self):
            all_issues = []
            def traverse(node):
                if hasattr(node, "lint") and node is not self:
                    all_issues.extend(node.lint())
                if hasattr(node, "nodes") and isinstance(node.nodes, list):
                    for child in node.nodes:
                        if child is not None:
                            traverse(child)
                elif hasattr(node, "node") and node.node is not None:
                    traverse(node.node)
            
            traverse(self)
            return all_issues


# ============================================================
# 5. Public Entry Point
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
# 6. Tests including Pipelines & Control Structures
# ============================================================

if __name__ == "__main__":
    test_scripts = [
        ('Pipeline check', 'cat file.txt | grep $PATTERN\n'),
        ('If statement check', 'if [ $val -eq 1 ]; then\n  echo $USER\nfi\n'),
        ('For loop check', 'for item in $LIST; do\n  echo $item\ndone\n'),
    ]

    print("--- Running Expanded Zsh Control Flow Tests ---")
    for name, code in test_scripts:
        print(f"\nTest Case: [{name}]")
        print(f"Code:\n{code.strip()}")
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
            print("  Parse Error:", e)