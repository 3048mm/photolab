"""テスト共通のフィクスチャ。

実データのフィクスチャは `data/test/` に置く（git 管理外 / 計画書 §4-Q6）。
無い環境ではそれを使うテストを skip する。
"""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "test"


@pytest.fixture(scope="session")
def fixtures():
    """`data/test/` のパス。フィクスチャが無ければ skip する。"""
    if not FIXTURES_DIR.is_dir() or not any(FIXTURES_DIR.iterdir()):
        pytest.skip(
            f"{FIXTURES_DIR} にフィクスチャがありません。"
            "D:\\写真 から NEF / JPG / MOV を複製してください"
        )
    return FIXTURES_DIR
