"""
Output Formatter module.
Formats raw database results into natural language summaries and tabular structures.
"""
import pandas as pd

SYSTEM_PROMPT = """You answer a user's question in 1-3 plain sentences, based ONLY on the query
result data given to you. Be direct and specific — cite actual numbers/names from the data.
Do not mention SQL, tables, or databases. If the result is empty, say so plainly."""


def format_output(question, columns, rows, client=None, model="qwen2.5-coder:7b", max_preview_rows=25):
    df = pd.DataFrame(rows, columns=columns) if columns else pd.DataFrame()

    if client is None:
        # no LLM client provided — return the table with a simple templated summary
        summary = _fallback_summary(df)
        return {"summary": summary, "table": df}

    preview = df.head(max_preview_rows).to_dict(orient="records")
    user_prompt = f"Question: {question}\n\nResult data ({len(df)} total rows, showing up to {max_preview_rows}):\n{preview}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    summary = response.choices[0].message.content.strip()
    return {"summary": summary, "table": df}


def _fallback_summary(df):
    if df.empty:
        return "No rows matched this query."
    return f"Returned {len(df)} row(s) across {len(df.columns)} column(s): {', '.join(df.columns)}."
