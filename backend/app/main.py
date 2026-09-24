from fastapi import FastAPI

from app.api.organizations import router as organizations_router
from app.api.plants import router as plants_router
from app.api.assets import router as assets_router
from app.api.channels import router as channels_router
from app.api.readings import router as readings_router
from app.api.files import router as files_router
from app.api.mapping_templates import router as mapping_templates_router
from app.api.ingestion_jobs import router as ingestion_jobs_router


app = FastAPI(
    title="PlantIQ API",
    description="Backend API for the PlantIQ solar plant monitoring platform",
    version="1.0.0",
)


app.include_router(organizations_router)
app.include_router(plants_router)
app.include_router(assets_router)
app.include_router(channels_router)
app.include_router(readings_router)
app.include_router(files_router)
app.include_router(mapping_templates_router)
app.include_router(ingestion_jobs_router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "PlantIQ API",
    }
