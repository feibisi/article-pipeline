"""Tests for content scheduler (T-008)."""

import pytest
from datetime import datetime, timezone, timedelta
from article_pipeline.scheduler import (
    get_week_start,
    check_queue_coverage,
    generate_alert,
    QueueStatus,
    PublishRhythm,
    ScheduleAlert,
)


class TestGetWeekStart:
    def test_monday(self):
        # 周一 00:00
        monday = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)  # 7/6 是周一
        result = get_week_start(monday)
        assert result.weekday() == 0  # 周一
        assert result.hour == 0
        assert result.minute == 0

    def test_wednesday(self):
        # 周三 12:00 → 返回本周一 00:00
        wednesday = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)  # 7/1 是周三
        result = get_week_start(wednesday)
        assert result.weekday() == 0
        assert result.day == 29  # 6/29 是周一

    def test_sunday(self):
        # 周日 23:59 → 返回本周一 00:00
        sunday = datetime(2026, 7, 5, 23, 59, tzinfo=timezone.utc)  # 7/5 是周日
        result = get_week_start(sunday)
        assert result.weekday() == 0
        assert result.day == 29  # 6/29 是周一


class TestCheckQueueCoverage:
    def test_full_coverage(self, mock_db_with_data):
        status = check_queue_coverage("wpcommunity", 2, mock_db_with_data)
        assert status.platform == "wpcommunity"
        assert status.queued_count == 2
        assert status.total_available == 2
        assert status.shortage == 0

    def test_shortage(self, mock_db_with_data):
        status = check_queue_coverage("wpcommunity", 5, mock_db_with_data)
        assert status.needed == 5
        assert status.shortage == 3

    def test_empty_queue(self, mock_db_with_data):
        status = check_queue_coverage("meta", 2, mock_db_with_data)
        assert status.queued_count == 1  # 只有 1 篇
        assert status.shortage == 1


class TestGenerateAlert:
    def test_no_shortage(self):
        status = QueueStatus(
            platform="test",
            queued_count=5,
            researching_count=0,
            total_available=5,
            needed=5,
            shortage=0,
        )
        alert = generate_alert(status, datetime.now(timezone.utc))
        assert alert is None

    def test_shortage_alert(self):
        status = QueueStatus(
            platform="test",
            queued_count=1,
            researching_count=0,
            total_available=1,
            needed=3,
            shortage=2,
        )
        week_start = datetime(2026, 7, 6, tzinfo=timezone.utc)
        alert = generate_alert(status, week_start)

        assert alert is not None
        assert alert.platform == "test"
        assert alert.shortage == 2
        assert alert.week_start == "2026-07-06T00:00:00+00:00"
        assert alert.alert_type == "shortage"
        assert "缺 2 篇" in alert.message

    def test_warning_alert(self):
        status = QueueStatus(
            platform="test",
            queued_count=2,
            researching_count=0,
            total_available=2,
            needed=3,
            shortage=1,
        )
        alert = generate_alert(status, datetime.now(timezone.utc))
        assert alert.alert_type == "warning"



# REMOVED: TestPublishRhythm.test_creation and TestScheduleAlert.test_creation —
# dataclass constructor-echo tests. They instantiated a dataclass and asserted
# back the literals just passed in; the "code under test" was the literal in the
# test body. Zero defect-detection power.


# Fixtures
@pytest.fixture
def mock_db_with_data(tmp_path):
    """A real TaskDB, populated through the real public API.

    The previous version of this fixture hand-built its own 3-column
    ``tasks (id, status, platform)`` table. That meant every test in
    TestCheckQueueCoverage validated the scheduler against a schema that does
    not exist in production: a column rename or a change to the status
    vocabulary in db.py would break the real pipeline while these tests stayed
    green. Use the real schema so schema drift actually fails a test.
    """
    from article_pipeline.db import TaskDB

    db = TaskDB(str(tmp_path / "test.db"))
    db.add_task("选题一", platform="wpcommunity")
    db.add_task("选题二", platform="wpcommunity")
    db.add_task("选题三", platform="meta")
    yield db
    db.conn.close()
