import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, ShiftSlot
from src.config.settings import ARTIFACT_DIR
from src.services import schedule


def create(db, data, actor='admin', horizon_days=None):
    j = db.get(Job, data.job_id)
    if not j or j.status != 'completed' or not j.approved:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    if data.schedule_mode == 'interval':
        r = Report(name=data.name, job_id=j.id, destination=data.destination,
                   interval_seconds=data.interval_seconds,
                   next_run=time.time() + data.delay_seconds, enabled=True,
                   schedule_mode='interval')
        db.add(r); db.flush()
        return r
    # 班历模式：登记时区、工作日、交班时刻；首版立即生效并物化场次。
    cfg = data.calendar_fields()
    r = Report(name=data.name, job_id=j.id, destination=data.destination,
               interval_seconds=data.interval_seconds, next_run=None,
               enabled=True, schedule_mode='calendar',
               start_date=cfg['start_date'])
    db.add(r); db.flush()
    schedule.create_calendar_version(db, r, cfg, effective_from=0.0,
                                     actor=actor, note=cfg['note'])
    schedule.materialize(db, r, horizon_days=horizon_days)
    return r


def render_payload(job):
    """把已批准分析的固定快照渲染为收件箱 CSV 字节。"""
    out = io.StringIO()
    out.write('\ufeff')
    table = job.result.get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)

    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text

    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []):
        writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    return out.getvalue().encode('utf-8')


def _write_artifacts(report, delivery, job, data):
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    csv_path = os.path.join(ARTIFACT_DIR, delivery.filename)
    tmp_path = csv_path + '.part'
    with open(tmp_path, 'wb') as f:
        f.write(data)
    os.replace(tmp_path, csv_path)  # 原子落盘，中断不会留下半截文件
    with open(csv_path + '.json', 'w') as f:
        json.dump({'job': job.name, 'params': job.params, 'result': job.result,
                   'checksum': delivery.checksum}, f,
                  ensure_ascii=False, allow_nan=False)


def _new_delivery(report, data, mode, slot=None):
    return Delivery(report_id=report.id, created_at=time.time(),
                    checksum=hashlib.sha256(data).hexdigest(), filename='',
                    destination=report.destination,
                    slot_id=slot.id if slot else None,
                    schedule_mode=mode,
                    version_id=slot.version_id if slot else None,
                    status='archived')


def deliver_slot(db, report, slot):
    """派送单个交班场次。同场次重试不重复留档，失败抛错由 worker 下轮重试。"""
    if slot.status == 'delivered':
        return db.scalar(select(Delivery).where(Delivery.slot_id == slot.id))
    existing = db.scalar(select(Delivery).where(Delivery.slot_id == slot.id))
    if existing:  # 归档已存在但场次未置完成：幂等补齐状态，不重建文件
        schedule.mark_result(db, slot, existing, None)
        return existing
    job = db.get(Job, report.job_id)
    if not job or not job.approved:
        raise RuntimeError('关联分析未批准或已删除，无法派送')
    data = render_payload(job)
    delivery = _new_delivery(report, data, 'calendar', slot)
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-slot-{slot.id}-delivery-{delivery.id}.csv'
    _write_artifacts(report, delivery, job, data)
    schedule.mark_result(db, slot, delivery, None)
    return delivery


def deliver(db, report):
    """旧版固定秒间隔派送，行为保持兼容（仍由 next_run/interval_seconds 驱动）。"""
    job = db.get(Job, report.job_id)
    if not job or not job.approved:
        return
    data = render_payload(job)
    delivery = _new_delivery(report, data, 'interval')
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    _write_artifacts(report, delivery, job, data)
    report.next_run = time.time() + report.interval_seconds
    return delivery
