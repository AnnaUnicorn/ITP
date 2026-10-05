"""Regression guards for the authenticated public settings route."""

import re
from pathlib import Path


def test_public_settings_allow_patch_without_removing_login_protection():
    config = (Path(__file__).parents[1] / "deploy/autodl/nginx-itp.conf").read_text()
    assert 'auth_basic "ITP Studio";' in config
    assert "auth_basic_user_file /etc/nginx/itp.htpasswd;" in config
    assert "auth_basic off" not in config
    settings = config.split("location = /api/settings {", 1)[1]
    assert re.search(r"limit_except\s+GET\s+PATCH\s*\{\s*deny all;\s*\}", settings)
    assert "proxy_pass http://127.0.0.1:8000;" in settings
