from fastapi import FastAPI

app = FastAPI(title="zeler-meli-gateway")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
