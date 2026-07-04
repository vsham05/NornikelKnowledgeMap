"""Tests for Yandex API health / fallback routing."""

from infra.yandex_health import is_yandex_failure, mark_yandex_unusable, yandex_usable_cached, mark_yandex_usable


def test_is_yandex_failure_detects_auth_and_network():
    assert is_yandex_failure(Exception("Error 401 Unauthorized"))
    assert is_yandex_failure(Exception("connection timeout"))
    assert not is_yandex_failure(Exception("invalid json in model response"))


def test_usable_cache_flips_on_mark():
    mark_yandex_usable()
    assert yandex_usable_cached() is True
    mark_yandex_unusable("HTTP 403")
    assert yandex_usable_cached() is False
    mark_yandex_usable()
    assert yandex_usable_cached() is True
