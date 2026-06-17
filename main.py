#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from typing import Any

from src.animator import PitchAnimator
from src.api import (
    fetch_animate,
    fetch_animate_code,
    fetch_lineup,
    fetch_livetext,
    fetch_match_info,
    fetch_max_sid,
    fetch_recent_monster_briefs,
    format_brief,
    is_monster_brief,
    list_world_cup_matches,
    parse_saishi_id,
    resolve_match_date,
)
from src.client import Zhibo8Client
from src.config import load_zhibo8_config, save_zhibo8_config
from src.dashboard import render_dashboard


def clear_screen() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def pick_world_cup_match(client: Zhibo8Client) -> str:
    matches = list_world_cup_matches(client)
    if not matches:
        raise RuntimeError("当前没有世界杯比赛")

    print("世界杯比赛列表：")
    for index, item in enumerate(matches, start=1):
        score = f"{item.home_score}-{item.away_score}" if item.home_score else "-"
        print(
            f"{index:>2}. [{item.sdate} {item.time}] "
            f"{item.home_team} {score} {item.away_team}  ({item.period_cn or '待定'})"
        )
    while True:
        raw = input("\n输入序号选择比赛: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1].saishi_id
        print("无效序号，请重试。")


def run_dashboard(
    *,
    saishi_id: str,
    match_date: str | None = None,
    once: bool = False,
) -> None:
    client = Zhibo8Client()
    config = load_zhibo8_config()
    saishi_id = parse_saishi_id(saishi_id)
    sdate = resolve_match_date(client, saishi_id, sdate=match_date or config.get("match_date") or None)

    config["saishi_id"] = saishi_id
    config["match_date"] = sdate
    save_zhibo8_config(config)

    poll = config.get("poll_intervals") or {}
    livetext_interval = max(int(poll.get("livetext", 2)), 1)
    animate_interval = max(int(poll.get("animate", 2)), 1)
    lineup_interval = max(int(poll.get("lineup", 60)), 5)
    score_interval = max(int(poll.get("score", 10)), 5)

    match_url = str(config.get("match_url") or f"https://www.src.com/zhibo/zuqiu/2026/match{saishi_id}v.htm")
    match_info: dict[str, Any] | None = None
    lineup: dict[str, Any] | None = None
    briefs, last_sid = fetch_recent_monster_briefs(client, saishi_id)
    status_message = ""
    animator = PitchAnimator()

    animate_code = fetch_animate_code(client, saishi_id, sdate)
    animator.update_from_animate(fetch_animate(client, saishi_id, sdate))
    last_animate_code = animate_code

    last_livetext = 0.0
    last_animate = 0.0
    last_lineup = 0.0
    last_score = 0.0

    print(f"进入直播吧比赛 {saishi_id} ({sdate})，按 Ctrl+C 退出。\n")
    time.sleep(1)

    while True:
        now = time.time()
        try:
            if match_info is None or now - last_score >= score_interval:
                match_info = fetch_match_info(client, saishi_id, sdate)
                last_score = now

            if lineup is None or now - last_lineup >= lineup_interval:
                lineup = fetch_lineup(client, saishi_id, sdate)
                last_lineup = now

            if now - last_animate >= animate_interval:
                animate_code = fetch_animate_code(client, saishi_id, sdate)
                if animate_code != last_animate_code:
                    animate_payload = fetch_animate(client, saishi_id, sdate)
                    animator.update_from_animate(animate_payload)
                    last_animate_code = animate_code
                last_animate = now

            if now - last_livetext >= livetext_interval:
                max_sid = fetch_max_sid(client, saishi_id)
                if max_sid > last_sid:
                    for item in fetch_livetext(client, saishi_id, max_sid):
                        sid = int(item.get("live_sid") or 0)
                        if sid <= last_sid:
                            continue
                        last_sid = sid
                        if is_monster_brief(item):
                            briefs.append(format_brief(item))
                        live_text = str(item.get("live_text") or "")
                        if live_text:
                            animator.update_from_text(live_text)
                last_livetext = now
                status_message = ""
        except KeyboardInterrupt:
            print("\n已退出。")
            return
        except Exception as exc:  # noqa: BLE001
            status_message = f"[拉取失败] {exc}"

        clear_screen()
        print(
            render_dashboard(
                saishi_id=saishi_id,
                match_url=match_url,
                match_info=match_info,
                lineup=lineup,
                animator=animator,
                briefs=briefs,
                terminal_width=shutil.get_terminal_size((120, 30)).columns,
                status_message=status_message,
            )
        )

        if once:
            return

        sleep_for = min(
            max(livetext_interval - (time.time() - last_livetext), 0.5),
            max(animate_interval - (time.time() - last_animate), 0.5),
            2,
        )
        time.sleep(sleep_for)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="直播吧世界杯终端看板")
    parser.add_argument("--match", help="比赛 saishi_id 或 match1869192v 链接片段")
    parser.add_argument("--date", help="比赛日期 YYYY-MM-DD，默认自动解析")
    parser.add_argument("--list", action="store_true", help="列出世界杯比赛并选择")
    parser.add_argument("--once", action="store_true", help="只刷新一次后退出")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = Zhibo8Client()
    config = load_zhibo8_config()

    saishi_id = args.match or config.get("saishi_id") or ""
    if args.list or not saishi_id:
        saishi_id = pick_world_cup_match(client)

    run_dashboard(saishi_id=saishi_id, match_date=args.date, once=args.once)


if __name__ == "__main__":
    main()
