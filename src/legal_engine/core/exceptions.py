"""Domain-specific exception hierarchy for the Legal Engine Platform."""


class LegalEngineError(Exception):
    """Base class for all Legal Engine domain errors."""


class IngestionError(LegalEngineError):
    """Raised when a source document cannot be fetched or parsed."""


class ParseError(IngestionError):
    """Raised when a parser cannot extract a valid document structure."""


class FormalLogicError(LegalEngineError):
    """Base class for formal-logic compilation/solving errors."""


class NotEPRFragmentError(FormalLogicError):
    """Raised when a formula cannot be compiled into the decidable EPR fragment.

    EPR (Bernays-Schoenfinkel-Ramsey) decidability requires: prenex-normal-form
    quantifier prefix exists*-forall*, zero-arity function symbols only, and a
    finite domain of discourse. A formula that violates any of these is
    rejected rather than passed to the solver, since satisfiability would no
    longer be guaranteed decidable.
    """


class SolverTimeoutError(FormalLogicError):
    """Raised when the Z3 solver exceeds its configured timeout."""


class SolverResourceLimitError(FormalLogicError):
    """Raised when the Z3 solver process exceeds its memory limit."""


class GameTheoryError(LegalEngineError):
    """Base class for game-theoretic modeling errors."""


class NoDominantStrategyError(GameTheoryError):
    """Raised when no penalty level makes compliance a dominant strategy."""


class RefactoringError(LegalEngineError):
    """Base class for dependency-graph / arbitrage refactoring errors."""


class UnbalancedCycleError(RefactoringError):
    """Raised when the cycle-basis system B * w = 0 has no feasible solution."""


class KnowledgeGraphError(LegalEngineError):
    """Base class for knowledge-graph and preemption-resolution errors."""


class WALIntegrityError(LegalEngineError):
    """Raised when a write-ahead log entry fails hash-chain or signature verification."""
