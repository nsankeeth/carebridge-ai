import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError, app_error_handler
from app.routers import admin, agent, auth, clinician, patient, threads
from app.triage import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")



@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    lifespan=lifespan,
    title="CareBridge — Medical Navigation & Clinician Handoff API",
    version="0.1.0",
    description="Medical navigation and clinician handoff, powered by Meta AI.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Invalid request", "details": details}})


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"ok": True}


for r in (auth.router, patient.router, clinician.router, admin.router, agent.router, threads.patient_router, threads.clinician_router):
    app.include_router(r)
