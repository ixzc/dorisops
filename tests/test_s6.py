from __future__ import annotations

from pathlib import Path

from dorisops.cluster import load_cluster_yaml
from dorisops.inspect import inspect_cluster
from test_s5 import (
    CLOUD_YAML,
    READY_YAML,
    SHOW_BACKENDS,
    SHOW_COMPUTE_GROUPS,
    SHOW_FRONTENDS,
    FakeHttp,
    FakeMysql,
    _http,
    _write,
)

CLOUD_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "cluster.cloud.example.yaml"

MS_YAML = CLOUD_YAML + "\nmeta_service:\n  http_url: http://127.0.0.1:5000\n"

INTEGRATED_WITH_MS = READY_YAML + "\nmeta_service:\n  http_url: http://127.0.0.1:5000\n"

MS_HTML = "<html><body>MetaService brpc status</body></html>"


def _cloud_mysql() -> FakeMysql:
    return FakeMysql(
        {
            "SHOW FRONTENDS": SHOW_FRONTENDS.replace("false", "true"),
            "SHOW BACKENDS": SHOW_BACKENDS,
            "SHOW COMPUTE GROUPS": SHOW_COMPUTE_GROUPS,
        }
    )


def _http_with_ms() -> FakeHttp:
    http = _http()
    http.responses["http://127.0.0.1:5000/status"] = (200, MS_HTML)
    return http


def test_integrated_refuses_ms_even_if_yaml_has_url(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", INTEGRATED_WITH_MS))
    assert cfg.mode == "integrated"
    assert cfg.ms_http_url == "http://127.0.0.1:5000"
    http = _http_with_ms()
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})
    report = inspect_cluster(cfg, mysql=mysql, http=http)
    ms = next(p for p in report.probes if p.name == "MS /status")
    assert ms.skipped is True
    assert "当前是 integrated" in ms.detail
    assert "拒绝" in ms.detail
    assert not any("/status" in url for url in http.urls)
    cache = next(p for p in report.probes if p.name == "BE file_cache metrics")
    assert cache.skipped is True
    assert "当前是 integrated" in cache.detail
    assert not any(url.endswith(":8040/metrics") for url in http.urls)


def test_cloud_with_ms_returns_health(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", MS_YAML))
    assert cfg.mode == "cloud"
    http = _http_with_ms()
    report = inspect_cluster(cfg, mysql=_cloud_mysql(), http=http)
    assert "http://127.0.0.1:5000/status" in http.urls
    ms = next(p for p in report.probes if p.name == "MS /status")
    assert ms.ok and not ms.skipped
    assert "HTTP 200" in ms.detail
    assert "MetaService" in ms.detail
    assert "待人执行" not in ms.detail


def test_cloud_without_ms_is_pending_not_ok(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", CLOUD_YAML))
    http = _http_with_ms()
    report = inspect_cluster(cfg, mysql=_cloud_mysql(), http=http)
    ms = next(p for p in report.probes if p.name == "MS /status")
    assert ms.skipped is True
    assert "待人执行" in ms.detail
    text = report.to_text()
    assert "[OK] MS /status" not in text
    assert "[SKIP] MS /status" in text
    assert not any(url.endswith(":5000/status") for url in http.urls)


def test_cloud_filters_file_cache_metrics(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", MS_YAML))
    http = _http_with_ms()
    report = inspect_cluster(cfg, mysql=_cloud_mysql(), http=http)
    assert "http://127.0.0.1:8040/metrics" in http.urls
    cache = next(p for p in report.probes if p.name == "BE file_cache metrics")
    assert cache.ok and not cache.skipped
    assert "file_cache_hits" in cache.detail
    assert "doris_be_cpu" not in cache.detail
    assert "hit rate" not in cache.detail.lower() or "do not invent" in cache.detail


def test_cloud_file_cache_missing_lines_not_invented(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", CLOUD_YAML))
    http = FakeHttp(
        {
            "http://127.0.0.1:8030/api/health": (200, "OK"),
            "http://127.0.0.1:8030/metrics": (200, "fe 1"),
            "http://127.0.0.1:8040/api/health": (200, "OK"),
            "http://127.0.0.1:8040/metrics": (200, "doris_be_cpu 1\n"),
        }
    )
    report = inspect_cluster(cfg, mysql=_cloud_mysql(), http=http)
    cache = next(p for p in report.probes if p.name == "BE file_cache metrics")
    assert cache.ok
    assert "do not invent hit rate" in cache.detail


def test_cloud_example_parses_ms_url() -> None:
    cfg = load_cluster_yaml(CLOUD_EXAMPLE)
    assert cfg.mode == "cloud"
    assert cfg.ms_http_url == "http://127.0.0.1:5000"
    assert cfg.credentials_ready() is False
