from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles 
from fastapi.responses import HTMLResponse 
from notion_loader import NotionPageLoader
import os 

app = FastAPI()

# Mount the static folder to serve HTML, CSS, and JS
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get('/',response_class=HTMLResponse)
async def serve_index():
    with open('static/index.html','r') as f:
        return HTMLResponse(content=f.read())

@app.post('/api/refresh-notion')
async def refresh_notion(force:bool=False):
    loader=NotionPageLoader(
        token=os.getenv("NOTION_TOKEN"),
        parent_page_id=os.getenv("NOTION_PARENT_PAGE_ID")
    )
    pages = loader.refresh_and_cache_pages(force_refresh=force)
    return {"status": "success", "pages_updated": len(pages), "pages": pages}

@app.get('/api/notion-pages')
async def fetch_notion_pages():
    loader=NotionPageLoader(os.getenv("NOTION_TOKEN"), os.getenv("NOTION_PARENT_PAGE_ID"))
    pages = loader.get_all_page_contents()  # From cache for speed
    return pages
    
@app.get('/api/test')
async def test_endpoint():
    return {"message": "Hello from FastAPI!"}