"""Application settings, read from environment variables (or a .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RESOURCES_DIR = Path(__file__).parent / "resources"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bom:bom@localhost:5432/bom"

    # Material Temp Number ranges (logic: equipment 5-digit starting 40000, spares 6-digit starting 500000)
    equipment_start: int = 40001
    spare_start: int = 500001

    # "plant_type" -> one running sequence for DUKHAN and one for OTHER plants
    # "plant"      -> one running sequence per selected planning plant code
    #                 (falls back to the plant type when no planning plant is chosen)
    numbering_scope: str = "plant"

    # sign-in: browser session lasts session_hours; "Remember this device" keeps it for remember_days
    session_hours: int = 12
    remember_days: int = 30
    cookie_secure: bool = False  # set COOKIE_SECURE=true when the app is served over HTTPS

    mfr_part_number_max: int = 35
    max_upload_mb: int = 20
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    template_dukhan: Path = RESOURCES_DIR / "BOM_WORKING_TEMPLATE_DUKHAN.xlsx"
    template_other: Path = RESOURCES_DIR / "BOM_WORKING_TEMPLATE_OTHER_PLANT.xlsx"
    submission_dukhan: Path = RESOURCES_DIR / "BOM SUBMISSION TEMPLATES DUKHAN.xlsx"
    submission_other: Path = RESOURCES_DIR / "BOM SUBMISSION TEMPLATES OTHER THAN DUKHAN.xlsx"
    country_reference: Path = RESOURCES_DIR / "COUNTRY_REFERENCE.xlsx"
    plants_seed: Path = RESOURCES_DIR / "plants.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
