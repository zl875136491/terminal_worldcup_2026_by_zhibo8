from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class PitchAnimator:
    width: int = 11
    height: int = 7
    state: AnimateState = field(default_factory=AnimateState)

    def update_from_animate(self, payload: dict[str, Any]) -> None:
        frames = payload.get("data") or []
        if not frames:
            return
        frame = frames[-1]
        left = frame.get("left") or {}
        right = frame.get("right") or {}
        self.state.home_team = str(left.get("team") or self.state.home_team)
        self.state.away_team = str(right.get("team") or self.state.away_team)
        self.state.home_score = str(left.get("score", self.state.home_score))
        self.state.away_score = str(right.get("score", self.state.away_score))
        self.state.period = str(frame.get("period") or frame.get("top_period") or self.state.period)
        self.state.possession_team = str(frame.get("team") or self.state.possession_team)

        events = frame.get("event") or []
        if not events:
            return
        event = events[-1]
        try:
            self.state.ball_x = float(event.get("coord_x", self.state.ball_x))
            self.state.ball_y = float(event.get("coord_y", self.state.ball_y))
        except (TypeError, ValueError):
            pass
        self.state.event_text = str(event.get("ext") or event.get("type") or self.state.event_text)

    def update_from_text(self, text: str, team_hint: str = "") -> None:
        if team_hint:
            self.state.possession_team = team_hint
        elif "阿根廷" in text or "主队" in text:
            self.state.possession_team = self.state.home_team
        elif "阿尔及利亚" in text or "客队" in text:
            self.state.possession_team = self.state.away_team

        if "射门" in text or "远射" in text:
            delta = 0.08 if self.state.possession_team == self.state.home_team else -0.08
            self.state.ball_x = min(0.95, max(0.05, self.state.ball_x + delta))
        elif "传球" in text or "向前" in text:
            delta = 0.04 if self.state.possession_team == self.state.home_team else -0.04
            self.state.ball_x = min(0.95, max(0.05, self.state.ball_x + delta))
        elif "角球" in text:
            self.state.ball_x = 0.92 if self.state.possession_team == self.state.home_team else 0.08
            self.state.ball_y = 0.08
        elif "界外球" in text:
            self.state.ball_y = min(0.92, self.state.ball_y + 0.05)

        self.state.event_text = text[:40]

    def render(self) -> list[str]:
        grid: list[list[str]] = [[" "] * self.width for _ in range(self.height)]
        col = min(self.width - 1, max(0, round(self.state.ball_x * (self.width - 1))))
        row = min(self.height - 1, max(0, round(self.state.ball_y * (self.height - 1))))
        grid[row][col] = "●"

        top = "+" + "-" * self.width + "+"
        body = [top]
        for line in grid:
            body.append("|" + "".join(line) + "|")
        body.append(top)
        return body
