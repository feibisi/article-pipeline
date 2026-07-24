"""Content calendar scheduler — pipeline task scheduling.

T-008: 内容日历 → pipeline 调度对接
读取发布节奏配置 → 检查队列选题覆盖 → NATS 通知缺口
"""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal


@dataclass
class PublishRhythm:
    """发布节奏配置"""
    platform: str  # 如 "wpcommunity", "meta"
    frequency: int  # 每周发布数量
    priority: str = "normal"  # 优先级


@dataclass
class QueueStatus:
    """队列状态"""
    platform: str
    queued_count: int
    researching_count: int
    total_available: int
    needed: int
    shortage: int


@dataclass
class ScheduleAlert:
    """调度提醒"""
    platform: str
    shortage: int
    week_start: str  # ISO 周一日期
    message: str
    alert_type: Literal["shortage", "warning", "ok"] = "shortage"


# 默认发布节奏配置。
# 注意: platform 必须和实际入队时用的 platform 一致，否则覆盖率永远是 0，
# 缺口告警每次都触发（历史上 rhythms 写的是 wpcommunity/meta，而 CLI 默认
# 入队 platform 是 wptea，于是这个调度器只会制造噪音）。
DEFAULT_RHYTHMS: list[PublishRhythm] = [
    PublishRhythm(platform="wptea", frequency=2, priority="high"),
]

# 向后兼容旧名
_DEFAULT_RHYTHMS = DEFAULT_RHYTHMS


def load_rhythms() -> list[PublishRhythm]:
    """从 config.yaml 的 schedule.rhythms 读取节奏，缺失时用默认值。

    格式:
        schedule:
          rhythms:
            - platform: wptea
              frequency: 2
    """
    from article_pipeline.config import load_config
    raw = (load_config().get("schedule") or {}).get("rhythms")
    if not isinstance(raw, list) or not raw:
        return list(DEFAULT_RHYTHMS)
    rhythms = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("platform"):
            continue
        try:
            freq = int(item.get("frequency", 1))
        except (TypeError, ValueError):
            continue
        rhythms.append(PublishRhythm(
            platform=str(item["platform"]), frequency=freq,
            priority=str(item.get("priority", "normal"))))
    return rhythms or list(DEFAULT_RHYTHMS)


def get_week_start(date: datetime | None = None) -> datetime:
    """获取本周一（UTC）.

    Args:
        date: 参考日期，默认当前时间

    Returns:
        本周一 datetime
    """
    if date is None:
        date = datetime.now(timezone.utc)
    # 周一 = weekday() == 0
    days_since_monday = date.weekday()
    monday = date - timedelta(days=days_since_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def check_queue_coverage(
    platform: str,
    frequency: int,
    db,
) -> QueueStatus:
    """检查队列选题覆盖情况.

    Args:
        platform: 平台名称
        frequency: 每周发布数量
        db: PipelineDB 实例

    Returns:
        QueueStatus
    """
    c = db.conn.cursor()
    # 真正"未开工的储备"= queued。
    c.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'queued' AND platform = ?",
        (platform,),
    )
    queued_count = c.fetchone()[0]

    # 在途任务单独统计：它们可能失败，不能算作本周的确定供给。
    c.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'researching' AND platform = ?",
        (platform,),
    )
    researching_count = c.fetchone()[0]

    total_available = queued_count
    shortage = max(0, frequency - total_available)

    return QueueStatus(
        platform=platform,
        queued_count=queued_count,
        researching_count=researching_count,
        total_available=total_available,
        needed=frequency,
        shortage=shortage,
    )


def generate_alert(status: QueueStatus, week_start: datetime) -> ScheduleAlert | None:
    """生成调度提醒.

    Args:
        status: QueueStatus
        week_start: 本周一

    Returns:
        ScheduleAlert 或 None（无缺口时）
    """
    if status.shortage <= 0:
        return None

    alert_type: Literal["shortage", "warning", "ok"] = "shortage"
    if status.shortage == 1:
        alert_type = "warning"

    return ScheduleAlert(
        platform=status.platform,
        shortage=status.shortage,
        week_start=week_start.isoformat(),
        message=f"本周 {status.platform} 缺 {status.shortage} 篇选题（队列中有 {status.total_available} 篇，需要 {status.needed} 篇）",
        alert_type=alert_type,
    )


def send_nats_alert(alert: ScheduleAlert, recipient: str = "modiqi") -> bool:
    """通过 NATS 发送调度提醒.

    Args:
        alert: ScheduleAlert
        recipient: 接收者

    Returns:
        是否成功发送
    """
    try:
        payload = json.dumps({
            "type": "schedule-alert",
            "platform": alert.platform,
            "shortage": alert.shortage,
            "week_start": alert.week_start,
            "alert_type": alert.alert_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)

        result = subprocess.run(
            ["vm-dm", recipient, payload],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [scheduler] Failed to send NATS alert: {e}")
        return False


def run_schedule_check(
    db,
    rhythms: list[PublishRhythm] | None = None,
    auto_notify: bool = True,
) -> list[ScheduleAlert]:
    """运行调度检查：检查所有平台的队列覆盖 → 发送提醒.

    Args:
        db: PipelineDB 实例
        rhythms: 发布节奏配置，默认使用 _DEFAULT_RHYTHMS
        auto_notify: 是否自动发送 NATS 提醒

    Returns:
        ScheduleAlert 列表
    """
    if rhythms is None:
        rhythms = load_rhythms()

    week_start = get_week_start()
    alerts = []

    for rhythm in rhythms:
        status = check_queue_coverage(rhythm.platform, rhythm.frequency, db)
        alert = generate_alert(status, week_start)

        if alert:
            alerts.append(alert)
            print(f"  [scheduler] {alert.message}")

            if auto_notify:
                # 根据 platform 确定接收者（可配置）
                recipient = "modiqi"  # 默认发给 modiqi
                if send_nats_alert(alert, recipient):
                    print(f"  [scheduler] Alert sent to {recipient}")
                else:
                    print(f"  [scheduler] Failed to send alert")

    return alerts


if __name__ == "__main__":
    # Test scheduler
    print("=== Scheduler Test ===")
    print(f"Week start: {get_week_start().isoformat()}")

    # Test with mock data
    class MockDB:
        def __init__(self):
            import sqlite3
            self.conn = sqlite3.connect(":memory:")
            self.conn.execute("""
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY,
                    status TEXT,
                    platform TEXT
                )
            """)
            # 添加测试数据
            self.conn.execute("INSERT INTO tasks (status, platform) VALUES ('queued', 'wpcommunity')")
            self.conn.execute("INSERT INTO tasks (status, platform) VALUES ('queued', 'wpcommunity')")
            self.conn.execute("INSERT INTO tasks (status, platform) VALUES ('queued', 'meta')")
            self.conn.commit()

    mock_db = MockDB()
    alerts = run_schedule_check(mock_db, auto_notify=False)

    print(f"\nGenerated {len(alerts)} alerts:")
    for alert in alerts:
        print(f"  - {alert.platform}: {alert.message}")
