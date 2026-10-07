"""Parts Master search: one field, a value with * wildcards; plus the Excel download of a search."""
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import PartField, PartPage
from ..services.parts import find_parts, search
from ..services.parts_export import export_parts

router = APIRouter(prefix="/api/parts", tags=["parts master"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("", response_model=PartPage)
def search_parts(
    field: PartField,
    q: str = Query(..., max_length=200, description="Value to find; * is a wildcard, e.g. 12* or *12*"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PartPage:
    if not q.strip():
        raise HTTPException(422, "Enter a value to search for.")
    items, total = search(db, field, q, limit, offset)
    return PartPage(items=items, total=total)


@router.get("/export")
def export_search(
    field: PartField | None = None,
    q: str | None = Query(None, max_length=200, description="Same search as the list; leave empty for every record"),
    db: Session = Depends(get_db),
) -> Response:
    """Every record of the search (not only the page on screen) as an Excel file laid out like the
    MATERIAL MASTER sheet of the submission template. Without a search value all records are exported."""
    searched = bool(field and q and q.strip())
    rows = find_parts(db, field, q) if searched else find_parts(db)
    label = re.sub(r"[^A-Za-z0-9-]+", "_", f"{field}_{q.strip()}").strip("_")[:60] if searched else "ALL"
    filename = f"PARTS_MASTER_{label}_{datetime.now():%Y%m%d-%H%M}.xlsx"
    return Response(export_parts(db, rows), media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
