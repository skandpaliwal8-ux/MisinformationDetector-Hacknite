from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import routes
from api.routes import router
import uvicorn

app = FastAPI(
    title="Is This News Real? — Misinformation Detector API",
    description="Multi-agent pipeline: forensics, reverse search, context check, claim verify, synthesis.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)