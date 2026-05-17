# Compilador Fortran 77 → EWVM

Projeto de Processamento de Linguagens (2025/2026).

Compilador de um subconjunto do Fortran 77 standard para a máquina virtual
EWVM (https://ewvm.epl.di.uminho.pt/), feito em Python usando PLY.

## Como correr

Precisa de Python 3.10+ (usámos type hints com `Optional` e `dataclasses`).

```bash
pip install -r requirements.txt
python compiler.py examples/factorial.f
```

Isto vai gerar `examples/factorial.vm`. Para escolher o nome do output:

```bash
python compiler.py examples/factorial.f -o saida.vm
```

Para desligar a optimização peep-hole:

```bash
python compiler.py examples/factorial.f --no-opt
```

Para correr os testes:

```bash
python -m unittest -v
```

E para compilar todos os exemplos de uma vez:

```bash
make examples
```

## Onde está o quê

- `compiler.py` — programa principal, lê o `.f` e escreve o `.vm`
- `f77c/preprocess.py` — limpeza inicial das linhas (comentários, labels)
- `f77c/lexer.py` — tokens, usa `ply.lex`
- `f77c/parser.py` — gramática, usa `ply.yacc`
- `f77c/ast_nodes.py` — classes da AST (dataclasses)
- `f77c/semantics.py` — tabela de símbolos, verificação de tipos
- `f77c/codegen.py` — geração de código EWVM
- `f77c/optimize.py` — optimizador peep-hole
- `examples/` — programas de exemplo (.f) e o respectivo `.vm`
- `tests/` — testes unitários

## O que está implementado

- `PROGRAM ... END`
- `INTEGER`, `REAL`, `LOGICAL` (escalares e arrays)
- expressões aritméticas, relacionais (`.LE.`, `.GT.`, ...) e lógicas (`.AND.`, `.OR.`, `.NOT.`)
- `IF ... THEN / ELSE IF / ELSE / ENDIF`
- ciclos `DO N var = inicio, fim [, step]` ... `N CONTINUE`
- `GOTO`, `CONTINUE`, `STOP`, `RETURN`
- `PRINT *, ...` e `READ *, ...`
- chamadas a `MOD` e `ABS`
- `FUNCTION` e `SUBROUTINE` (com argumentos escalares)
- comentários com `!`, `C` ou `*`

## O que NÃO está

- formato de colunas fixas estrito (usamos formato livre, ver relatório)
- `CHARACTER` e variáveis de string
- `COMMON`, `DATA`, `EQUIVALENCE`
- `IMPLICIT`
- arrays passados como parâmetro
- formatos no `PRINT`/`READ` (só `*`)

## Documentação

Ver `RELATORIO.md` para a descrição técnica do projeto.
