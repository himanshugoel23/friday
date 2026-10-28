"""Live mode needs S3 for recordings, except the private pilot profile (one small server)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from friday.core.interfaces import ProviderError
from friday.db.objectstore import LocalObjectStore, build_object_store


def _st(tmp_path, *, live, profile):
    return SimpleNamespace(object_store_url=None, is_live=live, profile=profile,
                           media_dir=str(tmp_path))


def test_live_default_profile_still_requires_s3(tmp_path):
    with pytest.raises(ProviderError):
        build_object_store(_st(tmp_path, live=True, profile="default"))


def test_live_pilot_profile_uses_local_disk(tmp_path):
    assert isinstance(build_object_store(_st(tmp_path, live=True, profile="pilot")),
                      LocalObjectStore)
