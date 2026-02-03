# scheduler_engine.py
import os
import time
import psutil
import threading
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger


log = logging.getLogger("engine")

class Engine:
    def __init__(self, store, executor):
        self.store = store
        self.executor = executor
        self.scheduler = BackgroundScheduler()
        self.running_lock = {}  # job_id -> threading.Lock()

    def start(self):
        self.scheduler.start()
        log.info("scheduler started")

    def stop(self):
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        log.info("scheduler stopped")

    def reload_jobs(self):
        self.scheduler.remove_all_jobs()
        jobs = self.store.list_jobs(enabled_only=True)
        for job in jobs:
            self._schedule_job(job)
        log.info("jobs reloaded: %d", len(jobs))


    def _schedule_job(self, job: dict):
        job_id = int(job["id"])
        self.running_lock.setdefault(job_id, threading.Lock())

        ttype = job["trigger_type"]

        if ttype == "interval":
            sec = int(job["interval_sec"] or 60)
            trigger = IntervalTrigger(seconds=sec)

        elif ttype == "daily":
            hh, mm = (job.get("daily_time") or "09:00").split(":")
            trigger = CronTrigger(hour=int(hh), minute=int(mm))

        elif ttype == "weekly":
            # 예: "mon,wed,fri" 또는 "mon-fri"
            hh, mm = (job.get("daily_time") or "09:00").split(":")
            dow = (job.get("day_of_week") or "mon").strip()
            trigger = CronTrigger(day_of_week=dow, hour=int(hh), minute=int(mm))

        elif ttype == "monthly":
            hh, mm = (job.get("daily_time") or "09:00").split(":")
            dom = int(job.get("day_of_month") or 1)   # 매월 1일 기본
            trigger = CronTrigger(day=dom, hour=int(hh), minute=int(mm))

        elif ttype == "cron":
            # cron_expr: "분 시 일 월 요일" (APScheduler는 5필드 Cron도 지원)
            expr = (job.get("cron_expr") or "").strip()
            if not expr:
                return  # 잘못된 설정이면 등록 안 함
            parts = expr.split()
            if len(parts) != 5:
                return
            minute, hour, day, month, dow = parts
            trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)

        else:
            return

        self.scheduler.add_job(
            lambda j=job: self._try_run(j),
            trigger=trigger,
            id=str(job_id),
            replace_existing=True,
            max_instances=1
        )

    def run_now(self, job_id: int):
        job = self.store.get_job(job_id)
        if not job:
            return
        # 별도 스레드에서 실행 (UI 응답 유지)
        threading.Thread(target=self._try_run, args=(job,), daemon=True).start()

    def _cond_ok(self, job: dict) -> bool:
        ctype = job.get("cond_type")
        cval = (job.get("cond_value") or "").strip()
        if not ctype:
            return True

        if ctype == "file_exists":
            return os.path.exists(cval)

        if ctype == "process_not_running":
            pname = cval.lower()
            for p in psutil.process_iter(["name"]):
                try:
                    if (p.info["name"] or "").lower() == pname:
                        return False
                except Exception:
                    continue
            return True

        return True

    def _try_run(self, job: dict):
        job_id = int(job["id"])
        lock = self.running_lock[job_id]

        prevent_overlap = int(job.get("prevent_overlap") or 1)

        if prevent_overlap and not lock.acquire(blocking=False):
            self.store.insert_run(job_id, status="SKIPPED", message="prevent_overlap")
            return

        try:
            if not self._cond_ok(job):
                self.store.insert_run(job_id, status="SKIPPED", message="condition_not_met")
                return

            run_id = self.store.insert_run(job_id, status="RUNNING", message="started")

            retry_count = int(job.get("retry_count") or 0)
            retry_delay = int(job.get("retry_delay_sec") or 5)
            attempts = retry_count + 1

            last = None
            for i in range(attempts):
                last = self.executor.run(job)
                self.store.finish_run(run_id, **last)

                if last["status"] == "SUCCESS":
                    break

                if i < attempts - 1:
                    time.sleep(retry_delay)

            log.info("job done: id=%s status=%s", job_id, (last or {}).get("status"))
        except Exception as e:
            self.store.insert_run(job_id, status="FAIL", message=f"engine_exception: {e}")
        finally:
            if prevent_overlap:
                try:
                    lock.release()
                except Exception:
                    pass
