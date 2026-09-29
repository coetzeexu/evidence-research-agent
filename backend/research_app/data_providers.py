"""Server-selected adapters. Agent tools never load arbitrary modules or credentials."""

from dataclasses import dataclass
from datetime import date
from importlib.metadata import entry_points
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from . import providers as public
from .domain import MarketDataset, SourceRecord


@runtime_checkable
class MarketDataProvider(Protocol):
    async def history(
        self, symbol: str, start: date, end: date, cache_dir: Path | None = None, refresh: bool = False
    ) -> MarketDataset: ...

    async def lookup(self, query: str) -> list[dict]: ...


@runtime_checkable
class NewsDataProvider(Protocol):
    async def search(self, query: str, start: date, end: date, limit: int = 15) -> list[dict]: ...

    async def read(self, url: str) -> tuple[SourceRecord, str]: ...


@runtime_checkable
class MacroDataProvider(Protocol):
    async def series(self, series_id: str, start: date, end: date) -> tuple[list[dict], SourceRecord]: ...


@runtime_checkable
class DataProviderInterface(Protocol):
    market: MarketDataProvider
    news: Mapping[str, NewsDataProvider]
    macro: MacroDataProvider


@dataclass(frozen=True)
class DataProviders:
    market: MarketDataProvider
    news: Mapping[str, NewsDataProvider]
    macro: MacroDataProvider

    def validate(self):
        if not isinstance(self.market, MarketDataProvider) or not isinstance(self.macro, MacroDataProvider):
            raise ValueError("数据源缺少行情或宏观接口")
        if "web" not in self.news or not all(isinstance(p, NewsDataProvider) for p in self.news.values()):
            raise ValueError("数据源需提供 web 默认资讯接口；可追加其他已注册检索路由")
        return self


class PublicNews:
    def __init__(self, kind="web"):
        self.kind = kind

    async def search(self, query, start, end, limit=15):
        if self.kind == "hn":
            return await public.hn_search(query, start, end, limit)
        # DDG only supports discovery here; historical disclosure dates are verified from originals.
        return await public.web_search(query, min(limit, 6))

    async def read(self, url):
        return await public.read_source(url)


class FredMacro:
    async def series(self, series_id, start, end):
        return await public.fred_series(series_id, start, end)


def public_providers():
    return DataProviders(public.YahooProvider(), {"web": PublicNews(), "hn": PublicNews("hn")}, FredMacro())


def load_providers(config) -> DataProviders:
    profile = getattr(config, "provider_profile", "public")
    if profile == "public":
        return public_providers().validate()
    plugins = list(entry_points(group="evidence_research.providers", name=profile))
    if len(plugins) != 1:
        raise ValueError("服务端数据源配置不存在或重名；检查已安装 provider 插件")
    result = plugins[0].load()(config)
    if not isinstance(result, DataProviderInterface):
        raise ValueError("数据源插件必须实现 DataProviderInterface")
    return DataProviders(result.market, result.news, result.macro).validate()
