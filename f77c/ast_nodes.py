# Nos da AST produzida pelo parser.
#
# Optamos por usar dataclasses porque assim ja temos __init__ e __repr__
# de borla, e e muito mais comodo do que escrever as classes a mao.

from dataclasses import dataclass, field
from typing import List, Optional


# ---------- declaracoes ----------

@dataclass
class ArrayDim:
    lower: int
    upper: int

    @property
    def extent(self):
        return self.upper - self.lower + 1


@dataclass
class DeclItem:
    name: str
    dims: List[ArrayDim] = field(default_factory=list)


@dataclass
class Declaration:
    type_name: str  # 'INTEGER' | 'REAL' | 'LOGICAL'
    items: List[DeclItem]


# ---------- expressoes ----------
# Todas as expressoes tem um campo 'typ' que e preenchido pelo
# analisador semantico (fica None ate la).

class Expr:
    typ = None


@dataclass
class IntLiteral(Expr):
    value: int
    typ: Optional[str] = None


@dataclass
class RealLiteral(Expr):
    value: float
    typ: Optional[str] = None


@dataclass
class LogicalLiteral(Expr):
    value: bool
    typ: Optional[str] = None


@dataclass
class StringLiteral:
    # so aparece em PRINT, nao tem 'typ'
    value: str


@dataclass
class VarRef(Expr):
    name: str
    typ: Optional[str] = None


@dataclass
class ArrayRef(Expr):
    name: str
    indices: List[Expr]
    typ: Optional[str] = None


@dataclass
class CallExpr(Expr):
    # Pode ser uma chamada a funcao OU um acesso a array
    # (o parser nao sabe distinguir, so a semantica e que sabe).
    name: str
    args: List[Expr]
    typ: Optional[str] = None
    cleanup_temp: Optional[int] = None  # slot para guardar resultado


@dataclass
class UnaryOp(Expr):
    op: str
    operand: Expr
    typ: Optional[str] = None


@dataclass
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr
    typ: Optional[str] = None


# ---------- alvos de atribuicao ----------

class Target:
    pass


@dataclass
class VarTarget(Target):
    name: str


@dataclass
class ArrayTarget(Target):
    name: str
    indices: List[Expr]


# ---------- statements ----------

@dataclass
class Assignment:
    target: Target
    expr: Expr


@dataclass
class PrintStmt:
    items: list  # mix de StringLiteral e Expr


@dataclass
class ReadStmt:
    targets: List[Target]


@dataclass
class GotoStmt:
    label: int


@dataclass
class ContinueStmt:
    pass


@dataclass
class StopStmt:
    pass


@dataclass
class ReturnStmt:
    pass


@dataclass
class CallStmt:
    name: str
    args: List[Expr]


@dataclass
class DoStmt:
    end_label: int
    var_name: str
    start: Expr
    end: Expr
    step: Optional[Expr] = None
    # estes campos sao preenchidos pela semantica:
    closing_index: Optional[int] = None
    end_temp: Optional[int] = None
    step_temp: Optional[int] = None
    loop_id: Optional[int] = None


@dataclass
class ElifBranch:
    condition: Expr
    body: list


@dataclass
class IfStmt:
    condition: Expr
    then_body: list
    elif_branches: List[ElifBranch] = field(default_factory=list)
    else_body: list = field(default_factory=list)


@dataclass
class Labeled:
    # Wrapper para statements que tem label (ex: "10 CONTINUE")
    label: int
    stmt: object


# ---------- subprogramas e programa principal ----------

@dataclass
class FunctionDef:
    name: str
    return_type: str
    params: List[str]
    declarations: List[Declaration]
    statements: list


@dataclass
class SubroutineDef:
    name: str
    params: List[str]
    declarations: List[Declaration]
    statements: list


@dataclass
class Program:
    name: str
    declarations: List[Declaration]
    statements: list
    subprograms: list = field(default_factory=list)


# ---------- utilitarios para lidar com Labeled ----------

def unwrap(stmt):
    """Se for Labeled, devolve o stmt interno; caso contrario, devolve o proprio."""
    if isinstance(stmt, Labeled):
        return stmt.stmt
    return stmt


def get_label(stmt):
    """Devolve a label (int) se o stmt tiver uma, ou None."""
    if isinstance(stmt, Labeled):
        return stmt.label
    return None
