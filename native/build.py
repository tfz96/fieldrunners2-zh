"""Build only our added x86 code; no proprietary game files are required."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import capstone
import pefile

ROOT = Path(__file__).resolve().parent
BASE = 0x10000000
RVA = 0x3B1000


def main():
    mingw = Path(os.environ.get('MINGW_BIN', r'D:\mingw64\bin'))
    def tool(name):
        return str(mingw / (name + '.exe')) if (mingw / (name + '.exe')).exists() else shutil.which(name)
    with tempfile.TemporaryDirectory() as tmp:
        obj, exe = Path(tmp) / 'render.o', Path(tmp) / 'render.exe'
        subprocess.run([tool('gcc'), '-m32', '-c', '-Os', '-fno-stack-protector',
                        '-fno-asynchronous-unwind-tables', '-fno-ident', '-fno-builtin',
                        '-fno-pic', str(ROOT / 'render.c'), '-o', str(obj)], check=True)
        subprocess.run([tool('ld'), '-m', 'i386pe', '--image-base', hex(BASE),
                        '--section-start', '.text=0x103b1000', '--section-start', '.rdata=0x103b2000',
                        '--entry', '_render@4', str(obj), '-o', str(exe)], check=True)
        pe = pefile.PE(str(exe))
        sections = [s for s in pe.sections if s.Name.startswith((b'.text', b'.rdata'))]
        end = max(s.VirtualAddress + s.Misc_VirtualSize for s in sections)
        payload = bytearray(end - RVA)
        relocs = []
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        for s in sections:
            data = s.get_data()[:s.Misc_VirtualSize]
            off = s.VirtualAddress - RVA
            payload[off:off + len(data)] = data
            if s.Name.startswith(b'.text'):
                for ins in md.disasm(data, BASE + s.VirtualAddress):
                    for op in ins.operands:
                        if op.type == capstone.x86.X86_OP_IMM and BASE <= op.imm < BASE + 0x500000:
                            if ins.group(capstone.CS_GRP_JUMP) or ins.group(capstone.CS_GRP_CALL):
                                continue  # Relative branch destinations must not be rebased.
                            assert ins.imm_size == 4
                            relocs.append(ins.address - BASE - RVA + ins.imm_offset)
                        if op.type == capstone.x86.X86_OP_MEM and BASE <= op.mem.disp < BASE + 0x500000:
                            assert ins.disp_size == 4
                            relocs.append(ins.address - BASE - RVA + ins.disp_offset)
        # Linker-generated data pointers (e.g. cached translation table) also relocate.
        for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', []):
            for entry in block.entries:
                if entry.type == 3 and RVA <= entry.rva < end:
                    relocs.append(entry.rva - RVA)
        (ROOT / 'payload.bin').write_bytes(payload)
        meta = {'rva': RVA, 'entry_rva': pe.OPTIONAL_HEADER.AddressOfEntryPoint,
                'sha256': hashlib.sha256(payload).hexdigest(), 'relocations': sorted(set(relocs)),
                'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in ['render.c', 'metrics.h', 'fallback.h']}}
        (ROOT / 'payload.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
        pe.close()
        print(f'Built {len(payload)} bytes, {len(set(relocs))} relocation entries')


if __name__ == '__main__':
    main()
