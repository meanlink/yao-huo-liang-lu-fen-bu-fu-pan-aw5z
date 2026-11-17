from sqlalchemy import String, Double, ForeignKey, Boolean, Integer, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    # 旧版固定秒间隔计划继续可用；schedule_mode='interval' 时沿用 interval_seconds/next_run。
    interval_seconds: Mapped[int] = mapped_column(default=86400)
    next_run: Mapped[float | None] = mapped_column(Double, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 'interval'（原秒间隔）或 'calendar'（时区/工作日/交班时刻班历）
    schedule_mode: Mapped[str] = mapped_column(String(16), default='interval')
    # 班历模式下的当地日历起点（YYYY-MM-DD），用于停机追补与物化窗口
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)


class ScheduleVersion(Base):
    """班历版本。调整即新增一版并指定生效时间，旧版保留用于欠发补齐与追溯。"""
    __tablename__ = 'schedule_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    version_no: Mapped[int]
    timezone: Mapped[str] = mapped_column(String(64))
    workdays: Mapped[str] = mapped_column(String(32))          # 逗号分隔，如 mon,tue,wed
    handover_time: Mapped[str] = mapped_column(String(5))      # HH:MM 当地时刻
    paused_dates: Mapped[str] = mapped_column(Text, default='')  # 逗号分隔 YYYY-MM-DD
    # UTC unix 秒：该版本从此刻起生效；生效点之前的场次仍归属旧版
    effective_from: Mapped[float] = mapped_column(Double)
    created_at: Mapped[float] = mapped_column(Double)
    created_by: Mapped[str] = mapped_column(String(160))
    note: Mapped[str] = mapped_column(String(300), default='')
    __table_args__ = (
        UniqueConstraint('report_id', 'version_no', name='uq_schedule_version_no'),
    )

    def config_dict(self):
        return {
            'timezone': self.timezone,
            'workdays': [w for w in self.workdays.split(',') if w],
            'handover_time': self.handover_time,
            'paused_dates': [d for d in self.paused_dates.split(',') if d],
        }


class ShiftSlot(Base):
    """一个具体交班场次。唯一键保证每场归属唯一版本，不漏场、不双发。"""
    __tablename__ = 'shift_slots'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'))
    slot_key: Mapped[str] = mapped_column(String(32))          # 当地日期T时刻，如 2026-11-17T08:30
    slot_date: Mapped[str] = mapped_column(String(10))
    local_time: Mapped[str] = mapped_column(String(5))
    scheduled_at: Mapped[float | None] = mapped_column(Double, nullable=True)  # UTC；gap 为 None
    utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending 待派送 / delivered 已派送 / skipped 当地不存在时刻跳过
    status: Mapped[str] = mapped_column(String(16), default='pending')
    dst_note: Mapped[str] = mapped_column(String(200), default='')
    last_error: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[float] = mapped_column(Double)
    delivered_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    __table_args__ = (
        UniqueConstraint('report_id', 'slot_key', name='uq_shift_slot_key'),
    )


class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    # 班历场次留档：唯一约束保证同场次重试不重复留档；旧秒间隔计划为空
    slot_id: Mapped[int | None] = mapped_column(
        ForeignKey('shift_slots.id'), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), default='archived')  # archived/failed
    schedule_mode: Mapped[str] = mapped_column(String(16), default='interval')
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey('schedule_versions.id'), nullable=True)
    error: Mapped[str] = mapped_column(String(500), default='')
