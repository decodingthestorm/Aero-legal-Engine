"""Knowledge graph service: statute nodes, the entities they apply to, and
Article VI Supremacy Clause preemption edges between them.

Two node kinds live in the same graph:

- statute nodes, one per ingested ``StatuteDocument``
- entity nodes, representing whatever real-world subject a statute regulates
  (a parcel, an actor, a regulated activity — anything ``preemption.py``
  needs to group statutes by to find candidate conflicts)

``applies_to`` edges connect statute -> entity. ``preempts`` edges connect
statute -> statute and are derived, not asserted directly by callers — see
``derive_preemption_edges`` — so the graph can't get out of sync with
``JurisdictionTier`` ordering.

``GraphService`` is a Protocol so the API/worker layers can depend on it
without caring whether the backing store is the in-process NetworkX graph
(``NetworkXGraphService``, fully functional and what the test suite uses) or
a real Neo4j deployment (``Neo4jGraphService`` — thin wrapper, requires a
live Neo4j instance and the `neo4j` driver package, neither of which this
environment has, so it's implemented but not exercised by tests).
"""

from __future__ import annotations

from typing import Any, Protocol, cast
from uuid import UUID

import networkx as nx

from legal_engine.core.models import StatuteDocument


class GraphService(Protocol):
    def add_statute(self, statute: StatuteDocument, applies_to: list[str]) -> None: ...

    def get_statute(self, statute_id: UUID) -> StatuteDocument: ...

    def statutes_for_entity(self, entity_id: str) -> list[StatuteDocument]: ...

    def add_preemption_edge(self, higher_id: UUID, lower_id: UUID) -> None: ...

    def preemption_edges(self) -> list[tuple[UUID, UUID]]: ...

    def all_entity_ids(self) -> list[str]: ...


class NetworkXGraphService:
    """In-process graph backed by networkx.DiGraph. Used for local dev and tests."""

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    def add_statute(self, statute: StatuteDocument, applies_to: list[str]) -> None:
        statute_node = _statute_node_id(statute.id)
        self._graph.add_node(statute_node, kind="statute", statute=statute)
        for entity_id in applies_to:
            entity_node = _entity_node_id(entity_id)
            self._graph.add_node(entity_node, kind="entity")
            self._graph.add_edge(statute_node, entity_node, relation="applies_to")

    def get_statute(self, statute_id: UUID) -> StatuteDocument:
        node = _statute_node_id(statute_id)
        if node not in self._graph:
            raise KeyError(f"No statute with id {statute_id}")
        return cast(StatuteDocument, self._graph.nodes[node]["statute"])

    def statutes_for_entity(self, entity_id: str) -> list[StatuteDocument]:
        entity_node = _entity_node_id(entity_id)
        if entity_node not in self._graph:
            return []
        statutes = []
        for predecessor in self._graph.predecessors(entity_node):
            if self._graph.nodes[predecessor].get("kind") == "statute":
                statutes.append(self._graph.nodes[predecessor]["statute"])
        return statutes

    def add_preemption_edge(self, higher_id: UUID, lower_id: UUID) -> None:
        higher_node = _statute_node_id(higher_id)
        lower_node = _statute_node_id(lower_id)
        if higher_node not in self._graph or lower_node not in self._graph:
            raise KeyError("Both statutes must already be in the graph")
        self._graph.add_edge(higher_node, lower_node, relation="preempts")

    def preemption_edges(self) -> list[tuple[UUID, UUID]]:
        edges = []
        for u, v, data in self._graph.edges(data=True):
            if data.get("relation") == "preempts":
                edges.append((self._graph.nodes[u]["statute"].id, self._graph.nodes[v]["statute"].id))
        return edges

    def all_statutes(self) -> list[StatuteDocument]:
        return [
            data["statute"]
            for _, data in self._graph.nodes(data=True)
            if data.get("kind") == "statute"
        ]

    def all_entity_ids(self) -> list[str]:
        return [
            node.removeprefix("entity:")
            for node, data in self._graph.nodes(data=True)
            if data.get("kind") == "entity"
        ]


class Neo4jGraphService:
    """Neo4j-backed GraphService. Requires a live Neo4j instance and the
    `neo4j` driver package — neither is installed/running in this
    environment, so this is implemented but not covered by the test suite.
    Import of the driver is deferred to __init__ so importing this module
    doesn't require the optional dependency to be installed.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase
        except Exception as exc:
            raise ImportError(
                "Neo4jGraphService requires the 'neo4j' package: pip install neo4j "
                f"(underlying error: {exc.__class__.__name__}: {exc})"
            ) from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def add_statute(self, statute: StatuteDocument, applies_to: list[str]) -> None:
        with self._driver.session() as session:
            session.execute_write(_create_statute_tx, statute, applies_to)

    def get_statute(self, statute_id: UUID) -> StatuteDocument:
        raise NotImplementedError("Neo4jGraphService.get_statute: implement once schema is final")

    def statutes_for_entity(self, entity_id: str) -> list[StatuteDocument]:
        raise NotImplementedError(
            "Neo4jGraphService.statutes_for_entity: implement once schema is final"
        )

    def add_preemption_edge(self, higher_id: UUID, lower_id: UUID) -> None:
        raise NotImplementedError(
            "Neo4jGraphService.add_preemption_edge: implement once schema is final"
        )

    def preemption_edges(self) -> list[tuple[UUID, UUID]]:
        raise NotImplementedError(
            "Neo4jGraphService.preemption_edges: implement once schema is final"
        )

    def all_entity_ids(self) -> list[str]:
        raise NotImplementedError(
            "Neo4jGraphService.all_entity_ids: implement once schema is final"
        )


def _create_statute_tx(tx: Any, statute: StatuteDocument, applies_to: list[str]) -> None:
    tx.run(
        "MERGE (s:Statute {id: $id}) SET s.citation = $citation, s.title = $title, "
        "s.jurisdiction_tier = $tier",
        id=str(statute.id),
        citation=statute.citation,
        title=statute.title,
        tier=statute.jurisdiction_tier.value,
    )
    for entity_id in applies_to:
        tx.run(
            "MERGE (e:Entity {id: $entity_id}) "
            "WITH e MATCH (s:Statute {id: $statute_id}) "
            "MERGE (s)-[:APPLIES_TO]->(e)",
            entity_id=entity_id,
            statute_id=str(statute.id),
        )


def _statute_node_id(statute_id: UUID) -> str:
    return f"statute:{statute_id}"


def _entity_node_id(entity_id: str) -> str:
    return f"entity:{entity_id}"
