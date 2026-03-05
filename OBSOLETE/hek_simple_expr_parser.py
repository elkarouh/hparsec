#!/usr/bin/env python3
"""Simple expression parser using hek_parser.py"""
from hek_parser import Input, method, fw, expect, NUMBER, LPAREN, RPAREN
import tokenize as tkn

PLUS = expect(tkn.OP, '+')
MINUS = expect(tkn.OP, '-')
STAR = expect(tkn.OP, '*')
SLASH = expect(tkn.OP, '/')

expr = fw('expr')
# LPAREN and RPAREN are ignored, so paren_expr.nodes = [expr]
paren_expr = LPAREN + expr + RPAREN
factor = NUMBER | paren_expr
term = factor + ((STAR | SLASH) + factor)[:]
expr = term + ((PLUS | MINUS) + term)[:]

@method(NUMBER)
def to_py(self): return self.node
@method(NUMBER)
def to_ast(self):
    import ast
    return ast.Constant(value=int(self.node) if self.node.isdigit() else float(self.node))
@method(PLUS)
def to_py(self): return '+'
@method(MINUS)
def to_py(self): return '-'
@method(STAR)
def to_py(self): return '*'
@method(SLASH)
def to_py(self): return '/'

@method(paren_expr)
def to_py(self):
    # LPAREN and RPAREN are ignored, nodes = [expr]
    return self.nodes[0].to_py()
@method(paren_expr)
def to_ast(self):
    return self.nodes[0].to_ast()

@method(factor)
def to_py(self):
    return self.nodes[0].to_py()
@method(factor)
def to_ast(self):
    return self.nodes[0].to_ast()

@method(term)
def to_py(self):
    result = self.nodes[0].to_py()
    if len(self.nodes) > 1:
        rep = self.nodes[1]
        if hasattr(rep, 'nodes') and rep.nodes:
            for seq in rep.nodes:
                op = seq.nodes[0].to_py()
                operand = seq.nodes[1].to_py()
                result = f'({result} {op} {operand})'
    return result
@method(term)
def to_ast(self):
    import ast
    left = self.nodes[0].to_ast()
    if len(self.nodes) > 1:
        rep = self.nodes[1]
        if hasattr(rep, 'nodes') and rep.nodes:
            for seq in rep.nodes:
                op = seq.nodes[0].node
                right = seq.nodes[1].to_ast()
                if op == '*': left = ast.BinOp(left, ast.Mult(), right)
                elif op == '/': left = ast.BinOp(left, ast.Div(), right)
    return left

@method(expr)
def to_py(self):
    result = self.nodes[0].to_py()
    if len(self.nodes) > 1:
        rep = self.nodes[1]
        if hasattr(rep, 'nodes') and rep.nodes:
            for seq in rep.nodes:
                op = seq.nodes[0].to_py()
                operand = seq.nodes[1].to_py()
                result = f'({result} {op} {operand})'
    return result
@method(expr)
def to_ast(self):
    import ast
    left = self.nodes[0].to_ast()
    if len(self.nodes) > 1:
        rep = self.nodes[1]
        if hasattr(rep, 'nodes') and rep.nodes:
            for seq in rep.nodes:
                op = seq.nodes[0].node
                right = seq.nodes[1].to_ast()
                if op == '+': left = ast.BinOp(left, ast.Add(), right)
                elif op == '-': left = ast.BinOp(left, ast.Sub(), right)
    return left

def parse_expr(code):
    stream = Input(code)
    result, _ = expr.parse(stream)
    return result

if __name__ == '__main__':
    print('=' * 50)
    print('Simple Expression Parser Test')
    print('=' * 50)
    for code in ['42', '3 + 4', '3 + 4 * 5', '(3 + 4) * 5', '1 + 2 + 3']:
        print(f'Input: {code}')
        r = parse_expr(code)
        if r:
            print(f'  to_py(): {r.to_py()}')
            print(f'  AST: {__import__("ast").dump(r.to_ast())}')
        else:
            print('  Parse failed!')
