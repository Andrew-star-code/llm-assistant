"""Плановые задачи scheduler — по часам (crontab), а не интервалом от старта процесса."""

from __future__ import annotations

from celery.schedules import crontab

from app.core.config import load_settings
from app.workers.celery_app import ad_sync_crontab, ad_sync_entry, celery_app


def test_beat_tasks_run_on_wall_clock() -> None:
    # Интервал отсчитывается от старта beat, а файл расписания живёт в /tmp контейнера:
    # частое пересоздание scheduler отменяло бы запуск. По часам — нет.
    schedule = celery_app.conf.beat_schedule
    assert {"exports-cleanup", "retention-purge"} <= set(schedule)
    assert all(isinstance(entry["schedule"], crontab) for entry in schedule.values())
    registered = set(celery_app.tasks)
    assert {entry["task"] for entry in schedule.values()} <= registered


def test_ad_sync_runs_on_wall_clock() -> None:
    # Делитель часа — каждые N минут; иначе — раз в целое число часов, но не реже раза в сутки.
    assert ad_sync_crontab(15) == crontab(minute="*/15")
    assert ad_sync_crontab(60) == crontab(minute=47, hour="*")
    assert ad_sync_crontab(45) == crontab(minute=47, hour="*")
    assert ad_sync_crontab(180) == crontab(minute=47, hour="*/3")
    assert ad_sync_crontab(5000) == crontab(minute=47, hour=4)


def test_ad_sync_is_scheduled_only_with_ldap() -> None:
    with_ldap = load_settings(auth={"providers": ["dev", "ldap"]})
    assert ad_sync_entry(with_ldap)["ad-sync"]["task"] == "users.ad_sync"
    assert "users.ad_sync" in celery_app.tasks
    assert ad_sync_entry(load_settings(auth={"providers": ["dev"]})) == {}
    off = load_settings(auth={"providers": ["dev", "ldap"]}, ldap={"sync_interval_minutes": 0})
    assert ad_sync_entry(off) == {}
