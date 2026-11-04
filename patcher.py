"""Reversible, version-locked Fieldrunners 2 Simplified Chinese patch."""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

VERSION = '0.1.0'
APPID = 215710
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
ORIGINALS = {
    'Data.pak': 'ea2c3de3636124feba025a9c437a5dd0b3e97815c811203dfbef2088b80f8c49',
    'Fieldrunners2.dll': '8a2a552c4c1dd316cfe3dd50f06aa6b5681ac6e9d5299c1c8c034ff39fec9517',
}
BACKUP_SUFFIX = '.fr2zh-original'
MANIFEST = 'fr2zh-install.json'
XOR = bytes(c ^ 0xF8 for c in range(256))
FONT_RE = re.compile(r'(?:ArialWhite\w*|Impact\w*|MarkerBlank\w*|Station_12pt|Stencil\w*|TypeBlank\w*)\.asc')
TOKENS = re.compile(r'\$\([^)]+\)|%(?:%|[-+#0]*\d*(?:\.\d+)?[diuoxXfFeEgGcs])')


class PatchError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_write(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def csv_translate(data, rows):
    """Replace English cells in order, preserving duplicate keys and all other columns."""
    index = 0
    def sub(m):
        nonlocal index
        key, text = m.group(1), m.group(2)
        if key == 'Key' or key.startswith('//'):
            return m.group(0)
        if index >= len(rows) or rows[index]['key'] != key or rows[index]['index'] != index:
            raise PatchError(f'文本结构不匹配：{key}，索引 {index}')
        zh = rows[index]['zh']
        if TOKENS.findall(text) != TOKENS.findall(zh):
            raise PatchError(f'占位符不匹配：{key}')
        if any(c in zh for c in '^\r\n'):
            raise PatchError(f'译文包含无效分隔符：{key}')
        index += 1
        return key + '^' + zh
    text = re.sub(r'(?m)^([^\^\r\n]+)\^([^\^\r\n]*)', sub, data.decode('cp1252'))
    if index != len(rows):
        raise PatchError(f'文本覆盖不完整：{index}/{len(rows)}')
    return text.encode('utf-8')


def patch_form(data, literals):
    text = data.decode('cp1252')
    def element(m):
        tag = m.group(0)
        font = re.search(r'\bFont="([^"]+)"', tag)
        if font and 'Yellow' in font.group(1) and 'Tint=' not in tag:
            tag = tag.replace(' Font=', ' Tint="255, 208, 40, 255" Font=', 1)
        return FONT_RE.sub('Chinese.ttf', tag)
    text = re.sub(r'<Element\b[^>]*>', element, text)
    def label(m):
        value = m.group(1)
        stripped = value.strip()
        if stripped in literals:
            return 'Text="' + value.replace(stripped, literals[stripped]) + '"'
        return m.group(0)
    text = re.sub(r'\bText="([^"]*)"', label, text)
    return text.encode('utf-8')


def build_pak(original):
    src = zipfile.ZipFile(io.BytesIO(original.translate(XOR)))
    target = io.BytesIO()
    literals = json_read(ROOT / 'translations/literals.json')
    changed = []
    with src, zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED) as out:
        if src.testzip() is not None or len(src.infolist()) != 2751:
            raise PatchError('资源包损坏或版本不符')
        for entry in src.infolist():
            data = old = src.read(entry)
            if entry.filename in ('Localizable.csv', 'PlatformLocalizable.csv'):
                data = csv_translate(data, json_read(ROOT / 'translations' / (entry.filename + '.json')))
            elif entry.filename.endswith('.form'):
                data = patch_form(data, literals)
            elif entry.filename.endswith('.ini'):
                data = FONT_RE.sub('Chinese.ttf', data.decode('cp1252')).encode('utf-8')
            if data != old:
                changed.append(entry.filename)
            out.writestr(entry, data)
        font = zipfile.ZipInfo('Chinese.ttf', (2026, 1, 1, 0, 0, 0))
        out.writestr(font, (ROOT / 'assets/Chinese.ttf').read_bytes())
    return target.getvalue().translate(XOR), changed


def align(n, boundary):
    return (n + boundary - 1) // boundary * boundary


def build_dll(original):
    """Add our code section and merge PE base relocations, including rebased loads."""
    data = bytearray(original)
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise PatchError('不是有效的 PE 文件')
    sections, opt_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    opt, table = pe + 24, pe + 24 + opt_size
    if struct.unpack_from('<H', data, opt)[0] != 0x10B:
        raise PatchError('仅支持已验证的 32 位游戏版本')
    section_align, file_align = struct.unpack_from('<II', data, opt + 32)
    def offset(rva):
        for i in range(sections):
            size, va, raw_size, ptr = struct.unpack_from('<IIII', data, table + i * 40 + 8)
            if va <= rva < va + max(size, raw_size):
                return ptr + rva - va
        raise PatchError(f'无效 RVA: {rva:x}')
    meta = json_read(ROOT / 'native/payload.json')
    payload = (ROOT / 'native/payload.bin').read_bytes()
    if digest(payload) != meta['sha256']:
        raise PatchError('本地补丁代码校验失败')
    rva = struct.unpack_from('<I', data, opt + 56)[0]
    if rva != meta['rva'] or table + (sections + 1) * 40 > struct.unpack_from('<I', data, opt + 60)[0]:
        raise PatchError('DLL 布局不匹配')
    branch, end = 0x1ABC8A, 0x1ABD9D
    code = b'\x56\xe8' + struct.pack('<i', meta['entry_rva'] - branch - 6)
    code += b'\xe9' + struct.pack('<i', end - branch - 11)
    data[offset(branch):offset(branch) + len(code)] = code
    data[offset(0x193E89)] = 60
    for m in list(re.finditer(rb'Station_12pt\.asc\x00', data)):
        data[m.start():m.end()] = b'Chinese.ttf\0'.ljust(m.end() - m.start(), b'\0')
    for before, after in [(b' Deck\0\0\0', '套组'.encode('utf-8') + b'\0\0'),
                          (b'%s Deck Collected!\0', '%s套组已集齐！'.encode('utf-8') + b'\0')]:
        # Keep the replacement within the original aligned string storage.
        if len(after) > len(before):
            after = '%s已集齐！'.encode('utf-8') + b'\0'
        if before not in data:
            raise PatchError('DLL 内置文本布局不匹配')
        data = data.replace(before, after.ljust(len(before), b'\0'))
    rel_rva, rel_size = struct.unpack_from('<II', data, opt + 96 + 5 * 8)
    rel_at, rel_end = offset(rel_rva), offset(rel_rva) + rel_size
    relocations = []
    while rel_at < rel_end:
        page, size = struct.unpack_from('<II', data, rel_at)
        if size < 8 or size % 2 or rel_at + size > rel_end:
            raise PatchError('无效的 PE 重定位表')
        for at in range(rel_at + 8, rel_at + size, 2):
            value = struct.unpack_from('<H', data, at)[0]
            kind, target = value >> 12, page + (value & 4095)
            if kind and not branch <= target < branch + len(code):
                relocations.append((kind, target))
        rel_at += size
    relocations.extend((3, rva + x) for x in meta['relocations'])
    pages = collections.defaultdict(list)
    for kind, target in sorted(set(relocations), key=lambda x: x[1]):
        pages[target & ~4095].append((kind << 12) | (target & 4095))
    reloc_blob = bytearray()
    for page, entries in pages.items():
        if len(entries) % 2:
            entries.append(0)
        reloc_blob += struct.pack('<II', page, 8 + 2 * len(entries))
        reloc_blob += struct.pack('<' + 'H' * len(entries), *entries)
    reloc_off = align(len(payload), 4)
    contents = payload.ljust(reloc_off, b'\0') + reloc_blob
    raw_at, raw_size = align(len(data), file_align), align(len(contents), file_align)
    data += b'\0' * (raw_at - len(data)) + contents.ljust(raw_size, b'\0')
    struct.pack_into('<8sIIIIIIHHI', data, table + sections * 40,
                     b'.fr2zh\0\0', len(contents), rva, raw_size, raw_at, 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<H', data, pe + 6, sections + 1)
    struct.pack_into('<I', data, opt + 56, align(rva + len(contents), section_align))
    struct.pack_into('<I', data, opt + 64, 0)
    struct.pack_into('<II', data, opt + 96 + 5 * 8, rva + reloc_off, len(reloc_blob))
    return bytes(data)


def ensure_closed():
    if os.name == 'nt':
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Fieldrunners2.exe', '/FO', 'CSV', '/NH'],
                                capture_output=True, creationflags=0x08000000, check=True)
        if b'fieldrunners2.exe' in result.stdout.lower():
            raise PatchError('请先关闭 Fieldrunners 2，再操作补丁。')


def originals(game):
    result = {}
    for name, expected in ORIGINALS.items():
        backup = game / (name + BACKUP_SUFFIX)
        source = backup if backup.exists() else game / name
        if not source.is_file():
            raise PatchError(f'缺少文件：{source.name}')
        data = source.read_bytes()
        if digest(data) != expected:
            raise PatchError(f'{source.name} 不是受支持的原版文件。请先用 Steam 验证游戏完整性。')
        result[name] = data
    return result


def verify(game):
    game = Path(game).resolve()
    marker = game / MANIFEST
    if not marker.exists():
        for name, expected in ORIGINALS.items():
            if digest((game / name).read_bytes()) != expected:
                raise PatchError(f'{name} 不是原版，也没有本补丁的安装记录。')
        return '原版文件校验通过。'
    record = json_read(marker)
    if set(record.get('patched', {})) != set(ORIGINALS):
        raise PatchError('安装记录损坏。')
    for name, expected in record['patched'].items():
        if digest((game / name).read_bytes()) != expected:
            raise PatchError(f'{name} 与安装记录不符，可能被 Steam 更新或其他补丁修改。')
    originals(game)
    return f'简体中文补丁 {record["version"]} 及原版备份校验通过。'


def install(game, log=print):
    game = Path(game).resolve()
    ensure_closed()
    if not game.is_dir() or not (game / 'Fieldrunners2.exe').is_file():
        raise PatchError('请选择包含 Fieldrunners2.exe 的游戏文件夹。')
    marker = game / MANIFEST
    if marker.exists():
        verify(game)
    else:
        # A backup alone is never permission to overwrite an unknown modification.
        for name, expected in ORIGINALS.items():
            if digest((game / name).read_bytes()) != expected:
                raise PatchError(f'{name} 已被修改且没有安装记录。请先还原原版。')
    source = originals(game)
    log('正在构建中文资源包……')
    pak, changed = build_pak(source['Data.pak'])
    outputs = {'Data.pak': pak, 'Fieldrunners2.dll': build_dll(source['Fieldrunners2.dll'])}
    record = {'version': VERSION, 'appid': APPID, 'original': ORIGINALS,
              'patched': {n: digest(d) for n, d in outputs.items()}, 'resources_changed': changed}
    for name, data in source.items():
        backup = game / (name + BACKUP_SUFFIX)
        if not backup.exists():
            # Exclusive creation protects a concurrently created or existing backup.
            with backup.open('xb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        if digest(backup.read_bytes()) != ORIGINALS[name]:
            raise PatchError(f'原版备份校验失败：{backup.name}')
    previous = {name: (game / name).read_bytes() for name in outputs}
    previous_marker = marker.read_bytes() if marker.exists() else None
    record['previous'] = {name: digest(data) for name, data in previous.items()}
    try:
        # Write the recovery record first, so a power loss can still be restored.
        atomic_write(marker, (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        for name, data in outputs.items():
            atomic_write(game / name, data)
    except Exception:
        for name, data in previous.items():
            atomic_write(game / name, data)
        if previous_marker is None:
            marker.unlink(missing_ok=True)
        else:
            atomic_write(marker, previous_marker)
        raise
    log(verify(game))
    log('安装完成。请通过 Steam 启动游戏；存档和 Steam 文件均未修改。')
    return record


def restore(game, log=print):
    game = Path(game).resolve()
    ensure_closed()
    # Validate every backup before writing any file.
    source = originals(game)
    marker = game / MANIFEST
    record = json_read(marker) if marker.exists() else None
    for name in ORIGINALS:
        current = digest((game / name).read_bytes())
        accepted = {ORIGINALS[name]}
        if record:
            accepted.add(record.get('patched', {}).get(name))
            accepted.add(record.get('previous', {}).get(name))
        if current not in accepted:
            raise PatchError(f'{name} 已被其他程序修改。为避免覆盖修改，还原已停止。')
    previous = {name: (game / name).read_bytes() for name in source}
    try:
        for name, data in source.items():
            atomic_write(game / name, data)
    except Exception:
        for name, data in previous.items():
            atomic_write(game / name, data)
        raise
    if marker.exists():
        marker.unlink()
    log('已恢复原版，校验通过。备份保留，可再次安装汉化。')


def detect_game():
    candidates = []
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                steam = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
            candidates.append(steam)
            vdf = steam / 'steamapps/libraryfolders.vdf'
            if vdf.exists():
                candidates.extend(Path(x.replace('\\\\', '\\')) for x in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding='utf-8')))
        except OSError:
            pass
    for folder in candidates:
        target = folder / 'steamapps/common/Fieldrunners 2'
        if (target / 'Fieldrunners2.exe').exists():
            return target
    return None


def main():
    parser = argparse.ArgumentParser(description='Fieldrunners 2 简体中文补丁')
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('action', nargs='?', choices=['install', 'restore', 'verify'])
    args = parser.parse_args()
    if not args.action:
        from installer import show_gui
        return show_gui()
    game = args.game_dir or detect_game()
    if not game:
        parser.error('未找到游戏，请用 --game-dir 指定文件夹。')
    try:
        if args.action == 'verify':
            print(verify(game))
        else:
            globals()[args.action](game)
        return 0
    except (PatchError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f'操作失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
