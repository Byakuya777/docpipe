from fastapi import FastAPI

from app.api.routes import batches, documents

app = FastAPI(title="docpipe")

app.include_router(batches.router)
app.include_router(documents.router)


@app.get("/health")
def health():
    return {"status": "ok"}
