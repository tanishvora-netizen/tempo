from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.security import Throttle
from tempo.optimize.options import ach_lead


def _request(ip: str) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_per_ip_limit() -> None:
    throttle = Throttle(limit=2, global_limit=100)
    throttle.check(_request("1.1.1.1"))
    throttle.check(_request("1.1.1.1"))

    with pytest.raises(HTTPException) as exc:
        throttle.check(_request("1.1.1.1"))

    assert exc.value.status_code == 429


def test_global_cap_stops_spoofed_ips() -> None:
    throttle = Throttle(limit=2, global_limit=3)
    for i in range(3):
        throttle.check(_request(f"10.0.0.{i}"))  # a client rotating X-Forwarded-For

    with pytest.raises(HTTPException):
        throttle.check(_request("10.0.0.99"))


def test_ach_lead_rule_is_shared() -> None:
    assert ach_lead(False, False) == 3
    assert ach_lead(True, False) == 4
    assert ach_lead(True, True) == 5 and ach_lead(False, True) == 5
