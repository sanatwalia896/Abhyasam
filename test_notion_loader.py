import os 
from notion_loader import  NotionPageLoader
loader = NotionPageLoader(os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID"))
pages = loader.refresh_and_cache_pages()
print(pages[0] if pages else "No pages found")