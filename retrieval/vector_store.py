"""
Vector Store module.
Manages embeddings and FAISS index for the metadata registry, providing semantic search capabilities.
"""
import json
import os
import sys

import numpy as np
import faiss

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "metadata"))
from registry import build_registry, table_to_embedding_text  # noqa: E402

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
HERE = os.path.dirname(__file__)
INDEX_PATH = os.path.join(HERE, "table_index.faiss")
META_PATH = os.path.join(HERE, "table_index_meta.json")


class TableRetriever:
    """Wraps a FAISS index over embedded table-metadata text."""

    def __init__(self, model_name=EMBED_MODEL_NAME):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self.index = None
        self.table_names = []
        self.registry_by_table = {}

    def build(self, registry=None):
        if registry is None:
            registry = build_registry()
        texts = [table_to_embedding_text(e) for e in registry]
        self.table_names = [e["table_name"] for e in registry]
        self.registry_by_table = {e["table_name"]: e for e in registry}

        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        embeddings = np.asarray(embeddings, dtype="float32")

        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)  # inner product on normalized vectors = cosine similarity
        self.index.add(embeddings)

        faiss.write_index(self.index, INDEX_PATH)
        with open(META_PATH, "w") as f:
            json.dump({"table_names": self.table_names}, f)
        print(f"Built FAISS index over {len(self.table_names)} tables -> {INDEX_PATH}")

    def load(self):
        self.index = faiss.read_index(INDEX_PATH)
        with open(META_PATH) as f:
            self.table_names = json.load(f)["table_names"]
        registry = build_registry()
        self.registry_by_table = {e["table_name"]: e for e in registry}

    def search(self, question, top_k=5):
        """Returns [(table_name, score), ...] sorted by descending relevance."""
        q_emb = self.model.encode([question], normalize_embeddings=True, show_progress_bar=False)
        q_emb = np.asarray(q_emb, dtype="float32")
        scores, indices = self.index.search(q_emb, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self.table_names[idx], float(score)))
        return results

    def get_table_metadata(self, table_name):
        return self.registry_by_table.get(table_name)


if __name__ == "__main__":
    retriever = TableRetriever()
    retriever.build()

    test_questions = [
        "Which customers jointly own the same account?",
        "Show me flagged card transactions that turned out to be false positives",
        "What's the current interest rate on savings accounts?",
        "List employees who report to a regional manager",
        "How much did each loan borrower pay in late fees last year?",
    ]
    for q in test_questions:
        print(f"\nQ: {q}")
        for table, score in retriever.search(q, top_k=4):
            print(f"    {score:.3f}  {table}")
