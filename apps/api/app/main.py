from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import get_settings
from app.core.db import database_ready
from app.api.routes import schedules, staff, admin, appointments, auth, dashboard, finance, imports, integrations, leads, masters, meta, patients, visits, procedures, procedure_integrations

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Idempotency-Key"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else response.headers.get("Cache-Control", "no-cache")
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(auth.router, prefix="/api/v1")
app.include_router(meta.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(patients.router, prefix="/api/v1")
app.include_router(schedules.router, prefix="/api/v1")
app.include_router(appointments.router, prefix="/api/v1")
app.include_router(visits.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(masters.router, prefix="/api/v1")
app.include_router(imports.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(integrations.router, prefix="/api/v1")
app.include_router(procedures.router, prefix="/api/v1")
app.include_router(procedure_integrations.router, prefix="/api/v1")


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(response: Response):
    if not database_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "database": "unavailable"}
    return {"status": "ready", "database": "ok"}


@app.get("/health")
def health_compat():
    return {"status": "ok"}

from app.api.routes import doctor_consultations
app.include_router(doctor_consultations.router, prefix="/api/v1")

from app.api.routes import clinical_team, clinical_preparations
app.include_router(clinical_team.router, prefix="/api/v1")
app.include_router(clinical_preparations.router, prefix="/api/v1")

from app.api.routes import diagnoses
app.include_router(diagnoses.router, prefix="/api/v1")

from app.api.routes import medicines
app.include_router(medicines.router, prefix="/api/v1")
