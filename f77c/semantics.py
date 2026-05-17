# Analisador semantico.
#
# O que esta fase faz:
#   - constroi a tabela de simbolos para o programa principal e
#     para cada subprograma (FUNCTION / SUBROUTINE)
#   - atribui offsets na memoria (global ou local) a cada variavel
#   - verifica tipos das expressoes e propaga-os pela AST
#   - verifica que as labels usadas pelos GOTO e pelos DO existem
#   - faz algumas verificacoes "de bom senso" (variavel do DO nao pode
#     ser alterada dentro do ciclo, step do DO nao pode ser zero, etc)
#
# No fim devolvemos um ProgramInfo com tudo o que o gerador de codigo
# vai precisar para nao ter de fazer estas analises outra vez.

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ast_nodes import (
    ArrayDim, ArrayRef, ArrayTarget, Assignment, BinaryOp,
    CallExpr, CallStmt, ContinueStmt, DoStmt, ElifBranch,
    FunctionDef, GotoStmt, IfStmt, IntLiteral, LogicalLiteral,
    PrintStmt, Program, ReadStmt, RealLiteral, ReturnStmt,
    StopStmt, StringLiteral, SubroutineDef, UnaryOp, VarRef,
    VarTarget, get_label, unwrap,
)
from .errors import SemanticError


# ================================================================
# Estruturas de dados
# ================================================================

@dataclass
class Symbol:
    """Entrada da tabela de simbolos."""
    name: str
    type_name: Optional[str]    # 'INTEGER' | 'REAL' | 'LOGICAL'
    kind: str                   # 'scalar' ou 'array'
    storage: str                # 'global' (main), 'local' (subprog) ou 'param'
    offset: int
    size: int = 1               # n. de celulas (1 para escalar)
    dims: List[ArrayDim] = field(default_factory=list)
    is_param: bool = False
    is_function_result: bool = False


@dataclass
class SubprogramSig:
    """Assinatura de uma FUNCTION ou SUBROUTINE.

    Os param_types so sao preenchidos depois de analisarmos
    as declaracoes do subprograma.
    """
    name: str
    kind: str               # 'function' ou 'subroutine'
    params: List[str]
    return_type: Optional[str] = None
    param_types: List[str] = field(default_factory=list)


@dataclass
class UnitInfo:
    """Informacao acumulada sobre uma unidade compilavel.

    Uma "unidade" e ou o programa principal ou um subprograma.
    """
    name: str
    kind: str                       # 'main' | 'function' | 'subroutine'
    symbols: Dict[str, Symbol]
    labels: Dict[int, object]       # int -> statement com aquela label
    local_cells: int                # quantas celulas locais reservar (PUSHN)
    temp_base: int                  # offset onde comecam os temporarios
    return_type: Optional[str] = None
    param_names: List[str] = field(default_factory=list)
    param_types: List[str] = field(default_factory=list)
    result_symbol: Optional[Symbol] = None
    user_cells: int = 0
    total_cells: int = 0


@dataclass
class ProgramInfo:
    """O que sai desta fase, vai todo direto para o codegen."""
    main: UnitInfo
    subprograms: Dict[str, UnitInfo]
    signatures: Dict[str, SubprogramSig]
    warnings: List[str] = field(default_factory=list)


# ================================================================
# Auxiliar: construtor de unidade
#
# A ideia e ter uma estrutura "em construcao" enquanto analisamos
# a unidade, e no fim chamar .finish() para obter o UnitInfo final.
# ================================================================

class _UnitBuilder:
    def __init__(self, name, kind):
        self.name = name
        self.kind = kind
        self.symbols = {}
        self.labels = {}
        # nos subprogramas o offset 0 e reservado (n. de args na stack
        # ou ponteiro de retorno, conforme a EWVM faz), por isso comecamos em 1
        self.next_user_offset = 0 if kind == "main" else 1
        self.next_temp_offset = self.next_user_offset
        self.return_type = None
        self.param_names = []
        self.param_types = []
        self.result_symbol = None

    def alloc_user(self, size):
        """Reserva 'size' celulas para uma variavel do utilizador."""
        offset = self.next_user_offset
        self.next_user_offset += size
        if self.next_temp_offset < self.next_user_offset:
            self.next_temp_offset = self.next_user_offset
        return offset

    def alloc_temp(self):
        """Reserva uma celula para um temporario interno do compilador."""
        offset = self.next_temp_offset
        self.next_temp_offset += 1
        return offset

    def finish(self):
        if self.kind == "main":
            user_cells = self.next_user_offset
            total_cells = self.next_temp_offset
            local_cells = 0
        else:
            # tira-se o 1 inicial que nao e "nosso"
            user_cells = max(0, self.next_user_offset - 1)
            total_cells = max(0, self.next_temp_offset - 1)
            local_cells = total_cells

        return UnitInfo(
            name=self.name,
            kind=self.kind,
            symbols=self.symbols,
            labels=self.labels,
            local_cells=local_cells,
            temp_base=self.next_user_offset,
            return_type=self.return_type,
            param_names=list(self.param_names),
            param_types=list(self.param_types),
            result_symbol=self.result_symbol,
            user_cells=user_cells,
            total_cells=total_cells,
        )


# ================================================================
# Analisador propriamente dito
# ================================================================

class SemanticAnalyzer:
    def __init__(self, program):
        self.program = program
        self.signatures = {}
        self.units = {}
        self.warnings = []
        self._loop_counter = 0    # para gerar ids unicos para cada DO

    # -----------------------------------------------------------
    # ponto de entrada
    # -----------------------------------------------------------
    def analyze(self):
        # 1) registar as cabeçalhos de todos os subprogramas para que
        #    o main os possa chamar mesmo que sejam definidos depois
        self._register_subprogram_headers()

        # 2) construir tabelas de simbolos
        self.units[self.program.name] = self._build_main_symbols()
        for sub in self.program.subprograms:
            self.units[sub.name] = self._build_subprogram_symbols(sub)

        # 3) percorrer os subprogramas (recolher labels + analisar stmts)
        for sub in self.program.subprograms:
            unit = self.units[sub.name]
            self._collect_labels(sub.statements, unit.labels)
            self._visit_stmts(sub.statements, unit)

        # 4) o mesmo para o main
        main_unit = self.units[self.program.name]
        self._collect_labels(self.program.statements, main_unit.labels)
        self._visit_stmts(self.program.statements, main_unit)

        # 5) "fechar" todas as unidades
        sub_infos = {}
        for name, builder in self.units.items():
            if name != self.program.name:
                sub_infos[name] = builder.finish()
        main_info = self.units[self.program.name].finish()

        # 6) actualizar param_types nas assinaturas (so depois das
        #    declaracoes e que sabemos os tipos)
        for name, info in sub_infos.items():
            self.signatures[name].param_types = list(info.param_types)

        return ProgramInfo(
            main=main_info,
            subprograms=sub_infos,
            signatures=self.signatures,
            warnings=list(self.warnings),
        )

    # -----------------------------------------------------------
    # cabeçalhos dos subprogramas
    # -----------------------------------------------------------
    def _register_subprogram_headers(self):
        for sub in self.program.subprograms:
            if sub.name in self.signatures:
                raise SemanticError(
                    f"subprograma {sub.name!r} declarado mais do que uma vez"
                )
            if isinstance(sub, FunctionDef):
                self.signatures[sub.name] = SubprogramSig(
                    name=sub.name,
                    kind="function",
                    params=list(sub.params),
                    return_type=sub.return_type,
                )
            else:  # SubroutineDef
                self.signatures[sub.name] = SubprogramSig(
                    name=sub.name,
                    kind="subroutine",
                    params=list(sub.params),
                    return_type=None,
                )

    # -----------------------------------------------------------
    # tabelas de simbolos
    # -----------------------------------------------------------
    def _build_main_symbols(self):
        unit = _UnitBuilder(self.program.name, "main")
        for decl in self.program.declarations:
            for item in decl.items:
                self._declare(unit, item.name, decl.type_name, item.dims)
        return unit

    def _build_subprogram_symbols(self, sub):
        kind = "function" if isinstance(sub, FunctionDef) else "subroutine"
        unit = _UnitBuilder(sub.name, kind)
        sig = self.signatures[sub.name]
        unit.param_names = list(sig.params)
        unit.return_type = sig.return_type

        # Nas funcoes, o nome da funcao tambem e uma "variavel" onde se
        # guarda o valor de retorno (ex: CONVRT = VAL)
        if kind == "function":
            result_sym = Symbol(
                name=sub.name,
                type_name=sig.return_type,
                kind="scalar",
                storage="local",
                offset=unit.alloc_user(1),
                size=1,
                is_function_result=True,
            )
            unit.symbols[sub.name] = result_sym
            unit.result_symbol = result_sym

        # os parametros vivem na pilha em offsets negativos relativos ao FP
        # (Frame Pointer). Para uma funcao, ainda existe o slot do valor
        # de retorno entre o ultimo arg e o FP, daí o -1 a mais.
        argc = len(sig.params)
        for i, pname in enumerate(sig.params):
            if pname in unit.symbols:
                raise SemanticError(
                    f"parametro {pname!r} colide com simbolo ja existente em {sub.name!r}"
                )
            if kind == "function":
                offset = -(argc - i + 1)
            else:
                offset = -(argc - i)
            unit.symbols[pname] = Symbol(
                name=pname,
                type_name=None,    # vai ser preenchido pela declaracao
                kind="scalar",
                storage="param",
                offset=offset,
                size=1,
                is_param=True,
            )

        # agora processar as declaracoes locais (e os tipos dos parametros)
        for decl in sub.declarations:
            for item in decl.items:
                existing = unit.symbols.get(item.name)
                if existing is not None and existing.is_param:
                    # declaracao do tipo de um parametro
                    if item.dims:
                        raise SemanticError(
                            f"parametro {item.name!r} nao pode ser array em {sub.name!r}"
                        )
                    if existing.type_name is not None:
                        raise SemanticError(
                            f"parametro {item.name!r} declarado mais do que uma vez em {sub.name!r}"
                        )
                    existing.type_name = decl.type_name
                    continue
                if existing is not None and existing.is_function_result:
                    raise SemanticError(
                        f"o tipo de {item.name!r} ja foi dado no cabeçalho da FUNCTION"
                    )
                self._declare(unit, item.name, decl.type_name, item.dims)

        # garantir que todos os parametros foram tipados
        falta = [p for p in sig.params if unit.symbols[p].type_name is None]
        if falta:
            nomes = ", ".join(repr(n) for n in falta)
            raise SemanticError(
                f"parametros {nomes} de {sub.name!r} nao foram declarados"
            )

        unit.param_types = [unit.symbols[p].type_name for p in sig.params]
        return unit

    def _declare(self, unit, name, type_name, dims):
        if name in unit.symbols:
            raise SemanticError(
                f"variavel {name!r} declarada mais do que uma vez em {unit.name!r}"
            )

        if dims:
            total = 1
            for d in dims:
                if d.extent <= 0:
                    raise SemanticError(
                        f"array {name!r} tem bounds invalidas: ({d.lower}:{d.upper})"
                    )
                total *= d.extent
            kind = "array"
            cells = total
        else:
            kind = "scalar"
            cells = 1

        unit.symbols[name] = Symbol(
            name=name,
            type_name=type_name,
            kind=kind,
            storage="global" if unit.kind == "main" else "local",
            offset=unit.alloc_user(cells),
            size=cells,
            dims=list(dims),
        )

    # -----------------------------------------------------------
    # labels
    # -----------------------------------------------------------
    def _collect_labels(self, stmts, target):
        """Percorre os stmts e mete num dicionario as labels que aparecem."""
        for s in stmts:
            lab = get_label(s)
            if lab is not None:
                if lab in target:
                    raise SemanticError(
                        f"label {lab} declarada mais do que uma vez no mesmo bloco"
                    )
                target[lab] = s

            # tambem precisamos de descer dentro dos IFs
            inner = unwrap(s)
            if isinstance(inner, IfStmt):
                self._collect_labels(inner.then_body, target)
                for br in inner.elif_branches:
                    self._collect_labels(br.body, target)
                self._collect_labels(inner.else_body, target)

    # -----------------------------------------------------------
    # percorrer instrucoes
    # -----------------------------------------------------------
    def _visit_stmts(self, stmts, unit, active_do_vars=None):
        active_do_vars = list(active_do_vars or [])

        # mapear label -> indice no array, para o DO conseguir saber
        # em que posicao esta a sua label de fim
        local_labels = {}
        for i, s in enumerate(stmts):
            lab = get_label(s)
            if lab is not None:
                local_labels[lab] = i

        # DOs "abertos" neste nivel
        open_dos = []   # lista de (var_name, closing_index)

        for idx, stmt in enumerate(stmts):
            current_dos = active_do_vars + [v for v, _ in open_dos]
            inner = unwrap(stmt)

            if isinstance(inner, Assignment):
                inner.target = self._analyze_lvalue(inner.target, unit)
                self._check_not_loop_var(inner.target, current_dos, unit)
                inner.expr = self._analyze_expr(inner.expr, unit)
                self._check_assign_types(
                    self._lvalue_type(inner.target, unit), inner.expr.typ
                )

            elif isinstance(inner, PrintStmt):
                novos = []
                for it in inner.items:
                    if isinstance(it, StringLiteral):
                        novos.append(it)
                    else:
                        novos.append(self._analyze_expr(it, unit))
                inner.items = novos

            elif isinstance(inner, ReadStmt):
                novos = [self._analyze_lvalue(t, unit) for t in inner.targets]
                for t in novos:
                    self._check_not_loop_var(t, current_dos, unit)
                inner.targets = novos

            elif isinstance(inner, GotoStmt):
                if inner.label not in unit.labels:
                    raise SemanticError(
                        f"GOTO refere a label {inner.label} que nao existe em {unit.name!r}"
                    )

            elif isinstance(inner, ContinueStmt):
                pass

            elif isinstance(inner, StopStmt):
                pass

            elif isinstance(inner, ReturnStmt):
                if unit.kind == "main":
                    raise SemanticError(
                        "RETURN so e valido dentro de FUNCTION ou SUBROUTINE"
                    )

            elif isinstance(inner, CallStmt):
                self._analyze_call_stmt(inner, unit)

            elif isinstance(inner, IfStmt):
                inner.condition = self._analyze_expr(inner.condition, unit)
                if inner.condition.typ != "LOGICAL":
                    raise SemanticError("condicao do IF tem de ser LOGICAL")
                self._visit_stmts(inner.then_body, unit, current_dos)
                for br in inner.elif_branches:
                    br.condition = self._analyze_expr(br.condition, unit)
                    if br.condition.typ != "LOGICAL":
                        raise SemanticError("condicao do ELSE IF tem de ser LOGICAL")
                    self._visit_stmts(br.body, unit, current_dos)
                self._visit_stmts(inner.else_body, unit, current_dos)

            elif isinstance(inner, DoStmt):
                # nao podemos abrir um DO sobre uma variavel que ja seja
                # variavel de controlo de outro DO ativo
                if inner.var_name in current_dos:
                    raise SemanticError(
                        f"variavel de controlo do DO {inner.var_name!r} ja esta em uso"
                    )
                self._analyze_do(inner, idx, local_labels, unit)
                open_dos.append((inner.var_name, inner.closing_index))

            else:
                raise SemanticError(
                    f"tipo de instrucao nao suportado: {type(inner).__name__}"
                )

            # fechar DOs cujo "CONTINUE" e esta linha
            open_dos = [(v, c) for v, c in open_dos if c != idx]

    # -----------------------------------------------------------
    # DO loops
    # -----------------------------------------------------------
    def _analyze_do(self, stmt, idx, local_labels, unit):
        sym = unit.symbols.get(stmt.var_name)
        if sym is None:
            raise SemanticError(
                f"variavel do DO {stmt.var_name!r} nao foi declarada em {unit.name!r}"
            )
        if sym.kind != "scalar" or sym.type_name != "INTEGER":
            raise SemanticError("a variavel de controlo do DO tem de ser um INTEGER escalar")

        stmt.start = self._analyze_expr(stmt.start, unit)
        stmt.end = self._analyze_expr(stmt.end, unit)
        if stmt.step is not None:
            stmt.step = self._analyze_expr(stmt.step, unit)

        # todos os limites tem de ser INTEGER
        if stmt.start.typ != "INTEGER" or stmt.end.typ != "INTEGER":
            raise SemanticError("os limites do DO tem de ser INTEGER")
        if stmt.step is not None and stmt.step.typ != "INTEGER":
            raise SemanticError("o step do DO tem de ser INTEGER")

        # step = 0 e um ciclo infinito garantido. Detetamos o caso obvio.
        if isinstance(stmt.step, IntLiteral) and stmt.step.value == 0:
            raise SemanticError("o step do DO nao pode ser zero")

        if stmt.end_label not in local_labels:
            raise SemanticError(
                f"DO {stmt.var_name!r} refere label {stmt.end_label} que nao existe neste bloco"
            )

        closing = local_labels[stmt.end_label]
        if closing <= idx:
            raise SemanticError(
                f"a label {stmt.end_label} do DO tem de aparecer depois do DO"
            )

        stmt.closing_index = closing
        stmt.end_temp = unit.alloc_temp()
        stmt.step_temp = unit.alloc_temp()
        stmt.loop_id = self._loop_counter
        self._loop_counter += 1

    # -----------------------------------------------------------
    # CALL
    # -----------------------------------------------------------
    def _analyze_call_stmt(self, stmt, unit):
        stmt.args = [self._analyze_expr(a, unit) for a in stmt.args]
        sig = self.signatures.get(stmt.name)
        if sig is None:
            raise SemanticError(f"CALL para subrotina desconhecida {stmt.name!r}")
        if sig.kind != "subroutine":
            raise SemanticError(
                f"CALL precisa de uma SUBROUTINE; {stmt.name!r} e uma FUNCTION"
            )
        self._check_call_args(stmt.name, stmt.args, sig)

    # -----------------------------------------------------------
    # lvalues (lado esquerdo de uma atribuicao)
    # -----------------------------------------------------------
    def _analyze_lvalue(self, target, unit):
        if isinstance(target, VarTarget):
            sym = unit.symbols.get(target.name)
            if sym is None:
                raise SemanticError(
                    f"variavel {target.name!r} nao foi declarada em {unit.name!r}"
                )
            if sym.kind != "scalar":
                raise SemanticError(
                    f"{target.name!r} e um array, faltam os indices"
                )
            return target

        if isinstance(target, ArrayTarget):
            sym = unit.symbols.get(target.name)
            if sym is None:
                raise SemanticError(
                    f"variavel {target.name!r} nao foi declarada em {unit.name!r}"
                )
            if sym.kind != "array":
                raise SemanticError(f"{target.name!r} nao e um array")
            if len(target.indices) != len(sym.dims):
                raise SemanticError(
                    f"array {target.name!r} esperava {len(sym.dims)} indices, recebeu {len(target.indices)}"
                )
            novos = []
            for idx_expr in target.indices:
                e = self._analyze_expr(idx_expr, unit)
                if e.typ != "INTEGER":
                    raise SemanticError(
                        f"indices do array {target.name!r} tem de ser INTEGER"
                    )
                novos.append(e)
            target.indices = novos
            return target

        raise SemanticError(f"lvalue nao suportado: {type(target).__name__}")

    def _lvalue_type(self, target, unit):
        return unit.symbols[target.name].type_name

    # -----------------------------------------------------------
    # expressoes
    # -----------------------------------------------------------
    def _analyze_expr(self, expr, unit):
        # literais
        if isinstance(expr, IntLiteral):
            expr.typ = "INTEGER"
            return expr
        if isinstance(expr, RealLiteral):
            expr.typ = "REAL"
            return expr
        if isinstance(expr, LogicalLiteral):
            expr.typ = "LOGICAL"
            return expr

        # variavel escalar
        if isinstance(expr, VarRef):
            sym = unit.symbols.get(expr.name)
            if sym is None:
                raise SemanticError(
                    f"variavel {expr.name!r} nao foi declarada em {unit.name!r}"
                )
            if sym.kind != "scalar":
                raise SemanticError(
                    f"{expr.name!r} e um array, faltam os indices"
                )
            expr.typ = sym.type_name
            return expr

        # acesso a array (vindo ja como ArrayRef)
        if isinstance(expr, ArrayRef):
            sym = unit.symbols.get(expr.name)
            if sym is None or sym.kind != "array":
                raise SemanticError(f"array desconhecido {expr.name!r}")
            if len(expr.indices) != len(sym.dims):
                raise SemanticError(
                    f"array {expr.name!r} esperava {len(sym.dims)} indices, recebeu {len(expr.indices)}"
                )
            expr.indices = [self._analyze_expr(i, unit) for i in expr.indices]
            for i in expr.indices:
                if i.typ != "INTEGER":
                    raise SemanticError(
                        f"indices do array {expr.name!r} tem de ser INTEGER"
                    )
            expr.typ = sym.type_name
            return expr

        # FOO(...) - pode ser array OU chamada de funcao
        if isinstance(expr, CallExpr):
            expr.args = [self._analyze_expr(a, unit) for a in expr.args]

            # 1) verificar se e um array
            sym = unit.symbols.get(expr.name)
            if sym is not None and sym.kind == "array":
                if len(expr.args) != len(sym.dims):
                    raise SemanticError(
                        f"array {expr.name!r} esperava {len(sym.dims)} indices, recebeu {len(expr.args)}"
                    )
                for a in expr.args:
                    if a.typ != "INTEGER":
                        raise SemanticError(
                            f"indices do array {expr.name!r} tem de ser INTEGER"
                        )
                # converter para ArrayRef
                ar = ArrayRef(name=expr.name, indices=expr.args)
                ar.typ = sym.type_name
                return ar

            # 2) builtins (MOD, ABS)
            if expr.name == "MOD":
                if len(expr.args) != 2:
                    raise SemanticError("MOD precisa de 2 argumentos")
                if expr.args[0].typ != "INTEGER" or expr.args[1].typ != "INTEGER":
                    raise SemanticError("os argumentos de MOD tem de ser INTEGER")
                expr.typ = "INTEGER"
                return expr

            if expr.name == "ABS":
                if len(expr.args) != 1:
                    raise SemanticError("ABS precisa de 1 argumento")
                if expr.args[0].typ not in ("INTEGER", "REAL"):
                    raise SemanticError("o argumento de ABS tem de ser INTEGER ou REAL")
                expr.typ = expr.args[0].typ
                expr.cleanup_temp = unit.alloc_temp()
                return expr

            # 3) chamada a uma funcao do utilizador
            sig = self.signatures.get(expr.name)
            if sig is None:
                if sym is not None:
                    raise SemanticError(
                        f"{expr.name!r} e um escalar; nao podes invoca-lo nem indexa-lo"
                    )
                raise SemanticError(f"funcao desconhecida {expr.name!r}")
            if sig.kind != "function":
                raise SemanticError(
                    f"{expr.name!r} e uma SUBROUTINE; so podes usa-la com CALL"
                )
            self._check_call_args(expr.name, expr.args, sig)
            expr.typ = sig.return_type
            expr.cleanup_temp = unit.alloc_temp()
            return expr

        # operadores unarios
        if isinstance(expr, UnaryOp):
            expr.operand = self._analyze_expr(expr.operand, unit)
            if expr.op in ("+", "-"):
                if expr.operand.typ not in ("INTEGER", "REAL"):
                    raise SemanticError(f"unario {expr.op} precisa de um numero")
                expr.typ = expr.operand.typ
                return expr
            if expr.op == "NOT":
                if expr.operand.typ != "LOGICAL":
                    raise SemanticError(".NOT. precisa de um LOGICAL")
                expr.typ = "LOGICAL"
                return expr
            raise SemanticError(f"operador unario desconhecido: {expr.op!r}")

        # operadores binarios
        if isinstance(expr, BinaryOp):
            expr.left = self._analyze_expr(expr.left, unit)
            expr.right = self._analyze_expr(expr.right, unit)
            return self._type_binary(expr)

        raise SemanticError(f"expressao nao suportada: {type(expr).__name__}")

    def _type_binary(self, expr):
        lt, rt, op = expr.left.typ, expr.right.typ, expr.op

        # aritmetica
        if op in ("+", "-", "*", "/"):
            self._require_num(lt, op)
            self._require_num(rt, op)
            # se algum lado for REAL, o resultado e REAL
            expr.typ = "REAL" if "REAL" in (lt, rt) else "INTEGER"
            return expr

        # logica
        if op in ("AND", "OR"):
            if lt != "LOGICAL" or rt != "LOGICAL":
                raise SemanticError(f"{op} precisa de dois LOGICAL")
            expr.typ = "LOGICAL"
            return expr

        # comparacoes numericas (so faz sentido para numeros)
        if op in ("LT", "LE", "GT", "GE"):
            self._require_num(lt, op)
            self._require_num(rt, op)
            expr.typ = "LOGICAL"
            return expr

        # igualdade: aceita mistura int/real, ou mesmos tipos
        if op in ("EQ", "NE"):
            if lt == rt or set([lt, rt]) == {"INTEGER", "REAL"}:
                expr.typ = "LOGICAL"
                return expr
            raise SemanticError(
                f"{op} com operandos incompativeis: {lt} e {rt}"
            )

        raise SemanticError(f"operador binario desconhecido: {op!r}")

    # -----------------------------------------------------------
    # helpers
    # -----------------------------------------------------------
    @staticmethod
    def _require_num(typ, op):
        if typ not in ("INTEGER", "REAL"):
            raise SemanticError(f"{op} precisa de operandos numericos, recebeu {typ}")

    @staticmethod
    def _check_assign_types(dst, src):
        if src is None:
            raise SemanticError("erro interno: expressao sem tipo inferido")
        if dst == src:
            return
        # aceita-se INTEGER <-> REAL (com conversao automatica no codegen)
        if set([dst, src]) == {"INTEGER", "REAL"}:
            return
        raise SemanticError(f"nao se pode atribuir {src} a uma variavel {dst}")

    def _check_call_args(self, name, args, sig):
        if len(args) != len(sig.params):
            raise SemanticError(
                f"{name!r} esperava {len(sig.params)} argumentos, recebeu {len(args)}"
            )
        if not sig.param_types:
            # ainda nao sabemos os tipos -- vai ser verificado quando se
            # analisar o subprograma
            return
        for i, (a, want) in enumerate(zip(args, sig.param_types), start=1):
            if a.typ == want:
                continue
            if set([a.typ, want]) == {"INTEGER", "REAL"}:
                continue
            raise SemanticError(
                f"argumento {i} de {name!r} e {a.typ}, esperava-se {want}"
            )

    def _check_not_loop_var(self, target, active_do_vars, unit):
        if isinstance(target, VarTarget):
            if target.name in active_do_vars:
                raise SemanticError(
                    f"a variavel de controlo do DO {target.name!r} nao pode ser modificada dentro do ciclo"
                )


def analyze(program):
    return SemanticAnalyzer(program).analyze()
