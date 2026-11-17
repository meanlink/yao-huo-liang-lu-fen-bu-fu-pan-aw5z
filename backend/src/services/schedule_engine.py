"""班历排程引擎：只依赖标准库，便于脱离数据库单测。

核心口径：
- 所有计划按 *当地时间* 登记（时区、工作日、交班时刻 HH:MM）。
- 停工日期不产生场次；工作日之外不产生场次。
- 春令时跳变造成的不存在时刻（gap）标记 skipped，跳过不派送。
- 回拨造成的重复时刻（fold/ambiguous）取 fold=0 的首次出现。
- 场次归属哪个班历版本，由该场次的 UTC 时刻与版本生效时间比较决定，
  与调整发生的先后无关，保证生效前欠发仍按旧版补齐。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
WEEKDAY_LABELS = {
    'mon': '周一', 'tue': '周二', 'wed': '周三', 'thu': '周四',
    'fri': '周五', 'sat': '周六', 'sun': '周日',
}
HORIZON_DAYS = 45          # worker 每次向前物化的天数窗口
BACKFILL_DAYS = 366        # 停机追补最多回看一年，避免无限补历史
PREVIEW_MAX_DAYS = 366


def get_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f'不支持的时区：{tz_name}') from exc


def validate_timezone(tz_name: str) -> str:
    get_zone(tz_name)
    return tz_name


def validate_handover(value: str) -> str:
    parts = value.split(':')
    if len(parts) != 2:
        raise ValueError('交班时刻格式应为 HH:MM')
    hh, mm = parts
    if not (hh.isdigit() and mm.isdigit()) or not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        raise ValueError('交班时刻需为 00:00–23:59')
    return f'{int(hh):02d}:{int(mm):02d}'


def validate_workdays(workdays: list[str]) -> list[str]:
    if not workdays:
        raise ValueError('至少选择一个工作日')
    bad = [w for w in workdays if w not in WEEKDAYS]
    if bad:
        raise ValueError(f'非法工作日：{bad}')
    # 去重并保持周内顺序
    seen, ordered = set(), []
    for w in WEEKDAYS:
        if w in workdays and w not in seen:
            seen.add(w)
            ordered.append(w)
    return ordered


def validate_paused(paused: list[str]) -> list[str]:
    out = []
    for item in paused:
        try:
            out.append(date.fromisoformat(item).isoformat())
        except (ValueError, TypeError) as exc:
            raise ValueError(f'停工日期格式应为 YYYY-MM-DD：{item}') from exc
    return sorted(set(out))


@dataclass
class ResolvedShift:
    slot_date: str          # 当地日期 YYYY-MM-DD
    local_time: str         # 登记的交班时刻 HH:MM
    status: str             # ok / ambiguous / gap
    scheduled_at: float | None  # UTC unix 秒；gap 为 None
    utc_offset_minutes: int | None
    note: str

    @property
    def slot_key(self) -> str:
        return f'{self.slot_date}T{self.local_time}'


def resolve_local(day: date, handover_time: str, tz: ZoneInfo) -> ResolvedShift:
    """把某当地日的交班时刻解析为 UTC 时刻，处理 DST gap/fold。"""
    hh, mm = (int(x) for x in handover_time.split(':'))
    naive = datetime.combine(day, dtime(hh, mm))
    first = naive.replace(tzinfo=tz)          # fold=0：重复时刻的首次出现
    second = first.replace(fold=1)
    off_first, off_second = first.utcoffset(), second.utcoffset()
    iso_day = day.isoformat()
    if off_first == off_second:
        return ResolvedShift(iso_day, handover_time, 'ok',
                             first.astimezone(timezone.utc).timestamp(),
                             int(off_first.total_seconds() // 60),
                             '当地时刻唯一')
    # fold 两侧偏移不同：只可能是 gap（不存在）或 fold（重复）。
    roundtrip = (first.astimezone(timezone.utc)
                 .astimezone(tz).replace(tzinfo=None))
    if roundtrip != naive:
        # 春令时前跳：该墙上时间在当地不存在，跳过不派送。
        return ResolvedShift(iso_day, handover_time, 'gap', None, None,
                             '当地不存在该时刻（夏令时跳变），已跳过')
    # 回拨：同一墙上时间出现两次，fold=0 即首次出现，取首次。
    return ResolvedShift(iso_day, handover_time, 'ambiguous',
                         first.astimezone(timezone.utc).timestamp(),
                         int(off_first.total_seconds() // 60),
                         '夏令时回拨重复时刻，取首次出现')


def _iter_days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def enumerate_shifts(config, start_day: date, end_day: date,
                     version_resolver=None) -> list[ResolvedShift]:
    """按一份班历配置枚举 [start_day, end_day] 的当地场次。

    config 需含 timezone / workdays / handover_time / paused_dates。
    version_resolver(day, shift) 可选，用于跨版本窗口，交给调用方决定版本，
    本函数只做纯日历计算。
    """
    tz = get_zone(config['timezone'])
    workdays = set(config['workdays'])
    paused = set(config['paused_dates'] or [])
    handover = config['handover_time']
    shifts: list[ResolvedShift] = []
    for day in _iter_days(start_day, end_day):
        if WEEKDAYS[day.weekday()] not in workdays:
            continue
        if day.isoformat() in paused:
            continue
        shifts.append(resolve_local(day, handover, tz))
    return shifts


def shifts_across_versions(versions, start_day: date, end_day: date) -> list[dict]:
    """跨版本枚举窗口内场次。每个场次按自身 UTC 时刻选择生效版本。

    返回 dict：resolved 场次 + version_id。gap 场次同样需要选版本，
    规则按该日当地 00:00 的 UTC 时刻判定，保证跳过也留痕且归属唯一。
    """
    if not versions:
        return []
    ordered = sorted(versions, key=lambda v: v.version_no)
    latest = ordered[-1]
    tz_cache: dict[str, ZoneInfo] = {}

    def zone_of(name):
        if name not in tz_cache:
            tz_cache[name] = get_zone(name)
        return tz_cache[name]

    def pick(ts: float):
        chosen = None
        for v in ordered:
            if v.effective_from <= ts:
                chosen = v
        return chosen or ordered[0]

    # 窗口按“当前版本”的当地日历铺日期；逐日再选版本，跨时区版本也不漏日。
    scope_tz = zone_of(latest.config_dict()['timezone'])
    out: list[dict] = []
    for day in _iter_days(start_day, end_day):
        anchor_ts = datetime.combine(day, dtime(0, 0), tzinfo=scope_tz).timestamp()
        version = pick(anchor_ts)
        cfg = version.config_dict()
        if WEEKDAYS[day.weekday()] not in set(cfg['workdays']):
            continue
        if day.isoformat() in set(cfg['paused_dates'] or []):
            continue
        shift = resolve_local(day, cfg['handover_time'], zone_of(cfg['timezone']))
        chosen = pick(shift.scheduled_at if shift.scheduled_at is not None else anchor_ts)
        if chosen.id != version.id:
            # 极端情况下生效点落在当天 00:00 与交班时刻之间，以交班时刻为准重算。
            version = chosen
            cfg = version.config_dict()
            if WEEKDAYS[day.weekday()] not in set(cfg['workdays']):
                continue
            if day.isoformat() in set(cfg['paused_dates'] or []):
                continue
            shift = resolve_local(day, cfg['handover_time'], zone_of(cfg['timezone']))
        out.append({'shift': shift, 'version_id': version.id})
    return out


def today_local(tz_name: str, now: float | None = None) -> date:
    now = time.time() if now is None else now
    return datetime.fromtimestamp(now, tz=get_zone(tz_name)).date()
