#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import select
import shutil
import sys
import termios
import time
import tty
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import requests

from src.animator import MatchPhase, PitchAnimator
from src.api import (
    fetch_animate,
    fetch_animate_code,
    fetch_lineup,
    fetch_livetext_updates,
    fetch_match_events,
    fetch_match_info,
    fetch_recent_livetext,
    fetch_team_stats,
    format_livetext_line,
    list_today_world_cup_matches,
    parse_saishi_id,
    resolve_match_date,
)
from src.client import Zhibo8Client
from src.config import load_zhibo8_config, save_zhibo8_config
from src.dashboard import LineupView, render_dashboard

FEED_MAXLEN = 200

_ALT_SCREEN_ON = "\033[?1049h"
_ALT_SCREEN_OFF = "\033[?1049l"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_HOME_CLEAR = "\033[H\033[J"


def enter_alt_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write(_ALT_SCREEN_ON)
        sys.stdout.flush()


def leave_alt_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write(_SHOW_CURSOR + _ALT_SCREEN_OFF)
        sys.stdout.flush()


def refresh_screen(content: str) -> None:
    """先准备好内容再刷新，避免清屏后空窗。"""
    if not sys.stdout.isatty():
        print(content)
        return
    sys.stdout.write(_HIDE_CURSOR + _HOME_CLEAR + content)
    if not content.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.write(_SHOW_CURSOR)
    sys.stdout.flush()


def enable_cbreak_input() -> list[Any] | None:
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    return termios.tcgetattr(fd)


def set_cbreak_input(enabled: bool, saved: list[Any] | None) -> None:
    if saved is None:
        return
    fd = sys.stdin.fileno()
    if enabled:
        tty.setcbreak(fd)
    else:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def poll_key(timeout: float) -> str | None:
    if not sys.stdin.isatty():
        return None
    ready, _, _ = select.select([sys.stdin], [], [], max(timeout, 0))
    if not ready:
        return None
    return sys.stdin.read(1)


def pick_world_cup_match(client: Zhibo8Client, *, match_date: str | None = None) -> str:
    target_date = match_date or date.today().isoformat()
    matches = list_today_world_cup_matches(client, on_date=target_date)
    if not matches:
        raise RuntimeError(f"{target_date} 没有世界杯比赛")

    print(f"\n直播吧世界杯 · {target_date} 比赛列表\n")
    for index, item in enumerate(matches, start=1):
        if item.home_score or item.away_score:
            score = f"{item.home_score}-{item.away_score}"
        else:
            score = "vs"
        print(
            f"  {index}. {item.time}  "
            f"{item.home_team} {score} {item.away_team}  "
            f"({item.period_cn or '未开赛'})"
        )
    while True:
        raw = input("\n输入序号进入文字直播: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            selected = matches[int(raw) - 1]
            print(f"已进入: {selected.home_team} vs {selected.away_team} (初始数据较大, 请耐心等候加载)")
            return selected.saishi_id
        print("无效序号，请重试。")


def resolve_match_phase(match_info: dict[str, Any] | None) -> MatchPhase:
    if not match_info:
        return "pre"
    period = str(match_info.get("period_cn") or "")
    state = str(match_info.get("state") or "")
    if "完" in period or state == "3":
        return "finished"
    if not period or any(token in period for token in ("未", "待定")):
        return "pre"
    return "live"


def format_fetch_error(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        return f"[网络错误] {exc}"
    if isinstance(exc, (ValueError, KeyError, TypeError, json.JSONDecodeError)):
        return f"[数据错误] {exc}"
    return f"[拉取失败] {exc}"


def load_initial_data(
    client: Zhibo8Client,
    *,
    saishi_id: str,
    sdate: str,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any],
    int,
    list[str],
    int,
]:
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_info = pool.submit(fetch_match_info, client, saishi_id, sdate)
        future_lineup = pool.submit(fetch_lineup, client, saishi_id, sdate)
        future_animate = pool.submit(fetch_animate, client, saishi_id, sdate)
        future_code = pool.submit(fetch_animate_code, client, saishi_id, sdate)
        future_livetext = pool.submit(fetch_recent_livetext, client, saishi_id)

        match_info = future_info.result()
        lineup = future_lineup.result()
        animate_payload = future_animate.result()
        animate_code = future_code.result()
        live_feed, last_sid = future_livetext.result()

    return match_info, lineup, animate_payload, animate_code, live_feed, last_sid


def run_dashboard(
    *,
    saishi_id: str,
    match_date: str | None = None,
    once: bool = False,
) -> None:
    client = Zhibo8Client()
    config = load_zhibo8_config()
    saishi_id = parse_saishi_id(saishi_id)
    if match_date:
        sdate = match_date
    else:
        try:
            sdate = resolve_match_date(client, saishi_id)
        except RuntimeError:
            sdate = date.today().isoformat()

    config["saishi_id"] = saishi_id
    config["match_date"] = sdate
    save_zhibo8_config(config)

    poll = config.get("poll_intervals") or {}
    livetext_interval = max(int(poll.get("livetext", 2)), 1)
    animate_interval = max(int(poll.get("animate", 2)), 1)
    lineup_interval = max(int(poll.get("lineup", 60)), 5)
    score_interval = max(int(poll.get("score", 10)), 5)
    report_interval = max(int(poll.get("report", 30)), 10)

    match_url = f"https://www.zhibo8.com/zhibo/zuqiu/2026/match{saishi_id}v.htm"
    saved_tty = enable_cbreak_input()

    enter_alt_screen()
    set_cbreak_input(True, saved_tty)
    refresh_screen("直播吧世界杯终端看板\n\n正在加载比赛数据，请稍候...")

    try:
        match_info, lineup, animate_payload, animate_code, initial_feed, last_sid = load_initial_data(
            client,
            saishi_id=saishi_id,
            sdate=sdate,
        )
    except Exception as exc:  # noqa: BLE001
        set_cbreak_input(False, saved_tty)
        leave_alt_screen()
        raise RuntimeError(f"初始数据加载失败: {exc}") from exc

    live_feed: deque[str] = deque(initial_feed, maxlen=FEED_MAXLEN)
    team_stats: dict[str, dict[str, str]] = {}
    events: list[dict[str, Any]] = []
    status_message = ""
    animator = PitchAnimator()
    animator.load_animate(animate_payload, animate_code=animate_code)
    last_animate_code = animate_code
    phase = resolve_match_phase(match_info)
    animator.set_phase(phase, hint=str((match_info or {}).get("period_cn") or ""))

    last_livetext = time.time()
    last_animate = time.time()
    last_lineup = time.time()
    last_score = time.time()
    last_report = 0.0
    lineup_view: LineupView = "formation"
    last_frame_hash = ""
    force_render = True

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            while True:
                now = time.time()
                status_message = ""
                pending: dict[str, Any] = {}

                try:
                    if match_info is None or now - last_score >= score_interval:
                        pending["score"] = pool.submit(fetch_match_info, client, saishi_id, sdate)
                    if lineup is None or now - last_lineup >= lineup_interval:
                        pending["lineup"] = pool.submit(fetch_lineup, client, saishi_id, sdate)
                    if now - last_report >= report_interval:
                        pending["report_stats"] = pool.submit(
                            fetch_team_stats, client, saishi_id, sdate
                        )
                        pending["report_events"] = pool.submit(
                            fetch_match_events, client, saishi_id, sdate
                        )
                    if now - last_animate >= animate_interval:
                        pending["animate_code"] = pool.submit(
                            fetch_animate_code, client, saishi_id, sdate
                        )
                    if now - last_livetext >= livetext_interval:
                        pending["livetext"] = pool.submit(
                            fetch_livetext_updates, client, saishi_id, last_sid
                        )

                    if "score" in pending:
                        match_info = pending["score"].result()
                        last_score = now
                        phase = resolve_match_phase(match_info)
                        if phase != animator.state.phase:
                            animator.set_phase(phase, hint=str(match_info.get("period_cn") or ""))

                    if "lineup" in pending:
                        lineup = pending["lineup"].result()
                        last_lineup = now

                    if "report_stats" in pending:
                        team_stats = pending["report_stats"].result()
                    if "report_events" in pending:
                        events = pending["report_events"].result()
                    if "report_stats" in pending or "report_events" in pending:
                        last_report = now

                    if "animate_code" in pending:
                        animate_code = pending["animate_code"].result()
                        if animate_code != last_animate_code:
                            animate_payload = fetch_animate(client, saishi_id, sdate)
                            animator.load_animate(animate_payload, animate_code=animate_code)
                            last_animate_code = animate_code
                            force_render = True
                        last_animate = now

                    if "livetext" in pending:
                        updates, last_sid = pending["livetext"].result()
                        for item in updates:
                            line = format_livetext_line(item)
                            if line:
                                live_feed.append(line)
                            live_text = str(item.get("live_text") or "")
                            if live_text:
                                animator.update_from_text(live_text)
                        if updates:
                            force_render = True
                        last_livetext = now

                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    status_message = format_fetch_error(exc)

                if animator.state.phase == "live":
                    animator.tick_live()
                animator.tick_animate()

                term_size = shutil.get_terminal_size((120, 30))
                frame = render_dashboard(
                    saishi_id=saishi_id,
                    match_url=match_url,
                    match_info=match_info,
                    lineup=lineup,
                    team_stats=team_stats,
                    events=events,
                    animator=animator,
                    live_feed=list(live_feed),
                    terminal_width=term_size.columns,
                    terminal_height=term_size.lines,
                    status_message=status_message,
                    lineup_view=lineup_view,
                )
                frame_hash = hashlib.md5(frame.encode(), usedforsecurity=False).hexdigest()
                if force_render or frame_hash != last_frame_hash or status_message:
                    refresh_screen(frame)
                    last_frame_hash = frame_hash
                    force_render = False

                if once:
                    return

                sleep_for = min(
                    max(livetext_interval - (time.time() - last_livetext), 0.2),
                    max(animate_interval - (time.time() - last_animate), 0.2),
                    1.0,
                )
                key = poll_key(sleep_for)
                if key in {"q", "Q"}:
                    break
                if key in {"t", "T"}:
                    lineup_view = "roster" if lineup_view == "formation" else "formation"
                    force_render = True
                if key in {"r", "R"}:
                    last_livetext = 0.0
                    last_animate = 0.0
                    last_lineup = 0.0
                    last_score = 0.0
                    last_report = 0.0
                    force_render = True
    except KeyboardInterrupt:
        pass
    finally:
        set_cbreak_input(False, saved_tty)
        leave_alt_screen()
        print("\n已退出。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="直播吧世界杯终端看板")
    parser.add_argument("--match", help="比赛 saishi_id 或 match1869192v 链接片段，指定后跳过选择")
    parser.add_argument("--date", help="比赛日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--once", action="store_true", help="只刷新一次后退出")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = Zhibo8Client()

    if args.match:
        saishi_id = args.match
    else:
        saishi_id = pick_world_cup_match(client, match_date=args.date)

    run_dashboard(saishi_id=saishi_id, match_date=args.date, once=args.once)


if __name__ == "__main__":
    main()
