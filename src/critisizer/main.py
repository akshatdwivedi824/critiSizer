from fastapi import FastAPI

from critisizer.accounts import router as accounts_router
from critisizer.admin import router as admin_router
from critisizer.api import router as api_router
from critisizer.web import router as web_router

app = FastAPI(title="critiSizer")
app.include_router(web_router)
app.include_router(api_router)
app.include_router(accounts_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
