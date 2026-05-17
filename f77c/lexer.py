# Analisador lexico usando ply.lex.
#
# Como o pre-processador ja poe tudo em maiusculas (fora de strings)
# nao precisamos de te ignorar capitalizacao aqui.

import ply.lex as lex

from .errors import LexerError


# palavras reservadas: nome -> tipo de token
reserved = {
    "PROGRAM":    "PROGRAM",
    "END":        "END",
    "INTEGER":    "INTEGER",
    "REAL":       "REAL",
    "LOGICAL":    "LOGICAL",
    "FUNCTION":   "FUNCTION",
    "SUBROUTINE": "SUBROUTINE",
    "CALL":       "CALL",
    "RETURN":     "RETURN",
    "IF":         "IF",
    "THEN":       "THEN",
    "ELSE":       "ELSE",
    "ELSEIF":     "ELSEIF",
    "ENDIF":      "ENDIF",
    "DO":         "DO",
    "CONTINUE":   "CONTINUE",
    "GOTO":       "GOTO",
    "PRINT":      "PRINT",
    "READ":       "READ",
    "STOP":       "STOP",
}

tokens = [
    "ID",
    "INT_CONST",
    "REAL_CONST",
    "STRING",
    "TRUE", "FALSE",
    "AND", "OR", "NOT",
    "LT", "LE", "GT", "GE", "EQ", "NE",
] + list(reserved.values())

# operadores e pontuacao "simples" sao literais
literals = "+-*/(),=:"

t_ignore = " \t\r"


# operadores logicos e relacionais do Fortran 77 -- vem entre pontos
# ex: .EQ.  .NE.  .AND.  .OR.  ...

def t_TRUE(t):
    r"\.TRUE\."
    t.value = True
    return t

def t_FALSE(t):
    r"\.FALSE\."
    t.value = False
    return t

def t_AND(t):
    r"\.AND\."
    return t

def t_OR(t):
    r"\.OR\."
    return t

def t_NOT(t):
    r"\.NOT\."
    return t

def t_LE(t):
    r"\.LE\."
    return t

def t_LT(t):
    r"\.LT\."
    return t

def t_GE(t):
    r"\.GE\."
    return t

def t_GT(t):
    r"\.GT\."
    return t

def t_EQ(t):
    r"\.EQ\."
    return t

def t_NE(t):
    r"\.NE\."
    return t


# numeros: real antes de inteiro (senao o '.' nunca era apanhado)
def t_REAL_CONST(t):
    r"(\d+\.\d*|\.\d+)"
    t.value = float(t.value)
    return t

def t_INT_CONST(t):
    r"\d+"
    t.value = int(t.value)
    return t


# strings entre apostrofos. '' dentro da string representa um apostrofe
def t_STRING(t):
    r"'([^']|'')*'"
    # tira as aspas de fora e faz unescape de ''
    t.value = t.value[1:-1].replace("''", "'")
    return t


def t_ID(t):
    r"[A-Z][A-Z0-9_]*"
    # se for palavra reservada muda o type
    t.type = reserved.get(t.value, "ID")
    return t


def t_error(t):
    raise LexerError(f"simbolo invalido {t.value[0]!r} na linha {t.lineno}")


def make_lexer():
    # optimize=False e lextab=None: nao queremos cache em ficheiro,
    # senao o ply gera ficheiros parser.out / lextab.py no projeto
    return lex.lex(optimize=False, lextab=None)
