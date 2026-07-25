# article-pipeline 全系统审计与架构改进报告

> 日期：2026-07-25 | 核查方：elementary（5 路并行子代理 + 主控综合）
> 前置报告：`AUDIT-2026-07-22.md`（首轮五维核查 + 6 处止血）
> 分支：`fix/quality-gate-fatal-bugs`（未提交）

## 一句话结论

**这套系统的失败不是"AI 写不好文章"，而是一连串工程缺陷叠加成了一台"结构上必然产出不可信内容"的机器**——提示词在数学上逼模型编造、发布环节自己往正文塞假话、质量门控量不到质量、而管线自 7-01 起因一个不存在的方法调用根本跑不通。主人删稿的判断是唯一正确的读数。

---

## 一、决定性发现（改写了此前的诊断）

### 1. 编造的真实机制（**已于 2026-07-25 修正，原结论有误**）

> **修正说明**：本节初版称"三条规则的交集在数学上只有一个解 → 只能编"。
> 该结论**不成立**，源于子代理报告引用 `writer.py:154` 时**截断了后半句**，主控采信未核原文。
> 核对 `git show 5335e6c:article_pipeline/writer.py` 后确认：原始提示词在**五处**明确禁止编造，
> 且明确给出了出口。保留此修正记录，不删除错误结论。

**原始提示词实际写了什么**（154 行完整原文 + 88-92 行事实层规则）：

- 「唯一信息来源是"参考素材"。**编造数据、URL、书名、人名、公司名是写作事故**」
- 「所有数字、百分比、时间、版本号**必须来自参考素材**」
- 「参考素材没有的，**跳过不写**」
- 「这些例子和数字**必须来自参考素材，不能编造**。素材不够支撑一个完整的 H2 段落，**宁可不写这个段落**」
- 「**没有图比编造图更好**」

**所以不是"被逼编造"，是"五处禁令都没拦住"。** 真实原因三条：

1. **品类规则公开推翻全局纪律**：`writer.py:234`（marketing）
   「用具体数字建立信任（"已有2300+开发者使用"），**没有数据用用户证言**」
   —— 位置更具体、更靠后，模型视其为特例豁免。这是 task 61 编造客户证言的直接来源。
   同类：`writer.py:207-208`（case-study）的示例数字「3s→0.8s，流量增长40%」会被**逐字照抄**。
2. **要求引用却不给出处**：`_extract_data_points` 读错键名（标注记录的键是 `book`，代码读 `title`），
   导致每条洞见渲染成 `（来源: ）`；网页素材连 URL 都没有。
   于是"必须来自素材"成为**模型无法自查**的要求。
   而审稿端又把"不在素材中的 URL"判为伪造 —— 写作端拿不到出处、审稿端按出处审。
3. **没有任何机制在拦**：提示词是请求，审稿是事后正则。
   中间没有一道机制能在"假数字被写出的瞬间"阻止它。

**这个修正让结论更强而非更弱**：五处明文禁令 + 事后正则检查都没能防住编造，
正是"反编造必须是机制而非纪律"的最有力证据。

更直接的证据，一行明文命令造假：
```
writer.py:234 (marketing): "用具体数字建立信任（"已有2300+开发者使用"），没有数据用用户证言"
```
这就是 task 61 给 WPDate 编造客户证言与转化率的来源。同类示例数字（case-study "3s→0.8s、流量增长40%"、trend "React份额38%→33%"）会被模型**逐字照抄**。已全部改为占位符 + "N 必须来自素材"。

### 2. 管线自 7-01 起根本跑不通

`pipeline.py:423` 调用 `TaskDB.save_meta`，而该方法**从未存在**（`git log -S` 查无）。每个任务走到 compile 必抛 `AttributeError` → 被裸 except 吞掉 → 标 `skipped`。
时间线吻合：6 篇 done 全是 5-26（Phase 5 之前），7-01 后一篇都出不来，DB 里 11 条 skipped 即证据。
**修正此前判断**：不是"人一停就空转"，是**即使人不停也产不出东西**。

### 3. 发布环节绕过质量闸门往正文注入假话

`converter.py` 的"类型通告注入"发生在 review **之后**：
- task 99（systemd 教程）被注入"**安全通告** — 请相关站长及时检查并更新受影响的插件或组件"
- task 96（Nginx 缓存）被注入"本文介绍 **1.5** 版本的主要变更"——"1.5"是从前 500 字随手抓的小数

**有些假话不是模型写的，是发布代码自己加的。**

### 4. 五层级联的真实净贡献是 2.9%

改动前最终写作提示词构成实测：**78% 是截断的无出处原始素材**，STYLE 层 2.9%（唯一真接线），SYNTHESIS/PROSODY **各 0%**，FRAMEWORK 仅经 outline 的 LLM 二次转译（方法论/H2/反模式在转译中全部蒸发）。
改动后级联净贡献 2.9% → **16.9%**，新增反编造纪律 6.8%。

### 5. 质量门控在两个方向上都没有判别力（最关键的架构结论）

对照实验（38 篇**人类写的已发布**范本 vs 10 篇 AI slop）：

| | value_density 均值 | 通过数 |
|---|---|---|
| AI slop | 4.14 | 0 |
| **人类已发布范本** | **2.14** | **0（35 fail）** |

人类范本得分**低于** AI slop——门控惩罚的是长度、URL 数、关键词计数，不是质量。

而修好信号传递（`pipeline.py` 三信号）后：task 96/98/99（slop）从 `fail` 翻成 **`pass`**——因为 `has_differentiation` 的判据只是"synthesis 写了 ≥20 字"，恒为真。

**不传信号 → 100% 拒稿；传信号 → slop 照过。这不是参数问题，是原理问题。**

### 6. 知识库本身不可信（比检索跑题更深的一层）

实测 `SELECT quality, COUNT(*) FROM annotations`：
- **`AI_draft` = 1504，占 100%**；`verified_by` = `ai-draft` = 1504

所谓"来自书的知识"**全部是 LLM 对书的二手转述，从未经人工核对**。文章写"《某书》指出…"时，这个归因本身就无法核验。
且语料不匹配：501 本书以心理/自助/营销为主，技术类极少，`data` 类标注仅 **12 条 / 1504**。

**三条 cocobook 通道当前全部不可用**：
- MCP（huawei-pc）自 7/11 不可达
- SSH tantivy（kk-pc）已死：WSL 挂不上 D: 索引盘，返回 UTF-16 错误文本
- 已发布标注库 `/mnt/shared-context/cocobook/cocobook-annotations.db` **自 2026-05-21 起是 0 字节占位文件**（`sqlite3.connect` 对空文件成功，`SELECT` 抛 "no such table" 正好被 `except sqlite3.Error: return []` 吞掉 → 标注通道静默归零，无任何日志）

唯一有数据的是 stage 暂存库。**而研究阶段此前 100% 崩溃**：kk-pc 的 UTF-16 错误文本让 `text=True` 在 `subprocess.run` **内部**抛 `UnicodeDecodeError`，落在 except 之外，直穿整个研究阶段。

其他结构性缺陷：
- **写作范本从来没进过写作提示词**：`writer.py:419` 用 `\[([AB])级\|` 解析，而真实 quality 是 `AI_draft` → 正则永不匹配
- **提纲是在只看得见文风样本的情况下定骨架的**：`outline.py` 只取 `research_note[:2000]`，而文风样本（≈4200 字）原本排在笔记最前面
- **时效性完全缺失**：标注无出版年、网页无发布日期。"2019 年的 nginx 配置"和"2026 年的"在笔记里长得一模一样
- **`TopicFilter` 永远无法拒绝任何选题**：`pipeline.py:815` 只在 `recommendation == "reject"` 时拒绝，而代码路径只产出 `accept`/`low_value`（`"reject"` 仅存在于 docstring）
- `vm_consult` 跨 VM 确认通道恒为空（`gather_research` 从不调用）；LanceDB 向量检索**不存在**（docstring 声称的是假的）

### 7. 安全问题（已止血）

`review_server.py`：默认监听 `0.0.0.0`、GET 无鉴权、POST 直接发线上站，且 `_send_static` 未规范化路径 → 任意文件读。等于全子网一个一键发布按钮。已改绑 `127.0.0.1` + 路径校验。**鉴权未真修**（表单 POST 与 Bearer token 不兼容）。

---

## 二、已完成修改（分层）

### 生成层
- PROSODY 断链**已接上**（writer 用真实范本 + 品类禁语，去重合并）
- COMPILE **判定不接**并给出量化理由（compile 的 596 字符缺全部事实护栏 vs writer 4103 字符）；其独有的"带出处素材"已原生搬进 writer
- framework 回退**已修**，并发现 manifest 声明的方法论名大面积过时（`step_by_step` 全库不存在），改为以 yaml 为准 + warning 暴露漂移
- **反编造纪律**（8 条可逐字核对规则）插入提示词最高优先级
- 修 6 个确证 bug：品类名连字符不匹配导致 **prosody 阶段整体崩溃 + framework 静默降级**；`h2_title` 被硬清空；`principles/anti_patterns/quality_gates` 全库 100% 从未进入提示词；synthesis 不知道文章主题；差异化门控绕过重试；每次调用白烧一个必然 4xx 的往返
- outline 加 `temperature=0.2`（此前结构化抽取在 ~1.0 默认温度下产 JSON）

### 编排层
- 补 `save_meta`（修复管线致命阻断）
- `_drive()` 状态驱动扁平调度器取代嵌套 if 链——**顺带修掉一个缩进错位导致的人工闸门绕过**（TIER_EXTERNAL 提纲未经放行直接写正文）
- `resume()` 覆盖全部 7 个活跃状态（此前 4 个永久卡死，只能手改 SQLite）
- `recover_stuck` 重写：统一回 queued、保留产物、`MAX_RECOVERY_ATTEMPTS=3`、不再摧毁待审工作
- 契约改 `from_dict` + `validate()`；`config.validate_config()`；结构化 `error_log` + `record_failure`
- 修 `pipeline-run.sh` 的 dry-run 改数据 / 重复 claim / 参数误用；修 shell 注入；修 systemd timer **非法语法**与重试风暴（**仍 disabled**）
- 选题去重（`normalize_keyword`）；CLI 两套合一

### 交付层
- 关闭类型通告注入（默认）+ 版本号正则收紧
- 修 Mermaid 图**错位 + 源码泄漏**（3 图场景下第 2 张丢失、第 1 张源码进正文）
- 修摘要被通告框劫持（影响归档页/搜索/社交预览）
- 修链接内加粗与行内代码丢失、✓✗ 被当 emoji 删除、列表/表格在 WP 编辑器判为无效区块
- 新增 `dry_run`（不联网不 ssh）+ 幂等闸门 + REST 成功需 `id`/`link` 才算成功
- review_server 安全加固 + `/preview` 发布预演（解决"审阅用 A 转换器、发布用 B 转换器"）

### 质量层
- **`semantic_judge.py`（456 行，默认关闭）**：4 维序数档 + 5 层防橡皮章
- 表层指标实测分离度，判定保留 `ai_check`/`format`/`word_count`/`fabrication` 作预过滤，其余降级
- `pipeline.py` 三信号传递（本次主控修复 + 回归测试）
- 测试体系重建：**131 collected+1 error（且会无限挂起）→ 374 passed**；删除刷绿测试（含一个"名字有 mock 实际调真实 LLM"的，在有 key 机器上会真实计费）

---

### 检索层
- 修研究阶段 100% 崩溃（`errors="replace"` + 异常兜底 + `shlex.quote` + 丢弃 error 载荷冒充素材）
- **话题盲的构造性根因**：`_route_topics` 无信号匹配时曾 fallback 到 3 个 WordPress 索引，且被渲染在"官方文档原文段落，这是最高质量的写作参考"标题下 → 改为返回空（诚实的空胜过自信的错）
- 删掉全仓唯一的 `ORDER BY RANDOM()`；修 LIKE 把"的"和空格当通配符导致全表近似匹配
- 相关性闸升级：虚词 bigram 过滤（"为什/什么"曾匹配任何中文句子）+ 正文/元数据加权 + 拉丁技术词规则。实测"systemd 定时器为什么不触发"的跑题注入归零，而"WordPress 缓存插件怎么选"仍拿到 6 条相关素材
- 出处可追溯：`_provenance()` 统一输出《书名》/作者/可信度/行号/URL；修 `_extract_data_points` 读错键名导致**每条洞见都渲染成 `(来源: )`**；网络素材首次带上 URL
- `AI_draft` 标签明写"未经人工核验，不可作为权威依据"
- 笔记组装改为优先级预算截断 + 事实在前文风在后（此前硬切尾部 8000 字，删掉的正好是网页全文与代码依据）
- 内容农场表补齐云厂商"开发者社区"与 CSDN 抓取镜像；单站上限 2 条；无 charset 时中文页乱码修复
- `topic_filter` 键名错配修复（读 `body` 而实际是 `snippet` → 三个筛子只看得见标题）

## 三、AI 原生改进方向（核心建议）

### 1. 把"不编造"从劝说变成机制（最高性价比）
现状全靠提示词请求模型自律 + 正则事后抓。
改法：写作调用挂 `cite(fact, evidence_id)` 工具，模型每要写一个数字/常量名/版本号，必须先调用并命中证据 ID，**拿不到就写不出那个 token**。这是唯一能结构性消灭本次全部事实错误的改法。

### 2. 分段生成 + 逐段确定性校验
现在整篇一次 8192 token 出稿，一段编造要整篇重写。
改法：按 framework.structure 逐段生成，每段生成后立刻校验（该段数字是否在该段分配的 `[E*]` 素材里逐字命中），不通过只重写该段。段级重试比篇级便宜一个数量级。

### 3. 放行决策权交给语义评审，表层指标退为预过滤
已实现 `semantic_judge`。成本实测 $0.0417/篇（Sonnet）或 $0.0091/篇（glm 档），100 篇/月 ≈ $4.17 / $0.91。
关键设计：judge 只输出档位与事实清单，`pass/revise/reject` 由 Python 硬规则算；逐字引文用字符串核对（伪造即降级）；校准压舱物检测橡皮章；双 pass 取 **min() 不取均值**。

### 4. 结构化输出替代正则刨 JSON
`outline.py:299` / `synthesis.py:80` 靠正则从自由文本找第一个 `{` 到最后一个 `}`；outline 无重试、fallback 配的是 **gemma3:1b**（1B 模型产结构化 JSON 只会产垃圾，只是让失败看起来像成功）。改用 JSON schema / tool-use 强制形状。

### 5. 补"选题供给"层，把人的动作从"想选题"降级为"打勾"
唯一入口是 `ap add`。建议 `schedule-check` 在缺口时产出 N 个 `status=proposed` 待确认选题，人 `ap approve-topic` 入队。

### 6. 交付层一个字都不许改内容
类型通告注入、em-dash 修正、emoji 剥离全发生在 review 之后。任何在质量闸门之后改动正文的代码，都是往已核查内容里塞未核查内容。全部左移到写作/审阅阶段。

---

## 三·五、端到端验证尝试的结果（2026-07-25 追加）

计划做 A/B 实验（同一关键词与素材，跑审计前 vs 审计后的写作层，数编造项）以验证反编造纪律的**实际效果**。**实验被两个配置阻断，未能完成**：

1. **管线没有可用的 API key。** `AP_DS_API_KEY` / `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` 全部未设置；`_get_api_key()` 的回退链捡到了 `ANTHROPIC_AUTH_TOKEN`（前缀 `studio-l...`，是 Claude Code 自身的 token），把它发给 `api.deepseek.com` → **HTTP 401 token expired or incorrect**。任何写作调用现在都会失败。
2. **检索通道确认全死**：kk-pc 的 WSL 挂不上 `D:/wsldir\ext4.vhdx`（返回 UTF-16 乱码），cocobook 全后端无命中。现在会诚实输出 "all backends down — the article will have no book knowledge"（此前是静默继续写）。

**这意味着**：反编造纪律的效果**仍未经实证**。全部改动只有离线单测支撑——接线正确可断言，效果不可断言。
**与 `wptea_url` 未配置属同一类问题：这套系统从未被真正配置过，只被开发过。**

## 四、待人工决定

1. **分支是否合并**（`fix/quality-gate-fatal-bugs`，未提交）
2. **是否启用 semantic_judge**（`AP_SEMANTIC_JUDGE`，默认关闭；启用需 API key 与成本认可）
3. **是否启用 systemd timer**（语法已修，仍 disabled；建议只跑体检不跑生产）
4. **`wptea_url` 未配置** —— 当前配置下 `ap publish` 走不到任何通道，需人决定填 REST endpoint 还是显式走桥
5. **孤儿模块删除**（visual/screenshot/social_card + 对应测试，共 1002 行）——待批准清单已列，未删
6. **僵尸数据清理**（21 条建议，`scripts/pipeline-cleanup.py` 默认 dry-run，永不 DELETE）；其中 #96/#98/#99/#100 已有 2388-2924 字正文，建议人工过目
7. **REST 通道端到端从未验证** —— 建议先用 `status=draft` 发一篇真文章验证（`publish.py` 的 `status: "publish"` 需先改为可配置）

## 五、未完成 / 已知缺口

- `evidence_against` / `conflicts` 未接进写作提示词（"有观点"的素材供给）
- `style.py:185` 仍含编造示例数字 `"TTFB 从 800ms 降到 200ms"`
- review_server 鉴权未真修（仅绑 loopback 止血）
- `test_publish.py` 仍缺（publish.py 零覆盖）；delivery 层已确证 bug 缺回归测试
- 反编造纪律的**实际效果未经端到端验证**（全部改动仅离线单测；需带 key 跑同关键词改动前后对照，人工核对数字命中率）
