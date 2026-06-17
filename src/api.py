from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.client import Zhibo8Client

WORLD_CUP_LEAGUE_ID = "4"
MONSTER_USER_ID = "63"
MONSTER_USER_NAME = "怪兽"

LIST_URL = "https://bifen4m.qiumibao.com/json/list.htm"
MATCH_INFO_URL = "https://bifen4pc2.qiumibao.com/json/{date}/{saishi_id}.htm"
MATCH_META_URL = "https://s.qiumibao.com/json/match/{saishi_id}.htm"
MAX_SID_URL = "https://dingshi4pc.qiumibao.com/livetext/data/cache/max_sid/{saishi_id}/0.htm"
LIVETEXT_URL = (
    "https://dingshi4pc.qiumibao.com/livetext/data/cache/"
    "livetext/{saishi_id}/0/lit_page_2/{max_sid}.htm"
)
LINEUP_URL = "https://dc.qiumibao.com/dc/matchs/data/{date}/match_lineup_{saishi_id}.htm"
ANIMATE_URL = "https://dc.qiumibao.com/dc/matchs/data/{date}/animate_v2_{saishi_id}.htm"
ANIMATE_CODE_URL = "https://dc.qiumibao.com/dc/matchs/data/{date}/animate_v2_{saishi_id}_code.htm"


@dataclass
class MatchSummary:
    saishi_id: str
    home_team: str
    away_team: str
    sdate: str
    time: str
    url: str
    leagueid: str
    period_cn: str
    home_score: str
    away_score: str
    state: str


def parse_saishi_id(value: str) -> str:
    match = re.search(r"match(\d+)v", value)
    if match:
        return match.group(1)
    if value.isdigit():
        return value
    raise ValueError(f"无法解析比赛 ID: {value}")


def list_matches(client: Zhibo8Client, *, league_id: str | None = None) -> list[MatchSummary]:
    payload = client.get_json(LIST_URL)
    results: list[MatchSummary] = []
    for item in payload.get("list") or []:
        if item.get("type") != "football":
            continue
        if league_id and str(item.get("leagueid")) != str(league_id):
            continue
        results.append(
            MatchSummary(
                saishi_id=str(item["id"]),
                home_team=str(item.get("home_team") or ""),
                away_team=str(item.get("visit_team") or ""),
                sdate=str(item.get("sdate") or ""),
                time=str(item.get("time") or ""),
                url=str(item.get("url") or ""),
                leagueid=str(item.get("leagueid") or ""),
                period_cn=str(item.get("period_cn") or ""),
                home_score=str(item.get("home_score") or ""),
                away_score=str(item.get("visit_score") or ""),
                state=str(item.get("state") or ""),
            )
        )
    return results


def list_world_cup_matches(client: Zhibo8Client) -> list[MatchSummary]:
    return list_matches(client, league_id=WORLD_CUP_LEAGUE_ID)


def fetch_match_meta(client: Zhibo8Client, saishi_id: str) -> dict[str, Any]:
    data = client.get_json(MATCH_META_URL.format(saishi_id=saishi_id))
    return data if isinstance(data, dict) else {}


def fetch_match_info(client: Zhibo8Client, saishi_id: str, sdate: str) -> dict[str, Any]:
    data = client.get_json(MATCH_INFO_URL.format(date=sdate, saishi_id=saishi_id))
    return data if isinstance(data, dict) else {}


def fetch_lineup(client: Zhibo8Client, saishi_id: str, sdate: str) -> dict[str, Any]:
    data = client.get_json(LINEUP_URL.format(date=sdate, saishi_id=saishi_id))
    return data if isinstance(data, dict) else {}


def fetch_animate_code(client: Zhibo8Client, saishi_id: str, sdate: str) -> int:
    text = client.get_text(ANIMATE_CODE_URL.format(date=sdate, saishi_id=saishi_id))
    return int(text)


def fetch_animate(client: Zhibo8Client, saishi_id: str, sdate: str) -> dict[str, Any]:
    data = client.get_json(ANIMATE_URL.format(date=sdate, saishi_id=saishi_id))
    return data if isinstance(data, dict) else {}


def fetch_max_sid(client: Zhibo8Client, saishi_id: str) -> int:
    text = client.get_text(MAX_SID_URL.format(saishi_id=saishi_id))
    return int(text)


def fetch_livetext(client: Zhibo8Client, saishi_id: str, max_sid: int) -> list[dict[str, Any]]:
    if max_sid <= 0:
        return []
    url = LIVETEXT_URL.format(saishi_id=saishi_id, max_sid=max_sid)
    response = client.http.get(url, timeout=client.timeout)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def is_monster_brief(item: dict[str, Any]) -> bool:
    if str(item.get("user_id") or "") == MONSTER_USER_ID:
        return True
    return str(item.get("user_chn") or "") == MONSTER_USER_NAME


def format_brief(item: dict[str, Any]) -> str:
    parts = [f"{item.get('live_ptime', '')} {item.get('live_text', '')}".strip()]
    img_url = str(item.get("img_url") or "").strip()
    if img_url:
        parts.append(f"[图片] {img_url}")
    text_url = str(item.get("text_url") or "").strip()
    if text_url.startswith("http"):
        parts.append(f"[视频] {text_url}")
    score = f"{item.get('home_score', '-')}-{item.get('visit_score', '-')}"
    return f"[{score}] {' '.join(part for part in parts if part)}"


def fetch_recent_monster_briefs(
    client: Zhibo8Client,
    saishi_id: str,
    *,
    limit: int = 30,
) -> tuple[list[str], int]:
    max_sid = fetch_max_sid(client, saishi_id)
    if max_sid <= 0:
        return [], 0

    seen_sids: set[int] = set()
    collected: list[tuple[int, str]] = []
    misses = 0
    sid = max_sid

    while sid > 0 and len(collected) < limit and misses < 15:
        batch = fetch_livetext(client, saishi_id, sid)
        if not batch:
            misses += 1
            sid -= 1
            continue

        misses = 0
        min_sid = sid
        for item in batch:
            live_sid = int(item.get("live_sid") or 0)
            if live_sid <= 0 or live_sid in seen_sids:
                continue
            seen_sids.add(live_sid)
            min_sid = min(min_sid, live_sid)
            if is_monster_brief(item):
                collected.append((live_sid, format_brief(item)))

        sid = min_sid - 1

    collected.sort(key=lambda pair: pair[0])
    last_sid = max(seen_sids) if seen_sids else max_sid
    return [text for _, text in collected[-limit:]], last_sid


def normalize_starters(lineup_payload: dict[str, Any], team_id: str) -> list[dict[str, Any]]:
    data = lineup_payload.get("data") or {}
    players = data.get(team_id) or []
    starters = [player for player in players if player.get("status") == "z"]
    return starters


def resolve_match_date(
    client: Zhibo8Client,
    saishi_id: str,
    *,
    sdate: str | None = None,
) -> str:
    if sdate:
        return sdate
    meta = fetch_match_meta(client, saishi_id)
    match_date = meta.get("match_date") or meta.get("sdate")
    if match_date:
        return str(match_date)
    for item in list_matches(client):
        if item.saishi_id == saishi_id and item.sdate:
            return item.sdate
    raise RuntimeError(f"无法解析比赛 {saishi_id} 的日期")
