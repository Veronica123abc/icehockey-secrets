from __future__ import annotations

import os
import re
import sqlite3

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from hockey.chat.claude_client import _SCHEMA

_MODEL = "claude-sonnet-4-6"

_SYSTEM_AGENT = f"""You are a hockey analytics assistant with access to a MySQL database via the run_sql tool.

When the user asks a data question:
1. Write a SELECT query and call run_sql.
2. If run_sql returns an error, revise the query and retry (up to 3 attempts).
3. For complex questions that require multiple lookups, make multiple run_sql calls.
4. After getting results, answer concisely in plain language.
5. If no rows are returned, say so directly.

SQL rules:
- Only write SELECT queries.
- Always add LIMIT 200 unless the query aggregates to a small result set.
- Only reference columns that exist in the schema below.
- Team names, player names, and league names may be misspelled — use LIKE in WHERE clauses.

Schema:
{_SCHEMA}

Table explanations:
Participation: team participation in one league during one season.
Affiliation: one player is affiliated with one team in one game.
"""


@tool
def run_sql(query: str) -> str:
    """Execute a SELECT query against the hockey analytics MySQL database and return results."""
    if not query.strip().upper().startswith("SELECT"):
        return "Error: only SELECT queries are allowed."

    host = os.getenv("DATABASE_HOST_AZURE")
    if not host:
        return "Error: database not available (DATABASE_HOST_AZURE not set)."

    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=host,
            user=os.environ["DATABASE_USERNAME_AZURE"],
            password=os.environ["DATABASE_PWD_AZURE"],
            database=os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
            auth_plugin="mysql_native_password",
            connect_timeout=5,
        )
    except Exception as e:
        return f"Error: could not connect to database: {e}"

    try:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(200)
        cursor.close()
    except Exception as e:
        return f"SQL error: {e}"
    finally:
        conn.close()

    if not rows:
        return "(no rows returned)\n__row_count__: 0"

    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    lines.append(f"__row_count__: {len(rows)}")
    return "\n".join(lines)


def _make_checkpointer() -> SqliteSaver:
    db_path = os.getenv("CHAT_SESSIONS_DB", "./chat_sessions.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


_checkpointer = _make_checkpointer()
_llm = ChatAnthropic(model=_MODEL)
_agent = create_react_agent(
    _llm,
    tools=[run_sql],
    checkpointer=_checkpointer,
    state_modifier=_SYSTEM_AGENT,
)


def chat(question: str, session_id: str) -> dict:
    config = {"configurable": {"thread_id": session_id}}
    result = _agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )

    messages = result["messages"]

    last = messages[-1]
    answer = last.content if isinstance(last.content, str) else str(last.content)

    sql = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] == "run_sql":
                    sql = tc["args"].get("query")
                    break
            if sql:
                break

    row_count = None
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            m = re.search(r"__row_count__: (\d+)", msg.content)
            if m:
                row_count = int(m.group(1))
            break

    return {"answer": answer, "sql": sql, "row_count": row_count}
