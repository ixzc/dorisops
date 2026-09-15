import pytest


@pytest.fixture(autouse=True)
def _clear_sop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORISOPS_SOP", raising=False)
