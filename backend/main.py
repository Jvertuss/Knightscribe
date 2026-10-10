from fastapi import FastAPI


app = FastAPI(
    title="KnightScribe API",
    description="Backend API for the KnightScribe classroom memory system",
    version="0.1.0",
)


@app.get("/")
def home():
    return {
        "message": "KnightScribe backend is running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }