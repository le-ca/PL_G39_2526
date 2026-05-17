# Analisador sintatico com ply.yacc.
#
# Notas sobre a gramatica:
#  - O Fortran 77 e baseado em linhas. Para o yacc trabalhar com isso
#    tivemos de introduzir um token artificial EOL no fim de cada linha
#    e um token LABEL no inicio das linhas que tenham label.
#  - O LineLexer la em baixo trata de partir o source linha a linha e
#    injetar esses tokens, alimentando depois o lexer "normal" do PLY
#    com o texto de cada linha.

from collections import deque

import ply.lex as plex
import ply.yacc as yacc

from .ast_nodes import (
    ArrayDim, ArrayTarget, Assignment, BinaryOp, CallExpr, CallStmt,
    ContinueStmt, DeclItem, Declaration, DoStmt, ElifBranch,
    FunctionDef, GotoStmt, IfStmt, IntLiteral, LogicalLiteral, Labeled,
    PrintStmt, Program, ReadStmt, RealLiteral, ReturnStmt, StopStmt,
    StringLiteral, SubroutineDef, UnaryOp, VarRef, VarTarget,
)
from .errors import ParserError
from .lexer import make_lexer, tokens as base_tokens
from .preprocess import SourceLine


# O parser tem 2 tokens extra alem dos do lexer: LABEL e EOL
tokens = base_tokens + ["LABEL", "EOL"]


# Precedencia dos operadores, do mais baixo para o mais alto.
# Isto e directamente o que esta na seccao de "expressions" do standard.
precedence = (
    ("left",   "OR"),
    ("left",   "AND"),
    ("right",  "NOT"),
    ("nonassoc", "LT", "LE", "GT", "GE", "EQ", "NE"),
    ("left",   "+", "-"),
    ("left",   "*", "/"),
    ("right",  "UMINUS", "UPLUS"),
)


def _attach_label(stmt, label):
    """Embrulha o stmt num Labeled se tiver label, senao deixa na mesma."""
    if label is None:
        return stmt
    return Labeled(label, stmt)


# ============================================================
# regras
# ============================================================

def p_program(p):
    "program : PROGRAM ID EOL decl_list stmt_list END opt_eol subprogram_list"
    p[0] = Program(
        name=p[2],
        declarations=p[4],
        statements=p[5],
        subprograms=p[8],
    )


# ---- subprogramas (FUNCTION / SUBROUTINE) ----

def p_subprogram_list(p):
    """subprogram_list : subprogram_list subprogram
                       | empty"""
    if len(p) == 3:
        p[1].append(p[2])
        p[0] = p[1]
    else:
        p[0] = []


def p_subprogram(p):
    """subprogram : function_def
                  | subroutine_def"""
    p[0] = p[1]


def p_function_def(p):
    "function_def : type_spec FUNCTION ID '(' opt_id_list ')' EOL decl_list stmt_list END opt_eol"
    p[0] = FunctionDef(
        name=p[3],
        return_type=p[1],
        params=p[5],
        declarations=p[8],
        statements=p[9],
    )


def p_subroutine_def(p):
    "subroutine_def : SUBROUTINE ID '(' opt_id_list ')' EOL decl_list stmt_list END opt_eol"
    p[0] = SubroutineDef(
        name=p[2],
        params=p[4],
        declarations=p[7],
        statements=p[8],
    )


def p_opt_id_list(p):
    """opt_id_list : id_list
                   | empty"""
    p[0] = p[1] or []


def p_id_list_single(p):
    "id_list : ID"
    p[0] = [p[1]]


def p_id_list_many(p):
    "id_list : id_list ',' ID"
    p[1].append(p[3])
    p[0] = p[1]


def p_opt_eol(p):
    """opt_eol : EOL
               | empty"""
    p[0] = None


# ---- declaracoes ----

def p_decl_list(p):
    """decl_list : decl_list declaration
                 | empty"""
    if len(p) == 3:
        p[1].append(p[2])
        p[0] = p[1]
    else:
        p[0] = []


def p_declaration(p):
    "declaration : type_spec decl_items EOL"
    p[0] = Declaration(type_name=p[1], items=p[2])


def p_type_spec(p):
    """type_spec : INTEGER
                 | REAL
                 | LOGICAL"""
    p[0] = p[1]


def p_decl_items_single(p):
    "decl_items : decl_item"
    p[0] = [p[1]]


def p_decl_items_many(p):
    "decl_items : decl_items ',' decl_item"
    p[1].append(p[3])
    p[0] = p[1]


def p_decl_item_scalar(p):
    "decl_item : ID"
    p[0] = DeclItem(name=p[1])


def p_decl_item_array(p):
    "decl_item : ID '(' dim_spec_list ')'"
    p[0] = DeclItem(name=p[1], dims=p[3])


def p_dim_spec_list_single(p):
    "dim_spec_list : dim_spec"
    p[0] = [p[1]]


def p_dim_spec_list_many(p):
    "dim_spec_list : dim_spec_list ',' dim_spec"
    p[1].append(p[3])
    p[0] = p[1]


def p_dim_spec_simple(p):
    "dim_spec : signed_int"
    # ARR(N)  ->  bounds [1, N]
    p[0] = ArrayDim(lower=1, upper=p[1])


def p_dim_spec_range(p):
    "dim_spec : signed_int ':' signed_int"
    # ARR(L:U)
    p[0] = ArrayDim(lower=p[1], upper=p[3])


def p_signed_int_plain(p):
    "signed_int : INT_CONST"
    p[0] = p[1]


def p_signed_int_plus(p):
    "signed_int : '+' INT_CONST"
    p[0] = p[2]


def p_signed_int_minus(p):
    "signed_int : '-' INT_CONST"
    p[0] = -p[2]


# ---- lista de instrucoes ----

def p_stmt_list(p):
    """stmt_list : stmt_list stmt
                 | empty"""
    if len(p) == 3:
        p[1].append(p[2])
        p[0] = p[1]
    else:
        p[0] = []


def p_stmt_simple(p):
    "stmt : opt_label simple_stmt EOL"
    p[0] = _attach_label(p[2], p[1])


def p_stmt_if(p):
    # o if ja tem EOLs proprios na if_tail
    "stmt : opt_label if_stmt"
    p[0] = _attach_label(p[2], p[1])


def p_opt_label(p):
    """opt_label : LABEL
                 | empty"""
    p[0] = p[1]


def p_simple_stmt(p):
    """simple_stmt : assignment
                   | print_stmt
                   | read_stmt
                   | goto_stmt
                   | continue_stmt
                   | do_stmt
                   | stop_stmt
                   | return_stmt
                   | call_stmt"""
    p[0] = p[1]


# ---- atribuicao ----

def p_assignment(p):
    "assignment : lvalue '=' expr"
    p[0] = Assignment(target=p[1], expr=p[3])


def p_lvalue_scalar(p):
    "lvalue : ID"
    p[0] = VarTarget(name=p[1])


def p_lvalue_array(p):
    "lvalue : ID '(' arg_list ')'"
    p[0] = ArrayTarget(name=p[1], indices=p[3])


# ---- I/O ----

def p_print_stmt(p):
    "print_stmt : PRINT '*' ',' print_items"
    p[0] = PrintStmt(items=p[4])


def p_print_items_single(p):
    "print_items : print_item"
    p[0] = [p[1]]


def p_print_items_many(p):
    "print_items : print_items ',' print_item"
    p[1].append(p[3])
    p[0] = p[1]


def p_print_item_string(p):
    "print_item : STRING"
    p[0] = StringLiteral(value=p[1])


def p_print_item_expr(p):
    "print_item : expr"
    p[0] = p[1]


def p_read_stmt(p):
    "read_stmt : READ '*' ',' read_items"
    p[0] = ReadStmt(targets=p[4])


def p_read_items_single(p):
    "read_items : lvalue"
    p[0] = [p[1]]


def p_read_items_many(p):
    "read_items : read_items ',' lvalue"
    p[1].append(p[3])
    p[0] = p[1]


# ---- controlo de fluxo simples ----

def p_goto_stmt(p):
    "goto_stmt : GOTO INT_CONST"
    p[0] = GotoStmt(label=p[2])


def p_continue_stmt(p):
    "continue_stmt : CONTINUE"
    p[0] = ContinueStmt()


def p_stop_stmt(p):
    "stop_stmt : STOP"
    p[0] = StopStmt()


def p_return_stmt(p):
    "return_stmt : RETURN"
    p[0] = ReturnStmt()


def p_call_stmt(p):
    "call_stmt : CALL ID '(' opt_arg_list ')'"
    p[0] = CallStmt(name=p[2], args=p[4])


# ---- ciclo DO ----

def p_do_stmt_no_step(p):
    "do_stmt : DO INT_CONST ID '=' expr ',' expr"
    p[0] = DoStmt(
        end_label=p[2], var_name=p[3],
        start=p[5], end=p[7], step=None,
    )


def p_do_stmt_with_step(p):
    "do_stmt : DO INT_CONST ID '=' expr ',' expr ',' expr"
    p[0] = DoStmt(
        end_label=p[2], var_name=p[3],
        start=p[5], end=p[7], step=p[9],
    )


# ---- IF / ELSE / ENDIF ----
#
# Tivemos algumas dificuldades aqui por causa do "ELSE IF" com espaco
# vs "ELSEIF" colado. No standard ambos sao validos. Resolvemos isto
# tendo duas regras separadas para o elseif_branch.

def p_if_stmt(p):
    "if_stmt : IF '(' expr ')' THEN EOL stmt_list if_tail"
    elifs, els = p[8]
    p[0] = IfStmt(
        condition=p[3],
        then_body=p[7],
        elif_branches=elifs,
        else_body=els,
    )


def p_if_tail_endif(p):
    "if_tail : ENDIF EOL"
    p[0] = ([], [])


def p_if_tail_else_only(p):
    "if_tail : ELSE EOL stmt_list ENDIF EOL"
    p[0] = ([], p[3])


def p_if_tail_with_elifs(p):
    "if_tail : elseif_branch_list opt_else_clause ENDIF EOL"
    p[0] = (p[1], p[2])


def p_elseif_branch_list_single(p):
    "elseif_branch_list : elseif_branch"
    p[0] = [p[1]]


def p_elseif_branch_list_many(p):
    "elseif_branch_list : elseif_branch_list elseif_branch"
    p[1].append(p[2])
    p[0] = p[1]


def p_elseif_branch_spaced(p):
    "elseif_branch : ELSE IF '(' expr ')' THEN EOL stmt_list"
    p[0] = ElifBranch(condition=p[4], body=p[8])


def p_elseif_branch_compact(p):
    "elseif_branch : ELSEIF '(' expr ')' THEN EOL stmt_list"
    p[0] = ElifBranch(condition=p[3], body=p[7])


def p_opt_else_clause(p):
    """opt_else_clause : ELSE EOL stmt_list
                       | empty"""
    if len(p) == 4:
        p[0] = p[3]
    else:
        p[0] = []


# ---- expressoes ----

def p_expr_binary(p):
    """expr : expr '+' expr
            | expr '-' expr
            | expr '*' expr
            | expr '/' expr
            | expr LT expr
            | expr LE expr
            | expr GT expr
            | expr GE expr
            | expr EQ expr
            | expr NE expr
            | expr AND expr
            | expr OR expr"""
    # p.slice[2].type da-nos o nome do token (LT, AND, '+', ...)
    p[0] = BinaryOp(op=p.slice[2].type, left=p[1], right=p[3])


def p_expr_not(p):
    "expr : NOT expr"
    p[0] = UnaryOp(op="NOT", operand=p[2])


def p_expr_uplus(p):
    "expr : '+' expr %prec UPLUS"
    p[0] = UnaryOp(op="+", operand=p[2])


def p_expr_uminus(p):
    "expr : '-' expr %prec UMINUS"
    p[0] = UnaryOp(op="-", operand=p[2])


def p_expr_group(p):
    "expr : '(' expr ')'"
    p[0] = p[2]


def p_expr_int(p):
    "expr : INT_CONST"
    p[0] = IntLiteral(value=p[1])


def p_expr_real(p):
    "expr : REAL_CONST"
    p[0] = RealLiteral(value=p[1])


def p_expr_true_false(p):
    """expr : TRUE
            | FALSE"""
    p[0] = LogicalLiteral(value=p[1])


def p_expr_var(p):
    "expr : ID"
    p[0] = VarRef(name=p[1])


def p_expr_call_or_index(p):
    # FOO(X, Y) pode ser chamada de funcao OU acesso a array.
    # Na semantica e que vamos distinguir.
    "expr : ID '(' opt_arg_list ')'"
    p[0] = CallExpr(name=p[1], args=p[3])


def p_opt_arg_list(p):
    """opt_arg_list : arg_list
                    | empty"""
    p[0] = p[1] or []


def p_arg_list_single(p):
    "arg_list : expr"
    p[0] = [p[1]]


def p_arg_list_many(p):
    "arg_list : arg_list ',' expr"
    p[1].append(p[3])
    p[0] = p[1]


def p_empty(p):
    "empty :"
    p[0] = None


def p_error(tok):
    if tok is None:
        raise ParserError("erro de sintaxe: fim de ficheiro inesperado")
    raise ParserError(
        f"erro de sintaxe na linha {tok.lineno}: nao esperava {tok.type} ({tok.value!r})"
    )


# ============================================================
# lexer "linha-a-linha" que injeta LABEL e EOL no meio dos tokens
# ============================================================

class LineLexer:
    """Wrapper a volta do lexer do ply.

    Recebe a lista de SourceLine (ja sem comentarios, em maiusculas,
    label separado) e devolve tokens a yacc um a um. No fim de cada
    linha injeta um EOL; se a linha tinha label, antes do primeiro
    token injeta um LABEL.
    """

    def __init__(self, lines):
        self._lines = iter(lines)
        self._queue = deque()
        self._base = make_lexer()

    @staticmethod
    def _make_token(tp, value, lineno):
        tok = plex.LexToken()
        tok.type = tp
        tok.value = value
        tok.lineno = lineno
        tok.lexpos = 0
        return tok

    def token(self):
        # se a fila esta vazia, vamos buscar a proxima linha
        while not self._queue:
            try:
                line = next(self._lines)
            except StopIteration:
                return None

            # 1) injeta o LABEL se houver
            if line.label is not None:
                self._queue.append(
                    self._make_token("LABEL", line.label, line.lineno)
                )

            # 2) tokeniza o resto do texto da linha
            self._base.lineno = line.lineno
            self._base.input(line.text)
            tok = self._base.token()
            while tok is not None:
                tok.lineno = line.lineno
                self._queue.append(tok)
                tok = self._base.token()

            # 3) marca fim de linha
            self._queue.append(self._make_token("EOL", "\n", line.lineno))

        return self._queue.popleft()


# constroi o parser uma so vez (e caro)
_parser = yacc.yacc(start="program", write_tables=False, debug=False)


def parse(lines):
    return _parser.parse(lexer=LineLexer(lines))
