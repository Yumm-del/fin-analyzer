"""
Fin Analyzer — AI 金融分析 Web 界面
=====================================
基于 Streamlit 构建的浏览器端 AI 金融分析工具。
输入公司名称，自动搜索网络信息 + DeepSeek LLM 分析 → 生成结构化报告。

与 CLI 版（fin_analyzer.py）的关系：
  · 复用 CLI 版的核心函数（搜索、LLM 调用、报告存储）—— 不改原代码
  · 新增 Web 特有的交互：进度追踪、Markdown 渲染、历史浏览、一键导出
  · CLI 版仍可独立运行，Web 版是额外的「产品化」界面

架构（PM 视角）：
  用户输入 → Web 层（app.py）→ 业务层（fin_analyzer.py）
                                 ├── 搜索模块（DuckDuckGo，3 维度并行）
                                 ├── LLM 分析（DeepSeek API）
                                 └── 持久化（Markdown + JSON 日记）

为什么用 Streamlit？
  · Python 原生，零前端门槛 —— 不需要写 HTML/CSS/JS
  · 丰富的 UI 组件 —— 输入框、进度条、Markdown 渲染开箱即用
  · 免费云部署 —— Streamlit Community Cloud 一键部署到公网
"""

import streamlit as st
import sys
import os
import io
import json
import time
from datetime import datetime

# ——— 修复 Windows GBK 编码问题 ———
# fin_analyzer.py 的 print 语句中使用了 emoji（✅❌⚠️等），
# 在 Windows 中文系统上，Streamlit 捕获 stdout 时会因为 GBK 编码
# 无法处理 emoji 而崩溃。这里把 stdout/stderr 强制设为 UTF-8。
# 不影响 CLI 版（CLI 版直接用终端，不受此限制）。
if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'gb2312', 'gb18030', 'cp936'):
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace'
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace'
        )
    except Exception:
        pass  # 如果 stdout 已经被包装过，忽略

# ——— 路径配置：确保能导入同目录下的 fin_analyzer 模块 ———
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# 导入核心业务模块（fin_analyzer.py）
# 注意：模块导入时会执行顶层代码（加载 .env、检查依赖等），
# 打印信息会输出到控制台，不会显示在 Web UI 中
import fin_analyzer as fa

# ============================================================
# 页面基础配置
# ============================================================
st.set_page_config(
    page_title="Fin Analyzer · AI 金融分析",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Fin Analyzer v0.2 · AI 驱动的金融分析工具\n\n"
                 "输入公司名 → 自动搜索 → LLM 分析 → 结构化报告\n\n"
                 "Built with Streamlit + DeepSeek",
    },
)

# ============================================================
# 自定义 CSS 样式
# ============================================================
st.markdown("""
<style>
    /* ——— 整体字体优化 ——— */
    .stApp {
        font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
    }

    /* ——— 报告容器：卡片风格 ——— */
    .report-container {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 2rem;
        margin: 1rem 0;
    }

    /* ——— 风险等级标签 ——— */
    .risk-high { color: #dc2626; font-weight: bold; }
    .risk-medium { color: #d97706; font-weight: bold; }
    .risk-low { color: #16a34a; font-weight: bold; }

    /* ——— 页脚 ——— */
    .footer {
        text-align: center;
        color: #94a3b8;
        font-size: 0.85rem;
        margin-top: 3rem;
        padding: 1rem 0;
        border-top: 1px solid #e2e8f0;
    }

    /* ——— 状态卡片 ——— */
    .stat-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .stat-card .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #1e293b;
    }
    .stat-card .stat-label {
        font-size: 0.85rem;
        color: #64748b;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 工具函数
# ============================================================

def get_effective_api_key() -> str:
    """
    多来源获取 DeepSeek API Key（按优先级排列）。

    优先级设计（PM 视角）：
      1. 用户在侧边栏手动输入 ———— 最高优先级（临时使用，不落盘）
      2. Streamlit Secrets          ———— 用于云部署，安全存储
      3. 环境变量 / .env 文件       ———— 本地开发，复用 CLI 版配置

    为什么设计多来源？
      · 本地开发和云部署的配置方式不同
      · 不想强制用户在本地改代码或配置环境变量
      · 临时用户可以在 UI 中输入 key 直接体验
    """
    # ① 用户在侧边栏输入的 key（存储在 session_state 中）
    user_key = st.session_state.get("user_api_key", "").strip()
    if user_key:
        return user_key

    # ② Streamlit Secrets（云部署时在 TOML 中配置）
    try:
        secret_key = st.secrets.get("DEEPSEEK_API_KEY", "")
        if secret_key:
            return secret_key
    except Exception:
        pass  # 本地运行时 st.secrets 可能抛异常

    # ③ 复用 fin_analyzer 模块自身从 .env / 环境变量中获取的值
    return fa.DEEPSEEK_API_KEY


def load_journal() -> dict:
    """
    加载分析日记（JSON 格式）。

    日记结构：
      {
        "records": [
          {
            "company": "比亚迪",
            "timestamp": "2026-07-24T15:30:22",
            "report_preview": "...",
            "report_file": "比亚迪_20260724_153022.md"
          },
          ...
        ]
      }

    fin_analyzer 的 save_to_journal() 负责写入，
    这里只负责读取和展示。
    """
    try:
        with open(fa.JOURNAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"records": []}


def load_full_report(filename: str) -> str | None:
    """
    根据日记中记录的文件名，加载完整的 Markdown 报告。

    文件存储在 reports/ 目录下，文件名如「比亚迪_20260724_153022.md」。
    """
    report_path = os.path.join(fa.REPORT_DIR, os.path.basename(filename))
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, Exception):
        return None


def get_journal_stats() -> dict:
    """
    从分析日记中提取汇总统计数据。

    用于在首页展示「已分析 X 家公司」「共生成 Y 份报告」等指标。
    这些数据后续可以用于产品迭代的数据驱动决策。
    """
    journal = load_journal()
    records = journal.get("records", [])

    if not records:
        return {
            "total_analyses": 0,
            "unique_companies": 0,
            "latest_analysis": None,
            "today_count": 0,
        }

    companies = set(r["company"] for r in records)
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for r in records if r["timestamp"][:10] == today)

    return {
        "total_analyses": len(records),
        "unique_companies": len(companies),
        "latest_analysis": records[-1]["timestamp"],
        "today_count": today_count,
    }


# ============================================================
# 侧边栏 ———— 导航 + API Key 配置
# ============================================================

def render_sidebar() -> str:
    """
    渲染侧边栏，返回当前选中的页面名称。

    PM 设计思路：
      · 侧边栏承担两个功能：导航 + 配置
      · 导航用 radio 按钮（选项互斥），清晰直观
      · API Key 输入框始终可见，用户随时可以修改
      · 底部显示当前配置状态（有无 key、模型名称等）
    """
    with st.sidebar:
        # ——— Logo 区 ———
        st.markdown("""
        <div style="text-align: center; padding: 1rem 0;">
            <h1 style="font-size: 2rem; margin: 0;">📊</h1>
            <h2 style="font-size: 1.2rem; margin: 0.3rem 0; color: #1e293b;">
                Fin Analyzer
            </h2>
            <p style="font-size: 0.8rem; color: #94a3b8; margin: 0;">
                AI 驱动的金融分析
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # ——— 导航 ———
        st.markdown("### 📍 导航")

        # 用 radio 做页面切换（比 selectbox 更直观，所有选项一目了然）
        page = st.radio(
            "选择功能",
            options=["🔍 分析公司", "📖 历史记录", "ℹ️ 关于项目"],
            label_visibility="collapsed",
        )

        st.divider()

        # ——— API Key 配置区 ———
        st.markdown("### 🔑 API 配置")

        # 检查当前 key 状态
        current_key = get_effective_api_key()
        if current_key:
            st.success(f"✅ DeepSeek API 已配置", icon="✅")
            with st.expander("查看/修改 API Key"):
                user_key = st.text_input(
                    "DeepSeek API Key",
                    type="password",
                    value=current_key[:8] + "****" if len(current_key) > 8 else "",
                    placeholder="sk-...",
                    help="获取地址: https://platform.deepseek.com",
                    key="user_api_key_input",
                )
                # 只在用户主动修改时才更新（避免用掩码值覆盖真实 key）
                if user_key and "****" not in user_key:
                    st.session_state["user_api_key"] = user_key
        else:
            st.warning("⚠️ 未配置 API Key", icon="⚠️")
            user_key = st.text_input(
                "输入 DeepSeek API Key",
                type="password",
                placeholder="sk-xxxxxxxx...",
                help="获取地址: https://platform.deepseek.com\n\n"
                     "你的 key 仅保存在当前会话中，不会上传到服务器。",
                key="user_api_key_input",
            )
            if user_key:
                st.session_state["user_api_key"] = user_key
                st.success("Key 已保存到当前会话 ✓")
                st.rerun()

        # 获取 key 的指引
        with st.expander("💡 如何获取 API Key？"):
            st.markdown("""
            1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
            2. 注册账号（新用户送免费额度）
            3. 在「API Keys」页面创建 key
            4. 复制 key 粘贴到上方输入框
            """)

        # ——— 配置状态摘要 ———
        st.divider()
        st.markdown("### ⚙️ 运行状态")
        is_ready = bool(current_key) and fa.LLM_AVAILABLE
        st.metric(
            label="系统状态",
            value="🟢 就绪" if is_ready else "🔴 未就绪",
        )
        st.caption(f"模型: {fa.DEEPSEEK_MODEL}")
        st.caption(f"搜索: {'🟢 可用' if fa.SEARCH_AVAILABLE else '🔴 不可用'}")
        st.caption(f"LLM SDK: {'🟢 可用' if fa.LLM_AVAILABLE else '🔴 未安装'}")

    # 返回当前页面标识（用于主区域路由）
    page_map = {
        "🔍 分析公司": "analyze",
        "📖 历史记录": "history",
        "ℹ️ 关于项目": "about",
    }
    return page_map[page]


# ============================================================
# 页面一：分析公司
# ============================================================

def render_analyze_page():
    """
    核心功能页面 ———— 输入公司名 → 搜索 → 分析 → 展示报告。

    用户流程（UX 设计）：
      1. 输入公司名称或股票代码
      2. 点击「开始分析」
      3. 系统依次执行：搜索（并行 3 维度）→ LLM 分析 → 保存报告
      4. 每个阶段都有实时进度提示
      5. 分析完成后展示完整 Markdown 报告
      6. 提供下载按钮
    """
    st.title("🔍 AI 金融分析")

    # ——— 输入区 ———
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        company = st.text_input(
            "输入公司名称或股票代码",
            placeholder="例如：比亚迪、宁德时代、Apple、TSLA……",
            label_visibility="collapsed",
            key="company_input",
        )
    with col2:
        # 快速模式：跳过搜索，直接用 LLM 训练数据分析
        # 在国内 DuckDuckGo 常被墙，开启此模式可节省 ~15-30s 的超时等待
        fast_mode = st.checkbox(
            "⚡ 快速模式",
            value=True,
            help="跳过网络搜索，直接用 LLM 训练数据分析。\n"
                 "国内网络环境下建议开启，可节省 15-30 秒。\n"
                 "LLM 训练数据截止到 2025 年底，时效性略差。"
        )
    with col3:
        analyze_clicked = st.button(
            "🚀 开始分析",
            type="primary",
            use_container_width=True,
            disabled=not bool(get_effective_api_key()),
        )

    # API Key 未配置时的引导
    if not get_effective_api_key():
        st.info(
            "👈 **请先在左侧边栏配置 DeepSeek API Key**\n\n"
            "API Key 仅用于调用 DeepSeek 进行金融分析，不会保存到服务器。"
        )
        return

    # ——— 快捷示例 ———
    if not company and not analyze_clicked:
        st.markdown("##### 💡 试试这些公司")
        example_cols = st.columns(4)
        examples = ["比亚迪", "宁德时代", "Apple", "特斯拉"]
        for i, example in enumerate(examples):
            with example_cols[i]:
                if st.button(example, key=f"example_{example}", use_container_width=True):
                    st.session_state["company_input"] = example
                    st.rerun()

    # ——— 分析流程 ———
    if analyze_clicked and company:
        execute_analysis(company, fast_mode)
    elif analyze_clicked and not company:
        st.warning("请输入公司名称或股票代码。")


def execute_analysis(company: str, fast_mode: bool = True):
    """
    执行完整的分析流程：搜索 → LLM 分析 → 展示 → 保存。

    参数：
        company: 公司名称
        fast_mode: True = 跳过网络搜索，直接用 LLM 训练数据分析（快 15-30s）

    PM 思考：
        DuckDuckGo 在国内经常不可用，每次搜索超时浪费用户时间。
        与其让用户干等，不如默认开启"快速模式"跳过搜索，
        让 LLM 用训练数据直接分析——牺牲一点时效性，换来流畅的体验。
        用户需要最新信息时可以关掉快速模式。
    """
    # 同步 API Key 到 fin_analyzer 模块（CLI 版从环境变量读，
    # Web 版需要从 session_state / secrets 注入）
    fa.DEEPSEEK_API_KEY = get_effective_api_key()

    # 用 st.status 替代 st.spinner，展示多步骤进度
    with st.status(f"正在分析「{company}」……", expanded=True) as status:
        # ——— Step 1: 搜索（快速模式下跳过） ———
        if fast_mode:
            st.write("⚡ **快速模式** ——— 跳过网络搜索，使用 LLM 训练知识")
            search_results = {"fundamentals": [], "news": [], "risks": []}
            search_duration = 0
            total_results = 0
        else:
            st.write("🔍 **搜索网络信息** ——— 基本面 / 最新动态 / 风险……")
            search_start = time.time()
            search_results = fa.parallel_search(company)
            search_duration = time.time() - search_start
            total_results = sum(len(v) for v in search_results.values())

        if fast_mode:
            st.write("   ⚡ 使用 LLM 训练数据分析（训练数据截止 2025 年底）")
        elif total_results > 0:
            st.write(f"   ✅ 搜索完成！耗时 {search_duration:.1f}s，获取 {total_results} 条结果")
        else:
            st.write("   ⚠️ 网络搜索暂不可用，将使用 LLM 训练数据中的知识")

        # ——— Step 2: LLM 分析 ———
        st.write("🤖 **AI 分析中** ——— 调用 DeepSeek 生成结构化报告……")

        # 调试：确认 API Key 已正确传递
        current_key = fa.DEEPSEEK_API_KEY
        if not current_key:
            status.update(label="未配置 API Key ❌", state="error")
            st.error(
                "**未检测到 API Key。**\n\n"
                "请确认已在左侧边栏「🔑 API 配置」中输入 DeepSeek API Key。\n"
                "如果已输入但仍然报错，请刷新页面后重新输入。"
            )
            return

        st.write(f"   🔑 使用 Key: {current_key[:10]}...（已脱敏）")
        report = fa.analyze_company(company, search_results)

        if report is None:
            status.update(label="分析失败 ❌", state="error")
            st.error(
                "LLM 分析失败。可能的原因：\n\n"
                "1. **API Key 无效或已过期** → 检查 [DeepSeek 控制台](https://platform.deepseek.com)\n"
                "2. **API 额度用完了** → 新用户有免费额度，检查余额\n"
                "3. **网络连接问题** → DeepSeek API 可能连接不稳定\n"
                "4. **Key 格式错误** → 确保是完整的 `sk-` 开头字符串，没有多余空格\n\n"
                "请检查后刷新页面重试。"
            )
            return

        # ——— Step 3: 保存 ———
        st.write("📁 **保存报告**……")
        filepath = fa.save_report_markdown(company, report)
        fa.save_to_journal(company, report)

        status.update(label=f"「{company}」分析完成 ✅", state="complete")

    # ——— 展示报告 ———
    st.divider()
    st.markdown("## 📊 分析报告")

    # 用卡片式容器包裹报告，视觉上更清晰
    with st.container(border=True):
        st.markdown(report)

    # ——— 操作区 ———
    st.divider()
    op_col1, op_col2 = st.columns(2)

    with op_col1:
        # 下载报告按钮
        st.download_button(
            label="📥 下载 Markdown 报告",
            data=report,
            file_name=f"{company}_分析报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with op_col2:
        if st.button("🔄 再分析一次", use_container_width=True):
            st.rerun()

    # 原始 Markdown 文本（可展开查看 + 手动复制）
    with st.expander("📋 查看/复制原始 Markdown"):
        st.code(report, language="markdown")
        st.caption("上方代码块右上角有复制按钮，点击即可复制全文。")

    # 保存路径提示
    st.caption(f"📁 报告已保存至: `{filepath}`")
    st.caption("💡 报告同时保存为 Markdown 文件和 JSON 日记，可在「历史记录」页面查看。")


# ============================================================
# 页面二：历史记录
# ============================================================

def render_history_page():
    """
    历史分析记录页面 ———— 展示所有过往分析，支持查看详情。

    功能：
      · 概览区：分析总次数、公司数、今日分析数
      · 列表区：按时间倒序展示所有分析记录
      · 详情区：点击任意记录展开完整报告
      · 搜索：按公司名筛选历史记录
    """
    st.title("📖 历史记录")

    journal = load_journal()
    records = journal.get("records", [])

    if not records:
        # ——— 空状态 ———
        st.info(
            "📭 还没有分析记录。\n\n"
            "去「🔍 分析公司」页面开始你的第一次 AI 金融分析吧！"
        )
        return

    # ——— 概览统计 ———
    stats = get_journal_stats()
    stat_cols = st.columns(4)
    with stat_cols[0]:
        with st.container(border=True):
            st.metric("📊 分析总次数", stats["total_analyses"])
    with stat_cols[1]:
        with st.container(border=True):
            st.metric("🏢 分析公司数", stats["unique_companies"])
    with stat_cols[2]:
        with st.container(border=True):
            st.metric("📅 今日分析", stats["today_count"])
    with stat_cols[3]:
        with st.container(border=True):
            latest = stats["latest_analysis"][:10] if stats["latest_analysis"] else "—"
            st.metric("🕐 最近分析", latest)

    st.divider()

    # ——— 搜索筛选 ———
    search_term = st.text_input(
        "🔎 按公司名筛选",
        placeholder="输入公司名快速查找……",
    )

    # 倒序展示（最新的在前）
    display_records = list(reversed(records))
    if search_term:
        display_records = [
            r for r in display_records
            if search_term.lower() in r["company"].lower()
        ]

    if not display_records:
        st.info(f"没有找到包含「{search_term}」的分析记录。")
        return

    st.caption(f"共 {len(display_records)} 条记录")

    # ——— 记录列表 ———
    for i, record in enumerate(display_records):
        company = record["company"]
        timestamp = record["timestamp"]
        preview = record.get("report_preview", "")[:120]
        report_file = record.get("report_file", "")

        # 每条记录一个可展开的容器
        with st.expander(f"📄 {company} — {timestamp}", expanded=(i == 0)):
            st.caption(f"报告文件: {report_file}")

            # 加载完整报告
            full_report = load_full_report(report_file)
            if full_report:
                with st.container(border=True):
                    st.markdown(full_report)

                # 下载按钮
                st.download_button(
                    label="📥 下载此报告",
                    data=full_report,
                    file_name=report_file,
                    mime="text/markdown",
                    key=f"download_{i}",
                )
            else:
                # 完整报告文件可能已被删除或移动
                st.warning("完整报告文件未找到。以下为日记中的预览摘要：")
                st.markdown(preview)


# ============================================================
# 页面三：关于项目
# ============================================================

def render_about_page():
    """
    关于项目页面 ———— 介绍技术栈、设计思路、迭代计划。

    这个页面有两层作用：
      1. 给用户：了解这个工具能做什么、怎么做的
      2. 给面试官：展示你的产品设计思路和技术理解
    """
    st.title("ℹ️ 关于 Fin Analyzer")

    # ——— 产品简介 ———
    st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 2rem; border-radius: 12px; margin-bottom: 2rem;">
        <h2 style="margin: 0 0 0.5rem 0; color: white;">📊 Fin Analyzer</h2>
        <p style="font-size: 1.1rem; margin: 0; opacity: 0.95;">
            AI 驱动的金融分析工具<br>
            输入公司名 → 自动搜索 + LLM 分析 → 结构化报告
        </p>
        <p style="font-size: 0.85rem; margin: 1rem 0 0 0; opacity: 0.8;">
            v0.2 · Built with Streamlit + DeepSeek · MIT License
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ——— 三栏：工作流程 ———
    st.markdown("### 🔄 工作流程")
    flow_cols = st.columns(4)
    steps = [
        ("🔍", "搜索", "并行搜索 3 个维度\n（基本面/动态/风险）"),
        ("🤖", "分析", "DeepSeek LLM\n生成结构化报告"),
        ("📊", "展示", "Web / Markdown\n美观展示报告"),
        ("📁", "存档", "自动保存报告\n随时回溯历史"),
    ]
    for i, (icon, title, desc) in enumerate(steps):
        with flow_cols[i]:
            st.markdown(f"""
            <div style="text-align: center; padding: 1rem;">
                <div style="font-size: 2rem;">{icon}</div>
                <div style="font-weight: bold; margin: 0.3rem 0;">{title}</div>
                <div style="font-size: 0.85rem; color: #64748b;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)
            if i < 3:
                st.markdown("→", help="")  # 箭头（Streamlit 没有很好的内联箭头方案）

    st.divider()

    # ——— 技术架构 ———
    st.markdown("### 🏗️ 技术架构")
    st.markdown("""
    ```
    ┌─────────────────────────────────────────┐
    │           用户界面（Web / CLI）           │
    │   Streamlit（Web） / 终端（CLI）          │
    ├─────────────────────────────────────────┤
    │              业务逻辑层                   │
    │   · 搜索模块 — DuckDuckGo 并行搜索        │
    │   · 分析模块 — DeepSeek LLM 调用          │
    │   · 存储模块 — Markdown + JSON 日记       │
    ├─────────────────────────────────────────┤
    │              基础设施                     │
    │   Python 3.10+ · Streamlit · OpenAI SDK  │
    └─────────────────────────────────────────┘
    ```
    """)

    # ——— AI PM 设计思路 ———
    st.markdown("### 💡 AI 产品设计思路")

    design_points = [
        ("🛡️ 防幻觉策略", "System prompt 中强制要求标注信息来源 URL，"
                        "搜索不到的信息标注「公开信息中暂未查到」，"
                        "从产品层而非模型层控制幻觉风险。"),
        ("📐 输出一致性", "用固定的 Markdown 模板（四模块结构）约束 LLM 输出格式，"
                        "比让 LLM 自由发挥更可控，也便于后续做批量分析。"),
        ("⏱️ 用户体验", "并行搜索三个维度（基本面/动态/风险），"
                      "将原本 9 秒的串行等待压缩到 3 秒。"
                      "Web 版用多步骤进度条替代简单的 spinner，"
                      "给用户「掌控感」。"),
        ("🔄 优雅降级", "如果网络搜索不可用（国内网络波动），"
                      "自动 fallback 到 LLM 训练数据，"
                      "核心功能不断——这是 PM 的「容错设计」思维。"),
        ("📦 数据资产沉淀", "每次分析都保存为 Markdown 文件 + JSON 日记，"
                         "不只是用完即弃的工具，而是积累分析数据资产。"
                         "未来可以做趋势分析、行业对比等衍生功能。"),
        ("🎯 用户分层", "CLI 版给技术用户（开发者、量化研究员），"
                      "Web 版给非技术用户（投资爱好者、金融从业者），"
                      "同一个核心引擎，不同界面形态——这是产品化的思路。"),
    ]

    for title, desc in design_points:
        with st.expander(title):
            st.write(desc)

    # ——— 迭代路线 ———
    st.divider()
    st.markdown("### 🗺️ 版本迭代路线")

    roadmap = [
        ("v0.1 ✅", "CLI 基础版", "单公司分析 + 终端预览 + Markdown 存档"),
        ("v0.2 ✅", "Web 界面", "Streamlit 浏览器端 + 历史记录 + 报告下载"),
        ("v0.3 🔜", "多公司对比", "同时分析多家公司，横向对比风险与动态"),
        ("v0.4 🔜", "数据可视化", "matplotlib / Plotly 生成走势图与风险雷达图"),
        ("v1.0 🎯", "完整产品", "用户系统 + 分析历史分析 + 行业对比 + 报告导出 PDF"),
    ]

    for version, title, desc in roadmap:
        cols = st.columns([1, 2, 5])
        with cols[0]:
            st.markdown(f"**{version}**")
        with cols[1]:
            st.markdown(f"*{title}*")
        with cols[2]:
            st.caption(desc)

    # ——— 页脚 ———
    st.markdown("""
    <div class="footer">
        Fin Analyzer · AI 驱动的金融分析工具 · Built with ❤️<br>
        <a href="https://gitee.com/yumm-del--pure-delight/fin-analyzer" target="_blank">
            Gitee 仓库
        </a>
        ·
        <a href="https://platform.deepseek.com" target="_blank">DeepSeek API</a>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# 主程序入口
# ============================================================

def main():
    """
    Streamlit 应用主入口。

    执行流程：
      1. 渲染侧边栏 → 获取当前页面
      2. 同步 API Key 到 fin_analyzer 模块
      3. 根据导航路由到对应页面

    Streamlit 的特性：
      每次用户交互（点击按钮、输入文字等）都会重新执行整个脚本。
      但 st.session_state 会持久化，module 缓存也会保留。
      这就是为什么侧边栏的 API Key 输入可以跨页面保持。
    """
    # 同步 API Key（每次 rerun 都执行，确保使用最新的 key）
    effective_key = get_effective_api_key()
    if effective_key:
        fa.DEEPSEEK_API_KEY = effective_key
        # 同时设置环境变量，确保所有代码路径都能读到
        os.environ["DEEPSEEK_API_KEY"] = effective_key

    # 渲染侧边栏并获取当前页面
    current_page = render_sidebar()

    # ——— 页面路由 ———
    if current_page == "analyze":
        render_analyze_page()
    elif current_page == "history":
        render_history_page()
    elif current_page == "about":
        render_about_page()


if __name__ == "__main__":
    main()
