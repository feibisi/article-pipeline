# 仓库对象损坏与修复记录

> 日期：2026-07-25 | 处理：elementary
> **重要：本修复使用 git replace ref，只存在于本地 `.git/refs/replace/`。别人 clone 或本仓库重建后不会带上，需重新执行下方命令。**

## 症状

`git fsck` 报缺失对象，`git log` 只能遍历 31 个提交，`git push` 被拒（误报 non-fast-forward），
`git merge-base` 与 `rev-list` 在部分范围内直接 fatal。

缺失对象（4 个，**永久丢失**）：

```
commit a18e00f17e722ca98b118397d802c992baaac7bc
commit d32310eb6d42ddff0dc6ec56a444a791c79208f8
tree   645b5a88a8796f7389390a7fb94dbaa1c69092ef
blob   86f9493286a2b4ef747ab38f043b5c5928f32a8a
```

均为 2026-07-01 `docs/system-guide` 分支相关的本地提交，**从未推送**。

## 恢复尝试（无损修复不可行）

| 来源 | 结果 |
|---|---|
| Forgejo 服务端 origin | 只有 `main@0ae7806`（2026-06-18），早于缺失对象，不含 |
| `~/workspaces/article-pipeline` | 独立仓库、不同历史，无 |
| NAS `backups/elementary` | 无此仓库备份 |
| reflog / gc.log | 无 gc 痕迹，非回收所致 |

结论：这些对象只存在过于本地，已无副本可取。**文件内容零丢失**（当前工作区完整，385 tests passed），丢的只是历史对象。

## 一个重要的误判纠正

初查时 `git log` 显示本地 main 与 origin/main **0 个共同提交**，看似两条无关历史。
**这是假象**——坏链切断了遍历，使 git 看不见共同祖先。实际两者本是同一条线（修复后
`git merge-base --is-ancestor origin/main main` 退出码 0 证实）。

## 修复方式：3 个 graft，全部只用真实存在的父提交

```bash
# 两个合并提交各自缺失"被合并的那一侧"，只保留真实存在的父提交
git replace --graft 8c6896d c2e66036
git replace --graft 4853f04 8c6896d
# 此提交的唯一父提交已永久丢失，标为根提交，不虚构父子关系
git replace --graft 012b717
```

**设计原则：不虚构历史。** 曾尝试把 `012b717` 嫁接到 `c2e66036` 以求"好看的连续历史"，
但那是一条不存在的父子关系，已撤销。改为根提交，如实表达"父提交已丢失"。
main 与旧历史的连接由 `4853f04 → 8c6896d → c2e66036` 这条**真实**路径承担。

## 修复效果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| `git log` 可遍历提交 | 31（遍历中断） | **54** |
| `origin/main` 是 main 祖先 | 否（误判） | **是** |
| `git push --dry-run` | rejected (non-fast-forward) | **`0ae7806..6cb6352` 快进** |
| 测试 | 385 passed | 385 passed（未受影响） |

`git fsck` **仍会报那 3 条坏链** —— 这是预期行为：fsck 检查真实对象、不采纳 replace ref。
不代表修复失效。

## 运维注意

1. **不要跑 `git gc` / `git prune`** —— 可能清掉尚可用的状态，且无法恢复缺失对象。
2. **replace ref 不随 clone 传播**。若在别处 clone 本仓库，需重新执行上面 3 条命令。
   可考虑推送 replace refs：`git push origin 'refs/replace/*'`（需人工决定）。
3. **永久修复**（可选）：`git filter-repo` 把 graft 落实为真实历史，代价是
   `012b717` 及其后所有提交 SHA 变化。仅在确实需要干净历史时才做。
4. 撤销任一 graft：`git replace -d <commit>`。
