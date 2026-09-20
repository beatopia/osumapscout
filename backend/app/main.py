from fastapi import FastAPI

from backend.app.top_plays import router as top_plays_router

app = FastAPI(title="osumapscout API")
app.include_router(top_plays_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Report whether the backend application is running."""
    return {"status": "ok"}
