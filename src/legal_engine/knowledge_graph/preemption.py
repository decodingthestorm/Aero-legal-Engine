"""Article VI Supremacy Clause conflict resolver. Not yet implemented — Phase 2.

Planned: when two statute nodes on the same graph_service.py entity conflict,
use JurisdictionTier.preempts() (core/models.py) to determine which one wins
and truncate the subordinate contradictory clause before it reaches
formal_logic/ verification.
"""
