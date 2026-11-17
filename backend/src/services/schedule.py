"""班历版本、场次物化与预览。

场次物化采用 upsert 语义（按 reports.id + slot_key 唯一）：
- 已存在的场次绝不改版本，保证调整与派送并发时每场归属唯一；
- gap 场次同样物化（status=skipped，scheduled_at=NULL），跳过留痕；
- 跨生效点的窗口里，每场按自身 UTC 时刻选版本，生效前欠发仍归旧版。
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import Report, ScheduleVersion, ShiftSlot, Delivery
from src.services import schedule_engine as engine


def _versions(db, report_id):
    return list(db.scalars(
        select(ScheduleVersion)
        .where(ScheduleVersion.report_id == report_id)
        .order_by(ScheduleVersion.version_no)))


def create_calendar_version(db, report: Report, cfg: dict, effective_from: float,
                            actor: str, note: str) -> ScheduleVersion:
    existing = db.scalar(
        select(ScheduleVersion)
        .where(ScheduleVersion.report_id == report.id)
        .order_by(ScheduleVersion.version_no.desc()))
    version_no = (existing.version_no + 1) if existing else 1
    version = ScheduleVersion(
        report_id=report.id, version_no=version_no,
        timezone=cfg['timezone'], workdays=','.join(cfg['workdays']),
        handover_time=cfg['handover_time'],
        paused_dates=','.join(cfg['paused_dates']),
        effective_from=effective_from, created_at=time.time(),
        created_by=actor, note=note)
    db.add(version)
    db.flush()
    return version


def _supersede_future_slots(db, report: Report, effective_from: float,
                            latest_tz_name: str):
    """调整生效后，重新登记生效点之后尚未派送的场次。

    - 已派送（delivered）与已有归档的场次一律保留，绝不重发；
    - 生效点之后仍 pending/skipped 的旧版场次删除，按新版重新物化；
    - 生效点之前的欠场保留旧版本，用于按旧版补齐。
    """
    effective_local_date = datetime.fromtimestamp(
        effective_from, tz=engine.get_zone(latest_tz_name)).date().isoformat()
    old = list(db.scalars(
        select(ShiftSlot).where(ShiftSlot.report_id == report.id,
                                ShiftSlot.status != 'delivered')))
    for slot in old:
        if slot.scheduled_at is not None:
            if slot.scheduled_at >= effective_from:
                db.delete(slot)
        elif slot.slot_date > effective_local_date:
            # gap 场次没有 UTC 时刻：仅当当地日期严格晚于生效日才由新版重算，
            # 生效日当天的 gap 视为生效前时刻，保留旧版跳过留痕。
            db.delete(slot)


def adjust(db, report_id: int, data, actor: str,
           horizon_days: int | None = None) -> tuple[Report, ScheduleVersion]:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, '分发计划不存在')
    if report.schedule_mode != 'calendar':
        raise HTTPException(409, '固定秒间隔计划不支持班历调整，请新建班历分发计划')
    if not report.enabled:
        raise HTTPException(409, '计划已暂停，恢复后才能调整班历')
    if data.effective_from < time.time() - 1:
        raise HTTPException(422, '生效时间不能早于当前时间；历史欠发由旧版自动补齐')
    cfg = data.normalized()
    # 先收编生效点之后的未派送旧场次，再登记新版本并重算，避免旧时刻被误派。
    _supersede_future_slots(db, report, data.effective_from, cfg['timezone'])
    version = create_calendar_version(db, report, cfg, data.effective_from,
                                      actor, data.note)
    # 立即物化，保证生效点附近场次已按新规则登记；既有场次版本保持不变。
    materialize(db, report, horizon_days=horizon_days)
    return report, version


def materialize(db, report: Report, now: float | None = None,
                horizon_days: int | None = None) -> int:
    """把窗口内所有班次登记为 ShiftSlot，返回新增场次数。幂等可重复调用。"""
    now = time.time() if now is None else now
    versions = _versions(db, report.id)
    if not versions:
        return 0
    start = date.fromisoformat(report.start_date)
    latest = versions[-1]
    local_today = engine.today_local(latest.timezone, now)
    # 追补回看一年，前看 HORIZON_DAYS 天；停工恢复后窗口自然覆盖所有欠场。
    lookahead = engine.HORIZON_DAYS if horizon_days is None else horizon_days
    window_start = max(start, local_today - timedelta(days=engine.BACKFILL_DAYS))
    window_end = local_today + timedelta(days=lookahead)
    planned = engine.shifts_across_versions(versions, window_start, window_end)
    existing = {s.slot_key: s for s in db.scalars(
        select(ShiftSlot).where(ShiftSlot.report_id == report.id))}
    added = 0
    for item in planned:
        shift = item['shift']
        if shift.slot_key in existing:
            continue
        slot = ShiftSlot(
            report_id=report.id, version_id=item['version_id'],
            slot_key=shift.slot_key, slot_date=shift.slot_date,
            local_time=shift.local_time, scheduled_at=shift.scheduled_at,
            utc_offset_minutes=shift.utc_offset_minutes,
            status='skipped' if shift.status == 'gap' else 'pending',
            dst_note=shift.note, created_at=time.time())
        db.add(slot)
        try:
            with db.begin_nested():  # 保存点：并发撞唯一键时只回滚本行
                db.flush()
            added += 1
            existing[slot.slot_key] = slot
        except IntegrityError:
            # 并发下另一事务已登记同场次：沿用既有场次，绝不双发。
            existing[slot.slot_key] = db.scalar(
                select(ShiftSlot).where(ShiftSlot.report_id == report.id,
                                        ShiftSlot.slot_key == shift.slot_key))
    return added


def due_slots(db, report: Report, now: float | None = None,
              horizon_days: int | None = None):
    now = time.time() if now is None else now
    materialize(db, report, now, horizon_days=horizon_days)
    return list(db.scalars(
        select(ShiftSlot)
        .where(ShiftSlot.report_id == report.id,
               ShiftSlot.status == 'pending',
               ShiftSlot.scheduled_at.isnot(None),
               ShiftSlot.scheduled_at <= now)
        .order_by(ShiftSlot.scheduled_at)))


def preview(data, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    cfg = data.normalized()
    tz = engine.get_zone(cfg['timezone'])
    if data.start_date:
        try:
            start_day = date.fromisoformat(data.start_date)
        except ValueError:
            raise HTTPException(422, '起始日期格式应为 YYYY-MM-DD')
    else:
        start_day = engine.today_local(cfg['timezone'], now)
    end_day = start_day + timedelta(days=min(data.days, engine.PREVIEW_MAX_DAYS) - 1)
    shifts = engine.enumerate_shifts(cfg, start_day, end_day)
    return {
        'timezone': cfg['timezone'],
        'handover_time': cfg['handover_time'],
        'workdays': cfg['workdays'],
        'paused_dates': cfg['paused_dates'],
        'window_start': start_day.isoformat(),
        'window_end': end_day.isoformat(),
        'shifts': [
            {
                'slot_key': s.slot_key, 'slot_date': s.slot_date,
                'local_time': s.local_time, 'status': s.status,
                'scheduled_at': s.scheduled_at,
                'utc_offset_minutes': s.utc_offset_minutes,
                'note': s.note,
                'weekday': engine.WEEKDAYS[date.fromisoformat(s.slot_date).weekday()],
                'weekday_label': engine.WEEKDAY_LABELS[
                    engine.WEEKDAYS[date.fromisoformat(s.slot_date).weekday()]],
            }
            for s in shifts
        ],
    }


def next_due_timestamp(db, report: Report, now: float | None = None) -> float | None:
    """供列表展示“下一场”：取最早一个未派送场次（含已到期欠场）的 UTC 时刻。"""
    now = time.time() if now is None else now
    slot = db.scalar(
        select(ShiftSlot)
        .where(ShiftSlot.report_id == report.id,
               ShiftSlot.status == 'pending',
               ShiftSlot.scheduled_at.isnot(None))
        .order_by(ShiftSlot.scheduled_at))
    return slot.scheduled_at if slot else None


def mark_result(db, slot: ShiftSlot, delivery: Delivery | None, error: str | None):
    if error:
        slot.status = 'pending'
        slot.last_error = error[:500]
    else:
        slot.status = 'delivered'
        slot.delivered_at = time.time()
        slot.last_error = ''
        if delivery is not None:
            delivery.slot_id = slot.id
            delivery.version_id = slot.version_id
