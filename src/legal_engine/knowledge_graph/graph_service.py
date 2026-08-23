"""Neo4j / NetworkX graph driver. Not yet implemented — Phase 2.

Planned: a directed graph of MunicipalCode/StateStatute/FederalCode/
InternationalTreaty/JudicialPrecedent nodes, with preemption edges weighted
by legal_engine.core.models.JurisdictionTier ordering, backed by Neo4j in
production and NetworkX for local/test use.
"""
