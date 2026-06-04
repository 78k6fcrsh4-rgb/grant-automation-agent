from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import grant_routes
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Grant Automation API",
    description="API for automating grant management tasks for nonprofits",
    version="2.5.2"
)

# --------------------------------------------------
# CORS CONFIGURATION (UPDATED)
# --------------------------------------------------

# Always allow localhost (for development)
default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000"
]

# Allow deployed frontend
azure_frontend = [
    "https://ca-grants-frontend.ambitioustree-e69e3f81.centralus.azurecontainerapps.io"
]

# Allow additional origins from environment variable
extra_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]

# Combine all allowed origins
allowed_origins = (
    default_origins
    + azure_frontend
    + extra_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

app.include_router(grant_routes.router)


@app.get("/")
async def root():
    return {
        "message": "Grant Automation API",
        "version": "2.5.2",
        "docs": "/docs",
        "database": "In-Memory (No DB)"
    }


@app.get("/health")
async def health(llm_probe: bool = False):
    """Health + LLM readiness diagnostics (never exposes the key itself)."""
    key = os.getenv("OPENAI_API_KEY") or ""
    try:
        from langchain_openai import ChatOpenAI  # noqa: F401
        langchain_import_ok = True
        langchain_error = None
    except Exception as e:
        langchain_import_ok = False
        langchain_error = f"{type(e).__name__}: {e}"

    from app.routes.grant_routes import llm_service
    probe = llm_service.probe() if llm_probe else None
    return {
        "status": "healthy",
        "storage": "in-memory",
        "llm": {
            "api_key_present": len(key) > 10,
            "api_key_length": len(key),
            "langchain_import_ok": langchain_import_ok,
            "langchain_error": langchain_error,
            "llm_available": llm_service.is_available(),
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
            "demo_mode": os.getenv("DEMO_MODE", "false"),
            "probe": probe,
        },
    }


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True
    )
