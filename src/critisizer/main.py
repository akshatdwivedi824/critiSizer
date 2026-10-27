from fastapi import FastAPI

app = FastAPI(title="critiSizer")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}