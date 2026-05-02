from __future__ import annotations

import os
import anthropic

from hockey.chat.claude_client import _SCHEMA, _SYSTEM_SQL, _SYSTEM_ANSWER

#_MODEL = "claude-sonnet-4-6"
_MODEL = "claude-haiku-4-5-20251001"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def sql_from_question(question: str, history: list[dict]) -> str:
    messages = []
    for turn in history:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({"role": "user", "content": question})

    response = _client().messages.create(
        model=_MODEL,
        max_tokens=512,
        system=_SYSTEM_SQL,
        messages=messages,
    )
    return _strip_markdown(response.content[0].text)


def answer_from_result(question: str, sql: str, rows: list, columns: list) -> str:
    if rows:
        header = " | ".join(columns)
        data_lines = [header, "-" * len(header)]
        for row in rows[:100]:
            data_lines.append(" | ".join("" if v is None else str(v) for v in row))
        result_text = "\n".join(data_lines)
    else:
        result_text = "(no rows returned)"

    content = f"Question: {question}\n\nSQL:\n{sql}\n\nResults:\n{result_text}"

    response = _client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM_ANSWER,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text.strip()
