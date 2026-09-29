from dataclasses import replace
from types import SimpleNamespace

import pytest
from research_app.config import Settings
from research_app.data_providers import DataProviders, load_providers, public_providers
from research_app.pipeline import Pipeline
from research_app.storage import Store


def test_default_and_installed_provider_profiles(monkeypatch, tmp_path):
    from research_app import data_providers as module

    config = Settings(tmp_path, "", "", "https://example.com")
    default = load_providers(config)
    assert set(default.news) == {"web", "hn"}
    plugin = public_providers()
    called = []

    def factory(cfg):
        called.append(cfg.provider_profile)
        return plugin

    def entries(**filters):
        assert filters == {"group": "evidence_research.providers", "name": "licensed"}
        return [SimpleNamespace(load=lambda: factory)]

    monkeypatch.setattr(module, "entry_points", entries)
    selected = load_providers(replace(config, provider_profile="licensed"))
    assert selected.market is plugin.market and called == ["licensed"]
    monkeypatch.setattr(module, "entry_points", lambda **kwargs: [])
    with pytest.raises(ValueError, match="不存在"):
        load_providers(replace(config, provider_profile="unregistered"))
    monkeypatch.setattr(
        module, "entry_points", lambda **kwargs: [SimpleNamespace(load=lambda: lambda cfg: object())]
    )
    with pytest.raises(ValueError, match="DataProviderInterface"):
        load_providers(replace(config, provider_profile="bad"))


async def test_pipeline_collect_uses_injected_market_and_macro_without_network(monkeypatch, tmp_path, bundle):
    from research_app import pipeline as module

    class Runtime:
        def __init__(self, *args):
            pass

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    history_calls, macro_calls = [], []

    class Market:
        async def history(self, symbol, start, end, cache_dir=None, refresh=False):
            history_calls.append((symbol, refresh))
            return bundle.datasets[symbol]

        async def lookup(self, query):
            return [{"symbol": "GLD"}]

    class Macro:
        async def series(self, series_id, start, end):
            macro_calls.append(series_id)
            return [{"date": str(end), "value": 100}], bundle.sources[0]

    defaults = public_providers()
    providers = DataProviders(Market(), defaults.news, Macro())
    cfg = Settings(tmp_path, "", "", "https://example.com")
    store = Store(tmp_path)
    rid = store.create("injected provider", refresh=True, export_reports=False)
    job = Pipeline(cfg, store, rid, providers=providers)
    assert job.runtime.providers is providers
    await job.collect({"spec": bundle.spec.model_dump(mode="json")})
    assert {s for s, refresh in history_calls if refresh} == {*bundle.spec.symbols, bundle.spec.benchmark}
    assert set(macro_calls) == {"CPIAUCNS", "DGS3MO"}
    assert set(job.read("collection.json")["datasets"]) == set(bundle.datasets)


async def test_public_news_keeps_date_filters_and_secure_reader(monkeypatch):
    from research_app import providers as module

    calls = []

    async def hn(query, start, end, limit):
        calls.append((query, start, end, limit))
        return [{"url": "https://example.com/news", "kind": "discovery"}]

    async def reader(url):
        raise ValueError("secure reader rejected URL")

    monkeypatch.setattr(module, "hn_search", hn)
    monkeypatch.setattr(module, "read_source", reader)
    p = public_providers()
    assert (await p.news["hn"].search("launch", "start", "end", 3))[0]["kind"] == "discovery"
    assert calls == [("launch", "start", "end", 3)]
    with pytest.raises(ValueError, match="rejected"):
        await p.news["web"].read("http://127.0.0.1")
