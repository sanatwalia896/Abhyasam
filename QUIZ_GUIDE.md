# MCQ quizzes

Start the API from `backend` using `python3 -m uvicorn main:app --reload`.
Open http://localhost:8000/quiz.html. The API serves the UI directly, including
inside Docker. The home page is at http://localhost:8000/index.html.
Alternatively serve the frontend with `python3 -m http.server 3000 --directory frontend`
from the repository root and open http://localhost:3000/quiz.html.
All pages load the shared `/js/config.js`; on port 3000 it targets the backend
on port 8000, and when served by the backend it uses the same origin.

The library and question navigation take inspiration from
https://github.com/sanatwalia896/Hyperverge_quiz_preparation.

## Generate, save, and practice

Choose a synced page and question count, optionally narrow the subject and name the set,
and click Generate & save. The UI reports the requested count, source capacity,
and actual generated count. Select Start quiz on a saved set to practice without
an LLM call. Navigate freely, bookmark questions, submit, review explanations,
or retake. Scores are calculated by the backend from saved correct answers.

Question sets live in `gs://<GCS_BUCKET_NAME>/quiz/question_sets/`. New objects
use reusable names such as `slot-01.json` through `slot-10.json`. Empty legacy
objects are reused first, preserving their original names. Filled objects remain usable.
Renaming changes the displayed title while preserving the stable object ID.
The library has a 10-set limit. Clear a set to create room. Export downloads
JSON from the GCS-backed API. Local JSON uploads are removed. Loading a set or
submitting answers always downloads its JSON from GCS; there is no local MCQ
file fallback. The legacy `/api/questions` route requires `set_id` and also
downloads from GCS. The page selector reads `sync_state.json` from GCS.

Flashcards have a separate limit of 10 decks and a cloud-backed library with
load/clear controls. The API checks capacity before generating cards and checks
again while holding a GCS collection lease before saving. MCQ creation uses the
same guarded final count check, so competing Cloud Run instances cannot both
take the last free slot during a normal save. Abandoned leases expire after ten
minutes. Existing objects are never silently evicted. Older libraries already
above ten must be reduced manually before any further creation.

The REST `DELETE` endpoints now CLEAR content without a GCS delete call. A quiz
becomes `{"id":"slot-01","questions":[],"empty":true}`; a deck becomes the
equivalent empty `flashcards` object. These are valid JSON, not zero-byte files.
Cleared slots are hidden from the library and return 404 if opened. Generation
reuses the same filename. Repeated clears do not rewrite already empty content.
The coordination lease objects are also overwritten and reused.

Replacement quizzes have a new revision. The UI submits the revision with its
answers, and the API returns 409 if the slot has since been reused. This prevents
scoring an old attempt against a new quiz.

Reusing filenames does NOT guarantee lower GCS charges: soft delete also applies
to overwrites, and Object Versioning may preserve earlier generations. This
change does not modify bucket protection policies.

All four study screens share the bright blue theme and a navigation bar linking
to each other. Selecting a page carries that page title to the other modes.

## Capacity and quality

The generator retrieves up to 500 chunks matching the selected page (or across
synced pages when no page is selected), ranked by the topic query. It removes
empty and duplicate text within each page, groups by `page_id`, and processes
chunks in `chunk_index` order. Legacy sources without positions fall back to
retrieval order; re-ingest them to restore source order. Capacity = 2 × unique
retrieved chunks is only an approximate upper bound. A request for 100 with 15
chunks can generate at most 30 questions, and often fewer.

After every chunk, the service checks the accepted count. Once the requested
count is reached, it stops processing remaining chunks, skips final buffer-only
attempts, saves the completed quiz once, and returns its ID. A test requests ten
from twenty source chunks and verifies that no calls happen after ten accepted
questions. No repeated GCS writes are needed for per-chunk progress.

For each chunk, the LLM chooses `generate`, `defer`, or `skip`. Generation is
optional, and at most two questions are accepted per step. Titles, subtitles,
document coverage trivia, and headings alone should be skipped. Meaningful
incomplete explanations can be deferred. Questions must have four distinct
nonempty options, a valid answer, an explanation, and `source_chunk_ids` drawn
only from the current passage and that page's pending context. Combined-evidence
questions cite every supporting passage; one is assigned as the primary source
for the two-question accounting budget. Exact and near-text duplicates and
obvious document-trivia questions are rejected.

`PageBuffer` is a Python list in request memory, NEVER a GCS blob or session.
Each page has a separate buffer of at most four original passages / 6,000
characters. A passage expires after five subsequent chunks of that page.
Retaining it does not reset its age. The backend validates requested source IDs;
the model cannot insert fabricated replacement text. Accepted questions consume
their evidence unless it is explicitly retained for further use. The generator
can drop irrelevant pending passages. Each page gets one final buffer-only
attempt, then its buffer is cleared. A new generation request starts empty.

Only accepted questions and aggregate decision counts are stored in the quiz
JSON. Existing quizzes are not rewritten. Interrupted requests lose their
temporary buffers. Text matching is a heuristic and cannot identify every
semantic duplicate; source grounding and educational quality still require
live evaluation. No usable output means no empty set is saved.

This sequential flow makes more LLM calls than the former five-chunk batches.
Large requests may be slow; a 500-chunk scan is not guaranteed to complete within
the Cloud Run request timeout. Start with a small page and question count.

Groq calls share a rolling 60-second budget across study modes within each backend process. The SDK's
automatic retries are disabled to avoid nested retry loops; the wrapper retries
429 responses at most twice, respects Retry-After, and bounds waiting to 60
seconds per call. Long limits return HTTP 429 with Retry-After. Default pacing
is 20 requests/minute and 8,000 tokens/minute; configure the matching environment
variables for your own account. Calls run immediately while budget remains.
Before a call the limiter estimates input and likely output from recent responses;
afterward it charges the actual total token usage, rather than the full maximum
completion allowance. It only waits for the rolling budget or provider Retry-After,
not a fixed 20-second interval. Estimates can differ from Groq accounting, and
this process cannot enforce quotas across other processes or applications.
MCQ output is capped at 2,048 tokens instead
of 8,192 and only the latest 20 question texts are repeated in the prompt; all
accepted questions still participate in backend deduplication.

Flashcards use the centered two-sided card viewer with a CSS 3D flip, previous/
next controls and a counter. Enter/Space activate the native flip button. The
animation is disabled when the user requests reduced motion. Notion-page
selection, the blue theme, cloud decks and clear/reuse semantics remain available.

Generation uses `GROQ_MODEL=openai/gpt-oss-20b`. Retrieval uses the same
`PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE`, and FastEmbed model as ingestion.
GCS credentials must be available to the API process, including inside Docker.

## API

- `POST /api/mcq/sets/generate`: `{ "topic_query": "JavaScript", "num_questions": 100, "page_title": null, "title": "JavaScript revision" }`
- `GET /api/mcq/sets`: list saved sets.
- `GET /api/mcq/sets/{id}`: load/export a set.
- `PATCH /api/mcq/sets/{id}`: `{ "title": "New title" }`.
- `DELETE /api/mcq/sets/{id}`: delete a set.
- `POST /api/mcq/sets/{id}/submit`: `{ "answers": { "q1": "B", "q2": "A" } }`.

The existing `/api/generate-quiz` batch-count endpoint forwards to the same MCQ
service for compatibility. `/api/question-sets` aliases remain available.
Short-answer practice has its own UI at `/short-answer.html` and endpoints
`/api/short-answer/sessions` and `/api/short-answer/answers`. Existing short-answer
routes remain available as aliases. Flashcards now have a page/count selector,
save a separate deck in GCS and load it by `deck_id`. The browser receives a
unique session ID per tab for chat and short-answer sessions, persisted in GCS.

For backend-only Cloud Run deployment and a separate Vercel frontend, follow
[DEPLOY_CLOUD_RUN.md](DEPLOY_CLOUD_RUN.md).

## Verification

Run `python3 -m unittest discover -s code_testing -p 'test_mcq*.py'`.
Also run `python3 -m unittest discover -s code_testing -p test_quiz_storage.py`.
Run `python3 -m unittest discover -s code_testing -p test_chunk_buffer.py` for
buffer isolation, expiration, final attempts, trivia rejection and JSON parsing.
Run `python3 -m unittest discover -s code_testing -p test_storage_slots.py` for
clear/reuse behavior, limits, and checking that no GCS delete operation is issued.
These tests use fake providers to check generation capacity, validation,
deduplication, import, request schemas, and backend scoring without API charges
or cloud writes. Malformed model JSON is retried once in JSON mode; repeated
failure returns a generation error. Invalid GCS JSON returns a distinct storage
error. Live LLM quality and GCS permissions require a real generation
run with configured credentials.
