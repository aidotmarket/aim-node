from __future__ import annotations

from pathlib import Path

import pytest

from aim_node.core.config import AIMCoreConfig


@pytest.fixture
def core_config(tmp_path: Path) -> AIMCoreConfig:
    return AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-123",
        data_dir=tmp_path / "data",
    )
