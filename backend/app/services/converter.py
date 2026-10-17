"""Orchestrates one conversion: read input -> allocate numbers -> build BOM -> write Excel -> store job
-> add the new lines to the material master."""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ConversionJob, Plant
from ..seed import country_map
from .bom_builder import DUKHAN, build_bom
from .excel_writer import TemplateError, write_submission, write_workbook
from .input_reader import InputFileError, read_input
from .material_master import save_to_master, with_master_descriptions
from .parts import save_lines
from .numbering import DbAllocator, numbering_scope, scope_plant_codes

log = logging.getLogger(__name__)


class ConversionFailed(Exception):
    """An unexpected error during a conversion, with a message the user can read (the API returns it)."""


def _short_error(exc: Exception) -> str:
    """First line of the error, without SQLAlchemy's statement dump ('value too long for type ...')."""
    text = str(getattr(exc, "orig", None) or exc).strip()
    return (text.splitlines()[0] if text else type(exc).__name__)[:300]


def output_filename(plant_type: str, plant_code: str | None, spir_numbers: list[str], input_name: str,
                    kind: str = "WORKING") -> str:
    base = spir_numbers[0] if spir_numbers else re.sub(r"\.[^.]+$", "", input_name)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    label = "DUKHAN" if plant_type == DUKHAN else "OTHER_PLANT"
    plant = f"_{plant_code}" if plant_code else ""
    return f"BOM_{kind}_TEMPLATE_{label}{plant}_{base}.xlsx"


def convert(db: Session, *, plant_type: str, plant: Plant | None, content: bytes, filename: str,
            user_name: str | None) -> ConversionJob:
    settings = get_settings()
    plant_type = plant_type.upper()
    plant_code = plant.code if plant else None

    job = ConversionJob(
        plant_type=plant_type, plant_id=plant.id if plant else None, plant_code=plant_code,
        user_name=user_name, status="SUCCESS", input_filename=filename, input_file=content,
    )
    try:
        rows = read_input(content)
        db.add(job)
        db.flush()  # get job.id

        allocator = DbAllocator(db, numbering_scope(plant_type, plant_code),
                                scope_plant_codes(db, plant_type, plant_code))
        allocator.job_id = job.id
        result = build_bom(rows, plant_type, plant_code, allocator, country_map(db), settings.mfr_part_number_max)

        # both templates: a spare matching a master record (temp number + SPF number) shows its description
        templates = with_master_descriptions(db, result, plant_code)
        template = settings.template_dukhan if plant_type == DUKHAN else settings.template_other
        job.output_file = write_workbook(templates, plant_type, template)
        job.output_filename = output_filename(plant_type, plant_code, result.spir_numbers, filename)
        submission = settings.submission_dukhan if plant_type == DUKHAN else settings.submission_other
        job.submission_file = write_submission(templates, submission)
        job.submission_filename = output_filename(plant_type, plant_code, result.spir_numbers, filename,
                                                  kind="SUBMISSION")
        job.spir_numbers = result.spir_numbers
        job.equipment_count = result.equipment_count
        job.spare_count = result.spare_count
        job.line_count = len(result.lines)
        job.warnings = [w.as_dict() for w in result.warnings]
        added = save_to_master(db, result, plant_code)
        save_lines(db, job.id, result)  # searchable on the Parts Master page
        log.info("Job %s: %s new rows added to the material master", job.id, added)
        db.commit()
        return job
    except Exception as exc:
        db.rollback()  # releases sequence locks and discards numbers handed out in this attempt
        log.exception("Conversion failed for %s", filename)
        failed = ConversionJob(
            plant_type=plant_type, plant_id=plant.id if plant else None, plant_code=plant_code,
            user_name=user_name, status="FAILED", error=str(exc)[:2000],
            input_filename=filename, input_file=content,
        )
        saved = ""
        try:
            db.add(failed)
            db.commit()
            saved = f" It is listed in the history as failed conversion #{failed.id}."
        except Exception:
            db.rollback()
            log.exception("Could not record the failed conversion of %s", filename)
        if isinstance(exc, (InputFileError, TemplateError)):
            raise  # a problem with the file or the template - the API shows its own message
        raise ConversionFailed(
            f"Unexpected error - nothing was saved and no numbers were used.{saved} Details: {_short_error(exc)}"
        ) from exc
