#!/usr/bin/env python3
"""Simplified Ada2Ada compiler - Inspired by hek_py2py.py and based on simplified_ada_grammar.gr"""
import ast
from ast import NodeVisitor
from contextlib import contextmanager, nullcontext
from enum import IntEnum, auto
from hek_parser import Input, method, fw, literal, G
from hek_parser import IDENTIFIER, INTEGER, DOUBLEDOT, LBRACKET, RBRACKET

MODULE, PROCEDURE = 0, 1

# Type Grammar for Basic Ada Types
primitive_type, container_type, array_type = fw("primitive_type"), fw("container_type"), fw("array_type")
range_type, basic_type, type_decl = fw("range_type"), fw("basic_type"), fw("type_decl")
none_type = literal("None")
boolean_type, integer_type, float_type, string_type = literal("Boolean"), literal("Integer"), literal("Float"), literal("String")
type_mark = IDENTIFIER
range_type = (INTEGER | type_mark) + DOUBLEDOT + (INTEGER | type_mark)
primitive_type = none_type | boolean_type | integer_type | float_type | string_type | range_type
array_type = LBRACKET + INTEGER + RBRACKET + basic_type
basic_type = primitive_type | array_type | type_mark
type_decl = basic_type

@method(primitive_type)
def to_ada(self): return self.node.to_ada()
@method(boolean_type)
def to_ada(self): return "Boolean"
@method(integer_type)
def to_ada(self): return "Integer"
@method(float_type)
def to_ada(self): return "Float"
@method(string_type)
def to_ada(self): return "String"
@method(range_type)
def to_ada(self): return f"{self.nodes[0].to_ada()} .. {self.nodes[1].to_ada()}"
@method(array_type)
def to_ada(self): return f"array (1 .. {self.nodes[0].to_ada()}) of {self.nodes[1].to_ada()}"
@method(basic_type)
def to_ada(self): return self.node.to_ada()
@method(type_decl)
def to_ada(self): return self.node.to_ada()
@method(IDENTIFIER)
def to_ada(self): return self.node
@method(INTEGER)
def to_ada(self): return self.node

# Symbol Table for Tracking Declarations
class SymbolTable(list):
    def __init__(self, scope_type, parent_scope=None, scope_level=0, index_in_parent=0):
        self.scope_type, self.parent_scope = scope_type, parent_scope
        self.current_level, self.index_in_parent, self.current_idx = scope_level, index_in_parent, 0
    def enter_scope(self, scope_type):
        G.current_symbol_table = SymbolTable(scope_type, self, self.current_level + 1, self.current_idx)
        return G.current_symbol_table
    def leave_scope(self):
        G.current_symbol_table = self.parent_scope
        return G.current_symbol_table
    def add_symbol(self, name, sym_type):
        super().append((name, sym_type)); self.current_idx += 1
    def _get_symb(self, the_name, max_index):
        for i, (name, sym_type) in enumerate(self[:max_index or self.current_idx]):
            if name == the_name: return sym_type
        return None
    def get_symbol(self, the_name, max_index=None):
        if res := self._get_symb(the_name, max_index): return res
        return self.parent_scope.get_symbol(the_name, self.index_in_parent) if self.parent_scope else None

G.current_symbol_table = SymbolTable(MODULE)

# Precedence Enum for Expression Parsing
class Precedence(IntEnum):
    NAMED_EXPR, TUPLE, OR, AND, NOT, CMP, BOR, ARITH, TERM, FACTOR, POWER, ATOM = range(12)
    def next(self):
        try: return self.__class__(self + 1)
        except ValueError: return self

def interleave(inter, f, seq):
    seq = iter(seq)
    try: f(next(seq))
    except StopIteration: pass
    else:
        for x in seq: inter(); f(x)

def translate_type_to_ada(mytype):
    if m := type_decl.parse(Input(mytype)): return m[0].to_ada()
    return mytype

# AdaUnparser - NodeVisitor subclass for converting Python AST to Ada
class AdaUnparser(NodeVisitor):
    def __init__(self, source):
        self.source, self._source, self._precedences, self._indent = source, [], {}, 0
    def get_precedence(self, node): return self._precedences.get(node, Precedence.ATOM)
    def set_precedence(self, prec, *nodes):
        for n in nodes: self._precedences[n] = prec
    def write(self, *text): self._source.extend(text)
    def newline(self): self.write(chr(10))
    def fill(self, text=""): self.newline(); self.write("    " * self._indent + text)
    @contextmanager
    def block(self):
        self._indent += 1; yield; self._indent -= 1
    @contextmanager
    def delimit(self, start, end):
        self.write(start); yield; self.write(end)
    def require_parens(self, prec, node):
        return self.delimit("(", ")") if self.get_precedence(node) > prec else nullcontext()
    def traverse(self, node):
        if isinstance(node, list):
            for item in node: self.traverse(item)
        else: super().visit(node)
    def visit(self, node):
        self._source = []; self.traverse(node); return "".join(self._source)
    def visit_Module(self, node):
        for stmt in node.body: self.traverse(stmt)
    def visit_FunctionDef(self, node):
        self.fill(f"procedure {node.name}")
        with self.delimit("(", ")"):
            interleave(lambda: self.write(", "), self.traverse, node.args.args)
        self.write(" is"); self._indent += 1
        for stmt in node.body: self.traverse(stmt)
        self._indent -= 1; self.fill(f"end {node.name};")
    def visit_arg(self, node):
        ada_type = node.annotation.id if hasattr(node.annotation, "id") else "Integer"
        self.fill(f"{node.arg} : {ada_type};")
    def visit_Assign(self, node):
        self.fill("")
        for target in node.targets: self.traverse(target); self.write(" := ")
        self.traverse(node.value); self.write(";")
    def visit_AnnAssign(self, node):
        self.fill(""); self.traverse(node.target)
        if node.annotation:
            ada_type = node.annotation.id if hasattr(node.annotation, "id") else "Integer"
            self.write(f" : {ada_type}")
        if node.value: self.write(" := "); self.traverse(node.value)
        self.write(";")
    def visit_Name(self, node): self.write(node.id)
    def visit_Constant(self, node):
        if isinstance(node.value, str): self.write(chr(34) + node.value + chr(34))
        elif isinstance(node.value, bool): self.write("True" if node.value else "False")
        else: self.write(str(node.value))
    def visit_BinOp(self, node):
        with self.require_parens(Precedence.TERM, node):
            self.set_precedence(Precedence.ARITH, node.left, node.right)
            self.traverse(node.left); self.write(" "); self.traverse(node.op); self.write(" ")
            self.traverse(node.right)
    def visit_Add(self, node): self.write("+")
    def visit_Sub(self, node): self.write("-")
    def visit_Mult(self, node): self.write("*")
    def visit_Div(self, node): self.write("/")
    def visit_Compare(self, node):
        with self.require_parens(Precedence.CMP, node):
            self.traverse(node.left)
            for op, comp in zip(node.ops, node.comparators):
                self.write(" "); self.traverse(op); self.write(" "); self.traverse(comp)
    def visit_Eq(self, node): self.write("=")
    def visit_NotEq(self, node): self.write("/=")
    def visit_Lt(self, node): self.write("<")
    def visit_LtE(self, node): self.write("<=")
    def visit_Gt(self, node): self.write(">")
    def visit_GtE(self, node): self.write(">=")
    def visit_If(self, node):
        self.fill("if "); self.traverse(node.test); self.write(" then")
        self._indent += 1
        for stmt in node.body: self.traverse(stmt)
        self._indent -= 1
        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                orelif = node.orelse[0]
                self.fill("elsif "); self.traverse(orelif.test); self.write(" then")
                self._indent += 1
                for stmt in orelif.body: self.traverse(stmt)
                self._indent -= 1
            else:
                self.fill("else"); self._indent += 1
                for stmt in node.orelse: self.traverse(stmt)
                self._indent -= 1
        self.fill("end if;")
    def visit_For(self, node):
        self.fill("for "); self.traverse(node.target); self.write(" in "); self.traverse(node.iter); self.write(" loop")
        self._indent += 1
        for stmt in node.body: self.traverse(stmt)
        self._indent -= 1; self.fill("end loop;")
    def visit_While(self, node):
        self.fill("while "); self.traverse(node.test); self.write(" loop")
        self._indent += 1
        for stmt in node.body: self.traverse(stmt)
        self._indent -= 1; self.fill("end loop;")
    def visit_Expr(self, node): self.fill(""); self.traverse(node.value); self.write(";")
    def visit_Pass(self, node): self.fill("null;")
    def visit_Return(self, node):
        self.fill("return")
        if node.value: self.write(" "); self.traverse(node.value)
        self.write(";")
    def visit_Call(self, node):
        self.traverse(node.func)
        with self.delimit("(", ")"): interleave(lambda: self.write(", "), self.traverse, node.args)
    def visit_BoolOp(self, node):
        op = " and " if isinstance(node.op, ast.And) else " or "
        with self.require_parens(Precedence.AND, node):
            interleave(lambda: self.write(op), self.traverse, node.values)
    def visit_And(self, node): self.write("and")
    def visit_Or(self, node): self.write("or")
    def visit_UnaryOp(self, node):
        self.traverse(node.op); self.write(" "); self.traverse(node.operand)
    def visit_UAdd(self, node): self.write("+")
    def visit_USub(self, node): self.write("-")
    def visit_Not(self, node): self.write("not")

def ada2ada(source_code):
    tree = ast.parse(source_code)
    return AdaUnparser(source_code).visit(tree)

if __name__ == "__main__":
    print("=" * 60 + chr(10) + "ADA2ADA COMPILER TEST" + chr(10) + "=" * 60)
    print(chr(10) + "Input Python-style code:" + chr(10) + "-" * 60)
    python_style = chr(10) + "def Example(x: int, y: float):" + chr(10)
    python_style += "    x = 42" + chr(10) + "    y = 3.14" + chr(10)
    python_style += "    if x > 10:" + chr(10) + "        x = x + 5" + chr(10)
    python_style += "    else:" + chr(10) + "        x = x - 1" + chr(10)
    python_style += "    for i in range(1, 11):" + chr(10) + "        x = x + i" + chr(10)
    python_style += "    return x" + chr(10)
    print(python_style + "-" * 60)
    print(chr(10) + "Output Ada-style code:" + chr(10) + "-" * 60)
    try: print(ada2ada(python_style))
    except Exception as e: print(f"Error: {e}")
    print("-" * 60 + chr(10) + "Type grammar tests:" + chr(10) + "-" * 60)
    for t in ["Integer", "Float", "Boolean", "String", "1 .. 100", "[10] Integer"]:
        m = type_decl.parse(Input(t))
        print(f"  {t:20} -> {m[0].to_ada() if m else '(parse failed)'}")
    print("-" * 60 + chr(10) + "Symbol table test:" + chr(10) + "-" * 60)
    symtab = SymbolTable(MODULE)
    symtab.add_symbol("counter", "Integer"); symtab.add_symbol("name", "String")
    print(f"  counter type: {symtab.get_symbol('counter')}")
    print(f"  name type: {symtab.get_symbol('name')}")
    nested = symtab.enter_scope(PROCEDURE); nested.add_symbol("local_var", "Float")
    print(f"  local_var type: {nested.get_symbol('local_var')}")
    print(f"  counter (from parent): {nested.get_symbol('counter')}")
    nested.leave_scope(); print("-" * 60 + chr(10) + "All tests completed!")
