import os
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, Delivery, ScheduleVersion, ShiftSlot
from src.schemas.report import ReportInput, VersionAdjustInput, PreviewInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports, schedule
from src.services.audit import record
from src.utils.serialization import (
    report_dict, delivery_dict, version_dict, slot_dict)
router = APIRouter()


def _with_versions(db, report_rows):
    """一次性带出各计划的班历版本，避免 N+1。"""
    if not report_rows:
        return report_rows
    ids = [r.id for r in report_rows]
    versions = list(db.scalars(
        select(ScheduleVersion)
        .where(ScheduleVersion.report_id.in_(ids))
        .order_by(ScheduleVersion.version_no)))
    grouped = {}
    for v in versions:
        grouped.setdefault(v.report_id, []).append(v)
    for r in report_rows:
        r._versions_cache = grouped.get(r.id, [])
    return report_rows


@router.get('/reports')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = list(db.scalars(select(Report).order_by(Report.id.desc())))
    _with_versions(db, rows)
    now = time.time()
    out = []
    for r in rows:
        item = report_dict(r)
        if r.schedule_mode == 'calendar':
            item['next_run'] = schedule.next_due_timestamp(db, r, now)
        out.append(item)
    return out


@router.post('/reports', status_code=201)
def create(data: ReportInput, db=Depends(get_db), u=Depends(admin_only)):
    try:
        r = reports.create(db, data, actor=u.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    record(db, u.email, 'report.schedule',
           {'id': r.id, 'destination': r.destination, 'mode': r.schedule_mode})
    db.commit()
    r = db.get(Report, r.id)
    _with_versions(db, [r])
    return report_dict(r)


@router.post('/reports/{id}/toggle')
def toggle(id: int, db=Depends(get_db), u=Depends(admin_only)):
    r = db.get(Report, id)
    if not r:
        raise HTTPException(404, '分发计划不存在')
    r.enabled = not r.enabled
    record(db, u.email, 'report.toggle', {'id': id, 'enabled': r.enabled})
    db.commit()
    _with_versions(db, [r])
    return report_dict(r)


@router.post('/reports/preview')
def preview(data: PreviewInput, db=Depends(get_db), u=Depends(current_user)):
    try:
        return schedule.preview(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/reports/{id}/adjust')
def adjust(id: int, data: VersionAdjustInput,
           db=Depends(get_db), u=Depends(admin_only)):
    try:
        report, version = schedule.adjust(db, id, data, u.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    record(db, u.email, 'report.adjust',
           {'id': id, 'version': version.version_no,
            'effective_from': version.effective_from})
    db.commit()
    report = db.get(Report, id)
    _with_versions(db, [report])
    return {'report': report_dict(report), 'version': version_dict(version)}


@router.get('/reports/{id}/versions')
def versions(id: int, db=Depends(get_db), u=Depends(current_user)):
    if not db.get(Report, id):
        raise HTTPException(404, '分发计划不存在')
    rows = db.scalars(
        select(ScheduleVersion)
        .where(ScheduleVersion.report_id == id)
        .order_by(ScheduleVersion.version_no))
    return [version_dict(v) for v in rows]


@router.get('/reports/{id}/slots')
def slots(id: int, status: str | None = Query(default=None),
          limit: int = Query(default=200, ge=1, le=1000),
          db=Depends(get_db), u=Depends(current_user)):
    if not db.get(Report, id):
        raise HTTPException(404, '分发计划不存在')
    stmt = select(ShiftSlot).where(ShiftSlot.report_id == id)
    if status:
        if status not in ('pending', 'delivered', 'skipped'):
            raise HTTPException(422, '状态仅支持 pending/delivered/skipped')
        stmt = stmt.where(ShiftSlot.status == status)
    rows = db.scalars(stmt.order_by(ShiftSlot.slot_key.asc()).limit(limit))
    return [slot_dict(s) for s in rows]


@router.get('/deliveries')
def deliveries(report_id: int | None = Query(default=None),
               db=Depends(get_db), u=Depends(current_user)):
    stmt = select(Delivery)
    if report_id is not None:
        stmt = stmt.where(Delivery.report_id == report_id)
    rows = db.scalars(stmt.order_by(Delivery.id.desc()).limit(200))
    return [delivery_dict(d) for d in rows]


@router.get('/deliveries/{id}/download')
def download(id: int, format: str = 'csv',
             db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Delivery, id)
    if not d:
        raise HTTPException(404, '归档不存在')
    if format not in ('csv', 'json'):
        raise HTTPException(422, '支持 CSV 或 JSON')
    filename = d.filename + ('.json' if format == 'json' else '')
    p = os.path.join(ARTIFACT_DIR, filename)
    if not os.path.exists(p):
        raise HTTPException(404, '归档文件不存在，请重新安排分发')
    return FileResponse(p, filename=filename,
                        media_type='application/json' if format == 'json'
                        else 'text/csv; charset=utf-8')
