"""config.yaml keys."""

from pathlib import Path

from endnote_mcp.config import Config


def _write(tmp_path, extra=""):
    p = tmp_path / "config.yaml"
    p.write_text(f"endnote_xml: {tmp_path}/lib.xml\npdf_dir: {tmp_path}/PDF\n{extra}", encoding="utf-8")
    return p


def test_add_references_is_off_by_default(tmp_path):
    cfg = Config.load(_write(tmp_path))
    assert cfg.add_references is False
    assert cfg.endnote_library is None


def test_add_references_settings(tmp_path):
    cfg = Config.load(_write(tmp_path, "add_references: true\nendnote_library: ~/Documents/My Library.enlp\n"))
    assert cfg.add_references is True
    assert cfg.endnote_library == Path.home() / "Documents" / "My Library.enlp"
