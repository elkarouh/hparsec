#!/usr/bin/env python
"""Python 2.7 Parser using hek_parser combinator framework.

Supports Python 2 specific features:
- print statement: print x, print >>file, print "hello"
- exec statement: exec code in globals, locals
- backtick repr: `x`
- <> operator (alternative to !=)
- Long literals: 123L
- Octal: 0755
"""

from hek_parser import (Input, method, fw, literal, G, shift, nothing,
    ignore, expect, expect_type, expect_re, filt, fmap, sequence,
    IDENTIFIER, NUMBER, STRING, INTEGER, FLOAT,
    LPAREN, RPAREN, LBRACE, RBRACE, LBRACKET, RBRACKET,
    COMMA, SEMICOLON, COLON, EQUAL, DOT,
    PLUS, MINUS, STAR, SLASH, PERCENT, DOUBLESTAR,
    AMPER, VBAR, CIRCUMFLEX, LEFTSHIFT, RIGHTSHIFT,
    LESS, GREATER, EQEQUAL, NOTEQUAL, LESSEQUAL, GREATEREQUAL,
    Parser, apply_parsing_context)
import tokenize as tkn

# Python 2 number literal - consumes optional L suffix
PYTHON2_NUMBER = NUMBER + (expect(tkn.NAME, 'L') | expect(tkn.NAME, 'l'))[:]

@method(PYTHON2_NUMBER)
def to_py(self):
    n = self.nodes[0]
    return python2_number(n)

# Python 2 number literal helper (handles 123L, 0755)
def python2_number(n):
    s = n.node if hasattr(n, "node") else str(n)
    if s.endswith(("L", "l")):
        return NumberLit(s[:-1], is_long=True)
    if s.startswith("0") and len(s) > 1 and s[1].isdigit():
        return NumberLit(s, is_octal=True)
    return NumberLit(s)

# Python 2 Keywords
PRINT = literal("print")
EXEC = literal("exec")
DEF = literal("def")
RETURN = literal("return")
IF = literal("if")
ELSE = literal("else")
ELIF = literal("elif")
WHILE = literal("while")
FOR = literal("for")
IN = literal("in")
IS = literal("is")
NOT = literal("not")
AND = literal("and")
OR = literal("or")
LAMBDA = literal("lambda")
CLASS = literal("class")
PASS = literal("pass")
BREAK = literal("break")
CONTINUE = literal("continue")
ASSERT = literal("assert")
DEL = literal("del")
GLOBAL = literal("global")
TRY = literal("try")
EXCEPT = literal("except")
FINALLY = literal("finally")
WITH = literal("with")
AS = literal("as")
NEQUAL = literal("<>")

# Helper to unwrap parser nodes
def unwrap(n):
    if isinstance(n, Py2Node): return n
    if hasattr(n, "node") and isinstance(n.node, Py2Node): return n.node
    if hasattr(n, "nodes") and n.nodes: return unwrap(n.nodes[0])
    if hasattr(n, "node"): return n.node
    return n

# Forward declarations
test = fw("test")
testlist = fw("testlist")
expr = fw("expr")
stmt = fw("stmt")
simple_stmt = fw("simple_stmt")
compound_stmt = fw("compound_stmt")
factor = fw("factor")
power = fw("power")
trailer = fw("trailer")
atom = fw("atom")

# AST Node Classes
class Py2Node:
    def to_ast(self): return self
    def to_py(self): raise NotImplementedError

class PrintStmt(Py2Node):
    def __init__(self, dest, values): self.dest, self.values = dest, values
    def to_py(self):
        parts = ["print"]
        if self.dest: parts += [">>", self.dest.to_py(), ","]
        parts.append(", ".join(v.to_py() for v in self.values))
        return " ".join(parts)

class ExecStmt(Py2Node):
    def __init__(self, code, glb=None, loc=None): self.code, self.glb, self.loc = code, glb, loc
    def to_py(self):
        parts = ["exec", self.code.to_py()]
        if self.glb: parts += ["in", self.glb.to_py()]
        if self.loc: parts += [",", self.loc.to_py()]
        return " ".join(parts)

class ReprExpr(Py2Node):
    def __init__(self, expr): self.expr = expr
    def to_py(self): return "`" + self.expr.to_py() + "`"

class BinOpExpr(Py2Node):
    def __init__(self, left, op, right): self.left, self.op, self.right = left, op, right
    def to_py(self): return f"({self.left.to_py()} {self.op} {self.right.to_py()})"

class UnaryOpExpr(Py2Node):
    def __init__(self, op, operand): self.op, self.operand = op, operand
    def to_py(self): return f"({self.op}{self.operand.to_py()})"

class LambdaExpr(Py2Node):
    def __init__(self, params, body): self.params, self.body = params, body
    def to_py(self): return f"lambda {self.params}: {self.body.to_py()}"

class CallExpr(Py2Node):
    def __init__(self, func, args): self.func, self.args = func, args
    def to_py(self): return f"{self.func.to_py()}({', '.join(a.to_py() for a in self.args)})"

class SubscriptExpr(Py2Node):
    def __init__(self, value, idx): self.value, self.idx = value, idx
    def to_py(self): return f"{self.value.to_py()}[{self.idx.to_py()}]"

class AttributeExpr(Py2Node):
    def __init__(self, value, attr): self.value, self.attr = value, attr
    def to_py(self): return f"{self.value.to_py()}.{self.attr}"

class IfExpr(Py2Node):
    def __init__(self, test, body, orelse): self.test, self.body, self.orelse = test, body, orelse
    def to_py(self): return f"({self.body.to_py()} if {self.test.to_py()} else {self.orelse.to_py()})"

class ListExpr(Py2Node):
    def __init__(self, elts): self.elts = elts
    def to_py(self): return "[" + ", ".join(e.to_py() for e in self.elts) + "]" if self.elts else "[]"

class TupleExpr(Py2Node):
    def __init__(self, elts): self.elts = elts
    def to_py(self):
        if len(self.elts) == 1: return f"({self.elts[0].to_py()},)"
        return "(" + ", ".join(e.to_py() for e in self.elts) + ")"

class DictExpr(Py2Node):
    def __init__(self, items): self.items = items
    def to_py(self):
        if not self.items: return "{}"
        return "{" + ", ".join(f"{k.to_py()}: {v.to_py()}" for k,v in self.items) + "}"

class NumberLit(Py2Node):
    def __init__(self, value, is_long=False, is_octal=False):
        self.value, self.is_long, self.is_octal = value, is_long, is_octal
    def to_py(self):
        if self.is_long: return self.value.upper() + "L"
        return self.value

class StringLit(Py2Node):
    def __init__(self, value): self.value = value
    def to_py(self): return self.value

class NameExpr(Py2Node):
    def __init__(self, name): self.name = name
    def to_py(self): return self.name

class AssignStmt(Py2Node):
    def __init__(self, targets, value): self.targets, self.value = targets, value
    def to_py(self): return " = ".join(t.to_py() for t in self.targets) + " = " + self.value.to_py()

class ExprStmt(Py2Node):
    def __init__(self, expr): self.expr = expr
    def to_py(self): return self.expr.to_py()

class PassStmt(Py2Node):
    def to_py(self): return "pass"

class BreakStmt(Py2Node):
    def to_py(self): return "break"

class ContinueStmt(Py2Node):
    def to_py(self): return "continue"

class ReturnStmt(Py2Node):
    def __init__(self, value=None): self.value = value
    def to_py(self): return "return " + self.value.to_py() if self.value else "return"

class AssertStmt(Py2Node):
    def __init__(self, test, msg=None): self.test, self.msg = test, msg
    def to_py(self): return f"assert {self.test.to_py()}" + (f", {self.msg.to_py()}" if self.msg else "")

class DelStmt(Py2Node):
    def __init__(self, targets): self.targets = targets
    def to_py(self): return "del " + ", ".join(t.to_py() for t in self.targets)

class GlobalStmt(Py2Node):
    def __init__(self, names): self.names = names
    def to_py(self): return "global " + ", ".join(self.names)

class IfStmt(Py2Node):
    def __init__(self, test, body, elifs=None, orelse=None):
        self.test, self.body, self.elifs, self.orelse = test, body, elifs or [], orelse
    def to_py(self):
        lines = [f"if {self.test.to_py()}:"]
        for s in self.body: lines.append(f"    {s.to_py()}")
        for t, b in self.elifs:
            lines.append(f"elif {t.to_py()}:")
            for s in b: lines.append(f"    {s.to_py()}")
        if self.orelse:
            lines.append("else:")
            for s in self.orelse: lines.append(f"    {s.to_py()}")
        return "\n".join(lines)

class WhileStmt(Py2Node):
    def __init__(self, test, body, orelse=None):
        self.test, self.body, self.orelse = test, body, orelse
    def to_py(self):
        lines = [f"while {self.test.to_py()}:"]
        for s in self.body: lines.append(f"    {s.to_py()}")
        if self.orelse:
            lines.append("else:")
            for s in self.orelse: lines.append(f"    {s.to_py()}")
        return "\n".join(lines)

class ForStmt(Py2Node):
    def __init__(self, target, iter_expr, body, orelse=None):
        self.target, self.iter_expr, self.body, self.orelse = target, iter_expr, body, orelse
    def to_py(self):
        lines = [f"for {self.target.to_py()} in {self.iter_expr.to_py()}:"]
        for s in self.body: lines.append(f"    {s.to_py()}")
        if self.orelse:
            lines.append("else:")
            for s in self.orelse: lines.append(f"    {s.to_py()}")
        return "\n".join(lines)

class DefStmt(Py2Node):
    def __init__(self, name, params, body): self.name, self.params, self.body = name, params, body
    def to_py(self):
        lines = [f"def {self.name}({self.params}):"]
        for s in self.body: lines.append(f"    {s.to_py()}")
        return "\n".join(lines)

class ClassStmt(Py2Node):
    def __init__(self, name, bases, body): self.name, self.bases, self.body = name, bases, body
    def to_py(self):
        bases_str = ", ".join(b.to_py() for b in self.bases) if self.bases else ""
        lines = [f"class {self.name}({bases_str}):"]
        for s in self.body: lines.append(f"    {s.to_py()}")
        return "\n".join(lines)

# Token parsers
LONG_NUMBER = expect_re(r"\d+[lL]")
OCTAL_NUMBER = expect_re(r"0[0-7]+")

@method(NUMBER)
def to_py(self): return python2_number(self)

@method(STRING)
def to_py(self): return StringLit(self.node)

@method(IDENTIFIER)
def to_py(self): return NameExpr(self.node)

@method(PASS)
def to_py(self): return PassStmt()

@method(BREAK)
def to_py(self): return BreakStmt()

@method(CONTINUE)
def to_py(self): return ContinueStmt()

# Grammar - atom is the base
atom = (
    LPAREN + test + RPAREN |
    LBRACKET + testlist[:] + RBRACKET |
    LBRACE + (test + COLON + test)[1:] + RBRACE |
    LBRACE + RBRACE |
    IDENTIFIER | PYTHON2_NUMBER | STRING
)

@method(atom)
def to_py(self):
    n = self.node
    if isinstance(n, Py2Node): return n
    if isinstance(n, list):
        if len(n) == 3: return n[1]
        if n[0].string == "[": return ListExpr(n[1] if isinstance(n[1], list) else [n[1]] if n[1] else [])
        if n[0].string == "{": return DictExpr(n[1] if isinstance(n[1], list) else [])
    return n

# Trailer: calls, subscripts, attributes
trailer = (
    LPAREN + (testlist[:]) + RPAREN |
    LBRACKET + test + RBRACKET |
    DOT + IDENTIFIER
)

@method(trailer)
def to_py(self): return self.node

# Power: atom with trailers (right-associative)
power = atom + trailer[:]

@method(power)
def to_py(self):
    result = self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else self.nodes[0]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for tr in self.nodes[1].nodes:
            if tr and hasattr(tr, "__getitem__") and len(tr) >= 2:
                if hasattr(tr[0], "string") and tr[0].string == "(": 
                    result = CallExpr(result, tr[1] if isinstance(tr[1], list) else [tr[1]] if tr[1] else [])
                elif hasattr(tr[0], "string") and tr[0].string == "[": 
                    result = SubscriptExpr(result, tr[1].to_py() if hasattr(tr[1], "to_py") else tr[1])
                elif hasattr(tr[0], "string") and tr[0].string == ".": 
                    result = AttributeExpr(result, tr[1].string if hasattr(tr[1], "string") else str(tr[1]))
    return result

# Factor: unary operators (right-recursive to avoid left-recursion)
# Unary operators with fmap to create proper result
def make_unary(result):
    # result could be a Sequence_Parser (from PLUS + factor) or a power result
    if hasattr(result, 'nodes') and len(result.nodes) >= 2:
        if hasattr(result.nodes[0], 'string'):
            op = result.nodes[0].string
            operand = result.nodes[1].to_py() if hasattr(result.nodes[1], 'to_py') else result.nodes[1]
            if op == '+': return UnaryOpExpr('+', operand)
            if op == '-': return UnaryOpExpr('-', operand)
    # Return the power result directly
    return result.to_py() if hasattr(result, 'to_py') else result

from hek_parser import fmap
unary_plus = fmap(make_unary, PLUS + factor)
unary_minus = fmap(make_unary, MINUS + factor)
factor = unary_plus | unary_minus | power

# Simpler factor without backtick recursion


def _factor_value(n):
    """Extract value from factor parse result (handles Sequence_Parser)"""
    if hasattr(n, 'to_py'): return n.to_py()
    if hasattr(n, 'nodes') and n.nodes:
        if len(n.nodes) >= 2 and hasattr(n.nodes[0], 'string'):
            op = n.nodes[0].string
            operand = _factor_value(n.nodes[1])
            if op == '+': return UnaryOpExpr('+', operand)
            if op == '-': return UnaryOpExpr('-', operand)
        return _factor_value(n.nodes[0])
    return n

@method(factor)
def to_py(self):
    if len(self.nodes) >= 2:
        if hasattr(self.nodes[0], "string") and self.nodes[0].string == "+":
            return UnaryOpExpr("+", self.nodes[1].to_py() if hasattr(self.nodes[1], "to_py") else self.nodes[1])
        if hasattr(self.nodes[0], "string") and self.nodes[0].string == "-":
            return UnaryOpExpr("-", self.nodes[1].to_py() if hasattr(self.nodes[1], "to_py") else self.nodes[1])
    return self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else self.nodes[0]

# Term: multiplicative (left-associative via iteration)
term = factor + ((STAR | SLASH | PERCENT | DOUBLESTAR) + factor)[:]

@method(term)
def to_py(self):
    result = self.nodes[0]
    for op_e in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if op_e:
            op = op_e.nodes[0].string if hasattr(op_e, "nodes") else op_e[0]
            right = op_e.nodes[1] if hasattr(op_e, "nodes") else op_e[1]
            result = BinOpExpr(result, op, right)
    return result

# Arithmetic
arith_expr = term + ((PLUS | MINUS) + term)[:]

@method(arith_expr)
def to_py(self):
    result = self.nodes[0]
    for op_e in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if op_e:
            op = op_e.nodes[0].string if hasattr(op_e, "nodes") else op_e[0]
            right = op_e.nodes[1] if hasattr(op_e, "nodes") else op_e[1]
            result = BinOpExpr(result, op, right)
    return result

# Shift
shift_expr = arith_expr + ((LEFTSHIFT | RIGHTSHIFT) + arith_expr)[:]

@method(shift_expr)
def to_py(self):
    result = self.nodes[0]
    for op_e in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if op_e:
            op = op_e.nodes[0].string if hasattr(op_e, "nodes") else op_e[0]
            right = op_e.nodes[1] if hasattr(op_e, "nodes") else op_e[1]
            result = BinOpExpr(result, op, right)
    return result

# Comparisons
comp_op = LESS | GREATER | EQEQUAL | NOTEQUAL | LESSEQUAL | GREATEREQUAL | NEQUAL | IS + NOT | IS | IN + NOT | NOT + IN | IN
comp_expr = shift_expr + (comp_op + shift_expr)[:]



@method(comp_expr)
def to_py(self):
    result = self.nodes[0]
    for op_e in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if op_e:
            op = op_e.nodes[0].string if hasattr(op_e, "nodes") else op_e[0]
            if isinstance(op, list): op = " ".join(o.string if hasattr(o, "string") else str(o) for o in op)
            right = op_e.nodes[1] if hasattr(op_e, "nodes") else op_e[1]
            result = BinOpExpr(result, op, right)
    return result

# Boolean operators (avoiding left-recursion)
not_expr = comp_expr + (NOT + comp_expr)[:]

@method(not_expr)
def to_py(self):
    result = self.nodes[0]
    for r in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if r: result = UnaryOpExpr("not ", r)
    return result

and_expr = not_expr + (AND + not_expr)[:]

@method(and_expr)
def to_py(self):
    result = self.nodes[0]
    for r in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if r: result = BinOpExpr(result, "and", r)
    return result

or_expr = and_expr + (OR + and_expr)[:]

@method(or_expr)
def to_py(self):
    result = self.nodes[0]
    for r in (self.nodes[1].nodes if hasattr(self.nodes[1], "nodes") else []):
        if r: result = BinOpExpr(result, "or", r)
    return result

# Lambda
lambda_params = (IDENTIFIER + (COMMA + IDENTIFIER)[:])[0:]
lambda_expr = LAMBDA + lambda_params + COLON + test

@method(lambda_expr)
def to_py(self):
    params = self.nodes[1]
    param_str = ", ".join(p.string if hasattr(p, "string") else p.to_py() for p in params) if params else ""
    return LambdaExpr(param_str, self.nodes[3])

# Test expression
test = or_expr + (IF + or_expr + ELSE + test)[:] | lambda_expr

@method(test)
def to_py(self):
    if self.nodes[0] == "lambda": return lambda_expr.to_py(self)
    result = self.nodes[0]
    if len(self.nodes) > 1 and self.nodes[1]:
        return IfExpr(self.nodes[1].nodes[1], result, self.nodes[1].nodes[3])
    return result

# Test list
testlist = test + (COMMA + test)[:] + COMMA[:]

@method(testlist)
def to_py(self):
    items = [self.nodes[0]]
    if len(self.nodes) > 1 and self.nodes[1]:
        items.extend(n.nodes[1] for n in self.nodes[1].nodes)
    if len(items) > 1:
        return TupleExpr([i.to_py() if hasattr(i, "to_py") else i for i in items])
    return items[0].to_py() if items and hasattr(items[0], "to_py") else items[0]

expr = testlist

@method(expr)
def to_py(self):
    result = testlist.to_py(self)
    return result.to_py() if hasattr(result, "to_py") and not isinstance(result, Py2Node) else result

# Print statement
print_dest = expect(tkn.OP, ">>") + test + COMMA[:]
print_values = test + (COMMA + test)[:]
print_stmt = PRINT + print_dest[:] + print_values[:] + COMMA[:]

@method(print_stmt)
def to_py(self):
    dest, values = None, []
    for node in self.nodes[1:]:
        if not node: continue
        if isinstance(node, list):
            for item in node:
                if isinstance(item, list) and len(item) >= 2 and item[0].string == ">>": dest = item[1]
                elif hasattr(item, "to_py"): values.append(item)
        elif hasattr(node, "to_py"): values.append(node)
    return PrintStmt(dest, values)

# Exec statement
exec_in_clause = IN + test + (COMMA + test)[:]
exec_stmt = EXEC + test + exec_in_clause[:]

@method(exec_stmt)
def to_py(self):
    code, glb, loc = self.nodes[1], None, None
    if len(self.nodes) > 2 and self.nodes[2]:
        ic = self.nodes[2]
        if isinstance(ic, list) and len(ic) >= 2:
            glb = ic[1]
            if len(ic) > 2 and isinstance(ic[2], list) and len(ic[2]) >= 2: loc = ic[2][1]
    return ExecStmt(code, glb, loc)

# Simple statements
simple_stmt = (
    print_stmt | exec_stmt |
    expr + EQUAL + expr + (EQUAL + expr)[:] |
    RETURN + test[:] | PASS | BREAK | CONTINUE |
    ASSERT + test + (COMMA + test)[:] |
    DEL + expr + (COMMA + expr)[:] |
    GLOBAL + IDENTIFIER + (COMMA + IDENTIFIER)[:] |
    expr
)

@method(simple_stmt)
def to_py(self):
    n = self.node
    if isinstance(n, Py2Node): return n
    if isinstance(n, list):
        if len(n) >= 3 and n[1].string == "=":
            targets, i = [n[0]], 2
            while i < len(n) and n[i-1].string == "=": targets.append(n[i]); i += 2
            return AssignStmt(targets, n[-1])
        if n[0] == "return": return ReturnStmt(n[1] if len(n) > 1 else None)
        if n[0] == "pass": return PassStmt()
        if n[0] == "break": return BreakStmt()
        if n[0] == "continue": return ContinueStmt()
        if n[0] == "assert": return AssertStmt(n[1], n[2] if len(n) > 2 else None)
        if n[0] == "del":
            targets = [n[1]]
            if len(n) > 2: targets.extend(x.nodes[1] for x in n[2].nodes)
            return DelStmt(targets)
        if n[0] == "global":
            names = [n[1].string] if len(n) > 1 else []
            if len(n) > 2: names.extend(x.string for x in n[2].nodes)
            return GlobalStmt(names)
    return ExprStmt(n)

# Suite (simplified - no INDENT/DEDENT)
suite = stmt[:]

@method(suite)
def to_py(self): return self.nodes[0].nodes if hasattr(self.nodes[0], "nodes") else self.nodes[0]

# Compound statements
compound_stmt = (
    IF + test + COLON + suite + (ELIF + test + COLON + suite)[:] + (ELSE + COLON + suite)[:] |
    WHILE + test + COLON + suite + (ELSE + COLON + suite)[:] |
    FOR + expr + IN + test + COLON + suite + (ELSE + COLON + suite)[:] |
    DEF + IDENTIFIER + LPAREN + (IDENTIFIER + (COMMA + IDENTIFIER)[:])[0:] + RPAREN + COLON + suite |
    CLASS + IDENTIFIER + (LPAREN + testlist + RPAREN)[:] + COLON + suite |
    TRY + COLON + suite + (EXCEPT + (test + (COMMA + test)[:] | nothing) + COLON + suite)[:] + (ELSE + COLON + suite)[:] + (FINALLY + COLON + suite)[:] |
    WITH + test + (AS + test)[:] + COLON + suite
)

@method(compound_stmt)
def to_py(self):
    n = self.node
    if isinstance(n, Py2Node): return n
    if isinstance(n, list):
        kw = n[0].string if hasattr(n[0], "string") else n[0]
        if kw == "if": return IfStmt(n[1], n[3], n[4] if len(n) > 4 and n[4] else [], n[5] if len(n) > 5 and n[5] else None)
        if kw == "while": return WhileStmt(n[1], n[3], n[5] if len(n) > 5 else None)
        if kw == "for": return ForStmt(n[1], n[3], n[5], n[7] if len(n) > 7 else None)
        if kw == "def": return DefStmt(n[1].string, n[3] if len(n) > 3 else "", n[5] if len(n) > 5 else n[4])
        if kw == "class": return ClassStmt(n[1].string, n[3].nodes if len(n) > 3 and hasattr(n[3], "nodes") else [], n[5] if len(n) > 5 else n[4])
    return n

# Statement
stmt = simple_stmt + SEMICOLON[:] | compound_stmt

@method(stmt)
def to_py(self): return self.node.to_py() if hasattr(self.node, "to_py") else self.node

# File input
file_input = stmt[:]

@method(file_input)
def to_py(self):
    if hasattr(self.nodes[0], "nodes"): return [s.to_py() for s in self.nodes[0].nodes if s]
    return [s.to_py() for s in self.nodes if s]

# Tests
if __name__ == "__main__":
    print("=" * 60)
    print("Python 2.7 Parser Tests")
    print("=" * 60)
    
    tests = [
        ("print 1", "print"),
        ("print 1, 2, 3", "print"),
        ('print "hello"', "print"),
        ("exec 'x=1'", "exec"),
        ("exec code in globals", "exec"),
        ("123L", "123"),
        ("0755", "0755"),
        ("x <> y", "<>"),
        ("x = 1", "="),
        ("lambda x: x + 1", "lambda"),
        ("[1, 2, 3]", "["),
        ("pass", "pass"),
        ("return x", "return"),
    ]
    
    passed = failed = 0
    for code, expected in tests:
        try:
            result = file_input.parse(Input(code))
            if result:
                ast, _ = result
                output = ast.to_py()
                if isinstance(output, list): output = output[0] if output else ""
                print(f"PASS: {code!r} -> {output!r}")
                passed += 1
            else:
                print(f"FAIL: {code!r} - parse failed")
                failed += 1
        except Exception as e:
            print(f"ERROR: {code!r} - {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
