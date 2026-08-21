# Codex Paper Reader Skill

简体中文 | [English](README_en.md)

`paper-reader` 用于为科研 PDF 构建本地、可追溯的交互式阅读器。它把原始 PDF 页面作为视觉依据，并提供逐页导读、坐标绑定批注、图表教学、公式精讲、可选的逐页中译以及携带证据上下文的提问模板。

当前版本：**2.7.1（beta）**

> 本项目是面向 Codex 的独立社区 Skill，并非 OpenAI 官方项目。

## 下载与版本

- [下载最新版 v2.7.1 安装包](https://github.com/piggymon907/codex-paper-reader-skill/releases/download/v2.7.1/paper-reader-v2.7.1.zip)
- [查看全部版本与更新说明](https://github.com/piggymon907/codex-paper-reader-skill/releases)
- [查看旧版 v2.4.0](https://github.com/piggymon907/codex-paper-reader-skill/releases/tag/v2.4.0)

下载 ZIP 后，可以直接让 Codex 从该压缩包安装 Skill。新用户建议使用标记为 **Latest** 的版本。

## 主要功能

- 渲染用户提供的全部 PDF 页面，保留原始版式、公式与图表。
- 把解释绑定到准确的页码、页面坐标和逐字原文证据。
- 提供阅读模式、图解模式和公式精讲模式。
- 对已审阅的每张科研图表和关键公式进行详细解释，不重新生成替代图片。
- 中文翻译按需生成，并要求保留变量、单位、引用号与公式。
- 提问时自动整理论文标题、页码、marker、原文摘录、当前解释和证据状态。
- 仅当某个已审阅内容确实使用实验测量数据，或存在明确但尚待核实的实验数据线索时，显示 **查实验数据来源** 操作。

默认构建阅读器时不会自动联网、下载数据或追踪全部参考文献。“查实验数据来源”只会准备一条范围明确的后续问题，并明确排除模拟结果、理论计算、模型输出、代码和仅来自文献的参数。

## 2.7.1 更新要点

- 阅读侧边栏与展开后的图表/公式教学共用同一个原文绑定对象，避免重复生成两套解释。
- 在第一次解释过程中完成 standard/full 分级教学检查；只有失败对象才定点修正。
- 记录可恢复 checkpoint、粗粒度墙钟分析阶段、定点返工时间及已知模型设置，不增加第二轮模型审读。
- 每篇论文只做短时内容与版式 smoke test；完整 UI 回归仅在界面或 schema 改变时运行。
- 记录审计触发原因和教学文字长度分布，仅用于诊断，不作为科学质量评分或硬性字数门槛。

## 安装

可以直接让 Codex 安装本仓库中的 `paper-reader` 目录：

```text
请从下面的 GitHub 目录安装 paper-reader Skill：
https://github.com/piggymon907/codex-paper-reader-skill/tree/main/paper-reader
```

也可以把 `paper-reader` 文件夹复制到：

```text
$CODEX_HOME/skills/paper-reader
```

手动复制后如果 Skill 没有立即出现，请重启或刷新 Codex。

仓库采用“根目录放用户说明、`paper-reader/` 放可安装 Skill”的结构，因此 Codex 可以直接安装子目录，而不会把仓库 README 和许可证复制进 Skill。

## 运行依赖

Codex Desktop 通常会提供所需的工作区运行环境。如果使用独立 Python 环境，请安装：

```bash
python -m pip install -r requirements.txt
```

PDF 提取流程还需要 `PATH` 中存在 Poppler 的 `pdftoppm` 命令。Skill 会优先使用 Codex 提供的 PDF 运行环境；如果依赖缺失，应明确报告，而不是静默切换到不可靠的工作流。

## 使用示例

附上科研 PDF 后，可以这样请求：

```text
请使用 $paper-reader 为这篇论文生成完整阅读器。详细解释每张图和关键公式；除非我另行要求，否则不要翻译。
```

如果阅读器已经生成，逐页翻译会走更快的补丁流程，不会重新构建或重新分析整篇论文。

## 输出

正常构建会生成以论文标题和版本号命名的目录，例如：

```text
Paper-Title-paper-reader-v2.7.1/
```

使用本地浏览器打开其中的 `index.html` 即可。输出是静态、可携带的；分享时需要保留完整目录结构。

## 范围与限制

- 结构验证会检查打包、证据绑定、文本质量和声明的覆盖范围，但不能证明科学解释本身一定正确。
- 默认证据范围仅包括用户实际提供的主 PDF 与补充材料。
- Skill 不会自动审查未提供的补充材料、数据集、代码、引用论文或全部参考文献。
- 正式引用、脆弱公式、优先权判断和后果重大的结论仍应回到原始 PDF 核对。
- PDF 提取质量因论文而异；不可靠文本应停止使用或隔离标记，不能作为可信正文展示。

## 隐私与联网行为

发布包不包含遥测。常规阅读器构建不会发起外部网络请求，所有阅读器文件保留在本地。只有用户主动触发后续问题时，Codex 才可能根据该问题查询特定实验数据来源；这不属于默认构建流程。

## 仓库结构

```text
paper-reader/
├── SKILL.md
├── agents/
├── assets/
├── references/
└── scripts/
```

仓库根目录只放面向用户的安装与许可说明；`paper-reader` 目录只包含 Skill 运行所需文件。

## 许可证

MIT，详见 [LICENSE](LICENSE)。

