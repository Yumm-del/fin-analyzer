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
import io
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# ——— 修复 Windows GBK 编码问题 ———
# Python 在 Windows 中文系统上默认用 GBK 编码 stdout，
# 导致 emoji（✅⚠️❌等）输出时报 UnicodeEncodeError。
# 这里在模块加载时把 stdout/stderr 强制设为 UTF-8（兼容 CLI 和 Web）。
if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding:
    if sys.stdout.encoding.lower() in ('gbk', 'gb2312', 'gb18030', 'cp936'):
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace'
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding='utf-8', errors='replace'
            )
        except Exception:
            pass

# ——— 搜索相关 ———
# 用 requests 直接访问 DuckDuckGo HTML 页面，不依赖第三方搜索库
# 为什么不用 duckduckgo_search 库？它底层走 Bing，国内经常连不上
# 直接 HTTP 请求更可控，而且能自定义 headers 和超时策略
import requests
import re
SEARCH_AVAILABLE = True  # requests 是标准库级别的依赖，几乎一定可用

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
DEEPSEEK_MODEL = "deepseek-v4-pro"  # DeepSeek V4 Pro，推理能力强，适合金融分析

# 搜索配置
SEARCH_MAX_RESULTS = 5  # 每个维度返回的搜索结果数
SEARCH_TIMEOUT = 5      # 每次搜索超时秒数（国内网络环境缩短等待时间）

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

    # 未找到 API Key — 静默返回空字符串
    # 配置方法已写在 README 中，无需在代码层重复提示
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


def search_bing(query: str, max_results: int = SEARCH_MAX_RESULTS) -> list[SearchResult]:
    """
    在 Bing（必应）上搜索指定关键词。

    为什么加 Bing？
      DuckDuckGo 在国内经常被墙，但 cn.bing.com 在国内可以正常访问。
      Bing 是微软的搜索引擎，对中文搜索支持很好，
      而且搜索结果时效性高（会标注"1天前""3小时前"等）。

    原理：
      直接 HTTP GET 请求 cn.bing.com，解析 HTML 提取搜索结果。
      和 DuckDuckGo 搜索器一样，用正则解析，零额外依赖。

    参数：
        query: 搜索关键词（支持中文）
        max_results: 最多返回几条结果

    返回值：
        list[SearchResult] — 搜索结果列表
    """
    results: list[SearchResult] = []
    url = "https://www.bing.com/search"  # 全球 Bing（中文搜索质量优于 cn.bing.com）

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        response = requests.get(
            url,
            params={
                "q": query,
                "count": max_results,
                "setlang": "en",       # 使用全球版 Bing，搜索质量更好
            },
            headers=headers,
            timeout=SEARCH_TIMEOUT,
        )

        if response.status_code != 200:
            print(f"   ⚠️  Bing 返回 {response.status_code}，回退到 DuckDuckGo")
            return results

        html = response.text

        # Bing 的搜索结果在 <li class="b_algo"> 里
        # 每个 b_algo 包含：<a href="...">标题</a> 和 <p>摘要</p>
        algo_pattern = re.compile(
            r'<li class="b_algo"[^>]*>(.*?)</li>',
            re.DOTALL,
        )
        blocks = algo_pattern.findall(html)

        for block in blocks:
            if len(results) >= max_results:
                break

            # 提取链接和标题
            link_match = re.search(
                r'<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>',
                block, re.DOTALL,
            )
            if not link_match:
                continue

            href = link_match.group(1)
            # 标题中可能有 HTML 标签，去掉
            title = re.sub(r'<[^>]+>', '', link_match.group(2)).strip()

            # 跳过非 http 链接和 Bing 自身的链接
            if not href.startswith("http") or "bing.com" in href:
                continue

            # 提取摘要（<p> 标签中的文字）
            snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            snippet = ""
            if snippet_match:
                # 去掉 HTML 实体和标签
                raw = snippet_match.group(1)
                raw = raw.replace("&ensp;", " ").replace("&#0183;", "·")
                snippet = re.sub(r'<[^>]+>', '', raw).strip()

            if title and href:
                results.append(SearchResult(
                    title=title,
                    href=href,
                    body=snippet,
                ))

        if results:
            print(f"   ✅ Bing 搜索完成: {query[:40]}... ({len(results)} 条结果)")

    except requests.exceptions.Timeout:
        print(f"   ⏱️  Bing 搜索超时，回退到 DuckDuckGo")
    except requests.exceptions.ConnectionError:
        print(f"   🔌 Bing 连接失败，回退到 DuckDuckGo")
    except Exception as e:
        print(f"   ⚠️  Bing 搜索异常: {e}")

    return results


def _filter_relevant_results(
    results: list[SearchResult],
    query: str,
) -> list[SearchResult]:
    """
    过滤搜索结果中的垃圾/不相关内容。

    Bing 的反爬机制有时会返回完全不相关的结果（如淘宝、GitHub、
    天气网站等）。这个函数检查每条结果的标题和摘要是否与搜索关键词
    有任何关联，不相关的直接丢弃。

    PM 视角：
      与其给 LLM 一堆垃圾信息让它硬着头皮分析，
      不如直接告诉 LLM「搜索没找到有效信息」——
      LLM 基于训练数据的分析反而更靠谱。

    返回：
      过滤后的有效结果列表
    """
    # 明显是垃圾站点的域名黑名单
    spam_domains = [
        "worldtimebuddy.com", "qr-code-generator.com", "app-sorteos.com",
        "feimogames.com", "52fhz.com", "hanyuguoxue.com",
    ]
    # 明显非财经类域名的部分匹配（这些域名大概率返回了不相关内容）
    non_finance_keywords = [
        "github.com", "apple.com/app", "instagram", "youtube",
        "microsoft.com/powerpoint", "google.com/support",
        "taobao.com/list", "bilibili.com", "quark.cn",
        "xueersi.com", "douyin.com", "weixin.qq.com/filehelper",
        "sfr.fr", "aliyun.com", "ru.wikipedia.org",
    ]

    filtered: list[SearchResult] = []
    for r in results:
        # 检查是否来自垃圾站点
        is_spam = False
        for domain in spam_domains:
            if domain in r.href.lower():
                is_spam = True
                break
        if is_spam:
            continue

        # 检查是否明显非财经内容
        for kw in non_finance_keywords:
            if kw in r.href.lower():
                is_spam = True
                break
        if is_spam:
            continue

        # 通过检查
        filtered.append(r)

    if len(filtered) < len(results):
        print(f"   🧹 过滤掉 {len(results) - len(filtered)} 条不相关结果，"
              f"保留 {len(filtered)} 条")

    return filtered


def search_web(query: str, max_results: int = SEARCH_MAX_RESULTS) -> list[SearchResult]:
    """
    搜索指定关键词 — 优先使用 Bing（国内可用），失败时回退到 DuckDuckGo。

    搜索策略（PM 视角）：
      1. 先试 Bing ———— 国内网络可用，时效性高
      2. Bing 失败 → DuckDuckGo ———— 作为备用
      3. 都失败 → 返回空列表 ———— LLM 用训练数据分析（优雅降级）

    参数：
        query: 搜索关键词（支持中文）
        max_results: 最多返回几条结果

    返回值：
        list[SearchResult] — 搜索结果列表

    原理：
        直接向 DuckDuckGo 的 HTML 端点发送 POST 请求（模拟浏览器表单提交），
        然后解析返回的 HTML，提取标题、链接和摘要。
        这种方式不需要 API key，不需要第三方库，
        而且 DuckDuckGo 对中文搜索的支持也还不错。

        踩过的坑：
        · duckduckgo_search 库底层走 Bing，国内经常连不上（connection reset）
        · 直接用 HTTP 请求 DuckDuckGo HTML 页面，稳定性好很多
        · 加了 3 个备用域名，一个挂了自动切下一个
    """
    results: list[SearchResult] = []

    # ——— 优先使用 Bing（国内可用） ———
    bing_results = search_bing(query, max_results)

    # 过滤掉明显不相关的垃圾结果
    # Bing 有时会返回完全不相关的内容（被反爬干扰或搜索质量问题）
    bing_results = _filter_relevant_results(bing_results, query)
    if bing_results:
        return bing_results

    # ——— Bing 失败，回退到 DuckDuckGo ———
    results: list[SearchResult] = []

    # DuckDuckGo 的 HTML 端点（不需要 JS 渲染）
    # 备用域名列表 ———— 一个挂了就试下一个
    base_urls = [
        "https://html.duckduckgo.com/html/",
        "https://duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    for base_url in base_urls:
        try:
            # POST 请求模拟搜索表单提交
            # DuckDuckGo 的 HTML 版本通过 POST 表单接收搜索词
            response = requests.post(
                base_url,
                data={"q": query},
                headers=headers,
                timeout=10,
            )

            if response.status_code != 200:
                continue  # 这个域名不可用，试下一个

            html = response.text

            # ——— 解析搜索结果 ———
            # DuckDuckGo HTML 版本的结构：
            #   <a rel="nofollow" class="result-link" href="...">标题</a>
            #   <a class="result-snippet">摘要</a>
            #
            # 用正则提取，避免引入 BeautifulSoup 做额外依赖
            # 正则虽然不够优雅，但对于这种简单提取场景完全够用

            # 提取所有结果块（每个结果包含一个链接和一个摘要）
            # 用一个简单的策略：找到所有 result-link 和紧随其后的 snippet
            link_pattern = re.compile(
                r'<a[^>]*result-link[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            snippet_pattern = re.compile(
                r'<a[^>]*result-snippet[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )

            links = link_pattern.findall(html)
            snippets = snippet_pattern.findall(html)

            # 配对链接和摘要
            for i in range(min(len(links), max_results)):
                href = links[i][0] if isinstance(links[i], tuple) else links[i]
                title = links[i][1] if isinstance(links[i], tuple) else links[i]
                if isinstance(title, tuple):
                    title = title[0]

                # 清理 HTML 标签
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()

                if title and href:
                    results.append(SearchResult(
                        title=title,
                        href=href,
                        body=snippet,
                    ))

            if results:
                print(f"   ✅ 搜索完成: {query[:40]}... ({len(results)} 条结果)")
                return results  # 成功获取结果，直接返回

        except requests.exceptions.Timeout:
            print(f"   ⏱️  搜索超时 [{base_url[:30]}...]，尝试下一个…")
            continue
        except requests.exceptions.ConnectionError:
            print(f"   🔌 连接失败 [{base_url[:30]}...]，尝试下一个…")
            continue
        except Exception as e:
            print(f"   ⚠️  搜索异常 [{base_url[:30]}...]: {e}")
            continue

    # 所有域名都失败了 ———— 优雅降级
    print(f"   ⚠️  搜索不可用: {query[:40]}... ")
    print(f"      （网络搜索暂时不可用，将使用 LLM 训练数据中的知识进行分析）")
    return results


# ——— 东方财富数据接口 ———
# 行情 API 是公开接口，无需 API Key，国内可用且返回实时金融数据
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_SEARCH_URL = "https://searchadapter.eastmoney.com/api/suggest/get"


def _lookup_stock_code(company: str) -> dict | None:
    """
    通过东方财富搜索接口查找公司股票代码和基本信息。

    参数：
        company: 公司名称（如"宁德时代"）

    返回值：
        {"code": "300750", "name": "宁德时代", "market": "0", "type": "AStock"}
        找不到返回 None
    """
    try:
        import urllib.parse as ul_parse
        import urllib.request as ul_req

        params = ul_parse.urlencode({
            "input": company,
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": "3",
        })
        url = f"{EASTMONEY_SEARCH_URL}?{params}"

        req = ul_req.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        })
        with ul_req.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))

        items = (data.get("QuotationCodeTable", {}).get("Data", [])
                 if isinstance(data, dict) else [])

        for item in items:
            # 优先选 A 股（MarketType=2）
            name = item.get("Name", "")
            code = item.get("Code", "")
            market = item.get("MktNum", "0")
            stype = item.get("SecurityTypeName", "")

            if code and name:
                return {
                    "code": code,
                    "name": name,
                    "market": market,
                    "type": stype,
                    "secid": f"{market}.{code}",
                }

    except Exception as e:
        print(f"   ⚠️  股票代码查询失败: {e}")

    return None


def _get_financial_data(secid: str) -> dict:
    """
    通过东方财富行情 API 获取公司实时财务数据。

    参数：
        secid: 证券 ID，格式如 "0.300750"（market.code）

    返回值：
        dict，包含市值、PE、营收、净利润等核心财务指标。
        字段说明：
        - total_mcap: 总市值（元）
        - pe_dynamic: 动态市盈率
        - revenue: 营业总收入（元）
        - net_profit: 净利润（元）
        - roe: 净资产收益率(%)
        - revenue_growth: 营收同比增速(%)
        - net_profit_growth: 净利润同比增速(%)
        - gross_margin: 销售毛利率(%)
        - industry: 所属行业
        - total_shares: 总股本
    """
    fields = (
        "f57,f58,f84,f85,f100,f116,f117,"
        "f162,f164,f167,f169,f170,f171,f173,f175,f177,f183,"
        "f9,f12,f20,f21,f40,f41,f45"
    )
    field_map = {
        "f57": "code",
        "f58": "name",
        "f84": "total_shares",       # 总股本
        "f85": "circulating_shares", # 流通股本
        "f100": "industry",          # 行业
        "f116": "total_mcap",        # 总市值
        "f117": "circulating_mcap",  # 流通市值
        "f162": "pe_static",         # 静态市盈率
        "f164": "pe_dynamic",        # 动态市盈率
        "f167": "revenue",           # 营业总收入
        "f169": "net_profit",        # 净利润
        "f170": "net_profit_growth", # 净利润同比增速
        "f171": "nav_per_share",     # 每股净资产
        "f173": "roe",               # ROE
        "f175": "revenue_growth",    # 营收同比增速
        "f177": "gross_margin",      # 销售毛利率
        "f183": "dividend_yield",    # 股息率
    }

    try:
        import urllib.parse as ul_parse
        import urllib.request as ul_req
        import json as json_mod

        params = ul_parse.urlencode({"secid": secid, "fields": fields})
        url = f"{EASTMONEY_QUOTE_URL}?{params}"
        req = ul_req.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        })
        with ul_req.urlopen(req, timeout=5) as resp:
            raw_data = json_mod.loads(resp.read().decode("utf-8"))
        data = raw_data.get("data", {})
        if not data:
            return {}

        result = {}
        for field_key, field_name in field_map.items():
            val = data.get(field_key, "")
            if val and val != "-" and val is not None:
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    pass
                result[field_name] = val

        return result

    except Exception as e:
        print(f"   ⚠️  财务数据获取失败: {e}")
        return {}


def _format_financial_data(data: dict) -> str:
    """
    将财务数据格式化为 LLM prompt 中的结构化文本。

    对极大/极小值做人性化转换（元→亿元），方便 LLM 理解。
    """
    if not data:
        return "（未获取到实时财务数据）"

    def yuan_to_yi(val):
        """元转亿元，保留 2 位小数"""
        if val and isinstance(val, (int, float)) and abs(val) > 10000:
            return f"{val / 100_000_000:.2f} 亿元"
        return str(val) if val else "—"

    lines = ["| 指标 | 数值 |", "|------|------|"]
    rows = [
        ("公司名称", data.get("name", "—")),
        ("所属行业", data.get("industry", "—")),
        ("总市值", yuan_to_yi(data.get("total_mcap"))),
        ("市盈率(动)", f"{data['pe_dynamic']:.2f}" if data.get("pe_dynamic") else "—"),
        ("市盈率(静)", f"{data['pe_static']:.2f}" if data.get("pe_static") else "—"),
        ("营业总收入", yuan_to_yi(data.get("revenue"))),
        ("净利润", yuan_to_yi(data.get("net_profit"))),
        ("营收增速", f"{data['revenue_growth']:.2f}%" if data.get("revenue_growth") else "—"),
        ("净利润增速", f"{data['net_profit_growth']:.2f}%" if data.get("net_profit_growth") else "—"),
        ("ROE", f"{data['roe']:.2f}%" if data.get("roe") else "—"),
        ("毛利率", f"{data['gross_margin']:.2f}%" if data.get("gross_margin") else "—"),
        ("每股净资产", f"{data['nav_per_share']:.2f}" if data.get("nav_per_share") else "—"),
        ("股息率", f"{data['dividend_yield']:.2f}%" if data.get("dividend_yield") else "—"),
    ]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")

    return "\n".join(lines)


def _get_english_hint(company: str) -> str:
    """
    根据中文公司名返回英文搜索提示（英文名 + 股票代码）。

    为什么需要这个？
      Bing 的中文分词很差，"宁德时代"会被拆成"宁德"+"时代"，
      搜索结果全是宁德市旅游攻略。但加上"CATL 300750"后，
      Bing 能准确定位到宁德时代这家公司。

    PM 视角：
      这是一个「搜索质量修复」而非功能。用户不需要知道背后的机制，
      但有了它，搜索结果从"完全不相关"变成"精准命中"。

    后续优化方向：
      可以通过 API 动态查询公司英文名和股票代码，
      而不是依赖硬编码的映射表。
    """
    # 常见中国公司的中英文映射（后续可扩展或接入 API）
    hints = {
        "宁德时代": "CATL 300750",
        "比亚迪": "BYD 002594 1211.HK",
        "中国平安": "Ping An Insurance 601318",
        "贵州茅台": "Kweichow Moutai 600519",
        "招商银行": "China Merchants Bank 600036",
        "腾讯": "Tencent 0700.HK",
        "阿里巴巴": "Alibaba BABA 9988.HK",
        "美团": "Meituan 3690.HK",
        "京东": "JD.com 9618.HK",
        "百度": "Baidu 9888.HK",
        "小米": "Xiaomi 1810.HK",
        "网易": "NetEase 9999.HK",
        "工商银行": "ICBC 601398",
        "建设银行": "CCB 601939",
        "农业银行": "ABC 601288",
        "中国银行": "Bank of China 601988",
        "中国移动": "China Mobile 600941",
        "中国石油": "PetroChina 601857",
        "中国石化": "Sinopec 600028",
        "中国神华": "China Shenhua 601088",
        "中芯国际": "SMIC 688981",
        "海康威视": "Hikvision 002415",
        "美的集团": "Midea 000333",
        "格力电器": "Gree 000651",
        "万科": "Vanke 000002",
        "保利发展": "Poly 600048",
        "恒瑞医药": "Hengrui Medicine 600276",
        "药明康德": "WuXi AppTec 603259",
        "隆基绿能": "LONGi 601012",
        "阳光电源": "Sungrow 300274",
        "中兴通讯": "ZTE 000063",
        "科大讯飞": "iFlytek 002230",
        "三一重工": "Sany 600031",
        "海尔智家": "Haier 600690",
        "长城汽车": "Great Wall Motor 601633",
        "蔚来": "NIO NIO.US",
        "小鹏汽车": "XPeng XPEV.US",
        "理想汽车": "Li Auto LI.US",
        "拼多多": "Pinduoduo PDD.US",
        "网易有道": "NetEase Youdao DAO.US",
    }

    # 精确匹配
    if company in hints:
        return hints[company]

    # 模糊匹配——检查公司名是否包含已知的公司关键词
    for key, hint in hints.items():
        if key in company or company in key:
            return hint

    return ""  # 未知公司，只用中文搜索


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
    # 搜索关键词设计（PM 视角）：
    #   中英混合搜索——Bing 的中文分词很烂（会把"宁德时代"拆成"宁德"+"时代"），
    #   但加上英文名/股票代码后就能精准定位。英文术语也能帮 LLM 更好理解上下文。
    english_hint = _get_english_hint(company)
    queries = {
        "fundamentals": f'{company} {english_hint} 财报 营收 净利润 主营业务 2025',
        "news": f'{company} {english_hint} 最新 新闻 动态 2025 2026',
        "risks": f'{company} {english_hint} 风险 亏损 诉讼 争议',
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
    把搜索结果 + 实时财务数据拼装成给 LLM 的 prompt。

    数据来源优先级：
      1. 东方财富实时行情 ———— 市值、PE、营收、ROE 等硬指标
      2. Bing 网络搜索 ———— 新闻、动态、研报等软信息
      3. LLM 训练知识 ———— 作为补充（明确标注）

    参数：
        company: 公司名称
        search_results: 并行搜索的结果字典

    返回值：
        拼接好的 prompt 字符串
    """
    # ——— 获取实时财务数据 ———
    stock_info = _lookup_stock_code(company)
    financial_text = ""
    if stock_info:
        fin_data = _get_financial_data(stock_info["secid"])
        financial_text = _format_financial_data(fin_data)
        print(f"   📊 获取到 {stock_info['name']}({stock_info['code']}) 实时行情数据")

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

## 实时行情数据（来源：东方财富，数据实时更新）

{financial_text if financial_text else "（未获取到实时行情数据）"}

## 网络搜索信息

{fundamentals}

{news}

{risks}

请根据以上信息生成专业的金融分析简报。注意：
- **优先使用实时行情数据中的财务指标**（市值、PE、营收、ROE 等），这些是准确数据。
- 网络搜索结果可用于补充新闻动态和风险信息。
- 如果网络搜索信息不充分，用你的训练知识补充公司背景和行业分析。
- 无论哪种情况，都不要编造不存在的财务数据或新闻。不确定的信息标注「公开信息中暂未核实」。
- 不要给出「买入/卖出/持有」等投资建议。"""

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
        print("⚠️  网络搜索暂不可用，将使用 LLM 训练数据中的知识进行分析。")
        print("   （这是一个「优雅降级」设计——即使搜索失败，核心功能仍然可用）\n")
        # 不 return，继续执行 LLM 分析（利用 LLM 自身的训练知识）

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
