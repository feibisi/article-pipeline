"""dbs-ai-check: AI 写作特征识别

源自 dontbesilent/dbskill，22 个 AI 特征检测。
整合到 article-pipeline review 层。

特征分类：
- 🔴 强信号 — 几乎只有 AI 会这样做
- ⚠️ 中信号 — AI 高频但人也可能做
- 💡 弱信号 — 需结合体裁和上下文判断
"""

import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class AIFeatureHit:
    """命中的 AI 特征"""
    feature_id: int  # 1-22
    feature_name: str
    severity: str  # "strong", "medium", "weak"
    text: str  # 命中的原文片段
    reason: str  # 问题说明
    position: int  # 在全文中的位置（大致）


class DbsAIChecker:
    """dbs-ai-check 检测器"""

    def __init__(self, text: str):
        self.text = text
        self.hits: List[AIFeatureHit] = []

    # ────────────────────────────────────────────────────────────────────
    # 特征检测函数（22 个）
    # ────────────────────────────────────────────────────────────────────

    def check_feature_1堵住所有反驳(self) -> List[AIFeatureHit]:
        """特征 1：堵住所有反驳
        🔴 强信号

        模式：连续列举可能的反对意见然后逐条反驳
        检测："你可能会觉得..." "有人可能会说..." + 反驳
        """
        hits = []
        # 检测：多个反驳结构在短距离内出现
        patterns = [
            r"你(?:可能)?(?:会)?觉得?[^。！？；]{5,30}(?:但是|不过|然而)",
            r"有人(?:可能)?(?:会)?(?:认为|说|觉得)[^。！？；]{5,30}(?:但是|不过|然而)",
            r"或许有人会说[^。！？；]{5,30}(?:但是|不过|然而)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, self.text):
                hits.append(AIFeatureHit(
                    feature_id=1,
                    feature_name="堵住所有反驳",
                    severity="strong",
                    text=match.group(0)[:60],
                    reason="你堵了这些反驳，哪个是你真的被人问过的？只留那个。",
                    position=match.start()
                ))
        # 如果超过 2 个反驳结构，标记
        if len(hits) >= 2:
            return hits
        return []

    def check_feature_2知识全部输出(self) -> List[AIFeatureHit]:
        """特征 2：知识全部输出
        🔴 强信号

        模式：堆砌术语、数据、概念，缺乏选择
        检测：高密度的专业术语/数据/名词
        """
        hits = []
        # 检测：段落内名词/术语密度过高
        paragraphs = self.text.split("\n\n")
        for para in paragraphs:
            if len(para) < 50:
                continue
            # 统计可能的术语/名词（2-6字的中文词组）
            terms = re.findall(r"[^\w\s]{2,6}(?:能力|系统|模式|框架|协议|标准|技术|算法|模型|机制)", para)
            if len(terms) >= 4:
                hits.append(AIFeatureHit(
                    feature_id=2,
                    feature_name="知识全部输出",
                    severity="strong",
                    text=para[:60],
                    reason="你堆了这么多术语，哪一个是你真正用来想事情的？留那一个。",
                    position=self.text.find(para)
                ))
        return hits[:2]  # 最多返回 2 处

    def check_feature_3匀速排比(self) -> List[AIFeatureHit]:
        """特征 3：匀速排比
        ⚠️ 中信号

        模式：3 个以上结构相似的句子连续出现
        """
        hits = []
        # 检测：3 个以上相似句式
        sentences = re.split(r"[。！？；]", self.text)
        for i in range(len(sentences) - 2):
            s1, s2, s3 = sentences[i:i+3]
            if len(s1) < 10 or len(s2) < 10 or len(s3) < 10:
                continue
            # 检查句式相似度（简单长度对比）
            lengths = [len(s1), len(s2), len(s3)]
            if max(lengths) - min(lengths) < 10:  # 长度差异小于 10 字
                hits.append(AIFeatureHit(
                    feature_id=3,
                    feature_name="匀速排比",
                    severity="medium",
                    text=f"{s1[:30]}...{s2[:30]}...",
                    reason="这几句排比里，哪一句是你最想说的？把那一句加长，打破均匀。",
                    position=self.text.find(s1)
                ))
                break
        return hits

    def check_feature_4让步模板反复用(self) -> List[AIFeatureHit]:
        """特征 4：同一个让步模板反复用
        ⚠️ 中信号

        模式：多次使用"虽然...但是..."、"尽管...却..."等结构
        """
        hits = []
        # 统计让步结构
        concession_patterns = [
            r"虽然[^。！？]{5,50}(?:但是|可是|然而)",
            r"尽管[^。！？]{5,50}(?:但是|可是|却|然而)",
            r"即使[^。！？]{5,50}(?:也|仍然)",
        ]
        all_matches = []
        for pattern in concession_patterns:
            all_matches.extend(re.finditer(pattern, self.text))

        if len(all_matches) >= 3:
            hits.append(AIFeatureHit(
                feature_id=4,
                feature_name="让步模板反复用",
                severity="medium",
                text=f"发现 {len(all_matches)} 处让步结构",
                reason="你走了三遍同一个让步结构，读者到第二遍就懂了。后面的能换说法吗？",
                position=all_matches[0].start()
            ))
        return hits

    def check_feature_5命名仪式(self) -> List[AIFeatureHit]:
        """特征 5：给概念起名字的仪式
        ⚠️ 中信号

        模式：使用引号、破折号、"我们称之为"等方式给概念命名
        """
        hits = []
        # 检测命名模式
        patterns = [
            r"(?:我们|我)(?:称之为|称为|叫)(?:为)?['""「「《][^」」》]{2,8}['""」」》]",
            r"[———]['""「「《][^」」》]{2,8}['""」」》](?:效应|现象|法则|定律|模式)",
            r"所谓的['""「「《][^」」》]{2,8}['""」」》]",
        ]
        all_matches = []
        for pattern in patterns:
            all_matches.extend(re.finditer(pattern, self.text))

        if len(all_matches) >= 2:
            for match in all_matches[:2]:
                hits.append(AIFeatureHit(
                    feature_id=5,
                    feature_name="命名仪式",
                    severity="medium",
                    text=match.group(0)[:50],
                    reason="你给了概念起名字，哪个名字是你真觉得精准的？留那一个。",
                    position=match.start()
                ))
        return hits

    def check_feature_6情绪曲线太光滑(self) -> List[AIFeatureHit]:
        """特征 6：情绪曲线太光滑
        💡 弱信号

        模式：文章节奏均匀，没有停顿、犹豫、卡顿
        检测：句子长度方差过小，缺乏长短变化
        """
        hits = []
        sentences = [s.strip() for s in re.split(r"[。！？]", self.text) if s.strip()]
        if len(sentences) < 10:
            return []

        lengths = [len(s) for s in sentences]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        std = variance ** 0.5

        # 标准差小于平均长度的 30%
        if std < avg * 0.3 and avg > 20:
            hits.append(AIFeatureHit(
                feature_id=6,
                feature_name="情绪曲线太光滑",
                severity="weak",
                text=f"平均句长 {avg:.0f} 字，标准差 {std:.0f}",
                reason="写的时候有没有哪个地方你自己也没完全想通？那个地方留着，别修圆了。",
                position=0
            ))
        return hits

    def check_feature_7替读者说蠢话(self) -> List[AIFeatureHit]:
        """特征 7：替读者说一句蠢话然后纠正
        ⚠️ 中信号

        模式："你可能会认为..." + 纠正
        检测：明显的读者声音 + 反驳
        """
        hits = []
        patterns = [
            r"(?:你|你|有些人)(?:可能|会|往往)?(?:觉得|认为|以为|想)(?:过)?[^。！？]{5,40}(?:但是|其实|事实上|然而)",
            r"你(?:可能)?(?:会)?(?:问|想|好奇)[^。！？]{5,40}(?:答案是|其实|事实是)",
        ]
        for match in re.finditer(patterns[0], self.text):
            hits.append(AIFeatureHit(
                feature_id=7,
                feature_name="替读者说蠢话",
                severity="medium",
                text=match.group(0)[:60],
                reason="你替读者说的那句话，是你真的听到过别人这么说，还是你编出来的？",
                position=match.start()
            ))
        return hits[:2]

    def check_feature_8不是X是Y高密度(self) -> List[AIFeatureHit]:
        """特征 8：「不是 X 是 Y」高密度
        ⚠️ 中信号

        模式：频繁使用"不是...而是..."结构
        检测：800 字内出现 3 次以上
        """
        hits = []
        pattern = r"不是[^。！？]{3,30}(?:而是|是(?![^。！？]{0,10}而是))"
        matches = list(re.finditer(pattern, self.text))

        if len(matches) >= 3:
            # 计算文章长度
            char_count = len(self.text)
            if char_count < 1000:  # 短文章
                hits.append(AIFeatureHit(
                    feature_id=8,
                    feature_name="不是X是Y高密度",
                    severity="medium",
                    text=f"{len(matches)} 处翻转",
                    reason="你翻转了三次，读者已经不觉得你深了，觉得你在教训人。",
                    position=matches[0].start()
                ))
        return hits

    def check_feature_9没有任何犹豫(self) -> List[AIFeatureHit]:
        """特征 9：没有任何犹豫
        💡 弱信号

        模式：整篇文章语气绝对，没有"可能""或许""大概"
        """
        hits = []
        # 检测：缺少不确定性表达
        uncertain_words = ["可能", "或许", "大概", "也许", "好像", "似乎", "大约", "左右"]
        uncertain_count = sum(self.text.count(w) for w in uncertain_words)

        # 统计句子总数
        sentences = len([s for s in re.split(r"[。！？]", self.text) if s.strip()])

        if sentences > 10 and uncertain_count == 0:
            hits.append(AIFeatureHit(
                feature_id=9,
                feature_name="没有任何犹豫",
                severity="weak",
                text="全文无不确定性表达",
                reason="你这篇文章里有没有什么地方你其实也不太确定？写出来。",
                position=0
            ))
        return hits

    def check_feature_10精确到不真实的情绪细节(self) -> List[AIFeatureHit]:
        """特征 10：精确到不真实的情绪细节
        🔴 强信号

        模式：情绪描述带有过于精确的数字（如"1.7秒""2.3秒"）
        """
        hits = []
        # 检测：小数 + 情绪/时间词
        pattern = r"\d+\.\d+(?:秒|分钟|小时|天|周|月|年)(?:后|前|之后|之前|的)?(?:感觉|感受|体验|瞬间|时刻)"
        for match in re.finditer(pattern, self.text):
            hits.append(AIFeatureHit(
                feature_id=10,
                feature_name="精确到不真实的情绪细节",
                severity="strong",
                text=match.group(0),
                reason="这个数字你量过吗？用你嘴上会说的词来描述。",
                position=match.start()
            ))
        return hits

    def check_feature_11脆弱感服务于论点(self) -> List[AIFeatureHit]:
        """特征 11：脆弱感服务于论点
        💡 弱信号

        模式：个人经历/脆弱感表达后紧接着强结论
        """
        hits = []
        # 检测：个人经历 + 强结论
        patterns = [
            r"(?:我|我自己|亲身)(?:的经历|的故事|的经历的故事)[^。！？]{10,80}(?:因此|所以|这说明|由此可见)",
            r"(?:我)(?:曾经|过去)(?:也|)[^。！？]{10,80}(?:意识到|明白|发现)(?:了)?(?:，)?[^。！？]{5,30}(?:才是|就是)",
        ]
        for match in re.finditer(patterns[0], self.text):
            hits.append(AIFeatureHit(
                feature_id=11,
                feature_name="脆弱感服务于论点",
                severity="weak",
                text=match.group(0)[:60],
                reason="你分享的这段经历，有没有哪部分跟你的论点其实没关系？",
                position=match.start()
            ))
        return hits[:1]

    def check_feature_12协议包装(self) -> List[AIFeatureHit]:
        """特征 12：把结论包装成「协议」
        ⚠️ 中信号

        模式：结尾用"你可以..."、"我们建议..."等操作建议收束
        """
        hits = []
        # 检测：结尾处的协议式表达
        last_para = self.text.split("\n\n")[-1] if "\n\n" in self.text else self.text[-200:]
        patterns = [
            r"(?:你可以|你可以考虑|你可以尝试|建议你|建议)(?:[^。！？]{5,30})",
            r"(?:第一步|首先|接下来)(?:[^。！？]{5,30})(?:，|。)(?:然后|接下来|第二步)",
        ]
        for pattern in patterns:
            if re.search(pattern, last_para):
                hits.append(AIFeatureHit(
                    feature_id=12,
                    feature_name="协议包装",
                    severity="medium",
                    text=last_para[:60],
                    reason="你前面花了几千字说这件事不能被简化，结尾又给了一个简化版。",
                    position=len(self.text) - len(last_para)
                ))
                break
        return hits

    def check_feature_13段落金句(self) -> List[AIFeatureHit]:
        """特征 13：每个段落都有收束金句
        ⚠️ 中信号

        模式：段落末尾有总结性/点睛式句子
        """
        hits = []
        paragraphs = [p.strip() for p in self.text.split("\n\n") if p.strip()]

        # 检测段末金句模式
        golden_patterns = [
            r"[。！？]?(?:这才是|就是|正是|本质上|归根结底|一句话)[^。！？]{5,25}[。！？]$",
            r"[。！？]?(?:关键|核心|要点|重点是)[^。！？]{5,25}[。！？]$",
        ]

        golden_count = 0
        for para in paragraphs:
            for pattern in golden_patterns:
                if re.search(pattern, para[-50:]):
                    golden_count += 1
                    break

        if golden_count >= 3 and len(paragraphs) >= 4:
            hits.append(AIFeatureHit(
                feature_id=13,
                feature_name="段落金句",
                severity="medium",
                text=f"{golden_count} 个段落有收束金句",
                reason="你这篇文章最重要的一句话是哪句？让那句爆发就行。",
                position=0
            ))
        return hits

    def check_feature_14句子节奏过于均匀(self) -> List[AIFeatureHit]:
        """特征 14：句子节奏过于均匀
        💡 弱信号

        类似特征 6，但关注句子而非段落
        """
        # 与特征 6 合并处理
        return self.check_feature_6情绪曲线太光滑()[:1]

    def check_feature_15身体感受替代论证(self) -> List[AIFeatureHit]:
        """特征 15：用身体感受替代论证
        ⚠️ 中信号

        模式：逻辑论证走到尽头时用"身体知道""直觉"收束
        """
        hits = []
        patterns = [
            r"(?:我的|你的)(?:身体|内心|直觉|本能)(?:知道|告诉|感觉)(?:我|你)?[^。！？]{5,30}",
            r"(?:用心感受|身体会告诉你|听从内心|相信直觉)",
        ]
        for match in re.finditer(patterns[0], self.text):
            hits.append(AIFeatureHit(
                feature_id=15,
                feature_name="身体感受替代论证",
                severity="medium",
                text=match.group(0)[:60],
                reason="你用「身体知道答案」来收束，是因为真觉得没法用道理讲清楚？",
                position=match.start()
            ))
        return hits

    def check_feature_16开头三件套(self) -> List[AIFeatureHit]:
        """特征 16：开头「钩子 + 痛点 + 承诺」三件套
        ⚠️ 中信号

        模式：文章开头依次是抓注意力的钩子、描述痛点、给出承诺
        """
        hits = []
        # 检测开头 300 字
        opening = self.text[:300]

        # 检测三件套
        has_hook = bool(re.search(r"(?:你是否|你是否曾|你有没有|你一定)", opening))
        has_pain = bool(re.search(r"(?:困扰|烦恼|痛苦|焦虑|担心|头疼|难题|困境)", opening))
        has_promise = bool(re.search(r"(?:本文|这篇文章|下面|接下来)(?:将|会|帮你|带你|教你怎么|告诉你)", opening))

        if has_hook and has_pain and has_promise:
            hits.append(AIFeatureHit(
                feature_id=16,
                feature_name="开头三件套",
                severity="medium",
                text=opening[:80],
                reason="你的前三句话在卖焦虑。你真正想让读者知道的那件事是什么？",
                position=0
            ))
        return hits

    def check_feature_17连接词过度使用(self) -> List[AIFeatureHit]:
        """特征 17：连接词过度使用且位置固定
        ⚠️ 中信号

        模式："然而""事实上""值得注意的是"等连接词高频出现
        """
        hits = []
        connector_words = ["然而", "事实上", "值得注意的是", "此外", "另外", "同时", "另一方面"]

        total = sum(self.text.count(w) for w in connector_words)
        if total >= 5:
            hits.append(AIFeatureHit(
                feature_id=17,
                feature_name="连接词过度使用",
                severity="medium",
                text=f"发现 {total} 处连接词",
                reason="搜一下全文里有多少个连接词，删掉一半，读者自己能感觉到话锋变了。",
                position=0
            ))
        return hits

    def check_feature_18同义词刻意替换(self) -> List[AIFeatureHit]:
        """特征 18：同义词刻意替换
        💡 弱信号

        模式：同一段内用不同词说同一件事（如"问题""难题""困境"）
        """
        hits = []
        # 检测：段落内同义词组
        synonym_groups = [
            ["问题", "难题", "困境", "挑战", "障碍"],
            ["方法", "方式", "途径", "手段", "策略"],
            ["重要", "关键", "核心", "主要", "首要"],
            ["认为", "觉得", "以为", "相信", "以为"],
        ]

        for group in synonym_groups:
            for para in self.text.split("\n\n"):
                found = [w for w in group if w in para]
                if len(found) >= 3:
                    hits.append(AIFeatureHit(
                        feature_id=18,
                        feature_name="同义词刻意替换",
                        severity="weak",
                        text=f"同一段内使用: {', '.join(found)}",
                        reason="如果这个词你觉得准，重复用。重复不是错。",
                        position=self.text.find(para)
                    ))
                    break
        return hits[:2]

    def check_feature_19翻译腔(self) -> List[AIFeatureHit]:
        """特征 19：中文翻译腔
        ⚠️ 中信号

        模式：使用"作为""关于""基于""进行"等欧化中文
        """
        hits = []
        patterns = [
            r"(?:作为|关于|基于|对于)(?:[^。！？]{2,10})(?:的|来说)",
            r"(?:对|进行)(?:[^。！？]{2,6})(?:分析|研究|讨论|思考|观察)",
            r"(?:处于|位于)(?:[^。！？]{2,10})(?:状态|情况|阶段)",
        ]
        for pattern in patterns:
            matches = list(re.finditer(pattern, self.text))
            for match in matches[:2]:
                hits.append(AIFeatureHit(
                    feature_id=19,
                    feature_name="翻译腔",
                    severity="medium",
                    text=match.group(0)[:50],
                    reason="这句话你嘴上会怎么说？那就怎么写。",
                    position=match.start()
                ))
        return hits[:3]

    def check_feature_20虚假讲故事(self) -> List[AIFeatureHit]:
        """特征 20：虚假的「讲个故事」
        🔴 强信号

        模式："我一个朋友...""我认识一个人..."但缺乏具体细节
        """
        hits = []
        patterns = [
            r"(?:我|我有一个)(?:朋友|同事|同学|熟人|认识的人)(?:叫|说|告诉我)[^。！？]{10,80}(?:然后|后来|结果)",
            r"(?:有一次|记得)(?:我|，我)[^。！？]{20,80}(?:让我|使我)(?:意识到|明白|发现)",
        ]
        for match in re.finditer(patterns[0], self.text):
            text = match.group(0)
            # 检查是否缺少具体细节（名字、时间、地点）
            lacks_detail = not any(x in text for x in ["叫", "名叫", "在", "那天", "去年", "前"])
            if lacks_detail:
                hits.append(AIFeatureHit(
                    feature_id=20,
                    feature_name="虚假讲故事",
                    severity="strong",
                    text=text[:60],
                    reason="这个朋友叫什么？中间出过什么差错？换一个你自己的经历。",
                    position=match.start()
                ))
        return hits

    def check_feature_21结尾祝福(self) -> List[AIFeatureHit]:
        """特征 21：结尾「你值得」式祝福
        ⚠️ 中信号

        模式：文章结尾有温暖祝福/鸡汤式结尾
        """
        hits = []
        # 检测结尾 150 字
        ending = self.text[-150:] if len(self.text) > 150 else self.text

        patterns = [
            r"(?:你值得|你配得上|你值得拥有|愿你|希望你)(?:[^。！？]{5,30})",
            r"(?:加油|努力|坚持|相信自己)(?:，|。)(?:你|我们)(?:一定|肯定|必)(?:会|能)",
            r"(?:美好的|光明的)(?:未来|前程|明天)",
        ]
        for pattern in patterns:
            if re.search(pattern, ending):
                hits.append(AIFeatureHit(
                    feature_id=21,
                    feature_name="结尾祝福",
                    severity="medium",
                    text=ending[:60],
                    reason="删掉最后一段再读一遍。文章是不是已经结束了？",
                    position=len(self.text) - len(ending)
                ))
                break
        return hits

    def check_feature_22过拟合深刻(self) -> List[AIFeatureHit]:
        """特征 22：对「深刻」的过拟合
        ⚠️ 中信号

        模式：将实操问题升维到哲学层面
        """
        hits = []
        patterns = [
            r"(?:本质上|归根结底|从.*角度看)(?:[^。！？]{5,30})(?:是|就是)(?:人性|哲学|存在|本质|真理)",
            r"(?:这不仅仅是|这不仅)(?:[^。！？]{5,30})(?:，|。)(?:更|而)(?:是)",
        ]
        for match in re.finditer(patterns[0], self.text):
            hits.append(AIFeatureHit(
                feature_id=22,
                feature_name="过拟合深刻",
                severity="medium",
                text=match.group(0)[:60],
                reason="你把一个实操问题升维到了哲学层面。这个话题真的需要升维吗？",
                position=match.start()
            ))
        return hits[:2]

    # ────────────────────────────────────────────────────────────────────
    # 主检测函数
    # ────────────────────────────────────────────────────────────────────

    def check_all(self) -> List[AIFeatureHit]:
        """运行全部 22 个特征检测"""
        self.hits = []
        self.hits.extend(self.check_feature_1堵住所有反驳())
        self.hits.extend(self.check_feature_2知识全部输出())
        self.hits.extend(self.check_feature_3匀速排比())
        self.hits.extend(self.check_feature_4让步模板反复用())
        self.hits.extend(self.check_feature_5命名仪式())
        self.hits.extend(self.check_feature_6情绪曲线太光滑())
        self.hits.extend(self.check_feature_7替读者说蠢话())
        self.hits.extend(self.check_feature_8不是X是Y高密度())
        self.hits.extend(self.check_feature_9没有任何犹豫())
        self.hits.extend(self.check_feature_10精确到不真实的情绪细节())
        self.hits.extend(self.check_feature_11脆弱感服务于论点())
        self.hits.extend(self.check_feature_12协议包装())
        self.hits.extend(self.check_feature_13段落金句())
        self.hits.extend(self.check_feature_14句子节奏过于均匀())
        self.hits.extend(self.check_feature_15身体感受替代论证())
        self.hits.extend(self.check_feature_16开头三件套())
        self.hits.extend(self.check_feature_17连接词过度使用())
        self.hits.extend(self.check_feature_18同义词刻意替换())
        self.hits.extend(self.check_feature_19翻译腔())
        self.hits.extend(self.check_feature_20虚假讲故事())
        self.hits.extend(self.check_feature_21结尾祝福())
        self.hits.extend(self.check_feature_22过拟合深刻())

        # 按位置排序
        self.hits.sort(key=lambda x: x.position)
        return self.hits

    def generate_report(self) -> str:
        """生成检测报告（dbskill 格式）"""
        hits = self.check_all()

        if not hits:
            return """# AI 写作特征检测报告

✅ **未检测到明显 AI 特征**

你的文字看起来很干净。英雄不问出处。
"""

        # 统计严重度
        strong = sum(1 for h in hits if h.severity == "strong")
        medium = sum(1 for h in hits if h.severity == "medium")
        weak = sum(1 for h in hits if h.severity == "weak")

        lines = [
            f"# AI 写作特征检测报告\n",
            f"**命中 {len(hits)} 处 AI 指纹**（🔴{strong} 强 · ⚠️{medium} 中 · 💡{weak} 弱）\n",
            ""
        ]

        # 按文本顺序输出
        for i, hit in enumerate(hits, 1):
            severity_emoji = {"strong": "🔴", "medium": "⚠️", "weak": "💡"}
            lines.append(f"**第 {i} 处**\n")
            lines.append(f"> {hit.text}\n")
            lines.append(f"{hit.reason}\n")
            lines.append(f"`特征 #{hit.feature_id} {hit.feature_name} {severity_emoji.get(hit.severity, '')}`\n")

        # 总结
        strong_features = [h for h in hits if h.severity == "strong"]
        if strong_features:
            lines.append("\n---\n")
            lines.append(f"**总结**：强信号集中在 {', '.join(set(h.feature_name for h in strong_features))}。建议优先修改。\n")
        else:
            lines.append("\n---\n")
            lines.append("**总结**：整体可读，但有一些 AI 惯用句式。建议逐一检查。\n")

        return "".join(lines)


def check_ai_fingerprint(text: str) -> List[AIFeatureHit]:
    """便捷函数：检测文本的 AI 指纹"""
    checker = DbsAIChecker(text)
    return checker.check_all()


def generate_ai_report(text: str) -> str:
    """便捷函数：生成 AI 检测报告"""
    checker = DbsAIChecker(text)
    return checker.generate_report()


if __name__ == "__main__":
    # 测试
    test_text = """
在当今数字化时代，人工智能技术得到了广泛的应用和发展。首先，我们需要理解AI的基本原理。其次，我们要掌握AI的应用方法。最后，我们才能有效地利用AI解决问题。

值得注意的是，人工智能在各个领域都发挥着重要作用。此外，机器学习作为AI的核心技术，也在不断进步。事实表明，AI将在未来发挥更大的作用。

你可能会认为AI会取代人类，但事实并非如此。有人可能会说AI没有创造力，然而这种观点也是片面的。

本质上，人工智能不仅仅是技术的进步，更是对人类智慧的延伸。
"""

    print(generate_ai_report(test_text))
