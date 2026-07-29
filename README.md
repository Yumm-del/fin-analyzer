# 🤖 AI 金融分析 Agent

> Python 手写的 AI 金融分析工具：输入公司名，自动搜索网络信息 + 调用 DeepSeek 大模型，生成结构化分析报告。
> 这是我从 AI 产品经理视角出发，独立设计并实现的一个「AI + 金融」产品原型。

---

## 🌐 在线体验（Web 版）

如果你不想安装任何东西，可以直接在浏览器中使用：

👉 **公网地址**：[部署后填入你的 Hugging Face / Streamlit Cloud 地址]

也可以本地启动 Web 版：

```bash
pip install -r requirements.txt
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`，即可使用完整功能。

> Web 版与 CLI 版共享同一套核心引擎，只是换了一个更友好的界面形态。

---

## 一句话介绍

输入「比亚迪」或「002594」，Agent 会：
1. 🔍 并行搜索三个维度的网络信息（基本面 / 最新动态 / 风险）
2. 🤖 调用 DeepSeek 大模型进行结构化分析
3. 📊 输出一份包含公司概况、近期动态、风险提示、一句话总结的专业简报

---

## 🚀 CLI 版快速开始

```bash
# 1. 克隆仓库
git clone https://gitee.com/yumm-del--pure-delight/fin-analyzer.git
cd fin-analyzer

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行 CLI 版（终端交互）
python fin_analyzer.py

# 4. 或运行 Web 版（浏览器交互）
streamlit run app.py
```

首次运行前，在项目根目录创建 `.env` 文件：

```
DEEPSEEK_API_KEY=你的密钥
```

获取地址：https://platform.deepseek.com（免费注册即送额度）

> Web 版也可以在侧边栏直接输入 API Key，无需创建 .env 文件。

---

## 📋 功能

- 🔍 **智能搜索** — 自动搜索三个维度的网络信息（基本面/动态/风险），并行执行
- 🤖 **LLM 分析** — 调用 DeepSeek 进行深度分析，内置防幻觉、来源标注等产品设计
- 📊 **结构化报告** — 固定四模块输出（公司概况、近期动态、风险提示、一句话总结）
- 📁 **自动存档** — 报告保存为 Markdown，同时写入 JSON 分析日记
- 🌐 **双界面** — CLI 版（终端）给技术用户；Web 版（浏览器）给非技术用户
- 📖 **历史回溯** — Web 版支持查看、搜索、下载过往分析记录

---

## 🏗️ 产品设计思路

这个 Agent 从产品视角出发，重点解决了三个问题：

### 1. 防幻觉机制
LLM 会编造不存在的财务数据。解决方案：prompt 中强制要求每条信息标注来源，搜索不到的信息标注「公开信息中暂未查到」。

### 2. 输出一致性
如果不约束格式，每次分析的结果结构会完全不同。解决方案：用一个详细的 Markdown 模板作为 system prompt 的输出约束。

### 3. 用户等待体验
串行搜索三个维度要等很久。解决方案：用 Python 多线程并行搜索，耗时约等于最慢的那个。

---

## 🧠 技术栈

| 技能 | 具体应用 |
|------|---------|
| Python | 主语言，CLI 版约 600 行 + Web 版约 500 行 |
| Streamlit | Web UI 框架（浏览器端交互） |
| DuckDuckGo | 免费网络搜索（直接 HTTP 请求，无需 API Key） |
| openai SDK | 调用 DeepSeek API（兼容 OpenAI 格式） |
| concurrent.futures | 多线程并行搜索加速 |
| dataclass + JSON | 数据模型 & 分析日记持久化 |
| Prompt Engineering | 角色设定、约束条件、输出模板 |

---

## 📂 项目结构

```
fin-analyzer/
├── fin_analyzer.py          ← CLI 版主程序（核心引擎）
├── app.py                   ← Web 版主程序（Streamlit 界面）
├── requirements.txt         ← Python 依赖
├── README.md               ← 项目文档
├── DEPLOY.md               ← 部署指南（HuggingFace / Streamlit Cloud）
├── .gitignore              ← 排除 .env、报告文件等
├── .streamlit/
│   └── config.toml         ← Streamlit 主题配置
├── versions/               ← 历史版本
│   └── v0.1_basic.py       ← 第一版
├── demo/
│   ├── sample_report.md    ← 示例分析报告
│   └── pitfalls.md         ← 踩坑记录（产品思考）
├── portfolio/              ← 作品集材料（PRD、竞品体验报告等）
└── reports/                ← 生成的分析报告存档
```

---

## 🔄 版本演进

- **v0.1** ✅ — CLI 基础版：搜索 + LLM 分析，终端预览，Markdown 存档
- **v0.2** ✅ — Web 界面：Streamlit 版上线，历史记录 + 报告下载
- **v0.3** 🔜 — 多公司对比 + 数据可视化 + 风险雷达图
- **v1.0** 🎯 — 完整产品：用户系统 + PDF 导出 + 行业分析

---

## 💡 产品设计思考

这个项目尝试从 AI 产品视角出发，而非单纯堆砌技术：

- **用户痛点驱动**：普通投资者面对海量信息不知从何看起——Agent 做的是「筛选 + 结构化」，而不是替人决策
- **防幻觉设计**：AI 会编造数据，所以 prompt 里强制要求来源标注，搜不到的就说「暂未查到」
- **优雅降级**：外部搜索服务不可用时，自动 fallback 到模型知识，核心功能不中断
- **输出一致性**：用结构化模板约束 LLM，避免每次分析格式不同——跟写 PRD 验收标准一个道理
- **渐进式迭代**：v0.1 先跑通核心链路，v0.2 优化搜索，v0.3 加可视化——不追求一步到位

---

## 📄 License

MIT
