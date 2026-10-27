from friday.connectors.doctor_checks import check_browser


def test_default_off_and_selftest_pass():
    s = check_browser({})
    assert not [c for c in s.checks if c.status == "FAIL"], s.checks
    assert any("off (default)" in c.message for c in s.checks)
    assert any("self test" in c.message and c.status == "OK" for c in s.checks)


def test_on_is_warned_and_message_has_no_values():
    s = check_browser({"FRIDAY_BROWSER_ENABLED": "1", "FRIDAY_CONNECTORS_KILL": "zomato.food"})
    assert any(c.status == "WARN" and "ON" in c.message for c in s.checks)
    assert "zomato.food" not in " ".join(c.message for c in s.checks)


def test_login_lines_default_off_http_base_fails_and_chat_otp_is_warned():
    base = {"FRIDAY_BROWSER_ENABLED": "1"}
    s = check_browser(base)
    assert any("login codes in chat are off" in c.message for c in s.checks)
    creds = {**base, "FRIDAY_BROWSER_CREDENTIALS_ENABLED": "1",
             "FRIDAY_BROWSER_CREDENTIALS_ENABLED_USERS": "u1"}
    s = check_browser({**creds, "FRIDAY_PUBLIC_BASE_URL": "http://friday.example"})
    assert any(c.status == "FAIL" and "not https" in c.message for c in s.checks)
    s = check_browser({**creds, "FRIDAY_PUBLIC_BASE_URL": "https://friday.example",
                       "FRIDAY_BROWSER_LOGIN_OTP_IN_CHAT": "1"})
    assert not any(c.status == "FAIL" and "https" in c.message for c in s.checks)
    assert any(c.status == "WARN" and "typed in WhatsApp chat" in c.message for c in s.checks)
    assert "friday.example" not in " ".join(c.message for c in s.checks)


async def test_works_inside_a_running_event_loop():
    s = check_browser({})
    assert any("self test" in c.message and c.status == "OK" for c in s.checks)
