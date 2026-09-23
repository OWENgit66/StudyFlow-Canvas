from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.documents import get_document_service
from app.core.config import Settings
from app.models import DocumentChunk, Resource
from app.models.common import ResourceStatus
from app.schemas.document import ParsedDocument, ParsedPage
from app.services.document_chunking import clean_text, split_page
from app.services.document_errors import DocumentError, DocumentDatabaseError
from app.services.document_processing import process_resource
from app.services.document_service import DocumentService


@pytest.fixture
def documents(tmp_path):
    return DocumentService(Settings(_env_file=None, materials_root=tmp_path,
                                    document_chunk_size=200, document_chunk_overlap=30))


@pytest.fixture
def make_pdf(tmp_path):
    def create(pages, name="lecture.pdf", encrypted=False):
        path = tmp_path / name
        with pymupdf.open() as pdf:
            pdf.set_metadata({"title": "Test lecture"})
            for text in pages:
                page = pdf.new_page()
                if text:
                    page.insert_text((50, 60), text, fontsize=11)
            options = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": "test-password"} if encrypted else {}
            pdf.save(path, **options)
        return path
    return create


def stored(db, resource_id):
    return list(db.scalars(select(DocumentChunk).where(DocumentChunk.resource_id == resource_id)
                          .order_by(DocumentChunk.chunk_index)))


def attach(db, graph, path):
    resource = graph[-1]
    resource.local_path = str(path)
    resource.sync_status = ResourceStatus.downloaded
    db.commit()
    return resource


def test_pdf_pages_metadata_and_empty_page(documents, make_pdf):
    doc = documents.parse(make_pdf(["First page", "", "Last page"]), 7)
    assert doc.total_pages == 3
    assert doc.pages_with_text == 2
    assert doc.empty_pages == 1
    assert doc.pages[1].has_text is False
    assert [p.page_number for p in doc.pages] == [1, 2, 3]
    assert doc.pages[0].text == "First page"
    assert doc.metadata["title"] == "Test lecture"
    assert doc.total_characters == len("First pageLast page")
    assert not doc.possible_scanned_pdf and doc.warnings


def test_actual_unicode_pdf(documents, tmp_path):
    path = tmp_path / "unicode.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 60), "中文课程，网络。", fontname="china-s")
        page.insert_text((50, 100), "EF = ES + Duration; for i in range(n):")
        pdf.save(path)
    doc = documents.parse(path, 1)
    assert "中文课程" in doc.pages[0].text
    assert "EF = ES + Duration" in doc.pages[0].text
    assert "for i in range(n):" in doc.pages[0].text


def test_cleaning_preserves_knowledge():
    source = "\r\nTitle  \r\n\r\n\r\n• 中文 — α ≤ β\r\nEF = ES + Duration\r\n    for i in range(n):  \r\n        print(i)\x00\r\n"
    assert clean_text(source) == "Title\n\n• 中文 — α ≤ β\nEF = ES + Duration\n    for i in range(n):\n        print(i)"


@pytest.mark.parametrize("size,overlap", [(200, 30), (101, 0), (100, 99)])
def test_long_paragraph_bounded_complete_and_overlap(size, overlap):
    text = "".join(chr(0x4e00 + i) for i in range(1000))
    chunks = list(split_page(text, size, overlap))
    assert all(0 < len(c) <= size for c in chunks)
    assert chunks[0].startswith(text[0]) and chunks[-1].endswith(text[-1])
    covered = set()
    for chunk in chunks:
        start = text.index(chunk)
        covered.update(range(start, start + len(chunk)))
    assert covered == set(range(len(text)))
    if overlap:
        assert chunks[0][-overlap:] == chunks[1][:overlap]


@pytest.mark.parametrize("separator", ["\n\n", "\n", ". ", " "])
def test_natural_boundaries(separator):
    text = "A" * 65 + separator + "B" * 70
    chunks = list(split_page(text, 100, 10))
    assert chunks[0] == "A" * 65 + separator


def test_chunks_preserve_pages_indices_unicode_and_indentation(documents):
    page1 = "    for i in range(n):\n        print(i)\n• 中文 — ∑ α ≤ β\n"
    page3 = "Network protocol explanation. " * 40
    doc = ParsedDocument(resource_id=23, filename="test.pdf", pages=[
        ParsedPage(page_number=1, text=page1), ParsedPage(page_number=2, text=""),
        ParsedPage(page_number=3, text=page3)])
    chunks = documents.chunk(doc)
    assert chunks[0].content == page1
    assert {c.page_number for c in chunks} == {1, 3}
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.resource_id == 23 for c in chunks)
    assert all(c.content in (page1 if c.page_number == 1 else page3) for c in chunks)


@pytest.mark.parametrize("case", ["missing", "empty", "fake", "corrupt", "extension", "outside", "mime"])
def test_invalid_files(documents, tmp_path, make_pdf, case):
    path = tmp_path / "bad.pdf"
    file_type = "pdf"
    if case == "empty":
        path.touch()
    elif case == "fake":
        path.write_text("not pdf")
    elif case == "corrupt":
        path.write_bytes(b"%PDF-1.7\ncorrupted data")
    elif case == "extension":
        path = make_pdf(["text"], "lecture.txt")
    elif case == "outside":
        path = tmp_path.parent / "outside.pdf"
    elif case == "mime":
        path = make_pdf(["text"])
        file_type = "docx"
    with pytest.raises(DocumentError):
        documents.parse(path, 1, file_type)


def test_encrypted_pdf(documents, make_pdf):
    with pytest.raises(DocumentError, match="Password"):
        documents.parse(make_pdf(["secret"], encrypted=True), 1)


@pytest.mark.parametrize("pages", [["", ""], ["Text"] + [""] * 9])
def test_scanned_heuristic(documents, make_pdf, pages):
    doc = documents.parse(make_pdf(pages), 1)
    assert doc.possible_scanned_pdf
    assert any("OCR" in warning for warning in doc.warnings)


def test_settings_reject_invalid_overlap():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, document_chunk_size=200, document_chunk_overlap=200)


def test_persist_reprocess_and_isolate(db, graph, documents, make_pdf):
    resource = attach(db, graph, make_pdf(["First page", "Second page"]))
    other = Resource(week=graph[2], filename="other.pdf", file_type="pdf")
    db.add(other)
    db.flush()
    db.add(DocumentChunk(resource_id=other.id, page_number=1, chunk_index=0, content="Keep me"))
    db.commit()
    for _ in range(2):
        result = process_resource(db, resource.id, documents)
        assert result.status == "parsed" and result.chunks_created == 2
        chunks = stored(db, resource.id)
        assert [(c.page_number, c.chunk_index, c.content) for c in chunks] == [(1, 0, "First page"), (2, 1, "Second page")]
        assert resource.sync_status == ResourceStatus.parsed
    assert stored(db, other.id)[0].content == "Keep me"


@pytest.mark.parametrize("failure", ["parse", "insert", "commit", "scanned"])
def test_failure_preserves_previous_chunks(db, graph, documents, make_pdf, monkeypatch, failure):
    resource = attach(db, graph, make_pdf(["New text"] if failure != "scanned" else [""]))
    db.add(DocumentChunk(resource_id=resource.id, page_number=1, chunk_index=0, content="Original text"))
    db.commit()
    if failure == "parse":
        Path(resource.local_path).write_bytes(b"broken")
        with pytest.raises(DocumentError):
            process_resource(db, resource.id, documents)
    elif failure == "scanned":
        result = process_resource(db, resource.id, documents)
        assert result.status == "needs_ocr" and result.chunks_created == 0
    else:
        method = "flush" if failure == "insert" else "commit"
        original = getattr(db, method)
        def fail(*args, **kwargs):
            # Let deletion and insertion run, then simulate failed flush/commit.
            if failure == "insert" and not db.new:
                return original(*args, **kwargs)
            raise SQLAlchemyError("simulated database failure")
        monkeypatch.setattr(db, method, fail)
        with pytest.raises(DocumentDatabaseError):
            process_resource(db, resource.id, documents)
        monkeypatch.setattr(db, method, original)
    assert [c.content for c in stored(db, resource.id)] == ["Original text"]
    db.refresh(resource)
    assert resource.sync_status == (ResourceStatus.failed if failure in {"parse", "scanned"} else ResourceStatus.downloaded)


def test_parse_and_read_api(client, db, graph, documents, make_pdf):
    resource = attach(db, graph, make_pdf(["First page", "Second page"]))
    client.app.dependency_overrides[get_document_service] = lambda: documents
    response = client.post(f"/api/resources/{resource.id}/parse")
    assert response.status_code == 200
    assert response.json()["chunks_created"] == 2
    response = client.get(f"/api/resources/{resource.id}/chunks?offset=1&limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["page_number"] == 2
    assert response.json()[0]["chunk_index"] == 1
    assert response.json()[0]["content"] == "Second page"
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("endpoint,method", [("parse", "post"), ("chunks", "get")])
def test_resource_missing_api(client, documents, endpoint, method):
    client.app.dependency_overrides[get_document_service] = lambda: documents
    response = getattr(client, method)(f"/api/resources/9999/{endpoint}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


def test_no_local_path_api(client, graph, documents):
    client.app.dependency_overrides[get_document_service] = lambda: documents
    response = client.post(f"/api/resources/{graph[-1].id}/parse")
    assert response.status_code == 422
    assert "download" in response.json()["detail"]["message"]


def test_unicode_and_indentation_database_api(client, db, graph):
    content = "    中文 — ∑ α ≤ β\n    for i in range(n):\n        x += 1\n"
    db.add(DocumentChunk(resource_id=graph[-1].id, page_number=3, chunk_index=0, content=content))
    db.commit()
    response = client.get(f"/api/resources/{graph[-1].id}/chunks")
    assert response.json()[0]["content"] == content


@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=201"])
def test_chunk_pagination_validation(client, graph, query):
    assert client.get(f"/api/resources/{graph[-1].id}/chunks?{query}").status_code == 422


def test_scanned_api_is_not_ordinary_success(client, db, graph, documents, make_pdf):
    resource = attach(db, graph, make_pdf(["", ""]))
    client.app.dependency_overrides[get_document_service] = lambda: documents
    result = client.post(f"/api/resources/{resource.id}/parse")
    assert result.status_code == 200
    assert result.json()["status"] == "needs_ocr"
    assert result.json()["possible_scanned_pdf"] is True
    assert result.json()["chunks_created"] == 0
    db.refresh(resource)
    assert resource.sync_status == ResourceStatus.failed


def test_pdf_extraction_error_is_safe(documents, make_pdf, monkeypatch):
    path = make_pdf(["text"])
    def fail(*args, **kwargs):
        raise RuntimeError("private source details")
    monkeypatch.setattr(pymupdf.Page, "get_text", fail)
    with pytest.raises(DocumentError) as error:
        documents.parse(path, 1)
    assert "private" not in str(error.value)


def test_database_api_error_is_safe(client, db, graph, documents, make_pdf, monkeypatch):
    resource = attach(db, graph, make_pdf(["text"]))
    client.app.dependency_overrides[get_document_service] = lambda: documents
    def fail(*args, **kwargs):
        raise SQLAlchemyError("private database details")
    monkeypatch.setattr("app.services.document_processing.replace_chunks", fail)
    result = client.post(f"/api/resources/{resource.id}/parse")
    assert result.status_code == 500
    assert result.json()["detail"]["code"] == "document_database_error"
    assert "private" not in result.text


def test_partial_insert_rollback(db, graph, documents, make_pdf, monkeypatch):
    from app.services import document_processing
    resource = attach(db, graph, make_pdf(["New page one", "New page two"]))
    db.add(DocumentChunk(resource_id=resource.id, page_number=1, chunk_index=0, content="Original"))
    db.commit()
    original_replace = document_processing.replace_chunks
    def partial_then_fail(session, resource_id, chunks):
        original_replace(session, resource_id, chunks[:1])
        raise SQLAlchemyError("second insert failed")
    monkeypatch.setattr(document_processing, "replace_chunks", partial_then_fail)
    with pytest.raises(DocumentDatabaseError):
        process_resource(db, resource.id, documents)
    assert [chunk.content for chunk in stored(db, resource.id)] == ["Original"]
