from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from src.client import Zhibo8Client

WORLD_CUP_LEAGUE_ID = "4"

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
MATCH_EVENT_URL = "https://dc.qiumibao.com/dc/matchs/data/{date}/match_event_{saishi_id}.htm"
MATCH_TEAM_STATICS_URL = (
    "https://dc.qiumibao.com/dc/matchs/data/{date}/match_team_statics_{saishi_id}.htm"
)

STAT_LABELS: dict[str, str] = {
    "possession_percentage": "控球",
    "total_scoring_att": "射门",
    "ontarget_scoring_att": "射正",
    "won_corners": "角球",
    "fk_foul_lost": "犯规",
    "pass_percentage": "传球成功率",
    "total_pass": "传球",
    "total_tackle": "抢断",
}

_LIST_CACHE: tuple[float, list["MatchSummary"]] | None = None
_LIST_CACHE_TTL = 60.0


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


def _parse_match_list(payload: dict[str, Any]) -> list[MatchSummary]:
    results: list[MatchSummary] = []
    for item in payload.get("list") or []:
        if item.get("type") != "football":
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


def list_matches(
    client: Zhibo8Client,
    *,
    league_id: str | None = None,
    force_refresh: bool = False,
) -> list[MatchSummary]:
    global _LIST_CACHE
    now = time.time()
    if not force_refresh and _LIST_CACHE and now - _LIST_CACHE[0] < _LIST_CACHE_TTL:
        matches = _LIST_CACHE[1]
    else:
        payload = client.get_json(LIST_URL)
        matches = _parse_match_list(payload if isinstance(payload, dict) else {})
        _LIST_CACHE = (now, matches)

    if league_id:
        return [item for item in matches if str(item.leagueid) == str(league_id)]
    return matches


def list_world_cup_matches(client: Zhibo8Client) -> list[MatchSummary]:
    return list_matches(client, league_id=WORLD_CUP_LEAGUE_ID)


def list_today_world_cup_matches(
    client: Zhibo8Client,
    *,
    on_date: str | None = None,
) -> list[MatchSummary]:
    target_date = on_date or date.today().isoformat()
    matches = [
        item
        for item in list_world_cup_matches(client)
        if item.sdate == target_date
    ]
    matches.sort(key=lambda item: item.time)
    return matches


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
    url = ANIMATE_CODE_URL.format(date=sdate, saishi_id=saishi_id)
    text = client.get_text(url, cache_ttl=1.0)
    return int(text)


def fetch_animate(client: Zhibo8Client, saishi_id: str, sdate: str) -> dict[str, Any]:
    data = client.get_json(ANIMATE_URL.format(date=sdate, saishi_id=saishi_id))
    return data if isinstance(data, dict) else {}


def fetch_match_events(client: Zhibo8Client, saishi_id: str, sdate: str) -> list[dict[str, Any]]:
    try:
        payload = client.get_json(MATCH_EVENT_URL.format(date=sdate, saishi_id=saishi_id))
    except Exception:  # noqa: BLE001
        return []
    events = payload.get("data") if isinstance(payload, dict) else None
    return events if isinstance(events, list) else []


def fetch_team_stats(client: Zhibo8Client, saishi_id: str, sdate: str) -> dict[str, dict[str, str]]:
    try:
        payload = client.get_json(MATCH_TEAM_STATICS_URL.format(date=sdate, saishi_id=saishi_id))
    except Exception:  # noqa: BLE001
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def parse_match_player_data(match_info: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if not match_info:
        return [], []
    raw = match_info.get("player_data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        return [], []

    def _format_goals(items: list[Any]) -> list[str]:
        lines: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("type")) != "1" and str(item.get("code")) != "1":
                continue
            minute = str(item.get("value") or "").strip()
            name = str(item.get("player_name") or "").strip()
            if name:
                lines.append(f"{minute} {name}")
        return lines

    return _format_goals(raw.get("left") or []), _format_goals(raw.get("right") or [])


def format_match_event_line(event: dict[str, Any]) -> str | None:
    if str(event.get("is_hide") or "") == "1" and not str(event.get("mark") or ""):
        return None
    minute = str(event.get("time") or "").strip()
    code = str(event.get("event_code_cn") or "").strip()
    info = str(event.get("Info") or event.get("info") or "").strip()
    player = str(event.get("player_name_cn") or "").strip()
    if not code and not info:
        return None
    if info:
        text = info
    elif player:
        text = f"{player} {code}"
    else:
        text = code
    if minute and minute != "0":
        return f"{minute}' {text}"
    return text


def fetch_max_sid(client: Zhibo8Client, saishi_id: str) -> int:
    text = client.get_text(MAX_SID_URL.format(saishi_id=saishi_id), cache_ttl=1.0)
    return int(text)


def fetch_livetext(client: Zhibo8Client, saishi_id: str, page_sid: int) -> list[dict[str, Any]]:
    if page_sid <= 0:
        return []
    url = LIVETEXT_URL.format(saishi_id=saishi_id, max_sid=page_sid)
    response = client.http.get(url, timeout=client.timeout)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def format_livetext_line(item: dict[str, Any]) -> str:
    text = str(item.get("live_text") or "").strip()
    if not text:
        return ""
    ptime = str(item.get("live_ptime") or "").strip()
    user = str(item.get("user_chn") or "").strip()
    score = f"{item.get('home_score', '-')}-{item.get('visit_score', '-')}"
    if user:
        body = f"{user}: {text}"
    else:
        body = text
    if ptime:
        return f"[{score}] {ptime} {body}"
    return f"[{score}] {body}"


def _walk_livetext_pages(
    client: Zhibo8Client,
    saishi_id: str,
    *,
    max_sid: int | None = None,
    after_sid: int = 0,
    limit: int = 40,
    item_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if max_sid is None:
        max_sid = fetch_max_sid(client, saishi_id)
    if max_sid <= 0 or max_sid <= after_sid:
        return [], after_sid

    collected: list[dict[str, Any]] = []
    seen: set[int] = set()
    page_sid = max_sid
    misses = 0

    while page_sid > after_sid and len(collected) < limit and misses < 25:
        batch = fetch_livetext(client, saishi_id, page_sid)
        if not batch:
            misses += 1
            page_sid -= 1
            continue

        misses = 0
        min_sid = page_sid
        for item in batch:
            live_sid = int(item.get("live_sid") or 0)
            if live_sid <= 0:
                continue
            min_sid = min(min_sid, live_sid)
            if live_sid <= after_sid or live_sid in seen:
                continue
            if item_filter and not item_filter(item):
                continue
            seen.add(live_sid)
            collected.append(item)

        page_sid = min_sid - 1

    collected.sort(key=lambda item: int(item.get("live_sid") or 0))
    if collected:
        new_last = max(int(item.get("live_sid") or 0) for item in collected)
    else:
        new_last = after_sid
    return collected, new_last


def fetch_livetext_updates(
    client: Zhibo8Client,
    saishi_id: str,
    last_sid: int,
    *,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], int]:
    max_sid = fetch_max_sid(client, saishi_id)
    if max_sid <= last_sid:
        return [], last_sid
    return _walk_livetext_pages(
        client,
        saishi_id,
        max_sid=max_sid,
        after_sid=last_sid,
        limit=limit,
    )


def fetch_recent_livetext(
    client: Zhibo8Client,
    saishi_id: str,
    *,
    limit: int = 30,
) -> tuple[list[str], int]:
    items, last_sid = _walk_livetext_pages(client, saishi_id, after_sid=0, limit=limit)
    lines: list[str] = []
    for item in items:
        line = format_livetext_line(item)
        if line:
            lines.append(line)
    return lines[-limit:], last_sid


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
