from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import accounting, analysis, tagging
from db.database import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Tokenria", lifespan=lifespan)
# accounting's static paths (/records, /records/summary) must be registered
# before tagging's /records/{record_id}, or the dynamic route would shadow them.
app.include_router(accounting.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(tagging.router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "accounting.html")
