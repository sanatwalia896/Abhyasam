import os 
from pathlib import Path
from backend.notion_loader import  NotionPageLoader
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import json
loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
page_ids = loader.search_all_pages()
pageid_with_title={}

for id in page_ids:
    page_title=loader.get_page_title(id)
    pageid_with_title[page_title]=id
    
with open("page_id_with_title.json","w") as f:
    json.dump(pageid_with_title, f, indent=4)
    
print(pageid_with_title)
    

# for id in range(len(page_ids)):
#     page_title=loader.get_page_title(page_ids[id])
    
#     print(f"The title of the notion page  with id {page_ids[id]}is ",page_title)
#     blocks=loader.get_page_blocks(page_ids[id])
    
#     for block in blocks:
#         content = "\n".join([b["text"] for b in blocks])
#     doc=Document(page_content=str(content),metadata={
#     "source": "Notion",
#     ,
#     "page_id": page_ids[id],
#     "chunk_id": id
#     })

# block=loader.get_page_blocks(pageid_with_title['USEFUL CODE SNIPPETS'])
# contrnt=''
# for blocks in block:
#     content = "\n".join([b["text"] for b in blocks])

# print(str(content))




# splitter=RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
# # chunks = splitter.split_text(str(content))
# docs=splitter.split_documents([doc])

# print(docs)
    
        



