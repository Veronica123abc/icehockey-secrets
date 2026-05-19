from __future__ import annotations

import subprocess

_SCHEMA = """
Tables (all foreign keys reference the `id` primary key of the target table):

game(id, sl_id, home_team_id→team.id, away_team_id→team.id, league_id→league.id,
     season, stage, scheduled_time DATETIME, event_status, home_team_goals, away_team_goals)

team(id, sl_id, name, location, display_name, shorthand)

league(id, sl_id, name)

player(id, sl_id, first_name, last_name)

affiliation(id, player_id→player.id, team_id→team.id, game_id→game.id, position)
  -- position: G=goalie, D=defence, F/LW/RW/C=forward

shift(id, player_id→player.id, game_id→game.id, in_time FLOAT, out_time FLOAT)
  -- in_time/out_time in seconds from start of game

event(id, game_id→game.id, sl_id, period, period_time FLOAT, game_time FLOAT,
      name, type, zone, outcome,
      team→team.id, team_in_possession→team.id,
      player_reference_id→player.id,
      expected_goals_all_shots FLOAT, expected_goals_all_shots_grade,
      team_skaters_on_ice, opposing_team_skaters_on_ice,
      score_differential, manpower_situation, x_coord FLOAT, y_coord FLOAT)
  -- name examples: goal, shot, carry, dumpin, pass, whistle, faceoff
  -- zone: oz=offensive zone, dz=defensive zone, nz=neutral zone
  -- expected_goals_all_shots_grade: A=high danger, B=medium, C=low danger

participation(id, league_id→league.id, team_id→team.id, season, sl_team_id)
"""

_SYSTEM_SQL = f"""You are a MySQL expert for a hockey analytics database.
Given a user question, return ONLY a valid SELECT query — no explanation, no markdown, no backticks.
Always add LIMIT 200 unless the query aggregates to a small result set.
Only reference columns that exist in the schema.
The user does not always spell or name leagues, team-names, player-names correctly, wich means
you must often use "LIKE" i the sql WHERE clauses.

Schema:
{_SCHEMA}

Table explanations:
Participation: team participation in one league during one season.
Affiliation: One player is affiliated with one team in one game.

"""

_SYSTEM_ANSWER = """You are a hockey analytics assistant.
The user asked a question, a SQL query was run, and results were returned.
Answer concisely in plain language. If the result set is empty, say so directly.
Do not repeat the SQL or column names unless helpful."""


def _run_claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "claude subprocess failed")
    return result.stdout.strip()


def sql_from_question(question: str, history: list[dict]) -> str:
    history_text = ""
    if history:
        parts = []
        for turn in history:
            parts.append(f"Q: {turn['question']}\nA: {turn['answer']}")
        history_text = "\n\nPrevious conversation:\n" + "\n\n".join(parts)
    prompt = f"{_SYSTEM_SQL}{history_text}\n\nQuestion: {question}"
    return _run_claude(prompt)


def answer_from_result(question: str, sql: str, rows: list, columns: list) -> str:
    if rows:
        header = " | ".join(columns)
        data_lines = [header, "-" * len(header)]
        for row in rows[:100]:
            data_lines.append(" | ".join("" if v is None else str(v) for v in row))
        result_text = "\n".join(data_lines)
    else:
        result_text = "(no rows returned)"

    prompt = f"""{_SYSTEM_ANSWER}

Question: {question}

SQL:
{sql}

Results:
{result_text}"""
    return _run_claude(prompt)
