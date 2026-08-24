"""Knowledge graph search & preemption endpoints.

Adding a statute writes to three places: the graph (traversal/preemption),
the vector index (semantic search), and the statute repository (durable
system-of-record — see persistence/). The first two are in-memory indexes
by default and lost on restart regardless of backend choice for *them*;
the repository is what actually survives a restart when
settings.statute_backend="sql" points it at Postgres.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from legal_engine.api.dependencies import (
    EmbedderDep,
    GraphServiceDep,
    StatuteRepositoryDep,
    VectorIndexDep,
)
from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.preemption import resolve_preemption_for_entity

router = APIRouter()


class AddStatuteRequest(BaseModel):
    source_type: SourceType
    jurisdiction_tier: JurisdictionTier
    citation: str
    title: str
    text: str
    applies_to: list[str]


class AddStatuteResponse(BaseModel):
    id: str
    citation: str


@router.post("/statutes", response_model=AddStatuteResponse)
async def add_statute(
    request: AddStatuteRequest,
    graph_service: GraphServiceDep,
    vector_index: VectorIndexDep,
    embedder: EmbedderDep,
    statute_repository: StatuteRepositoryDep,
) -> AddStatuteResponse:
    statute = StatuteDocument(
        source_type=request.source_type,
        jurisdiction_tier=request.jurisdiction_tier,
        citation=request.citation,
        title=request.title,
        text=request.text,
    )
    graph_service.add_statute(statute, applies_to=request.applies_to)
    vector_index.upsert(statute.id, embedder.embed(statute.text), {"citation": statute.citation})
    await statute_repository.add(statute)
    return AddStatuteResponse(id=str(statute.id), citation=statute.citation)


@router.get("/statutes/{statute_id}", response_model=StatuteDocument)
async def get_statute(statute_id: UUID, statute_repository: StatuteRepositoryDep) -> StatuteDocument:
    statute = await statute_repository.get(statute_id)
    if statute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Statute not found")
    return statute


@router.get("/statutes", response_model=list[StatuteDocument])
async def list_statutes(
    statute_repository: StatuteRepositoryDep, citation: str | None = None
) -> list[StatuteDocument]:
    if citation is not None:
        return await statute_repository.list_by_citation(citation)
    return await statute_repository.all()


class PreemptionResponse(BaseModel):
    entity_id: str
    governing_citation: str | None
    preempted_citations: list[str]
    requires_review: bool
    conflicting_tier: JurisdictionTier | None


@router.get("/preemption/{entity_id}", response_model=PreemptionResponse)
async def get_preemption(entity_id: str, graph_service: GraphServiceDep) -> PreemptionResponse:
    result = resolve_preemption_for_entity(graph_service, entity_id)
    return PreemptionResponse(
        entity_id=result.entity_id,
        governing_citation=result.governing.citation if result.governing else None,
        preempted_citations=[s.citation for s in result.preempted],
        requires_review=result.requires_review,
        conflicting_tier=result.conflicting_tier,
    )


class SearchRequest(BaseModel):
    query_text: str
    top_k: int = 5


class SearchMatch(BaseModel):
    citation: str
    distance: float
    is_match: bool


@router.post("/search", response_model=list[SearchMatch])
async def search_statutes(
    request: SearchRequest, vector_index: VectorIndexDep, embedder: EmbedderDep
) -> list[SearchMatch]:
    query_vector = embedder.embed(request.query_text)
    matches = vector_index.search(query_vector, top_k=request.top_k)
    return [
        SearchMatch(
            citation=m.metadata.get("citation", str(m.id)), distance=m.distance, is_match=m.is_match
        )
        for m in matches
    ]
