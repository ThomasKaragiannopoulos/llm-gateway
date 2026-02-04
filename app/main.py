from fastapi import FastAPI

app = FastAPI(title="llm-gateway")


@app.get("/health")
def health():
    return {"status": "ok"}
