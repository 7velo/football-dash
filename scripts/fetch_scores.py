#!/usr/bin/env python3
"""自动抓取比赛比分，更新 data.json"""
import json, os, urllib.request, urllib.parse, sys
from datetime import datetime, timedelta

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(REPO_DIR, "data.json")

# ESPN联赛代码映射
LEAGUE_CODES = {
    "欧冠": "uefa.champions",
    "瑞典超": "SWE.1", 
    "巴甲": "BRA.1",
    "挪超": "NORWAY.1",
    "芬兰超": "FINLAND.1",
    "K联赛": "KOREA.1",
    "美职联": "USA.1",
}

def fetch_espn_scoreboard(league_code, date_str):
    """从ESPN获取某联赛某日期的比赛"""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard?dates={date_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        events = data.get("events", [])
        results = []
        for e in events:
            comp = e.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) >= 2:
                home = competitors[0]["team"]["displayName"]
                away = competitors[1]["team"]["displayName"]
                status = comp.get("status", {}).get("type", {}).get("name", "")
                # 只看已结束的比赛
                if "FINAL" in status or "FT" in status or "FULL_TIME" in status:
                    home_score = competitors[0].get("score", "")
                    away_score = competitors[1].get("score", "")
                    results.append({
                        "home": home, "away": away,
                        "score": f"{home_score}-{away_score}",
                        "home_score": int(home_score) if home_score else None,
                        "away_score": int(away_score) if away_score else None,
                    })
        return results
    except Exception as e:
        print(f"  ESPN获取失败: {e}")
        return []

def determine_match_result(home_score, away_score, pick):
    """根据比分和选项判断是否中奖"""
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        actual = "胜"
    elif home_score < away_score:
        actual = "负"
    else:
        actual = "平"
    if pick == actual:
        return "win"
    if "或" in pick and actual in pick.split("或"):
        return "win"
    return "lose"

def main():
    print(f"⏰ 自动查分 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    if not os.path.exists(DATA_PATH):
        print("❌ data.json 不存在")
        return
    
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 找所有待赛的比赛
    pending = []
    for t in data.get("tickets", []):
        for i, m in enumerate(t["matches"]):
            if m.get("result") == "pending":
                pending.append((t, i, m))
    
    if not pending:
        print("✅ 没有待赛的比赛")
        return
    
    print(f"🔍 找到 {len(pending)} 场待赛比赛")
    
    updated = 0
    for ticket, match_idx, match in pending:
        league = match.get("league", "")
        date = ticket.get("date", "")
        home = match.get("home", "")
        away = match.get("away", "")
        pick = match.get("pick", "")
        
        print(f"\n  检查: {home} vs {away} ({date}, {league})")
        
        code = LEAGUE_CODES.get(league, "")
        if not code:
            print(f"    跳过: 未知联赛 {league}")
            continue
        
        results = fetch_espn_scoreboard(code, date.replace("-", ""))
        
        found = False
        for r in results:
            # 简单匹配: 检查队名是否包含关键词
            h_keywords = home[:2] if len(home) > 1 else home
            a_keywords = away[:2] if len(away) > 1 else away
            
            if (h_keywords.lower() in r["home"].lower() or h_keywords.lower() in r["away"].lower() or
                a_keywords.lower() in r["home"].lower() or a_keywords.lower() in r["away"].lower()):
                
                result = determine_match_result(r["home_score"], r["away_score"], pick)
                if result is not None:
                    match["result"] = result
                    match["score"] = r["score"]
                    print(f"    ✅ 找到! {r['home']} {r['score']} {r['away']} → {'中' if result=='win' else '错'}")
                    updated += 1
                    found = True
                    break
        
        if not found:
            print(f"    ⚠️ 未在ESPN找到匹配")
    
    if updated > 0:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已更新 {updated} 场比赛结果")
    else:
        print(f"\nℹ️ 未更新任何比赛")

if __name__ == "__main__":
    main()
