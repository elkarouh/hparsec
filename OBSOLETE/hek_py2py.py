# BUG1: comment duplication in the else branch of an IF statement IS FIXED, look for 'elif'  !!!
# BUG2 : sixth comment doesn't show
# TODO:  process 'new ' and 'var'
# TODO:  add range constraints
# TODO: add symbol table
import ast  # first comment
import sys  # third comment
from _ast import *  # fourth comment
from ast import NodeVisitor, iter_child_nodes  # second comment
from contextlib import contextmanager, nullcontext  # fifth comment
from enum import IntEnum, _simple_enum, auto  # sixth comment DOESN'T SHOW !!!
from keyword import iskeyword

##########################################################################################
import hek_rxe
from hek_rxe import (
    ANYCHARS,
    SOMESPACE,
    VAR_DECL,
    BetweenMatchingBrackets,
    UnnamedGroup,
    split_on_comma,
)

BUILTIN, MODULE, CLASS, FUNCTION = range(4)


def rindex(lst, value):
    import operator

    try:
        return len(lst) - operator.indexOf(reversed(lst), value) - 1
    except ValueError:
        return None


def interleave(inter, f, seq):
    """Call f on each item in seq, calling inter() in between."""
    seq = iter(seq)
    try:
        f(next(seq))
    except StopIteration:
        pass
    else:
        for x in seq:
            inter()
            f(x)


##############################################################################################
########################################################################################################################
from hek_parsec import (
    COLON,
    COMMA,
    DOUBLEDOT,
    IDENTIFIER,
    INTEGER,
    LBRACE,
    LBRACKET,
    LPAREN,
    QUESTION_MARK,
    RARROW,
    RBRACE,
    RBRACKET,
    RPAREN,
    SSTAR,
    STAR,
    VBAR,
    G,
    Input,
    fw,
    literal,
    method,
)

# 4 way to declare a type
# 1. type typename is ... (choice an enum or a constraint type or alias): type Temperature is int range 1..50
# 2. def func(...): ... PYTHON
# 3. class Klass: ...   PYTHON
# 4.
# from typing import TypeAlias
# myvar: TypeAlias = ...
####################### Forward declarations ################
primitive_type = fw("primitive_type")
map_type = fw("map_type")
container_type = fw("container_type")
list_type = fw("list_type")
tuple_type = fw("tuple_type")
multi_tuple_type = fw("multi_tuple_type")
empty_tuple_type = fw("empty_tuple_type")
singleton_tuple_type = fw("singleton_tuple_type")
set_type = fw("set_type")
iterable_type = fw("iterable_type")
array_type = fw("array_type")
sequence_type = fw("sequence_type")
optional_type = fw("optional_type")
maybe_optional_type = fw("maybe_optional_type")
pointer_type = fw("pointer_type")
maybe_pointer_type = fw("maybe_pointer_type")
basic_type = fw("basic_type")
union_type = fw("union_type")
maybe_union_type = fw("maybe_union_type")
named_tuple_type = fw("named_tuple_type")
#####################################################################################
none_type = literal("None")
any_type = literal("ANY")
boolean_type = literal("bool")
integer_type = literal("int")
string_type = literal("str")
char_type = literal("char")
bytes_type = literal("bytes")
float_type = literal("float")
type_mark = IDENTIFIER  # the identifier must designate a type
range_type = (INTEGER | IDENTIFIER) + DOUBLEDOT + (INTEGER | IDENTIFIER)
type_decl = union_type | maybe_optional_type
union_type = maybe_optional_type + (VBAR + maybe_optional_type)[1:]
maybe_optional_type = optional_type | maybe_pointer_type
optional_type = maybe_pointer_type + QUESTION_MARK
maybe_pointer_type = pointer_type | basic_type
pointer_type = STAR + basic_type  # we only allow one level of indirection
basic_type = primitive_type | container_type | map_type | type_mark
primitive_type = (
    none_type
    | float_type
    | boolean_type
    | string_type
    | integer_type
    | char_type
    | range_type
)
map_type = LBRACKET + basic_type + RBRACKET + basic_type
container_type = (
    array_type | sequence_type | set_type | iterable_type | string_type | bytes_type
)
sequence_type = list_type | tuple_type | named_tuple_type
list_type = LBRACKET + RBRACKET + basic_type
tuple_type = empty_tuple_type | singleton_tuple_type | multi_tuple_type
multi_tuple_type = LPAREN + basic_type + (COMMA + basic_type)[1:] + RPAREN
singleton_tuple_type = LPAREN + basic_type + COMMA + RPAREN
empty_tuple_type = LPAREN + COMMA + RPAREN
var_decl = IDENTIFIER + COLON + basic_type
named_tuple_type = LPAREN + var_decl + (COMMA + var_decl)[1:] + RPAREN
set_type = LBRACE + RBRACE + basic_type
array_type = LBRACKET + (INTEGER | SSTAR) + RBRACKET + basic_type
iterable_type = LBRACKET + RBRACKET + RARROW + basic_type


@method(iterable_type)
def to_py(self):
    return f"Sequence[{self.node.to_py()}]"


@method(none_type)
def to_py(self):
    return "None"


@method(boolean_type)
def to_py(self):
    return "bool"


@method(integer_type)
def to_py(self):
    return "int"


@method(char_type)
def to_py(self):
    return "char"  # ?????????


@method(string_type)
def to_py(self):
    return "str"


@method(float_type)
def to_py(self):
    return "float"


@method(range_type)
def to_py(self):
    return f"range"
    # return f"range from {self.nodes[0].to_py()} to {self.nodes[1].to_py()}"


@method(union_type)
def to_py(self):
    return f"{self.nodes[0].to_py()+ ' | ' + ' | '.join(n.node.to_py() for n in self.nodes[1].nodes)}"


@method(optional_type)
def to_py(self):
    return f"Optional[{self.node.to_py()}]"


@method(pointer_type)
def to_py(self):
    return "access to " + f"{self.node.to_py()}"


@method(list_type)
def to_py(self):
    return f"list[{self.node.to_py()}]"


@method(set_type)
def to_py(self):
    return f"set[{self.node.to_py()}]"


@method(array_type)
def to_py(self):
    if self.nodes[0].to_py() == "*":
        return f"list[{self.nodes[1].to_py()}]"
    else:
        return f"Annotated[Tuple[{self.nodes[1].to_py()}],{self.nodes[0].to_py()}]"
    # return f"[array size {self.nodes[0].to_py()} of {self.nodes[1].to_py()}]"


@method(map_type)
def to_py(self):
    if type(self.nodes[0]).__name__ == "multi_tuple_type":
        return f"Callable[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]".replace(
            "tuple", "", 1
        )
    elif type(self.nodes[0]).__name__ in ("singleton_tuple_type", "empty_tuple_type"):
        return f"Callable[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]".replace(
            ",]", "]"
        ).replace("tuple", "", 1)
    else:
        return f"dict[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]"


@method(multi_tuple_type)
def to_py(self):
    output = f"tuple[{self.nodes[0].to_py()}, "
    output += f"{', '.join(n.node.to_py() for n in self.nodes[1].nodes)}]"
    return output


@method(empty_tuple_type)
def to_py(self):
    return f"tuple[]"


@method(singleton_tuple_type)
def to_py(self):
    return f"tuple[{self.node.to_py()},]"


@method(var_decl)
def to_py(self):
    return f"{self.nodes[0].to_py()}:{self.nodes[1].to_py()}"


@method(named_tuple_type)
def to_py(self):
    output = f"NamedTuple[{self.nodes[0].to_py()}, "
    output += f"{', '.join(n.node.to_py() for n in self.nodes[1].nodes)}]"
    return output


if __name__ == "__main__" and 1:
    ##################################################### test type declarations ######################
    mytype = "[2 .. 5]str"
    my_ast, rest = type_decl.parse(Input(mytype))
    print(my_ast.to_py())
    # raise SystemExit
    my_ast, rest = range_type.parse(Input("a .. 77"))
    print(my_ast.to_py())
    # my_ast,rest=basic_type.parse(Input("[5][10]str"))
    my_ast, rest = basic_type.parse(Input("[5]str"))
    print(my_ast.to_py())
    my_ast, rest = basic_type.parse(Input("[]str"))
    print(my_ast.to_py())
    my_ast, rest = basic_type.parse(Input("(int,str,float, []int)"))
    print(my_ast.to_py())
    my_ast, rest = basic_type.parse(Input("[int][float]str"))
    print(my_ast.to_py())
    my_ast, rest = pointer_type.parse(Input("*int"))
    my_ast, rest = pointer_type.parse(Input("*[int][float]str"))
    my_ast, rest = maybe_pointer_type.parse(Input("*[int][float]str"))
    print(my_ast.to_py())
    my_ast, rest = optional_type.parse(Input("str?"))
    my_ast, rest = maybe_optional_type.parse(Input("*[int][float]str?"))
    print(my_ast.to_py())
    my_ast, rest = union_type.parse(Input("str|float|mytype"))
    my_ast, rest = type_decl.parse(Input("str|*[]float?|mytype"))
    G.DEBUG = False
    my_ast, rest = type_decl.parse(
        Input("[(int,int)]bool")
    )  # a function is a mapping from tuple to type
    print(my_ast.to_py())
    my_ast, rest = type_decl.parse(
        Input("[(int,)]bool")
    )  # a function is a mapping from tuple to type
    print(my_ast.to_py())
    my_ast, rest = type_decl.parse(
        Input("[(,)]bool")
    )  # a function is a mapping from tuple to type
    print(my_ast.to_py())
    my_ast, rest = var_decl.parse(Input("name:str"))
    print(my_ast.to_py())
    #####################################
    my_ast, rest = type_decl.parse(Input("(name:str,code:int)"))
    # print(my_ast.to_py())
    raise SystemExit


def translate_typedecl_to_python(mytype):
    # print("Parsing",mytype)
    if "var" in mytype:
        mytype = mytype.replace("var ", "")
    if m := type_decl.parse(Input(mytype)):
        ast, rest = m
        return ast.to_py()
    return False


#####################################################################################################
class SymbolTable(list):
    def __init__(self, scope_type, parent_scope=None, scope_level=0, index_in_parent=0):
        self.scope_type = scope_type
        self.parent_scope = parent_scope
        self.current_level = scope_level  # current scope level
        self.index_in_parent = (
            index_in_parent  # index of this scope in the parent scope
        )
        self.current_idx = 0  # index in the current scope

    def enter_scope(self, scope_type):
        G.current_symbol_table = SymbolTable(
            scope_type, self, self.current_level + 1, self.current_idx
        )
        return G.current_symbol_table

    def leave_scope(self):
        G.current_symbol_table = self.parent_scope
        return G.current_symbol_table

    def add_symbol(self, name, type):
        super().append((name, type))
        self.current_idx += 1

    def _get_symb(self, the_name, max_index):
        max_index = max_index or self.current_idx
        for i, (name, type) in enumerate(self):
            if i > max_index:
                return None
            if name == the_name:
                return type

    def get_symbol(self, the_name, max_index=None):
        if res := self._get_symb(the_name, max_index):
            return res
        if self.parent_scope is not None:
            return self.parent_scope.get_symbol(the_name, self.index_in_parent)


class G:
    current_symbol_table = SymbolTable(MODULE)


if __name__ == "__main__" and 0:
    a = SymbolTable(MODULE)
    a.add_symbol("var11", "int")
    a.add_symbol("var12", "str")
    a.add_symbol("var13", "float")
    print(a.get_symbol("var12"))
    b = a.enter_scope(CLASS)
    b.add_symbol("var21", "int")
    b.add_symbol("var22", "str")
    b.add_symbol("var23", "float")
    print(b.get_symbol("var21"))
    print(b.get_symbol("var11"))
    c = b.enter_scope(FUNCTION)
    c.add_symbol("var31", "int")
    c.add_symbol("var32", "str")
    c.add_symbol("var33", "float")
    print(c.get_symbol("var11"))
    # raise SystemExit


@_simple_enum(IntEnum)
class Precedence:
    """Precedence table that originated from python grammar."""

    NAMED_EXPR = auto()  # <target> := <expr1>
    TUPLE = auto()  # <expr1>, <expr2>
    YIELD = auto()  # 'yield', 'yield from'
    TEST = auto()  # 'if'-'else', 'lambda'
    OR = auto()  # 'or'
    AND = auto()  # 'and'
    NOT = auto()  # 'not'
    CMP = auto()  # '<', '>', '==', '>=', '<=', '!=',
    # 'in', 'not in', 'is', 'is not'
    EXPR = auto()
    BOR = EXPR  # '|'
    BXOR = auto()  # '^'
    BAND = auto()  # '&'
    SHIFT = auto()  # '<<', '>>'
    ARITH = auto()  # '+', '-'
    TERM = auto()  # '*', '@', '/', '%', '//'
    FACTOR = auto()  # unary '+', '-', '~'
    POWER = auto()  # '**'
    AWAIT = auto()  # 'await'
    ATOM = auto()

    def next(self):
        try:
            return self.__class__(self + 1)
        except ValueError:
            return self


_SINGLE_QUOTES = "'", '"'
_MULTI_QUOTES = '"""', "'''"
_ALL_QUOTES = *_SINGLE_QUOTES, *_MULTI_QUOTES


def add_parent_attribute(node):
    def _fix(node, parent):
        node.parent = parent
        for child in iter_child_nodes(node):
            _fix(child, node)

    _fix(node, None)
    return node


def get_comments(lines, line_no, ELSE=False):
    if line_no == 1:  # the first line has no preceding comment !!!
        return None
    if ELSE:  # we have to search for the lineno containing the 'else:'
        while True:
            line, *rest = lines[line_no]
            if line.lstrip().startswith("else:"):
                break
            line_no -= 1
    start_backward_search = line_no - 1
    line, end_col_offset, start_lineno, end_lineno = lines[start_backward_search]
    # print (line_no,"==============>",line, end_col_offset, start_lineno, end_lineno)
    if start_lineno > 0 or line.lstrip().startswith("else:"):
        if "#" not in line[end_col_offset:]:
            return None
        cmt_idx = line.find("#", end_col_offset)
        padding = len(line[:cmt_idx]) - len(line[:cmt_idx].rstrip())
        return " " * padding + line[cmt_idx:]
    # we got 0
    plain_line_comments = []
    need_nl = False
    while True:
        if line.lstrip().startswith(('"""', "'''")) or "pass" in line:
            break
        if "#" in line[end_col_offset:]:  # plain-line comment or comment
            if end_col_offset > 0:  # eol-comment
                cmt_idx = line.find("#", end_col_offset)
                padding = len(line[:cmt_idx]) - len(line[:cmt_idx].rstrip())
                plain_line_comments.insert(0, " " * padding + line[cmt_idx:])
            else:  # plain-line comment
                plain_line_comments.insert(0, line)
                need_nl = True
        elif len(line.strip()) == 0:  # empty line
            plain_line_comments.insert(0, line)
        else:
            break
        start_backward_search -= 1
        if start_backward_search < 1 or start_lineno > 0:
            if start_lineno > 0:
                need_nl = False
            break
        line, end_col_offset, start_lineno, end_lineno = lines[start_backward_search]
        # print ("&&&&&&&&&&&&&&&&",line, end_col_offset, start_lineno, end_lineno)
    if need_nl:
        plain_line_comments.insert(0, "")
    return "\n".join(plain_line_comments)


class Unparser(NodeVisitor):
    """Methods in this class recursively traverse an AST and
    output source code for the abstract syntax; original formatting
    is disregarded."""

    def __init__(self, source, *, _avoid_backslashes=False):
        self.source = source
        self.source_lines = [
            (line, 0, 0, 0) for i, line in enumerate([""] + source.splitlines())
        ]  # line_no are 1-based !!!
        self._source = []
        self._precedences = {}
        self._type_ignores = {}
        self._indent = 0
        self._avoid_backslashes = _avoid_backslashes
        self._in_try_star = False
        self.current_lineno = 0

    def get_previous_line_comment(self, node):
        self.current_lineno = node.lineno
        return get_comments(self.source_lines, node.lineno)

    def items_view(self, traverser, items):
        """Traverse and separate the given *items* with a comma and append it to
        the buffer. If *items* is a single item sequence, a trailing comma
        will be added."""
        if len(items) == 1:
            traverser(items[0])
            self.write(",")
        else:
            interleave(lambda: self.write(", "), traverser, items)

    def newline(self, comment=None):
        if comment is None:
            self.write("\n")
        elif len(comment) == 0:  # empty line
            self.write("\n")
        else:
            self.write(f"{comment}\n")

    def fill(self, text="", comment=None):
        """Indent a piece of text and append it, according to the current
        indentation level"""
        self.newline(comment)
        self.write("    " * self._indent + text)

    def write(self, *text):
        """Add new source parts"""
        self._source.extend(text)

    @contextmanager
    def buffered(self, buffer=None):
        if buffer is None:
            buffer = []
        original_source = self._source
        self._source = buffer
        yield buffer
        self._source = original_source

    @contextmanager
    def block(self, *, extra=None):
        """A context manager for preparing the source for blocks. It adds
        the character':', increases the indentation on enter and decreases
        the indentation on exit. If *extra* is given, it will be directly
        appended after the colon character.
        """
        self.write(":")
        if extra:
            self.write(extra)
        self._indent += 1
        yield
        self._indent -= 1

    @contextmanager
    def delimit(self, start, end):
        """A context manager for preparing the source for expressions. It adds
        *start* to the buffer and enters, after exit it adds *end*."""
        self.write(start)
        start_idx = len(self._source)
        if sol_idx := rindex(self._source, "\n"):
            opening_paren_idx = len("".join(self._source[sol_idx:start_idx])) - 1
        yield
        end_idx = len(self._source)
        # print(self._source[sol_idx:])
        txt_inside_parens = "".join(self._source[start_idx:end_idx])
        # print("TEXT INSIDE PARENS=",txt_inside_parens)
        if len(txt_inside_parens) > 40:
            txt_lines = split_on_comma(txt_inside_parens)
            if (
                len(txt_lines) > 2 and sol_idx is not None
            ):  # only when more than 2 arguments
                import textwrap as tr

                self._source[start_idx:end_idx] = tr.indent(
                    ",\n".join(txt_lines), " " * opening_paren_idx
                ).lstrip()
        self.write(end)

    def delimit_if(self, start, end, condition):
        if condition:
            return self.delimit(start, end)
        else:
            return nullcontext()

    def require_parens(self, precedence, node):
        """Shortcut to adding precedence related parens"""
        return self.delimit_if("(", ")", self.get_precedence(node) > precedence)

    def get_precedence(self, node):
        return self._precedences.get(node, Precedence.TEST)

    def set_precedence(self, precedence, *nodes):
        for node in nodes:
            self._precedences[node] = precedence

    def get_raw_docstring(self, node):
        """If a docstring node is found in the body of the *node* parameter,
        return that docstring node, None otherwise.

        Logic mirrored from ``_PyAST_GetDocString``."""
        if (
            not isinstance(node, (AsyncFunctionDef, FunctionDef, ClassDef, Module))
            or len(node.body) < 1
        ):
            return None
        node = node.body[0]
        if not isinstance(node, Expr):
            return None
        node = node.value
        if isinstance(node, Constant) and isinstance(node.value, str):
            return node

    def get_type_comment(self, node):
        comment = self._type_ignores.get(node.lineno) or node.type_comment
        if comment is not None:
            return f" # type: {comment}"

    def traverse_annotation(self, node):
        if isinstance(node, Constant) and isinstance(node.value, str):
            mytype = node.value
            # print(f"{node.value=}")
        elif isinstance(node, Name):
            mytype = node.id
            # print(f"{node.id=}")
        else:
            raise Exception(f"Not foreseen: {node}")
        translated = translate_typedecl_to_python(mytype)
        # print("===>", translated)
        node = Name(translated)
        self.traverse(node)

    def traverse(self, node):
        if isinstance(node, list):
            for item in node:
                self.traverse(item)
        else:
            try:
                line, _, _, _ = self.source_lines[node.lineno]
                self.source_lines[node.lineno] = (
                    line,
                    node.end_col_offset,
                    node.lineno,
                    node.end_lineno,
                )
            except:
                pass
            super().visit(node)

    # Note: as visit() resets the output text, do NOT rely on
    # NodeVisitor.generic_visit to handle any nodes (as it calls back in to
    # the subclass visit() method, which resets self._source to an empty list)
    def visit(self, node):
        """Outputs a source code string that, if converted back to an ast
        (using ast.parse) will generate an AST equivalent to *node*"""
        self._source = []
        self.traverse(node)
        first_line = self._source[0]
        if first_line.startswith("\n"):
            return first_line.lstrip() + "".join(self._source[1:])
        else:
            return "".join(self._source)

    def _write_docstring_and_traverse_body(self, node):
        if docstring := self.get_raw_docstring(node):
            self._write_docstring(docstring)
            self.traverse(node.body[1:])
        else:
            self.traverse(node.body)

    def visit_Module(self, node):
        self._type_ignores = {
            ignore.lineno: f"ignore{ignore.tag}" for ignore in node.type_ignores
        }
        self._write_docstring_and_traverse_body(node)
        self._type_ignores.clear()

    def visit_FunctionType(self, node):
        with self.delimit("(", ")"):
            interleave(lambda: self.write(", "), self.traverse, node.argtypes)
        self.write(" -> ")
        self.traverse(node.returns)

    def visit_Expr(self, node):
        self.fill("", self.get_previous_line_comment(node))
        self.set_precedence(Precedence.YIELD, node.value)
        self.traverse(node.value)

    def visit_NamedExpr(self, node):
        # with self.require_parens(Precedence.NAMED_EXPR, node):
        # print(f"{node.parent.__class__.__name__=}")
        with self.delimit_if(
            "(",
            ")",
            self.get_precedence(node) > Precedence.NAMED_EXPR
            and node.parent.__class__.__name__ not in ("If", "While"),
        ):
            self.set_precedence(Precedence.ATOM, node.target, node.value)
            self.traverse(node.target)
            self.write(" := ")
            self.traverse(node.value)

    def visit_Import(self, node):
        self.fill("import ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.traverse, node.names)

    def visit_ImportFrom(self, node):
        self.fill("from ", self.get_previous_line_comment(node))
        self.write("." * (node.level or 0))
        if node.module:
            self.write(node.module)
        self.write(" import ")
        interleave(lambda: self.write(", "), self.traverse, node.names)

    def visit_Assign(self, node):
        self.fill("", self.get_previous_line_comment(node))
        for target in node.targets:
            self.set_precedence(Precedence.TUPLE, target)
            self.traverse(target)
            self.write(" = ")
        self.traverse(node.value)

    def visit_AugAssign(self, node):
        self.fill("", self.get_previous_line_comment(node))
        self.traverse(node.target)
        self.write(" " + self.binop[node.op.__class__.__name__] + "= ")
        self.traverse(node.value)

    def visit_AnnAssign(self, node):
        self.fill("", self.get_previous_line_comment(node))
        with self.delimit_if(
            "(", ")", not node.simple and isinstance(node.target, Name)
        ):
            self.traverse(node.target)
        self.write(": ")
        self.traverse_annotation(node.annotation)
        if node.value:
            self.write(" = ")
            self.traverse(node.value)

    def visit_Return(self, node):
        self.fill("return", self.get_previous_line_comment(node))
        if node.value:
            self.write(" ")
            self.traverse(node.value)

    def visit_Pass(self, node):
        self.fill("pass", self.get_previous_line_comment(node))

    def visit_Break(self, node):
        self.fill("break", self.get_previous_line_comment(node))

    def visit_Continue(self, node):
        self.fill("continue", self.get_previous_line_comment(node))

    def visit_Delete(self, node):
        self.fill("del ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.traverse, node.targets)

    def visit_Assert(self, node):
        self.fill("assert ", self.get_previous_line_comment(node))
        self.traverse(node.test)
        if node.msg:
            self.write(", ")
            self.traverse(node.msg)

    def visit_Global(self, node):
        self.fill("global ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.write, node.names)

    def visit_Nonlocal(self, node):
        self.fill("nonlocal ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.write, node.names)

    def visit_Await(self, node):
        with self.require_parens(Precedence.AWAIT, node):
            self.write("await")
            if node.value:
                self.write(" ")
                self.set_precedence(Precedence.ATOM, node.value)
                self.traverse(node.value)

    def visit_Yield(self, node):
        with self.require_parens(Precedence.YIELD, node):
            self.write("yield")
            if node.value:
                self.write(" ")
                self.set_precedence(Precedence.ATOM, node.value)
                self.traverse(node.value)

    def visit_YieldFrom(self, node):
        with self.require_parens(Precedence.YIELD, node):
            self.write("yield from ")
            if not node.value:
                raise ValueError("Node can't be used without a value attribute.")
            self.set_precedence(Precedence.ATOM, node.value)
            self.traverse(node.value)

    def visit_Raise(self, node):
        self.fill("raise", self.get_previous_line_comment(node))
        if not node.exc:
            if node.cause:
                raise ValueError(f"Node can't use cause without an exception.")
            return
        self.write(" ")
        self.traverse(node.exc)
        if node.cause:
            self.write(" from ")
            self.traverse(node.cause)

    def do_visit_try(self, node):
        self.fill("try", self.get_previous_line_comment(node))
        with self.block():
            self.traverse(node.body)
        for ex in node.handlers:
            self.traverse(ex)
        if node.orelse:
            # self.fill('else', self.get_previous_line_comment(node))
            self.fill(
                "else",
                get_comments(self.source_lines, node.orelse[0].lineno - 1, ELSE=True),
            )
            with self.block():
                self.traverse(node.orelse)
        if node.finalbody:
            self.fill("finally", self.get_previous_line_comment(node))
            with self.block():
                self.traverse(node.finalbody)

    def visit_Try(self, node):
        prev_in_try_star = self._in_try_star
        try:
            self._in_try_star = False
            self.do_visit_try(node)
        finally:
            self._in_try_star = prev_in_try_star

    def visit_TryStar(self, node):
        prev_in_try_star = self._in_try_star
        try:
            self._in_try_star = True
            self.do_visit_try(node)
        finally:
            self._in_try_star = prev_in_try_star

    def visit_ExceptHandler(self, node):
        self.fill(
            "except*" if self._in_try_star else "except",
            self.get_previous_line_comment(node),
        )
        if node.type:
            self.write(" ")
            self.traverse(node.type)
        if node.name:
            self.write(" as ")
            self.write(node.name)
        with self.block():
            self.traverse(node.body)

    def visit_ClassDef(self, node):
        G.current_symbol_table.enter_scope(CLASS)
        self.newline()
        for deco in node.decorator_list:
            self.fill("@", self.get_previous_line_comment(node))
            self.traverse(deco)
        self.fill("class " + node.name, self.get_previous_line_comment(node))
        with self.delimit_if("(", ")", condition=node.bases or node.keywords):
            comma = False
            for e in node.bases:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)
            for e in node.keywords:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)
        with self.block():
            self._write_docstring_and_traverse_body(node)
        G.current_symbol_table.leave_scope()

    def visit_FunctionDef(self, node):
        G.current_symbol_table.enter_scope(FUNCTION)
        self._function_helper(node, "def")
        G.current_symbol_table.leave_scope()

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, "async def")

    def _function_helper(self, node, fill_suffix):
        # print(node.parent.__class__.__name__)
        if node.parent.__class__.__name__ in ("Module", "ClassDef"):
            self.newline()
        for deco in node.decorator_list:
            self.fill("@", self.get_previous_line_comment(node))
            self.traverse(deco)
        def_str = fill_suffix + " " + node.name
        self.fill(def_str, self.get_previous_line_comment(node))
        with self.delimit("(", ")"):
            self.traverse(node.args)
        if node.returns:
            self.write(" -> ")
            self.traverse_annotation(node.returns)
        with self.block(extra=self.get_type_comment(node)):
            self._write_docstring_and_traverse_body(node)

    def visit_For(self, node):
        self._for_helper("for ", node)

    def visit_AsyncFor(self, node):
        self._for_helper("async for ", node)

    def _for_helper(self, fill, node):
        self.fill(fill, self.get_previous_line_comment(node))
        self.set_precedence(Precedence.TUPLE, node.target)
        self.traverse(node.target)
        self.write(" in ")
        self.traverse(node.iter)
        with self.block(extra=self.get_type_comment(node)):
            self.traverse(node.body)
        if node.orelse:
            # self.fill('else', self.get_previous_line_comment(node))
            self.fill(
                "else",
                get_comments(self.source_lines, node.orelse.lineno - 1, ELSE=True),
            )
            with self.block():
                self.traverse(node.orelse)

    def visit_If(self, node):
        self.fill("if ", self.get_previous_line_comment(node))
        # print(f"{node.lineno=}")
        self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        # collapse nested ifs into equivalent elifs.
        while node.orelse and len(node.orelse) == 1 and isinstance(node.orelse[0], If):
            node = node.orelse[0]
            self.fill(
                "elif ", get_comments(self.source_lines, node.lineno - 1, ELSE=True)
            )
            self.traverse(node.test)
            with self.block():
                self.traverse(node.body)
        # final else
        if node.orelse:
            # print(f"ELSE {type(node.orelse[0])=} {node.orelse[0].lineno=}")
            self.fill(
                "else",
                get_comments(self.source_lines, node.orelse[0].lineno - 1, ELSE=True),
            )
            with self.block():
                self.traverse(node.orelse)

    def visit_While(self, node):
        self.fill("while ", self.get_previous_line_comment(node))
        self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        if node.orelse:
            # self.fill('else', self.get_previous_line_comment(node))
            self.fill(
                "else",
                get_comments(self.source_lines, node.orelse.lineno - 1, ELSE=True),
            )
            with self.block():
                self.traverse(node.orelse)

    def visit_With(self, node):
        self.fill("with ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.traverse, node.items)
        with self.block(extra=self.get_type_comment(node)):
            self.traverse(node.body)

    def visit_AsyncWith(self, node):
        self.fill("async with ", self.get_previous_line_comment(node))
        interleave(lambda: self.write(", "), self.traverse, node.items)
        with self.block(extra=self.get_type_comment(node)):
            self.traverse(node.body)

    def _str_literal_helper(
        self, string, *, quote_types=_ALL_QUOTES, escape_special_whitespace=False
    ):
        """Helper for writing string literals, minimizing escapes.
        Returns the tuple (string literal to write, possible quote types).
        """

        def escape_char(c):
            # \n and \t are non-printable, but we only escape them if
            # escape_special_whitespace is True
            if not escape_special_whitespace and c in "\n\t":
                return c
            # Always escape backslashes and other non-printable characters
            if c == "\\" or not c.isprintable():
                return c.encode("unicode_escape").decode("ascii")
            return c

        escaped_string = "".join(map(escape_char, string))
        possible_quotes = quote_types
        if "\n" in escaped_string:
            possible_quotes = [q for q in possible_quotes if q in _MULTI_QUOTES]
        possible_quotes = [q for q in possible_quotes if q not in escaped_string]
        if not possible_quotes:
            # If there aren't any possible_quotes, fallback to using repr
            # on the original string. Try to use a quote from quote_types,
            # e.g., so that we use triple quotes for docstrings.
            string = repr(string)
            quote = next((q for q in quote_types if string[0] in q), string[0])
            return string[1:-1], [quote]
        if escaped_string:
            # Sort so that we prefer '''"''' over """\""""
            possible_quotes.sort(key=lambda q: q[0] == escaped_string[-1])
            # If we're using triple quotes and we'd need to escape a final
            # quote, escape it
            if possible_quotes[0][0] == escaped_string[-1]:
                assert len(possible_quotes[0]) == 3
                escaped_string = escaped_string[:-1] + "\\" + escaped_string[-1]
        return escaped_string, possible_quotes

    def _write_str_avoiding_backslashes(self, string, *, quote_types=_ALL_QUOTES):
        """Write string literal value with a best effort attempt to avoid backslashes."""
        string, quote_types = self._str_literal_helper(string, quote_types=quote_types)
        quote_type = quote_types[1]
        self.write(f"{quote_type}{string}{quote_type}")

    def visit_JoinedStr(self, node):
        self.write("f")
        if self._avoid_backslashes:
            with self.buffered() as buffer:
                self._write_fstring_inner(node)
            return self._write_str_avoiding_backslashes("".join(buffer))

        # If we don't need to avoid backslashes globally (i.e., we only need
        # to avoid them inside FormattedValues), it's cosmetically preferred
        # to use escaped whitespace. That is, it's preferred to use backslashes
        # for cases like: f"{x}\n". To accomplish this, we keep track of what
        # in our buffer corresponds to FormattedValues and what corresponds to
        # Constant parts of the f-string, and allow escapes accordingly.
        fstring_parts = []
        for value in node.values:
            with self.buffered() as buffer:
                self._write_fstring_inner(value)
            fstring_parts.append(("".join(buffer), isinstance(value, Constant)))
        new_fstring_parts = []
        quote_types = list(_ALL_QUOTES)
        for value, is_constant in fstring_parts:
            value, quote_types = self._str_literal_helper(
                value, quote_types=quote_types, escape_special_whitespace=is_constant
            )
            new_fstring_parts.append(value)
        value = "".join(new_fstring_parts)
        quote_type = quote_types[0]
        self.write(f"{quote_type}{value}{quote_type}")

    def _write_fstring_inner(self, node):
        if isinstance(node, JoinedStr):
            # for both the f-string itself, and format_spec
            for value in node.values:
                self._write_fstring_inner(value)
        elif isinstance(node, Constant) and isinstance(node.value, str):
            value = node.value.replace("{", "{{").replace("}", "}}")
            self.write(value)
        elif isinstance(node, FormattedValue):
            self.visit_FormattedValue(node)
        else:
            raise ValueError(f"Unexpected node inside JoinedStr, {node!r}")

    def visit_FormattedValue(self, node):
        def unparse_inner(inner):
            unparser = type(self)(self.source, _avoid_backslashes=True)
            unparser.set_precedence(Precedence.TEST.next(), inner)
            return unparser.visit(inner)

        with self.delimit("{", "}"):
            expr = unparse_inner(node.value)
            if "\\" in expr:
                raise ValueError(
                    "Unable to avoid backslash in f-string expression part"
                )
            if expr.startswith("{"):
                # Separate pair of opening brackets as "{ {"
                self.write(" ")
            self.write(expr)
            if node.conversion != -1:
                self.write(f"!{chr(node.conversion)}")
            if node.format_spec:
                self.write(":")
                self._write_fstring_inner(node.format_spec)

    def visit_Name(self, node):
        self.write(node.id)

    def _write_docstring(self, node):
        self.fill("", self.get_previous_line_comment(node))
        if node.kind == "u":
            self.write("u")
        self._write_str_avoiding_backslashes(node.value, quote_types=_MULTI_QUOTES)

    def _write_constant(self, value):
        if isinstance(value, (float, complex)):
            # Substitute overflowing decimal literal for AST infinities,
            # and inf - inf for NaNs.
            self.write(
                repr(value)
                .replace("inf", _INFSTR)
                .replace("nan", f"({_INFSTR}-{_INFSTR})")
            )
        elif self._avoid_backslashes and isinstance(value, str):
            self._write_str_avoiding_backslashes(value)
        else:
            self.write(repr(value))

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, tuple):
            with self.delimit("(", ")"):
                self.items_view(self._write_constant, value)
        elif value is ...:
            self.write("...")
        elif (
            isinstance(value, str)
            and hasattr(node, "end_lineno")
            and node.end_lineno
            and node.end_lineno > node.lineno
        ):
            # Multi-line string: extract original source to preserve triple quotes
            lines = [
                line[0] for line in self.source_lines
            ]  # source_lines is list of (line, ...) tuples
            first = lines[node.lineno]
            if node.lineno == node.end_lineno:
                original = first[node.col_offset : node.end_col_offset]
            else:
                parts = [first[node.col_offset :]]
                for ln in range(node.lineno + 1, node.end_lineno):
                    parts.append(lines[ln])
                parts.append(lines[node.end_lineno][: node.end_col_offset])
                original = chr(10).join(parts)
            self.write(original)
        else:
            if node.kind == "u":
                self.write("u")
            self._write_constant(node.value)

    def visit_List(self, node):
        with self.delimit("[", "]"):
            interleave(lambda: self.write(", "), self.traverse, node.elts)

    def visit_ListComp(self, node):
        with self.delimit("[", "]"):
            self.traverse(node.elt)
            for gen in node.generators:
                self.traverse(gen)

    def visit_GeneratorExp(self, node):
        with self.delimit("(", ")"):
            self.traverse(node.elt)
            for gen in node.generators:
                self.traverse(gen)

    def visit_SetComp(self, node):
        with self.delimit("{", "}"):
            self.traverse(node.elt)
            for gen in node.generators:
                self.traverse(gen)

    def visit_DictComp(self, node):
        with self.delimit("{", "}"):
            self.traverse(node.key)
            self.write(": ")
            self.traverse(node.value)
            for gen in node.generators:
                self.traverse(gen)

    def visit_comprehension(self, node):
        if node.is_async:
            self.write(" async for ")
        else:
            self.write(" for ")
        self.set_precedence(Precedence.TUPLE, node.target)
        self.traverse(node.target)
        self.write(" in ")
        self.set_precedence(Precedence.TEST.next(), node.iter, *node.ifs)
        self.traverse(node.iter)
        for if_clause in node.ifs:
            self.write(" if ")
            self.traverse(if_clause)

    def visit_IfExp(self, node):
        with self.require_parens(Precedence.TEST, node):
            self.set_precedence(Precedence.TEST.next(), node.body, node.test)
            self.traverse(node.body)
            self.write(" if ")
            self.traverse(node.test)
            self.write(" else ")
            self.set_precedence(Precedence.TEST, node.orelse)
            self.traverse(node.orelse)

    def visit_Set(self, node):
        if node.elts:
            with self.delimit("{", "}"):
                interleave(lambda: self.write(", "), self.traverse, node.elts)
        else:
            # `{}` would be interpreted as a dictionary literal, and
            # `set` might be shadowed. Thus:
            self.write("{*()}")

    def visit_Dict(self, node):
        def write_key_value_pair(k, v):
            self.traverse(k)
            self.write(": ")
            self.traverse(v)

        def write_item(item):
            k, v = item
            if k is None:
                # for dictionary unpacking operator in dicts {**{'y': 2}}
                # see PEP 448 for details
                self.write("**")
                self.set_precedence(Precedence.EXPR, v)
                self.traverse(v)
            else:
                write_key_value_pair(k, v)

        with self.delimit("{", "}"):
            interleave(
                lambda: self.write(", "), write_item, zip(node.keys, node.values)
            )

    def visit_Tuple(self, node):
        # from see import see
        # print(see(node))
        # print(f"{node.parent.__class__.__name__=}")
        with self.delimit_if(
            "(",
            ")",
            (len(node.elts) == 0 or self.get_precedence(node) > Precedence.TUPLE)
            and node.parent.__class__.__name__ not in ("Return", "Assign"),
        ):
            self.items_view(self.traverse, node.elts)

    unop = {"Invert": "~", "Not": "not", "UAdd": "+", "USub": "-"}
    unop_precedence = {
        "not": Precedence.NOT,
        "~": Precedence.FACTOR,
        "+": Precedence.FACTOR,
        "-": Precedence.FACTOR,
    }

    def visit_UnaryOp(self, node):
        operator = self.unop[node.op.__class__.__name__]
        operator_precedence = self.unop_precedence[operator]
        with self.require_parens(operator_precedence, node):
            self.write(operator)
            # factor prefixes (+, -, ~) shouldn't be separated
            # from the value they belong, (e.g: +1 instead of + 1)
            if operator_precedence is not Precedence.FACTOR:
                self.write(" ")
            self.set_precedence(operator_precedence, node.operand)
            self.traverse(node.operand)

    binop = {
        "Add": "+",
        "Sub": "-",
        "Mult": "*",
        "MatMult": "@",
        "Div": "/",
        "Mod": "%",
        "LShift": "<<",
        "RShift": ">>",
        "BitOr": "|",
        "BitXor": "^",
        "BitAnd": "&",
        "FloorDiv": "//",
        "Pow": "**",
    }

    binop_precedence = {
        "+": Precedence.ARITH,
        "-": Precedence.ARITH,
        "*": Precedence.TERM,
        "@": Precedence.TERM,
        "/": Precedence.TERM,
        "%": Precedence.TERM,
        "<<": Precedence.SHIFT,
        ">>": Precedence.SHIFT,
        "|": Precedence.BOR,
        "^": Precedence.BXOR,
        "&": Precedence.BAND,
        "//": Precedence.TERM,
        "**": Precedence.POWER,
    }

    binop_rassoc = frozenset(("**",))

    def visit_BinOp(self, node):
        operator = self.binop[node.op.__class__.__name__]
        operator_precedence = self.binop_precedence[operator]
        with self.require_parens(operator_precedence, node):
            if operator in self.binop_rassoc:
                left_precedence = operator_precedence.next()
                right_precedence = operator_precedence
            else:
                left_precedence = operator_precedence
                right_precedence = operator_precedence.next()
            self.set_precedence(left_precedence, node.left)
            self.traverse(node.left)
            self.write(f" {operator} ")
            self.set_precedence(right_precedence, node.right)
            self.traverse(node.right)

    cmpops = {
        "Eq": "==",
        "NotEq": "!=",
        "Lt": "<",
        "LtE": "<=",
        "Gt": ">",
        "GtE": ">=",
        "Is": "is",
        "IsNot": "is not",
        "In": "in",
        "NotIn": "not in",
    }

    def visit_Compare(self, node):
        with self.require_parens(Precedence.CMP, node):
            self.set_precedence(Precedence.CMP.next(), node.left, *node.comparators)
            self.traverse(node.left)
            for o, e in zip(node.ops, node.comparators):
                self.write(" " + self.cmpops[o.__class__.__name__] + " ")
                self.traverse(e)

    boolops = {"And": "and", "Or": "or"}
    boolop_precedence = {"and": Precedence.AND, "or": Precedence.OR}

    def visit_BoolOp(self, node):
        operator = self.boolops[node.op.__class__.__name__]
        operator_precedence = self.boolop_precedence[operator]

        def increasing_level_traverse(node):
            nonlocal operator_precedence
            operator_precedence = operator_precedence.next()
            self.set_precedence(operator_precedence, node)
            self.traverse(node)

        with self.require_parens(operator_precedence, node):
            s = f" {operator} "
            interleave(lambda: self.write(s), increasing_level_traverse, node.values)

    def visit_Attribute(self, node):
        self.set_precedence(Precedence.ATOM, node.value)
        self.traverse(node.value)
        # Special case: 3.__abs__() is a syntax error, so if node.value
        # is an integer literal then we need to either parenthesize
        # it or add an extra space to get 3 .__abs__().
        if isinstance(node.value, Constant) and isinstance(node.value.value, int):
            self.write(" ")
        self.write(".")
        self.write(node.attr)

    def visit_Call(self, node):
        self.set_precedence(Precedence.ATOM, node.func)
        self.traverse(node.func)
        with self.delimit("(", ")"):
            comma = False
            for e in node.args:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)
            for e in node.keywords:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)

    def visit_Subscript(self, node):
        def is_non_empty_tuple(slice_value):
            return isinstance(slice_value, Tuple) and slice_value.elts

        self.set_precedence(Precedence.ATOM, node.value)
        self.traverse(node.value)
        with self.delimit("[", "]"):
            if is_non_empty_tuple(node.slice):
                # parentheses can be omitted if the tuple isn't empty
                self.items_view(self.traverse, node.slice.elts)
            else:
                self.traverse(node.slice)

    def visit_Starred(self, node):
        self.write("*")
        self.set_precedence(Precedence.EXPR, node.value)
        self.traverse(node.value)

    def visit_Ellipsis(self, node):
        self.write("...")

    def visit_Slice(self, node):
        if node.lower:
            self.traverse(node.lower)
        self.write(":")
        if node.upper:
            self.traverse(node.upper)
        if node.step:
            self.write(":")
            self.traverse(node.step)

    def visit_Match(self, node):
        self.fill("match ", self.get_previous_line_comment(node))
        self.traverse(node.subject)
        with self.block():
            for case in node.cases:
                self.traverse(case)

    def visit_arg(self, node):
        self.write(node.arg)
        if node.annotation:
            self.write(": ")
            self.traverse_annotation(node.annotation)

    def visit_arguments(self, node):
        first = True
        # normal arguments
        all_args = node.posonlyargs + node.args
        defaults = [None] * (len(all_args) - len(node.defaults)) + node.defaults
        for index, elements in enumerate(zip(all_args, defaults), 1):
            a, d = elements
            if first:
                first = False
            else:
                self.write(", ")
            self.traverse(a)
            if d:
                self.write("=")
                self.traverse(d)
            if index == len(node.posonlyargs):
                self.write(", /")
        # varargs, or bare '*' if no varargs but keyword-only arguments present
        if node.vararg or node.kwonlyargs:
            if first:
                first = False
            else:
                self.write(", ")
            self.write("*")
            if node.vararg:
                self.write(node.vararg.arg)
                if node.vararg.annotation:
                    self.write(": ")
                    self.traverse_annotation(node.vararg.annotation)
        # keyword-only arguments
        if node.kwonlyargs:
            for a, d in zip(node.kwonlyargs, node.kw_defaults):
                self.write(", ")
                self.traverse(a)
                if d:
                    self.write("=")
                    self.traverse(d)
        # kwargs
        if node.kwarg:
            if first:
                first = False
            else:
                self.write(", ")
            self.write("**" + node.kwarg.arg)
            if node.kwarg.annotation:
                self.write(": ")
                self.traverse_annotation(node.kwarg.annotation)

    def visit_keyword(self, node):
        if node.arg is None:
            self.write("**")
        else:
            self.write(node.arg)
            self.write("=")
        self.traverse(node.value)

    def visit_Lambda(self, node):
        with self.require_parens(Precedence.TEST, node):
            self.write("lambda")
            with self.buffered() as buffer:
                self.traverse(node.args)
            if buffer:
                self.write(" ", *buffer)
            self.write(": ")
            self.set_precedence(Precedence.TEST, node.body)
            self.traverse(node.body)

    def visit_alias(self, node):
        self.write(node.name)
        if node.asname:
            self.write(" as " + node.asname)

    def visit_withitem(self, node):
        self.traverse(node.context_expr)
        if node.optional_vars:
            self.write(" as ")
            self.traverse(node.optional_vars)

    def visit_match_case(self, node):
        self.fill("case ", self.get_previous_line_comment(node))
        self.traverse(node.pattern)
        if node.guard:
            self.write(" if ")
            self.traverse(node.guard)
        with self.block():
            self.traverse(node.body)

    def visit_MatchValue(self, node):
        self.traverse(node.value)

    def visit_MatchSingleton(self, node):
        self._write_constant(node.value)

    def visit_MatchSequence(self, node):
        with self.delimit("[", "]"):
            interleave(lambda: self.write(", "), self.traverse, node.patterns)

    def visit_MatchStar(self, node):
        name = node.name
        if name is None:
            name = "_"
        self.write(f"*{name}")

    def visit_MatchMapping(self, node):
        def write_key_pattern_pair(pair):
            k, p = pair
            self.traverse(k)
            self.write(": ")
            self.traverse(p)

        with self.delimit("{", "}"):
            keys = node.keys
            interleave(
                lambda: self.write(", "),
                write_key_pattern_pair,
                zip(keys, node.patterns, strict=True),
            )
            rest = node.rest
            if rest is not None:
                if keys:
                    self.write(", ")
                self.write(f"**{rest}")

    def visit_MatchClass(self, node):
        self.set_precedence(Precedence.ATOM, node.cls)
        self.traverse(node.cls)
        with self.delimit("(", ")"):
            patterns = node.patterns
            interleave(lambda: self.write(", "), self.traverse, patterns)
            attrs = node.kwd_attrs
            if attrs:

                def write_attr_pattern(pair):
                    attr, pattern = pair
                    self.write(f"{attr}=")
                    self.traverse(pattern)

                if patterns:
                    self.write(", ")
                interleave(
                    lambda: self.write(", "),
                    write_attr_pattern,
                    zip(attrs, node.kwd_patterns, strict=True),
                )

    def visit_MatchAs(self, node):
        name = node.name
        pattern = node.pattern
        if name is None:
            self.write("_")
        elif pattern is None:
            self.write(node.name)
        else:
            with self.require_parens(Precedence.TEST, node):
                self.set_precedence(Precedence.BOR, node.pattern)
                self.traverse(node.pattern)
                self.write(f" as {node.name}")

    def visit_MatchOr(self, node):
        with self.require_parens(Precedence.BOR, node):
            self.set_precedence(Precedence.BOR.next(), *node.patterns)
            interleave(lambda: self.write(" | "), self.traverse, node.patterns)


def preprocess(code):
    def remove_comment(line):
        return line
        # return line.rsplit('#',1)[0]

    lines = []
    for line in code.splitlines():
        line = remove_comment(line)
        if line.lstrip().startswith("def"):
            if m := BetweenMatchingBrackets("()").search(line):
                for arg_decl in split_on_comma(
                    m[0].string[m[0].start() + 1 : m[0].end() - 1]
                ):  # we remove the outer parentheses
                    if ":" in arg_decl:
                        var, type_declaration = arg_decl.split(":", 1)
                        if not type_declaration.strip().isidentifier():
                            line = line.replace(
                                arg_decl, f'{var.rstrip()}:"{type_declaration.strip()}"'
                            )
            ret_type = "->" + UnnamedGroup(ANYCHARS) + ":"
            line = ret_type.sub(
                lambda m: f'->"{m[1].strip()}":'
                if not m[1].strip().isidentifier()
                else f"-> {m[1].strip()}:",
                line,
            )
        elif m := VAR_DECL.match(line):
            if not m[2].strip().isidentifier() and not iskeyword(m[1].strip()):
                line = VAR_DECL.sub(
                    lambda m: f'{m[1].rstrip()}:"{m[2].lstrip()}"', line
                )
            # else:
            #    print(m[2].strip())
        elif line.lstrip().startswith("type ") and " is " in line:
            # type x is y ==> x: TypeAlias = y
            parts = line.lstrip().split(" ", 4)
            indent = " " * (len(line) - len(line.lstrip()))
            if m := type_decl.parse(Input(parts[3])):
                ast, _ = m
                line = f"{indent}{parts[1]}: TypeAlias = {ast.to_py()} {''.join(parts[4:])}"
                # print(line)
            else:
                print("Syntax Error:", line)
                raise SystemExit
        package_regex = "package" + SOMESPACE + UnnamedGroup(hek_rxe.IDENTIFIER) + ":"
        # package_regex=('package'+SOMESPACE+UnnamedGroup(hek_rxe.IDENTIFIER)+':').filter_matches(hek_rxe.BETWEENQUOTES)
        line = package_regex.sub(lambda m: f"class {m[1]}:", line)
        lines.append(line)
    return "\n".join(lines)


a = """\
type vandermonde is []row # vandermonde: seq[seq[int]]
package Hello:
    def talk(self, *args: int) -> (name:str, code:int):
    def hello(a:int,b:[5][10]float)->[]str:
        a:[]int
        b:str
        if '#' in line[end_col_offset:]: # plain-line comment or comment
            if end_col_offset > 0: # eol-comment
                cmt_idx = line.find('#', end_col_offset)
            else: # plain-line comment
                plain_line_comments.insert(0, line)
                need_nl = True

"""
# print(preprocess(a))
# raise SystemExit


def convert(source):
    source = preprocess(source)
    # print("===>")
    # print(source)
    # print(source, file=open('converted.py','w'))
    # print("===>")
    # raise SystemExit
    unparser = Unparser(source)
    ast_obj = ast.parse(source)
    add_parent_attribute(ast_obj)
    return unparser.visit(ast_obj)


if __name__ == "__main__" and 1:
    file = sys.argv[1] if sys.argv[1:] else __file__
    with open(file) as f:
        print(convert(f.read()))
else:
    ############################################################# TEST CODE ########################################
    code = """\
class Parent: # comment
  ddd: range
  names: []str
  names: [9]str
  names: [2 .. 5]str
  def __init__(self,name : str):
    self.name = name
  def speak(self):
    print("I am the Parent")
  def cry(self):
    self.talk() # call child method
  def __str__(self):
    return "PARENT"
  def __del__(self):
    print("deleting")

class Child(Parent):
  age: int
  def __init__(self, name: str, age: int):
    super().__init__(name) # call parent constructor
    self.age = age
  def speak(self, rep:[*]int) -> str:
    super().speak() # call parent method
    print("I am the child")
    return "HELLO"
  def talk(self, *args: int) -> int:
    print("child talks")
    return 5
  def __str__(self):
    return "CHILD"

a:Child = new_Child("mickey",20)
a.speak()
a.cry()
package Utils:
  def getAlphabet(a:[*]int) -> (code:int,name:str):
    type My_Array_t is [10]float
    type row is []int
    type vandermonde is []row # vandermonde: seq[seq[int]]
    accm : str = f"dddd{var}"
    x : int = 5
    vandermonde= new(5, row) # allocation-> newSeq[row](5)
    for letter in "'a'..'z'":  # see iterators0
      row= new(int) # allocation -> newSeq[int]()
      accm.add(letter[1:2]) # exclusive
      accm.add(letter["1 .. 2"]) #inclusive
      accm.add(letter[:2])
      accm.add(letter[1:])
    return accm.first
  def square(inSeq:[]float) -> []int:
    result = new(len(inSeq),float)
    for i, v in "!ls -rtl":
      result[i] = v*v;

"""
    print(convert(code))
