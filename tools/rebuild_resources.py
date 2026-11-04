"""Rebuild optional font resources and hashed cached-map translations."""
import argparse
import io
from pathlib import Path
import re
import zipfile
import patcher

ROOT = Path(__file__).resolve().parents[1]
FONT_SHA = 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da'


def hashes(data):
    a, b = 2166136261, 5381
    for c in data:
        a = ((a ^ c) * 16777619) & 0xFFFFFFFF
        b = ((b * 33) ^ c) & 0xFFFFFFFF
    return a, b, len(data)


def rebuild_fallback(game):
    pak = patcher.originals(Path(game))['Data.pak']
    with zipfile.ZipFile(io.BytesIO(pak.translate(patcher.XOR))) as z:
        text = z.read('Localizable.csv').decode('cp1252')
    source = {m.group(1): m.group(2) for m in re.finditer(r'(?m)^([^\^\r\n]+)\^([^\^\r\n]*)', text)}
    rows = {}
    for row in patcher.json_read(ROOT / 'translations/Localizable.csv.json'):
        key = row['key']
        if re.fullmatch(r'(Grasslands|Drylands|Lavaflow|City)_Map\d+[a-z]?(Name|Description)', key):
            en = source[key]
            if en and not en.startswith('UNUSED'):
                for encoding in ['cp1252', 'utf-8']:
                    rows[hashes(en.encode(encoding))] = row['zh']
    # Resumed games sometimes lack mission-selection globals; show coherent objectives.
    for before, after in [
        ('阻止入侵，坚守 波！', '阻止入侵，坚守到最后一波！'),
        ('在防线被突破前击败 个单位。', '在防线被突破前尽可能击败敌人。'),
        ('在时间耗尽前击败 个单位。', '在时间耗尽前尽可能击败敌人。'),
        ('在 波内击败这名首领。', '击败这名首领，守住防线！'),
    ]:
        for candidate in {before, before.replace(' ', '  ')}:
            rows[hashes(candidate.encode('utf-8'))] = after
    out = '/* Display-only localization of cached map metadata. No save files are changed. */\n'
    out += 'typedef struct {unsigned hash,check,length; const char*zh;} CachedMap;\nstatic const CachedMap cached_maps[]={\n'
    for (a, b, n), zh in sorted(rows.items()):
        escaped = ''.join(f'\\x{c:02x}' for c in zh.encode('utf-8'))
        out += f'{{{a}u,{b}u,{n}u,"{escaped}"}},\n'
    (ROOT / 'native/fallback.h').write_text(out + '};\n', encoding='ascii', newline='\n')
    print(f'Rebuilt {len(rows)} cached-map fallback records')


def rebuild_font(source):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    if patcher.digest(Path(source).read_bytes()) != FONT_SHA:
        raise patcher.PatchError('Source font hash differs from the pinned upstream version')
    font = TTFont(source)
    font = instantiateVariableFont(font, {'wght': 550}, inplace=True)
    chars = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'translations').glob('*.json'))
    chars += ''.join(chr(i) for i in range(32, 256)) + 'Ω→←↑↓×÷★☆…'
    options = subset.Options()
    options.name_IDs = ['*']
    options.name_legacy = True
    options.name_languages = ['*']
    options.recalc_timestamp = False
    tool = subset.Subsetter(options=options)
    tool.populate(text=chars)
    tool.subset(font)
    for name in font['name'].names:
        if name.nameID in [1, 4, 6]:
            name.string = ('FR2ChineseUI' if name.nameID == 6 else 'FR2 Chinese UI').encode(name.getEncoding())
    font.recalcTimestamp = False
    font['head'].modified = 3850070400  # OpenType epoch: 2026-01-01 UTC.
    font.save(ROOT / 'assets/Chinese.ttf')
    widths, units = font['hmtx'].metrics, font['head'].unitsPerEm
    rows = [(cp, round(widths[glyph][0] * 1000 / units)) for cp, glyph in sorted(font.getBestCmap().items()) if cp < 65536]
    header = '/* Generated from assets/Chinese.ttf; units normalized to 1000. */\nstatic const unsigned short metrics[][2]={\n'
    header += ',\n'.join('{%d,%d}' % row for row in rows) + '\n};\n'
    (ROOT / 'native/metrics.h').write_text(header, encoding='ascii', newline='\n')
    print('Font SHA256:', patcher.digest((ROOT / 'assets/Chinese.ttf').read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-source', type=Path)
    parser.add_argument('--game-dir', type=Path)
    args = parser.parse_args()
    if args.font_source:
        rebuild_font(args.font_source)
    if args.game_dir:
        rebuild_fallback(args.game_dir)
    if not args.font_source and not args.game_dir:
        parser.error('Provide --font-source and/or --game-dir')


if __name__ == '__main__':
    main()
