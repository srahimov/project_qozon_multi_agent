"""Public document summaries and approved citation links; original PDFs stay private."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from qozon_multi_agent.api.dependencies import get_document_reader
from qozon_multi_agent.api.schemas import APIErrorResponse
from qozon_multi_agent.knowledge_base.documents import DocumentReader

router = APIRouter(prefix="/documents", tags=["documents"], responses={
    404: {"model": APIErrorResponse, "description": "Document or approved source is unavailable."},
    422: {"model": APIErrorResponse, "description": "Invalid document request."},
    502: {"model": APIErrorResponse, "description": "A checked response could not be provided."},
    503: {"model": APIErrorResponse, "description": "Document service unavailable."},
    504: {"model": APIErrorResponse, "description": "Document access timed out."},
})
Reader = Annotated[DocumentReader, Depends(get_document_reader)]
NO_CACHE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: UUID
    title: str
    active_revision: str | None


@router.get("", response_model=list[DocumentSummary])
async def documents(reader: Reader, response: Response,
                    limit: Annotated[int, Query(ge=1, le=100)] = 50,
                    offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    response.headers.update(NO_CACHE_HEADERS)
    return await reader.list_documents(limit, offset)


@router.get("/{document_id}", response_model=DocumentSummary)
async def document(document_id: UUID, reader: Reader, response: Response):
    response.headers.update(NO_CACHE_HEADERS)
    return await reader.document(document_id)



@router.get("/{document_id}/citations/{chunk_id}/{kind}", status_code=307,
            response_class=RedirectResponse, responses={307: {
                "description": "Redirect to a previously approved public citation file.",
                "headers": {"Location": {"schema": {"type": "string", "format": "uri"}}},
            }})
async def citation_source(document_id: UUID,
                          chunk_id: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
                          kind: Literal["image", "structured", "text"], reader: Reader):
    url = await reader.citation_url(document_id, chunk_id, kind)
    return RedirectResponse(url, status_code=307, headers=NO_CACHE_HEADERS)
