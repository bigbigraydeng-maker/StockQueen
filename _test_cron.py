"""Test CronTrigger next fire time calculation for exit_passes."""
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime

nz = pytz.timezone("Pacific/Auckland")
et = pytz.timezone("US/Eastern")

# Simulate scheduler start at 17:11:22 UTC (when user deployed)
start_utc = datetime(2026, 4, 10, 17, 11, 22, tzinfo=pytz.utc)
print(f"Scheduler started: {start_utc} UTC")
print(f"  = {start_utc.astimezone(nz)} Auckland")
print(f"  = {start_utc.astimezone(et)} Eastern")
print()

# Check day_of_week in Auckland time
nz_time = start_utc.astimezone(nz)
print(f"Auckland weekday: {nz_time.strftime('%A')} (0=Mon, 6=Sun = {nz_time.weekday()})")
print(f"Auckland hour: {nz_time.hour} (cron hour='2-8')")
print()

# Test exit_passes trigger
trigger = CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/5', timezone=nz)
next_fire = trigger.get_next_fire_time(None, start_utc)
print(f"exit_passes next fire: {next_fire}")
if next_fire:
    print(f"  = {next_fire.astimezone(et)} Eastern")
    print(f"  = {next_fire.astimezone(nz)} Auckland")
print()

# Test intraday_scoring trigger (new 15-min)
trigger2 = CronTrigger(day_of_week='tue-sat', hour='1-9', minute='0,15,30,45', timezone=nz)
next_fire2 = trigger2.get_next_fire_time(None, start_utc)
print(f"intraday_scoring (15min) next fire: {next_fire2}")
if next_fire2:
    print(f"  = {next_fire2.astimezone(et)} Eastern")
print()

# Test trailing_stop trigger (should fire at 17:15)
trigger3 = CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/5', timezone=nz)
next_fire3 = trigger3.get_next_fire_time(None, start_utc)
print(f"trailing_stop next fire: {next_fire3}")

# What about current time?
now = datetime.now(pytz.utc)
print(f"\nCurrent UTC: {now}")
trigger_ep = CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/5', timezone=nz)
next_ep = trigger_ep.get_next_fire_time(None, now)
print(f"exit_passes next fire from NOW: {next_ep}")
