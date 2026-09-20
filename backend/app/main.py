from fastapi import FastAPI

app = FastAPI(title="osumapscout API")


@app.get("/health")
def health() -> dict[str, str]:
    """Report whether the backend application is running."""
    return {"status": "ok"}
