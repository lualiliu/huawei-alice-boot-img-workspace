#!/usr/bin/env python3
"""
bootimg_tool.py — Android boot.img 解包 / 打包工具
支持 Header v0 / v1 / v2

用法：
  解包:  python bootimg_tool.py unpack boot.img [--out ./out]
  打包:  python bootimg_tool.py repack ./out [--output new_boot.img]
"""

import argparse
import json
import math
import os
import struct
import sys
from pathlib import Path

# ──────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────
BOOT_MAGIC        = b"ANDROID!"
BOOT_MAGIC_SIZE   = 8
BOOT_NAME_SIZE    = 16
BOOT_ARGS_SIZE    = 512
BOOT_EXTRA_ARGS_SIZE = 1024

# ──────────────────────────────────────────────────
# Header 解析
# ──────────────────────────────────────────────────

def _read_cstr(data: bytes) -> str:
    """将 bytes 中的 C 字符串（以 \x00 截断）解码为 str。"""
    return data.rstrip(b"\x00").decode("utf-8", errors="replace")


def parse_header(data: bytes) -> dict:
    """解析 boot.img header，返回字段字典。"""
    if data[:BOOT_MAGIC_SIZE] != BOOT_MAGIC:
        raise ValueError("不是有效的 Android boot.img（magic 不匹配）")

    # v0 基础字段（固定偏移）
    # 格式: magic(8) kernel_size(4) kernel_addr(4) ramdisk_size(4) ramdisk_addr(4)
    #       second_size(4) second_addr(4) tags_addr(4) page_size(4)
    #       header_version(4) os_version(4) name(16) cmdline(512)
    #       id(32) extra_cmdline(1024)
    fmt_v0 = (
        "8s"   # magic
        "I"    # kernel_size
        "I"    # kernel_addr
        "I"    # ramdisk_size
        "I"    # ramdisk_addr
        "I"    # second_size
        "I"    # second_addr
        "I"    # tags_addr
        "I"    # page_size
        "I"    # header_version  (v0 叫 dt_size，这里统一处理)
        "I"    # os_version
        f"{BOOT_NAME_SIZE}s"
        f"{BOOT_ARGS_SIZE}s"
        "32s"  # id
        f"{BOOT_EXTRA_ARGS_SIZE}s"
    )
    size_v0 = struct.calcsize(fmt_v0)
    fields = struct.unpack_from(fmt_v0, data)

    h = {
        "magic":          fields[0].decode(),
        "kernel_size":    fields[1],
        "kernel_addr":    fields[2],
        "ramdisk_size":   fields[3],
        "ramdisk_addr":   fields[4],
        "second_size":    fields[5],
        "second_addr":    fields[6],
        "tags_addr":      fields[7],
        "page_size":      fields[8],
        "header_version": fields[9],
        "os_version":     fields[10],
        "name":           _read_cstr(fields[11]),
        "cmdline":        _read_cstr(fields[12]),
        "id":             fields[13].hex(),
        "extra_cmdline":  _read_cstr(fields[14]),
    }

    version = h["header_version"]

    # v1 新增字段
    if version >= 1:
        off = size_v0
        h["recovery_dtbo_size"],   = struct.unpack_from("<I", data, off); off += 4
        h["recovery_dtbo_offset"], = struct.unpack_from("<Q", data, off); off += 8
        h["header_size"],          = struct.unpack_from("<I", data, off); off += 4

    # v2 新增字段
    if version >= 2:
        h["dtb_size"],   = struct.unpack_from("<I", data, off); off += 4
        h["dtb_addr"],   = struct.unpack_from("<Q", data, off); off += 8

    return h


# ──────────────────────────────────────────────────
# 辅助：页对齐
# ──────────────────────────────────────────────────

def page_align(size: int, page_size: int) -> int:
    """返回 size 向上对齐到 page_size 倍数的字节数。"""
    if size == 0:
        return 0
    return math.ceil(size / page_size) * page_size


def pad_to_page(data: bytes, page_size: int) -> bytes:
    """在 data 末尾补零，使总长度对齐到 page_size。"""
    r = len(data) % page_size
    return data if r == 0 else data + b"\x00" * (page_size - r)


# ──────────────────────────────────────────────────
# 解包
# ──────────────────────────────────────────────────

def unpack(img_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw = Path(img_path).read_bytes()
    h = parse_header(raw)
    page = h["page_size"]
    version = h["header_version"]

    print(f"[*] header_version : {version}")
    print(f"[*] page_size      : {page}")
    print(f"[*] kernel_size    : {h['kernel_size']}")
    print(f"[*] ramdisk_size   : {h['ramdisk_size']}")
    print(f"[*] second_size    : {h['second_size']}")

    # 各分区在文件中的起始偏移
    offset = page  # header 占 1 page

    # kernel
    kernel = raw[offset: offset + h["kernel_size"]]
    (out / "kernel").write_bytes(kernel)
    offset += page_align(h["kernel_size"], page)
    print(f"[+] 解包 kernel    → kernel ({len(kernel)} bytes)")

    # ramdisk
    ramdisk = raw[offset: offset + h["ramdisk_size"]]
    (out / "ramdisk.img").write_bytes(ramdisk)
    offset += page_align(h["ramdisk_size"], page)
    print(f"[+] 解包 ramdisk   → ramdisk.img ({len(ramdisk)} bytes)")

    # second（可选）
    if h["second_size"] > 0:
        second = raw[offset: offset + h["second_size"]]
        (out / "second").write_bytes(second)
        offset += page_align(h["second_size"], page)
        print(f"[+] 解包 second    → second ({len(second)} bytes)")

    # recovery dtbo（v1+）
    if version >= 1 and h.get("recovery_dtbo_size", 0) > 0:
        dtbo = raw[offset: offset + h["recovery_dtbo_size"]]
        (out / "recovery_dtbo").write_bytes(dtbo)
        offset += page_align(h["recovery_dtbo_size"], page)
        print(f"[+] 解包 recovery_dtbo → recovery_dtbo ({len(dtbo)} bytes)")

    # dtb（v2+）
    if version >= 2 and h.get("dtb_size", 0) > 0:
        dtb = raw[offset: offset + h["dtb_size"]]
        (out / "dtb").write_bytes(dtb)
        print(f"[+] 解包 dtb       → dtb ({len(dtb)} bytes)")

    # 保存 header 元数据（用于重新打包）
    meta = {k: v for k, v in h.items() if k != "magic"}
    (out / "header.json").write_text(json.dumps(meta, indent=2))
    print(f"[+] 元数据         → header.json")
    print(f"[✓] 解包完成，输出目录: {out.resolve()}")


# ──────────────────────────────────────────────────
# 打包
# ──────────────────────────────────────────────────

def _read_opt(base: Path, name: str) -> bytes:
    p = base / name
    return p.read_bytes() if p.exists() else b""


def repack(src_dir: str, output: str) -> None:
    base = Path(src_dir)
    meta_file = base / "header.json"
    if not meta_file.exists():
        sys.exit(f"[!] 找不到 {meta_file}，请先执行解包")

    h = json.loads(meta_file.read_text())
    page = h["page_size"]
    version = h["header_version"]

    kernel  = (base / "kernel").read_bytes()
    ramdisk = (base / "ramdisk.img").read_bytes()
    second  = _read_opt(base, "second")
    dtbo    = _read_opt(base, "recovery_dtbo")
    dtb     = _read_opt(base, "dtb")

    # 更新 size 字段
    h["kernel_size"]  = len(kernel)
    h["ramdisk_size"] = len(ramdisk)
    h["second_size"]  = len(second)
    if version >= 1:
        h["recovery_dtbo_size"] = len(dtbo)
    if version >= 2:
        h["dtb_size"] = len(dtb)

    # 构建 header bytes
    header_bytes = _build_header(h, page)

    # 拼接所有分区（每块末尾补零对齐）
    parts = [
        pad_to_page(header_bytes, page),
        pad_to_page(kernel, page),
        pad_to_page(ramdisk, page),
    ]
    if len(second) > 0:
        parts.append(pad_to_page(second, page))
    if version >= 1 and len(dtbo) > 0:
        parts.append(pad_to_page(dtbo, page))
    if version >= 2 and len(dtb) > 0:
        parts.append(pad_to_page(dtb, page))

    img = b"".join(parts)
    Path(output).write_bytes(img)

    print(f"[✓] 打包完成: {Path(output).resolve()}  ({len(img)} bytes)")


def _build_header(h: dict, page: int) -> bytes:
    """将元数据字典重新序列化为 header bytes。"""

    def enc(s: str, size: int) -> bytes:
        b = s.encode("utf-8")
        return b[:size].ljust(size, b"\x00")

    data = struct.pack(
        "<"
        "8s"    # magic
        "I"     # kernel_size
        "I"     # kernel_addr
        "I"     # ramdisk_size
        "I"     # ramdisk_addr
        "I"     # second_size
        "I"     # second_addr
        "I"     # tags_addr
        "I"     # page_size
        "I"     # header_version
        "I",    # os_version
        BOOT_MAGIC,
        h["kernel_size"],
        h["kernel_addr"],
        h["ramdisk_size"],
        h["ramdisk_addr"],
        h["second_size"],
        h["second_addr"],
        h["tags_addr"],
        page,
        h["header_version"],
        h["os_version"],
    )
    data += enc(h.get("name", ""), BOOT_NAME_SIZE)
    data += enc(h.get("cmdline", ""), BOOT_ARGS_SIZE)
    data += bytes.fromhex(h.get("id", "00" * 32))
    data += enc(h.get("extra_cmdline", ""), BOOT_EXTRA_ARGS_SIZE)

    version = h["header_version"]

    # v1 扩展
    if version >= 1:
        data += struct.pack("<I", h.get("recovery_dtbo_size", 0))
        # recovery_dtbo_offset 相对于文件头，需根据布局计算
        # 这里直接使用解包时存储的原始值（或重新计算）
        dtbo_offset = h.get("recovery_dtbo_offset", 0)
        data += struct.pack("<Q", dtbo_offset)
        header_size = len(data) + 4  # 加上 header_size 字段本身
        data += struct.pack("<I", header_size)

    # v2 扩展
    if version >= 2:
        data += struct.pack("<I", h.get("dtb_size", 0))
        data += struct.pack("<Q", h.get("dtb_addr", 0))

    return data


# ──────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Android boot.img 解包 / 打包工具 (v0/v1/v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python bootimg_tool.py unpack boot.img --out ./out
  python bootimg_tool.py repack ./out --output new_boot.img
""",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_unpack = sub.add_parser("unpack", help="解包 boot.img")
    p_unpack.add_argument("img", help="boot.img 路径")
    p_unpack.add_argument("--out", default="./boot_out", help="输出目录（默认 ./boot_out）")

    p_repack = sub.add_parser("repack", help="打包 boot.img")
    p_repack.add_argument("src", help="解包输出目录")
    p_repack.add_argument("--output", default="new_boot.img", help="输出文件（默认 new_boot.img）")

    args = ap.parse_args()
    if args.cmd == "unpack":
        unpack(args.img, args.out)
    else:
        repack(args.src, args.output)


if __name__ == "__main__":
    main()
