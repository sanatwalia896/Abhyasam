import asyncio
import httpx
import json
import os
from datetime import datetime
from tabulate import tabulate

# Correct imports for recent RAGAS versions
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,      # How relevant the answer is to the question
    faithfulness,          # How faithful the answer is to the context (hallucination check)
)
from datasets import Dataset

# ========================= CONFIG =========================
API_BASE = "http://localhost:8000"
TEST_PAGE_TITLE = "Model Context Protocol"
METRICS_FILE = "rag_metrics_results.json"

TEST_QUERIES = [
    "What is the Model Context Protocol?",
    "How does MCP define tools?",
    "What is the purpose of Prompts in MCP?",
]


async def get_rag_response(client, query: str):
    try:
        resp = await client.post(
            f"{API_BASE}/api/chat",
            json={
                "question": query,
                "session_id": "metrics_run",
                "page_title": TEST_PAGE_TITLE
            },
            timeout=60.0
        )
        data = resp.json()
        answer = data.get("answer", "")
        # Currently using page_title as context (weak). Improve later when /api/chat returns real chunks
        contexts = [data.get("page_title", TEST_PAGE_TITLE)]
        
        return {"answer": answer, "contexts": contexts}
    except Exception as e:
        print(f"   ❌ API call failed for '{query}': {e}")
        return {"answer": "", "contexts": []}


async def run_evaluation():
    print("🚀 Starting RAG Metrics Evaluation (RAGAS - Reference Free)...\n")

    async with httpx.AsyncClient(timeout=None) as client:
        questions = []
        answers = []
        contexts_list = []

        for query in TEST_QUERIES:
            print(f"📝 Query: {query}")
            result = await get_rag_response(client, query)

            if not result["answer"].strip():
                print("   Skipped (empty answer)\n")
                continue

            questions.append(query)
            answers.append(result["answer"])
            contexts_list.append(result["contexts"])

            print(f"   Answer received ({len(result['answer'])} characters)\n")

    if not questions:
        print("❌ No answers received from your API.")
        return []

    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts_list
    })

    print("🔍 Running evaluation with answer_relevancy + faithfulness...\n")

    try:
        result = evaluate(
            dataset=dataset,
            metrics=[answer_relevancy, faithfulness]
        )

        final_results = []
        for i in range(len(result["question"])):
            final_results.append({
                "timestamp": datetime.now().isoformat(),
                "query": result["question"][i],
                "answer_relevancy": round(float(result.get("answer_relevancy", [0])[i]), 3),
                "faithfulness": round(float(result.get("faithfulness", [0])[i]), 3),   # Higher = better (less hallucination)
                "answer_length": len(result["answer"][i])
            })

        return final_results

    except Exception as e:
        print(f"❌ RAGAS evaluation failed: {e}")
        print("   This often happens if no LLM is configured for RAGAS.")
        return []


def save_and_print_report(results):
    timestamp = datetime.now().isoformat()

    print("\n" + "=" * 110)
    print(" " * 40 + "ABHYASAM RAG METRICS REPORT")
    print("=" * 110)

    if not results:
        print("No metrics were generated.")
    else:
        table_data = []
        for r in results:
            table_data.append([
                r["query"][:65] + "..." if len(r["query"]) > 65 else r["query"],
                r["answer_relevancy"],
                r["faithfulness"],
                r["answer_length"]
            ])

        print(tabulate(table_data,
                       headers=["Query", "Answer Relevancy", "Faithfulness", "Answer Length"],
                       tablefmt="grid",
                       floatfmt=".3f"))

    # Save to JSON (keeps history)
    try:
        entry = {
            "run_timestamp": timestamp,
            "run_id": f"run_{int(datetime.now().timestamp())}",
            "rag_metrics": results
        }

        if os.path.exists(METRICS_FILE):
            with open(METRICS_FILE, "r") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = [history]
            history.append(entry)
        else:
            history = [entry]

        with open(METRICS_FILE, "w") as f:
            json.dump(history, f, indent=2)

        print(f"\n✅ Saved to → {METRICS_FILE}  (Total runs: {len(history)})")
    except Exception as e:
        print(f"Failed to save JSON: {e}")

    print("=" * 110)


if __name__ == "__main__":
    results = asyncio.run(run_evaluation())
    save_and_print_report(results)
    print("\n🎉 Done! Use rag_metrics_results.json for your visualizations.")