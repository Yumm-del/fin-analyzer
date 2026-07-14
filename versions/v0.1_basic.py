"""
AI 金融分析 Agent v0.1 ———— 基础版（单次搜索 + LLM 分析）
============================================================
功能演进：
  v0.1：单次搜索 + DeepSeek 分析 + 终端报告
  v0.2（计划）：并行搜索 + 结构化 Markdown 报告
  v0.3（计划）：多公司对比 + 数据可视化（matplotlib）

技术栈：
  · duckduckgo_search — 免费网络搜索
  · openai SDK       — 调用 DeepSeek API
  · concurrent        — 并行搜索加速
  · dataclass + JSON  — 数据模型 & 报告持久化

架构设计思路：
  用户输入公司名 → 并行搜索 3 个维度（基本面/动态/风险）
  → 拼成一段 prompt → 发给 DeepSeek → 解析结构化报告
  → 终端预览 + 自动保存 Markdown

新手友好说明：
  这个项目的核心思路和你的 tarot-cli 一模一样：
  tarot 是「抽牌 → 保存日记 → 可视化」
  这里是 「搜索 → 调用 LLM → 输出报告」
  只是数据来源从本地牌库换成了互联网 + 大模型。
"""

import os
import sys
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# ——— 搜索相关 ———
# duckduckgo_search 是一个免费的网络搜索库，不需要 API key
# 原理：它模拟浏览器向 DuckDuckGo 发送搜索请求，解析返回的 HTML
try:
    from duckduckgo_search import DDGS
    SEARCH_AVAILABLE = True
except ImportError:
    SEARCH_AVAILABLE = False
    print("⚠️  duckduckgo_search 未安装。搜索功能不可用。")
    print("   请运行: pip install duckduckgo_search")

# ——— LLM API 相关 ———
# DeepSeek 的 API 完全兼容 OpenAI SDK，只需要改 base_url 即可
try:
    from openai import OpenAI
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    print("⚠️  openai 库未安装。LLM 分析功能不可用。")
    print("   请运行: pip install openai")

# ——— 环境变量 ———
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


# ============================================================
# 第〇部分：配置 & API Key 管理
# ============================================================

# DeepSeek API 配置
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"  # V3 模型，性价比最高

# 搜索配置
SEARCH_MAX_RESULTS = 5  # 每个维度返回的搜索结果数
SEARCH_TIMEOUT = 10     # 每次搜索超时秒数

# 报告保存路径（和 tarot-cli 的 JOURNAL_PATH 一样的设计）
REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
JOURNAL_PATH = os.path.join(os.path.dirname(__file__), "analysis_journal.json")


def _get_api_key() -> str:
    """
    获取 DeepSeek API Key。

    查找顺序：
        1. 环境变量 DEEPSEEK_API_KEY
        2. 项目根目录下的 .env 文件
        3. 如果都没有 → 交互式输入并保存到 .env

    原理：
        永远不要 hardcode API key 在代码里！这样即使代码公开到 GitHub，
        你的 key 也不会泄露。.env 文件已在 .gitignore 中排除。
    """
    # 方法 1：环境变量
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if api_key:
        return api_key

    # 方法 2：.env 文件
    if DOTENV_AVAILABLE:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                return api_key

    # 方法 3：交互式输入
    print("\n🔑 未找到 DeepSeek API Key。")
    print("   如果你还没有，去 https://platform.deepseek.com 注册获取（免费）。")
    api_key = input("   请输入你的 DeepSeek API Key → ").strip()

    if api_key:
        # 询问是否保存
        save = input("   是否保存到 .env 文件以便下次使用？(y/n) → ").strip().lower()
        if save == "y":
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"DEEPSEEK_API_KEY={api_key}")
            print(f"   ✅ 已保存到 {env_path}")
        return api_key

    print("❌ 未提供 API Key，LLM 分析功能不可用。")
    return ""


# 全局 API key（模块加载时获取一次）
DEEPSEEK_API_KEY = _get_api_key()


# ============================================================
# 第一部分：数据模型
# ============================================================
# 和 tarot-cli 的 TarotCard / DrawRecord 一样，
# 用 @dataclass 定义数据结构，用 asdict() 做 JSON 序列化。


@dataclass
class SearchResult:
    """一条搜索结果的模型"""
    title: str          # 搜索结果标题
    href: str           # 链接地址
    body: str           # 摘要


@dataclass
class AnalysisReport:
    """一份完整的分析报告"""
    company: str                # 公司名称
    timestamp: str              # 分析时间（ISO 格式）
    risk_level: str             # 风险等级：🔴高 / 🟡中 / 🟢低
    overview: str               # 一、公司概况
    recent_news: list[dict]     # 二、近期动态 [{属性, 内容, 来源}]
    risks: list[dict]           # 三、核心风险 [{名称, 等级, 分析, 依据}]
    summary: str                # 四、一句话总结
    raw_report: str             # 原始 Markdown 报告（完整版）


# ============================================================
# 第二部分：搜索模块
# ============================================================
# 原理：用 duckduckgo_search 库向 DuckDuckGo 发送搜索请求，
# 免费、不需要 API key、返回标题+链接+摘要。
#
# 为什么用 DuckDuckGo 而不是 Google？
#   · Google 搜索 API 要钱，而且需要科学上网
#   · DuckDuckGo 免费、国内能用、返回结果质量不差
#   · 对于公司基本面/新闻这类公开信息，DuckDuckGo 完全够用


def search_web(query: str, max_results: int = SEARCH_MAX_RESULTS) -> list[SearchResult]:
    """
    在 DuckDuckGo 上搜索指定关键词。

    参数：
        query: 搜索关键词（支持中文）
        max_results: 最多返回几条结果

    返回值：
        list[SearchResult] — 搜索结果列表，每条包含标题/链接/摘要

    原理：
        DDGS().text() 内部发送 HTTP 请求到 DuckDuckGo，
        解析返回的 HTML 页面，提取搜索结果。
        它模拟了你在浏览器里输入搜索词的整个过程。
    """
    if not SEARCH_AVAILABLE:
        print(f"   ⚠️  搜索不可用，跳过: {query[:40]}...")
        return []

    results: list[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    href=r.get("href", ""),
                    body=r.get("body", ""),
                ))
        print(f"   ✅ 搜索完成: {query[:40]}... ({len(results)} 条结果)")
    except Exception as e:
        print(f"   ❌ 搜索失败: {query[:40]}... — {e}")

    return results


def parallel_search(company: str) -> dict[str, list[SearchResult]]:
    """
    并行搜索三个维度的信息。

    为什么用并行而不是串行？
        串行：搜基本面(3秒) → 搜动态(3秒) → 搜风险(3秒) = 9秒
        并行：三个同时搜 = 3秒（等最慢的那个）

    原理：
        ThreadPoolExecutor 创建一个线程池，每个线程独立执行一次搜索。
        因为搜索是 I/O 密集型操作（大部分时间在等网络返回），
        Python 的 GIL 对它的影响不大，多线程能有效加速。

    参数：
        company: 公司名称

    返回值：
        {"fundamentals": [...], "news": [...], "risks": [...]}
    """
    queries = {
        "fundamentals": f"{company} 公司基本面 主营业务 财报 2025 2026",
        "news": f"{company} 最新动态 新闻 2026",
        "risks": f"{company} 风险 负面 亏损 诉讼 争议",
    }

    results: dict[str, list[SearchResult]] = {}

    # ThreadPoolExecutor 会自动管理线程的创建和销毁
    # max_workers=3 表示最多同时运行 3 个线程
    with ThreadPoolExecutor(max_workers=3) as executor:
        # 一次性提交三个搜索任务
        future_to_key = {
            executor.submit(search_web, query): key
            for key, query in queries.items()
        }
        # as_completed 会按完成顺序（而不是提交顺序）返回结果
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"   ❌ 搜索线程异常 [{key}]: {e}")
                results[key] = []

    return results


# ============================================================
# 第三部分：LLM 分析模块
# ============================================================
# 把搜索结果拼成一段结构化的 prompt，发给 DeepSeek，
# 让它生成一份专业的分析报告。
#
# 这里的设计核心是「prompt 工程」：
#   · 角色设定 → 告诉 LLM "你是谁"
#   · 约束条件 → 告诉 LLM "什么能做、什么不能做"
#   · 输出模板 → 让每次输出结构一致


SYSTEM_PROMPT = """# Role（角色）
你是一位资深的金融分析师，拥有 10 年以上的行业研究经验。
你的分析风格：客观、结构化、风险意识强、语言通俗易懂。

# Constraints（重要约束）
1. 严格基于提供的搜索结果进行分析，不要使用你自己的知识编造信息
2. 如果某个维度的搜索结果不充分，标注「公开信息中暂未查到」，绝对不要编造
3. 每条事实性信息需要能够追溯到搜索结果中的具体来源
4. 不要给出「买入/卖出/持有」等投资建议
5. 风险分级标准：
   - 🔴 高风险：可能对公司经营产生重大负面影响的事件
   - 🟡 中风险：需要持续关注的不确定性因素
   - 🟢 低风险：影响有限的常规经营风险
6. 语言精简，每个部分控制在合理长度内，让普通投资者也能看懂

# Output Format（严格按此格式输出，使用 Markdown）
---
## 📊 [公司名] · 金融分析简报
🏷️ **风险等级**：[🔴高 / 🟡中 / 🟢低]风险

## 一、公司概况
- **行业**：[行业分类]
- **主营业务**：[核心业务，2-3 句话]
- **近期大事**：[过去 3 个月内最重要的 1-2 个事件]

## 二、近期动态
| 属性 | 动态内容 | 来源/时间 |
|------|---------|----------|
| 🟢利好 | ... | ... |
| 🔴风险 | ... | ... |
| ➖中性 | ... | ... |

（列出 3-6 条动态，覆盖利好/利空/中性三个维度）

## 三、核心风险提示
1. **[风险名称]** — [🔴高 / 🟡中 / 🟢低]
   - 具体情况：...
   - 影响分析：...

（至少列出 3 条风险，按严重程度从高到低排列）

## 四、一句话总结
[用通俗语言，一句话概括当前该公司的核心投资关注点]
---
⚡ *本分析基于网络公开信息自动生成。*
⚠️ *免责声明：本内容由 AI 生成，仅供参考，不构成任何投资建议。投资有风险，决策须谨慎。*
"""


def _build_analysis_prompt(company: str, search_results: dict[str, list[SearchResult]]) -> str:
    """
    把搜索结果拼装成给 LLM 的 prompt。

    参数：
        company: 公司名称
        search_results: 并行搜索的结果字典

    返回值：
        拼接好的 prompt 字符串
    """
    # 把搜索结果格式化为文本
    def format_results(results: list[SearchResult], label: str) -> str:
        if not results:
            return f"### {label}\n（未搜索到相关信息）\n"
        lines = [f"### {label}"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   摘要：{r.body}")
            lines.append(f"   来源：{r.href}")
            lines.append("")
        return "\n".join(lines)

    fundamentals = format_results(search_results.get("fundamentals", []), "基本面/主营业务")
    news = format_results(search_results.get("news", []), "最新动态/新闻")
    risks = format_results(search_results.get("risks", []), "风险/负面信息")

    user_prompt = f"""请分析以下公司：**{company}**

以下是网络搜索获取的信息：

{fundamentals}

{news}

{risks}

请根据以上信息，严格按照输出格式要求，生成一份专业的金融分析简报。"""

    return user_prompt


def analyze_company(company: str, search_results: dict[str, list[SearchResult]]) -> str | None:
    """
    调用 DeepSeek API 对公司进行分析。

    参数：
        company: 公司名称
        search_results: 搜索结果字典

    返回值：
        LLM 生成的分析报告（Markdown 格式），失败返回 None

    原理：
        使用 OpenAI SDK 连接 DeepSeek API。
        DeepSeek 的 API 完全兼容 OpenAI 格式，所以不需要特殊适配。
        只需把 base_url 改为 https://api.deepseek.com 即可。
    """
    if not LLM_AVAILABLE:
        print("❌ openai 库未安装，无法调用 LLM。")
        return None

    if not DEEPSEEK_API_KEY:
        print("❌ 未配置 DeepSeek API Key，无法调用 LLM。")
        return None

    user_prompt = _build_analysis_prompt(company, search_results)

    print(f"\n🤖 正在调用 DeepSeek 分析「{company}」……")
    print("   （根据搜索信息量，可能需要 10-30 秒）\n")

    try:
        # 创建 OpenAI 客户端，但指向 DeepSeek 的服务器
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )

        # 调用 Chat Completion API
        # temperature=0.3 让输出更稳定（金融分析不需要创意性）
        # max_tokens=4096 确保报告不会被截断
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        # 提取 LLM 返回的文本
        report = response.choices[0].message.content
        print("✅ 分析完成！")
        return report

    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        return None


# ============================================================
# 第四部分：报告保存 & 管理
# ============================================================
# 和 tarot-cli 的日记系统一样：JSON 持久化 + Markdown 存档。


def save_report_markdown(company: str, report: str) -> str:
    """
    将分析报告保存为 Markdown 文件。

    参数：
        company: 公司名（用于生成文件名）
        report: Markdown 格式的分析报告

    返回值：
        保存的文件路径

    文件名示例：比亚迪_20260714_153022.md
    """
    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{company}_{timestamp}.md"
    filepath = os.path.join(REPORT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath


def save_to_journal(company: str, report: str) -> None:
    """
    将分析摘要追加到分析日记（JSON 格式）。

    和 tarot-cli 的 tarot_journal.json 一样的设计——
    每条记录是一个 JSON 对象，方便后续做统计或可视化。
    """
    # 读取已有日记
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            journal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        journal = {"records": []}

    # 追加新记录
    journal["records"].append({
        "company": company,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "report_preview": report[:500] + "……" if len(report) > 500 else report,
        "report_file": f"{company}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
    })

    # 写回文件
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2, ensure_ascii=False)


def show_journal_summary() -> None:
    """显示历史分析记录（和 tarot-cli 的日记概览一样）"""
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            journal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("\n📭 还没有分析记录。去分析一家公司开始吧！")
        return

    records: list[dict] = journal.get("records", [])
    if not records:
        print("\n📭 还没有分析记录。")
        return

    print(f"\n📖 历史分析记录 ———— 共 {len(records)} 条")
    print("─" * 60)
    for i, rec in enumerate(reversed(records[-10:]), 1):  # 最近 10 条
        ts = rec["timestamp"]
        company = rec["company"]
        report_file = rec.get("report_file", "未保存")
        print(f"  [{i}] {ts}  |  {company}  |  📄 {report_file}")
    print("─" * 60)


# ============================================================
# 第五部分：终端预览
# ============================================================


def display_report(company: str, report: str) -> None:
    """在终端中展示分析报告"""
    print("\n" + "=" * 60)
    print(f"  📊 {company} · 金融分析简报")
    print("=" * 60)
    print(report)
    print("=" * 60)


# ============================================================
# 第六部分：交互式 CLI 菜单
# ============================================================


def show_welcome() -> None:
    """欢迎信息"""
    print("""
╔══════════════════════════════════════════════╗
║     🤖  AI 金融分析 Agent  v0.1              ║
║     Fin Analyzer  —  智能搜索 + LLM 分析      ║
╚══════════════════════════════════════════════╝
    """)
    print("输入任意公司名称或股票代码，AI 会自动搜索网络信息")
    print("并生成一份结构化的金融分析简报。")
    print(f"📁 报告存档: {REPORT_DIR}")
    print(f"📖 分析日记: {JOURNAL_PATH}\n")


def show_menu() -> str:
    """显示主菜单"""
    print("─" * 46)
    print("  请选择功能：")
    print("  [1]  分析一家公司      — 输入公司名，生成分析报告")
    print("  [2]  历史记录          — 查看过去的分析报告")
    print("  [3]  关于这个项目      — 了解技术栈和设计思路")
    print("  [0]  退出")
    print("─" * 46)
    return input("  输入数字选择 → ").strip()


def menu_analyze() -> None:
    """功能 1：分析公司 ———— 整个程序的核心流程"""
    print("\n📌 分析公司")
    company = input("  请输入公司名称或股票代码 → ").strip()

    if not company:
        print("⚠️  输入为空，已取消。")
        return

    # Step 1：并行搜索（这里是最耗时的步骤）
    print(f"\n🔍 正在搜索「{company}」的相关信息……\n")
    start_time = time.time()
    search_results = parallel_search(company)
    search_duration = time.time() - start_time

    total_results = sum(len(v) for v in search_results.values())
    print(f"\n📊 搜索耗时 {search_duration:.1f} 秒，共获取 {total_results} 条结果。")

    if total_results == 0:
        print("⚠️  未搜索到任何信息。请检查公司名称是否正确，或检查网络连接。")
        return

    # Step 2：LLM 分析
    report = analyze_company(company, search_results)

    if report is None:
        print("❌ 分析失败。请检查 API Key 配置和网络连接。")
        return

    # Step 3：终端预览
    display_report(company, report)

    # Step 4：保存
    filepath = save_report_markdown(company, report)
    save_to_journal(company, report)
    print(f"\n📁 报告已保存: {filepath}")
    print(f"📖 已加入分析日记。")

    # Step 5：使用提示
    print(f"\n💡 提示：你可以打开 {filepath} 查看完整报告，")
    print(f"   或用浏览器查看（支持 Markdown 渲染）。")


def menu_about() -> None:
    """关于这个项目"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║              关于 AI 金融分析 Agent                           ║
╚══════════════════════════════════════════════════════════════╝

  这个项目的核心思路：

  1. 🔍 搜索模块
     用 duckduckgo_search 免费搜索三个维度：
     · 公司基本面（主营业务、财报、行业地位）
     · 最新动态（新闻、公告、重大事件）
     · 风险信息（负面新闻、诉讼、争议）
     三个搜索并行执行，耗时约等于最慢的那一个。

  2. 🤖 分析模块
     把搜索结果拼成一段 prompt，调用 DeepSeek API。
     system prompt 设定了角色（金融分析师）、约束（不编造、
     标注来源）、输出格式（四个固定模块）。

  3. 📊 输出模块
     · 终端直接展示报告
     · 自动保存为 Markdown 文件
     · 追加到 JSON 分析日记（方便后续做数据分析）

  技术栈：
  · Python 3.10+
  · duckduckgo_search（免费网络搜索）
  · openai SDK（调用 DeepSeek API）
  · concurrent.futures（并行搜索加速）

  AI PM 视角的思考：
  · 「防幻觉」：强制要求标注来源，无来源要声明
  · 「输出一致性」：用结构化模板约束 LLM 输出
  · 「用户体验」：并行搜索减少等待时间
  · 「数据资产」：每次分析都存档，可做后续分析
""")


# ============================================================
# 第七部分：主循环
# ============================================================


def main() -> None:
    """程序入口 ———— 和 tarot-cli 的设计一模一样"""
    show_welcome()

    while True:
        choice = show_menu()
        match choice:
            case "1":
                menu_analyze()
            case "2":
                show_journal_summary()
            case "3":
                menu_about()
            case "0":
                print("\n👋 再见！你的分析报告已存档，随时可以回来看。\n")
                break
            case _:
                print("\n⚠️  请输入 0-3 之间的数字\n")


if __name__ == "__main__":
    main()
