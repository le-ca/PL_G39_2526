# Exceções usadas pelo compilador.
# Todas herdam de CompilerError para conseguirmos apanhar tudo
# numa só clause no programa principal.

class CompilerError(Exception):
    pass


class PreprocessError(CompilerError):
    pass


class LexerError(CompilerError):
    pass


class ParserError(CompilerError):
    pass


class SemanticError(CompilerError):
    pass
