"""Idempotent additive SQLite upgrade for existing Phase 1–5 development DBs."""
from sqlalchemy import inspect


def upgrade_sync_columns(engine):
    additions = {'weeks': ('canvas_module_id', 'INTEGER'),
                 'resources': ('sync_stage', 'VARCHAR(20)'),
                 'sync_records': ('details', "JSON NOT NULL DEFAULT '{}'" )}
    with engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        inspector = inspect(connection)
        for table, (column, declaration) in additions.items():
            if table in inspector.get_table_names() and column not in {
                    c['name'] for c in inspector.get_columns(table)}:
                connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        if 'weeks' in inspector.get_table_names():
            connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_week_canvas_module '
                                       'ON weeks (course_id, canvas_module_id)')
        if 'resources' in inspector.get_table_names() and 'parsing_report' not in {
                c['name'] for c in inspector.get_columns('resources')}:
            connection.exec_driver_sql('ALTER TABLE resources ADD COLUMN parsing_report JSON')
        if 'semesters' in inspector.get_table_names():
            columns = {c['name'] for c in inspector.get_columns('semesters')}
            for name, definition in [('is_active', 'BOOLEAN NOT NULL DEFAULT 0'), ('canvas_term_id', 'INTEGER')]:
                if name not in columns:
                    connection.exec_driver_sql(f'ALTER TABLE semesters ADD COLUMN {name} {definition}')
            connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_active_semester '
                                       'ON semesters (is_active) WHERE is_active = 1')
            connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_semester_canvas_term '
                                       'ON semesters (canvas_term_id)')
        if 'sync_records' in inspector.get_table_names():
            ddl = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='sync_records'").scalar_one()
            if "'cancelled'" not in ddl and 'syncstatus' in ddl:
                # SQLite cannot alter a CHECK constraint. Rebuild this leaf table
                # transactionally, preserving every column, row and count.
                updated = ddl.replace('CREATE TABLE sync_records', 'CREATE TABLE sync_records_new', 1)
                updated = updated.replace("'completed_with_errors', 'failed'", "'completed_with_errors', 'failed', 'cancelled'")
                if updated == ddl or "'cancelled'" not in updated:
                    raise RuntimeError('Unrecognized sync status constraint; migration stopped safely.')
                connection.exec_driver_sql(updated)
                connection.exec_driver_sql('INSERT INTO sync_records_new SELECT * FROM sync_records')
                connection.exec_driver_sql('DROP TABLE sync_records')
                connection.exec_driver_sql('ALTER TABLE sync_records_new RENAME TO sync_records')
