#!/usr/bin/env python3
"""Loggt den Status von Monitor 15 (GitLab Server FH Aachen) aus der Uptime-Kuma-Statusseite
und erzeugt die Auswertung für das Dashboard.

  python monitor.py collect   # neue Messpunkte abrufen und in data/JJJJ-MM.csv ergänzen
  python monitor.py build     # data/*.csv auswerten -> site/ (data.json + index.html)
"""
import csv, json, shutil, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://status.fh-aachen.de/api/status-page/heartbeat/fhac"
MONITOR_ID = "15"
MONITOR_NAME = "GitLab Server FH Aachen"
TZ = ZoneInfo("Europe/Berlin")      # Tage/Wochen/Monate werden nach deutscher Zeit abgegrenzt
GAP_MIN = 5                         # größerer Abstand zwischen Messpunkten = "keine Daten" (Minuten)
UP, DOWN = {1}, {0, 2}              # 1 = Up | 0 = Down, 2 = Pending (Ausfall) | 3 = Wartung (nicht gewertet)
DATA, SITE = Path("data"), Path("site")
FMT = "%Y-%m-%dT%H:%M:%SZ"
MIN = timedelta(minutes=1)


def iso(t):
    return t.strftime(FMT)


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "gitlab-status-logger"})
    err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["heartbeatList"][MONITOR_ID]
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5)
    sys.exit(f"Abruf fehlgeschlagen: {err!r}")


def collect():
    DATA.mkdir(exist_ok=True)
    by_month = defaultdict(dict)
    for hb in fetch():
        # Uptime Kuma liefert UTC ohne Zeitzonenangabe
        t = datetime.strptime(hb["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        by_month[t.strftime("%Y-%m")][iso(t)] = str(hb["status"])
    new = 0
    for month, rows in by_month.items():
        f = DATA / f"{month}.csv"
        have = {}
        if f.exists():
            with f.open() as fh:
                have = {r["time_utc"]: r["status"] for r in csv.DictReader(fh)}
        merged = {**rows, **have}  # bereits gespeicherte Werte haben Vorrang
        new += len(merged) - len(have)
        with f.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_utc", "status"])
            for k in sorted(merged):
                w.writerow([k, merged[k]])
    print(f"{new} neue Messpunkte")


def load():
    rows = []
    for f in sorted(DATA.glob("*.csv")):
        with f.open() as fh:
            for r in csv.DictReader(fh):
                rows.append((datetime.strptime(r["time_utc"], FMT).replace(tzinfo=timezone.utc), int(r["status"])))
    return sorted(rows)


def pct(up, down):
    # abgeschnitten statt gerundet: 100 % erscheint nur, wenn es wirklich keinen Ausfall gab
    return (up * 10000 // (up + down)) / 100 if up + down else None


def build():
    rows = load()
    if not rows:
        sys.exit("Keine Daten in data/")
    now = datetime.now(timezone.utc)
    daily, weekly, monthly, hourly = (defaultdict(lambda: [0, 0]) for _ in range(4))
    for t, s in rows:
        if s not in UP | DOWN:
            continue
        i, l = (0 if s in UP else 1), t.astimezone(TZ)
        wk = l.isocalendar()
        daily[l.strftime("%Y-%m-%d")][i] += 1
        weekly[f"{wk[0]}-W{wk[1]:02d}"][i] += 1
        monthly[l.strftime("%Y-%m")][i] += 1
        hourly[l.strftime("%Y-%m-%dT%H")][i] += 1

    # Ausfälle (zusammenhängende Down/Pending-Messpunkte) und Datenlücken
    def outage(a, b, ongoing):
        return {"start": iso(a), "end": iso(b), "minutes": round((b - a).total_seconds() / 60), "ongoing": ongoing}

    outages, gaps, cur, prev = [], [], None, None
    for t, s in rows:
        if prev and t - prev > timedelta(minutes=GAP_MIN):
            if cur:
                outages.append(outage(cur, prev + MIN, False))
                cur = None
            gaps.append({"start": iso(prev), "end": iso(t), "minutes": round((t - prev).total_seconds() / 60)})
        if s in DOWN:
            cur = cur or t
        elif cur:
            outages.append(outage(cur, t, False))
            cur = None
        prev = t
    if cur:
        outages.append(outage(cur, prev + MIN, True))

    def window(days):
        c = now - timedelta(days=days)
        return pct(sum(s in UP for t, s in rows if t >= c), sum(s in DOWN for t, s in rows if t >= c))

    d0, d1 = rows[0][0].astimezone(TZ).date(), now.astimezone(TZ).date()
    rec = lambda k, v: {"k": k, "up": v[0], "down": v[1], "pct": pct(*v)}  # noqa: E731
    days, d = [], d0
    while d <= d1:
        days.append(rec(d.isoformat(), daily.get(d.isoformat(), [0, 0])))
        d += timedelta(days=1)
    cut = (d1 - timedelta(days=13)).isoformat()

    data = {
        "generated": iso(now),
        "monitor": {"id": MONITOR_ID, "name": MONITOR_NAME},
        "gap_minutes": GAP_MIN,
        "summary": {
            "last_status": rows[-1][1], "last_time": iso(rows[-1][0]), "first_time": iso(rows[0][0]),
            "samples": len(rows), "h24": window(1), "d7": window(7), "d30": window(30),
            "total": pct(sum(s in UP for _, s in rows), sum(s in DOWN for _, s in rows)),
        },
        "daily": days,
        "weekly": [rec(k, weekly[k]) for k in sorted(weekly)],
        "monthly": [rec(k, monthly[k]) for k in sorted(monthly)],
        "hourly": {k: v for k, v in hourly.items() if k[:10] >= cut},
        "outages": outages[::-1][:500],
        "gaps": gaps[::-1][:200],
    }
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False))
    shutil.copy("web/index.html", SITE / "index.html")
    print(f"{len(rows)} Messpunkte, {len(outages)} Ausfälle, {len(gaps)} Lücken")


if __name__ == "__main__":
    {"collect": collect, "build": build}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
