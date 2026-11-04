import io
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import patcher


def fake_dll():
    data = bytearray(0x301000)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x14C, 1)
    struct.pack_into('<H', data, 0x94, 224)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x10B)
    struct.pack_into('<I', data, opt + 28, 0x10000000)
    struct.pack_into('<II', data, opt + 32, 4096, 512)
    struct.pack_into('<II', data, opt + 56, 0x3B1000, 512)
    struct.pack_into('<I', data, opt + 92, 16)
    struct.pack_into('<II', data, opt + 96 + 5 * 8, 0x300000, 12)
    struct.pack_into('<8sIIIIIIHHI', data, opt + 224, b'.text\0\0\0',
                     0x300000, 0x1000, 0x300000, 0x1000, 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<IIHH', data, 0x300000, 0x1AB000, 12, 0x3C92, 0x3100)
    data[0x400:0x408] = b' Deck\0\0\0'
    string = b'%s Deck Collected!\0'
    data[0x420:0x420 + len(string)] = string
    return bytes(data)


def fixture_pak():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('Localizable.csv', b'Key^English^Comment\r\nA^Hello %d^keep\r\n')
        z.writestr('PlatformLocalizable.csv', b'Key^English\r\nB^Click\r\n')
        z.writestr('View.form', b'<Element Text="BUY" Font="StencilYellow10.asc"/>')
        z.writestr('BaseEngine.ini', b'DefaultTextFont = Station_12pt.asc\r\n')
        for i in range(2747):
            z.writestr(f'assets/{i}.bin', bytes(range(256)))
    return out.getvalue().translate(patcher.XOR)


class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pak = fixture_pak()
        cls.dll = fake_dll()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'patch'
        (self.assets / 'translations').mkdir(parents=True)
        (self.assets / 'assets').mkdir()
        (self.assets / 'native').mkdir()
        for name, key, zh in [('Localizable.csv', 'A', '你好 %d'), ('PlatformLocalizable.csv', 'B', '点击')]:
            (self.assets / 'translations' / (name + '.json')).write_text(
                json.dumps([{'index': 0, 'key': key, 'zh': zh}]), encoding='utf-8')
        (self.assets / 'translations/literals.json').write_text('{"BUY":"购买"}', encoding='utf-8')
        (self.assets / 'assets/Chinese.ttf').write_bytes(b'font fixture')
        for name in ['payload.bin', 'payload.json']:
            (self.assets / 'native' / name).write_bytes((patcher.ROOT / 'native' / name).read_bytes())
        self.game = self.root / 'game'
        self.game.mkdir()
        (self.game / 'Data.pak').write_bytes(self.pak)
        (self.game / 'Fieldrunners2.dll').write_bytes(self.dll)
        (self.game / 'Fieldrunners2.exe').write_bytes(b'exe fixture')
        self.hashes = {'Data.pak': patcher.digest(self.pak), 'Fieldrunners2.dll': patcher.digest(self.dll)}
        self.addCleanup(patch.stopall)
        patch('patcher.ROOT', self.assets).start()
        patch('patcher.ORIGINALS', self.hashes).start()
        patch('patcher.ensure_closed').start()

    def test_duplicate_keys_and_placeholders_preserved(self):
        data = b'Key^English^Comments\r\n// section^^\r\nA^Hi %d^x\r\nA^$(Name): %s^y\r\n'
        rows = [{'index': 0, 'key': 'A', 'zh': '你好 %d'},
                {'index': 1, 'key': 'A', 'zh': '$(Name)：%s'}]
        result = patcher.csv_translate(data, rows).decode('utf-8')
        self.assertIn('A^你好 %d^x\r\nA^$(Name)：%s^y\r\n', result)
        rows[1]['zh'] = '错了 %d'
        with self.assertRaises(patcher.PatchError):
            patcher.csv_translate(data, rows)

    def test_unrelated_resource_bytes_unchanged(self):
        result, changed = patcher.build_pak(self.pak)
        before = zipfile.ZipFile(io.BytesIO(self.pak.translate(patcher.XOR)))
        after = zipfile.ZipFile(io.BytesIO(result.translate(patcher.XOR)))
        self.assertEqual(len(after.namelist()), 2752)
        self.assertEqual(set(changed), {'Localizable.csv', 'PlatformLocalizable.csv', 'View.form', 'BaseEngine.ini'})
        for name in before.namelist():
            if name not in changed:
                self.assertEqual(before.read(name), after.read(name))
        self.assertIn('Tint="255, 208, 40, 255"', after.read('View.form').decode('utf-8'))

    def test_install_verify_restore_roundtrip(self):
        logs = []
        patcher.install(self.game, logs.append)
        self.assertIn('0.1.0', patcher.verify(self.game))
        for name, expected in self.hashes.items():
            self.assertEqual(patcher.digest((self.game / (name + patcher.BACKUP_SUFFIX)).read_bytes()), expected)
        saved = {n: (self.game / n).read_bytes() for n in self.hashes}
        patcher.install(self.game, logs.append)
        self.assertEqual(saved, {n: (self.game / n).read_bytes() for n in self.hashes})
        patcher.restore(self.game, logs.append)
        for name, expected in self.hashes.items():
            self.assertEqual(patcher.digest((self.game / name).read_bytes()), expected)
        self.assertFalse((self.game / patcher.MANIFEST).exists())
        self.assertIn('原版', patcher.verify(self.game))

    def test_unknown_version_never_overwritten(self):
        (self.game / 'Data.pak').write_bytes(b'unknown mod')
        with self.assertRaises(patcher.PatchError):
            patcher.install(self.game, lambda _: None)
        self.assertEqual((self.game / 'Data.pak').read_bytes(), b'unknown mod')
        self.assertFalse((self.game / ('Data.pak' + patcher.BACKUP_SUFFIX)).exists())

    def test_backup_tampering_blocks_restore(self):
        patcher.install(self.game, lambda _: None)
        current = (self.game / 'Data.pak').read_bytes()
        (self.game / ('Data.pak' + patcher.BACKUP_SUFFIX)).write_bytes(b'corrupt')
        with self.assertRaises(patcher.PatchError):
            patcher.restore(self.game, lambda _: None)
        self.assertEqual((self.game / 'Data.pak').read_bytes(), current)

    def test_external_modification_not_overwritten_on_restore(self):
        patcher.install(self.game, lambda _: None)
        (self.game / 'Data.pak').write_bytes(b'another mod')
        with self.assertRaises(patcher.PatchError):
            patcher.restore(self.game, lambda _: None)
        self.assertEqual((self.game / 'Data.pak').read_bytes(), b'another mod')

    def test_interrupted_install_can_be_restored(self):
        record = patcher.install(self.game, lambda _: None)
        (self.game / 'Fieldrunners2.dll').write_bytes(self.dll)
        with self.assertRaises(patcher.PatchError):
            patcher.verify(self.game)
        patcher.restore(self.game, lambda _: None)
        self.assertEqual((self.game / 'Data.pak').read_bytes(), self.pak)
        self.assertEqual(record['original'], self.hashes)

    def test_write_failure_rolls_back_both_files(self):
        real_write = patcher.atomic_write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if Path(path).name == 'Fieldrunners2.dll' and not failed:
                failed = True
                raise OSError('simulated write failure')
            return real_write(path, data)
        with patch('patcher.atomic_write', fail_once):
            with self.assertRaises(OSError):
                patcher.install(self.game, lambda _: None)
        self.assertEqual((self.game / 'Data.pak').read_bytes(), self.pak)
        self.assertEqual((self.game / 'Fieldrunners2.dll').read_bytes(), self.dll)
        self.assertFalse((self.game / patcher.MANIFEST).exists())

    def test_pe_relocations_preserve_relative_branches(self):
        result = patcher.build_dll(self.dll)
        opt = 0x98
        self.assertEqual(struct.unpack_from('<H', result, 0x86)[0], 2)
        rva, size = struct.unpack_from('<II', result, opt + 96 + 5 * 8)
        table = opt + 224 + 40
        va, ptr = struct.unpack_from('<I', result, table + 12)[0], struct.unpack_from('<I', result, table + 20)[0]
        pos, end = ptr + rva - va, ptr + rva - va + size
        targets = []
        while pos < end:
            page, length = struct.unpack_from('<II', result, pos)
            for value in struct.unpack_from('<' + 'H' * ((length - 8) // 2), result, pos + 8):
                if value >> 12:
                    targets.append(page + (value & 4095))
            pos += length
        self.assertIn(0x1AB100, targets)
        self.assertNotIn(0x1ABC92, targets)  # Removed relocation inside replacement branch.
        meta = patcher.json_read(self.assets / 'native/payload.json')
        self.assertTrue(all(meta['rva'] + x in targets for x in meta['relocations']))


class TranslationDataTests(unittest.TestCase):
    def test_native_payload_matches_source_manifest(self):
        root = Path(patcher.__file__).resolve().parent
        meta = patcher.json_read(root / 'native/payload.json')
        self.assertEqual(patcher.digest((root / 'native/payload.bin').read_bytes()), meta['sha256'])
        for name, expected in meta['sources'].items():
            source = (root / 'native' / name).read_bytes()
            self.assertNotIn(b'\r', source, 'Generated source must retain LF across checkouts')
            self.assertEqual(patcher.digest(source), expected)

    def test_published_translation_counts_and_font_coverage(self):
        from fontTools.ttLib import TTFont
        root = Path(patcher.__file__).resolve().parent
        font = TTFont(root / 'assets/Chinese.ttf')
        cmap = font.getBestCmap()
        self.assertIn('glyf', font)
        self.assertNotIn('fvar', font)
        for file, count in [('Localizable.csv', 987), ('PlatformLocalizable.csv', 24)]:
            rows = patcher.json_read(root / 'translations' / (file + '.json'))
            self.assertEqual(len(rows), count)
            self.assertEqual([r['index'] for r in rows], list(range(count)))
            for row in rows:
                for c in row['zh']:
                    if ord(c) >= 32:
                        self.assertIn(ord(c), cmap, f'{row["key"]}: {c}')
        font.close()

    @unittest.skipUnless(os.environ.get('FR2_GAME'), 'Optional local game integration check')
    def test_local_game_integration(self):
        import pefile
        game = Path(os.environ['FR2_GAME'])
        source = {n: (game / (n + patcher.BACKUP_SUFFIX)).read_bytes() for n in patcher.ORIGINALS}
        for name, data in source.items():
            self.assertEqual(patcher.digest(data), patcher.ORIGINALS[name])
        result, changed = patcher.build_pak(source['Data.pak'])
        before = zipfile.ZipFile(io.BytesIO(source['Data.pak'].translate(patcher.XOR)))
        after = zipfile.ZipFile(io.BytesIO(result.translate(patcher.XOR)))
        for name in before.namelist():
            if name not in changed:
                self.assertEqual(before.read(name), after.read(name))
        for name in ['Localizable.csv', 'PlatformLocalizable.csv']:
            rows = patcher.json_read(patcher.ROOT / 'translations' / (name + '.json'))
            parsed = [(m.group(1), m.group(2)) for m in re.finditer(r'(?m)^([^\^\r\n]+)\^([^\^\r\n]*)',
                      after.read(name).decode('utf-8')) if m.group(1) != 'Key' and not m.group(1).startswith('//')]
            self.assertEqual(parsed, [(r['key'], r['zh']) for r in rows])
        pe = pefile.PE(data=patcher.build_dll(source['Fieldrunners2.dll']))
        self.assertEqual(pe.sections[-1].Name.rstrip(b'\0'), b'.fr2zh')
        self.assertTrue(pe.OPTIONAL_HEADER.DATA_DIRECTORY[5].Size > 0)


if __name__ == '__main__':
    unittest.main()
