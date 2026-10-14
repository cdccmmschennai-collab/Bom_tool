"""One-time cleanup of the tester's data, run at the tester's first extraction after this was deployed.

It deletes what the tester's conversions produced so far - history (with stored files and Parts Master lines),
temporary combined files, the numbering memory, and the material master rows those conversions inserted -
and records that it ran in one_time_tasks. The record is claimed in the same transaction as the deletes, so
the cleanup runs exactly once: never again after a restart or a new login, and never for anyone else.

Kept on purpose:
* the running counters (number_sequences) - numbers already handed out are never issued again;
* material master rows the conversions did not insert (rows imported in pgAdmin, including ones a
  conversion reused). A conversion inserts its master rows in the same transaction as its history row, so
  "inserted by that conversion" = same PostgreSQL transaction id (xmin). A row edited afterwards gets a
  new xmin and is kept - the rule can only delete too little, never too much.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import CombineTask, ConversionJob, MaterialNumber, OneTimeTask, User

TASK_NAME = "tester-initial-cleanup"
TESTER_USERNAME = "tester"

log = logging.getLogger(__name__)


def run_tester_cleanup_once(db: Session, user: User) -> dict | None:
    """Run the cleanup if `user` is the tester and it has not run yet. Commits; returns the deleted counts,
    or None when nothing was done. On error everything is rolled back, so it runs again next time."""
    if user.username.lower() != TESTER_USERNAME:
        return None
    if db.get(OneTimeTask, TASK_NAME) is not None:  # fast path, no lock
        return None
    try:
        # claim the task: a second request waits here on the primary key and then finds it taken
        claimed = db.execute(
            insert(OneTimeTask).values(name=TASK_NAME, done_by=user.username)
            .on_conflict_do_nothing(index_elements=["name"]).returning(OneTimeTask.name)
        ).scalar_one_or_none()
        if claimed is None:
            db.rollback()
            return None

        job_ids = list(db.scalars(select(ConversionJob.id).where(ConversionJob.user_name == user.display_name)))
        summary = {"conversions": len(job_ids), "master_rows": 0, "numbering_rows": 0, "combine_tasks": 0}
        if job_ids:
            # master rows first: the match needs the history rows that are deleted below
            summary["master_rows"] = db.execute(text(
                "DELETE FROM material_master_import m "
                "WHERE m.xmin::text IN (SELECT j.xmin::text FROM conversion_jobs j "
                "                       WHERE j.id = ANY(:ids) AND j.status = 'SUCCESS')"
            ), {"ids": job_ids}).rowcount
            summary["numbering_rows"] = db.execute(
                delete(MaterialNumber).where(MaterialNumber.first_job_id.in_(job_ids))).rowcount
            # Parts Master lines go with their conversion (ON DELETE CASCADE)
            db.execute(delete(ConversionJob).where(ConversionJob.id.in_(job_ids)))
        summary["combine_tasks"] = db.execute(
            delete(CombineTask).where(CombineTask.user_name == user.display_name)).rowcount

        db.get(OneTimeTask, TASK_NAME).summary = summary
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Tester initial cleanup failed - nothing was deleted; it will run on the next extraction")
        raise
    log.warning("Tester initial cleanup done (one time only): %s", summary)
    return summary
