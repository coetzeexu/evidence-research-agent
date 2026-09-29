"""Free data adapters. Network errors and empty datasets are distinct outcomes."""

import asyncio
import csv
import ipaddress
import json
import re
import socket
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import httpx
import pandas as pd
from bs4 import BeautifulSoup

from .domain import Bar, Instrument, MarketDataset, SourceRecord, digest, now_iso


class ProviderError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


async def get_public(
    url: str,
    params: dict | None = None,
    *,
    trust_env: bool = True,
    user_agent: str | None = "EvidenceResearch/0.1",
) -> httpx.Response:
    """Only called by fixed provider adapters, not by LLM-selected URLs."""
    async with httpx.AsyncClient(
        timeout=30, headers={"User-Agent": user_agent} if user_agent else {}, trust_env=trust_env
    ) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    retry = response.headers.get("Retry-After", "")
                    await asyncio.sleep(min(15, int(retry) if retry.isdigit() else 2 ** (attempt + 1)))
                    continue
                response.raise_for_status()
                if len(response.content) > 12_000_000:
                    raise ProviderError("Provider response exceeds size limit")
                return response
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise ProviderError("数据源连接超时或网络不可用", retryable=True) from None
                await asyncio.sleep(2**attempt)
            except httpx.HTTPStatusError as exc:
                raise ProviderError(
                    f"数据源 HTTP {exc.response.status_code}",
                    exc.response.status_code >= 500 or exc.response.status_code == 429,
                ) from None
    raise ProviderError("数据源请求失败")


def parse_yahoo(payload: dict, symbol: str, url: str, as_of: datetime | None = None) -> MarketDataset:
    as_of = as_of or datetime.now(timezone.utc)
    result = payload.get("chart", {}).get("result")
    if not result:
        raise ProviderError(f"未找到 {symbol} 的行情")
    data = result[0]
    meta = data["meta"]
    currency = meta.get("currency", "")
    if currency != "USD":
        raise ProviderError(f"{symbol} 为 {currency} 计价，当前版本需要美元序列；请明确指定美元代理")
    crypto = meta.get("instrumentType") == "CRYPTOCURRENCY"
    tz = meta.get("exchangeTimezoneName", "UTC")
    if not crypto and tz != "America/New_York":
        raise ProviderError(f"尚未支持 {symbol} 的交易日历 {tz}")
    instrument = Instrument(
        symbol=symbol,
        name=meta.get("longName", meta.get("shortName", symbol)),
        currency=currency,
        asset_type=meta.get("instrumentType", "EQUITY"),
        timezone=tz,
        calendar="24/7" if crypto else "XNYS",
        source_url=f"https://finance.yahoo.com/quote/{quote(symbol)}/history/",
        proxy_note="黄金（GLD ETF 代理），使用交易所价格而非现货报价" if symbol == "GLD" else None,
    )
    quotes = data.get("indicators", {}).get("quote", [{}])[0]
    adjusted = data.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    timestamps = data.get("timestamp", [])
    calendar = None
    if not crypto and timestamps:
        first = datetime.fromtimestamp(timestamps[0], timezone.utc).date() - timedelta(days=10)
        last = as_of.date() + timedelta(days=10)
        calendar = xcals.get_calendar("XNYS", start=str(first), end=str(last))
    bars, warnings, rejected, unfinished = [], [], 0, 0
    seen = set()
    for i, timestamp in enumerate(timestamps):
        opened = datetime.fromtimestamp(timestamp, timezone.utc)
        session = opened.astimezone(ZoneInfo(tz)).date() if not crypto else opened.date()
        if session in seen:
            raise ProviderError(f"{symbol} 包含重复交易日")
        seen.add(session)
        if crypto:
            closed = datetime.combine(session + timedelta(days=1), datetime.min.time(), timezone.utc)
        else:
            try:
                closed = calendar.session_close(pd.Timestamp(session)).to_pydatetime()
            except (ValueError, KeyError):
                rejected += 1
                continue
        if closed > as_of:
            unfinished += 1
            continue
        try:
            values = {key: quotes[key][i] for key in ["open", "high", "low", "close", "volume"]}
            if any(v is None for v in values.values()):
                raise ValueError("Missing field")
            adjusted_close = adjusted[i] if i < len(adjusted) and adjusted[i] is not None else values["close"]
            bars.append(
                Bar(
                    date=str(session),
                    opened_at=opened.isoformat(),
                    closed_at=closed.isoformat(),
                    adj_close=adjusted_close,
                    **values,
                )
            )
        except (ValueError, KeyError, IndexError, TypeError):
            rejected += 1
    if not bars:
        raise ProviderError(f"{symbol} 无可用完整日线")
    if rejected:
        warnings.append(f"{symbol} 排除 {rejected} 条缺失或无效 OHLCV，未插值补造价格")
    if rejected > max(3, len(timestamps) * 0.02):
        raise ProviderError(f"{symbol} 无效行情占比过高")
    if unfinished:
        warnings.append(f"{symbol} 排除 {unfinished} 条未完成日线")
    if not adjusted:
        warnings.append(f"{symbol} 缺少 adjusted close，收益仅使用提供商收盘价")
    content_hash = digest(payload)
    return MarketDataset(
        id=f"prices-{symbol}-{content_hash[:12]}",
        instrument=instrument,
        retrieved_at=now_iso(),
        source_url=url,
        content_hash=content_hash,
        bars=sorted(bars, key=lambda b: b.date),
        corporate_actions=data.get("events", {}),
        warnings=warnings,
    )


class YahooProvider:
    async def history(
        self, symbol: str, start: date, end: date, cache_dir: Path | None = None, refresh: bool = False
    ) -> MarketDataset:
        params = {
            "period1": int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()),
            "period2": int(
                datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()
            ),
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        base = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        cache = cache_dir / f"yahoo-{digest([symbol, params])[:24]}.json" if cache_dir else None
        if cache and cache.exists() and not refresh:
            age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
            if age < 6 * 3600:
                saved = MarketDataset.model_validate_json(cache.read_text())
                saved.warnings.append("使用六小时内行情缓存；采集时间保留为原始时间")
                return saved
        response = await get_public(base, params)
        dataset = parse_yahoo(response.json(), symbol, str(response.url))
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(dataset.model_dump_json())
        return dataset

    async def lookup(self, query: str) -> list[dict]:
        response = await get_public(
            "https://query1.finance.yahoo.com/v1/finance/search",
            {"q": query[:100], "quotesCount": 6, "newsCount": 0},
        )
        return [
            {k: row.get(k) for k in ["symbol", "shortname", "longname", "quoteType", "exchange"]}
            for row in response.json().get("quotes", [])
        ]


async def fred_series(series_id: str, start: date, end: date) -> tuple[list[dict], SourceRecord]:
    if series_id not in {"CPIAUCNS", "DGS3MO"}:
        raise ProviderError("未注册的宏观序列")
    response = await get_public(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        {"id": series_id},
        trust_env=False,
        user_agent=None,
    )
    reader = csv.DictReader(StringIO(response.text))
    if not reader.fieldnames or series_id not in reader.fieldnames:
        raise ProviderError("FRED 未返回预期 CSV")
    points = []
    for row in reader:
        try:
            observed = row[reader.fieldnames[0]]
            if str(start) <= observed <= str(end):
                points.append({"date": observed, "value": float(row[series_id])})
        except (ValueError, TypeError):
            continue
    if not points:
        raise ProviderError("FRED 序列为空")
    source = SourceRecord(
        id=f"fred-{series_id}",
        title=f"FRED · {series_id}",
        url=f"https://fred.stlouisfed.org/series/{series_id}",
        publisher="FRED",
        retrieved_at=now_iso(),
        content_hash=digest(points),
        excerpt="宏观历史序列；当前可获得版本，用于事后研究，不代表当时已知值。",
    )
    return points, source


async def hn_search(query: str, start: date, end: date, limit: int = 15) -> list[dict]:
    after = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())
    before = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp())
    response = await get_public(
        "https://hn.algolia.com/api/v1/search",
        {
            "query": query[:160],
            "tags": "story",
            "numericFilters": f"created_at_i>={after},created_at_i<{before}",
            "hitsPerPage": min(limit, 15),
        },
    )
    return [
        {
            "title": hit.get("title", ""),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "discussion_url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "discussion_at": hit.get("created_at"),
            "kind": "discovery",
        }
        for hit in response.json().get("hits", [])
    ]


async def web_search(query: str, limit: int = 6) -> list[dict]:
    from ddgs import DDGS

    def search():
        # No proxy rotation or challenge bypass. Backends follow their normal public search flow.
        with DDGS(timeout=15) as client:
            results = list(client.text(query[:250], max_results=min(limit, 8), backend="duckduckgo"))
            if not results:
                results = list(client.text(query[:250], max_results=min(limit, 8), backend="bing"))
            return results

    try:
        results = await asyncio.wait_for(asyncio.to_thread(search), timeout=25)
    except Exception:
        import xml.etree.ElementTree as ET

        try:
            response = await get_public(
                "https://www.bing.com/search", {"q": query[:250], "format": "rss", "setlang": "en-US"}
            )
            root = ET.fromstring(response.text)
            return [
                {
                    "title": item.findtext("title", ""),
                    "url": item.findtext("link", ""),
                    "snippet": item.findtext("description", "")[:450],
                    "kind": "discovery",
                }
                for item in root.findall(".//item")[:limit]
            ]
        except Exception:
            raise ProviderError(
                "免费网页检索暂不可用，可缩小查询或使用官方来源链接", retryable=True
            ) from None
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("href", ""),
            "snippet": item.get("body", "")[:450],
            "kind": "discovery",
        }
        for item in results
    ]


def public_target(url: str) -> tuple[str, str]:
    """Resolve and pin a public address so DNS cannot change between check and connection."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ProviderError("只允许公开 HTTP(S) 来源")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ProviderError("来源端口不允许")
    try:
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ProviderError("无法解析来源域名") from None
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ProviderError("拒绝非公开网络地址")
    selected = sorted(ips, key=lambda ip: ":" in ip)[0]
    host = f"[{selected}]" if ":" in selected else selected
    pinned = urlunsplit((parts.scheme, f"{host}:{port}", parts.path or "/", parts.query, ""))
    return pinned, parts.hostname


def publication_date(soup: BeautifulSoup) -> str | None:
    """Read publication metadata, never modified dates or related-story timestamps."""
    candidates = []
    for attrs in [
        {"property": "article:published_time"},
        {"name": "date"},
        {"itemprop": "datePublished"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(str(tag["content"]))
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in list(nodes):
            if isinstance(node, dict):
                nodes.extend(node.get("@graph", []))
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type", [])
            kinds = kind if isinstance(kind, list) else [kind]
            if set(kinds) & {"Article", "NewsArticle", "BlogPosting", "TechArticle"}:
                candidates.append(node.get("datePublished", ""))
    # Newsrooms often put this outside the article-body; keep it with the evidence.
    for node in soup.select(".article-date, time[itemprop=datePublished]"):
        candidates.append(node.get("datetime") or node.get_text(" ", strip=True))
    # A single entry header is publication evidence; body 'Update ...' text is not.
    entry_dates = soup.select("[data-permalink-context] > .mobile-date")
    if len(entry_dates) == 1:
        candidates.append(entry_dates[0].get_text(" ", strip=True))
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        raw = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw.strip(), flags=re.I)
        try:
            if len(raw) == 10:
                return date.fromisoformat(raw).isoformat()
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return stamp.isoformat() if stamp.tzinfo else stamp.date().isoformat()
        except ValueError:
            for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
                try:
                    return datetime.strptime(raw, fmt).date().isoformat()
                except ValueError:
                    pass
    return None


async def read_source(url: str) -> tuple[SourceRecord, str]:
    current = url
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        for _ in range(5):
            pinned, hostname = await asyncio.to_thread(public_target, current)
            async with client.stream(
                "GET",
                pinned,
                headers={"Host": hostname, "User-Agent": "EvidenceResearch/0.1"},
                extensions={"sni_hostname": hostname},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    current = urljoin(current, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                if not any(
                    t in response.headers.get("content-type", "") for t in ["text/", "application/xhtml"]
                ):
                    raise ProviderError("网页阅读工具仅接受文本内容")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 5_000_000:
                        raise ProviderError("来源正文超过读取限制")
                    chunks.append(chunk)
                raw = b"".join(chunks).decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else hostname
            published = publication_date(soup)
            for tag in soup.select("script,style,nav,footer,noscript,header[role=banner],header.site-header"):
                tag.decompose()
            candidates = soup.select(
                "main, [role=main], #content, .article-body, .article-content, .post-content, .content-body, article"
            )
            main = max(candidates, key=lambda node: len(node.get_text()), default=soup)
            # Some newsrooms use <article> for tiny related-story cards only.
            if len(main.get_text()) < 500:
                main = soup
            text = " ".join(main.stripped_strings)
            if len(text) < 300:
                raise ProviderError("页面正文不足，不能作为已核验来源")
            source = SourceRecord(
                id="src-" + digest(current)[:14],
                title=title[:250],
                url=current,
                publisher=hostname,
                retrieved_at=now_iso(),
                published_at=published,
                excerpt=" ".join(text.split()[:20])[:200],
                content_hash=digest(text),
            )
            return source, text[:16000]
    raise ProviderError("来源重定向次数超限")
