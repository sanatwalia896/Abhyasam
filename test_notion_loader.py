import os 
from pathlib import Path
from notion_loader import  NotionPageLoader
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
page_ids = loader.search_all_pages()
pageid_with_title={}
for id in range(len(page_ids)):
    page_title=loader.get_page_title(page_ids[id])
    
    print(f"The title of the notion page  with id {page_ids[id]}is ",page_title)
    blocks=loader.get_page_blocks(page_ids[id])
    
    for block in blocks:
        content = "\n".join([b["text"] for b in blocks])
    doc=Document(page_content=str(content),metadata={
    "source": "Notion",
    "page_title": page_title,
    "page_id": page_ids[id],
    "chunk_id": id
    })


for id in page_ids:
    page_title=loader.get_page_title(id)
    pageid_with_title[page_title]=id
    
# # print(pageid_with_title)
# filename='content.txt'
# with open(filename,'w+') as f:
#     f.write(str(content))

# file_path=Path(filename)
# print('the file path is',file_path)



splitter=RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
# chunks = splitter.split_text(str(content))
docs=splitter.split_documents([doc])

print(docs)
    
        



