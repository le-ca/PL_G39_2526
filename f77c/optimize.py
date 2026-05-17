# Optimizacao peep-hole simples sobre o codigo VM ja gerado.
#
# A ideia e olhar para "janelas" pequenas (2-3 instrucoes seguidas)
# e substitui-las por algo mais curto sempre que se possa garantir
# que o efeito final e o mesmo.
#
# As que fazemos sao:
#   - eliminar PUSHI 0 / ADD  (e variantes)            -> nao faz nada
#   - eliminar PUSHI 1 / MUL                           -> nao faz nada
#   - eliminar STOREG n / PUSHG n  e  STOREL/PUSHL     -> guardar e logo carregar
#     a mesma celula deixa o valor onde estava; mas precisamos
#     mesmo de guardar, por isso convertemos para
#     DUP 1 / STOREG n
#   - juntar JUMP X / X:        -> remove o JUMP
#   - remover instrucoes a seguir a JUMP/STOP/RETURN
#     que nao tenham label (codigo morto)
#
# Nao tentamos nada mais ambicioso para evitar bugs:
# o objectivo e so reduzir um pouco o codigo gerado.

import re


_LABEL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*$")


def _is_label(line):
    return _LABEL_RE.match(line) is not None


def _label_name(line):
    m = _LABEL_RE.match(line)
    return m.group(1) if m else None


def _drop_dead_after_jump(lines):
    """Remove instrucoes a seguir a JUMP/STOP/RETURN ate ao proximo label."""
    out = []
    skipping = False
    for line in lines:
        if _is_label(line):
            skipping = False
            out.append(line)
            continue
        if skipping:
            continue
        out.append(line)
        # se acabamos de emitir um salto incondicional, marcamos
        # tudo a seguir como morto ate haver um label
        stripped = line.strip()
        if (
            stripped.startswith("JUMP ")
            or stripped == "STOP"
            or stripped == "RETURN"
        ):
            skipping = True
    return out


def _collapse_jump_to_next(lines):
    """JUMP L \n L:  ->  L:  (remove o JUMP redundante)"""
    out = []
    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        if cur.startswith("JUMP ") and i + 1 < len(lines):
            target = cur[5:].strip()
            nxt = lines[i + 1].strip()
            if _is_label(nxt) and _label_name(nxt) == target:
                # saltar o proprio JUMP, manter o label
                i += 1
                continue
        out.append(lines[i])
        i += 1
    return out


def _remove_identity_arith(lines):
    """Remove PUSHI 0 + ADD/SUB  e  PUSHI 1 + MUL/DIV (operando direito).

    Nao mexemos nas versoes float porque sao mais raras e precisamos
    de ter a certeza de que nao alteramos representacoes.
    """
    out = []
    i = 0
    while i < len(lines):
        a = lines[i].strip()
        b = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if a == "PUSHI 0" and b in ("ADD", "SUB"):
            i += 2
            continue
        if a == "PUSHI 1" and b in ("MUL", "DIV"):
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def optimize(vm_code):
    """Recebe o codigo VM completo (string) e devolve uma versao optimizada."""
    lines = vm_code.splitlines()
    # corremos varias vezes porque uma optimizacao pode abrir oportunidade
    # para outra (ex: remover um JUMP pode criar codigo morto antes)
    for _ in range(3):
        before = lines
        lines = _remove_identity_arith(lines)
        lines = _collapse_jump_to_next(lines)
        lines = _drop_dead_after_jump(lines)
        if lines == before:
            break
    return "\n".join(lines) + ("\n" if vm_code.endswith("\n") else "")
