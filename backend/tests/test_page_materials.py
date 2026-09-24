import httpx2 as httpx
import pytest

from app.schemas.canvas import CanvasModuleItem
from app.services.canvas_errors import CanvasError
from app.services.canvas_service import CanvasService
from app.services.page_materials import extract_material_links
from test_canvas_service import BASE, TOKEN, settings


def extract(html):
    return extract_material_links(html, BASE, 1, 'week-one')


@pytest.mark.parametrize('locator,path', [('week-one', 'week-one'), (7, 'page_id:7'), ('7', '7')])
def test_get_page_uses_official_get_api(locator, path):
    def handle(request):
        assert request.method == 'GET'
        assert request.url.path == f'/api/v1/courses/1/pages/{path}'
        assert request.headers['Authorization'] == f'Bearer {TOKEN}'
        return httpx.Response(200, json={'page_id': 7, 'url': 'week-one', 'title': 'Week one', 'body': '<p>Hello</p>'})
    with CanvasService(settings(), transport=httpx.MockTransport(handle)) as canvas:
        assert canvas.get_page(1, locator).body == '<p>Hello</p>'
    item = CanvasModuleItem(id=1, module_id=1, title='Page', type='Page', page_url='week-one')
    assert item.page_url == 'week-one' and item.canvas_file_id is None


@pytest.mark.parametrize('locator', ['', '../files/1', 'https://evil.test', '%2e%2e', 'page?x=1', True])
def test_page_locator_cannot_escape_endpoint(locator):
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: pytest.fail('Unexpected request'))) as canvas:
        with pytest.raises((CanvasError, ValueError)):
            canvas.get_page(1, locator)


@pytest.mark.parametrize('payload', [
    {'page_id': 1, 'url': 'x', 'title': 'Page', 'locked_for_user': True, 'body': 'private'},
    {'page_id': 1, 'url': 'x', 'title': 'Page'},
    {'page_id': 'invalid', 'url': 'x', 'title': 'Page', 'body': 'text'},
])
def test_locked_missing_or_invalid_page_body_fails_safely(payload):
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as canvas:
        with pytest.raises(CanvasError): canvas.get_page(1, 'x')


@pytest.mark.parametrize('href', ['/courses/1/files/31/download?download_frd=1', '/files/31/download',
    '/api/v1/files/31', '/api/v1/courses/1/files/31', '/courses/1/files?preview=31', '//canvas.example.test/files/31#preview'])
def test_canonical_canvas_link_forms(href):
    links, unsupported = extract(f'<a href="{href}">Slides</a>')
    assert [link.canvas_file_id for link in links] == [31]
    assert not unsupported


def test_html_parser_attributes_entities_relative_links_and_multiple_files():
    links, unsupported = extract('''<a HREF="/ignored" data-api-endpoint="/api/v1/files/1" data-api-returntype="File">A</a>
        <a href='../files/2/download'>B</a><a href="https://public.test/slides.pdf?a=1&amp;b=2#page=3">PDF</a>''')
    assert [link.canvas_file_id for link in links[:2]] == [1, 2]
    assert links[2].external_url == 'https://public.test/slides.pdf?a=1&b=2'
    assert not unsupported


def test_inert_html_no_script_form_iframe_actions_or_cross_origin_canvas_ids():
    links, unsupported = extract('''<script><a href="/files/1">no</a></script>
      <form action="/delete"><a href="/files/2">no</a></form><iframe src="/files/3"></iframe>
      <a href="javascript:alert(1)">no</a><a href="https://evil.test/files/4">no</a>
      <a href="https://drive.google.com/file/d/example/view">unsupported</a>
      <a href="#section">jump</a><a href="/courses/1/pages/other">no recursion</a>''')
    assert not links and len(unsupported) == 4


def test_page_limits_fail_without_partial_results():
    with pytest.raises(CanvasError): extract('x'*2_000_001)
    with pytest.raises(CanvasError): extract('<a href="/files/1">x</a>'*2001)


def test_file_id_attribute_requires_canvas_origin():
    links,unsupported=extract('<a href="/attachment" data-file-id="31">Canvas</a><a href="https://other.test/attachment" data-file-id="31">Other</a>')
    assert [link.canvas_file_id for link in links]==[31] and len(unsupported)==1


@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_page_request_errors_use_existing_safe_handling(status):
    with CanvasService(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(status,text='PRIVATE_PAGE_BODY'))) as canvas:
        with pytest.raises(CanvasError) as error:canvas.get_page(1,'page')
        assert 'PRIVATE_PAGE_BODY' not in str(error.value)
