import argparse
import json
import sqlite3
from pathlib import Path
from xlsx_reader import load_workbook, rows_to_records

KEEP_RAW_SHEETS = {
    'Telemetry APIs': 'telemetry_apis',
    'URI Expansion Ranges': 'uri_expansion_ranges',
    'Log Collection Catalog': 'log_collection_catalog',
    'Log Collection Configuration': 'log_collection_configuration',
    'Revision History': 'revision_history',
}


def q(name):
    return '"' + name.replace('"', '""') + '"'


def create_raw_table(conn, table, headers):
    cols = ['_source_row INTEGER'] + [f'{q(h)} TEXT' for h in headers]
    conn.execute(f'DROP TABLE IF EXISTS {q(table)}')
    conn.execute(f'CREATE TABLE {q(table)} ({", ".join(cols)})')


def insert_raw(conn, table, headers, records):
    cols = ['_source_row'] + headers
    sql = f'INSERT INTO {q(table)} ({", ".join(q(c) for c in cols)}) VALUES ({", ".join("?" for _ in cols)})'
    for r in records:
        conn.execute(sql, [r.get(c) for c in cols])


def build_search_text(rec):
    parts = []
    for k, v in rec.items():
        if k.startswith('_') or v in (None, ''):
            continue
        parts.append(f'{k}: {v}')
    return '\n'.join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx')
    ap.add_argument('--db', default='telemetry_catalog.sqlite')
    args = ap.parse_args()

    wb = load_workbook(args.xlsx)
    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')

    conn.execute('CREATE TABLE catalog_docs (id INTEGER PRIMARY KEY, sheet TEXT, source_row INTEGER, title TEXT, device TEXT, category TEXT, data_type TEXT, availability TEXT, search_text TEXT, record_json TEXT)')

    for sheet_name, table in KEEP_RAW_SHEETS.items():
        headers, records = rows_to_records(wb.get(sheet_name, []))
        create_raw_table(conn, table, headers)
        insert_raw(conn, table, headers, records)
        for rec in records:
            title = rec.get('telemetry_guid_deviceparamname') or rec.get('id') or rec.get('configuration_item') or f'{sheet_name} row {rec.get("_source_row")}'
            device = rec.get('device_compclass') or rec.get('component')
            category = rec.get('category_paramclass') or rec.get('collection_group') or rec.get('section')
            data_type = rec.get('data_type')
            availability = rec.get('availability_iboobbothnone') or rec.get('enabled')
            conn.execute(
                'INSERT INTO catalog_docs (sheet, source_row, title, device, category, data_type, availability, search_text, record_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (sheet_name, rec.get('_source_row'), title, device, category, data_type, availability, build_search_text(rec), json.dumps(rec, ensure_ascii=False)),
            )

    conn.execute('CREATE VIRTUAL TABLE catalog_fts USING fts5(title, device, category, search_text, content="catalog_docs", content_rowid="id")')
    conn.execute('INSERT INTO catalog_fts(rowid, title, device, category, search_text) SELECT id, title, COALESCE(device,""), COALESCE(category,""), search_text FROM catalog_docs')

    conn.execute('CREATE VIEW telemetry_metrics AS SELECT id, source_row, title AS telemetry_guid, device, category, data_type, availability, record_json FROM catalog_docs WHERE sheet="Telemetry APIs"')
    conn.execute('CREATE VIEW log_collectors AS SELECT id, source_row, title AS log_id, device AS component, category AS collection_group, availability AS enabled, record_json FROM catalog_docs WHERE sheet="Log Collection Catalog"')
    conn.commit()

    print(f'created {db_path}')
    for row in conn.execute('SELECT sheet, COUNT(*) FROM catalog_docs GROUP BY sheet ORDER BY sheet'):
        print(row[0], row[1])

if __name__ == '__main__':
    main()
