from pydantic import BaseModel, Field
from src.services import schedule_engine as engine


class ReportInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    job_id: int
    destination: str = Field(default='业务复核组', min_length=2, max_length=120)
    # 原秒间隔计划字段保留，默认值与旧版一致
    interval_seconds: int = Field(default=86400, ge=60, le=2592000)
    delay_seconds: int = Field(default=0, ge=0, le=2592000)
    # 新增班历模式：schedule_mode='calendar' 时下列字段必填
    schedule_mode: str = Field(default='interval', pattern='^(interval|calendar)$')
    timezone: str | None = Field(default=None, max_length=64)
    workdays: list[str] | None = None
    handover_time: str | None = Field(default=None, max_length=5)
    paused_dates: list[str] | None = None
    start_date: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)

    def calendar_fields(self):
        if self.schedule_mode != 'calendar':
            return None
        missing = [f for f in ('timezone', 'workdays', 'handover_time', 'start_date')
                   if not getattr(self, f)]
        if missing:
            raise ValueError('班历模式需填写时区、工作日、交班时刻与起始日期：' + ','.join(missing))
        from datetime import date
        try:
            start = date.fromisoformat(self.start_date)
        except (ValueError, TypeError):
            raise ValueError('起始日期格式应为 YYYY-MM-DD')
        return {
            'timezone': engine.validate_timezone(self.timezone),
            'workdays': engine.validate_workdays(self.workdays),
            'handover_time': engine.validate_handover(self.handover_time),
            'paused_dates': engine.validate_paused(self.paused_dates or []),
            'start_date': start.isoformat(),
            'note': (self.note or '初始班历')[:300],
        }


class VersionAdjustInput(BaseModel):
    timezone: str = Field(max_length=64)
    workdays: list[str]
    handover_time: str = Field(max_length=5)
    paused_dates: list[str] = Field(default_factory=list)
    # 生效时间：UTC unix 秒，不得早于当前时间
    effective_from: float = Field(ge=0)
    note: str = Field(default='班历调整', max_length=300)

    def normalized(self):
        return {
            'timezone': engine.validate_timezone(self.timezone),
            'workdays': engine.validate_workdays(self.workdays),
            'handover_time': engine.validate_handover(self.handover_time),
            'paused_dates': engine.validate_paused(self.paused_dates),
            'note': self.note,
        }


class PreviewInput(BaseModel):
    timezone: str = Field(max_length=64)
    workdays: list[str]
    handover_time: str = Field(max_length=5)
    paused_dates: list[str] = Field(default_factory=list)
    days: int = Field(default=14, ge=1, le=366)
    start_date: str | None = Field(default=None, max_length=10)

    def normalized(self):
        return {
            'timezone': engine.validate_timezone(self.timezone),
            'workdays': engine.validate_workdays(self.workdays),
            'handover_time': engine.validate_handover(self.handover_time),
            'paused_dates': engine.validate_paused(self.paused_dates),
        }
