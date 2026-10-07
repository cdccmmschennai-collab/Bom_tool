from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plant_type: str
    code: str
    name: str


class PlantTypeOut(BaseModel):
    value: str
    label: str


class WarningOut(BaseModel):
    code: str
    message: str
    lines: list[int] = []


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    plant_type: str
    plant_code: str | None
    user_name: str | None
    status: str
    error: str | None
    input_filename: str
    output_filename: str | None
    submission_filename: str | None = None
    spir_numbers: list[str] | None
    equipment_count: int
    spare_count: int
    line_count: int
    warnings: list[WarningOut] | None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int


class LoginIn(BaseModel):
    username: str  # username or e-mail
    password: str
    remember: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    full_name: str | None


class ProfileOut(BaseModel):
    username: str
    email: str | None
    full_name: str | None
    extraction_count: int  # successful conversions made by this user
    last_login: datetime   # when the current session signed in


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class CombineIn(BaseModel):
    job_ids: list[int] = Field(min_length=2, max_length=200)
    kind: Literal["WORKING", "SUBMISSION"]


class CombineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    done: int
    total: int
    error: str | None
    filename: str | None


PartField = Literal["part_number", "tag_number", "sap_material_number", "material_temp_number",
                    "material_category", "description", "planning_plant", "manufacturer_name",
                    "country_name", "spir"]


class PartOut(BaseModel):
    source: Literal["CONVERSION", "MASTER", "BOTH"]  # BOTH = conversion + material master merged into one row
    job_id: int | None
    created_at: datetime | None
    material_temp_number: str | None
    material_category: str | None
    part_number: str | None
    description: str | None
    tag_number: str | None
    sap_material_number: str | None
    planning_plant: str | None
    manufacturer_name: str | None
    country_name: str | None
    spir: str | None


class PartPage(BaseModel):
    items: list[PartOut]
    total: int
