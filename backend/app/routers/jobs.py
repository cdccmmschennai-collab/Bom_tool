import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, cast, delete, func, select, update
from sqlalchemy.orm import Session, undefer

from ..auth import current_user
from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import CombineTask, ConversionJob, MaterialNumber, Plant, User
from ..schemas import CombineIn, CombineOut, JobOut, JobPage
from ..services.excel_writer import TemplateError
from ..services.input_reader import InputFileError
from ..services.combiner import SUBMISSION, WORKING, combine
from ..services.converter import convert

router = APIRouter(prefix="/api/jobs", tags=["conversions"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COMBINE_KEEP = timedelta(hours=24)  # combined files are temporary, not part of the history

log = logging.getLogger(__name__)


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    plant_type: str = Form(..., description="DUKHAN or OTHER"),
    plant_id: int | None = Form(None, description="Maintenance planning plant (optional)"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ConversionJob:
    plant_type = plant_type.strip().upper()
    if plant_type not in ("DUKHAN", "OTHER"):
        raise HTTPException(422, "Plant type must be DUKHAN or OTHER.")

    plant = None
    if plant_id:
        plant = db.get(Plant, plant_id)
        if plant is None or not plant.active:
            raise HTTPException(422, "Selected planning plant does not exist.")
        if plant.plant_type != plant_type:
            raise HTTPException(422, f"Planning plant {plant.code} does not belong to plant type {plant_type}.")

    name = file.filename or "input.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "Please upload an Excel .xlsx file.")
    content = await file.read()
    if len(content) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB.")

    try:
        return convert(db, plant_type=plant_type, plant=plant, content=content, filename=name,
                       user_name=user.display_name)  # history shows the signed-in user
    except (InputFileError, TemplateError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("", response_model=JobPage)
def list_jobs(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    date_from: datetime | None = Query(None, description="Created at or after (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Created before (ISO 8601, exclusive)"),
    db: Session = Depends(get_db),
) -> JobPage:
    q = select(ConversionJob)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(ConversionJob.input_filename.ilike(like) | ConversionJob.output_filename.ilike(like)
                    | ConversionJob.user_name.ilike(like) | ConversionJob.plant_code.ilike(like)
                    | cast(ConversionJob.spir_numbers, String).ilike(like))
    if date_from:
        q = q.where(ConversionJob.created_at >= date_from)
    if date_to:
        q = q.where(ConversionJob.created_at < date_to)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    items = db.execute(q.order_by(ConversionJob.id.desc()).limit(limit).offset(offset)).scalars().all()
    return JobPage(items=[JobOut.model_validate(j) for j in items], total=total)


# ------------------------------------------------------------------ combine (declared before /{job_id})
def _run_combine(task_id: int) -> None:
    """Background work for one combine request; progress is committed after every file."""
    with SessionLocal() as db:
        task = db.get(CombineTask, task_id)
        try:
            column = ConversionJob.output_file if task.kind == WORKING else ConversionJob.submission_file
            stored = dict(db.execute(select(ConversionJob.id, column).where(ConversionJob.id.in_(task.job_ids))).all())
            missing = [i for i in task.job_ids if not stored.get(i)]
            if missing:
                raise ValueError(f"Conversion(s) {', '.join(map(str, missing))} no longer have this file.")

            def progress(done: int) -> None:
                task.done = done
                db.commit()

            task.file = combine([stored[i] for i in task.job_ids], task.kind, progress)
            task.done, task.status = task.total, "DONE"
            db.commit()
        except Exception as exc:  # the user sees the reason on the progress card
            log.exception("Combine %s failed", task_id)
            db.rollback()
            task.status, task.error = "FAILED", str(exc)[:2000]
            db.commit()


@router.post("/combine", response_model=CombineOut, status_code=202)
def start_combine(body: CombineIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  user: User = Depends(current_user)) -> CombineTask:
    ids = list(dict.fromkeys(body.job_ids))  # drop repeated ids, keep the order
    if len(ids) < 2:
        raise HTTPException(422, "Select at least two conversions to combine.")
    jobs = {j.id: j for j in db.execute(select(ConversionJob).where(ConversionJob.id.in_(ids))).scalars()}
    if missing := [i for i in ids if i not in jobs]:
        raise HTTPException(404, f"Conversion(s) not found: {', '.join(map(str, missing))}.")
    if failed := [i for i in ids if jobs[i].status != "SUCCESS"]:
        raise HTTPException(422, f"Failed conversions cannot be combined: {', '.join(map(str, failed))}.")
    if len({jobs[i].plant_type for i in ids}) > 1:
        raise HTTPException(422, "Dukhan and Other-plant conversions use different templates and cannot be "
                                 "combined - select conversions of one plant type.")
    if body.kind == SUBMISSION and (old := [i for i in ids if not jobs[i].submission_filename]):
        raise HTTPException(422, f"Conversion(s) {', '.join(map(str, old))} have no submission template.")

    ids.sort()  # oldest conversion first
    db.execute(delete(CombineTask).where(CombineTask.created_at < datetime.now(timezone.utc) - COMBINE_KEEP))
    label = "DUKHAN" if jobs[ids[0]].plant_type == "DUKHAN" else "OTHER_PLANT"
    task = CombineTask(
        kind=body.kind, job_ids=ids, user_name=user.display_name, status="RUNNING", done=0, total=len(ids),
        filename=f"BOM_{body.kind}_TEMPLATE_COMBINED_{label}_{len(ids)}_FILES_{datetime.now():%Y%m%d-%H%M}.xlsx",
    )
    db.add(task)
    db.commit()
    background.add_task(_run_combine, task.id)
    return task


@router.get("/combine/{task_id}", response_model=CombineOut)
def combine_status(task_id: int, db: Session = Depends(get_db)) -> CombineTask:
    task = db.get(CombineTask, task_id)
    if task is None:
        raise HTTPException(404, "Combine request not found (combined files are kept for 24 hours).")
    return task


@router.get("/combine/{task_id}/file")
def combine_file(task_id: int, db: Session = Depends(get_db)) -> Response:
    task = db.execute(select(CombineTask).where(CombineTask.id == task_id)
                      .options(undefer(CombineTask.file))).scalar_one_or_none()
    if task is None or task.status != "DONE" or not task.file:
        raise HTTPException(404, "The combined file is not available.")
    return _download(task.filename, task.file)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> ConversionJob:
    job = db.get(ConversionJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> Response:
    """Removes the conversion from the history (with its stored files).

    The temp numbers it issued stay taken: they remain in material_master_import and in the numbering
    memory, so they are never handed out to another item.
    """
    job = db.get(ConversionJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    db.execute(update(MaterialNumber).where(MaterialNumber.first_job_id == job_id).values(first_job_id=None))
    db.delete(job)
    db.commit()
    return Response(status_code=204)


def _download(filename: str, content: bytes) -> Response:
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/{job_id}/output")
def download_output(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.execute(select(ConversionJob).where(ConversionJob.id == job_id)
                     .options(undefer(ConversionJob.output_file))).scalar_one_or_none()
    if job is None or not job.output_file:
        raise HTTPException(404, "No output file for this job.")
    return _download(job.output_filename or f"bom_{job_id}.xlsx", job.output_file)


@router.get("/{job_id}/submission")
def download_submission(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.execute(select(ConversionJob).where(ConversionJob.id == job_id)
                     .options(undefer(ConversionJob.submission_file))).scalar_one_or_none()
    if job is None or not job.submission_file:
        raise HTTPException(404, "No submission file for this job.")
    return _download(job.submission_filename or f"bom_submission_{job_id}.xlsx", job.submission_file)


@router.get("/{job_id}/input")
def download_input(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.execute(select(ConversionJob).where(ConversionJob.id == job_id)
                     .options(undefer(ConversionJob.input_file))).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Job not found.")
    return _download(job.input_filename, job.input_file)
