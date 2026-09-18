"""
SQL Generator Agent module.
Generates SQLite-dialect SQL from natural language questions and schema context.
"""
import os
import re

from openai import OpenAI

GROQ_MODEL = "qwen2.5-coder:7b"  # using local ollama model
BASE_URL = "http://localhost:11434/v1"

SYSTEM_PROMPT = """You are a senior data engineer who writes precise, secure SQL for SQLite.

Rules:
- Use ONLY the tables and columns given in the schema below. Never invent columns or tables.
- Write a SINGLE SQLite-dialect SQL query that answers the question.
- Pay close attention to notes in table/column descriptions and relationships — they flag
  ambiguous terms (e.g. current_balance vs available_balance), polymorphic references
  (entity_type/applies_to_type columns that determine which table a FK points to), and
  temporal/"as of" logic (status history, rate history) that naive queries get wrong.
- Never use SELECT * in production-style output; select only the columns needed to answer
  the question, plus any identifying columns (names/ids) that make the result readable.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any statement that mutates data —
  this is a read-only analytics query.
- Return ONLY the SQL query, no explanation, no markdown code fences.
"""

FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|ATTACH|PRAGMA)\b", re.IGNORECASE
)


def _client():
    api_key = os.environ.get("GROQ_API_KEY", "ollama")
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def _strip_code_fences(text):
    text = text.strip()
    match = re.search(r"```(?:sql)?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    else:
        text = re.sub(r"^```(sql)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_sql(question, schema_text, client=None, prior_attempt=None, prior_error=None):
    """
    Generates a SQL query. If prior_attempt/prior_error are provided, this is
    a self-correction retry: the prompt includes the failed query and the
    exact database error so the model can fix it.
    """
    client = client or _client()

    user_prompt = f"Database schema (only these tables/columns exist):\n\n{schema_text}\n\nQuestion: {question}\n"
    if prior_attempt and prior_error:
        user_prompt += (
            f"\nYour previous attempt failed:\n```sql\n{prior_attempt}\n```\n"
            f"Database error:\n{prior_error}\n\n"
            f"Fix the query. Return only the corrected SQL."
        )

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    sql = _strip_code_fences(response.choices[0].message.content)

    if FORBIDDEN_PATTERN.search(sql):
        raise ValueError(f"Generated query contains a forbidden statement, refusing to execute:\n{sql}")

    return sql
