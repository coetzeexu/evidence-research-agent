import socket
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from research_app.config import Settings
from research_app.domain import Bar, ResearchSpec
from research_app.exporters import safe_json
from research_app.providers import ProviderError, parse_yahoo, public_target
from research_app.security import allowed_link, safe_error


def payload():
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "instrumentType": "CRYPTOCURRENCY",
                        "exchangeTimezoneName": "UTC",
                    },
                    "timestamp": [1704067200, 1704153600],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10, 11],
                                "high": [12, 12],
                                "low": [9, 10],
                                "close": [11, 11.5],
                                "volume": [100, 200],
                            }
                        ],
                        "adjclose": [{"adjclose": [11, 11.5]}],
                    },
                    "events": {"splits": {"x": {"splitRatio": "4:1"}}},
                }
            ]
        }
    }


def test_partial_crypto_daily_bar_is_excluded_and_not_readjusted():
    result = parse_yahoo(
        payload(), "BTC-USD", "https://example.com", datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    )
    assert len(result.bars) == 1
    assert result.bars[0].close == 11
    assert result.corporate_actions["splits"]
    assert any("未完成" in w for w in result.warnings)


def test_duplicate_and_nonusd_data_fail_closed():
    p = payload()
    p["chart"]["result"][0]["timestamp"][1] = 1704067200
    with pytest.raises(ProviderError, match="重复"):
        parse_yahoo(p, "BTC-USD", "https://example.com")
    p = payload()
    p["chart"]["result"][0]["meta"]["currency"] = "EUR"
    with pytest.raises(ProviderError, match="美元"):
        parse_yahoo(p, "ABC", "https://example.com")


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://user:pass@example.com", "https://example.com:8080", "ftp://example.com"],
)
def test_unsafe_source_protocols_rejected(url):
    with pytest.raises(ProviderError):
        public_target(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"])
def test_private_and_metadata_addresses_rejected(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(ProviderError, match="非公开"):
        public_target("https://example.com")


def test_public_dns_is_pinned(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    url, host = public_target("https://example.com/article?q=1")
    assert url == "https://93.184.216.34:443/article?q=1" and host == "example.com"


def test_html_embedded_data_cannot_end_script():
    out = safe_json({"title": "</script><script>alert(1)</script>"})
    assert "<" not in out
    import json

    assert json.loads(out)["title"].startswith("</script>")


def test_key_redaction_and_link_schemes(tmp_path):
    config = Settings(tmp_path, "test", "private-test-token", "https://example.com")
    out = safe_error(ValueError("private-test-token sk-fakekey0123456789"), config)
    assert "private-test-token" not in out and "sk-fakekey" not in out
    assert not allowed_link("javascript:alert(1)")
    assert not allowed_link("https://user:pass@example.com")


def test_weights_and_bar_invariants(spec):
    obj = spec.model_dump()
    obj["weights"] = [0.8, 0.8]
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(obj)
    with pytest.raises(ValidationError):
        Bar(
            date="2024-01-01",
            opened_at="",
            closed_at="",
            open=10,
            high=8,
            low=1,
            close=9,
            adj_close=9,
            volume=1,
        )


@pytest.mark.parametrize("symbols", ["GLD", [None], [123], None])
def test_malformed_symbols_rejected_as_validation_errors(spec, symbols):
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate({**spec.model_dump(), "symbols": symbols})


def test_publication_date_keeps_article_date_outside_body():
    from bs4 import BeautifulSoup
    from research_app.providers import publication_date

    soup = BeautifulSoup(
        '<div class="article-date">March 18, 2024</div><article>Announced today</article><span class="index-item-text-info-date">September 28, 2026</span>',
        "html.parser",
    )
    assert publication_date(soup) == "2024-03-18"


def test_publication_date_ignores_updated_and_related_schema_dates():
    from bs4 import BeautifulSoup
    from research_app.providers import publication_date

    soup = BeautifulSoup(
        """<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","datePublished":"2024-03-18T16:00:00-04:00","dateModified":"2025-01-01"},{"@type":"VideoObject","datePublished":"2026-01-01"}]}</script>""",
        "html.parser",
    )
    assert publication_date(soup) == "2024-03-18T16:00:00-04:00"
    assert (
        publication_date(
            BeautifulSoup('<meta property="article:modified_time" content="2026-01-01">', "html.parser")
        )
        is None
    )
