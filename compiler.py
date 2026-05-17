#!/usr/bin/env python3
# Programa principal do compilador.
# Le um ficheiro .f, compila e escreve um ficheiro .vm.

import argparse
import sys
from pathlib import Path

from f77c import compile_file
from f77c.errors import CompilerError


def main():
    ap = argparse.ArgumentParser(
        description="Compilador de Fortran 77 (subset) para a EWVM."
    )
    ap.add_argument("source", help="ficheiro de entrada (.f ou .f77)")
    ap.add_argument(
        "-o", "--output",
        help="ficheiro de saida (.vm). Por omissao troca a extensao do ficheiro de entrada.",
    )
    ap.add_argument(
        "--no-opt",
        action="store_true",
        help="desliga a optimizacao peep-hole",
    )
    args = ap.parse_args()

    res = compile_file(args.source, optimize_code=not args.no_opt)

    if args.output:
        out = Path(args.output)
    else:
        out = Path(args.source).with_suffix(".vm")

    out.write_text(res.vm_code, encoding="utf-8")

    for w in res.info.warnings:
        print(f"[aviso] {w}", file=sys.stderr)

    print(f"[ok] gerado {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CompilerError as e:
        print(f"[erro] {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"[erro] nao foi possivel abrir o ficheiro: {e}", file=sys.stderr)
        sys.exit(1)
