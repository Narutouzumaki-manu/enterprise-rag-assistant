import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_app_settings,
    get_current_user,
    get_db,
    get_ingestion_runner,
    get_retriever,
)
from app.api.ingestion_service import IngestionRunner
from app.api.uploads import MIB, receive_upload
from app.core.config import Settings
from app.db import models, repository
from app.schemas.api import DocumentDetail, DocumentStatusResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents")

BUSY_STATUSES = {"queued", "parsing", "ocr_fallback", "indexing"}


def _stored_path(document: models.Document, settings: Settings) -> Path:
    return Path(settings.upload_dir) / f"{document.document_id}.{document.source_type}"


def _detail(document: models.Document, user: models.User) -> DocumentDetail:
    return DocumentDetail(
        document_id=document.document_id,
        filename=document.filename,
        status=document.status,
        error_message=document.error_message,
        source_type=document.source_type,
        created_at=document.created_at,
        uploaded_by_me=document.uploaded_by == user.id,
    )


@router.post("/upload", response_model=DocumentStatusResponse, status_code=202)
async def upload_document(
    request: Request,
    response: Response,
    file: UploadFile,
    user: models.User = Depends(get_current_user),
    runner: IngestionRunner = Depends(get_ingestion_runner),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> DocumentStatusResponse:
    stored = await receive_upload(file, Path(settings.upload_dir), settings.max_upload_mb * MIB)
    document = None
    try:
        existing = await repository.get_active_document_by_hash(db, stored.content_hash)
        if existing is not None and existing.status == "failed":
            # An earlier attempt failed: let the user try the same file again.
            await repository.soft_delete_document(db, existing.document_id)
            _stored_path(existing, settings).unlink(missing_ok=True)
            existing = None
        if existing is None:
            try:
                document = await repository.create_document(
                    db,
                    document_id=stored.document_id,
                    filename=stored.original_filename,
                    content_hash=stored.content_hash,
                    source_type=stored.source_type,
                    status="queued",
                    uploaded_by=user.id,
                )
            except IntegrityError:  # an identical upload arrived at the same moment
                existing = await repository.get_active_document_by_hash(db, stored.content_hash)
                if existing is None:
                    raise
    except BaseException:
        stored.path.unlink(missing_ok=True)
        raise

    if document is None:  # a duplicate: keep the first copy, drop this one
        stored.path.unlink(missing_ok=True)
        response.status_code = 200
        return DocumentStatusResponse(
            document_id=existing.document_id, filename=existing.filename, status="duplicate"
        )

    task = asyncio.create_task(runner.process(document.document_id, stored.path))
    tasks = request.app.state.background_tasks
    tasks.add(task)  # a task nobody refers to can be garbage-collected mid-run
    task.add_done_callback(tasks.discard)
    return DocumentStatusResponse(
        document_id=document.document_id, filename=document.filename, status="queued"
    )


@router.get("", response_model=list[DocumentDetail])
async def list_documents(
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentDetail]:
    return [_detail(document, user) for document in await repository.list_documents(db)]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    document = await repository.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _detail(document, user)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    user: models.User = Depends(get_current_user),
    retriever=Depends(get_retriever),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    document = await repository.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.uploaded_by != user.id:  # also true for documents ingested by script
        raise HTTPException(status_code=403, detail="Only the user who uploaded a document can delete it.")
    if document.status in BUSY_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="The document is still being processed. Try again when it has finished.",
        )
    try:
        await run_in_threadpool(retriever.delete_document, document_id)  # the index first
    except Exception:
        logger.exception("Could not remove document %s from the index", document_id)
        raise HTTPException(
            status_code=503,
            detail="The document could not be removed from the search index. Please try again.",
        ) from None
    await repository.soft_delete_document(db, document_id)
    _stored_path(document, settings).unlink(missing_ok=True)
    return Response(status_code=204)