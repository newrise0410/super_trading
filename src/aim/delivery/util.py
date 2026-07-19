"""딜리버리 공용 유틸."""

from __future__ import annotations


def split_message(text: str, limit: int) -> list[str]:
    """줄 단위로 limit 이하 청크 분할 (텔레그램 4096자, 디스코드 2000자 제한 대응)."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks
