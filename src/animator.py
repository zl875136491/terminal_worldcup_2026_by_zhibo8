from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

MatchPhase = Literal["pre", "live", "finished"]


@dataclass
class AnimateState:
    home_team: str = ""
    away_team: str = ""
    home_score: str = "-"
    away_score: str = "-"
    period: str = ""
    ball_x: float = 0.5
    ball_y: float = 0.5
    event_text: str = ""
    possession_team: str = ""
    phase: MatchPhase = "pre"
    phase_hint: str = ""


@dataclass
class PitchAnimator:
    width: int = 19
    height: int = 9
    state: AnimateState = field(default_factory=AnimateState)
    _frames: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _frame_index: int = 0
    _tick_phase: float = 0.0
    _last_animate_code: int = 0

    def set_phase(self, phase: MatchPhase, *, hint: str = "") -> None:
        self.state.phase = phase
        if hint:
            self.state.phase_hint = hint
        elif phase == "pre":
            self.state.phase_hint = "未开赛 · 等待开球"
        elif phase == "finished":
            self.state.phase_hint = "比赛已结束"
        else:
            self.state.phase_hint = ""

        if phase == "pre":
            self.state.ball_x = 0.5
            self.state.ball_y = 0.5
            if not self.state.event_text:
                self.state.event_text = "等待开球"

    def load_animate(self, payload: dict[str, Any], *, animate_code: int = 0) -> None:
        frames = payload.get("data") or []
        if not frames:
            return

        if animate_code and animate_code != self._last_animate_code:
            self._last_animate_code = animate_code

        self._frames = frames
        playback_start = max(0, len(frames) - 5)
        self._frame_index = playback_start
        self._apply_frame(self._frames[self._frame_index])

    def frame_progress(self) -> tuple[int, int]:
        return self._frame_index + 1, len(self._frames)

    def has_pending_frames(self) -> bool:
        return self._frame_index < len(self._frames) - 1

    def advance_frame(self) -> bool:
        if not self.has_pending_frames():
            return False
        self._frame_index += 1
        self._apply_frame(self._frames[self._frame_index])
        return True

    def tick_animate(self) -> None:
        if self.has_pending_frames():
            self.advance_frame()

    def _apply_team_side(self, team: str) -> None:
        if not team:
            return
        self.state.possession_team = team
        if team == self.state.home_team:
            self.state.ball_x = min(0.88, self.state.ball_x + 0.12)
        elif team == self.state.away_team:
            self.state.ball_x = max(0.12, self.state.ball_x - 0.12)

    def _apply_frame(self, frame: dict[str, Any]) -> None:
        left = frame.get("left") or {}
        right = frame.get("right") or {}
        self.state.home_team = str(left.get("team") or self.state.home_team)
        self.state.away_team = str(right.get("team") or self.state.away_team)
        self.state.home_score = str(left.get("score", self.state.home_score))
        self.state.away_score = str(right.get("score", self.state.away_score))
        self.state.period = str(frame.get("period") or frame.get("top_period") or self.state.period)

        ep_msg = str(frame.get("ep_msg") or "").strip()
        if ep_msg:
            self.state.phase_hint = ep_msg

        team = str(frame.get("team") or "").strip()
        if team:
            self._apply_team_side(team)

        events = frame.get("event") or []
        applied_coords = False
        for event in reversed(events):
            try:
                coord_x = event.get("coord_x")
                coord_y = event.get("coord_y")
                if coord_x is not None and coord_y is not None:
                    self.state.ball_x = float(coord_x) / 100 if float(coord_x) > 1 else float(coord_x)
                    self.state.ball_y = float(coord_y) / 100 if float(coord_y) > 1 else float(coord_y)
                    applied_coords = True
                    break
            except (TypeError, ValueError):
                continue

        if events:
            event = events[-1]
            event_text = str(event.get("ext") or event.get("type") or "").strip()
            if event_text:
                self.state.event_text = event_text
            if not applied_coords and team:
                self._apply_team_side(team)

    def tick_live(self) -> None:
        if self.state.phase != "live":
            return

        self._tick_phase += 0.35
        wobble = math.sin(self._tick_phase) * 0.03

        if self.state.possession_team == self.state.home_team:
            self.state.ball_x = min(0.9, self.state.ball_x + 0.025 + wobble * 0.5)
        elif self.state.possession_team == self.state.away_team:
            self.state.ball_x = max(0.1, self.state.ball_x - 0.025 + wobble * 0.5)
        else:
            self.state.ball_x = min(0.9, max(0.1, 0.5 + wobble * 2))
            self.state.ball_y = min(0.75, max(0.25, 0.5 + math.cos(self._tick_phase * 0.7) * 0.08))

    def update_from_text(self, text: str, team_hint: str = "") -> None:
        if self.state.phase != "live":
            return

        if team_hint:
            self.state.possession_team = team_hint
        elif self.state.home_team and self.state.home_team in text:
            self.state.possession_team = self.state.home_team
        elif self.state.away_team and self.state.away_team in text:
            self.state.possession_team = self.state.away_team
        elif "主队" in text:
            self.state.possession_team = self.state.home_team
        elif "客队" in text:
            self.state.possession_team = self.state.away_team

        home_controls = self.state.possession_team == self.state.home_team
        if "射门" in text or "远射" in text or "头球" in text:
            delta = 0.1 if home_controls else -0.1
            self.state.ball_x = min(0.95, max(0.05, self.state.ball_x + delta))
        elif "传球" in text or "向前" in text or "推进" in text or "禁区" in text:
            delta = 0.05 if home_controls else -0.05
            self.state.ball_x = min(0.95, max(0.05, self.state.ball_x + delta))
        elif "角球" in text:
            self.state.ball_x = 0.92 if home_controls else 0.08
            self.state.ball_y = 0.18
        elif "界外球" in text:
            self.state.ball_y = min(0.9, self.state.ball_y + 0.06)
        elif "进球" in text or "破门" in text or "超出比分" in text:
            self.state.ball_x = 0.96 if home_controls else 0.04
            self.state.ball_y = 0.5
        elif "VAR" in text.upper() or "复审" in text:
            self.state.ball_x = 0.5
            self.state.ball_y = 0.5
            self.state.phase_hint = "VAR 复审中"
        elif "换人" in text:
            pass

        if text.strip():
            self.state.event_text = text[:48]

    def render(self) -> list[str]:
        w, h = self.width, self.height
        grid: list[list[str]] = [[" "] * w for _ in range(h)]

        mid_row = h // 2
        mid_col = w // 2
        for row in range(h):
            if 0 < row < h - 1:
                grid[row][mid_col] = "┊"
        for col in range(w):
            if 0 < col < w - 1:
                grid[mid_row][col] = "─"
        grid[mid_row][mid_col] = "┼"

        goal_top = max(1, h // 4)
        goal_bottom = min(h - 2, h - h // 4 - 1)
        for row in range(goal_top, goal_bottom + 1):
            grid[row][0] = "╫"
            grid[row][w - 1] = "╫"

        col = min(w - 1, max(0, round(self.state.ball_x * (w - 1))))
        row = min(h - 1, max(0, round(self.state.ball_y * (h - 1))))
        ball = "◎" if self.state.phase_hint and "VAR" in self.state.phase_hint else "●"
        grid[row][col] = ball

        home_label = (self.state.home_team or "主队")[:6]
        away_label = (self.state.away_team or "客队")[:6]
        label_line = f"{home_label:<6}{' ' * max(w - 12, 0)}{away_label:>6}"

        top = "┌" + "─" * w + "┐"
        bottom = "└" + "─" * w + "┘"
        body = [label_line, top]
        for line in grid:
            body.append("│" + "".join(line) + "│")
        body.append(bottom)
        return body
