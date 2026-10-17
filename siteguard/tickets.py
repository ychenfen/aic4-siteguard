"""整改通知单生成与闭环状态管理。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from .models import Hazard

STATUS_FLOW = ["待整改", "整改中", "待复查", "已闭环"]


@dataclass
class Ticket:
    ticket_no: str
    hazard: Hazard
    issued_at: datetime
    deadline: datetime
    action: str
    responsible: str = "现场安全员"
    status: str = "待整改"
    history: list[tuple[str, str]] = field(default_factory=list)

    def advance(self, note: str = "", at: datetime | None = None) -> str:
        i = STATUS_FLOW.index(self.status)
        if i == len(STATUS_FLOW) - 1:
            raise ValueError("工单已闭环")
        self.status = STATUS_FLOW[i + 1]
        self.history.append(((at or datetime.now()).isoformat(timespec="seconds"),
                             f"{self.status}{'：' + note if note else ''}"))
        return self.status

    def reject(self, note: str, at: datetime | None = None) -> None:
        """复查不通过，退回整改中。"""
        if self.status != "待复查":
            raise ValueError("只有待复查的工单可以退回")
        self.status = "整改中"
        self.history.append(((at or datetime.now()).isoformat(timespec="seconds"), f"复查未通过：{note}"))

    def to_markdown(self, project: str = "XX项目") -> str:
        h = self.hazard
        return "\n".join([
            f"# 安全隐患整改通知单 {self.ticket_no}",
            "",
            f"| 项目 | {project} | 摄像头 | {h.camera_id} |",
            "|---|---|---|---|",
            f"| 隐患 | {h.title} | 等级 | **{h.level}**（风险分 {h.score:.1f}） |",
            f"| 发现时间 | {self.issued_at:%Y-%m-%d %H:%M:%S} | 整改期限 | {self.deadline:%Y-%m-%d %H:%M}（{self.action}） |",
            f"| 责任人 | {self.responsible} | 状态 | {self.status} |",
            "",
            f"**依据：** {h.standard}",
            "",
            f"**整改措施：** {h.measure}",
            "",
            "**整改回执：** ______________________　　**复查人：** __________",
        ])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issued_at"] = self.issued_at.isoformat(timespec="seconds")
        d["deadline"] = self.deadline.isoformat(timespec="seconds")
        return d


class TicketBook:
    def __init__(self, levels: list[dict], base_time: datetime | None = None):
        self.levels = {lv["name"]: lv for lv in levels}
        self.base_time = base_time or datetime.now().replace(microsecond=0)
        self.tickets: list[Ticket] = []

    def issue(self, hazard: Hazard) -> Ticket:
        lv = self.levels[hazard.level]
        issued = self.base_time + timedelta(seconds=hazard.ts)
        t = Ticket(
            ticket_no=f"ZG{issued:%Y%m%d}-{len(self.tickets) + 1:03d}",
            hazard=hazard,
            issued_at=issued,
            deadline=issued + timedelta(hours=lv["deadline_hours"]),
            action=lv["action"],
        )
        t.history.append((issued.isoformat(timespec="seconds"), "系统自动生成"))
        self.tickets.append(t)
        return t

    def summary(self) -> dict:
        by_level: dict[str, int] = {}
        by_rule: dict[str, int] = {}
        for t in self.tickets:
            by_level[t.hazard.level] = by_level.get(t.hazard.level, 0) + 1
            by_rule[t.hazard.title] = by_rule.get(t.hazard.title, 0) + 1
        closed = sum(t.status == "已闭环" for t in self.tickets)
        return {
            "total": len(self.tickets),
            "by_level": by_level,
            "by_rule": by_rule,
            "closed_rate": closed / len(self.tickets) if self.tickets else 0.0,
        }
