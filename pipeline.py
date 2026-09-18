"""
NL2SQL Pipeline orchestration module.
Handles semantic routing, sub-schema extraction, SQL generation, and execution.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "retrieval"))

from vector_store import TableRetriever
from subschema import extract_subschema
from executor import execute_with_self_correction
from formatter import format_output

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "db", "bank.db")

GROQ_MODEL = "qwen2.5-coder:7b"
BASE_URL = "http://localhost:11434/v1"


class NL2SQLPipeline:
    def __init__(self, db_path=DB_PATH, build_index=False, use_llm=True):
        self.retriever = TableRetriever()
        if build_index:
            self.retriever.build()
        else:
            try:
                self.retriever.load()
            except Exception as e:
                print(f"No cached index found or error loading ({e}) — building one now.")
                self.retriever.build()

        self.db_path = db_path
        self.client = None
        if use_llm:
            from openai import OpenAI
            api_key = os.environ.get("GROQ_API_KEY", "ollama")
            self.client = OpenAI(api_key=api_key, base_url=BASE_URL)

    def ask(self, question, top_k=5, max_retries=3, verbose=True):
        # [1] + [2] retrieve and build minimal sub-schema
        sub = extract_subschema(question, self.retriever, top_k=top_k)
        if verbose:
            print(f"Routed to tables: {sub['selected_tables']}")

        # [3] + [4] generate SQL, execute, self-correct on error
        result = execute_with_self_correction(
            question, sub["schema_text"], self.db_path, client=self.client, max_retries=max_retries
        )
        if verbose:
            for i, a in enumerate(result["attempts"], 1):
                status = "OK" if a["error"] is None else f"ERROR: {a['error']}"
                print(f"  attempt {i}: {status}")
                print(f"    SQL: {a['sql']}")

        if not result["success"]:
            return {
                "question": question,
                "sql": result["sql"],
                "success": False,
                "summary": "The query could not be executed successfully after retries.",
                "table": None,
                "routing": sub,
                "attempts": result["attempts"],
            }

        # [5] format output
        formatted = format_output(question, result["columns"], result["rows"], client=self.client, model=GROQ_MODEL)

        return {
            "question": question,
            "sql": result["sql"],
            "success": True,
            "summary": formatted["summary"],
            "table": formatted["table"],
            "routing": sub,
            "attempts": result["attempts"],
        }


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Which employees manage the most branches?"
    pipeline = NL2SQLPipeline()
    result = pipeline.ask(question)

    print("\n" + "=" * 60)
    print("QUESTION:", result["question"])
    print("=" * 60)
    print("\nSQL:\n", result["sql"])
    print("\nSummary:\n", result["summary"])
    if result["table"] is not None:
        print("\nTable:\n", result["table"])
