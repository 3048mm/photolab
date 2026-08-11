"""photolab/core/config.py のテスト。

GUI の親フォルダ登録を永続化する（計画書 §3.6）。
読みは標準の tomllib、書きは手書きのシリアライザ。
"""

from photolab.core.config import Config, DestRoot, load_config, save_config, suggest_label


class TestSuggestLabel:
    """登録ボタンのラベルはフォルダ名の末尾（計画書 §3.6）。"""

    def test_フォルダ名の末尾を使う(self):
        assert suggest_label(r"D:\写真\Z6", []) == "Z6"

    def test_同名があれば1つ上の階層を含める(self):
        existing = [DestRoot(label="Z6", path=r"D:\写真\Z6")]
        assert suggest_label(r"E:\backup\Z6", existing) == "backup\\Z6"

    def test_末尾の区切り文字は無視する(self):
        assert suggest_label("D:\\写真\\Z50\\", []) == "Z50"

    def test_ドライブ直下でも壊れない(self):
        assert suggest_label("L:\\", [])


class TestLoadSave:
    def test_ファイルが無ければ既定値になる(self, tmp_path):
        config = load_config(tmp_path / "missing.toml")
        assert config.dest_roots == []
        assert config.last_dest_root is None

    def test_保存して読み直せる(self, tmp_path):
        path = tmp_path / "config.toml"
        config = Config(
            dest_roots=[
                DestRoot(label="Z6", path=r"D:\写真\Z6"),
                DestRoot(label="Z50", path=r"D:\写真\Z50"),
            ],
            last_dest_root=r"D:\写真\Z6",
        )
        save_config(config, path)

        loaded = load_config(path)
        assert loaded.dest_roots == config.dest_roots
        assert loaded.last_dest_root == config.last_dest_root

    def test_日本語とバックスラッシュが壊れない(self, tmp_path):
        path = tmp_path / "config.toml"
        original = r"D:\写真\Z6\家"
        save_config(Config(dest_roots=[DestRoot(label="家", path=original)]), path)
        assert load_config(path).dest_roots[0].path == original

    def test_保存先のフォルダが無ければ作る(self, tmp_path):
        path = tmp_path / "a" / "b" / "config.toml"
        save_config(Config(), path)
        assert path.is_file()

    def test_壊れたファイルでも既定値を返す(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("これは TOML ではない [[[", encoding="utf-8")
        assert load_config(path).dest_roots == []

    def test_ウィンドウサイズを保存できる(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(Config(window_width=1400, window_height=900), path)
        loaded = load_config(path)
        assert (loaded.window_width, loaded.window_height) == (1400, 900)

    def test_darktableの設定を保存できる(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(
            Config(darktable_executable=r"C:\Program Files\darktable\bin\darktable.exe"),
            path,
        )
        loaded = load_config(path)
        assert loaded.darktable_executable.endswith("darktable.exe")
