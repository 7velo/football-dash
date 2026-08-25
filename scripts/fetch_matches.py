#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_matches.py —— 抓取比赛数据,输出 matches.json(仓库根目录)

数据源:
- 英超/西甲/德甲/意甲/法甲/日职/芬超/瑞超:ESPN scoreboard API(免费、无需 key)
  https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD
- 韩职:ESPN 无此联赛,用 TheSportsDB 免费 API 兜底(搜索 K League)
  拿不到就跳过,并在 matches.json 里标记 "korean_unavailable": true

输出结构:
{
  "generated_at": "2026-07-21T12:00:00+08:00",
  "korean_unavailable": false,
  "matches": [
    {"matchId":"...", "league":"eng.1", "league_cn":"英超",
     "kickoff":"2026-07-21T20:00:00+08:00",
     "home":"...", "away":"...", "score_home":2, "score_away":1, "status":"fin"}
  ]
}
status: pre(未开赛) / in(进行中) / fin(已完场)
时间统一为北京时间(Asia/Shanghai, +08:00)。
仅用 Python 标准库,无第三方依赖。
"""
import json
import os
import datetime
import urllib.request

BEIJING = datetime.timezone(datetime.timedelta(hours=8))
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={date}"
TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3/"

# ESPN 联赛标识(已实测可用) -> 中文名
LEAGUES = [
    ("eng.1", "英超"),
    ("esp.1", "西甲"),
    ("ger.1", "德甲"),
    ("ita.1", "意甲"),
    ("fra.1", "法甲"),
    ("jpn.1", "日职"),
    ("fin.1", "芬超"),
    ("swe.1", "瑞超"),
]
LEAGUE_CN = dict(LEAGUES)

# ESPN status.type.state -> 统一状态
STATUS_MAP = {"pre": "pre", "in": "in", "post": "fin", "final": "fin"}


def http_get(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "football-dash/1.0 (https://github.com/7velo/football-dash)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def to_num(v):
    """比分转 int,空值转 None"""
    try:
        if v is None or str(v).strip() == "":
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def to_beijing_iso(ts):
    """各种来源的时间字符串 -> 北京时间 ISO,如 2026-07-21T20:00:00+08:00"""
    if not ts:
        return ""
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif len(s) >= 16 and s[10] == " ":
        s = s.replace(" ", "T")
    if len(s) == 19 and s[10] == "T":  # 无时区,默认按 UTC
        s += "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(BEIJING).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except ValueError:
        return str(ts)


def fetch_espn_league(league, date):
    """抓单个联赛单日赛程(ESPN scoreboard)"""
    url = ESPN_BASE.format(league=league, date=date)
    try:
        payload = json.loads(http_get(url))
    except Exception as exc:
        print(f"  [ESPN {league}] 请求失败: {exc}")
        return []
    out = []
    for ev in payload.get("events", []):
        try:
            comps = ev.get("competitions", [{}])[0].get("competitors", [])
            home_c = next((c for c in comps if c.get("homeAway") == "home"), None)
            away_c = next((c for c in comps if c.get("homeAway") == "away"), None)
            if not home_c or not away_c:
                continue
            state = ev.get("status", {}).get("type", {}).get("state", "pre")
            out.append({
                "matchId": str(ev.get("id", "")),
                "league": league,
                "league_cn": LEAGUE_CN.get(league, league),
                "kickoff": to_beijing_iso(ev.get("date", "")),
                "home": home_c.get("team", {}).get("displayName", ""),
                "away": away_c.get("team", {}).get("displayName", ""),
                "score_home": to_num(home_c.get("score")),
                "score_away": to_num(away_c.get("score")),
                "status": STATUS_MAP.get(state, "pre"),
            })
        except Exception as exc:
            print(f"  [ESPN {league}] 单场解析失败: {exc}")
    return out


# TheSportsDB 中 K League 1 的联赛 id(已实测 = 4689);free key 下 all_leagues 列表被截断,
# 所以优先直接探测候选 id,失败再退回名称搜索
KOREAN_LEAGUE_IDS = ["4689", "4679", "4678"]


def tsdb_status(code):
    """TheSportsDB strStatus 代码 -> 统一状态"""
    c = (code or "").upper()
    if c in ("FT", "AET", "PEN", "FT_PEN", "WO"):
        return "fin"
    if c in ("LIVE", "1H", "2H", "HT", "ET", "P"):
        return "in"
    return "pre"  # NS / 空 = 未开赛


def fetch_korean():
    """韩职兜底:TheSportsDB 抓 K League 未来赛程。失败返回 (None, 原因)"""
    lid = None
    for cand in KOREAN_LEAGUE_IDS:
        try:
            payload = json.loads(http_get(TSDB_BASE + f"lookupleague.php?id={cand}"))
            lg = payload.get("leagues") or []
            if lg and "K League" in (lg[0].get("strLeague") or ""):
                lid = cand
                break
        except Exception:
            continue
    if lid is None:  # 退回名称搜索
        try:
            payload = json.loads(http_get(TSDB_BASE + "all_leagues.php"))
            kl = [l for l in payload.get("leagues", []) if "K League" in (l.get("strLeague") or "")]
            if kl:
                lid = kl[0].get("idLeague")
        except Exception as exc:
            return None, f"TheSportsDB 搜索失败: {exc}"
    if lid is None:
        return None, "TheSportsDB 未找到 K League 联赛"
    try:
        payload = json.loads(http_get(TSDB_BASE + f"eventsnextleague.php?id={lid}"))
    except Exception as exc:
        return None, f"TheSportsDB 赛事抓取失败: {exc}"
    events = payload.get("events") or []
    matches = []
    for ev in events:
        name = (ev.get("strEvent") or "") or ""
        if " vs " in name:
            home, away = name.split(" vs ", 1)
        else:
            home, away = name, ""
        if not home or not away:
            continue
        st = tsdb_status(ev.get("strStatus"))
        matches.append({
            "matchId": str(ev.get("idEvent", "")),
            "league": "kor.1",
            "league_cn": "韩职",
            "kickoff": to_beijing_iso(ev.get("strTimestamp") or ev.get("dateEvent", "")),
            "home": home.strip(),
            "away": away.strip(),
            "score_home": to_num(ev.get("intHomeScore")),
            "score_away": to_num(ev.get("intAwayScore")),
            "status": st,
        })
    if not matches:
        return None, "K League 近期无赛程"
    return matches, None


def main():
    today = datetime.datetime.now(BEIJING)
    dates = [(today + datetime.timedelta(days=i)).strftime("%Y%m%d") for i in range(2)]  # 今天 + 明天
    all_matches = []
    for league, cn in LEAGUES:
        got = []
        for d in dates:
            got += fetch_espn_league(league, d)
        seen, uniq = set(), []
        for m in sorted(got, key=lambda x: x["kickoff"]):  # 去重(按 matchId)+ 按开赛排序
            if m["matchId"] not in seen:
                seen.add(m["matchId"])
                uniq.append(m)
        all_matches += uniq
        print(f"  {cn}: {len(uniq)} 场")

    korean, kerr = fetch_korean()
    korean_unavailable = korean is None
    if korean:
        all_matches += korean
        print(f"  韩职: {len(korean)} 场")
    else:
        print(f"  韩职: 暂缺({kerr})")

    all_matches.sort(key=lambda x: x["kickoff"])
    out = {
        "generated_at": today.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "korean_unavailable": korean_unavailable,
        "matches": all_matches,
    }
    out_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "matches.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已写入 {out_path},共 {len(all_matches)} 场")


if __name__ == "__main__":
    main()
