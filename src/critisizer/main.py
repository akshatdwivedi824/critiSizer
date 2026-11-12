import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from critisizer import cache
from critisizer.accounts import router as accounts_router
from critisizer.admin import router as admin_router
from critisizer.api import router as api_router
from critisizer.aspect_reviews import router as aspect_reviews_router
from critisizer.deps import SessionDep
from critisizer.review import router as review_router
from critisizer.web import router as web_router

app = FastAPI(title="critiSizer")
app.include_router(web_router)
app.include_router(api_router)
app.include_router(accounts_router)
app.include_router(admin_router)
app.include_router(review_router)
app.include_router(aspect_reviews_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Touches nothing else."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready(session: SessionDep) -> JSONResponse:
    """Readiness: the database and Redis both answer. 503 if either does not."""
    failed = []
    try:
        session.execute(text("select 1"))
    except SQLAlchemyError:
        failed.append("database")
    try:
        cache.get_redis().ping()
    except redis.RedisError:
        failed.append("redis")
    if failed:
        return JSONResponse({"status": "not_ready", "failed": failed}, status_code=503)
    return JSONResponse({"status": "ready"})