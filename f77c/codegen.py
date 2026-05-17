# Geracao de codigo para a maquina virtual EWVM.
#
# Estrategia: percorrer a AST e emitir instrucoes uma a uma para uma
# lista de strings. No fim juntamos tudo com '\n'.
#
# Memoria:
#   - as variaveis do main vao todas para a area global (PUSHG/STOREG)
#   - as variaveis e parametros dos subprogramas vao para a stack local
#     (PUSHL/STOREL), com offsets calculados na fase semantica
#
# Sobre os labels que aparecem no codigo VM:
#   - labels do Fortran (10, 20, ...) viram SRC_<unit>_<n>
#   - labels internos (IF, DO, etc) sao gerados com fresh()

from .ast_nodes import (
    ArrayRef, ArrayTarget, Assignment, BinaryOp, CallExpr, CallStmt,
    ContinueStmt, DoStmt, FunctionDef, GotoStmt, IfStmt, IntLiteral,
    LogicalLiteral, PrintStmt, Program, ReadStmt, RealLiteral,
    ReturnStmt, StopStmt, StringLiteral, SubroutineDef, UnaryOp,
    VarRef, VarTarget, get_label, unwrap,
)
from .errors import SemanticError


class CodeGenerator:
    def __init__(self, info):
        self.info = info
        self.lines = []          # codigo gerado
        self._fresh_id = 0       # contador para labels frescos
        self.cur_unit = None     # UnitInfo da unidade actualmente a gerar

    # -----------------------------------------------------------
    # helpers
    # -----------------------------------------------------------
    def emit(self, line):
        self.lines.append(line)

    def fresh(self, prefix):
        self._fresh_id += 1
        unit_name = self.cur_unit.name.lower() if self.cur_unit is not None else "g"
        return f"{prefix.lower()}{unit_name}{self._fresh_id}"

    def unit_label(self, name):
        return f"unit{name.lower()}"

    def src_label(self, label):
        return f"l{self.cur_unit.name.lower()}{label}"

    # -----------------------------------------------------------
    # entrada
    # -----------------------------------------------------------
    def generate(self, program):
        # programa principal
        if self.info.main.total_cells > 0:
            self.emit(f"PUSHN {self.info.main.total_cells}")
        self.emit("START")
        self.cur_unit = self.info.main
        self._emit_stmts(program.statements)
        self.emit("STOP")

        # subprogramas
        for sub in program.subprograms:
            self._emit_subprogram(sub)

        return "\n".join(self.lines) + "\n"

    def _emit_subprogram(self, sub):
        unit = self.info.subprograms[sub.name]
        self.cur_unit = unit
        self.emit(f"{self.unit_label(sub.name)}:")
        if unit.local_cells > 0:
            self.emit(f"PUSHN {unit.local_cells}")
        self._emit_stmts(sub.statements)

        # se nao houver RETURN explicito no fim, geramos um
        if not self._ends_with_return(sub.statements):
            if unit.kind == "function":
                self._emit_function_return()
            else:
                self.emit("RETURN")

    @staticmethod
    def _ends_with_return(stmts):
        if not stmts:
            return False
        return isinstance(unwrap(stmts[-1]), ReturnStmt)

    # -----------------------------------------------------------
    # lista de instrucoes
    # -----------------------------------------------------------
    def _emit_stmts(self, stmts):
        # primeiro identificar onde acabam os ciclos DO neste nivel
        do_closers = {}     # indice -> lista de DOs que fecham aqui
        for s in stmts:
            inner = unwrap(s)
            if isinstance(inner, DoStmt) and inner.closing_index is not None:
                do_closers.setdefault(inner.closing_index, []).append(inner)

        for idx, stmt in enumerate(stmts):
            # se tem label, emitir o label fonte
            lab = get_label(stmt)
            if lab is not None:
                self.emit(f"{self.src_label(lab)}:")

            inner = unwrap(stmt)
            self._emit_one(inner)

            # se algum DO fechava aqui, emitir o codigo de fim de ciclo
            if idx in do_closers:
                # podem fechar varios DOs na mesma linha; o mais "interior"
                # fecha primeiro
                for do_stmt in reversed(do_closers[idx]):
                    self._emit_do_close(do_stmt)

    def _emit_one(self, stmt):
        if isinstance(stmt, Assignment):
            self._emit_assignment(stmt)
        elif isinstance(stmt, PrintStmt):
            self._emit_print(stmt)
        elif isinstance(stmt, ReadStmt):
            self._emit_read(stmt)
        elif isinstance(stmt, GotoStmt):
            self.emit(f"JUMP {self.src_label(stmt.label)}")
        elif isinstance(stmt, ContinueStmt):
            # CONTINUE serve so para ter algo onde por o label;
            # nao precisa de instrucao real, mas pomos NOP para
            # ficar visivel no .vm
            self.emit("NOP")
        elif isinstance(stmt, StopStmt):
            self.emit("STOP")
        elif isinstance(stmt, ReturnStmt):
            if self.cur_unit.kind == "function":
                self._emit_function_return()
            else:
                self.emit("RETURN")
        elif isinstance(stmt, CallStmt):
            self._emit_call_stmt(stmt)
        elif isinstance(stmt, IfStmt):
            self._emit_if(stmt)
        elif isinstance(stmt, DoStmt):
            self._emit_do_start(stmt)
        else:
            raise SemanticError(
                f"codegen: instrucao desconhecida: {type(stmt).__name__}"
            )

    # -----------------------------------------------------------
    # atribuicao
    # -----------------------------------------------------------
    def _emit_assignment(self, stmt):
        if isinstance(stmt.target, VarTarget):
            sym = self._sym(stmt.target.name)
            self._emit_expr_as(stmt.expr, sym.type_name)
            self._emit_store(sym)
            return

        if isinstance(stmt.target, ArrayTarget):
            sym = self._sym(stmt.target.name)
            # STOREN espera: <base> <indice> <valor>
            self._emit_array_addr(stmt.target.indices, sym)
            self._emit_expr_as(stmt.expr, sym.type_name)
            self.emit("STOREN")
            return

        raise SemanticError(f"alvo de atribuicao desconhecido: {type(stmt.target).__name__}")

    # -----------------------------------------------------------
    # I/O
    # -----------------------------------------------------------
    def _emit_print(self, stmt):
        # O Fortran 77 com PRINT *, ... separa os items por um espaço
        # no output. Nao quisemos por espacos a mais nem nada de mais
        # sofisticado -- so um espaço entre items.
        for i, item in enumerate(stmt.items):
            if i > 0:
                self.emit('PUSHS " "')
                self.emit("WRITES")

            if isinstance(item, StringLiteral):
                self.emit(f'PUSHS "{self._escape_vm(item.value)}"')
                self.emit("WRITES")
            else:
                self._emit_expr(item)
                if item.typ == "REAL":
                    self.emit("WRITEF")
                else:
                    # INTEGER e LOGICAL (este ultimo vai sair como 0/1)
                    self.emit("WRITEI")
        self.emit("WRITELN")

    def _emit_read(self, stmt):
        for t in stmt.targets:
            if isinstance(t, VarTarget):
                sym = self._sym(t.name)
                self.emit("READ")
                self._emit_read_cast(sym.type_name)
                self._emit_store(sym)
            elif isinstance(t, ArrayTarget):
                sym = self._sym(t.name)
                self._emit_array_addr(t.indices, sym)
                self.emit("READ")
                self._emit_read_cast(sym.type_name)
                self.emit("STOREN")
            else:
                raise SemanticError(
                    f"alvo de READ desconhecido: {type(t).__name__}"
                )

    @staticmethod
    def _read_cast_instr(typ):
        return "ATOF" if typ == "REAL" else "ATOI"

    def _emit_read_cast(self, typ):
        self.emit(self._read_cast_instr(typ))

    # -----------------------------------------------------------
    # CALL (chamada de subrotina como instrucao)
    # -----------------------------------------------------------
    def _emit_call_stmt(self, stmt):
        sig = self.info.signatures[stmt.name]
        # empilhar argumentos (com conversao se preciso)
        for a, want in zip(stmt.args, sig.param_types):
            self._emit_expr_as(a, want)
        self.emit(f"PUSHA {self.unit_label(stmt.name)}")
        self.emit("CALL")
        # limpar args da stack
        if stmt.args:
            self.emit(f"POP {len(stmt.args)}")

    # -----------------------------------------------------------
    # IF / ELSE
    # -----------------------------------------------------------
    def _emit_if(self, stmt):
        # Modelo:
        #   <cond1>
        #   JZ next1
        #     <then>
        #     JUMP end
        #   next1:
        #   <cond2>
        #   JZ next2
        #     <elif body>
        #     JUMP end
        #   next2:
        #     <else body>
        #   end:
        end = self.fresh("ENDIF")
        nxt = self.fresh("ELSE")

        self._emit_expr_as(stmt.condition, "LOGICAL")
        self.emit(f"JZ {nxt}")
        self._emit_stmts(stmt.then_body)
        self.emit(f"JUMP {end}")
        self.emit(f"{nxt}:")

        for br in stmt.elif_branches:
            fail = self.fresh("ELIF")
            self._emit_expr_as(br.condition, "LOGICAL")
            self.emit(f"JZ {fail}")
            self._emit_stmts(br.body)
            self.emit(f"JUMP {end}")
            self.emit(f"{fail}:")

        self._emit_stmts(stmt.else_body)
        self.emit(f"{end}:")

    # -----------------------------------------------------------
    # DO loops
    #
    # O codigo gerado tem 3 partes:
    #   1) inicio: inicializa a var, guarda end e step nos temporarios
    #   2) corpo: o corpo do ciclo
    #   3) fim: incrementa, testa, e ou salta para o corpo ou sai
    #
    # Como o step pode ser positivo ou negativo, o teste tem 2 ramos.
    # -----------------------------------------------------------
    def _emit_do_start(self, stmt):
        sym = self._sym(stmt.var_name)

        body = self._lbl_do(stmt, "BODY")
        test = self._lbl_do(stmt, "TEST")

        # var = start
        self._emit_expr_as(stmt.start, "INTEGER")
        self._emit_store(sym)

        # end_temp = end
        self._emit_expr_as(stmt.end, "INTEGER")
        self._emit_store_off(stmt.end_temp)

        # step_temp = step (default = 1)
        if stmt.step is None:
            self.emit("PUSHI 1")
        else:
            self._emit_expr_as(stmt.step, "INTEGER")
        self._emit_store_off(stmt.step_temp)

        self.emit(f"JUMP {test}")
        self.emit(f"{body}:")

    def _emit_do_close(self, stmt):
        sym = self._sym(stmt.var_name)
        body = self._lbl_do(stmt, "BODY")
        test = self._lbl_do(stmt, "TEST")
        neg = self._lbl_do(stmt, "NEG")
        end = self._lbl_do(stmt, "END")

        # var = var + step
        self._emit_load(sym)
        self._emit_load_off(stmt.step_temp)
        self.emit("ADD")
        self._emit_store(sym)

        # teste: se step >= 0 -> var <= end?  senao -> var >= end?
        self.emit(f"{test}:")
        self._emit_load_off(stmt.step_temp)
        self.emit("PUSHI 0")
        self.emit("SUPEQ")
        self.emit(f"JZ {neg}")

        # ramo step positivo
        self._emit_load(sym)
        self._emit_load_off(stmt.end_temp)
        self.emit("INFEQ")
        self.emit(f"JZ {end}")
        self.emit(f"JUMP {body}")

        # ramo step negativo
        self.emit(f"{neg}:")
        self._emit_load(sym)
        self._emit_load_off(stmt.end_temp)
        self.emit("SUPEQ")
        self.emit(f"JZ {end}")
        self.emit(f"JUMP {body}")

        self.emit(f"{end}:")

    def _lbl_do(self, stmt, kind):
        return f"do{kind.lower()}{self.cur_unit.name.lower()}{stmt.loop_id}"

    # -----------------------------------------------------------
    # FUNCTION return
    # -----------------------------------------------------------
    def _emit_function_return(self):
        # nas funcoes, o valor de retorno fica no slot -1 da stack frame
        # (logo abaixo dos parametros). Convencao da EWVM.
        result = self.cur_unit.result_symbol
        if result is None:
            raise SemanticError("erro interno: funcao sem simbolo de retorno")
        self._emit_load(result)
        self.emit("STOREL -1")
        self.emit("RETURN")

    # -----------------------------------------------------------
    # expressoes
    # -----------------------------------------------------------
    def _emit_expr_as(self, expr, want_type):
        """Avalia 'expr' e converte o valor no topo da stack para 'want_type'."""
        self._emit_expr(expr)
        if expr.typ == want_type:
            return
        # conversoes numericas
        if expr.typ == "INTEGER" and want_type == "REAL":
            self.emit("ITOF")
            return
        if expr.typ == "REAL" and want_type == "INTEGER":
            self.emit("FTOI")
            return
        # ja era LOGICAL e querem LOGICAL: ok
        if expr.typ == "LOGICAL" and want_type == "LOGICAL":
            return
        raise SemanticError(
            f"nao se sabe converter {expr.typ} para {want_type}"
        )

    def _emit_expr(self, expr):
        if isinstance(expr, IntLiteral):
            self.emit(f"PUSHI {expr.value}")
            return
        if isinstance(expr, RealLiteral):
            self.emit(f"PUSHF {self._fmt_real(expr.value)}")
            return
        if isinstance(expr, LogicalLiteral):
            # LOGICAL representado como inteiro: 0 = falso, 1 = verdadeiro
            self.emit("PUSHI 1" if expr.value else "PUSHI 0")
            return
        if isinstance(expr, VarRef):
            self._emit_load(self._sym(expr.name))
            return
        if isinstance(expr, ArrayRef):
            sym = self._sym(expr.name)
            self._emit_array_addr(expr.indices, sym)
            self.emit("LOADN")
            return
        if isinstance(expr, CallExpr):
            # builtins primeiro
            if expr.name == "MOD":
                self._emit_expr_as(expr.args[0], "INTEGER")
                self._emit_expr_as(expr.args[1], "INTEGER")
                self.emit("MOD")
                return
            if expr.name == "ABS":
                self._emit_abs(expr)
                return
            # chamada a funcao do utilizador
            self._emit_function_call(expr)
            return
        if isinstance(expr, UnaryOp):
            self._emit_unary(expr)
            return
        if isinstance(expr, BinaryOp):
            self._emit_binary(expr)
            return

        raise SemanticError(
            f"codegen: expressao desconhecida: {type(expr).__name__}"
        )

    def _emit_unary(self, expr):
        if expr.op == "+":
            # unario + nao faz nada
            self._emit_expr(expr.operand)
            return
        if expr.op == "-":
            if expr.typ == "REAL":
                self.emit("PUSHF 0.0")
                self._emit_expr_as(expr.operand, "REAL")
                self.emit("FSUB")
            else:
                self.emit("PUSHI 0")
                self._emit_expr_as(expr.operand, "INTEGER")
                self.emit("SUB")
            return
        if expr.op == "NOT":
            self._emit_expr_as(expr.operand, "LOGICAL")
            self.emit("NOT")
            return
        raise SemanticError(f"operador unario desconhecido: {expr.op!r}")

    def _emit_binary(self, expr):
        op = expr.op
        l, r = expr.left, expr.right

        # aritmeticos
        if op in ("+", "-", "*", "/"):
            if expr.typ == "REAL":
                self._emit_expr_as(l, "REAL")
                self._emit_expr_as(r, "REAL")
                self.emit({"+": "FADD", "-": "FSUB", "*": "FMUL", "/": "FDIV"}[op])
            else:
                self._emit_expr_as(l, "INTEGER")
                self._emit_expr_as(r, "INTEGER")
                self.emit({"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}[op])
            return

        # logicos
        if op in ("AND", "OR"):
            self._emit_expr_as(l, "LOGICAL")
            self._emit_expr_as(r, "LOGICAL")
            self.emit(op)   # AND / OR existem na EWVM
            return

        # comparacoes (excepto =/= que tem regra propria)
        if op in ("LT", "LE", "GT", "GE"):
            if l.typ == "REAL" or r.typ == "REAL":
                self._emit_expr_as(l, "REAL")
                self._emit_expr_as(r, "REAL")
                instr = {"LT": "FINF", "LE": "FINFEQ", "GT": "FSUP", "GE": "FSUPEQ"}[op]
            else:
                self._emit_expr_as(l, "INTEGER")
                self._emit_expr_as(r, "INTEGER")
                instr = {"LT": "INF", "LE": "INFEQ", "GT": "SUP", "GE": "SUPEQ"}[op]
            self.emit(instr)
            return

        # igualdade (com .NE. = nao igual)
        if op in ("EQ", "NE"):
            if l.typ == "REAL" or r.typ == "REAL":
                self._emit_expr_as(l, "REAL")
                self._emit_expr_as(r, "REAL")
            elif l.typ == "INTEGER" or r.typ == "INTEGER":
                self._emit_expr_as(l, "INTEGER")
                self._emit_expr_as(r, "INTEGER")
            else:
                # ambos LOGICAL
                self._emit_expr_as(l, "LOGICAL")
                self._emit_expr_as(r, "LOGICAL")
            self.emit("EQUAL")
            if op == "NE":
                self.emit("NOT")
            return

        raise SemanticError(f"operador binario desconhecido: {op!r}")

    # -----------------------------------------------------------
    # ABS: abs(x) = if x >= 0 then x else -x
    # -----------------------------------------------------------
    def _emit_abs(self, expr):
        neg = self.fresh("ABS_NEG")
        done = self.fresh("ABS_DONE")
        is_real = expr.typ == "REAL"
        slot = expr.cleanup_temp

        # avaliar e guardar o valor (precisamos dele duas vezes)
        self._emit_expr_as(expr.args[0], expr.typ)
        self._emit_store_off(slot)

        # testar se e >= 0
        self._emit_load_off(slot)
        if is_real:
            self.emit("PUSHF 0.0")
            self.emit("FSUPEQ")
        else:
            self.emit("PUSHI 0")
            self.emit("SUPEQ")
        self.emit(f"JZ {neg}")

        # >= 0: usar o valor original
        self._emit_load_off(slot)
        self.emit(f"JUMP {done}")

        # < 0: negar
        self.emit(f"{neg}:")
        if is_real:
            self.emit("PUSHF 0.0")
            self._emit_load_off(slot)
            self.emit("FSUB")
        else:
            self.emit("PUSHI 0")
            self._emit_load_off(slot)
            self.emit("SUB")

        self.emit(f"{done}:")

    # -----------------------------------------------------------
    # Chamada a funcao do utilizador
    # -----------------------------------------------------------
    def _emit_function_call(self, expr):
        sig = self.info.signatures.get(expr.name)
        if sig is None or sig.kind != "function":
            raise SemanticError(f"codegen: chamada a funcao desconhecida {expr.name!r}")

        # argumentos
        for a, want in zip(expr.args, sig.param_types):
            self._emit_expr_as(a, want)

        # slot para o valor de retorno (vai ser preenchido com STOREL -1)
        if sig.return_type == "REAL":
            self.emit("PUSHF 0.0")
        else:
            self.emit("PUSHI 0")

        self.emit(f"PUSHA {self.unit_label(expr.name)}")
        self.emit("CALL")

        # depois do retorno, o resultado fica em cima da stack
        # mas com os argumentos ainda por baixo. Tiramos o resultado
        # para um temporario, limpamos os argumentos e voltamos a por
        # o resultado no topo.
        slot = expr.cleanup_temp
        self._emit_store_off(slot)
        if expr.args:
            self.emit(f"POP {len(expr.args)}")
        self._emit_load_off(slot)

    # -----------------------------------------------------------
    # acesso a simbolos / memoria
    # -----------------------------------------------------------
    def _sym(self, name):
        sym = self.cur_unit.symbols.get(name)
        if sym is None:
            raise SemanticError(
                f"codegen: simbolo desconhecido {name!r} em {self.cur_unit.name!r}"
            )
        return sym

    def _emit_load(self, sym):
        if sym.storage == "global":
            self.emit(f"PUSHG {sym.offset}")
        else:
            self.emit(f"PUSHL {sym.offset}")

    def _emit_store(self, sym):
        if sym.storage == "global":
            self.emit(f"STOREG {sym.offset}")
        else:
            self.emit(f"STOREL {sym.offset}")

    def _emit_load_off(self, offset):
        if self.cur_unit.kind == "main":
            self.emit(f"PUSHG {offset}")
        else:
            self.emit(f"PUSHL {offset}")

    def _emit_store_off(self, offset):
        if self.cur_unit.kind == "main":
            self.emit(f"STOREG {offset}")
        else:
            self.emit(f"STOREL {offset}")

    def _emit_array_addr(self, indices, sym):
        """Calcula o endereco do elemento indexado e deixa-o no topo.

        Layout: base + (i1 - l1) + (i2 - l2) * extent1 + ...
        """
        if sym.storage == "global":
            self.emit("PUSHGP")
        else:
            self.emit("PUSHFP")
        self.emit(f"PUSHI {sym.offset}")
        self.emit("PADD")

        # calcular o indice linear
        stride = 1
        first = True
        for idx_expr, dim in zip(indices, sym.dims):
            self._emit_expr_as(idx_expr, "INTEGER")
            self.emit(f"PUSHI {dim.lower}")
            self.emit("SUB")
            # CHECK 0 N-1: a EWVM faz bounds checking
            self.emit(f"CHECK 0 {dim.extent - 1}")
            if stride != 1:
                self.emit(f"PUSHI {stride}")
                self.emit("MUL")
            if first:
                first = False
            else:
                self.emit("ADD")
            stride *= dim.extent

    # -----------------------------------------------------------
    # auxiliares de formatacao
    # -----------------------------------------------------------
    @staticmethod
    def _fmt_real(v):
        # garantir que o numero sai sempre com ponto decimal
        s = repr(float(v))
        if "." not in s and "e" not in s.lower():
            s += ".0"
        return s

    @staticmethod
    def _escape_vm(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')


def generate(program, info):
    return CodeGenerator(info).generate(program)
