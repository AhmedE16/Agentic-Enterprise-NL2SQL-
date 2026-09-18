"""
Sub-Schema Extractor module.
Expands semantic search results through known relationships to build a complete, resolvable sub-schema for SQL generation.
"""
import re


def _referenced_tables(relationship_lines, known_tables):
    """Pull out table names mentioned in relationship notes via regex on
    'table.column' patterns, filtered to tables that actually exist."""
    found = set()
    for line in relationship_lines:
        for match in re.findall(r"\b([a-z_]+)\.[a-z_]+", line):
            if match in known_tables:
                found.add(match)
    return found


def extract_subschema(question, retriever, top_k=5, score_threshold=0.15, max_tables=8):
    """
    Args:
        question: natural language question
        retriever: a loaded TableRetriever (see retrieval/vector_store.py)
        top_k: how many tables to pull directly from semantic search
        score_threshold: below this similarity, drop unless pulled in via FK expansion
        max_tables: hard cap on total tables included in the sub-schema

    Returns: dict with 'tables' (list of table metadata dicts included),
             'schema_text' (the formatted string for the prompt),
             'routing' (raw search results for transparency/debugging).
    """
    raw_hits = retriever.search(question, top_k=top_k)
    known_tables = set(retriever.table_names)

    selected = set()
    for table, score in raw_hits:
        if score >= score_threshold:
            selected.add(table)
    if not selected and raw_hits:
        selected.add(raw_hits[0][0])  # always keep at least the single best match

    # one-hop expansion through relationships, to keep join paths resolvable
    expansion = set()
    for table in list(selected):
        meta = retriever.get_table_metadata(table)
        if meta:
            expansion |= _referenced_tables(meta["relationships"], known_tables)
    selected |= expansion

    if len(selected) > max_tables:
        # keep the highest-scoring ones first, then fill with expansion tables
        scored_order = [t for t, _ in raw_hits if t in selected]
        remaining = [t for t in selected if t not in scored_order]
        selected = set((scored_order + remaining)[:max_tables])

    tables_meta = [retriever.get_table_metadata(t) for t in selected if retriever.get_table_metadata(t)]
    # stable, readable order
    tables_meta.sort(key=lambda e: e["table_name"])

    schema_text = format_schema_text(tables_meta)
    return {
        "tables": tables_meta,
        "schema_text": schema_text,
        "routing": raw_hits,
        "selected_tables": sorted(t["table_name"] for t in tables_meta),
    }


def format_schema_text(tables_meta):
    blocks = []
    for t in tables_meta:
        col_lines = [f"    {c['name']} {c['type']}  -- {c['description']}" for c in t["columns"]]
        rel_lines = [f"    {r}" for r in t["relationships"]]
        sample = t["sample_rows"][:2]
        block = (
            f"TABLE {t['table_name']}\n"
            f"  Description: {t['description']}\n"
            f"  Columns:\n" + "\n".join(col_lines) + "\n"
            f"  Relationships:\n" + ("\n".join(rel_lines) if rel_lines else "    (none)") + "\n"
            f"  Sample rows: {sample}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "retrieval"))
    from vector_store import TableRetriever

    retriever = TableRetriever()
    retriever.build()

    q = "Which flagged card transactions turned out to be confirmed fraud, and at which merchants?"
    result = extract_subschema(q, retriever)
    print("Question:", q)
    print("Routing scores:", result["routing"])
    print("Selected tables:", result["selected_tables"])
    print("\n--- Sub-schema text ---\n")
    print(result["schema_text"])
