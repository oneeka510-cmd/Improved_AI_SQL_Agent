"""
app.py
======
Simple Streamlit frontend for the maritime data assistant.

What it does:
1. Shows a text box where you type a question in plain English.
2. Sends it through db_utils.py to generate + run SQL.
3. Shows a plain-English answer and the underlying data table.
4. Lets you download that data as an Excel file.

Run with:
    streamlit run app.py

(Needs db_utils.py in the same folder, and your .env file with the
DB_* and OPENAI_API_KEY variables.)
"""

import io
import pandas as pd
import streamlit as st

from db_utils import (
    get_connection,
    get_schema_info,
    generate_sql,
    is_safe_select,
    run_query,
    generate_explanation,
)

st.set_page_config(page_title="Maritime Data Assistant", page_icon="")
st.title(" Data Assistant")
st.caption("Ask a question about the data in plain English.")

# ---------------------------------------------------------------------------
# Read the table's schema ONCE per session (not on every click) using
# Streamlit's cache - this avoids hitting the database every time you
# just re-render the page.
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Reading table schema...")
def load_schema():
    conn = get_connection()
    try:
        return get_schema_info(conn)
    finally:
        conn.close()


dtype_info, sample_rows = load_schema()

# ---------------------------------------------------------------------------
# Streamlit reruns the ENTIRE script from top to bottom every time you
# click something. session_state is how we remember the last answer
# across those reruns - otherwise the download button would "forget"
# the data the moment you clicked it.
# ---------------------------------------------------------------------------
if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "explanation" not in st.session_state:
    st.session_state.explanation = None
if "sql_query" not in st.session_state:
    st.session_state.sql_query = None

question = st.text_input(
    "Your question",
    placeholder="e.g. Export all entries for vessel B in January 2025 into excel",
)

ask_clicked = st.button("Ask", type="primary")

if ask_clicked and question.strip():
    with st.spinner("Thinking..."):
        sql_query = generate_sql(question, dtype_info, sample_rows)

        if sql_query.strip() == "INSUFFICIENT_COLUMNS":
            st.session_state.result_df = None
            st.session_state.explanation = None
            st.error("Sorry, I don't have the data to answer that question.")

        elif not is_safe_select(sql_query):
            st.session_state.result_df = None
            st.session_state.explanation = None
            st.error("The generated query wasn't a safe SELECT statement, so it was blocked.")

        else:
            conn = get_connection()
            result_df = None
            try:
                result_df = run_query(conn, sql_query)
            except Exception as e:
                st.session_state.result_df = None
                st.session_state.explanation = None
                st.error(f"The query failed to run: {e}")
            finally:
                conn.close()

            if result_df is not None:
                explanation = generate_explanation(question, result_df)
                st.session_state.result_df = result_df
                st.session_state.explanation = explanation
                st.session_state.sql_query = sql_query

# ---------------------------------------------------------------------------
# Show the answer + data, if we have any
# ---------------------------------------------------------------------------
if st.session_state.explanation:
    st.subheader("Answer")
    st.write(st.session_state.explanation)

if st.session_state.result_df is not None:
    st.subheader("Data")
    st.dataframe(st.session_state.result_df)

    # Handy while testing - shows the SQL that was generated.
    # can remove this expander later for non-technical end users.
    with st.expander("Show generated SQL (for testing)"):
        st.code(st.session_state.sql_query, language="sql")

    # -----------------------------------------------------------------
    # Export to Excel. We write the dataframe into an in-memory file
    # (io.BytesIO) instead of saving to disk, then hand it to Streamlit's
    # download button - the file goes straight to the user's browser.
    # -----------------------------------------------------------------
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        st.session_state.result_df.to_excel(writer, index=False, sheet_name="Results")
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Download as Excel",
        data=excel_buffer,
        file_name="query_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )