from pathlib import Path

from bidkit.audit import sha256


def test_sha256_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"Port of Tacoma")
    assert sha256(source) == sha256(source)
