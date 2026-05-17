      PROGRAM MEDIA
C     Calcula a media de 3 numeros reais lidos do teclado
C     usando uma FUNCTION que devolve um REAL
      REAL A, B, C, M, AVG3

      PRINT *, 'Introduza tres numeros reais:'
      READ *, A
      READ *, B
      READ *, C

      M = AVG3(A, B, C)
      PRINT *, 'A media e: ', M
      END

      REAL FUNCTION AVG3(X, Y, Z)
      REAL X, Y, Z
      AVG3 = (X + Y + Z) / 3.0
      RETURN
      END
