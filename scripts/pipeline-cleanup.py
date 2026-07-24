#!/usr/bin/env python3
"""僵尸任务清理 —— 默认 dry-run，只输出建议，不改数据。

设计原则：这是主人的数据。本脚本
  * 默认只打印计划，什么都不做；
  * 即使加了 --execute 也**不会 DELETE 任何一行**，只把任务状态改成 skipped
    并写入 skip_reason，随时可以按 skip_reason 反查/回滚；
  * --execute 还需要同时给 --yes，避免手滑。

用法:
  scripts/pipeline-cleanup.py                      # 打印清理计划
  scripts/pipeline-cleanup.py --stale-days 7       # 调整"僵尸"判定阈值
  scripts/pipeline-cleanup.py --execute --yes      # 真的执行（仅改状态）
  scripts/pipeline-cleanup.py --execute --yes --only test-residue
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from article_pipeline.db import (  # noqa: E402
    TaskDB, ACTIVE_STATES, TERMINAL_STATES, normalize_keyword,
)

# 明显是测试残渣的关键词（7-01 那批）
TEST_KEYWORDS = {"测试选题", "高价值选题", "强制添加选题", "测试文章"}
TEST_PLATFORMS = {"test"}

CATEGORIES = ("test-residue", "duplicate", "stale-active", "empty-skipped")


def classify(db: TaskDB, stale_days: int) -> dict[str, list[dict]]:
    tasks = db.list_tasks()
    plan: dict[str, list[dict]] = {k: [] for k in CATEGORIES}
    cutoff = datetime.now(timezone.utc).timestamp() - stale_days * 86400

    # 1) 测试残渣
    for t in tasks:
        if t["status"] in ("done", "published"):
            continue  # 发布过的一律不动
        if t["keyword"].strip() in TEST_KEYWORDS or t["platform"] in TEST_PLATFORMS:
            why = f"platform={t['platform']} / 测试关键词"
            if t.get("article"):
                # 有正文的任务丢掉就是丢掉已经花钱写出来的文章，人要先看一眼
                why += f"  [注意: 已有正文 {len(t['article'])} 字，先人工过目]"
            plan["test-residue"].append({
                "id": t["id"], "status": t["status"], "keyword": t["keyword"],
                "why": why,
            })

    # 2) 同关键词重复（保留 id 最小的那条，其余建议 skip）
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        if t["status"] in ("skipped", "rejected"):
            continue
        groups[normalize_keyword(t["keyword"])].append(t)
    for norm, members in groups.items():
        if len(members) < 2 or not norm:
            continue
        # 保留：已发布 > 已写出正文 > id 最小
        def rank(x):
            return (
                0 if x["status"] in ("done", "published") else 1,
                0 if x.get("article") else 1,
                x["id"],
            )
        members = sorted(members, key=rank)
        keeper = members[0]
        for dup in members[1:]:
            plan["duplicate"].append({
                "id": dup["id"], "status": dup["status"],
                "keyword": dup["keyword"],
                "why": f"与 #{keeper['id']} 同选题（保留 #{keeper['id']}）",
            })

    # 3) 长期停在自动化状态里的僵尸
    for t in tasks:
        if t["status"] not in ACTIVE_STATES:
            continue
        meta = json.loads(t.get("meta_json") or "{}")
        ts = TaskDB._parse_ts(meta.get("status_changed_at") or t.get("created_at"))
        if ts is None or ts < cutoff:
            plan["stale-active"].append({
                "id": t["id"], "status": t["status"], "keyword": t["keyword"],
                "why": f"停在 {t['status']} 超过 {stale_days} 天",
            })

    # 4) skipped 但没有任何原因、也没有任何产物 —— 纯噪音，建议补 skip_reason
    for t in tasks:
        if t["status"] != "skipped":
            continue
        meta = json.loads(t.get("meta_json") or "{}")
        if not t.get("skip_reason"):
            plan["empty-skipped"].append({
                "id": t["id"], "status": t["status"], "keyword": t["keyword"],
                "why": "skip_reason 列为空"
                       + (f"（meta_json 里有: {str(meta.get('skip_reason'))[:40]}）"
                          if meta.get("skip_reason") else "（连 meta 里也没有）"),
            })

    # 去重：同一个 id 只出现在第一个匹配的分类里
    seen: set[int] = set()
    for cat in CATEGORIES:
        kept = []
        for item in plan[cat]:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            kept.append(item)
        plan[cat] = kept
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--only", choices=CATEGORIES, action="append",
                    help="只处理指定分类（可重复）")
    ap.add_argument("--execute", action="store_true",
                    help="真的写入（仍然只改状态，不删行）")
    ap.add_argument("--yes", action="store_true", help="配合 --execute 使用")
    ap.add_argument("--db", default=None, help="指定数据库路径（测试用）")
    args = ap.parse_args()

    db = TaskDB(db_path=args.db) if args.db else TaskDB()
    plan = classify(db, args.stale_days)
    wanted = args.only or list(CATEGORIES)

    total = 0
    print(f"数据库: {db.db_path}")
    print(f"僵尸判定阈值: {args.stale_days} 天\n")
    for cat in CATEGORIES:
        items = plan[cat] if cat in wanted else []
        print(f"[{cat}] {len(items)} 条")
        for it in items:
            print(f"  #{it['id']:<5} {it['status']:<13} "
                  f"{it['keyword'][:34]:<36} {it['why']}")
        total += len(items)
        print()

    if not args.execute:
        print(f"合计 {total} 条建议。这是 dry-run，未做任何修改。")
        print("确认后执行: scripts/pipeline-cleanup.py --execute --yes")
        return 0

    if not args.yes:
        print("拒绝执行：--execute 必须配合 --yes。")
        return 2

    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for cat in wanted:
        for it in plan[cat]:
            if cat == "empty-skipped":
                # 已经是 skipped，只补原因，不改状态
                meta = json.loads(db.get_task(it["id"])["meta_json"] or "{}")
                reason = meta.get("skip_reason") or f"cleanup:{cat}"
                db.update_status(it["id"], "skipped", {"skip_reason": reason})
            else:
                db.update_status(it["id"], "skipped", {
                    "skip_reason": f"cleanup:{cat}: {it['why']}",
                    "cleaned_at": now,
                    "cleaned_from": it["status"],
                })
            changed += 1
    print(f"已处理 {changed} 条（仅状态变更，无删除）。")
    print("回滚参考: meta_json.cleaned_from 记录了原状态。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
