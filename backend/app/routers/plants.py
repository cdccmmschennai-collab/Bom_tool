from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Plant
from ..schemas import PlantOut, PlantTypeOut

router = APIRouter(prefix="/api", tags=["plants"])


@router.get("/plant-types", response_model=list[PlantTypeOut])
def plant_types() -> list[PlantTypeOut]:
    return [PlantTypeOut(value="DUKHAN", label="Dukhan plant"),
            PlantTypeOut(value="OTHER", label="Other than Dukhan plant")]


@router.get("/plants", response_model=list[PlantOut])
def list_plants(plant_type: str | None = None, db: Session = Depends(get_db)) -> list[Plant]:
    q = select(Plant).where(Plant.active.is_(True)).order_by(Plant.sort_order, Plant.code)
    if plant_type:
        q = q.where(Plant.plant_type == plant_type.upper())
    return list(db.execute(q).scalars())
