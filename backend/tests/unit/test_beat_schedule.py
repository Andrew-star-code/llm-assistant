"""Плановые задачи scheduler — по часам (crontab), а не интервалом от старта процесса."""

from __future__ import annotations

from celery.schedules import crontab

from app.workers.celery_app import celery_app


def test_beat_tasks_run_on_wall_clock() -> None:
    # Интервал отсчитывается от старта beat, а файл расписания живёт в /tmp контейнера:
    # частое пересоздание scheduler отменяло бы запуск. По часам — нет.
    schedule = celery_app.conf.beat_schedule
    assert {"exports-cleanup", "retention-purge"} <= set(schedule)
    assert all(isinstance(entry["schedule"], crontab) for entry in schedule.values())
    registered = set(celery_app.tasks)
    assert {entry["task"] for entry in schedule.values()} <= registered
