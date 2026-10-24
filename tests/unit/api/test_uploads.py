import hashlib
import io
import zipfile

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api import uploads
from app.api.uploads import clean_display_name, receive_upload, reject_if_declared_too_large

LIMIT = 1024 * 1024
PDF = b"%PDF-1.4\nsome content"


def _upload(data: bytes, filename: str | None = "report.pdf") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


def _zip_bytes(*members: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member in members:
            archive.writestr(member, "<xml/>")
    return buffer.getvalue()


async def _rejected(upload, folder, status_code, limit=LIMIT):
    with pytest.raises(HTTPException) as info:
        await receive_upload(upload, folder, limit)
    assert info.value.status_code == status_code
    assert list(folder.iterdir()) == []  # nothing is left behind


@pytest.mark.asyncio
async def test_a_valid_pdf_is_stored_under_a_generated_name_with_its_hash(tmp_path):
    stored = await receive_upload(_upload(PDF, "Q3 report.pdf"), tmp_path, LIMIT)
    assert stored.original_filename == "Q3 report.pdf"
    assert stored.source_type == "pdf"
    assert stored.size_bytes == len(PDF)
    assert stored.content_hash == hashlib.sha256(PDF).hexdigest()
    assert len(stored.document_id) == 32
    assert stored.path == tmp_path / f"{stored.document_id}.pdf"
    assert stored.path.read_bytes() == PDF


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../../etc/evil.pdf", "..\\..\\evil.pdf"])
async def test_folders_in_the_filename_never_reach_the_stored_path(tmp_path, name):
    stored = await receive_upload(_upload(PDF, name), tmp_path, LIMIT)
    assert stored.original_filename == "evil.pdf"
    assert stored.path.parent == tmp_path
    assert "evil" not in stored.path.name


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["malware.exe", "notes.txt", "no_extension", "archive.pdf.exe"])
async def test_unsupported_file_types_are_refused_with_415(tmp_path, name):
    await _rejected(_upload(PDF, name), tmp_path, 415)


@pytest.mark.asyncio
async def test_a_pdf_that_is_not_a_pdf_is_refused_and_removed(tmp_path):
    await _rejected(_upload(b"just some text", "fake.pdf"), tmp_path, 415)


@pytest.mark.asyncio
async def test_a_real_docx_is_accepted(tmp_path):
    data = _zip_bytes("[Content_Types].xml", "word/document.xml")
    stored = await receive_upload(_upload(data, "memo.docx"), tmp_path, LIMIT)
    assert stored.source_type == "docx"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04 not really a zip archive",
        _zip_bytes("something/else.xml"),
        b"%PDF-1.4 pretending to be a docx",
    ],
)
async def test_a_docx_that_is_not_a_docx_is_refused_and_removed(tmp_path, data):
    await _rejected(_upload(data, "memo.docx"), tmp_path, 415)


@pytest.mark.asyncio
async def test_a_docx_that_unpacks_to_something_huge_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_DOCX_UNPACKED_BYTES", 3)  # the test file unpacks to 6 bytes
    await _rejected(_upload(_zip_bytes("word/document.xml"), "bomb.docx"), tmp_path, 415)


@pytest.mark.asyncio
async def test_a_csv_is_accepted(tmp_path):
    stored = await receive_upload(_upload(b"a,b\n1,2\n", "data.csv"), tmp_path, LIMIT)
    assert stored.source_type == "csv"


@pytest.mark.asyncio
async def test_a_binary_file_posing_as_csv_is_refused(tmp_path):
    await _rejected(_upload(b"a,b\n\x00\x01\x02", "data.csv"), tmp_path, 415)


@pytest.mark.asyncio
async def test_an_empty_file_is_refused_with_422(tmp_path):
    await _rejected(_upload(b"", "empty.pdf"), tmp_path, 422)


@pytest.mark.asyncio
async def test_a_file_over_the_limit_is_refused_with_413_and_removed(tmp_path):
    data = b"%PDF-" + b"x" * 2000
    await _rejected(_upload(data, "big.pdf"), tmp_path, 413, limit=1000)


@pytest.mark.asyncio
async def test_a_file_of_exactly_the_limit_is_accepted(tmp_path):
    data = b"%PDF-" + b"x" * 995  # 1000 bytes
    stored = await receive_upload(_upload(data, "exact.pdf"), tmp_path, 1000)
    assert stored.size_bytes == 1000


@pytest.mark.asyncio
async def test_a_file_without_a_name_is_refused_with_422(tmp_path):
    await _rejected(_upload(PDF, None), tmp_path, 422)


def test_control_characters_are_removed_from_the_display_name():
    assert clean_display_name("re\x00port\n.pdf") == "report.pdf"


def test_a_very_long_name_is_shortened_but_keeps_its_extension():
    name = clean_display_name("a" * 300 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


@pytest.mark.asyncio
async def test_the_same_file_twice_gets_two_different_stored_names(tmp_path):
    first = await receive_upload(_upload(PDF), tmp_path, LIMIT)
    second = await receive_upload(_upload(PDF), tmp_path, LIMIT)
    assert first.document_id != second.document_id
    assert first.path != second.path
    assert first.content_hash == second.content_hash  # same content, same fingerprint


def test_the_declared_size_is_checked_early_but_only_when_it_is_clearly_too_big():
    reject_if_declared_too_large(None, 1000)  # unknown: nothing to refuse yet
    reject_if_declared_too_large("not-a-number", 1000)
    reject_if_declared_too_large("500", 1000)
    reject_if_declared_too_large(str(1000 + uploads.MULTIPART_OVERHEAD_BYTES), 1000)  # at the edge
    with pytest.raises(HTTPException) as info:
        reject_if_declared_too_large(str(1000 + uploads.MULTIPART_OVERHEAD_BYTES + 1), 1000)
    assert info.value.status_code == 413