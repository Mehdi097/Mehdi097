#!/usr/bin/env python3
"""Fabrique un lanceur Windows PE32+ natif (aucun compilateur nécessaire).

    python3 tools/make_launcher.py

Produit ``release/TraderDesk-Launcher.exe`` : un vrai exécutable Windows x64
qui lance ``py -3 run.py`` (ou ``python run.py``) depuis le dossier où il se
trouve, donc le dashboard TraderDesk s'ouvre dans le navigateur au double-clic.

Ce lanceur suppose Python 3 installé sur le PC. Pour un .exe **autonome**
(qui embarque Python, aucun prérequis), utilisez ``build_windows.bat`` :
PyInstaller doit tourner sur Windows, c'est ce que fait aussi le workflow CI.

Le fichier PE est écrit à la main (headers COFF/PE32+, table d'imports
KERNEL32.dll : WinExec + ExitProcess, code x86-64 minimal). Vérifiable avec :

    pip install pefile && python -c "import pefile; print(pefile.PE('release/TraderDesk-Launcher.exe'))"
"""

import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "release" / "TraderDesk-Launcher.exe"

# Chaîne de commande exécutée au double-clic (WinExec -> cmd.exe).
CMD = ('cmd /c "title TraderDesk && (py -3 run.py || python run.py || '
       'start https://www.python.org/downloads/)"').encode("ascii") + b"\0"

IMAGE_BASE = 0x140000000
RVA_TEXT, RVA_IDATA = 0x1000, 0x2000
RAW_TEXT, RAW_IDATA = 0x200, 0x400
FILE_ALIGN, SECT_ALIGN = 0x200, 0x1000

# Offsets dans .idata
ILT, IAT, DLLNAME, HINT1, HINT2 = 0x2030, 0x2050, 0x2070, 0x2090, 0x20A0
STR_RVA = 0x1100


def code():
    """Code x86-64 minimal : WinExec(cmd, SW_SHOWNORMAL); ExitProcess(0)."""
    b = bytearray()
    b += b"\x48\x83\xec\x28"                                   # sub rsp, 28h
    # lea rcx, [rip + disp] -> CMD
    lea_at = RVA_TEXT + len(b)
    disp = STR_RVA - (lea_at + 7)
    b += b"\x48\x8d\x0d" + struct.pack("<i", disp)
    b += b"\xba\x01\x00\x00\x00"                               # mov edx, 1
    call1_at = RVA_TEXT + len(b)
    disp1 = IAT - (call1_at + 6)
    b += b"\xff\x15" + struct.pack("<i", disp1)               # call [IAT.WinExec]
    b += b"\x31\xc9"                                           # xor ecx, ecx
    call2_at = RVA_TEXT + len(b)
    disp2 = (IAT + 8) - (call2_at + 6)
    b += b"\xff\x15" + struct.pack("<i", disp2)               # call [IAT.ExitProcess]
    b += b"\xcc"                                               # int3 (ne doit pas être atteint)
    return bytes(b)


def text_section():
    buf = bytearray(b"\x00" * FILE_ALIGN)
    c = code()
    buf[:len(c)] = c
    buf[STR_RVA - RVA_TEXT:STR_RVA - RVA_TEXT + len(CMD)] = CMD
    return bytes(buf)


def idata_section():
    buf = bytearray(b"\x00" * FILE_ALIGN)

    def put(rva, data):
        buf[rva - RVA_IDATA:rva - RVA_IDATA + len(data)] = data

    # IMAGE_IMPORT_DESCRIPTOR (+ descripteur nul de fin)
    put(RVA_IDATA, struct.pack("<IIIII", ILT, 0, 0, DLLNAME, IAT))
    # ILT / IAT : deux pointeurs vers les Hint/Name + terminateur
    thunks = struct.pack("<QQQ", HINT1, HINT2, 0)
    put(ILT, thunks)
    put(IAT, thunks)
    put(DLLNAME, b"KERNEL32.dll\0")
    put(HINT1, struct.pack("<H", 0) + b"WinExec\0" + b"\0")
    put(HINT2, struct.pack("<H", 0) + b"ExitProcess\0" + b"\0")
    return bytes(buf)


def dos_header():
    h = bytearray(0x80)
    h[0:2] = b"MZ"
    struct.pack_into("<I", h, 0x3C, 0x80)
    msg = b"This is a Win64 TraderDesk launcher.\r\r\n$"
    h[0x40:0x40 + len(msg)] = msg
    return bytes(h)


def coff_header():
    return struct.pack("<HHIIIHH", 0x8664, 2, 0, 0, 0, 0xF0, 0x0022)


def optional_header():
    o = bytearray(0xF0)
    struct.pack_into("<H", o, 0x00, 0x20B)      # PE32+
    o[0x02], o[0x03] = 1, 0
    struct.pack_into("<I", o, 0x04, FILE_ALIGN)   # SizeOfCode
    struct.pack_into("<I", o, 0x08, FILE_ALIGN)   # SizeOfInitializedData
    struct.pack_into("<I", o, 0x10, RVA_TEXT)     # AddressOfEntryPoint
    struct.pack_into("<I", o, 0x14, RVA_TEXT)     # BaseOfCode
    struct.pack_into("<Q", o, 0x18, IMAGE_BASE)
    struct.pack_into("<I", o, 0x20, SECT_ALIGN)
    struct.pack_into("<I", o, 0x24, FILE_ALIGN)
    struct.pack_into("<H", o, 0x28, 4)            # MajorOSVersion
    struct.pack_into("<H", o, 0x30, 4)            # MajorSubsystemVersion
    struct.pack_into("<I", o, 0x38, 0x3000)      # SizeOfImage
    struct.pack_into("<I", o, 0x3C, 0x200)       # SizeOfHeaders
    struct.pack_into("<H", o, 0x44, 3)           # Subsystem = console
    struct.pack_into("<Q", o, 0x48, 0x100000)    # SizeOfStackReserve
    struct.pack_into("<Q", o, 0x50, 0x1000)      # SizeOfStackCommit
    struct.pack_into("<Q", o, 0x58, 0x100000)    # SizeOfHeapReserve
    struct.pack_into("<Q", o, 0x60, 0x1000)      # SizeOfHeapCommit
    struct.pack_into("<I", o, 0x6C, 16)          # NumberOfRvaAndSizes
    struct.pack_into("<II", o, 0x70 + 1 * 8, RVA_IDATA, 40)   # Import directory
    struct.pack_into("<II", o, 0x70 + 12 * 8, IAT, 16)        # IAT directory
    return bytes(o)


def section(name, vsize, vaddr, rawsize, rawptr, chars):
    return (name.encode().ljust(8, b"\0") +
            struct.pack("<IIIIIIHHI", vsize, vaddr, rawsize, rawptr,
                        0, 0, 0, 0, chars))


def build():
    headers = bytearray()
    headers += dos_header()
    headers += b"PE\0\0"
    headers += coff_header()
    headers += optional_header()
    headers += section(".text", FILE_ALIGN, RVA_TEXT, FILE_ALIGN, RAW_TEXT, 0x60000020)
    headers += section(".idata", FILE_ALIGN, RVA_IDATA, FILE_ALIGN, RAW_IDATA, 0xC0000040)
    headers += b"\0" * (FILE_ALIGN - len(headers))
    assert len(headers) == FILE_ALIGN
    return bytes(headers) + text_section() + idata_section()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = build()
    OUT.write_bytes(blob)
    print("Écrit %s (%d octets) — PE32+ x64, imports KERNEL32!WinExec / ExitProcess" %
          (OUT, len(blob)))
    try:
        import pefile  # type: ignore
        pe = pefile.PE(str(OUT))
        print("PE valide : machine=0x%x, entry=0x%x, sections=%s, imports=%s" %
              (pe.FILE_HEADER.Machine, pe.OPTIONAL_HEADER.AddressOfEntryPoint,
               [s.Name.rstrip(b"\0").decode() for s in pe.sections],
               [(d.dll.decode(), [i.name.decode() for i in d.imports])
                for d in pe.DIRECTORY_ENTRY_IMPORT]))
    except ImportError:
        print("(installez pefile pour valider le PE : pip install pefile)")


if __name__ == "__main__":
    main()
