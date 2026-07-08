import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {
    'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}


def _col_to_idx(cell_ref: str) -> int:
    m = re.match(r'([A-Z]+)', cell_ref or 'A1')
    letters = m.group(1)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _clean_header(value, fallback_index: int) -> str:
    value = (value or f'unnamed_{fallback_index + 1}').strip()
    value = re.sub(r'\s+', ' ', value)
    value = value.replace('/', ' or ')
    value = re.sub(r'[^0-9A-Za-z_ ]+', '', value)
    value = value.strip().lower().replace(' ', '_')
    value = re.sub(r'_+', '_', value).strip('_')
    return value or f'unnamed_{fallback_index + 1}'


def _unique_headers(headers):
    out = []
    counts = {}
    for i, h in enumerate(headers):
        base = _clean_header(h, i)
        counts[base] = counts.get(base, 0) + 1
        out.append(base if counts[base] == 1 else f'{base}_{counts[base]}')
    return out


def load_workbook(path):
    path = Path(path)
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall('a:si', NS):
            shared.append(''.join(t.text or '' for t in si.iter(f"{{{NS['a']}}}t")))

    wb_root = ET.fromstring(z.read('xl/workbook.xml'))
    rel_root = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    rels = {rel.attrib['Id']: rel.attrib['Target'] for rel in list(rel_root)}

    sheets = []
    for sh in wb_root.find('a:sheets', NS):
        rid = sh.attrib[f"{{{NS['r']}}}id"]
        target = rels[rid]
        xml_path = target.lstrip('/') if target.startswith('/') else 'xl/' + target.lstrip('../')
        sheets.append((sh.attrib['name'], xml_path))

    result = {}
    for sheet_name, xml_path in sheets:
        root = ET.fromstring(z.read(xml_path))
        rows = []
        for row in root.iter(f"{{{NS['a']}}}row"):
            cells = []
            max_col = -1
            for c in row.findall('a:c', NS):
                idx = _col_to_idx(c.attrib.get('r', 'A1'))
                value = None
                v = c.find('a:v', NS)
                if v is not None:
                    value = v.text
                    if c.attrib.get('t') == 's':
                        value = shared[int(value)]
                elif c.attrib.get('t') == 'inlineStr':
                    value = ''.join(t.text or '' for t in c.iter(f"{{{NS['a']}}}t"))
                if value == '':
                    value = None
                cells.append((idx, value))
                max_col = max(max_col, idx)
            vals = [None] * (max_col + 1)
            for idx, value in cells:
                vals[idx] = value
            rows.append(vals)
        result[sheet_name] = rows
    return result


def rows_to_records(rows):
    if not rows:
        return [], []
    width = max(len(r) for r in rows)
    headers = rows[0] + [None] * (width - len(rows[0]))
    headers = _unique_headers(headers)
    records = []
    for n, row in enumerate(rows[1:], start=2):
        row = row + [None] * (width - len(row))
        if not any(v not in (None, '') for v in row):
            continue
        rec = {headers[i]: row[i] for i in range(width)}
        rec['_source_row'] = n
        records.append(rec)
    return headers, records
