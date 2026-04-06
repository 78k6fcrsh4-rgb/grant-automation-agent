from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import grant_routes
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Grant Automation API",
    description="API for automating grant management tasks for nonprofits",
    version="1.0.0"
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
        "version": "1.0.0",
        "docs": "/docs",
        "database": "In-Memory (No DB)"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "storage": "in-memory"
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
