import pytest
import httpx
import time
import numpy as np
from tabulate import tabulate
import asyncio
import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

from opik.evaluation.metrics import Hallucination, AnswerRelevance

load_dotenv("backend/.env")

logging.getLogger("httpx").setLevel(logging.WARNING)

API_BASE = "http://localhost:8000"
TEST_PAGE_TITLE = "Model Context Protocol"

TEST_QUERIES = [
    {"query": "What is the Model Context Protocol?", "expected_keywords": ["protocol", "context", "model"]},
    {"query": "How does MCP define tools?", "expected_keywords": ["tools"]},
    {"query": "What is the purpose of Prompts in MCP?", "expected_keywords": ["prompts", "mcp"]},
]

metrics_store = {
    "regression": [],
    "latency": {},
    "rag_metrics": []
}

METRICS_FILE = "opik_rag_metrics.json"


@pytest.fixture(scope="session")
def rag_metrics():
    groq_model = "groq/llama-3.3-70b-versatile"
    return {
        "relevance": AnswerRelevance(model=groq_model, temperature=0.0, track=False),
        "hallucination": Hallucination(model=groq_model, temperature=0.0, track=False),
    }


@pytest.mark.asyncio
async def test_regression_endpoints():
    async with httpx.AsyncClient(timeout=None) as client:
        endpoints = [
            (f"{API_BASE}/api/notion-pages", "GET", None),
            (f"{API_BASE}/api/chat", "POST", {"question": "Hello", "session_id": "test_reg", "page_title": TEST_PAGE_TITLE}),
            (f"{API_BASE}/api/start-quiz", "POST", {"num_questions": 1, "session_id": "test_quiz", "page_title": TEST_PAGE_TITLE}),
            (f"{API_BASE}/api/submit-quiz-answer", "POST", {"answer": "I don't know", "session_id": "test_quiz"}),
            (f"{API_BASE}/api/generate-flashcards", "POST", {"topic_query": "Basics", "num_batches": 1, "flashcards_per_batch": 1, "page_title": TEST_PAGE_TITLE}),
            (f"{API_BASE}/api/flashcards", "GET", None),
        ]

        for url, method, payload in endpoints:
            if method == "GET":
                r = await client.get(url)
            else:
                r = await client.post(url, json=payload)
            status = "PASS" if r.status_code == 200 else f"FAIL({r.status_code})"
            name = f"{method} {url.split('/')[-1]}"
            metrics_store["regression"].append((name, status))


@pytest.mark.asyncio
async def test_latency():
    endpoints = [
        ("POST /api/chat", f"{API_BASE}/api/chat", {"question": "Summarize this page", "session_id": "latency", "page_title": TEST_PAGE_TITLE}),
        ("POST /api/start-quiz", f"{API_BASE}/api/start-quiz", {"num_questions": 1, "session_id": "latency", "page_title": TEST_PAGE_TITLE}),
    ]

    async with httpx.AsyncClient(timeout=None) as client:
        for name, url, payload in endpoints:
            times = []
            for _ in range(3):
                start = time.time()
                await client.post(url, json=payload)
                times.append((time.time() - start) * 1000)

            metrics_store["latency"][name] = {
                "mean_ms": round(np.mean(times), 2),
                "p95_ms": round(np.percentile(times, 95), 2),
            }


@pytest.mark.asyncio
async def test_rag_metrics(rag_metrics):
    """RAG Metrics: Relevance + Hallucination + Context Utilization"""
    async with httpx.AsyncClient(timeout=None) as client:
        for test in TEST_QUERIES:
            query = test["query"]

            r = await client.post(f"{API_BASE}/api/chat", json={
                "question": query,
                "session_id": "rag_test",
                "page_title": TEST_PAGE_TITLE
            })

            data = r.json()
            answer = data.get("answer", "")
            context = [data.get("page_title", TEST_PAGE_TITLE)]

            try:
                rel = rag_metrics["relevance"].score(input=query, output=answer, context=context)
                hal = rag_metrics["hallucination"].score(input=query, output=answer, context=context)

                relevance_score = rel.value
                hallucination_score = hal.value

                context_text = " ".join(context)
                context_util = len(answer) / (len(context_text) + 1) if context_text.strip() else 0.0
                context_util = min(1.0, max(0.0, context_util))

            except Exception as e:
                print(f"⚠️ Opik failed for '{query[:60]}...': {e}")
                relevance_score = None
                hallucination_score = None
                context_util = None

            metrics_store["rag_metrics"].append({
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "relevance_score": round(relevance_score, 3) if relevance_score is not None else None,
                "hallucination_score": round(hallucination_score, 3) if hallucination_score is not None else None,
                "hallucination_percent": round((hallucination_score or 0) * 100, 1),
                "context_utilization": round(context_util, 3) if context_util is not None else None,
                "answer_length": len(answer)
            })


# ====================== RUN TESTS + SHOW REPORT ======================
if __name__ == "__main__":
    print("🚀 Starting Abhyasam RAG Tests...\n")

    # Run the tests
    pytest.main([
        "-q",
        "--disable-warnings",
        "--asyncio-mode=auto",
        __file__
    ])

    # ====================== PRINT REPORT AFTER TESTS ======================
    timestamp = datetime.now().isoformat()

    print("\n" + "="*100)
    print(" " * 38 + "ABHYASAM RAG METRICS REPORT")
    print("="*100)

    if not metrics_store["rag_metrics"]:
        print("❌ No RAG metrics collected. Check if tests ran properly.")
    else:
        table_data = []
        for m in metrics_store["rag_metrics"]:
            table_data.append([
                m["query"][:62] + "..." if len(m["query"]) > 62 else m["query"],
                m.get("relevance_score") or "N/A",
                f"{m.get('hallucination_percent', 0)}%",
                m.get("context_utilization") or "N/A",
                m.get("answer_length", 0)
            ])

        print(tabulate(table_data,
                       headers=["Query", "Relevance Score", "Hallucination %", "Context Util", "Answer Length"],
                       tablefmt="grid",
                       floatfmt=".3f"))

    # Save to JSON
    try:
        final_data = {
            "run_timestamp": timestamp,
            "run_id": f"rag_run_{int(time.time())}",
            "regression": metrics_store["regression"],
            "latency": metrics_store["latency"],
            "rag_metrics": metrics_store["rag_metrics"]
        }

        if os.path.exists(METRICS_FILE):
            with open(METRICS_FILE, "r") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = [history]
            history.append(final_data)
        else:
            history = [final_data]

        with open(METRICS_FILE, "w") as f:
            json.dump(history, f, indent=2)

        print(f"\n✅ Metrics saved successfully to: {METRICS_FILE}")
        print(f"   You can now use this file in your reports or visualization.")
    except Exception as e:
        print(f"❌ Failed to save JSON: {e}")

    print("\n" + "="*100)
    print(f"✅ Test Run Completed at: {timestamp}")
    print("="*100)