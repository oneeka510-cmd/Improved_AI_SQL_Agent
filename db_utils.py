"""
db_utils.py
===========
All the "backend" logic lives here: connecting to the database,
looking at the table's schema, asking the LLM to write SQL, running
that SQL safely, and asking the LLM to explain the result in plain
English.

This assumes ONE table (pretend this is the table Power BI has already
joined for you). Update TABLE_NAME below to match your real table.

app.py (the Streamlit frontend) imports these functions - you don't
need to touch this file to change how the UI looks.
"""

import os
import pyodbc
import pandas as pd
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


# CONFIG - update this to your actual (joined) table name

TABLE_NAME = "[dbo].[temp_tbl_Event_Data]"


# Connection string 

DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("DB_SERVER")
DB_DATABASE = os.getenv("DB_DATABASE")
DB_UID = os.getenv("DB_UID")
DB_PWD = os.getenv("DB_PWD")
DB_TRUST_CERT = os.getenv("DB_TRUST_SERVER_CERT", "yes")
DB_TIMEOUT_SECONDS = os.getenv("DB_TIMEOUT_SECONDS", "5")

CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_DATABASE};"
    f"UID={DB_UID};"
    f"PWD={DB_PWD};"
    f"TrustServerCertificate={DB_TRUST_CERT};"
    f"Connection Timeout={DB_TIMEOUT_SECONDS};"
)


def get_connection():
    """Open one fresh pyodbc connection. Caller is responsible for closing it."""
    return pyodbc.connect(CONNECTION_STRING)


def get_schema_info(conn):
    """
    Look at the table once and return two things as plain text:
    - dtype_info: column names + data types
    - sample_rows: a few real example rows
    Both get fed into the LLM prompt so it knows exactly what columns
    exist and what the actual data looks like.
    """
    sample_df = pd.read_sql(f"SELECT TOP 5 * FROM {TABLE_NAME}", conn)

    dtype_info = "\n".join(f"{col}: {dtype}" for col, dtype in sample_df.dtypes.items())
    sample_rows = sample_df.to_string(index=False)

    return dtype_info, sample_rows


def generate_sql(question, dtype_info, sample_rows):
    """
    Ask the LLM to turn a plain-English question into SQL Server syntax,
    using ONLY the columns that actually exist in the table.

    Returns the cleaned-up SQL string, OR the literal text
    "INSUFFICIENT_COLUMNS" if the question can't be answered with what
    this table has.
    """
    model = ChatOpenAI(model="gpt-4o", temperature=0)

    prompt = f"""You are a maritime expert. I am providing you a list containing
the column names and a user question. Based on the user question, write a
SQL Server query using the column names provided.

#table name
{TABLE_NAME}

# Columns and Data Types
{dtype_info}

IMPORTANT:
- The only valid column names are the ones listed above.
- Never invent, rename, split, or merge column names.
- If the question cannot be answered using the available columns, return
  exactly: INSUFFICIENT_COLUMNS

# Sample Rows
{sample_rows}

# User question
{question}

Rules:
- Return ONLY the SQL query, nothing else - no explanation, no markdown.
- Use SQL Server syntax. Use TOP, never LIMIT.
- When the user asks for totals, use SUM().
- When filtering TEXT columns (names, descriptions, etc.) from user input, use
  LIKE '%value%' unless the user explicitly asks for an exact match.
- NEVER use LIKE on a date/datetime column (e.g. never write
  [EventDate] LIKE '2026-06%'). Comparing a date as text silently matches
  nothing even when matching rows exist, because SQL Server may convert
  the date to a different text format internally. Instead:
  - For "a specific month/year", use YEAR([Col]) = 2026 AND MONTH([Col]) = 6
  - For "a date range", use [Col] >= '2026-06-01' AND [Col] < '2026-07-01'
- When multiple rows can share the max/min value (latest, earliest,
  highest, lowest), return ALL matching rows. To do this, do NOT write
  WHERE [Col] = (SELECT MAX([Col]) FROM ...) - this pattern can silently
  return ZERO rows if the column is a float/real number, because SQL
  Server can store tiny rounding differences that make two visually-equal
  numbers fail an exact equality check.
  Instead, always write it like this:
  SELECT TOP 1 WITH TIES [columns]
  FROM [table]
  ORDER BY [Col] DESC   -- use ASC for "lowest/earliest" instead
  "TOP 1 WITH TIES" returns the top row AND any other rows tied with it,
  without relying on exact equality comparison.
- Every non-aggregated column in a SELECT with aggregates must appear
  in GROUP BY.
"""

    result = model.invoke(prompt)
    sql_query = result.content
    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
    return sql_query


def is_safe_select(sql_query):
    """Basic safety check: only allow SELECT statements to run."""
    return sql_query.strip().upper().startswith("SELECT")


def run_query(conn, sql_query):
    """Execute the SQL and return a pandas DataFrame of results."""
    return pd.read_sql(sql_query, conn)


def generate_explanation(question, result_df, max_rows_to_show=20):
    """
    Ask the LLM to explain the result in plain English (no SQL talk).

    IMPORTANT: we do NOT send the whole result_df to the LLM if it's
    large. Sending, say, 1000 rows as raw text would be slow, expensive,
    and can hit the model's context limit. Instead we send:
    - the total row count
    - just the first `max_rows_to_show` rows as a sample
    This is enough for the LLM to describe what the data looks like and
    answer the question, without needing to "read" every single row.

    Note: this only affects the explanation paragraph. The full,
    untouched result_df is still what gets shown in the table and
    exported to Excel - this function never changes that data.
    """
    model = ChatOpenAI(model="gpt-4o", temperature=0)

    total_rows = len(result_df)
    sample_df = result_df.head(max_rows_to_show)

    if total_rows > max_rows_to_show:
        data_section = (
            f"(Showing the first {max_rows_to_show} of {total_rows} total rows)\n"
            f"{sample_df.to_string(index=False)}"
        )
    else:
        data_section = sample_df.to_string(index=False)

    prompt = f"""You are a maritime expert. I am providing you the result of a
database query (as a table) and the original user question. Write a short,
clear, plain-English answer to the question. Do not mention SQL or
databases - just answer as if you looked this up yourself.

CRITICAL - read this carefully:
- "Rows shown below" just tells you how many rows are in this table.
  It is NOT the answer to the question unless the question is literally
  "how many rows/records are there" with no grouping or counting involved.
- If the table contains a count/sum/total column (e.g. RecordCount,
  TotalIncidents, etc.), the ANSWER is the VALUE inside that column,
  not the number of rows in the table. A table can have just 1 row that
  contains the number 2305 inside it - in that case the answer is 2305,
  not 1.
- Always read the actual column values in the table below before
  answering. Never guess a number - only state numbers that appear
  directly in the table.
- Your ONLY job is to describe what the data shows. Do NOT tell the
  user how to export, download, or save the data as Excel/CSV/etc,
  and do NOT tell them what steps they "would need" to take - the
  application already handles exporting automatically, separately from
  your answer. Just describe the findings (e.g. "There are 35 records
  for Wenche Victory in January 2025."), nothing about next steps.

# Rows shown below
{total_rows}

# Query result
{data_section}

# User question
{question}
"""
    result = model.invoke(prompt)
    return result.content