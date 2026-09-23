r"""Optional visual QA fixture, never imported by the production application.

Run from backend with the frontend production server already on port 3000:
    .venv\Scripts\python.exe tests/preview_study.py
Open http://127.0.0.1:3002. All API data uses a temporary in-memory database;
non-API GETs proxy the actual frontend. Canvas/LLM network calls are disabled.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from urllib.parse import urlsplit
import re
import sys
import argparse
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.knowledge import get_knowledge_service
from app.api.study import get_material_root
from app.core.config import Settings
from app.core.database import build_engine, create_session_factory, init_db
from app.main import create_app
from app.models import Course, DocumentChunk, Resource, Semester, Week, SyncRecord
from app.models.common import utc_now
from app.services.document_processing import process_resource
from app.services.document_service import DocumentService
from app.services.knowledge_service import KnowledgeService
from test_knowledge import FakeProvider, ai, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-progress', action='store_true', help='Show a synthetic running snapshot, with all external work disabled.')
    parser.add_argument('--parsing-review', action='store_true', help='Include real synthetic PDF layout/empty-page warnings.')
    args = parser.parse_args()
    with TemporaryDirectory(prefix='studyflow-ui-fixture-') as directory:
        root = Path(directory)
        pdf_path = root / 'QA lecture.pdf'
        source = ('Frames carry data between neighboring devices. A frame contains a header and data.\n'
                  'The header describes the frame. This lecture shows an Ethernet frame.\n'
                  'Learning outcome: identify the parts of a frame.\nF = D + H')
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((50, 80), source)
            if args.parsing_review:
                page = pdf.new_page()
                page.insert_text((50, 100), 'x', fontsize=20)
                page.insert_text((61, 94), '2', fontsize=12)
                pdf.new_page()
            pdf.save(pdf_path)
        engine = build_engine('sqlite:///:memory:')
        init_db(engine)
        service = KnowledgeService(DocumentService(Settings(_env_file=None, materials_root=root)))
        with create_session_factory(engine)() as db:
            semester = Semester(name='UI verification — isolated fixture', year=2026, term='S2', is_active=True, canvas_term_id=101)
            course = Course(semester=semester, code='TEST ONLY', name='Networks and distributed systems: isolated interface verification')
            week = Week(course=course, week_number=1, title='Learning cards — test fixture')
            resource = Resource(week=week, filename='QA lecture.pdf', file_type='pdf', local_path=str(pdf_path))
            if args.parsing_review:
                resource.filename = 'Synthetic_Lecture_Week_07_Parsing_Review_With_A_Long_Course_Material_Filename.pdf'
            db.add(resource); db.commit()
            process_resource(db, resource.id, service.documents)
            chunk_id = db.scalar(select(DocumentChunk.id))
            data = payload(chunk_id=chunk_id)
            explanation = ('Frames carry data between neighboring devices. A frame contains a header and data. '
                           'The header describes the frame. ')
            data['concepts'][0]['explanation'] = explanation * 4
            sourced = {'source_chunk_ids': [chunk_id], 'source_pages': [1]}
            data['examples'] = [dict(sourced, description='This lecture shows an Ethernet frame.')]
            data['exam_focus'] = [dict(sourced, content='Learning outcome: identify the parts of a frame.')]
            data['formulas'] = [dict(source_chunk_ids=[chunk_id], source_page=1, formula='F = D + H', explanation=None, reliable=True)]
            service.generate(db, resource.id, ai(FakeProvider([data])))
        app = create_app(engine)
        app.dependency_overrides[get_knowledge_service] = lambda: service
        app.dependency_overrides[get_material_root] = lambda: root
        with TestClient(app) as client:
            if args.sync_progress:
                with create_session_factory(engine)() as db:
                    db.add(SyncRecord(started_at=utc_now()-timedelta(minutes=6, seconds=42),
                        courses_processed=1, files_discovered=12, files_downloaded=6, files_skipped=1, files_failed=1,
                        details={'discovery_complete': True, 'files_analyzed': 5, 'progress': {
                            'course_code': 'TEST ONLY', 'course_name': 'Networks and distributed systems',
                            'module': 'Week 07 · Synthetic preview module',
                            'filename': 'TEST_ONLY_07_Synthetic_Lecture_very_long_course_material_filename.pdf',
                            'stage': 'generation', 'processing': True, 'batch': 2, 'batches': 4,
                            'updated_at': (utc_now()-timedelta(seconds=3)).isoformat(),
                            'steps': {'discovery': 'completed', 'download': 'completed', 'parse': 'completed',
                                      'generation': 'current', 'review': 'pending', 'persistence': 'pending'}},
                            'errors': [{'course_code': 'TEST ONLY', 'filename': 'Failed.pdf', 'stage': 'review'}]}))
                    db.commit()
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path.startswith('/api/'):
                        if not re.fullmatch(r'/api/(?:sync/(?:current|\d+)|study/dashboard|courses/\d+(?:/weeks)?|weeks/\d+(?:/resources)?|resources/\d+/(?:knowledge|file))', urlsplit(self.path).path):
                            self.send_error(404, 'Route unavailable in isolated visual QA')
                            return
                        response = client.get(self.path)
                        status, content, headers = response.status_code, response.content, response.headers
                    else:
                        # Fixed localhost target: only serves the real built UI for visual QA.
                        with urlopen('http://127.0.0.1:3000' + self.path) as response:
                            status, content, headers = response.status, response.read(), response.headers
                    self.send_response(status)
                    for name in ('Content-Type', 'Content-Disposition', 'X-Content-Type-Options'):
                        if headers.get(name):
                            self.send_header(name, headers[name])
                    self.send_header('Content-Length', str(len(content)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(content)

                def do_POST(self):
                    self.send_error(405, 'Visual QA is read-only. Canvas and AI requests are disabled.')

            print('Isolated visual QA at http://127.0.0.1:3002/weeks/1', flush=True)
            with ThreadingHTTPServer(('127.0.0.1', 3002), Handler) as server:
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass


if __name__ == '__main__':
    main()
