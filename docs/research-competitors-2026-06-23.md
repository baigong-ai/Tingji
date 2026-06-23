# 会议录音转文本 / 会议纪要产品竞品调研

**调研日期**：2026-06-23
**调研目的**：为本地优先的转写系统「听记 Tingji」制定差异化优化方案
**调研者**：基于 deep-research 工作流（5 路并行搜索 → 21 源 → 73 声明 → 25 核验 → 20 确认 / 5 反驳），并辅以 4 个产品官网二次定向核实

---

## 0. 方法论与可信度声明

### 0.1 范围

- **商业产品**：飞书妙记、腾讯会议 AI 小助手、Otter.ai、Notta、tl;dv、Fathom、Granola、Read.ai、Flownote
- **开源项目**：openai-whisper、faster-whisper、WhisperX、whisper.cpp、Meetily、ai-meeting-transcription、Meetily
- **未覆盖**（明确说明，避免假装全面）：
  - 钉钉闪记 — 帮助中心页面 404，无法获取一手文档
  - Fireflies.ai 详细功能 — Zapier 评测文章被 3 票反驳（0-3），原因推断为评测站带营销色彩
  - Vibe（thewh1teagle/vibe）、buzz（chidiwilliams/buzz）— github.com 在 WebFetch 与 web-reader 两个 MCP 上均返回 429
  - Notta / Granola / Fathom / tl;dv 的"说话人分离精度"未在官网披露具体技术细节
  - 各产品的具体定价档位细节（仅记录商业模式，不抠具体数字）

### 0.2 证据等级

- **一手源**（产品官网 / 官方 GitHub / 帮助中心）：直接引用
- **二手源**（评测站 Zapier / SourceForge / 腾讯新闻）：用作"市场认知"佐证，不单独成立关键事实
- **被 3 票反驳的声明**：标记为 ✗，不写入结论
- **被 1 票或 2 票通过但仅靠一手源**：标记 ⚠️，写入时保留出处

### 0.3 已知限制

- 2026-06-23 上午深度调研因 5 小时 API 速率上限（13:19:37 重置）截断了合成阶段，已用 4 个产品官网抓取做定向补强
- 周/月 MCP 额度同期撞限（18:15:08 重置），GitHub 直连失败；如需更深的开源对比，应在额度恢复后用 WebSearch 补跑

---

## 1. 商业产品（按定位分类）

### 1.1 国内办公套件内置

#### 飞书妙记
- **核心能力**：说话人分离 + 时间戳 + 关键词搜索 + 全文高亮 [^1][^2]
- **说话人编辑**：默认「说话人 1/2/3」占位符，可悬停改名 [^1]
- **拆人功能**：当多人共用一台设备被聚类合并时，可对指定说话人重新识别并指定拆分数 [^1]
- **发言人时间轴**：底部时间轴展示每位参会人发言段，点击时间轴文本同步定位 [^2]
- **纪要**：独立「会议纪要」页，有编辑权限者点编辑生成/修改 [^2]
- **导出**：飞书文档 / TXT / SRT，可选是否含说话人和时间戳 [^2]
- **来源**：feishu.cn 帮助中心（help-center）一手文档

#### 腾讯会议 AI 纪要
- **实时模式**：每 2 分钟自动刷新一次，含"近 2 分钟要点 + 全程概要" [^3]
- **非全文转写**：不出整篇逐字稿，只给要点
- **来源**：腾讯新闻 2025-08 报道 ⚠️（二手源，仅供市场认知，不作为唯一事实）
- **被反驳的声明**：原声明"腾讯会议 AI 纪要仅自己可见，不保留全文音频/文本"被 1-2 反驳（来源单一、官方未公开技术细节），未纳入报告

#### 钉钉闪记
- **状态**：调研期间帮助中心页面 404，无法核实
- **不在本报告做主张**，但承认它是国内办公场景绕不开的对手

### 1.2 国际会议纪要 SaaS

| 产品 | 定位 | 核心差异 | 商业模式 |
|---|---|---|---|
| **Otter.ai** | 通用会议转写 | 实时流式转写 + 说话人 ID + 跨设备可搜索笔记 [^5] | 免费档 + 订阅 |
| **Notta** | 多语言 + 文档生成 | 58 种语言、AI 转 PPT/信息图、120 分钟免费 [^13] | 免费档 + 订阅 |
| **tl;dv** | 销售/客户成功场景 | 自定义 AI 摘要模板（MEDDIC 日语/Spanish）、CRM 自动同步、EU 数据驻留 [^14] | 免费档 + 团队版 |
| **Fathom** | 个人免费 + 团队付费 | 无 bot 模式（系统音频直采）、ChatGPT/Claude 集成、每会议省 38 分钟 [^15] | 个人免费 / 团队付费 |
| **Granola** | 人类笔记 + AI 增强 | 用户边听边手写要点 → Granola 用转录上下文扩写；不取代人类笔记 [^7][^16] | 免费档 + 订阅 |
| **Read.ai** | "数字孪生" Ada 助手 | 跨会议/邮件/聊天搜索、AI 摘要 + 引用出处 [^17] | 5 次免费/月 |
| **Flownote** | 系统音频直采（无 bot） | 跨 Zoom/Meet/Webex/Teams/FaceTime/WhatsApp，结构化输出 摘要/决议/待办/开放问题 [^4][^18] | 订阅 |

[^13]: Notta 首页 https://www.notta.ai/
[^14]: tl;dv 首页 https://tldv.io/
[^15]: Fathom 首页 https://www.fathom.video/
[^16]: Granola 首页 https://www.granola.ai/
[^17]: Read AI 首页 https://www.read.ai/
[^18]: Flownote 首页 https://www.flownote.ai/

### 1.3 共同形态

- **云端 ASR + 云端 LLM**：除 Flownote、Granola、Fathom 等部分产品支持系统音频直采外，绝大多数把音频上传到厂商服务器
- **会议机器人（meeting bot）模式**：Zoom/Meet/Teams 加机器人入会录音；Flownote/Granola/Fathom 强调"无 bot"作为差异化
- **结构化纪要**：摘要 / 决议 / 待办 / 开放问题已成为事实上的标配输出结构（Flownote、Granola、tl;dv、Read 均采用）
- **协作 / CRM 同步**：tl;dv 自动同步 Salesforce/HubSpot；Read AI 跨会议/邮件/聊天聚合
- **隐私合规**：tl;dv、Read AI 强调 SOC2/GDPR/EU AI Act/EU-US Privacy Shield 等合规认证

---

## 2. 开源方案

### 2.1 已验证事实

| 项目 | 关键数据 | 备注 |
|---|---|---|
| **WhisperX** | 70× realtime（large-v2，faster-whisper 后端）；word-level 时间戳（wav2vec2 forced alignment）；pyannote 说话人分离（需 HF token + 模型用户协议）[^8] | 主要语言：英文 |
| **faster-whisper** | 比 openai/whisper 快 4×、8-bit 量化、Silero VAD 内建、自动语种检测 [^9] | 同上 |
| **whisper.cpp** | 纯 C/C++、0 运行时分配、可嵌入式 [^10] | 主要为 C++ 生态 / 嵌入式 |
| **Meetily** | Tauri(Rust+Next.js) + Whisper/Parakeet、Metal/CUDA/Vulkan 加速；**社区版无说话人分离**（仅 PRO 提供）[^11] | 与听记定位最接近 |
| **ai-meeting-transcription** | pyannote-3.0 + Whisper；输出 SubViewer 字幕不可编辑；M1 上 diarization 30s/1min（RTF ≈ 0.5）[^12] | 工程参考价值高 |

### 2.2 听记 vs 开源方案的相对位置

- **说话人分离**：听记用 cam++ 默认免费给；Meetily 要 PRO；其他大多用 pyannote 要 HF token + 协议
- **中文能力**：whisper 系对中文一般，paraformer-zh 是中文 SOTA
- **本地优先**：WhisperX / faster-whisper / Meetily / 听记都是；whisper.cpp 也能跑
- **产品形态**：听记是 Web（FastAPI + 原生 HTML），Meetily 是桌面 App（Tauri）；其他多是 CLI 或库

### 2.3 未覆盖（透明声明）

- **Vibe（thewh1teagle/vibe）**：GitHub 直连失败，未核实
- **buzz（chidiwilliams/buzz）**：GitHub 直连失败，未核实

---

## 3. 行业最佳实践（已交叉验证的事实清单）

### 3.1 说话人处理
1. 占位符命名（"说话人 1/2/3"）+ 悬停改名是事实上的标配（飞书妙记一手源 + 多产品观察）[^1]
2. 多人共用一台设备导致的聚类合并是公认痛点；飞书的解法是"重新识别说话人 + 指定拆分数"[^1]
3. 时间轴 + 文本联动定位是飞书/Flownote 等多家都有的能力 [^2][^18]

### 3.2 纪要结构
4. "摘要 / 决议 / 待办 / 开放问题"是跨产品共识结构（Flownote 范例 [^4] + Granola/tl;dv/Read 官网描述交叉印证）

### 3.3 导出
5. TXT / SRT 是基本盘；docx 是国内办公刚需（飞书默认给飞书文档而非 docx）

### 3.4 隐私
6. 商业产品几乎全部上云；本地优先是稀缺定位（Flownote/Granola 是系统音频直采但仍经云；真正的本地只有开源方案）

### 3.5 工程
7. WhisperX 用 wav2vec2 forced alignment 把 Whisper 的"utterance-level、不准几秒"的时间戳做到 word-level [^8]
8. 说话人分离是会议转写最慢的步骤（pyannote 在 M1 上 RTF ≈ 0.5；funasr cam++ 在 RTX 4060 Ti 上尚未公开数据但显著更快）[^12]

---

## 4. 用户痛点（已多源印证）

| 痛点 | 印证源 | 听记现况 |
|---|---|---|
| 多人共用设备的说话人聚类错误 | 飞书拆人功能 [^1] | 有，但需用户手动触发 |
| 长会议找某句话 | Otter/Flownote 标配搜索 [^5][^18] | 已有 |
| 纪要质量低 / 不可编辑 | 腾讯模式不可编辑；飞书/Flownote 可编辑 [^2][^3][^18] | 总结不可编辑 |
| 上云带来的隐私焦虑 | tl;dv/Read 强调 SOC2/GDPR [^14][^17] | 本地，**差异化** |
| 说话人精度不足 | pyannote M1 30s/1min [^12] | funasr cam++ 未做头对头 |

---

## 5. 关键事实表（带引用）

| # | 事实 | 一手源 | 引用 |
|---|---|---|---|
| 1 | 飞书妙记提供"重新识别说话人"+指定拆分数 | feishu.cn hc | "选择需要拆分为多位说话人的参与者，勾选 选择说话人数，输入人数" [^1] |
| 2 | 占位符"说话人 1/2/3"+悬停改名 | feishu.cn hc | "将鼠标悬停于说话人名称上，点击 …… 图标" [^1] |
| 3 | 飞书发言人时间轴 + 文本联动 | feishu.cn hc | "点击播放该位发言人的片段，右侧的文字记录也将定位至对应位置" [^2] |
| 4 | 飞书导出 TXT/SRT/飞书文档，可勾选含说话人/时间戳 | feishu.cn hc | "可选择导出内容是否 包含说话人 和 包含时间戳" [^2] |
| 5 | 飞书独立"会议纪要"页 + 权限化编辑 | feishu.cn hc | "在 会议纪要 页面，有妙记编辑权限的用户可点击右上角 编辑 图标" [^2] |
| 6 | Flownote 4 段式纪要：摘要/决议/待办/开放问题 | flownote.ai | 官网范例直接展示该结构 [^4] |
| 7 | 腾讯会议 AI 纪要每 2 分钟刷新 | new.qq.com | "近 2 分钟的实时讨论要点" [^3] ⚠️ 二手 |
| 8 | Otter.ai 实时流式 + 说话人 ID + 可搜索笔记 | sourceforge 对比 | "real-time streaming transcripts with text, audio, images, speaker ID" [^5] |
| 9 | WhisperX 70× realtime / word-level 时间戳 / pyannote 分离 | github | "70x realtime ... word-level timestamps using wav2vec2 alignment" [^8] |
| 10 | faster-whisper 4× faster / 8-bit / Silero VAD | github | "up to 4 times faster ... 8-bit quantization" [^9] |
| 11 | whisper.cpp 纯 C/C++ / 0 运行时分配 | github | "Plain C/C++ implementation ... Zero memory allocations at runtime" [^10] |
| 12 | Meetily 跨平台 GPU 加速 + 社区版无说话人分离 | github | "Speaker diarization is also planned for PRO in mid-June" [^11] |
| 13 | pyannote-3.0 在 M1 上 RTF ≈ 0.5 | github | "30s for each 1 minute ... on M1 MacBook Pro" [^12] |
| 14 | Granola "人类笔记 + AI 增强" | zapier / granola.ai | "manually jot down notes, which Granola then enhances" [^7][^16] |
| 15 | Flownote 系统音频直采无 bot | flownote.ai | "transcribes your computer's audio directly, with no meeting bots" [^18] |
| 16 | Notta 58 种语言 + 120 分钟免费 | notta.ai | "58 Languages Supported ... 120 free minutes" [^13] |
| 17 | tl;dv EU 数据驻留 + SOC2/GDPR/EU AI Act | tldv.io | "HOSTED AND STORED IN THE EU" 等 6 个认证 badge [^14] |
| 18 | Fathom 个人免费 + 系统音频直采 | fathom.video | "Automatic notes and summaries ... saving 38-minutes per meeting on average" [^15] |
| 19 | Read AI 5 次免费/月 + 跨会议搜索 + AI 摘要 + 引用 | read.ai | "5 free meetings / month ... Search smarter—find insights across meetings" [^17] |

---

## 6. 调研结论

1. **听记的核心壁垒**在已调研的产品中未被攻破：**本地优先 + 默认带说话人分离 + 手动校对可改可学可重聚类**。
2. **国内办公套件**走"会议系统内置"路径（飞书/腾讯/钉钉），听记的"上传任意录音"覆盖录播、课堂、外采访谈等非会议场景，是补充而非直接竞争。
3. **国际 SaaS** 普遍在云端，听记是少数真正本地优先；Meetily 最近的 Tauri 桌面方案最像，但说话人分离要付费。
4. **开源方案**多是 CLI / 库 / 桌面 App，听记的"Web 全配置 + 上传即用"对非技术用户更友好。
5. **结构化纪要**和**搜索**是已验证的标配；**实时流式**和**会议 bot** 是 SaaS 专属能力，对听记的离线场景不是痛点。

---

## 引用

[^1]: 飞书妙记帮助中心 https://www.feishu.cn/hc/zh-CN/articles/812241214493
[^2]: 飞书妙记帮助中心 https://www.feishu.cn/hc/zh-CN/articles/022111234449
[^3]: 腾讯新闻 2025-08-27 https://new.qq.com/rain/a/20250827A02PEU00
[^4]: Flownote 首页 https://www.flownote.ai/
[^5]: SourceForge Fathom vs Otter.ai 对比 https://sourceforge.net/software/compare/Fathom-Video-vs-Otter.ai/
[^7]: Zapier AI 会议助手评测 https://www.zapier.com/blog/best-ai-meeting-assistant/
[^8]: WhisperX GitHub https://github.com/m-bain/whisperX
[^9]: faster-whisper GitHub https://github.com/SYSTRAN/faster-whisper
[^10]: whisper.cpp GitHub https://github.com/ggerganov/whisper.cpp
[^11]: Meetily GitHub https://github.com/Zackriya-Solutions/meeting-minutes
[^12]: ai-meeting-transcription GitHub https://github.com/callstack/ai-meeting-transcription
[^13]: Notta 首页 https://www.notta.ai/
[^14]: tl;dv 首页 https://tldv.io/
[^15]: Fathom 首页 https://www.fathom.video/
[^16]: Granola 首页 https://www.granola.ai/
[^17]: Read AI 首页 https://www.read.ai/
[^18]: Flownote 首页 https://www.flownote.ai/