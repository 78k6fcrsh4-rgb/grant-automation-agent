from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import grant_routes
import os
from dotenv import load_dotenv

load_dotenv()

# DON'T initialize database for now
# from app.db import init_db
# init_db()

app = FastAPI(
    title="Grant Automation API",
    description="API for automating grant management tasks for nonprofits",
    version="1.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(grant_routes.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Grant Automation API",
        "version": "1.0.0",
        "docs": "/docs",
        "database": "In-Memory (No DB)"
    }


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "storage": "in-memory"
    }


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "localhost")
    port = int(os.getenv("PORT", 8000))
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True
    )