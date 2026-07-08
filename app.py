import json
import sqlite3
from pathlib import Path
import streamlit as st

DB_PATH = Path(__file__).with_name('telemetry_catalog.sqlite')

st.set_page_config(page_title='NVIDIA Telemetry Catalog Prototype', layout='wide')
st.title('NVIDIA Telemetry Catalog Prototype')
st.caption('Structured catalog search over telemetry metrics, Redfish URIs, DCGM/NVML fields, platform applicability, and log collectors.')

@st.cache_resource
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

conn = db()

with st.sidebar:
    st.header('Filters')
    sheet = st.selectbox('Catalog area', ['All', 'Telemetry APIs', 'Log Collection Catalog', 'URI Expansion Ranges', 'Log Collection Configuration'])
    device = st.text_input('Device/component contains', '')
    limit = st.slider('Result limit', 5, 50, 12)

query = st.text_input('Ask/search the catalog', placeholder='e.g. B200 GPU temperature Redfish DCGM or thermal throttling logs')

where = []
params = []
if sheet != 'All':
    where.append('d.sheet = ?')
    params.append(sheet)
if device:
    where.append('LOWER(COALESCE(d.device,"")) LIKE ?')
    params.append(f'%{device.lower()}%')

if query:
    # Quote query terms for safer FTS prefix search.
    terms = [t.replace('"', '') for t in query.split() if t.strip()]
    fts = ' OR '.join(f'"{t}"' for t in terms) or query
    sql = '''
    SELECT d.id, d.sheet, d.source_row, d.title, d.device, d.category, d.data_type, d.availability, d.record_json,
           bm25(catalog_fts) AS score
    FROM catalog_fts
    JOIN catalog_docs d ON d.id = catalog_fts.rowid
    WHERE catalog_fts MATCH ? {extra}
    ORDER BY score
    LIMIT ?
    '''.format(extra=(' AND ' + ' AND '.join(where)) if where else '')
    rows = conn.execute(sql, [fts] + params + [limit]).fetchall()
else:
    sql = '''SELECT d.id, d.sheet, d.source_row, d.title, d.device, d.category, d.data_type, d.availability, d.record_json, 0 AS score
             FROM catalog_docs d {extra} ORDER BY d.sheet, d.source_row LIMIT ?'''.format(extra=('WHERE ' + ' AND '.join(where)) if where else '')
    rows = conn.execute(sql, params + [limit]).fetchall()

st.subheader('Results')
for _, sheet_name, source_row, title, dev, cat, dtype, avail, record_json, score in rows:
    rec = json.loads(record_json)
    with st.expander(f'{title} · {sheet_name} row {source_row}', expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('Device/component', dev or 'N/A')
        c2.metric('Category/group', cat or 'N/A')
        c3.metric('Data type', dtype or 'N/A')
        c4.metric('Availability/enabled', avail or 'N/A')
        important = [
            'description','in_band_api_dcgm','in_band_api_nvmlnvsdm','in_band_cli_nvidia_smi_q_x',
            'oob_api_wildcards_redfish_uri_and_field_na_for_nvswitch_tray','uri_search_domain',
            'uri_match_criteria_for_search_domain','recommended_poll_freq','cross_validation_scope',
            'api_calls','api_args','action_type','parser_type','validation_methods','execution_methods'
        ]
        for k in important:
            if rec.get(k):
                st.markdown(f'**{k.replace("_", " ").title()}**')
                st.code(str(rec[k]), language=None)
        with st.expander('Full raw record'):
            st.json(rec)

st.divider()
st.subheader('Simple SQL console')
st.caption('Useful for engineering validation. Example: SELECT telemetry_guid, device, category FROM telemetry_metrics WHERE device="GPU" LIMIT 20')
sql_text = st.text_area('SQL', height=120)
if st.button('Run SQL') and sql_text.strip():
    try:
        cur = conn.execute(sql_text)
        st.dataframe(cur.fetchall(), use_container_width=True)
        st.caption(', '.join([d[0] for d in cur.description or []]))
    except Exception as e:
        st.error(str(e))
