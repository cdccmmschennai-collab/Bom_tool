import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .auth import current_user
from .config import get_settings
from .database import Base, SessionLocal, engine, upgrade_columns
from .routers import auth, jobs, parts, plants
from .seed import load_country_reference, sync_plants
from .services.parts import backfill as backfill_parts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # several uvicorn workers start together - an advisory lock makes start-up seeding run one at a time
    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(424242)"))
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                upgrade_columns(conn)
            with SessionLocal() as db:
                sync_plants(db)
                load_country_reference(db)
                filled = backfill_parts(db)  # older conversions become searchable on the Parts Master page
                if filled:
                    logging.getLogger(__name__).info("Parts Master: added the lines of %s conversions", filled)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(424242)"))
            lock_conn.commit()
    yield


app = FastAPI(title="SPIR -> BOM Working Template converter", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
    expose_headers=["Content-Disposition"],
)
app.include_router(auth.router)
# everything except sign-in and the health check needs a signed-in user
app.include_router(plants.router, dependencies=[Depends(current_user)])
app.include_router(jobs.router, dependencies=[Depends(current_user)])
app.include_router(parts.router, dependencies=[Depends(current_user)])


@app.get("/api/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
