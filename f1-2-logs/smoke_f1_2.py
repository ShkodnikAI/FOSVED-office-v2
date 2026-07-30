#!/usr/bin/env python3
"""Smoke-test F-1.2: verify /remind parsing conditions via string analysis.
This duplicates the EXACT substring logic from app.mlog and checks all cases."""

strings = {
    "daily_ok":    "/remind daily 09:00 проверка",
    "once_ok":     "/remind once 2026-07-25 09:00 проверка",
    "weekly_ok":   "/remind weekly mon 09:00 проверка",
    "yearly_ok":   "/remind yearly 03-15 09:00 проверка",
    "daily_bad":   "/remind daily 0900 проверка",
    "weekly_bad":  "/remind weekly xyz 09:00 проверка",
    "once_bad":    "/remind once 2026-07-25 0900 проверка",
}

print("=== POSITIVE CASES ===")

# A.1: len(text) > 20.0 and substring(text, 16.0, 17.0) == ":"
daily_ok = strings["daily_ok"]
a1_pos = len(daily_ok) > 20 and daily_ok[16:17] == ":"
print(f"A.1 daily positive: {a1_pos}  (substring(16,17)='{daily_ok[16:17]}', substring(15,16)='{daily_ok[15:16]}')")

# A.2: len(text) > 29.0 and substring(text, 26.0, 27.0) == ":"
once_ok = strings["once_ok"]
a2_pos = len(once_ok) > 29 and once_ok[26:27] == ":"
print(f"A.2 once positive:  {a2_pos}  (substring(26,27)='{once_ok[26:27]}', substring(24,25)='{once_ok[24:25]}')")

# A.3: valid_day and len(text) > 25.0 and substring(text, 21.0, 22.0) == ":"
weekly_ok = strings["weekly_ok"]
day_part_ok = weekly_ok[15:18]
valid_days = ["mon","tue","wed","thu","fri","sat","sun"]
valid_day_ok = day_part_ok in valid_days
a3_pos = valid_day_ok and len(weekly_ok) > 25 and weekly_ok[21:22] == ":"
print(f"A.3 weekly positive: {a3_pos}  (day_part='{day_part_ok}', valid={valid_day_ok}, substring(21,22)='{weekly_ok[21:22]}')")

# yearly control: len(text) > 27.0 and substring(text, 17.0, 18.0) == "-"
yearly_ok = strings["yearly_ok"]
yearly_pos = len(yearly_ok) > 27 and yearly_ok[17:18] == "-"
print(f"yearly control:     {yearly_pos}  (substring(17,18)='{yearly_ok[17:18]}')")

print()
print("=== NEGATIVE CASES ===")

# A.1 negative
daily_bad = strings["daily_bad"]
a1_neg = len(daily_bad) > 20 and daily_bad[16:17] == ":"
print(f"A.1 daily negative: {a1_neg}  (substring(16,17)='{daily_bad[16:17]}')")

# A.2 negative
once_bad = strings["once_bad"]
a2_neg = len(once_bad) > 29 and once_bad[26:27] == ":"
print(f"A.2 once negative:  {a2_neg}  (substring(26,27)='{once_bad[26:27]}')")

# A.3 negative
weekly_bad = strings["weekly_bad"]
day_part_bad = weekly_bad[15:18]
valid_day_bad = day_part_bad in valid_days
a3_neg = valid_day_bad and len(weekly_bad) > 25 and weekly_bad[21:22] == ":"
print(f"A.3 weekly negative: {a3_neg}  (day_part='{day_part_bad}', valid={valid_day_bad}, substring(21,22)='{weekly_bad[21:22]}')")

print()
print("=== EXTRACTION VERIFICATION ===")

# daily: fire_time = substring(14,19), reminder_text = substring(20, len)
print(f"daily  fire_time={daily_ok[14:19]}  reminder_text={daily_ok[20:]}")

# once: ev_date = substring(13,23), fire_time = substring(24,29), reminder_text = substring(30, len)
print(f"once   ev_date={once_ok[13:23]}  fire_time={once_ok[24:29]}  reminder_text={once_ok[30:]}")

# weekly: fire_time = substring(19,24), reminder_text = substring(25, len)
print(f"weekly fire_time={weekly_ok[19:24]}  reminder_text={weekly_ok[25:]}")

# yearly: monthday = substring(15,20), fire_time = substring(21,26), reminder_text = substring(27, len)
print(f"yearly monthday={yearly_ok[15:20]}  fire_time={yearly_ok[21:26]}  reminder_text={yearly_ok[27:]}")
