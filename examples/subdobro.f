      PROGRAM DOBROS
C     Demonstra o uso de uma SUBROUTINE
C     que recebe um valor e imprime o dobro
      INTEGER X
      PRINT *, 'Introduza um numero:'
      READ *, X
      CALL MOSTRA(X)
      END

      SUBROUTINE MOSTRA(N)
      INTEGER N
      INTEGER DOBRO
      DOBRO = N * 2
      PRINT *, 'O dobro de ', N, ' e ', DOBRO
      RETURN
      END
