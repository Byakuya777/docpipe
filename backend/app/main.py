from fastapi import FastAPI

from app.api.routes import documents

app = FastAPI(title="docpipe")

app.include_router(documents.router)


@app.get("/health")
def health():
    return {"status": "ok"}
