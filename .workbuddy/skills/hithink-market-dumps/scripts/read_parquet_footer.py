"""不依赖任何第三方库，读出 Parquet 文件的页脚元数据与列统计。

用途：核对同花顺 market-dumps 的 Parquet（行数、列名、物理类型、日期覆盖、复权口径），
而不需要安装 pyarrow / pandas。

    python read_parquet_footer.py /path/to/file.parquet

实现要点：Parquet 文件是 `<data><4 字节小端元数据长度><PAR1>`，元数据本身是 Thrift
compact 编码，所以只要实现 compact 协议的读取就能拿到 FileMetaData —— 不用碰数据页、
不用解压缩、不用字典解码。
"""

from __future__ import annotations

import struct
import sys
from datetime import datetime, timedelta, timezone

STOP, TRUE_, FALSE_, BYTE, I16, I32, I64, DOUBLE, BINARY, LIST, SET, MAP, STRUCT = range(13)

PHYSICAL = {
    0: 'BOOLEAN',
    1: 'INT32',
    2: 'INT64',
    3: 'INT96',
    4: 'FLOAT',
    5: 'DOUBLE',
    6: 'BYTE_ARRAY',
    7: 'FIXED_LEN_BYTE_ARRAY',
}


class Reader:
    """最小 Thrift compact 协议读取器。"""

    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.p = 0

    def byte(self) -> int:
        value = self.buf[self.p]
        self.p += 1
        return value

    def varint(self) -> int:
        result = shift = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    def zigzag(self) -> int:
        n = self.varint()
        return (n >> 1) ^ -(n & 1)

    def value(self, type_id: int):
        if type_id in (TRUE_, FALSE_):
            return type_id == TRUE_
        if type_id == BYTE:
            return self.byte()
        if type_id in (I16, I32, I64):
            return self.zigzag()
        if type_id == DOUBLE:
            chunk = self.buf[self.p:self.p + 8]
            self.p += 8
            return struct.unpack('<d', chunk)[0]
        if type_id == BINARY:
            size = self.varint()
            chunk = self.buf[self.p:self.p + size]
            self.p += size
            return chunk
        if type_id in (LIST, SET):
            header = self.byte()
            size = (header >> 4) & 0x0F
            elem_type = header & 0x0F
            if size == 15:
                size = self.varint()
            return [self.value(elem_type) for _ in range(size)]
        if type_id == MAP:
            size = self.varint()
            if not size:
                return {}
            header = self.byte()
            key_type, val_type = (header >> 4) & 0x0F, header & 0x0F
            return {self.value(key_type): self.value(val_type) for _ in range(size)}
        if type_id == STRUCT:
            return self.struct()
        raise ValueError(f'未知的 thrift 类型 {type_id}')

    def struct(self) -> dict:
        fields: dict[int, object] = {}
        last_id = 0
        while True:
            header = self.byte()
            if header == 0:
                return fields
            type_id = header & 0x0F
            delta = (header >> 4) & 0x0F
            field_id = last_id + delta if delta else self.zigzag()
            last_id = field_id
            fields[field_id] = self.value(type_id)


def as_text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def shanghai(ms: int) -> str:
    moment = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
    return moment.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')


def describe(physical: str, raw_min, raw_max) -> str:
    if raw_min is None or raw_max is None:
        return ''
    if physical in ('INT32', 'INT64') and len(raw_min) == len(raw_max) == 8:
        fmt = '<i' if physical == 'INT32' else '<q'
        lo, hi = struct.unpack(fmt, raw_min)[0], struct.unpack(fmt, raw_max)[0]
        if 1_000_000_000_000 < lo < 4_000_000_000_000:
            return f'  {shanghai(lo)}  ..  {shanghai(hi)}'
        return f'  {lo} .. {hi}'
    if physical in ('DOUBLE', 'FLOAT') and len(raw_min) == len(raw_max) == 8:
        return f'  {struct.unpack("<d", raw_min)[0]} .. {struct.unpack("<d", raw_max)[0]}'
    return f'  {raw_min[:16]!r} .. {raw_max[:16]!r}'


def main(path: str) -> int:
    blob = open(path, 'rb').read()
    if blob[:4] != b'PAR1' or blob[-4:] != b'PAR1':
        print('不是 Parquet 文件（缺少 PAR1 magic）')
        return 1

    meta_len = struct.unpack('<I', blob[-8:-4])[0]
    footer = Reader(blob[len(blob) - 8 - meta_len:len(blob) - 8]).struct()

    print(f'文件大小: {len(blob):,} 字节 | 页脚元数据: {meta_len:,} 字节')
    print(f'version={footer.get(1)}  num_rows={footer.get(3):,}')
    created_by = footer.get(6)
    if created_by:
        print(f'created_by={as_text(created_by)}')

    schema = footer.get(2) or []
    leaves = 0
    for element in schema:
        if element.get(5) is None:
            leaves += 1
    print(f'\nschema 元素 {len(schema)} 个，叶子列 {leaves} 个：')

    row_groups = footer.get(4) or []
    print(f'row group 数: {len(row_groups)}\n')

    for chunk in (row_groups[0].get(1) if row_groups else None) or []:
        meta = chunk.get(3) or {}
        path_in_schema = meta.get(3) or []
        column = as_text(path_in_schema[0]) if path_in_schema else '?'
        physical = PHYSICAL.get(meta.get(1), str(meta.get(1)))
        stats = meta.get(12) or {}
        raw_min = stats.get(6) or stats.get(2)
        raw_max = stats.get(5) or stats.get(1)
        null_count = stats.get(3)
        print(f'{column:16} {physical:12} 值={meta.get(5):<8} codec={meta.get(4)} '
              f'null={null_count}{describe(physical, raw_min, raw_max)}')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
