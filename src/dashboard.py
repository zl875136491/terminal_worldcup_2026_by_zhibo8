from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
import unicodedata

from src.animator import PitchAnimator
from src.api import STAT_LABELS, format_match_event_line


LATERAL_BY_POSITION_Y = {
    "L": 0,
    "CL": 1,
    "C": 2,
    "CR": 3,
    "R": 4,
}

# 主队纵深列：0=后卫线 … 3=近中线；不含门将。
HOME_DEPTH_COL = {
    "D1": 0,
    "D2": 0,
    "D3": 0,
    "DM": 1,
    "M": 2,
    "AM": 2,
    "A": 3,
    "F": 3,
}

# 客队纵深列：0=近中线 … 3=后卫线；不含门将。
AWAY_DEPTH_COL = {
    "A": 0,
    "F": 0,
    "AM": 1,
    "M": 2,
    "DM": 2,
    "D1": 3,
    "D2": 3,
    "D3": 3,
}

FORMATION_ROWS = 5
FORMATION_COLS = 4
FORMATION_CELL_WIDTH = 5
FORMATION_DIVIDER = " ¦ "

LineupView = Literal["formation", "roster"]


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


def _is_box_line(line: str) -> bool:
    return bool(line) and set(line) <= set("+-| ") and any(ch in "+-|" for ch in line)


def _wrap_panel(body_lines: list[str], inner_width: int) -> list[str]:
    wrapped: list[str] = []
    for line in body_lines:
        if _is_box_line(line):
            if _display_width(line) <= inner_width:
                wrapped.append(line)
            else:
                wrapped.append(_truncate_display(line, inner_width))
        else:
            wrapped.extend(_wrap_lines(line, inner_width))
    return wrapped or ["暂无数据"]


def _render_box(
    title: str,
    body_lines: list[str],
    width: int,
    *,
    max_body_lines: int | None = None,
    clip_tail: bool = True,
    truncate_content: bool = True,
) -> list[str]:
    inner_width = max(width - 4, 8)
    wrapped = _wrap_panel(body_lines, inner_width)
    if max_body_lines is not None and len(wrapped) > max_body_lines:
        wrapped = wrapped[-max_body_lines:] if clip_tail else wrapped[:max_body_lines]

    top = "+" + "-" * (width - 2) + "+"
    title_line = "| " + _pad_display(_truncate_display(title, width - 4), width - 4) + " |"
    separator = "+" + "-" * (width - 2) + "+"
    content: list[str] = []
    for line in wrapped:
        body = _truncate_display(line, inner_width) if truncate_content else line
        content.append(f"| {_pad_display(body, inner_width)} |")
    bottom = "+" + "-" * (width - 2) + "+"
    return [top, title_line, separator, *content, bottom]


def _merge_columns(columns: list[list[str]], col_widths: list[int], gap: int = 1) -> list[str]:
    height = max(len(col) for col in columns) if columns else 0
    gap_str = " " * gap
    merged: list[str] = []
    for row in range(height):
        parts: list[str] = []
        for col, box_width in zip(columns, col_widths):
            if row < len(col):
                line = col[row]
                if _display_width(line) < box_width:
                    line = _pad_display(line, box_width)
                elif _display_width(line) > box_width:
                    line = _truncate_display(line, box_width)
                parts.append(line)
            else:
                parts.append(" " * box_width)
        merged.append(gap_str.join(parts))
    return merged


def _format_grid_player(player: dict[str, Any]) -> str:
    number = str(player.get("shirt_number") or "-").rjust(2)
    name = str(player.get("player_name_cn") or "")
    if name:
        return number + name[0]
    return number


def _formation_cell(text: str) -> str:
    return _pad_display(_truncate_display(text, FORMATION_CELL_WIDTH), FORMATION_CELL_WIDTH)


def _player_grid_pos(
    player: dict[str, Any],
    *,
    is_home: bool,
) -> tuple[int, int] | None:
    pos_x = str(player.get("positionX") or player.get("positionX2") or "M")
    if pos_x == "GK":
        return None

    pos_y = str(player.get("positionY") or "C")
    row = LATERAL_BY_POSITION_Y.get(pos_y, 2)
    if not is_home:
        row = FORMATION_ROWS - 1 - row

    col = (HOME_DEPTH_COL if is_home else AWAY_DEPTH_COL).get(pos_x, 2)
    return row, col


def _place_player_on_formation_grid(
    grid: list[list[str]],
    occupied: set[tuple[int, int]],
    *,
    player: dict[str, Any],
    col_offset: int,
) -> None:
    pos = _player_grid_pos(player, is_home=col_offset == 0)
    if pos is None:
        return

    row, col = pos
    col += col_offset
    label = _format_grid_player(player)

    for d_row, d_col in ((0, 0), (1, 0), (-1, 0), (2, 0), (-2, 0), (0, 1), (0, -1)):
        try_row = row + d_row
        try_col = col + d_col
        if not (0 <= try_row < FORMATION_ROWS):
            continue
        if not (col_offset <= try_col < col_offset + FORMATION_COLS):
            continue
        if (try_row, try_col) in occupied:
            continue
        occupied.add((try_row, try_col))
        grid[try_row][try_col] = label
        return


def _formation_grid_view(
    home_starters: list[dict[str, Any]],
    away_starters: list[dict[str, Any]],
    *,
    total_width: int,
) -> list[str]:
    """5 行 × 4 列对阵网格：行=球场宽度，列=纵深，不含门将。"""
    grid: list[list[str]] = [[""] * (FORMATION_COLS * 2 + 1) for _ in range(FORMATION_ROWS)]
    occupied: set[tuple[int, int]] = set()

    for row in range(FORMATION_ROWS):
        occupied.add((row, FORMATION_COLS))
        grid[row][FORMATION_COLS] = "|"

    for player in home_starters:
        _place_player_on_formation_grid(grid, occupied, player=player, col_offset=0)
    for player in away_starters:
        _place_player_on_formation_grid(grid, occupied, player=player, col_offset=FORMATION_COLS + 1)

    lines: list[str] = []
    for row in grid:
        parts: list[str] = []
        for col, cell in enumerate(row):
            if col == FORMATION_COLS:
                parts.append(FORMATION_DIVIDER)
            else:
                parts.append(_formation_cell(cell))
        line = "".join(parts)
        if _display_width(line) > total_width:
            line = _truncate_display(line, total_width)
        lines.append(line)

    if not any(cell for row in grid for col, cell in enumerate(row) if col != FORMATION_COLS and cell):
        return ["(暂无阵型)"]
    return lines


def _player_badges(player: dict[str, Any]) -> str:
    badges: list[str] = []
    goals = int(player.get("goal") or 0)
    if goals:
        badges.append(f"球×{goals}")
    assists = int(player.get("assist") or 0)
    if assists:
        badges.append(f"助×{assists}")

    card = player.get("card")
    if isinstance(card, dict):
        if int(card.get("red") or 0):
            badges.append("红牌")
        elif int(card.get("yellow") or 0):
            badges.append("黄牌")

    up_time = str(player.get("up_time") or "").strip()
    down_time = str(player.get("down_time") or "").strip()
    if up_time:
        badges.append(f"↑{up_time}'")
    if down_time:
        badges.append(f"↓{down_time}'")
    return " ".join(badges)


def _format_compact_player(player: dict[str, Any]) -> str:
    number = str(player.get("shirt_number") or "-").rjust(2)
    name = str(player.get("player_name_cn") or "")
    marks: list[str] = []
    goals = int(player.get("goal") or 0)
    if goals:
        marks.append(f"球×{goals}")
    assists = int(player.get("assist") or 0)
    if assists:
        marks.append(f"助×{assists}")
    card = player.get("card")
    if isinstance(card, dict):
        if int(card.get("red") or 0):
            marks.append("红")
        elif int(card.get("yellow") or 0):
            marks.append("黄")
    down_time = str(player.get("down_time") or "").strip()
    if down_time:
        marks.append(f"↓{down_time}'")
    up_time = str(player.get("up_time") or "").strip()
    if up_time:
        marks.append(f"↑{up_time}'")

    text = f"{number}{name}"
    if marks:
        text += " " + " ".join(marks)
    return text


def _render_roster_view(
    home_starters: list[dict[str, Any]],
    away_starters: list[dict[str, Any]],
    *,
    content_width: int,
) -> list[str]:
    """每人一行，主队 | 客队，完整显示不省略。"""
    divider = "|"
    divider_gap = " "
    divider_text = divider_gap + divider + divider_gap
    divider_width = _display_width(divider_text)
    side_width = max((content_width - divider_width) // 2, 10)
    row_count = max(len(home_starters), len(away_starters))
    if row_count == 0:
        return ["暂无首发"]

    lines: list[str] = []
    for index in range(row_count):
        home_text = _format_compact_player(home_starters[index]) if index < len(home_starters) else ""
        away_text = _format_compact_player(away_starters[index]) if index < len(away_starters) else ""
        line = (
            _pad_display(home_text, side_width)
            + divider_text
            + _pad_display(away_text, side_width)
        )
        lines.append(line)
    return lines


def render_lineup_panel(
    lineup: dict[str, Any] | None,
    *,
    home_team_id: str = "",
    away_team_id: str = "",
    home_team_name: str = "主队",
    away_team_name: str = "客队",
    total_width: int = 80,
    view: LineupView = "formation",
    max_lines: int | None = None,
) -> list[str]:
    if not lineup:
        return ["阵容加载中..."]

    data = lineup.get("data") or {}
    team_ids = list(data.keys())
    home_id = home_team_id or (team_ids[0] if team_ids else "")
    away_id = away_team_id or (team_ids[1] if len(team_ids) > 1 else "")

    info = lineup.get("info") or {}
    if isinstance(info, dict):
        home_team_name = str((info.get(home_id) or {}).get("name") or home_team_name)
        away_team_name = str((info.get(away_id) or {}).get("name") or away_team_name)

    coach = lineup.get("coach") or {}
    home_formation = str(lineup.get(home_id) or "")
    away_formation = str(lineup.get(away_id) or "")

    home_starters = [p for p in data.get(home_id) or [] if p.get("status") == "z"]
    away_starters = [p for p in data.get(away_id) or [] if p.get("status") == "z"]

    content_width = max(total_width - 4, 8)

    header_lines = [
        _truncate_display(
            f"{home_team_name} {home_formation}  ¦  {away_team_name} {away_formation}",
            content_width,
        ),
        _truncate_display(
            f"教练 {coach.get(home_id, '-')}  ¦  教练 {coach.get(away_id, '-')}",
            content_width,
        ),
    ]

    if view == "formation":
        if home_starters or away_starters:
            formation_lines = _formation_grid_view(
                home_starters,
                away_starters,
                total_width=content_width,
            )
        else:
            formation_lines = ["(暂无阵型)"]
        return [*header_lines, "", *formation_lines]

    lines = _render_roster_view(
        home_starters,
        away_starters,
        content_width=content_width,
    )

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def render_pitch_panel(animator: PitchAnimator, match_info: dict[str, Any] | None) -> list[str]:
    state = animator.state
    if match_info:
        state.home_team = str(match_info.get("home_team") or state.home_team)
        state.away_team = str(match_info.get("visit_team") or state.away_team)
        state.home_score = str(match_info.get("home_score") or state.home_score)
        state.away_score = str(match_info.get("visit_score") or state.away_score)
        state.period = str(match_info.get("period_cn") or state.period)

    lines = [
        _truncate_display(
            f"{state.home_team} {state.home_score}-{state.away_score} {state.away_team}  "
            f"{state.period or '-'}",
            28,
        ),
    ]
    if state.phase_hint and state.phase_hint != (state.period or ""):
        lines.append(_truncate_display(state.phase_hint, 28))

    lines.append("")
    lines.extend(animator.render())

    if state.event_text and state.event_text not in {state.phase_hint, "等待开球"}:
        lines.append(_truncate_display(f"▶ {state.event_text}", 28))

    current, total = animator.frame_progress()
    if total > 1:
        lines.append(f"帧 {current}/{total}")

    return lines


def render_report_panel(
    match_info: dict[str, Any] | None,
    lineup: dict[str, Any] | None,
    team_stats: dict[str, dict[str, str]],
    events: list[dict[str, Any]],
    *,
    inner_width: int,
) -> list[str]:
    if not match_info:
        return ["战报加载中..."]

    home_id = str(match_info.get("home_id") or "")
    away_id = str(match_info.get("visit_id") or "")
    home_name = str(match_info.get("home_team") or "主队")
    away_name = str(match_info.get("visit_team") or "客队")
    half_score = str(match_info.get("half_score") or "").strip()

    lines = [
        f"{home_name} {match_info.get('home_score', '-')} - "
        f"{match_info.get('visit_score', '-')} {away_name}",
        f"状态: {match_info.get('period_cn') or '-'}",
    ]
    if half_score:
        lines.append(half_score)

    if lineup:
        venue = str(lineup.get("venue") or "").strip()
        weather = str(lineup.get("weather") or "").strip()
        temp = str(lineup.get("temperature") or "").strip()
        env = " · ".join(part for part in (venue, weather, temp) if part)
        if env:
            lines.extend(_wrap_lines(env, inner_width))

    home_stats = team_stats.get(home_id) or {}
    away_stats = team_stats.get(away_id) or {}
    stat_keys = [
        "possession_percentage",
        "total_scoring_att",
        "ontarget_scoring_att",
        "won_corners",
        "fk_foul_lost",
        "pass_percentage",
    ]
    has_stats = any(home_stats.get(k) or away_stats.get(k) for k in stat_keys)
    if has_stats:
        lines.append("")
        lines.append("技术统计")
        for key in stat_keys:
            left = str(home_stats.get(key) or "-")
            right = str(away_stats.get(key) or "-")
            if left == "-" and right == "-":
                continue
            label = STAT_LABELS.get(key, key)
            lines.append(_truncate_display(f"{left:>5} {label} {right:<5}", inner_width))

    timeline: list[str] = []
    for event in events:
        line = format_match_event_line(event)
        if line:
            timeline.append(line)

    if timeline:
        lines.append("")
        lines.append("事件")
        lines.extend(timeline[-8:])

    return lines or ["暂无战报"]


def render_livetext_panel(
    live_feed: list[str],
    inner_width: int,
    status_message: str = "",
    *,
    max_lines: int | None = None,
) -> list[str]:
    if status_message:
        lines = _wrap_lines(status_message, inner_width)
    elif not live_feed:
        lines = ["等待文字直播...", "解说员播报将显示在此"]
    else:
        lines = []
        for entry in live_feed[-25:]:
            lines.extend(_wrap_lines(entry, inner_width))

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def render_brief_panel(
    briefs: list[str],
    inner_width: int,
    status_message: str = "",
    *,
    max_lines: int | None = None,
) -> list[str]:
    if status_message:
        lines = _wrap_lines(status_message, inner_width)
    elif not briefs:
        lines = ["暂无怪兽简报", "等待文字直播..."]
    else:
        lines = []
        for brief in briefs[-20:]:
            lines.extend(_wrap_lines(brief, inner_width))

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def render_header(*, saishi_id: str, match_url: str, updated_at: datetime) -> list[str]:
    return [
        "直播吧世界杯终端看板  |  数据源: zhibo8.com",
        f"比赛ID: {saishi_id}  |  {match_url}",
        f"更新: {updated_at.strftime('%H:%M:%S')}",
    ]


def _stack_panels_horizontally(
    panels: list[list[str]],
    widths: list[int],
    gap: int = 1,
) -> list[str]:
    height = max(len(panel) for panel in panels) if panels else 0
    gap_str = " " * gap
    merged: list[str] = []
    for row in range(height):
        parts: list[str] = []
        for panel, width in zip(panels, widths):
            if row < len(panel):
                line = panel[row]
                if _display_width(line) < width:
                    line = _pad_display(line, width)
                elif _display_width(line) > width:
                    line = _truncate_display(line, width)
                parts.append(line)
            else:
                parts.append(" " * width)
        merged.append(gap_str.join(parts))
    return merged


def _merge_left_right_columns(
    left_lines: list[str],
    right_lines: list[str],
    left_width: int,
    right_width: int,
    *,
    gap: int = 1,
) -> list[str]:
    height = max(len(left_lines), len(right_lines))
    gap_str = " " * gap
    merged: list[str] = []
    for row in range(height):
        if row < len(left_lines):
            left = left_lines[row]
            if _display_width(left) < left_width:
                left = _pad_display(left, left_width)
            elif _display_width(left) > left_width:
                left = _truncate_display(left, left_width)
        else:
            left = " " * left_width

        if row < len(right_lines):
            right = right_lines[row]
            if _display_width(right) < right_width:
                right = _pad_display(right, right_width)
            elif _display_width(right) > right_width:
                right = _truncate_display(right, right_width)
        else:
            right = " " * right_width

        merged.append(left + gap_str + right)
    return merged


def render_dashboard(
    *,
    saishi_id: str,
    match_url: str,
    match_info: dict[str, Any] | None,
    lineup: dict[str, Any] | None,
    team_stats: dict[str, dict[str, str]],
    events: list[dict[str, Any]],
    animator: PitchAnimator,
    live_feed: list[str],
    briefs: list[str] | None = None,
    terminal_width: int,
    terminal_height: int = 30,
    status_message: str = "",
    lineup_view: LineupView = "formation",
) -> str:
    width = max(terminal_width, 72)
    header = render_header(saishi_id=saishi_id, match_url=match_url, updated_at=datetime.now())
    body_height = max(terminal_height - len(header) - 1, 10)
    compact = body_height < 22 or width < 90
    top_content_lines = 6 if compact else max(8, min(body_height // 3, 10))

    gap = 1
    anim_w = max(width * 24 // 100, 24)
    report_w = max(width * 30 // 100, 26)
    left_w = anim_w + gap + report_w
    right_w = max(width - left_w - gap, 28)

    anim_inner = max(anim_w - 4, 12)
    anim_h = 4 if compact else max(5, min(top_content_lines - 2, 7))
    anim_w_inner = max(11, min(anim_inner - 2, 17 if compact else 19))
    animator.height = anim_h
    animator.width = anim_w_inner

    pitch_body = render_pitch_panel(animator, match_info)
    report_body = render_report_panel(
        match_info,
        lineup,
        team_stats,
        events,
        inner_width=max(report_w - 4, 16),
    )

    left_top_row = _stack_panels_horizontally(
        [
            _render_box("模拟动画", pitch_body, anim_w, max_body_lines=top_content_lines, clip_tail=False),
            _render_box("战报数据", report_body, report_w, max_body_lines=top_content_lines, clip_tail=False),
        ],
        [anim_w, report_w],
        gap=gap,
    )

    lineup_budget = max(body_height - len(left_top_row) - 1, 8)
    if lineup_view == "roster":
        lineup_body_budget = max(lineup_budget - 4, 11)
    else:
        lineup_body_budget = max(lineup_budget - 5, 4)
    lineup_body = render_lineup_panel(
        lineup,
        home_team_id=str((match_info or {}).get("home_id") or ""),
        away_team_id=str((match_info or {}).get("visit_id") or ""),
        home_team_name=str((match_info or {}).get("home_team") or "主队"),
        away_team_name=str((match_info or {}).get("visit_team") or "客队"),
        total_width=max(left_w, 40),
        view=lineup_view,
        max_lines=lineup_body_budget,
    )
    lineup_title = (
        "球员名单(按 T 显示阵容)"
        if lineup_view == "roster"
        else "阵容(按 T 显示球员名单)"
    )
    lineup_box = _render_box(
        lineup_title,
        lineup_body,
        left_w,
        max_body_lines=lineup_body_budget,
        clip_tail=False,
        truncate_content=lineup_view != "roster",
    )

    left_column = left_top_row + [""] + lineup_box

    livetext_budget = max(body_height - 5, 4)
    livetext_body = render_livetext_panel(
        live_feed,
        max(right_w - 4, 16),
        status_message,
        max_lines=livetext_budget,
    )
    livetext_box = _render_box(
        "文字直播",
        livetext_body,
        right_w,
        max_body_lines=livetext_budget,
        clip_tail=True,
    )

    body = _merge_left_right_columns(left_column, livetext_box, left_w, right_w, gap=gap)

    lines = header + [""] + body
    if len(lines) > terminal_height:
        lines = lines[:terminal_height]
    if len(lines) < terminal_height:
        lines.extend([""] * (terminal_height - len(lines)))
    return "\n".join(lines[:terminal_height])
