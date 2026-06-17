from __future__ import annotations

from datetime import datetime
from typing import Any
import unicodedata

from src.animator import PitchAnimator


ROW_BY_POSITION_X = {
    "GK": 6,
    "D1": 5,
    "D2": 5,
    "D3": 5,
    "DM": 4,
    "M": 3,
    "AM": 2,
    "A": 1,
    "F": 1,
}

COL_BY_POSITION_Y = {
    "L": 0,
    "CL": 2,
    "C": 4,
    "CR": 6,
    "R": 8,
}

def _display_width(text: str) -> int:
    width = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width

def _pad_display(text: str, target: int) -> str:
    if _display_width(text) >= target:
        return text
    return text + " " * (target - _display_width(text))

def _truncate_display(text: str, target: int) -> str:
    if _display_width(text) <= target:
        return text
    result = ""
    width = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if width + ch_w > target - 1:
            return result + "…"
        result += ch
        width += ch_w
    return result

def _wrap_lines(text: str, width: int) -> list[str]:
    if width <= 0:
        return [text]
    lines: list[str] = []
    current = ""
    for ch in text:
        piece = current + ch
        if _display_width(piece) > width:
            if current:
                lines.append(current)
            current = ch
        else:
            current = piece
    if current:
        lines.append(current)
    return lines or [""]

def _wrap_panel(body_lines: list[str], inner_width: int) -> list[str]:
    wrapped: list[str] = []
    for line in body_lines:
        wrapped.extend(_wrap_lines(line, inner_width))
    return wrapped or ["暂无数据"]

def _render_box(title: str, body_lines: list[str], width: int, min_body_lines: int | None = None) -> list[str]:
    inner_width = max(width - 4, 10)
    wrapped = _wrap_panel(body_lines, inner_width)
    if min_body_lines is not None and len(wrapped) < min_body_lines:
        wrapped.extend([""] * (min_body_lines - len(wrapped)))

    top = "+" + "-" * (width - 2) + "+"
    title_line = "| " + title.center(width - 4) + " |"
    separator = "+" + "-" * (width - 2) + "+"
    content = [f"| {_pad_display(_truncate_display(line, inner_width), inner_width)} |" for line in wrapped]
    bottom = "+" + "-" * (width - 2) + "+"
    return [top, title_line, separator, *content, bottom]

def _merge_columns(columns: list[list[str]], col_widths: list[int], gap: int = 2) -> list[str]:
    height = max(len(col) for col in columns)
    gap_str = " " * gap
    merged: list[str] = []
    for row in range(height):
        parts: list[str] = []
        for col, box_width in zip(columns, col_widths):
            if row < len(col):
                line = col[row]
                if _display_width(line) < box_width:
                    line = _pad_display(line, box_width)
                parts.append(line)
            else:
                parts.append(" " * box_width)
        merged.append(gap_str.join(parts))
    return merged


def _merge_rows(rows: list[list[str]], row_heights: list[int] | None = None) -> list[str]:
    if not rows:
        return []
    width = max(max(_display_width(line) for line in block) for block in rows)
    merged: list[str] = []
    for block in rows:
        padded = []
        for line in block:
            if _display_width(line) < width:
                line = _pad_display(line, width)
            padded.append(line)
        merged.extend(padded)
        if block is not rows[-1]:
            merged.append("")
    return merged


def _formation_grid(
    starters: list[dict[str, Any]],
    *,
    width: int = 9,
    height: int = 7,
) -> tuple[list[str], list[str]]:
    grid: list[list[str]] = [["  "] * width for _ in range(height)]
    occupied: set[tuple[int, int]] = set()
    legend: list[str] = []

    for player in starters:
        number = str(player.get("shirt_number") or "").strip()
        name = str(player.get("player_name_cn") or "").strip()
        if not number:
            continue

        pos_x = str(player.get("positionX") or player.get("positionX2") or "M")
        pos_y = str(player.get("positionY") or "C")
        row = ROW_BY_POSITION_X.get(pos_x, 3)
        col = COL_BY_POSITION_Y.get(pos_y, 4)

        while (row, col) in occupied and col < width - 1:
            col += 1
        while (row, col) in occupied and row < height - 1:
            row += 1
        occupied.add((row, col))
        grid[row][col] = number.rjust(2)
        legend.append(f"{number}: {name}")

    pitch = ["+" + "-" * (width * 2) + "+"]
    for row in grid:
        pitch.append("|" + "".join(cell for cell in row) + "|")
    pitch.append("+" + "-" * (width * 2) + "+")
    return pitch, legend


def render_lineup_panel(
    lineup: dict[str, Any] | None,
    *,
    home_team_id: str | None = None,
    away_team_id: str | None = None,
    inner_width: int = 40,
) -> list[str]:
    if not lineup:
        return ["阵容加载中..."]

    data = lineup.get("data") or {}
    team_ids = list(data.keys())
    home_id = home_team_id or (team_ids[0] if team_ids else "")
    away_id = away_team_id or (team_ids[1] if len(team_ids) > 1 else "")

    lines: list[str] = []
    for label, team_id in (("主队", home_id), ("客队", away_id)):
        if not team_id:
            continue
        starters = [player for player in data.get(team_id) or [] if player.get("status") == "z"]
        if not starters:
            lines.append(f"{label}: 暂无首发")
            lines.append("")
            continue
        pitch, legend = _formation_grid(starters)
        lines.append(f"{label} ({len(starters)}人)")
        lines.extend(pitch)
        lines.append("")
        current = ""
        for item in legend:
            piece = item if not current else f"  {item}"
            if _display_width(current + piece) > inner_width:
                lines.append(current)
                current = item
            else:
                current += piece
        if current:
            lines.append(current)
        lines.append("")

    return lines or ["暂无阵容数据"]


def render_pitch_panel(animator: PitchAnimator, match_info: dict[str, Any] | None) -> list[str]:
    state = animator.state
    if match_info:
        state.home_team = str(match_info.get("home_team") or state.home_team)
        state.away_team = str(match_info.get("visit_team") or state.away_team)
        state.home_score = str(match_info.get("home_score") or state.home_score)
        state.away_score = str(match_info.get("visit_score") or state.away_score)
        state.period = str(match_info.get("period_cn") or state.period)

    header = (
        f"{state.home_team} {state.home_score} - {state.away_score} {state.away_team}  "
        f"{state.period or '-'}"
    )
    lines = [header, ""]
    lines.extend(animator.render())
    if state.event_text:
        lines.append("")
        lines.append(f"事件: {state.event_text}")
    if state.possession_team:
        lines.append(f"控球: {state.possession_team}")
    return lines


def render_brief_panel(briefs: list[str], inner_width: int, status_message: str = "") -> list[str]:
    if status_message:
        return _wrap_lines(status_message, inner_width)
    if not briefs:
        return ["暂无怪兽简报", "", "等待文字直播更新..."]

    lines: list[str] = []
    for brief in briefs[-30:]:
        lines.extend(_wrap_lines(brief, inner_width))
    return lines


def render_header(*, saishi_id: str, match_url: str, updated_at: datetime) -> list[str]:
    return [
        "直播吧世界杯终端看板  |  数据源: zhibo8.com (HTTP 轮询)",
        f"比赛ID: {saishi_id}  |  页面: {match_url}",
        f"更新时间: {updated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]


def render_dashboard(
    *,
    saishi_id: str,
    match_url: str,
    match_info: dict[str, Any] | None,
    lineup: dict[str, Any] | None,
    animator: PitchAnimator,
    briefs: list[str],
    terminal_width: int,
    status_message: str = "",
) -> str:
    brief_width = max(terminal_width // 4, 24)
    main_width = max(terminal_width - brief_width - 2, 40)
    brief_inner = max(brief_width - 4, 16)
    main_inner = max(main_width - 4, 20)

    header = render_header(
        saishi_id=saishi_id,
        match_url=match_url,
        updated_at=datetime.now(),
    )

    pitch_lines = render_pitch_panel(animator, match_info)
    lineup_lines = render_lineup_panel(
        lineup,
        home_team_id=str((match_info or {}).get("home_id") or ""),
        away_team_id=str((match_info or {}).get("visit_id") or ""),
        inner_width=main_inner,
    )
    brief_lines = render_brief_panel(briefs, brief_inner, status_message)

    pitch_body = len(_wrap_panel(pitch_lines, main_inner))
    lineup_body = len(_wrap_panel(lineup_lines, main_inner))
    brief_body = max(len(_wrap_panel(brief_lines, brief_inner)), pitch_body + lineup_body + 1)

    pitch_box = _render_box("动画", pitch_lines, main_width, min_body_lines=pitch_body)
    lineup_box = _render_box("阵容", lineup_lines, main_width, min_body_lines=lineup_body)
    brief_box = _render_box("直播 · 怪兽简报", brief_lines, brief_width, min_body_lines=brief_body)

    left_column = _merge_rows([pitch_box, lineup_box])
    left_width = max(_display_width(line) for line in left_column)
    brief_width = max(_display_width(line) for line in brief_box)
    body = _merge_columns([left_column, brief_box], [left_width, brief_width])
    return "\n".join(header + body)
