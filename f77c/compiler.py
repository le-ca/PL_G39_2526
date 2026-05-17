from dataclasses import dataclass
from pathlib import Path

from .codegen import generate
from .optimize import optimize
from .parser import parse
from .preprocess import preprocess
from .semantics import ProgramInfo, analyze


@dataclass
class CompileResult:
    vm_code: str
    info: ProgramInfo


def compile_source(source, optimize_code=True):
    # pipeline do compilador:
    #   1) preprocess: tira comentarios, normaliza maiusculas, isola labels
    #   2) parse: lex+yacc -> AST
    #   3) semantica: tabela de simbolos, types, labels
    #   4) codegen: AST -> codigo EWVM
    #   5) (opcional) optimize: peep-hole sobre o codigo gerado
    lines = preprocess(source)
    prog = parse(lines)
    info = analyze(prog)
    code = generate(prog, info)
    if optimize_code:
        code = optimize(code)
    return CompileResult(code, info)


def compile_file(path, optimize_code=True):
    src = Path(path).read_text(encoding="utf-8")
    return compile_source(src, optimize_code=optimize_code)
