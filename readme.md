# Maritime Data Assistant

A simple tool that lets you ask questions about your maritime data in
plain English, see the answer, and download the results as an Excel
file — no SQL knowledge needed to use it.

**Note:** This currently works with **Microsoft SQL Server** only
(connected via `pyodbc`), not MySQL.

## What it does

1. You type a question in plain English (e.g. *"Show all vessel
   entries after 5th June 2026"*).
2. An LLM (GPT-4o) turns your question into a SQL query, using only
   the real column names from your table.
3. The query runs against your SQL Server database.
4. A second LLM call summarizes the result in plain English.
5. You can view the data and download it as an Excel file.

## Files

| File | Purpose |
|---|---|
| `db_utils.py` | Backend logic: connects to the database, generates SQL, runs it, and writes the explanation |
| `app.py` | The Streamlit web interface |
| `.env` | Your database and OpenAI credentials (not included — you create this yourself) |

## Setup

1. Install the required packages:
   ```
   pip install streamlit openpyxl langchain-openai pyodbc python-dotenv pandas --break-system-packages
   ```

2. Create a `.env` file in the same folder as `app.py`, with:
   ```
   DB_DRIVER=ODBC Driver 17 for SQL Server
   DB_SERVER=your_server_name
   DB_DATABASE=your_database_name
   DB_UID=your_username
   DB_PWD=your_password
   OPENAI_API_KEY=your_openai_key
   ```

3. Update `TABLE_NAME` at the top of `db_utils.py` to match your actual table.

## Running it

```
streamlit run app.py
```

This opens a browser tab where you can type questions and get answers.

## Current scope / limitations

- **Single table only.** This assumes one flat table (currently intended
  to be a Power BI–joined table), not multiple joined tables.
- **SQL Server only.** MySQL, PostgreSQL, etc. are not supported yet.
- **Read/SELECT only.** The app blocks anything that isn't a SELECT
  statement, so it cannot modify or delete data.
- **Accuracy isn't perfect.** LLM-generated SQL can occasionally be
  wrong, especially on unusual phrasing. Always sanity-check important
  numbers, especially before using them for decisions.
- **Recommended:** the database login used in `.env` should have
  **read-only** permissions at the SQL Server level, as an extra layer
  of protection beyond the SELECT-only check in the code.

## Known issues already fixed

- Date filtering now uses `YEAR()`/`MONTH()`/date ranges instead of
  `LIKE` on date columns (which silently matched nothing).
- "Highest/lowest" questions use `TOP 1 WITH TIES` + `ORDER BY` instead
  of `WHERE col = (SELECT MAX(col)...)`, which could silently return
  zero rows on float/decimal columns.
- The explanation step no longer confuses "number of rows returned"
  with aggregate values (e.g. a count column) inside those rows.
- The explanation step no longer tells users to manually export data —
  the app's own download button already handles that.
