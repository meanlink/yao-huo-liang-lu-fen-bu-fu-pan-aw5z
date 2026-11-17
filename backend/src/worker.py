import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, ShiftSlot
from src.services.business import analyze
from src.services.reports import deliver, deliver_slot
from src.services import schedule
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def _tick_interval(db, r):
    """旧版秒间隔计划：维持原 next_run 语义。"""
    d=deliver(db,r)
    if d:
        record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
    db.commit()
def _tick_calendar(report_id):
    """班历计划：每个交班场次独立事务派送，单场失败不影响其他场次。"""
    with Session() as db:
        r = db.get(Report, report_id)
        if not r or not r.enabled:
            return
        try:
            slots = schedule.due_slots(db, r)
            db.commit()  # 物化结果先落库，保证场次登记不被单场失败回滚
        except Exception:
            logging.exception('Schedule materialize failed report=%s', report_id)
            db.rollback()
            return
        slot_ids = [s.id for s in slots]
    for slot_id in slot_ids:
        try:
            with Session() as slot_db:
                # 重新读取：并发调整/派送下确认场次仍待派送，归属版本不变。
                fresh = slot_db.get(ShiftSlot, slot_id)
                if not fresh or fresh.status != 'pending':
                    continue
                rep = slot_db.get(Report, report_id)
                if not rep or not rep.enabled:
                    continue
                delivery = deliver_slot(slot_db, rep, fresh)
                record(slot_db, 'worker', 'report.delivered',
                       {'id': report_id, 'delivery': delivery.id, 'slot': fresh.id,
                        'version': fresh.version_id, 'slot_key': fresh.slot_key})
                slot_db.commit()
        except Exception as e:
            # 留痕失败原因，场次保持 pending，下一轮继续重试且不重复留档。
            logging.exception('Slot delivery failed slot=%s', slot_id)
            try:
                with Session() as err_db:
                    fresh = err_db.get(ShiftSlot, slot_id)
                    if fresh and fresh.status == 'pending':
                        fresh.last_error = str(e)[:500]
                    err_db.commit()
            except Exception:
                logging.exception('Failed to record slot error')
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        ids=list(db.scalars(select(Report.id).where(Report.enabled==True)))
        modes={rid: db.get(Report,rid).schedule_mode for rid in ids}
    for rid in ids:
        if modes[rid]=='calendar':
            _tick_calendar(rid)
            continue
        with Session() as db:
            due=db.get(Report,rid)
            if due and due.enabled and due.next_run is not None and due.next_run<=time.time():
                try:
                    _tick_interval(db,due)
                except Exception:
                    logging.exception('Interval delivery failed report=%s', rid)
                    db.rollback()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
