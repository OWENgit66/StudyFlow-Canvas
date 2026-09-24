from contextlib import contextmanager
import io
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect, text

from app.core.config import Settings
from app.core.database import build_engine
from app.core.schema_upgrade import upgrade_sync_columns
from app.services import external_pdf as external
from app.services.material_paths import MaterialContext

URL='https://public.example.test/lecture.pdf'
CONTENT=b'%PDF-synthetic-test'
HEADERS={'content-type':'application/pdf','content-length':str(len(CONTENT)),'etag':'"v1"'}


class Response:
    def __init__(self,headers=None,body=CONTENT,status=200):
        self.headers=HEADERS.copy() if headers is None else headers
        self.body=io.BytesIO(body)
        self.status=status
    def getheader(self,name,default=None):return self.headers.get(name.lower(),default)
    def read(self,n):return self.body.read(n)


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(external.socket,'getaddrinfo',lambda host,*a,**kw:[(2,1,6,'',('93.184.216.34',443))])
    return external.ExternalPDFClient(Settings(_env_file=None,materials_root=tmp_path/'materials'))


def transport(client,monkeypatch,handler):
    calls=[]
    @contextmanager
    def opened(url,method):
        external.public_target(url)
        calls.append((url,method))
        yield handler(url,method)
    monkeypatch.setattr(client,'_open',opened)
    return calls


@pytest.mark.parametrize('address',['127.0.0.1','10.1.2.3','169.254.169.254','192.168.0.1','::1','fc00::1','224.0.0.1','::ffff:127.0.0.1'])
def test_private_and_nonpublic_addresses_rejected(monkeypatch,address):
    monkeypatch.setattr(external.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(address,443))])
    with pytest.raises(external.ExternalPDFError): external.public_target(URL)


@pytest.mark.parametrize('url',['http://public.test/a.pdf','https://user:pass@public.test/a.pdf','https://public.test:8443/a.pdf','https://public.test/\na.pdf'])
def test_unsafe_urls_rejected_before_network(client,url):
    with pytest.raises((external.ExternalPDFError,ValueError)): external.public_target(url)


def test_mixed_dns_response_fails_closed(monkeypatch):
    monkeypatch.setattr(external.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(ip,443)) for ip in ['93.184.216.34','127.0.0.1']])
    with pytest.raises(external.ExternalPDFError): external.public_target(URL)


def test_transport_pins_ip_and_preserves_verified_tls_hostname(monkeypatch):
    sock=Mock();connect=Mock(return_value=sock)
    monkeypatch.setattr(external.socket,'create_connection',connect)
    connection=external.PinnedHTTPSConnection('public.example.test','93.184.216.34',20)
    context=Mock();connection._context=context
    connection.connect()
    connect.assert_called_once_with(('93.184.216.34',443),20)
    context.wrap_socket.assert_called_once_with(sock,server_hostname='public.example.test')


def test_transport_sends_only_read_methods_no_canvas_credentials(client,monkeypatch):
    response=Mock(status=200)
    conn=Mock();conn.getresponse.return_value=response
    monkeypatch.setattr(external,'PinnedHTTPSConnection',Mock(return_value=conn))
    with client._open(URL,'HEAD'):pass
    conn.request.assert_called_once_with('HEAD','/lecture.pdf',headers={'Accept':'application/pdf','Accept-Encoding':'identity'})
    conn.close.assert_called_once()


def test_head_discovery_no_body_then_validated_download_same_storage(client,monkeypatch):
    head=Response();head.read=Mock(side_effect=AssertionError('HEAD must not read document'))
    calls=transport(client,monkeypatch,lambda u,m:head if m=='HEAD' else Response())
    meta=client.metadata(URL)
    assert calls==[(URL,'HEAD')] and meta.filename=='lecture.pdf'
    head.read.assert_not_called()
    path=client.download(meta,MaterialContext(2026,'S1','TEST','Synthetic course','Module'))
    assert path.read_bytes()==CONTENT and 'Module' in str(path)
    assert calls[-1]==(URL,'GET')


@pytest.mark.parametrize('headers',[
    {**HEADERS,'content-type':'text/html'}, {**HEADERS,'content-length':'bad'},
    {**HEADERS,'content-length':'0'}, {**HEADERS,'content-length':str(200_000_000)},
    {**HEADERS,'etag':''}, {**HEADERS,'etag':'W/"weak"'},
    {**HEADERS,'content-encoding':'gzip'},
])
def test_metadata_requires_pdf_size_and_revision(client,monkeypatch,headers):
    transport(client,monkeypatch,lambda u,m:Response(headers))
    with pytest.raises(external.ExternalPDFError):client.metadata(URL)


def test_last_modified_fallback_and_stable_url_identity(client,monkeypatch):
    headers={**HEADERS,'etag':'','last-modified':'Tue, 01 Sep 2026 10:00:00 GMT'}
    transport(client,monkeypatch,lambda u,m:Response(headers))
    first=client.metadata(URL+'#page=2')
    assert first.source_key==client.metadata(URL).source_key
    headers['last-modified']='Wed, 02 Sep 2026 10:00:00 GMT'
    assert first.revision!=client.metadata(URL).revision


def test_redirect_revalidates_destination_and_blocks_downgrade(client,monkeypatch):
    calls=transport(client,monkeypatch,lambda u,m:Response({'location':'http://public.test/a.pdf'},status=302))
    with pytest.raises((ValueError,external.ExternalPDFError)):client.metadata(URL)
    assert len(calls)==1


def test_redirect_loop_bounded(client,monkeypatch):
    calls=transport(client,monkeypatch,lambda u,m:Response({'location':URL},status=302))
    with pytest.raises(external.ExternalPDFError):client.metadata(URL)
    assert len(calls)==1


def test_timeout_is_safe_and_not_retried(client,monkeypatch):
    conn=Mock();conn.request.side_effect=TimeoutError('PRIVATE_URL_OR_QUERY')
    monkeypatch.setattr(external,'PinnedHTTPSConnection',Mock(return_value=conn))
    with pytest.raises(external.ExternalPDFError) as error:client.metadata(URL)
    assert 'PRIVATE_URL_OR_QUERY' not in str(error.value)
    assert conn.request.call_count==1
    conn.close.assert_called_once()


@pytest.mark.parametrize('changed', ['revision','not_pdf','short','long'])
def test_bad_download_never_publishes_or_replaces_material(client,monkeypatch,changed,tmp_path):
    headers=HEADERS.copy();body=CONTENT
    if changed=='revision':headers['etag']='"v2"'
    if changed=='not_pdf':body=b'HTML-not-a-PDF-file'
    if changed=='short':body=CONTENT[:-3]
    if changed=='long':body=CONTENT+b'extra'
    transport(client,monkeypatch,lambda u,m:Response() if m=='HEAD' else Response(headers,body))
    meta=client.metadata(URL)
    with pytest.raises(external.CanvasDownloadError):client.download(meta,MaterialContext(2026,'S1','TEST','Synthetic','Module'))
    assert not list(tmp_path.rglob('*.pdf'))
    assert not list(tmp_path.rglob('*.partial'))


def test_additive_external_identity_migration_preserves_existing_rows():
    engine=build_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE resources (id INTEGER PRIMARY KEY, canvas_file_id INTEGER)'))
        conn.execute(text('INSERT INTO resources VALUES (1, 123)'))
    upgrade_sync_columns(engine);upgrade_sync_columns(engine)
    assert {'external_source_key','external_revision'} <= {c['name'] for c in inspect(engine).get_columns('resources')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT id, canvas_file_id, external_source_key, external_revision FROM resources')).one()==(1,123,None,None)
    engine.dispose()
