"""Bounded public-HTTPS PDF access, without Canvas auth, cookies or proxies.

Pin a vetted public address for each connection while verifying TLS against the
original hostname. Revalidate every redirect; DNS is not resolved a second time
by the HTTP client. HEAD discovery never fetches the document body.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from hashlib import sha256
from http.client import HTTPSConnection, HTTPException
from ipaddress import ip_address
from pathlib import PurePosixPath
import socket
from urllib.parse import unquote, urljoin, urlsplit

from app.services.canvas_errors import CanvasDownloadError
from app.services.canvas_storage import save_stream
from app.services.material_paths import build_material_path, material_root
from app.services.page_materials import external_key, normalized_url


class ExternalPDFError(CanvasDownloadError):
    pass


@dataclass(frozen=True)
class ExternalPDF:
    source_key: str
    revision: str
    filename: str
    size: int
    url: str = field(repr=False)


def public_target(url):
    url = normalized_url(url, url)
    parsed = urlsplit(url)
    if parsed.port not in {None, 443}:
        raise ExternalPDFError('External PDF must use standard HTTPS.')
    addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ip_address(ip).is_global or ip_address(ip).is_multicast for ip in addresses):
        raise ExternalPDFError('External PDF host is not a public address.')
    return parsed, sorted(addresses)[0]


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, hostname, address, timeout):
        super().__init__(hostname, port=443, timeout=timeout)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class ExternalPDFClient:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def _open(self, url, method):
        connection = None
        try:
            parsed, address = public_target(url)
            connection = PinnedHTTPSConnection(parsed.hostname, address, self.settings.canvas_timeout_seconds)
            target = parsed.path + ('?' + parsed.query if parsed.query else '')
            connection.request(method, target, headers={'Accept': 'application/pdf', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            try:
                yield response
            finally:
                response.close()
        except (OSError, HTTPException, ValueError, UnicodeError):
            raise ExternalPDFError('External PDF request failed or was unsafe.') from None
        finally:
            if connection:
                connection.close()

    @contextmanager
    def _follow(self, url, method):
        seen = set()
        for _ in range(6):
            if url in seen:
                raise ExternalPDFError('External PDF redirect loop.')
            seen.add(url)
            with self._open(url, method) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader('Location')
                    if not location:
                        raise ExternalPDFError('External PDF redirect has no destination.')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ExternalPDFError('External PDF is unavailable.')
                yield response
                return
        raise ExternalPDFError('External PDF exceeds the redirect limit.')

    def _properties(self, response):
        content_type = (response.getheader('Content-Type') or '').split(';')[0].lower().strip()
        if content_type not in {'application/pdf', 'application/octet-stream'}:
            raise ExternalPDFError('External link did not return PDF metadata.')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise ExternalPDFError('Encoded external PDF is unsupported.')
        try:
            size = int(response.getheader('Content-Length', ''))
        except ValueError:
            raise ExternalPDFError('External PDF has no reliable size.') from None
        if not 0 < size <= self.settings.canvas_max_download_bytes:
            raise ExternalPDFError('External PDF size is invalid or exceeds the limit.')
        etag = response.getheader('ETag', '')
        modified = response.getheader('Last-Modified', '')
        strong_etag = etag if etag.startswith('"') and etag.endswith('"') else ''
        if modified:
            try:
                if parsedate_to_datetime(modified).tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                modified = ''
        if not strong_etag and not modified:
            raise ExternalPDFError('External PDF has no reliable revision validator.')
        revision = sha256(f'{strong_etag}\n{modified}\n{size}'.encode()).hexdigest()
        return size, revision

    def metadata(self, url):
        url = normalized_url(url, url)
        if not urlsplit(url).path.lower().endswith('.pdf'):
            raise ExternalPDFError('Only direct external PDF URLs are supported.')
        with self._follow(url, 'HEAD') as response:
            size, revision = self._properties(response)
        filename = PurePosixPath(unquote(urlsplit(url).path)).name
        return ExternalPDF(external_key(url), revision, filename, size, url)

    def download(self, metadata, context, *, existing_path=None):
        root = material_root(self.settings)
        target = build_material_path(root, context, metadata.filename)
        with self._follow(metadata.url, 'GET') as response:
            if self._properties(response) != (metadata.size, metadata.revision):
                raise ExternalPDFError('External PDF changed since discovery; retry discovery.')
            prefix = response.read(5)
            if prefix != b'%PDF-':
                raise ExternalPDFError('External file is not a PDF.')
            def chunks():
                yield prefix
                while chunk := response.read(65536):
                    yield chunk
            return save_stream(root, target, chunks(), metadata.size,
                               self.settings.canvas_max_download_bytes, existing_path=existing_path)
