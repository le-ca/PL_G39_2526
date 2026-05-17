      PROGRAM TABMULT
*     Tabuada de 1 a 5 usando ciclos DO encaixados
      INTEGER I, J, P
      DO 20 I = 1, 5
         DO 10 J = 1, 5
            P = I * J
            PRINT *, I, ' x ', J, ' = ', P
   10    CONTINUE
   20 CONTINUE
      END
