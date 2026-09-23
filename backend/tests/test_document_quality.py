import pymupdf
import pytest

from app.api.documents import get_document_service
from app.core.config import Settings
from app.schemas.document import ParsedPage, TextSpan
from app.services.document_quality import detect_quality, remove_repeated_margins
from app.services.document_service import DocumentService


@pytest.fixture
def service(tmp_path):
    return DocumentService(Settings(_env_file=None, materials_root=tmp_path))


def make_document(tmp_path, *, count=5, header=True, footer=True, body_repeat=False, rare=False):
    path = tmp_path / 'quality.pdf'
    with pymupdf.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=600, height=800)
            if header and (not rare or index == 0):
                page.insert_text((40, 25), 'Repeated lecture header', fontsize=8)
            page.insert_text((40, 140), f'Body title {index+1}', fontsize=20)
            page.insert_text((40, 200), 'TCP\nCRC\nMachine Learning', fontsize=14)
            if body_repeat:
                page.insert_text((40, 300), 'Repeated lecture header', fontsize=14)
            if footer:
                page.insert_text((40, 775), 'Example University', fontsize=8)
                page.insert_text((530, 775), f'Page {index+1}', fontsize=8)
        pdf.save(path)
    return path


def test_real_pdf_metadata_raw_and_margin_removal(service, tmp_path):
    path = make_document(tmp_path)
    doc = service.parse(path, 4)
    assert doc.repeated_headers_removed == 5
    assert doc.repeated_footers_removed == 10  # University and visual page number per page.
    assert doc.pages_with_warnings == 5
    with pymupdf.open(path) as pdf:
        for page in doc.pages:
            assert page.raw_text == pdf[page.page_number - 1].get_text('text', sort=True)
            assert page.cleaned_text == page.text
            assert 'Repeated lecture header' in page.raw_text
            assert 'Example University' not in page.text
            assert f'Page {page.page_number}' not in page.text
            assert 'Repeated lecture header' not in page.text
            assert 'Machine Learning' in page.text and 'TCP' in page.text
            assert f'Body title {page.page_number}' in page.text
            assert all(s.font and s.size > 0 and len(s.bbox) == 4 and len(s.origin) == 2 for s in page.spans)
    chunks = service.chunk(doc)
    assert [c.page_number for c in chunks] == [1, 2, 3, 4, 5]
    assert [c.chunk_index for c in chunks] == list(range(5))
    assert all(c.content == doc.pages[c.page_number-1].text for c in chunks)


def test_repeated_body_and_ambiguous_header_preserved(service, tmp_path):
    doc = service.parse(make_document(tmp_path, body_repeat=True), 1)
    assert doc.repeated_headers_removed == 0
    assert all(p.text.count('Repeated lecture header') == 2 for p in doc.pages)


@pytest.mark.parametrize('options', [{'count':2}, {'rare':True}])
def test_insufficient_repetition_preserved(service, tmp_path, options):
    doc = service.parse(make_document(tmp_path, **options), 1)
    assert doc.repeated_headers_removed == 0
    assert 'Repeated lecture header' in doc.pages[0].text


def span(text, x, baseline, size=20, flags=0, line_index=0):
    return TextSpan(text=text, bbox=(x,baseline-size,x+20,baseline+2), origin=(x,baseline),
                    size=size,font='Example',flags=flags,line_index=line_index)


@pytest.mark.parametrize('baseline', [94, 106])
def test_superscript_and_subscript_warn_without_rewrite(baseline):
    page = ParsedPage(page_number=1, raw_text='x2(N-1)', text='x2(N-1)',
                      spans=[span('x',20,100),span('2(N-1)',41,baseline,size=13)])
    detect_quality(page)
    warning = next(w for w in page.warnings if w.code == 'suspicious_formula_layout')
    assert warning.span_indices == [1]
    assert page.text == page.raw_text == 'x2(N-1)'


def test_superscript_flag_and_displaced_symbol():
    page=ParsedPage(page_number=1, raw_text='a . b',text='a . b',
                    spans=[span('a',20,100),span('.',41,96,size=13,flags=1),span('b',62,100)])
    detect_quality(page)
    assert {w.code for w in page.warnings} == {'suspicious_formula_layout','unusual_symbol_position'}
    assert page.text == 'a . b'


@pytest.mark.parametrize('spans', [
    [span('normal',20,100),span('small',41,100,size=13)],
    [span('title',20,100),span('body',20,200,size=13,line_index=1)],
    [span('normal',20,100),span('far away',400,94,size=13)],
])
def test_font_size_alone_does_not_trigger_formula_warning(spans):
    page=ParsedPage(page_number=1, raw_text='normal text',text='normal text',spans=spans)
    detect_quality(page)
    assert not page.warnings


def test_actual_pdf_superscript_and_subscript(service,tmp_path):
    path=tmp_path/'formula.pdf'
    with pymupdf.open() as pdf:
        p=pdf.new_page()
        p.insert_text((50,100),'x',fontsize=20)
        p.insert_text((61,94),'2',fontsize=12)
        p.insert_text((50,150),'t',fontsize=20)
        p.insert_text((58,154),'0',fontsize=12)
        pdf.save(path)
    doc=service.parse(path,1)
    assert doc.pages_with_formula_warnings == 1
    evidence={s.text.strip() for w in doc.pages[0].warnings for i in w.span_indices for s in [doc.pages[0].spans[i]]}
    assert {'2','0'} <= evidence
    assert '^' not in doc.pages[0].text


def test_encoding_warning_counts_and_preserves_characters():
    page=ParsedPage(page_number=1,raw_text='中文 \ufffd + \ufffd',text='中文 \ufffd + \ufffd')
    detect_quality(page)
    assert page.warnings[0].code == 'encoding_warning'
    assert page.warnings[0].occurrences == 2
    assert page.text == page.raw_text


def test_blank_page_warnings(service,tmp_path):
    path=tmp_path/'blank.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    doc=service.parse(path,1)
    assert {w.code for w in doc.pages[0].warnings} == {'empty_text','possible_scanned_page'}
    assert doc.possible_scanned_pdf


def test_quality_summary_api(client,db,graph,service,tmp_path):
    resource=graph[-1]
    resource.local_path=str(make_document(tmp_path))
    db.commit()
    client.app.dependency_overrides[get_document_service]=lambda:service
    result=client.post(f'/api/resources/{resource.id}/parse')
    assert result.status_code == 200
    data=result.json()
    assert data['pages_with_warnings'] == 5
    assert data['pages_with_formula_warnings'] == 0
    assert data['pages_with_encoding_warnings'] == 0
    assert data['repeated_headers_removed'] == 5
    assert data['repeated_footers_removed'] == 10
    assert [p['page_number'] for p in data['page_warnings']] == [1,2,3,4,5]
    assert 'spans' not in data and 'pages' not in data
    chunks=client.get(f'/api/resources/{resource.id}/chunks').json()
    assert [c['page_number'] for c in chunks] == [1,2,3,4,5]
    assert all('Example University' not in c['content'] for c in chunks)


def test_margin_position_and_font_size_are_required(service,tmp_path):
    path=tmp_path/'body.pdf'
    with pymupdf.open() as pdf:
        for n in range(5):
            p=pdf.new_page(width=600,height=800)
            p.insert_text((40,40),'Machine Learning',fontsize=20)
            p.insert_text((40,200),'Example University',fontsize=14)
            p.insert_text((40,775),'CRC',fontsize=8)
        pdf.save(path)
    doc=service.parse(path,1)
    assert doc.repeated_headers_removed == doc.repeated_footers_removed == 0
    assert all('Machine Learning' in p.text and 'CRC' in p.text and 'Example University' in p.text for p in doc.pages)


def test_wrong_visual_page_number_preserved(service,tmp_path):
    path=tmp_path/'numbers.pdf'
    with pymupdf.open() as pdf:
        for n in range(5):
            p=pdf.new_page(width=600,height=800)
            p.insert_text((40,200),'Body text',fontsize=20)
            p.insert_text((530,775),str(100+n),fontsize=8)
        pdf.save(path)
    doc=service.parse(path,1)
    assert doc.repeated_footers_removed == 0
    assert all(str(99+p.page_number) in p.text for p in doc.pages)


def test_right_aligned_page_numbers_across_digit_widths(service,tmp_path):
    path=tmp_path/'right-aligned.pdf'
    with pymupdf.open() as pdf:
        for n in range(12):
            p=pdf.new_page(width=600,height=800)
            p.insert_text((40,200),'Body text',fontsize=20)
            text=f'Page {n+1}'
            width=pymupdf.get_text_length(text,fontsize=8)
            p.insert_text((570-width,775),text,fontsize=8)
        pdf.save(path)
    doc=service.parse(path,1)
    assert doc.repeated_footers_removed == 12
    assert all(f'Page {p.page_number}' not in p.text for p in doc.pages)


def test_quality_summary_encoding_and_raw_serialization():
    from app.schemas.document import ParsedDocument,ParseSummary
    page=ParsedPage(page_number=1,raw_text='\ufffd\ufffd',text='\ufffd\ufffd')
    detect_quality(page)
    doc=ParsedDocument(resource_id=1,filename='test.pdf',pages=[page])
    summary=ParseSummary(**doc.model_dump(exclude={'pages','metadata'}),chunks_created=1,status='parsed')
    assert summary.pages_with_encoding_warnings == 1
    assert summary.pages_with_warnings == 1
    assert summary.page_warnings[0].warnings[0].occurrences == 2
    restored=ParsedDocument.model_validate_json(doc.model_dump_json())
    assert restored.pages[0].raw_text == '\ufffd\ufffd'
    assert restored.pages[0].cleaned_text == '\ufffd\ufffd'
