# Testes do compilador.
# Sao "smoke tests" -- nao testamos o output da EWVM em si,
# so verificamos que:
#  - os exemplos compilam sem erros
#  - certas instrucoes aparecem (ou nao) no codigo gerado
#  - certos erros semanticos sao apanhados

import unittest
from pathlib import Path

from f77c import compile_file, compile_source
from f77c.errors import SemanticError, ParserError, PreprocessError


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class TestExamplesDoEnunciado(unittest.TestCase):
    """Os exemplos que vem no enunciado tem todos de compilar."""

    def test_todos_os_exemplos_compilam(self):
        nomes = ["hello.f", "factorial.f", "prime.f", "sumarr.f", "conversor.f"]
        for n in nomes:
            with self.subTest(exemplo=n):
                r = compile_file(EXAMPLES / n)
                self.assertIn("STOP", r.vm_code)

    def test_hello_imprime_a_string(self):
        r = compile_file(EXAMPLES / "hello.f")
        self.assertIn('PUSHS "Ola, Mundo!"', r.vm_code)
        self.assertIn("WRITES", r.vm_code)

    def test_factorial_le_inteiro(self):
        r = compile_file(EXAMPLES / "factorial.f")
        self.assertIn("READ", r.vm_code)
        self.assertIn("ATOI", r.vm_code)

    def test_array_usa_check(self):
        # o sumarr usa NUMS(I) -- tem de gerar instrucao CHECK
        # para validar os bounds em runtime
        r = compile_file(EXAMPLES / "sumarr.f")
        self.assertIn("CHECK", r.vm_code)


class TestExpressoes(unittest.TestCase):

    def test_expr_aritmetica_simples(self):
        src = """
        PROGRAM ARIT
        INTEGER X
        X = 2 + 3 * 4
        PRINT *, X
        END
        """
        r = compile_source(src)
        self.assertIn("ADD", r.vm_code)
        self.assertIn("MUL", r.vm_code)

    def test_divisao_real(self):
        src = """
        PROGRAM REALDIV
        REAL X
        X = 3.0 / 2.0
        END
        """
        r = compile_source(src)
        self.assertIn("FDIV", r.vm_code)

    def test_conversao_int_para_real(self):
        # atribuir int a real tem de inserir ITOF
        src = """
        PROGRAM CONV
        REAL X
        X = 5
        END
        """
        r = compile_source(src)
        self.assertIn("ITOF", r.vm_code)

    def test_operadores_logicos(self):
        src = """
        PROGRAM LOGOP
        LOGICAL A, B
        A = .TRUE.
        B = .NOT. A
        END
        """
        r = compile_source(src)
        self.assertIn("NOT", r.vm_code)

    def test_comparacao_real(self):
        src = """
        PROGRAM CMPR
        REAL X
        LOGICAL R
        X = 1.5
        R = X .GT. 1.0
        END
        """
        r = compile_source(src)
        self.assertIn("FSUP", r.vm_code)


class TestControloDeFluxo(unittest.TestCase):

    def test_if_else_compila(self):
        src = """
        PROGRAM TESTE
        INTEGER X
        X = 2
        IF (X .EQ. 1) THEN
          PRINT *, 'UM'
        ELSE
          PRINT *, 'OUTRO'
        ENDIF
        END
        """
        r = compile_source(src)
        self.assertIn("JZ", r.vm_code)
        self.assertIn("JUMP", r.vm_code)

    def test_if_elseif_else(self):
        src = """
        PROGRAM ELIFTEST
        INTEGER X
        X = 5
        IF (X .EQ. 1) THEN
          PRINT *, 'UM'
        ELSE IF (X .EQ. 2) THEN
          PRINT *, 'DOIS'
        ELSE
          PRINT *, 'OUTRO'
        ENDIF
        END
        """
        r = compile_source(src)
        # tem de haver pelo menos 2 saltos condicionais (um por cada IF)
        self.assertGreaterEqual(r.vm_code.count("JZ"), 2)

    def test_do_loop_basico(self):
        src = """
        PROGRAM LOOP
        INTEGER I
        DO 10 I = 1, 10
          PRINT *, I
   10   CONTINUE
        END
        """
        r = compile_source(src)
        # nome dos labels gerados pelos DOs
        self.assertIn("dobody", r.vm_code)
        self.assertIn("doend", r.vm_code)


    def test_goto_e_label(self):
        src = """
        PROGRAM JUMPS
        INTEGER I
        I = 0
   10   I = I + 1
        IF (I .LT. 5) GOTO 10
        END
        """
        # Nota: o nosso compilador so suporta GOTO como statement
        # simples, nao 'IF (...) GOTO X' nesta linha. Vamos verificar
        # uma versao com IF-THEN.
        # Versao alternativa:
        src2 = """
        PROGRAM JUMPS
        INTEGER I
        I = 0
   10   I = I + 1
        IF (I .LT. 5) THEN
          GOTO 10
        ENDIF
        END
        """
        r = compile_source(src2)
        self.assertIn("JUMP ljumps10", r.vm_code)


class TestSemanticErrors(unittest.TestCase):

    def test_variavel_nao_declarada(self):
        src = """
        PROGRAM ERRO
        X = 1
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_redeclaracao(self):
        src = """
        PROGRAM DUP
        INTEGER X
        INTEGER X
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_atribuir_real_a_logical(self):
        src = """
        PROGRAM BADTYPE
        LOGICAL L
        L = 1.5
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_do_step_zero(self):
        src = """
        PROGRAM BADSTEP
        INTEGER I
        DO 10 I = 1, 5, 0
   10   CONTINUE
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_alterar_variavel_de_do(self):
        src = """
        PROGRAM BADDO
        INTEGER I
        DO 10 I = 1, 3
          I = I + 1
   10   CONTINUE
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_goto_sem_destino(self):
        src = """
        PROGRAM BADGOTO
        INTEGER X
        X = 1
        GOTO 99
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)

    def test_array_indice_errado(self):
        src = """
        PROGRAM ARRERR
        INTEGER A(5)
        A(1, 2) = 0
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)


class TestSubprogramas(unittest.TestCase):

    def test_funcao_inteira(self):
        src = """
        PROGRAM USAF
        INTEGER X, DOBRO
        X = DOBRO(5)
        PRINT *, X
        END

        INTEGER FUNCTION DOBRO(N)
        INTEGER N
        DOBRO = N * 2
        RETURN
        END
        """
        r = compile_source(src)
        self.assertIn("unitdobro", r.vm_code)
        self.assertIn("CALL", r.vm_code)

    def test_subroutine_call(self):
        src = """
        PROGRAM USES
        INTEGER X
        X = 3
        CALL DOBRA(X)
        END

        SUBROUTINE DOBRA(N)
        INTEGER N
        PRINT *, N * 2
        RETURN
        END
        """
        r = compile_source(src)
        self.assertIn("unitdobra", r.vm_code)
        self.assertIn("CALL", r.vm_code)

    def test_call_a_funcao_inexistente(self):
        src = """
        PROGRAM ERRCALL
        INTEGER X
        X = NAOEXISTE(1)
        END
        """
        with self.assertRaises(SemanticError):
            compile_source(src)


class TestPreprocess(unittest.TestCase):

    def test_comentario_com_excl(self):
        src = """
        PROGRAM COMM
        INTEGER X  ! isto e um comentario
        X = 1      ! outro
        END
        """
        r = compile_source(src)
        self.assertIn("STOP", r.vm_code)

    def test_comentario_fortran_classico_C(self):
        # No Fortran 77, linhas com C na coluna 1 sao comentario
        src = """C este programa imprime ola mundo
        PROGRAM OLA
        PRINT *, 'OLA'
        END
        """
        r = compile_source(src)
        self.assertIn('PUSHS "OLA"', r.vm_code)

    def test_comentario_com_asterisco(self):
        # Linhas com * na coluna 1 tambem sao comentario
        src = """* este e outro tipo de comentario
        PROGRAM OLA2
        PRINT *, 'OLA'
        END
        """
        r = compile_source(src)
        self.assertIn('PUSHS "OLA"', r.vm_code)

    def test_string_nao_terminada(self):
        src = """
        PROGRAM BAD
        PRINT *, 'nao tem fim
        END
        """
        with self.assertRaises(PreprocessError):
            compile_source(src)


class TestOptimizer(unittest.TestCase):
    """Testes da optimizacao peep-hole."""

    def test_optimize_e_default(self):
        # codigo gerado com e sem optimizacao deve ser diferente
        # (ou pelo menos nao maior) quando se desliga
        src = """
        PROGRAM OPTTEST
        INTEGER I
        DO 10 I = 1, 3
          PRINT *, I
   10   CONTINUE
        END
        """
        r1 = compile_source(src, optimize_code=False)
        r2 = compile_source(src, optimize_code=True)
        self.assertLessEqual(len(r2.vm_code), len(r1.vm_code))


if __name__ == "__main__":
    unittest.main()
