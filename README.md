# Agentic NL2SQL — RAG over a 20-Table Banking Schema

Translates natural language questions into executable SQL over a deliberately
hard 20-table banking database, using a RAG-style metadata registry for
semantic table routing, minimal sub-schema extraction, an LLM SQL generator,
an execution loop with automatic self-correction on runtime errors, and a
natural-language + tabular output formatter.

## Why the data is hard

- **Joint accounts**: ownership goes through `account_holders`, not a direct FK.
- **Ambiguous terms**: `current_balance` vs `available_balance`; `status` on
  `accounts` can be stale relative to `account_status_history`.
- **Polymorphic references**: `fraud_flags.entity_type` and
  `interest_rate_history.applies_to_type` determine which table the row
  actually points to — no single clean foreign key.
- **Dual representation**: a transfer exists both as one row in `transfers`
  and as two linked rows in `transactions` — summing both double-counts.
- **Self-referential hierarchy**: `employees.manager_id` (up to 3 levels).
- **Temporal data**: overlapping interest rate windows, multi-currency
  transactions needing `exchange_rates` for a specific date, historical risk
  scores where "current" means "latest by date".

## Architecture

```
question -> [1] semantic router (FAISS + sentence-transformers over the
                 metadata registry)
         -> [2] sub-schema extractor (top-k matches + one-hop FK expansion)
         -> [3] SQL generator agent (LLM, SQLite dialect, read-only)
         -> [4] executor + self-correction loop (retries with the exact
                 DB error fed back to the generator)
         -> [5] output formatter (NL summary + pandas table)
```

## Project layout

```
schema/schema.sql          20-table DDL with FK constraints and comments
data/generate_data.py      synthetic data generator (Faker, seeded)
db/build_db.py             loads schema + CSVs into SQLite (db/bank.db)
metadata/registry.py       hand-authored table/column docs + sample rows
retrieval/vector_store.py  embeds the registry, builds/loads a FAISS index
agents/subschema.py        semantic routing -> minimal join-complete schema
agents/sql_generator.py    LLM call that writes the SQL
agents/executor.py         runs SQL, retries with self-correction on error
agents/formatter.py        LLM call that summarizes results in plain English
pipeline.py                ties it all together, CLI entry point
notebook/nl2sql_walkthrough.ipynb   exploratory notebook, cell by cell
```

## Setup

1. Install requirements:
```bash
pip install -r requirements.txt
pip install streamlit
```

2. Start your local Ollama server with the `qwen2.5-coder:7b` model:
```bash
ollama serve
# In a separate terminal window:
ollama pull qwen2.5-coder:7b
```

## Run it

1. Generate synthetic data and build the SQLite database (only needed once):
```bash
python data/generate_data.py
python db/build_db.py
```

2. Launch the Streamlit Web UI:
```bash
streamlit run app.py
```

You can now open `http://localhost:8501` in your browser and ask questions in plain English!

## Architecture Details

- **LLM**: Powered locally by `qwen2.5-coder:7b` via Ollama.
- **Embeddings**: Local `sentence-transformers/all-MiniLM-L6-v2`.
- **Vector store**: FAISS (in-memory/local).
