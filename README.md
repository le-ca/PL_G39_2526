# Compilador de Fortran 77 para a EWVM

Projeto desenvolvido no âmbito da unidade curricular de **Processamento de Linguagens** (2025/2026),
Licenciatura em Engenharia Informática, Universidade do Minho.

**Grupo 39**
- Gonçalo Costa — A107381
- Diogo Costa — A107328
- Lourenço Martins — A106849

---

## Descrição

O objetivo deste projeto foi implementar um compilador para um subconjunto do Fortran 77
(standard ANSI X3.9-1978) que gera código para a máquina virtual EWVM.

O compilador foi escrito em Python e usa a biblioteca PLY (*Python Lex-Yacc*) para as fases
de análise léxica e sintática, conforme indicado no enunciado.

---

## Requisitos

- Python 3.10 ou superior
- PLY 3.11 ou superior

Para instalar as dependências:

```bash
pip install -r requirements.txt
```

---

## Como usar

### Compilar um ficheiro Fortran

```bash
python compiler.py examples/factorial.f
```

Isto gera o ficheiro `examples/factorial.vm` com o código para a EWVM.

Para especificar o ficheiro de saída:

```bash
python compiler.py examples/factorial.f -o saida.vm
```

Para desligar a optimização peep-hole:

```bash
python compiler.py examples/factorial.f --no-opt
```

### Compilar todos os exemplos

```bash
make examples
```

### Correr os testes

```bash
python -m unittest -v
```

ou

```bash
make test
```

---

## Estrutura do projeto

fortran77_compiler/
├── compiler.py          # programa principal
├── requirements.txt
├── Makefile
├── f77c/
│   ├── preprocess.py    # pré-processamento do código fonte
│   ├── lexer.py         # análise léxica (ply.lex)
│   ├── parser.py        # análise sintática (ply.yacc)
│   ├── ast_nodes.py     # nós da AST
│   ├── semantics.py     # análise semântica e tabela de símbolos
│   ├── codegen.py       # geração de código EWVM
│   └── optimize.py      # optimizador peep-hole
├── examples/            # programas Fortran de exemplo (.f) e respectivo código VM (.vm)
└── tests/               # testes automáticos

---

## O que está implementado

- Declaração de variáveis `INTEGER`, `REAL` e `LOGICAL` (escalares e arrays)
- Expressões aritméticas, relacionais e lógicas
- Atribuições
- `IF ... THEN / ELSE IF / ELSE / ENDIF`
- Ciclos `DO` com label de fim e step opcional (positivo e negativo)
- `GOTO`, `CONTINUE`, `STOP`, `RETURN`
- `PRINT *, ...` e `READ *, ...`
- Funções built-in `MOD` e `ABS`
- Definição e chamada de `FUNCTION` e `SUBROUTINE`
- Comentários com `!`, `C` ou `*`
- Optimizador peep-hole (eliminação de código morto, saltos redundantes, aritmética identidade)

## O que não está implementado

- Tipo `CHARACTER` e operações sobre strings
- Instruções `COMMON`, `DATA`, `EQUIVALENCE`
- `IMPLICIT` (tipagem implícita do Fortran 77)
- Arrays como parâmetros de subprogramas
- Formatos no `PRINT`/`READ` (suportamos apenas `*`)
- Formato de colunas fixas estrito do standard

---

## Exemplos incluídos

| Ficheiro | Descrição |
|---|---|
| `hello.f` | Olá Mundo |
| `factorial.f` | Cálculo do factorial |
| `prime.f` | Verificação de número primo |
| `sumarr.f` | Soma de elementos de um array |
| `conversor.f` | Conversão decimal para bases 2 a 9 (usa FUNCTION) |
| `subdobro.f` | Exemplo de SUBROUTINE |
| `tabmult.f` | Tabuada com DOs encaixados |
| `media.f` | Média de três reais (usa FUNCTION com REAL) |

---

## Validação

O código gerado foi testado na máquina virtual EWVM disponível em
[https://ewvm.epl.di.uminho.pt/](https://ewvm.epl.di.uminho.pt/).

Para mais detalhes sobre as opções de implementação, a gramática e as dificuldades
encontradas, consultar o `relatorio.pdf` incluído no repositório.
