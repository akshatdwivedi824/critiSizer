from fastapi import FastAPI

from critisizer.api import router as api_router
from critisizer.web import router as web_router

app = FastAPI(title="critiSizer")
app.include_router(web_router)
app.include_router(api_router)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}