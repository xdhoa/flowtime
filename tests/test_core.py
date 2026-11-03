import pytest

from flowtime.core import HttpError, request_fields, safe_url, timestamp, validate_settings, vi_datetime

GOOD_SETTINGS = {"timezone": "Asia/Ho_Chi_Minh", "weekdays": [1], "start": 9, "end": 18,
                 "lunchStart": 12, "lunchEnd": 13, "buffer": 15, "busy": []}


def test_script_links_are_blocked():
    with pytest.raises(HttpError):
        safe_url("javascript:alert(1)")
    assert safe_url("https://example.com/doc") == "https://example.com/doc"
    assert safe_url("") == ""


def test_invalid_dates_are_blocked():
    with pytest.raises(HttpError):
        request_fields({"title": "Test", "requested_deadline": "bad"})
    with pytest.raises(HttpError):
        timestamp(None)


def test_timestamp_matches_javascript_iso_format():
    assert timestamp("2026-11-05T10:00Z") == "2026-11-05T10:00:00.000Z"
    assert timestamp("2026-11-05T17:00:00+07:00") == "2026-11-05T10:00:00.000Z"


def test_inverted_schedules_are_blocked():
    with pytest.raises(HttpError):
        validate_settings({**GOOD_SETTINGS, "start": 18, "end": 9})


def test_settings_validation():
    assert validate_settings(GOOD_SETTINGS)["weekdays"] == [1]
    for bad in ({"timezone": "Mars/Base"}, {"weekdays": []}, {"weekdays": [7]}, {"buffer": True},
                {"busy": [{"start": "2026-11-02T03:00Z", "end": "2026-11-02T02:00Z"}]}):
        with pytest.raises(HttpError):
            validate_settings({**GOOD_SETTINGS, **bad})


def test_vietnamese_datetime_format():
    assert vi_datetime("2026-11-07T10:00:00.000Z") == "17:00:00 7/11/2026"
