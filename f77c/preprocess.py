# Pre-processamento das linhas de Fortran antes de irem para o lexer.
#
# O Fortran 77 standard usa um formato de colunas fixas chato, em que
# a coluna 1 indica comentario (C ou *), as colunas 1-5 sao para labels,
# coluna 6 e continuacao e o codigo comeca na coluna 7. Decidimos suportar
# uma versao "relaxada":
#   - linhas que comecem com C, c ou * sao comentario (formato classico)
#   - tambem aceitamos '!' como comentario ate ao fim da linha
#   - labels podem aparecer no inicio da linha seguidos de espaco
#   - tudo o resto e "livre" (free-form)

import re

from .errors import PreprocessError


class SourceLine:
    """Linha já limpa, pronta para o lexer."""

    def __init__(self, lineno, label, text):
        self.lineno = lineno
        self.label = label   # int ou None
        self.text = text     # sem label, sem comentario, em MAIUSCULAS fora das strings

    def __repr__(self):
        return f"SourceLine(lineno={self.lineno}, label={self.label}, text={self.text!r})"


_LABEL_RE = re.compile(r"^\s*(\d+)\s+(.*)$")


def _is_full_line_comment(raw):
    # comentario classico do Fortran 77: 'C', 'c' ou '*' na coluna 1
    if not raw:
        return False
    return raw[0] in ("C", "c", "*")


def _strip_comment_and_upper(line):
    """Remove comentario '!' (fora de strings) e poe tudo em maiusculas
    (excepto dentro de strings 'foo')."""
    out = []
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]

        # strings: '...'  com '' a escapar a apostrofe
        if ch == "'":
            out.append(ch)
            if in_string:
                if i + 1 < len(line) and line[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_string = False
            else:
                in_string = True
            i += 1
            continue

        # comentario com '!' fora de string
        if not in_string and ch == "!":
            break

        if in_string:
            out.append(ch)
        else:
            out.append(ch.upper())
        i += 1

    if in_string:
        raise PreprocessError("string nao terminada antes do fim da linha")

    return "".join(out)


def preprocess(source):
    """Recebe o codigo fonte e devolve uma lista de SourceLine."""
    result = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        # comentarios classicos C/* ocupam a linha toda
        if _is_full_line_comment(raw):
            continue

        cooked = _strip_comment_and_upper(raw).strip()
        if not cooked:
            continue

        # extrair label se a linha começar com digitos
        label = None
        text = cooked
        m = _LABEL_RE.match(cooked)
        if m:
            label = int(m.group(1))
            text = m.group(2).strip()

        if not text:
            # linha so com label, sem instrucao -> erro
            raise PreprocessError(f"linha {lineno}: label sem instrucao a seguir")

        result.append(SourceLine(lineno, label, text))

    return result
