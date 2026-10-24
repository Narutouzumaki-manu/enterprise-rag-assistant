import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

MIB = 1024 * 1024
ALLOWED_SUFFIXES = {".pdf": "pdf", ".docx": "docx", ".csv": "csv"}
READ_CHUNK_BYTES = MIB
MULTIPART_OVERHEAD_BYTES = MIB  # form framing around the file inside the request body
MAX_NAME_CHARS = 255
MAX_DOCX_UNPACKED_BYTES = 200 * MIB  # guard against "zip bombs"


@dataclass(frozen=True)
class StoredUpload:
    document_id: str  # random, unique; also the stem of the stored file
    original_filename: str  # for display only; never used in a path
    source_type: str  # "pdf" | "docx" | "csv"
    path: Path
    content_hash: str  # SHA-256 of the file bytes
    size_bytes: int


def _limit_text(max_bytes: int) -> str:
    return f"{max_bytes // MIB} MB" if max_bytes >= MIB else f"{max_bytes} bytes"


def clean_display_name(raw: str | None) -> str:
    name = PureWindowsPath(raw or "").name  # drops any folders, whether written with / or \
    name = "".join(ch for ch in name if ch.isprintable()).strip()  # drops control characters
    if len(name) > MAX_NAME_CHARS:
        suffix = PureWindowsPath(name).suffix
        name = name[: MAX_NAME_CHARS - len(suffix)] + suffix
    return name


def _content_mismatch() -> HTTPException:
    return HTTPException(status_code=415, detail="The file content does not match its type.")


def _check_content_start(source_type: str, first_chunk: bytes) -> None:
    if source_type == "pdf" and b"%PDF-" not in first_chunk[:1024]:
        raise _content_mismatch()
    if source_type == "docx" and not first_chunk.startswith(b"PK\x03\x04"):
        raise _content_mismatch()
    if source_type == "csv" and b"\x00" in first_chunk:
        raise _content_mismatch()


def _check_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        raise _content_mismatch() from None
    if "word/document.xml" not in names:
        raise _content_mismatch()
    if unpacked > MAX_DOCX_UNPACKED_BYTES:
        raise HTTPException(status_code=415, detail="The file is too large once unpacked.")


def reject_if_declared_too_large(content_length: str | None, max_bytes: int) -> None:
    """A cheap early refusal from the Content-Length header. Not trusted on its own:
    receive_upload counts the real bytes."""
    if content_length is None or not content_length.isdigit():
        return
    if int(content_length) > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"The file is larger than {_limit_text(max_bytes)}."
        )


async def receive_upload(upload: UploadFile, upload_dir: Path, max_bytes: int) -> StoredUpload:
    name = clean_display_name(upload.filename)
    if not name:
        raise HTTPException(status_code=422, detail="The file has no name.")
    source_type = ALLOWED_SUFFIXES.get(PureWindowsPath(name).suffix.lower())
    if source_type is None:
        raise HTTPException(status_code=415, detail="Only PDF, DOCX and CSV files are accepted.")

    upload_dir.mkdir(parents=True, exist_ok=True)
    document_id = uuid4().hex
    path = upload_dir / f"{document_id}.{source_type}"  # nothing here comes from the client
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "wb") as handle:
            while chunk := await upload.read(READ_CHUNK_BYTES):
                if size == 0:
                    _check_content_start(source_type, chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The file is larger than {_limit_text(max_bytes)}.",
                    )
                digest.update(chunk)
                await run_in_threadpool(handle.write, chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The file is empty.")
        if source_type == "docx":
            await run_in_threadpool(_check_docx, path)
    except BaseException:  # includes cancellation when the client disconnects
        path.unlink(missing_ok=True)  # the handle is already closed here
        raise

    return StoredUpload(
        document_id=document_id,
        original_filename=name,
        source_type=source_type,
        path=path,
        content_hash=digest.hexdigest(),
        size_bytes=size,
    )