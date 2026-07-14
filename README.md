# 🤖 AI 金融分析 Agent

> Python 手写的 AI 金融分析工具：输入公司名，自动搜索网络信息 + 调用 DeepSeek 大模型，生成结构化分析报告。
> 这是我从 AI 产品经理视角出发，独立设计并实现的一个「AI + 金融」产品原型。

---

## 一句话介绍

输入「比亚迪」或「002594」，Agent 会：
1. 🔍 并行搜索三个维度的网络信息（基本面 / 最新动态 / 风险）
2. 🤖 调用 DeepSeek 大模型进行结构化分析
3. 📊 输出一份包含公司概况、近期动态、风险提示、一句话总结的专业简报

---

## 🚀 快速开始

```bash
# 1. 克隆仓库
git clone https://gitee.com/yumm-del--pure-delight/fin-analyzer.git
cd fin-analyzer

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python fin_analyzer.py
```

首次运行会提示输入 DeepSeek API Key（获取地址：https://platform.deepseek.com），可选择保存到 `.env` 文件，下次自动读取。

---

## 📋 功能

- 🔍 **智能搜索** — 自动搜索三个维度的网络信息，并行执行
- 🤖 **LLM 分析** — 调用 DeepSeek 进行深度分析，prompt 中包含防幻觉、来源标注等设计
- 📊 **结构化报告** — 固定四模块输出（公司概况、近期动态、风险提示、一句话总结）
- 📁 **自动存档** — 报告保存为 Markdown 文件，同时写入 JSON 分析日记

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
| Python | 主语言，约 600 行 |
| duckduckgo_search | 免费网络搜索（无需 API Key） |
| openai SDK | 调用 DeepSeek API |
| concurrent.futures | 多线程并行搜索加速 |
| dataclass + JSON | 数据模型 & 分析日记持久化 |
| Prompt Engineering | 角色设定、约束条件、输出模板 |

---

## 📂 项目结构

```
fin-analyzer/
├── fin_analyzer.py          ← 主程序
├── requirements.txt         ← Python 依赖
├── README.md               ← 项目文档
├── .gitignore              ← 排除 .env 等敏感文件
├── versions/               ← 历史版本
│   └── v0.1_basic.py       ← 第一版
└── reports/                ← 生成的分析报告存档
```

---

## 🔄 版本演进

```
v0.1 ────────→ v0.2（计划）──→ v0.3（计划）
搜索 + LLM     并行搜索优化    多公司对比
               结构化报告      数据可视化
                              （matplotlib）
```

---

## 🎯 AI 产品经理求职方向

这个项目展示了以下 AI PM 核心能力：

- **AI 产品设计**：从用户痛点出发设计功能，而非堆砌技术
- **Prompt Engineering**：结构化 system prompt，约束输出质量
- **产品迭代思维**：渐进式版本演进（v0.1 → v0.2 → v0.3）
- **技术理解力**：能用 Python 独立验证想法，能与工程师有效沟通
- **用户视角**：考虑等待体验（并行搜索）、一致性（输出模板）、信任问题（来源标注）

---

## 📄 License

MIT
