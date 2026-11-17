from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 既有库的增量列：create_all 只建新表，已存在的表需要手工补列。
_ADDED_COLUMNS = {
    'reports': {
        'schedule_mode': "VARCHAR(16) NOT NULL DEFAULT 'interval'",
        'start_date': 'VARCHAR(10)',
    },
    'deliveries': {
        'slot_id': 'INTEGER',
        'status': "VARCHAR(16) NOT NULL DEFAULT 'archived'",
        'schedule_mode': "VARCHAR(16) NOT NULL DEFAULT 'interval'",
        'version_id': 'INTEGER',
        'error': "VARCHAR(500) NOT NULL DEFAULT ''",
    },
}


def _ensure_columns(inspector):
    existing = {t: {c['name'] for c in inspector.get_columns(t)}
                for t in inspector.get_table_names()}
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing:
                continue
            for name, ddl in columns.items():
                if name not in existing[table]:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
        # 场次留档唯一约束：同场次重试不得重复留档（PG 与 SQLite 均支持该写法）。
        conn.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_deliveries_slot_id '
            'ON deliveries (slot_id) WHERE slot_id IS NOT NULL'))


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns(inspect(engine))


if __name__ == '__main__':
    migrate()
