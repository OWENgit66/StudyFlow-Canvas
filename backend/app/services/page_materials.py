"""Extract inert link references; never render HTML or follow Page navigation."""
from dataclasses import dataclass, field, replace
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from app.services.canvas_errors import CanvasError


@dataclass(frozen=True)
class MaterialLink:
    canvas_file_id: int | None = None
    external_url: str | None = field(default=None, repr=False)
    link_text: str = field(default='', repr=False)
    surrounding_text: str = field(default='', repr=False)
    page_title: str = field(default='', repr=False)

    @property
    def key(self):
        return ('canvas', self.canvas_file_id) if self.canvas_file_id else ('external', external_key(self.external_url))


def external_key(url):
    # Full normalized URL including query; never put external hashes in Canvas IDs.
    return sha256(url.encode('utf-8')).hexdigest()


def normalized_url(value, base):
    if not value or len(value) > 8192 or '\\' in value or any(ord(c) < 32 or c.isspace() for c in value):
        raise ValueError('Unsafe link')
    parsed = urlsplit(urljoin(base, value))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Unsafe link')
    port = parsed.port
    host = parsed.hostname.lower().encode('idna').decode('ascii')
    host = f'[{host}]' if ':' in host else host
    authority = host + (f':{port}' if port and port != 443 else '')
    return urlunsplit(('https', authority, parsed.path or '/', parsed.query, ''))


def canvas_id(url, origin):
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != (urlsplit(origin).scheme, urlsplit(origin).netloc):
        return None
    match = re.fullmatch(r'/(?:api/v1/)?(?:courses/\d+/)?files/([1-9]\d*)(?:/(?:download|preview))?/?', parsed.path)
    if match:
        return int(match[1])
    # Canvas attachment links also occur as course file-browser previews.
    if re.fullmatch(r'/courses/\d+/files/?', parsed.path):
        values = parse_qs(parsed.query)
        for key in ('preview', 'file_id'):
            ids = values.get(key, [])
            if len(ids) == 1 and re.fullmatch(r'[1-9]\d*', ids[0]):
                return int(ids[0])
    return None


class PageLinks(HTMLParser):
    def __init__(self, base, origin):
        super().__init__(convert_charrefs=True)
        self.base, self.origin = base, origin
        self.links, self.unsupported = [], []
        self.blocked = []
        self.count = 0
        self.headings = {}
        self.heading = None
        self.blocks = []
        self.anchor = None
        self.contexts = {}
        self.previous_paragraph = ''
        self.list_contexts = []
        self.link_blocks = set()

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'form', 'template'}:
            self.blocked.append(tag)
        if self.blocked:
            return
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.previous_paragraph = ''
            level = int(tag[1])
            self.headings = {k: v for k, v in self.headings.items() if k < level}
            self.heading = (level, [])
        if tag in {'ul', 'ol'}:
            self.list_contexts.append(self.previous_paragraph)
            self.previous_paragraph = ''
        if tag in {'p', 'li', 'td', 'figcaption'}:
            self.blocks.append((tag, []))
        if tag != 'a':
            return
        self.anchor = None
        if self.blocks:
            self.link_blocks.add(id(self.blocks[-1][1]))
        self.count += 1
        if self.count > 2000:
            raise CanvasError('Canvas page exceeds the link limit.')
        attrs = dict(attrs)
        href = attrs.get('href')
        if href and href.startswith('#'):
            return
        # Canonical endpoint attributes are preferred, but only on the Canvas origin.
        for candidate in [attrs.get('data-api-endpoint'), href]:
            try:
                url = normalized_url(candidate, self.base)
                file_id = canvas_id(url, self.origin)
                if file_id:
                    self._add_link(MaterialLink(canvas_file_id=file_id), attrs)
                    return
            except (ValueError, UnicodeError):
                continue
        try:
            url = normalized_url(href, self.base)
            parsed = urlsplit(url)
            file_id = attrs.get('data-file-id', '')
            if parsed.netloc == urlsplit(self.origin).netloc and re.fullmatch(r'[1-9]\d*', file_id or ''):
                self._add_link(MaterialLink(canvas_file_id=int(file_id)), attrs)
                return
            if parsed.path.lower().endswith('.pdf'):
                self._add_link(MaterialLink(external_url=url), attrs)
                return
        except (ValueError, UnicodeError):
            pass
        # No raw URL/query, Page HTML, or signed credentials in diagnostics.
        self.unsupported.append('unsupported_or_unresolved_link')

    def _add_link(self, link, attrs):
        text = [str(attrs.get('title') or '')[:500]]
        block = self.blocks[-1][1] if self.blocks else []
        preceding = self.list_contexts[-1] if self.list_contexts else self.previous_paragraph
        heading = ' '.join(self.headings.values()) + ' ' + preceding
        self.contexts[len(self.links)] = (text, block, heading)
        self.links.append(link)
        self.anchor = text

    def handle_data(self, data):
        if self.blocked:
            return
        targets = [block for _, block in self.blocks[-1:]]
        if self.anchor is not None:
            targets.append(self.anchor)
        if self.heading is not None:
            targets.append(self.heading[1])
        for target in targets:
            # Bounded, plain-text context only. No attributes, scripts or full Page bodies.
            if sum(map(len, target)) < 1500:
                target.append(data[:1500])

    def handle_endtag(self, tag):
        if tag in self.blocked:
            self.blocked = self.blocked[:self.blocked.index(tag)]
        if self.blocked:
            return
        if tag == 'a':
            self.anchor = None
        if tag in {'ul', 'ol'} and self.list_contexts:
            self.list_contexts.pop()
            self.previous_paragraph = ''
        if self.heading is not None and tag == f'h{self.heading[0]}':
            self.headings[self.heading[0]] = ' '.join(self.heading[1])
            self.heading = None
        for index in range(len(self.blocks) - 1, -1, -1):
            if self.blocks[index][0] == tag:
                block = self.blocks[index][1]
                if tag == 'p':
                    text = ' '.join(block).strip()
                    # A nearby plain paragraph can introduce a following list/link.
                    # Do not carry material-link paragraphs or distant Page prose forward.
                    self.previous_paragraph = text if id(block) not in self.link_blocks and len(text) <= 500 else ''
                self.link_blocks.discard(id(block))
                self.blocks = self.blocks[:index]
                break

    def close(self):
        super().close()
        for index, (text, block, heading) in self.contexts.items():
            self.links[index] = replace(self.links[index], link_text=' '.join(text),
                                        surrounding_text=heading + ' ' + ' '.join(block))


def extract_material_links(body, canvas_origin, course_id, page_url):
    if len(body) > 2_000_000:
        raise CanvasError('Canvas page exceeds the HTML size limit.')
    origin = normalized_url(canvas_origin, canvas_origin).rstrip('/')
    base = f'{origin}/courses/{course_id}/pages/{page_url}'
    parser = PageLinks(base, origin)
    parser.feed(body)
    parser.close()
    return parser.links, parser.unsupported
