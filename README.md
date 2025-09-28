# Abhyasam
<!-- Replace with actual logo if available -->

A professional web application for revising Notion notes through interactive quizzes and Q&A sessions. Built with modern technologies to demonstrate full-stack engineering skills, including backend APIs, vector databases, and responsive frontend design.

## Overview

RevisionAI syncs your Notion pages, vectorizes their content for semantic search, and provides two core modes:
- **Quiz Mode**: Generate open-ended or MCQ quizzes to test knowledge.
- **Chat Mode**: Ask questions about your notes for on-demand revision.

The app is designed for desktop and mobile responsiveness, using FastAPI for the backend, Pinecone for vector storage, Groq for LLM inference via LangChain, and vanilla HTML/CSS/JS for the frontend. It's deployable on Vercel or GitHub Pages for the static assets, with the backend on a server like Render or Fly.io.

This project showcases skills in:
- API development and integration (FastAPI, Notion API, Groq API).
- Vector embeddings and RAG (Retrieval-Augmented Generation) with HuggingFace, Pinecone, and LangChain (v0.3+).
- Responsive UI/UX design with glassmorphism aesthetics.
- Secure environment management and incremental data syncing.

## Features

- **Notion Sync**: Refresh and vectorize Notion pages on-demand.
- **Page Filtering**: Select specific Notion pages for targeted quizzes or chats.
- **Interactive Quiz**: Open-ended questions with AI evaluation (score + feedback).
- **MCQ Generation**: Batch-generate multiple-choice quizzes (stored as JSON).
- **Q&A Chat**: Conversational interface for asking questions with context-aware responses.
- **Responsive Design**: Mobile-friendly layout with particles.js animations.
- **Stateful Sessions**: Maintain chat history and quiz states.

## Tech Stack

- **Backend**: FastAPI (Python 3.11+), LangChain (>v0.3), Groq API (LLM), Pinecone (vector store), HuggingFace Embeddings.
- **Frontend**: HTML5, CSS3 (glassmorphism), Vanilla JavaScript, particles.js.
- **Data Sources**: Notion API for page loading.
- **Environment**: .env for API keys (Notion, Pinecone, Groq, HuggingFace).
- **Deployment**: Vercel/GitHub Pages (static), Render/Fly.io (backend).

## Installation

### Prerequisites
- Python 3.11+
- Conda or virtualenv for environment management
- API Keys: Notion, Pinecone, Groq, HuggingFace (store in `.env`)

### Setup
1. Clone the repository:
   ```
   git clone https://github.com/yourusername/revisionai.git
   cd revisionai
   ```

2. Create and activate a virtual environment:
   ```
   conda create -n revisionai python=3.11
   conda activate revisionai
   ```

3. Install dependencies:
   ```
   pip install fastapi uvicorn langchain langchain-groq langchain-pinecone langchain-huggingface pinecone-client python-dotenv
   ```

4. Configure `.env`:
   ```
   NOTION_TOKEN=your_notion_token
   PINECONE_API_KEY=your_pinecone_key
   GROQ_API_KEY=your_groq_key
   HUGGINGFACE_TOKEN=your_hf_token
   ```

5. Run the app locally:
   ```
   uvicorn main:app --reload
   ```
   Access at `http://127.0.0.1:8000/` (home), `/quiz` (quiz), `/chat` (chat).

## Usage

1. **Home Page**: Select a Notion page and choose Quiz or Chat mode.
2. **Refresh Notion**: Click "Refresh Pages" to sync and vectorize new content.
3. **Quiz Mode**:
   - Enter number of questions.
   - Answer open-ended prompts; get AI-scored feedback.
4. **Chat Mode**:
   - Ask questions filtered by page; responses use RAG from Pinecone.
5. **API Endpoints** (for extension):
   - `/api/refresh-notion`: Sync Notion pages.
   - `/api/start-quiz`: Start interactive quiz.
   - `/api/submit-quiz-answer`: Submit answers for evaluation.
   - `/api/chat`: Handle Q&A queries.

For production: Deploy static files (`/static`, HTML) to Vercel/GitHub Pages; backend to a server. Use NGINX/Apache for reverse proxy if needed.

## Directory Structure

```
    ├── code_testing/
    │   ├── test_notion_loader.py
    │   ├── test_pinecone_vector_store.py
    │   └── testing_pinecone.py
    ├── frontend/
    │   ├── index.html
    │   ├── .DS_Store
    │   ├── css/
    │   │   ├── index.css
    │   │   ├── chat.css
    │   │   └── quiz.css
    │   ├── js/
    │   │   ├── quiz.js
    │   │   ├── index.js
    │   │   └── chat.js
    │   ├── questions.json
    │   ├── quiz.html
    │   ├── page_id_with_titles.json
    │   └── chat.html
    ├── LICENSE
    ├── vercel.json
    ├── backend/
    │   ├── requirements.txt
    │   ├── __init__.py
    │   ├── __pycache__/
    │   ├── .env
    │   ├── populate_vectors.py
    │   ├── notion_loader.py
    │   ├── chatbot.py
    │   ├── main.py
    │   ├── data/
    │   │   └── page_id_with_titles.json
    │   └── populate_vectorstore_with_new_pages.py
    ├── README.md
    └── page_id_with_title.json
```

## Contributing

Contributions welcome! Fork the repo, create a branch, and submit a PR. Focus on:
- Bug fixes in LangChain/Pinecone integration.
- UI enhancements for better mobile UX.
- Additional features like user auth or export quizzes.

## License

MIT License. See [LICENSE](LICENSE) for details.


