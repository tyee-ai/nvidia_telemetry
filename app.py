import hmac
import json
import math
import os
import sqlite3
from pathlib import Path

import streamlit as st


DB_PATH = Path(__file__).with_name("telemetry_catalog.sqlite")

st.set_page_config(
    page_title="NVIDIA Telemetry Catalog",
    page_icon="🔐",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def configured_credentials() -> tuple[str, str]:
    """
    Load credentials from environment variables, with Streamlit secrets taking
    precedence when they are configured.

    Environment variables:
        TELEMETRY_APP_USERNAME
        TELEMETRY_APP_PASSWORD

    Streamlit secrets:
        [auth]
        username = "..."
        password = "..."
    """
    username = os.getenv("TELEMETRY_APP_USERNAME", "")
    password = os.getenv("TELEMETRY_APP_PASSWORD", "")

    try:
        auth = st.secrets.get("auth", {})
        username = str(auth.get("username", username))
        password = str(auth.get("password", password))
    except (FileNotFoundError, KeyError, TypeError):
        pass

    return username, password


def require_login() -> None:
    """Prevent the application from rendering until authentication succeeds."""
    configured_username, configured_password = configured_credentials()

    if not configured_username or not configured_password:
        st.error(
            "Authentication is not configured. Add credentials to "
            "`.streamlit/secrets.toml` or set the "
            "`TELEMETRY_APP_USERNAME` and `TELEMETRY_APP_PASSWORD` "
            "environment variables."
        )
        st.stop()

    if st.session_state.get("authenticated", False):
        with st.sidebar:
            st.success(
                f"Signed in as "
                f"{st.session_state.get('authenticated_username', 'user')}"
            )

            if st.button(
                "Log out",
                use_container_width=True,
                key="logout_button",
            ):
                st.session_state.authenticated = False
                st.session_state.pop("authenticated_username", None)
                st.rerun()

        return

    st.title("NVIDIA Telemetry Catalog")
    st.caption("Sign in to access the telemetry catalog.")

    with st.form("login_form", clear_on_submit=False):
        submitted_username = st.text_input(
            "Login",
            key="login_username",
        )

        submitted_password = st.text_input(
            "Password",
            type="password",
            key="login_password",
        )

        submitted = st.form_submit_button(
            "Sign in",
            use_container_width=True,
        )

    if submitted:
        username_valid = hmac.compare_digest(
            submitted_username,
            configured_username,
        )

        password_valid = hmac.compare_digest(
            submitted_password,
            configured_password,
        )

        if username_valid and password_valid:
            st.session_state.authenticated = True
            st.session_state.authenticated_username = submitted_username
            st.rerun()

        st.error("Invalid login or password.")

    # This is critical. It prevents the catalog UI from appearing below login.
    st.stop()


# Authentication must run before any catalog UI is rendered.
require_login()


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_database_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        st.error(
            f"Database not found: `{DB_PATH.name}`. "
            "Run the ingestion script before launching the application."
        )
        st.stop()

    connection = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row
    return connection


connection = get_database_connection()


# ---------------------------------------------------------------------------
# Application header
# ---------------------------------------------------------------------------

st.title("NVIDIA Telemetry Catalog")
st.caption(
    "Structured search across NVIDIA telemetry metrics, Redfish URIs, "
    "DCGM and NVML fields, platform applicability, and log collectors."
)


# ---------------------------------------------------------------------------
# Search controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    st.header("Search filters")

    catalog_area = st.selectbox(
        "Catalog area",
        [
            "All",
            "Telemetry APIs",
            "Log Collection Catalog",
            "URI Expansion Ranges",
            "Log Collection Configuration",
        ],
        key="catalog_area",
    )

    device_filter = st.text_input(
        "Device or component contains",
        value="",
        key="device_filter",
    )

    rows_per_page = st.selectbox(
        "Rows per page",
        [12, 25, 50, 100, 250, 500],
        index=1,
        help="Controls how many matching records are shown on each page.",
        key="rows_per_page",
    )


search_query = st.text_input(
    "Search the catalog",
    placeholder=(
        "Example: B200 GPU temperature Redfish DCGM thermal throttling"
    ),
    key="search_query",
)


# ---------------------------------------------------------------------------
# Build filters
# ---------------------------------------------------------------------------

filters: list[str] = []
filter_parameters: list[object] = []

if catalog_area != "All":
    filters.append("d.sheet = ?")
    filter_parameters.append(catalog_area)

if device_filter.strip():
    filters.append("LOWER(COALESCE(d.device, '')) LIKE ?")
    filter_parameters.append(f"%{device_filter.strip().lower()}%")


additional_and_clause = (
    " AND " + " AND ".join(filters)
    if filters
    else ""
)

additional_where_clause = (
    " WHERE " + " AND ".join(filters)
    if filters
    else ""
)


# ---------------------------------------------------------------------------
# Full-text search preparation
# ---------------------------------------------------------------------------

fts_query = ""

if search_query.strip():
    search_terms = [
        term.replace('"', "").strip()
        for term in search_query.split()
        if term.strip()
    ]

    # OR improves recall for exploratory engineering searches.
    fts_query = " OR ".join(
        f'"{term}"'
        for term in search_terms
    )


# ---------------------------------------------------------------------------
# Count matching results
# ---------------------------------------------------------------------------

try:
    if search_query.strip():
        count_sql = f"""
            SELECT COUNT(*)
            FROM catalog_fts
            JOIN catalog_docs d
                ON d.id = catalog_fts.rowid
            WHERE catalog_fts MATCH ?
            {additional_and_clause}
        """

        count_parameters = [fts_query, *filter_parameters]

    else:
        count_sql = f"""
            SELECT COUNT(*)
            FROM catalog_docs d
            {additional_where_clause}
        """

        count_parameters = filter_parameters

    total_rows = connection.execute(
        count_sql,
        count_parameters,
    ).fetchone()[0]

except sqlite3.Error as error:
    total_rows = 0
    st.error(f"Unable to count search results: {error}")


total_pages = max(
    1,
    math.ceil(total_rows / rows_per_page),
)


# ---------------------------------------------------------------------------
# Pagination state
# ---------------------------------------------------------------------------

search_signature = (
    search_query,
    catalog_area,
    device_filter,
    rows_per_page,
)

if "last_search_signature" not in st.session_state:
    st.session_state.last_search_signature = None

if "current_page" not in st.session_state:
    st.session_state.current_page = 1

if search_signature != st.session_state.last_search_signature:
    st.session_state.current_page = 1
    st.session_state.last_search_signature = search_signature

if st.session_state.current_page > total_pages:
    st.session_state.current_page = total_pages


# ---------------------------------------------------------------------------
# Pagination controls
# ---------------------------------------------------------------------------

st.subheader("Results")

previous_column, page_column, next_column, count_column = st.columns(
    [1, 2, 1, 3]
)

with previous_column:
    previous_disabled = st.session_state.current_page <= 1

    if st.button(
        "Previous",
        disabled=previous_disabled,
        use_container_width=True,
    ):
        st.session_state.current_page -= 1
        st.rerun()

with page_column:
    selected_page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=int(st.session_state.current_page),
        step=1,
        key="page_selector",
    )

    if int(selected_page) != st.session_state.current_page:
        st.session_state.current_page = int(selected_page)
        st.rerun()

with next_column:
    next_disabled = st.session_state.current_page >= total_pages

    if st.button(
        "Next",
        disabled=next_disabled,
        use_container_width=True,
    ):
        st.session_state.current_page += 1
        st.rerun()

with count_column:
    st.metric(
        "Matching records",
        f"{total_rows:,}",
    )


page_start = (
    ((st.session_state.current_page - 1) * rows_per_page) + 1
    if total_rows
    else 0
)

page_end = min(
    st.session_state.current_page * rows_per_page,
    total_rows,
)

summary_column_1, summary_column_2, summary_column_3 = st.columns(3)

summary_column_1.metric(
    "Current page",
    f"{st.session_state.current_page:,}",
)

summary_column_2.metric(
    "Total pages",
    f"{total_pages:,}",
)

summary_column_3.metric(
    "Rows displayed",
    f"{page_start:,}–{page_end:,}",
)


offset = (
    st.session_state.current_page - 1
) * rows_per_page


# ---------------------------------------------------------------------------
# Retrieve current page
# ---------------------------------------------------------------------------

try:
    if search_query.strip():
        rows_sql = f"""
            SELECT
                d.id,
                d.sheet,
                d.source_row,
                d.title,
                d.device,
                d.category,
                d.data_type,
                d.availability,
                d.record_json,
                bm25(catalog_fts) AS score
            FROM catalog_fts
            JOIN catalog_docs d
                ON d.id = catalog_fts.rowid
            WHERE catalog_fts MATCH ?
            {additional_and_clause}
            ORDER BY score
            LIMIT ? OFFSET ?
        """

        row_parameters = [
            fts_query,
            *filter_parameters,
            rows_per_page,
            offset,
        ]

    else:
        rows_sql = f"""
            SELECT
                d.id,
                d.sheet,
                d.source_row,
                d.title,
                d.device,
                d.category,
                d.data_type,
                d.availability,
                d.record_json,
                0 AS score
            FROM catalog_docs d
            {additional_where_clause}
            ORDER BY d.sheet, d.source_row
            LIMIT ? OFFSET ?
        """

        row_parameters = [
            *filter_parameters,
            rows_per_page,
            offset,
        ]

    result_rows = connection.execute(
        rows_sql,
        row_parameters,
    ).fetchall()

except sqlite3.Error as error:
    result_rows = []
    st.error(f"Unable to retrieve search results: {error}")


# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------

if not result_rows:
    st.info("No rows matched the current search and filters.")


important_fields = [
    "description",
    "in_band_api_dcgm",
    "in_band_api_nvmlnvsdm",
    "in_band_cli_nvidia_smi_q_x",
    "oob_api_wildcards_redfish_uri_and_field_na_for_nvswitch_tray",
    "uri_search_domain",
    "uri_match_criteria_for_search_domain",
    "recommended_poll_freq",
    "cross_validation_scope",
    "api_calls",
    "api_args",
    "action_type",
    "parser_type",
    "validation_methods",
    "execution_methods",
]


for result in result_rows:
    try:
        record = json.loads(result["record_json"])
    except (json.JSONDecodeError, TypeError):
        record = {}

    result_title = result["title"] or "Untitled record"
    sheet_name = result["sheet"] or "Unknown sheet"
    source_row = result["source_row"] or "N/A"

    with st.expander(
        f"{result_title} · {sheet_name} row {source_row}",
        expanded=False,
    ):
        metadata_columns = st.columns(4)

        metadata_columns[0].metric(
            "Device/component",
            result["device"] or "N/A",
        )

        metadata_columns[1].metric(
            "Category/group",
            result["category"] or "N/A",
        )

        metadata_columns[2].metric(
            "Data type",
            result["data_type"] or "N/A",
        )

        metadata_columns[3].metric(
            "Availability",
            result["availability"] or "N/A",
        )

        for field_name in important_fields:
            field_value = record.get(field_name)

            if field_value not in (None, "", [], {}):
                display_name = field_name.replace("_", " ").title()

                st.markdown(f"**{display_name}**")
                st.code(
                    str(field_value),
                    language=None,
                )

        with st.expander("Full raw record"):
            st.json(record)


# ---------------------------------------------------------------------------
# Bottom pagination controls
# ---------------------------------------------------------------------------

if total_pages > 1:
    st.divider()

    bottom_previous, bottom_summary, bottom_next = st.columns(
        [1, 3, 1]
    )

    with bottom_previous:
        if st.button(
            "← Previous page",
            disabled=st.session_state.current_page <= 1,
            use_container_width=True,
            key="bottom_previous",
        ):
            st.session_state.current_page -= 1
            st.rerun()

    with bottom_summary:
        st.markdown(
            (
                f"<div style='text-align:center; padding-top:8px;'>"
                f"Page <strong>{st.session_state.current_page:,}</strong> "
                f"of <strong>{total_pages:,}</strong> "
                f"— showing rows "
                f"<strong>{page_start:,}–{page_end:,}</strong> "
                f"of <strong>{total_rows:,}</strong>"
                f"</div>"
            ),
            unsafe_allow_html=True,
        )

    with bottom_next:
        if st.button(
            "Next page →",
            disabled=st.session_state.current_page >= total_pages,
            use_container_width=True,
            key="bottom_next",
        ):
            st.session_state.current_page += 1
            st.rerun()


# ---------------------------------------------------------------------------
# SQL console
# ---------------------------------------------------------------------------

st.divider()
st.subheader("SQL console")

st.caption(
    "For engineering validation. The console currently allows read-only "
    "SELECT and WITH queries."
)

sql_text = st.text_area(
    "SQL query",
    height=120,
    placeholder=(
        "SELECT telemetry_guid, device, category "
        "FROM telemetry_metrics "
        "WHERE device = 'GPU' "
        "LIMIT 20"
    ),
)

if st.button("Run SQL", key="run_sql_button"):
    normalized_sql = sql_text.strip().lower()

    if not normalized_sql:
        st.warning("Enter a SQL query.")

    elif not (
        normalized_sql.startswith("select")
        or normalized_sql.startswith("with")
    ):
        st.error(
            "Only read-only SELECT and WITH queries are allowed."
        )

    else:
        try:
            cursor = connection.execute(sql_text)
            sql_rows = cursor.fetchall()

            column_names = [
                description[0]
                for description in cursor.description or []
            ]

            formatted_rows = [
                dict(zip(column_names, row))
                for row in sql_rows
            ]

            st.dataframe(
                formatted_rows,
                use_container_width=True,
                hide_index=True,
            )

            st.caption(
                f"Returned {len(formatted_rows):,} rows."
            )

        except sqlite3.Error as error:
            st.error(f"SQL error: {error}")
