from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import settings
from app.database import Base, engine
from app.routers import assessments, auth, configuration, health, organization, performance, recommendations, reporting

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Progressive employee performance evaluation and explainable HR recommendations.",
)


@app.on_event("startup")
def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE kpis ADD COLUMN IF NOT EXISTS default_weight NUMERIC(5, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id UUID UNIQUE REFERENCES employees(id)"))


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(assessments.router, prefix="/api/v1")
app.include_router(organization.router, prefix="/api/v1")
app.include_router(configuration.router, prefix="/api/v1")
app.include_router(performance.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
app.include_router(reporting.router, prefix="/api/v1")








