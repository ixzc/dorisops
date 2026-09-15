"""Optional L1 smoke against a real cluster. Never runs in default CI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dorisops.cluster import load_cluster_yaml
from dorisops.service import inspect_from_path

pytestmark = pytest.mark.live


def test_live_show_frontends() -> None:
    raw = os.environ.get("DORISOPS_LIVE_CLUSTER", "").strip()
    if not raw:
        pytest.skip("optional: set DORISOPS_LIVE_CLUSTER to a real read-only cluster.yaml")
    path = Path(raw)
    if not path.is_file():
        pytest.skip(f"cluster yaml not found: {path}")
    pytest.importorskip("pymysql")
    cfg = load_cluster_yaml(path)
    if not cfg.credentials_ready():
        pytest.skip("cluster.yaml still has placeholders; fill a read-only user to smoke L1")
    report, _code = inspect_from_path(path)
    assert report.level == "L1"
    fe = next(probe for probe in report.probes if probe.name == "SHOW FRONTENDS")
    assert fe.ok
    assert "Alive true=" in fe.detail or "Alive false=" in fe.detail
