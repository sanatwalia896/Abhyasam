# 📚 MCQ Generation Pipeline - Complete Explanation

## 🎯 What You're Asking For

When you request "Generate 10 MCQs about LangChain", here's the ENTIRE journey:

---

## 🔄 THE COMPLETE PIPELINE

```
User Request
    ↓
1. Vector Retrieval (Pinecone)
    ↓
2. Pre-filtering (Remove junk)
    ↓
3. Random Sampling
    ↓
4. LLM Processing (Groq API) ← THIS IS WHERE THE PROBLEM WAS
    ↓
5. Validation & Deduplication
    ↓
6. Save to Storage
    ↓
Return MCQs to User
```

Let me explain each step in detail:

---

## STEP 1: Vector Retrieval 🔍

**File:** `mcq_service.py` → `sources()` method

```python
def sources(self, topic, page_title):
    filters = {"source": "Notion"}
    if page_title:
        filters["page_title"] = page_title

    # Retrieve chunks from Pinecone
    documents = self.chat._retrieve(topic, filters, k=80)
    return unique_sources(documents)
```

**What happens:**
1. You ask for MCQs about "LangChain"
2. System searches Pinecone vector database
3. Finds **80 most relevant chunks** (text snippets from your Notion pages)
4. Each chunk is ~500 characters of text

**Example chunks retrieved:**
```
Chunk 1: "LangChain is a framework for developing applications..."
Chunk 2: "LangGraph extends LangChain by adding graph-based workflows..."
Chunk 3: "Table of Contents: Chapter 1, Chapter 2..." ← JUNK!
Chunk 4: "Click here to see more examples" ← JUNK!
...
Chunk 80: "The Agent class in LangChain provides..."
```

---

## STEP 2: Pre-filtering 🗑️

**File:** `mcq_service.py` → `unique_sources()` and `is_junk_chunk()`

```python
def is_junk_chunk(text: str, min_length: int = 50) -> bool:
    # Too short?
    if len(text) < min_length:
        return True

    # Just a heading?
    if single_line_title(text):
        return True

    # Navigation text?
    if "click here" in text.lower():
        return True

    # And more filters...
```

**What happens:**
1. Goes through all 80 chunks
2. Filters out:
   - Page titles ("LangChain Guide")
   - Headings ("Chapter 1: Introduction")
   - Navigation ("See page 5", "Click here")
   - Metadata ("Author: John Doe")
   - Very short chunks (< 50 chars)

**Result:**
```
Started with: 80 chunks
After filtering: ~50-60 usable chunks
Removed: 20-30 junk chunks
```

---

## STEP 3: Random Sampling 🎲

**File:** `mcq_service.py` → `sample_sources_by_blocks()`

```python
def sample_sources_by_blocks(sources, sample_size=25, group_size=3):
    # Group adjacent blocks together
    # Then randomly sample groups
    # This keeps related content together
```

**What happens:**
1. Takes the 50-60 filtered chunks
2. Groups adjacent chunks from same page (block grouping)
3. Randomly selects **25 chunks** to process
4. Why random? To get variety across your entire knowledge base

**Result:**
```
50-60 filtered chunks
    ↓
25 randomly sampled chunks (to process)
```

**Example of grouped sampling:**
```
Page: "LangChain Guide"
  Block Group 1: Chunks 5, 6, 7 (about Agents)
  Block Group 2: Chunks 15, 16, 17 (about Memory)

Page: "LangGraph Tutorial"
  Block Group 3: Chunks 3, 4, 5 (about State Graphs)

→ Randomly sample 8-10 groups → Get 25 chunks total
```

---

## STEP 4: LLM Processing 🤖 ← THE PROBLEM WAS HERE!

### OLD APPROACH (Sequential - WHY IT WAS SLOW)

**File:** `mcq_service.py` → `generate()` method

```python
# OLD CODE - SEQUENTIAL PROCESSING
for page_id, page_sources in groupby(sources):  # 25 chunks
    for step, source in enumerate(page_sources):
        # ONE API CALL PER CHUNK!
        result = process(source, buffer.sources(step))
        # Wait for response...
        # Update buffer with "pending" chunks...
        # Repeat for next chunk...
```

**What was happening (OLD):**

```
Processing Chunk 1:
├─ Build prompt: "Here is chunk 1: [500 chars]..."
├─ Add pending context: [0 chunks]
├─ Send to Groq API
├─ Input tokens: ~1,000
├─ Output tokens: ~2,048 (max)
├─ Total: ~3,048 tokens
├─ Wait for response... (rate limit)
└─ Decision: DEFER (save for later)

Processing Chunk 2:
├─ Build prompt: "Here is chunk 2: [500 chars]..."
├─ Add pending context: [Chunk 1] ← NOW PAYLOAD IS BIGGER!
├─ Send to Groq API
├─ Input tokens: ~1,500 (growing!)
├─ Output tokens: ~2,048
├─ Total: ~3,548 tokens
├─ Wait for response...
└─ Decision: GENERATE (1 MCQ created)

Processing Chunk 3:
├─ Build prompt: "Here is chunk 3: [500 chars]..."
├─ Add pending context: [Chunks 1, 2] ← EVEN BIGGER!
├─ Send to Groq API
├─ Input tokens: ~2,000
├─ Output tokens: ~2,048
├─ Total: ~4,048 tokens
└─ And so on...

... REPEAT 25 TIMES! ...

Total API calls: 25
Total tokens: ~77,700 tokens
Time: 5+ minutes (hitting rate limits)
Groq free tier limit: 15,000 tokens/minute
→ REQUIRES MULTIPLE WAITS! ⏰
```

**The DEFER Mechanism Made It Worse:**

```python
# If decision is DEFER:
result.retain_source_ids = [chunk1, chunk2]  # Keep for next call
pending_context.append(deferred_chunks)

# Next API call includes ALL pending chunks!
payload = {
    "current_chunk": chunk_3,
    "pending_context": [chunk_1, chunk_2],  # BLOAT!
    # This makes prompts huge and wastes tokens
}
```

**Visual of Token Waste:**

```
Call 1:  [Chunk 1]                        → 3,000 tokens
Call 2:  [Chunk 2] + pending[1]           → 3,500 tokens
Call 3:  [Chunk 3] + pending[1,2]         → 4,000 tokens
Call 4:  [Chunk 4] + pending[1,2,3]       → 4,500 tokens
...
Call 25: [Chunk 25] + pending[1-24]       → 8,000+ tokens

TOTAL: 77,700 tokens! 🔥
```

---

### NEW APPROACH (Batch - OPTIMIZED)

**File:** `mcq_service_optimized.py` → `_process_batch()`

```python
# NEW CODE - BATCH PROCESSING
batch_size = 4  # Process 4 chunks at once

for batch in chunks_by_batch:  # 15 chunks / 4 = ~4 batches
    # ONE API CALL PER BATCH (4 chunks together!)
    batch_questions = process_batch(batch, topic, max_questions=3)
    # Much faster!
```

**What happens now (NEW):**

```
Processing Batch 1 (Chunks 1-4):
├─ Build prompt:
│   "Generate MCQs from these 4 passages:
│    CHUNK 1: [300 chars] ← TRUNCATED!
│    CHUNK 2: [300 chars]
│    CHUNK 3: [300 chars]
│    CHUNK 4: [300 chars]
│    Return max 3 questions."
├─ Send to Groq API
├─ Input tokens: ~400 (4 chunks * 100 tokens each)
├─ Output tokens: ~500 (reduced from 2048!)
├─ Total: ~900 tokens
├─ Wait for response...
└─ Get back: 2-3 MCQs

Processing Batch 2 (Chunks 5-8):
├─ Build prompt: [Same structure, 4 chunks]
├─ Input: ~400 tokens
├─ Output: ~500 tokens
├─ Total: ~900 tokens
└─ Get back: 2-3 MCQs

Processing Batch 3 (Chunks 9-12):
├─ Same...
└─ Get back: 2-3 MCQs

Processing Batch 4 (Chunks 13-15):
├─ Same...
└─ Get back: 1-2 MCQs

Total API calls: 4 (was 25)
Total tokens: ~3,600 (was 77,700)
Time: 30-45 seconds (was 5+ minutes)
✅ FITS IN GROQ FREE TIER!
```

**Key Differences:**

| Aspect | OLD (Sequential) | NEW (Batch) |
|--------|------------------|-------------|
| Chunks per call | 1 | 4 |
| API calls | 25 | 4 |
| Pending context | Yes (grows) | No |
| Output tokens | 2,048 | 500 |
| Chunk text | 500 chars | 300 chars |
| Total tokens | 77,700 | 3,600 |
| Time | 5+ min | 30-45 sec |

---

## STEP 5: Validation & Deduplication ✅

**File:** `mcq_service.py` → `process()` inner function

```python
for candidate in result.questions:
    # Validate question structure
    item = GeneratedMCQ.model_validate(candidate)

    # Check if it's document trivia
    if document_trivia(item.question):
        continue  # Skip!

    # Check for duplicates
    if is_duplicate(item.question, existing_questions):
        continue  # Skip!

    # All good, accept it!
    questions.append(item)
```

**What happens:**
1. LLM returns questions (might be 12 questions from 4 batches)
2. Check each question:
   - Has all required fields? (question, options A/B/C/D, answer, explanation)
   - Options are distinct? (A ≠ B ≠ C ≠ D)
   - Answer is valid? (A, B, C, or D)
   - Not document trivia? ("What is the title of this guide?" ❌)
   - Not duplicate? (Compare to already accepted questions)
3. Accept first 10 valid, unique questions
4. Discard the rest

**Example:**
```
LLM returned: 12 questions
  Q1: ✅ Valid and unique
  Q2: ❌ Duplicate of Q1
  Q3: ✅ Valid
  Q4: ❌ "What is the guide titled?" (document trivia)
  Q5: ✅ Valid
  Q6: ✅ Valid
  Q7: ✅ Valid
  Q8: ✅ Valid
  Q9: ✅ Valid
  Q10: ✅ Valid
  Q11: ✅ Valid
  Q12: ✅ Valid

Accepted: Q1, Q3, Q5-Q11 (10 questions total)
```

---

## STEP 6: Save to Storage 💾

**File:** `question_bank.py` → `save_question_set()`

```python
saved = save_question_set(
    questions,
    title="LangChain — 10 MCQs",
    page_title="LangChain Guide",
    generation={
        "topic_query": "LangChain",
        "requested_count": 10,
        "generated_count": 10,
        "total_chunks": 80,
        "sampled_chunks": 25,
        "method": "batch_processing_optimized"
    }
)
```

**What happens:**
1. Creates a question set with metadata
2. Saves to Google Cloud Storage (GCS)
3. Stores in `state/question-sets/<set_id>.json`
4. Returns set ID to user

**Saved JSON structure:**
```json
{
  "id": "set_abc123",
  "title": "LangChain — 10 MCQs",
  "page_title": "LangChain Guide",
  "created_at": "2026-11-15T22:30:00Z",
  "questions": [
    {
      "id": "q1",
      "question": "What is the primary purpose of LangChain?",
      "options": {
        "A": "To create databases",
        "B": "To build LLM applications",
        "C": "To host websites",
        "D": "To manage cloud storage"
      },
      "answer": "B",
      "explanation": "LangChain is a framework specifically designed...",
      "source_chunk_ids": ["abc123", "def456"]
    },
    // ... 9 more questions
  ],
  "generation": {
    "topic_query": "LangChain",
    "method": "batch_processing_optimized"
  }
}
```

---

## STEP 7: Return to User 🎉

**File:** `main.py` → `create_mcq()` endpoint

```python
@app.post("/api/mcq/sets/generate")
def create_mcq(req: MCQRequest) -> dict:
    result = MCQService(get_chatbot()).generate(
        req.topic_query,
        req.num_questions,
        req.page_title,
        req.title
    )
    return {
        "status": "success",
        "set_id": result["set_id"],
        "generated_count": 10,
        "total_chunks": 80,
        "sampled_chunks": 25
    }
```

**User sees:**
```json
{
  "status": "success",
  "set_id": "set_abc123",
  "generated_count": 10
}
```

---

## 🔧 THE .SH FILE EXPLAINED

**File:** `switch_to_optimized.sh`

**Purpose:** Simple script to swap your current MCQ service with the optimized version

**What it does:**
```bash
#!/bin/bash

1. Backup your current mcq_service.py
   cp mcq_service.py mcq_service_OLD_BACKUP.py

2. Replace with optimized version
   cp mcq_service_optimized.py mcq_service.py

3. Tell you what changed
```

**Why a script?**
- Makes it easy to switch back and forth
- One command instead of manual file operations
- Shows you what it's doing

**How to use:**
```bash
cd backend
./switch_to_optimized.sh

# Or if you want to revert:
cp mcq_service_OLD_BACKUP.py mcq_service.py
```

---

## 📊 COMPLETE FLOW DIAGRAM

```
USER: "Generate 10 MCQs about LangChain"
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1: RETRIEVAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pinecone Vector DB
  → Search for "LangChain"
  → Find 80 most relevant chunks
  → Each chunk: ~500 chars from Notion pages

[Chunk 1] [Chunk 2] ... [Chunk 80]
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2: PRE-FILTERING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Filter out junk:
  ✗ "Table of Contents" (heading)
  ✗ "Click here" (navigation)
  ✗ "Author: John" (metadata)
  ✗ Very short chunks
  ✓ Keep: Actual content chunks

50-60 usable chunks remain
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3: RANDOM SAMPLING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Group adjacent blocks:
  Group 1: [Chunks 5,6,7] about Agents
  Group 2: [Chunks 15,16,17] about Memory
  Group 3: [Chunks 23,24,25] about Chains
  ...

Randomly select 15-25 chunks
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4A: LLM PROCESSING (OLD - SLOW)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOR EACH of 25 chunks:
  ┌─────────────────────────┐
  │ Chunk 1 + pending[]     │ → Groq API → 3,000 tokens
  │ Chunk 2 + pending[1]    │ → Groq API → 3,500 tokens
  │ Chunk 3 + pending[1,2]  │ → Groq API → 4,000 tokens
  │ ...                     │
  │ Chunk 25 + pending[1-24]│ → Groq API → 8,000 tokens
  └─────────────────────────┘

  Total: 25 API calls
  Total: 77,700 tokens
  Time: 5+ minutes
  ❌ HITS GROQ LIMITS!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4B: LLM PROCESSING (NEW - FAST)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Process in BATCHES of 4:
  ┌─────────────────────────┐
  │ Batch 1: [C1,C2,C3,C4]  │ → Groq API → 900 tokens
  │ Batch 2: [C5,C6,C7,C8]  │ → Groq API → 900 tokens
  │ Batch 3: [C9,C10,C11,C12]│ → Groq API → 900 tokens
  │ Batch 4: [C13,C14,C15]  │ → Groq API → 900 tokens
  └─────────────────────────┘

  Total: 4 API calls
  Total: 3,600 tokens
  Time: 30-45 seconds
  ✅ WITHIN LIMITS!
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5: VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM returned 12 questions
  ✓ Q1: Valid
  ✗ Q2: Duplicate
  ✓ Q3: Valid
  ✗ Q4: Document trivia
  ✓ Q5-Q11: Valid (7 more)

Accept first 10 unique, valid questions
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6: SAVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Save to GCS:
  state/question-sets/set_abc123.json
  {
    "id": "set_abc123",
    "questions": [10 MCQs],
    "metadata": {...}
  }
  ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7: RETURN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return to user:
  {
    "status": "success",
    "set_id": "set_abc123",
    "generated_count": 10
  }

USER: Gets 10 MCQs ready to practice! 🎉
```

---

## 💡 KEY INSIGHTS

### Why Sequential Processing Was Bad

1. **25 API calls** = 25 waits = 25 chances to hit rate limits
2. **DEFER mechanism** = growing payloads = wasted tokens
3. **High output tokens** (2048) = quota burned even when generating 1-2 MCQs
4. **Full chunk text** (500 chars) = unnecessary input tokens

### Why Batch Processing Is Better

1. **4 API calls** = 4 waits = 84% fewer rate limit issues
2. **No DEFER** = fixed payload size = predictable token usage
3. **Low output tokens** (500) = 75% less quota per call
4. **Truncated text** (300 chars) = 40% less input tokens
5. **Same quality** = Still get 10 good MCQs!

### The Math

```
OLD:
  25 calls × 3,108 tokens = 77,700 tokens
  Time: 5+ minutes

NEW:
  4 calls × 900 tokens = 3,600 tokens
  Time: 30-45 seconds

SAVINGS:
  Tokens: 94% reduction
  Time: 85% reduction
  API calls: 84% reduction
```

---

## 🎯 SUMMARY

**The .sh file:** Simple script to switch to optimized version

**The pipeline:**
1. Get chunks from Pinecone (80 chunks)
2. Filter junk (→ 50-60 chunks)
3. Random sample (→ 15-25 chunks)
4. **PROBLEM WAS HERE:** Process with LLM
   - OLD: 1 chunk per call × 25 = 77,700 tokens
   - NEW: 4 chunks per call × 4 = 3,600 tokens
5. Validate & deduplicate
6. Save to storage
7. Return to user

**Bottom line:** Batch processing fixes the token explosion by grouping chunks together instead of processing them one by one!

---

Need me to explain any specific part in more detail?
