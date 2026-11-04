#!/usr/bin/env python3
"""
Challenge 6 - Silicon Badge : solveur / reproduction (100% live, aucun reverse).

CHAÎNE D'ATTAQUE
----------------
1. enroll_master  -> écrit un badge (secteur 2) et DIVULGUE le plaintext "00000000LEVEL999".
2. read_block 8   -> block 8 brut = plaintext XOR keystream.
      => keystream(16o) = block8  XOR  b"00000000LEVEL999"
3. my_keys        -> coffre de 80o = 5 blocs de 16o, CHACUN XOR le MÊME keystream
      (réutilisation de keystream = "only half the story"). On déchiffre -> codes en clair,
      dont la PASSKEY BLE.
4. [BLE, manuel / nRF Connect] bonding avec la passkey -> lecture caractéristique -> ÉNIGME
      (une citation). L'auteur = "the Architect".
      -> "If you spend more on coffee than on IT security..." = Richard Clarke.
5. Taper le nom au prompt UART -> clarke_gate -> FLAG affiché (UART + écran).

RFID : TAP FRAIS obligatoire (carte absente->présente), ne pas tenir le badge.
BOOT : keystream + passkey changent à CHAQUE reset. Tout doit se faire dans UNE session,
       sans resetter entre l'étape 1 et l'étape 5.

USAGE :
    python3 ch6_solve.py                 # chaîne complète (te guide pour les taps + BLE)
    python3 ch6_solve.py --flag-only     # juste la soumission du nom (si tu as déjà l'auteur)
    python3 ch6_solve.py --name "Richard Clarke"
"""
import sys, time, re, argparse, serial

PLAINTEXT_BADGE = b"00000000LEVEL999"      # divulgué par enroll_master (block 8 en clair)
ARCHITECT       = "Richard Clarke"         # auteur de la citation (énigme BLE)

def drain(ser, secs, stop=None):
    end = time.time() + secs; buf = bytearray()
    while time.time() < end:
        c = ser.read(4096)
        if c:
            buf += c; end = max(end, time.time() + 0.5)
            if stop and stop in buf: break
    return bytes(buf)

def cmd(ser, line, secs=2.0, stop=None):
    ser.reset_input_buffer(); ser.write(line.encode() + b"\r\n"); ser.flush()
    return drain(ser, secs, stop).decode(errors="replace")

def tap_cmd(ser, line, ok_markers, label, tries=10):
    """Commande carte : attend un TAP FRAIS, avec retries sur timeout/busy."""
    for att in range(1, tries + 1):
        print(f"  [{label}] essai {att}/{tries} — FAIS UN TAP FRAIS (approche->touche le badge)...", flush=True)
        ser.reset_input_buffer(); ser.write(line.encode() + b"\r\n"); ser.flush()
        end = time.time() + 16; buf = bytearray()
        while time.time() < end:
            c = ser.read(2048)
            if c:
                buf += c; end = max(end, time.time() + 0.8)
                if any(m in buf for m in ok_markers): return buf.decode(errors="replace")
                if b'"reason":"timeout"' in buf: break
        if b'"reason":"busy"' in buf: time.sleep(1.0)
    return None

def hexblock(txt):
    """Extrait 16 octets (32 hex) de la réponse read_block/dump."""
    m = re.search(r'([0-9A-Fa-f]{32})', txt)
    return bytes.fromhex(m.group(1)) if m else None

def derive_keystream(ser):
    print("[1] enroll_master : enrôle un badge (divulgue le plaintext).")
    tap_cmd(ser, "enroll_master", [b'"ok":true', b"LEVEL999", b"enroll"], "enroll_master")
    print("[2] read_block 8 : récupère block 8 brut -> keystream.")
    r = tap_cmd(ser, "read_block 8", [b'"ok":true', b"block", b'"data"'], "read_block 8")
    if not r: print("  !! pas de block 8 (tap manqué)."); return None
    blk = hexblock(r)
    if not blk: print("  !! block 8 illisible :\n", r); return None
    ks = bytes(b ^ p for b, p in zip(blk, PLAINTEXT_BADGE))
    print(f"    block8   = {blk.hex()}")
    print(f"    plaintext= {PLAINTEXT_BADGE.decode()}")
    print(f"    KEYSTREAM= {ks.hex()}")
    return ks

def decode_vault(ser, ks):
    print("[3] my_keys : déchiffre le coffre (XOR keystream).")
    r = cmd(ser, "my_keys", 2.0)
    m = re.search(r'vault_hex"\s*:\s*"([0-9A-Fa-f]+)"', r) or re.search(r'([0-9A-Fa-f]{160,})', r)
    if not m: print("  !! vault introuvable :\n", r); return None
    vault = bytes.fromhex(m.group(1))
    print(f"    vault_hex ({len(vault)} o) = {vault.hex()}")
    codes = []
    for i in range(0, len(vault), 16):
        dec = bytes(b ^ ks[j] for j, b in enumerate(vault[i:i+16]))
        ascii_ = "".join(chr(c) if 32 <= c < 127 else "." for c in dec)
        digits = re.findall(r'\d{3,}', ascii_)
        codes.append((i // 16, ascii_, digits))
        print(f"    bloc {i//16}: '{ascii_}'   digits={digits}")
    return codes

def submit_name(ser, name):
    print(f"[5] clarke_gate : soumission du nom « {name} »...")
    r = cmd(ser, name, 2.0, stop=b"esc_2026{")
    m = re.search(r"esc_2026\{[^}]*\}", r)
    if m:
        print("\n" + "="*62)
        print("            QUOTE AUTHOR CONFIRMED — FLAG RELEASED")
        print("="*62)
        print("  " + m.group(0))
        print("="*62)
        open("ch6_FLAG.txt", "w").write(m.group(0) + "\n")
        return m.group(0)
    print("  pas de flag. Réponse :\n", r)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--name", default=ARCHITECT, help="auteur de la citation (défaut: Richard Clarke)")
    ap.add_argument("--flag-only", action="store_true", help="ne fait QUE la soumission du nom")
    a = ap.parse_args()
    ser = serial.Serial(a.port, 115200, timeout=0.3)

    if a.flag_only:
        submit_name(ser, a.name); ser.close(); return

    ks = derive_keystream(ser)
    if not ks: ser.close(); return
    codes = decode_vault(ser, ks)
    if codes:
        print("\n  >>> La PASSKEY BLE est le code 6 chiffres du coffre (étiqueté 'ble').")
        print("  >>> Entre-la dans nRF Connect pour t'appairer à Silicon_Badge_6,")
        print("  >>> lis la caractéristique -> énigme -> identifie l'auteur de la citation.\n")
    input("  [BLE] Fais le bonding nRF + lis l'énigme, puis Entrée pour soumettre le nom... ")
    submit_name(ser, a.name)
    ser.close()

if __name__ == "__main__":
    main()
