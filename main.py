from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles 
from fastapi.responses import HTMLResponse 

app = FastAPI()

# Mount the static folder to serve HTML, CSS, and JS
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get('/',response_class=HTMLResponse)
async def serve_index():
    with open('static/index.html','r') as f:
        return HTMLResponse(content=f.read())
@app.get('/api/test')
async def test_endpoint():
    return {"message": "Hello from FastAPI!"}