#!/usr/bin/env python3
"""
Challenge 2 - EEPROM Secrets : solveur automatique (100% live, aucun reverse).

LOGIQUE
-------
1. dump_eeprom -> base de config XORée avec une "clé = identité répétée".
   On retrouve la clé (c'est une MAC de 6 octets qui se répète) en s'appuyant
   sur un plaintext connu : les enregistrements finissent par "_GW".
   On décode -> on lit le credential 4 octets du gateway "Master_GW"
   = [suffix MAC 3o][niveau 1o]  (ex: 54 F2 A5 99).
2. La carte stocke une "visite" en block 5 : [suffix][réponse] (ex: C1 F6 50 FF = refusé).
   On FORGE une visite Master accordée : write_block 5 = <credential Master>.
3. Un tap déclenche la vérif -> "Access Granted" -> flag esc_2026{...}.

RFID : le firmware ignore une carte TENUE ; il faut un TAP FRAIS
       (carte absente -> présente). Le script te demande de taper au bon moment.

USAGE :  python3 ch2_solve.py   [--port /dev/ttyUSB0]
"""
import sys, time, re, argparse, serial

def drain(ser, secs, stop=None):
    end = time.time() + secs; buf = bytearray()
    while time.time() < end:
        try: c = ser.read(4096)
        except Exception: time.sleep(0.1); continue
        if c:
            buf += c; end = max(end, time.time() + 0.6)
            if stop and stop in buf: break
    return buf.decode(errors="replace")

def cmd(ser, line, secs=3, stop=None):
    ser.reset_input_buffer(); ser.write(line.encode() + b"\r\n"); ser.flush()
    return drain(ser, secs, stop)

def parse_eeprom(txt):
    cells = {}
    for ln in txt.replace("\r", "").splitlines():
        m = re.match(r'^([0-9A-Fa-f]{4}):\s+((?:[0-9A-Fa-f]{2}\s+)+)', ln)
        if m:
            off = int(m.group(1), 16)
            for k, x in enumerate(m.group(2).split()):
                cells[off + k] = int(x, 16)
    return cells

def recover_key_and_decode(cells):
    """La clé est une MAC 6o répétée (key[o] = MAC[(o+phase)%6]).
    On la retrouve via le plaintext connu '_GW' + noms, en testant toutes les
    phases et en cherchant un décodage contenant 'Master_GW'."""
    offs = sorted(cells)
    # candidats de clé : on reconstruit 6 octets consécutifs depuis un plaintext
    # supposé. Plus simple et robuste : brute force la clé octet par octet en
    # imposant que le décodage global contienne les noms de gateways.
    # Ici : on teste les 6 phases d'une MAC lue dans le 1er enregistrement
    # grâce au fait que block0 (0x10) commence par un nom ASCII + '_GW'.
    for phase in range(6):
        # suppose cells commence ~0x10 ; on tente de deviner la clé par
        # contrainte ASCII sur les 6 premières colonnes de plusieurs records.
        pass
    # Méthode directe : brute force chaque octet de clé (6) pour maximiser
    # les caractères imprimables sur l'ensemble.
    base = min(offs)
    best = None
    import itertools
    # trop grand pour 6 octets en aveugle -> on s'appuie sur '_GW' à offset fixe.
    # Les records font 16 o ; le nom finit par "_GW\0". On cherche la clé telle
    # que le décodage d'un bloc donne "..._GW".
    for start in offs[:32]:
        for name_guess in (b"Lobby_GW", b"Office_GW"):
            L = len(name_guess)
            if all((start + i) in cells for i in range(L)):
                # clé partielle sur ces colonnes
                kcols = {(start + i): cells[start + i] ^ name_guess[i] for i in range(L)}
                # étend en clé 6o répétée : clé[o%... ] -> il faut l'alignement.
                # on déduit period-6 : k[(start+i) % 6] = kcols
                key = [None] * 6
                for pos, kv in kcols.items():
                    key[pos % 6] = kv
                if None in key:
                    continue
                dec = "".join(chr(cells[o] ^ key[o % 6]) if 32 <= (cells[o] ^ key[o % 6]) < 127 else "."
                               for o in offs)
                if "Master_GW" in dec:
                    return key, {o: cells[o] ^ key[o % 6] for o in offs}
    return None, None

def find_master_credential(dec_bytes):
    offs = sorted(dec_bytes)
    s = bytes(dec_bytes[o] for o in offs)
    i = s.find(b"Master_GW")
    if i < 0:
        return None
    rec_start = offs[i] & ~0xF            # début du record 16o
    cred = bytes(dec_bytes[rec_start + 12 + j] for j in range(4))  # 4 derniers octets
    return cred

def tap_command(ser, line, ok_markers, label, tries=8):
    """Envoie une commande carte et attend un TAP FRAIS, avec retries."""
    for att in range(1, tries + 1):
        print(f"  [{label}] essai {att}/{tries} — FAIS UN TAP FRAIS (approche->touche)...", flush=True)
        ser.reset_input_buffer(); ser.write(line.encode() + b"\r\n"); ser.flush()
        end = time.time() + 16; buf = bytearray()
        while time.time() < end:
            try: c = ser.read(2048)
            except Exception: time.sleep(0.05); continue
            if c:
                buf += c; end = max(end, time.time() + 0.8)
                if b'"reason":"timeout"' in buf: break
                if any(m in buf for m in ok_markers): return buf.decode(errors="replace")
        if b'"reason":"busy"' in buf:
            time.sleep(1.0)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    a = ap.parse_args()
    ser = serial.Serial(a.port, 115200, timeout=0.3)

    print("[1] Lecture + décodage EEPROM...")
    # reset pour une init propre, puis dump
    ser.setDTR(False); ser.setRTS(True); time.sleep(0.1); ser.setRTS(False); time.sleep(2.5)
    drain(ser, 1.0)
    dump = cmd(ser, "dump_eeprom", 6, stop=b"-----------------------")
    cells = parse_eeprom(dump)
    key, dec = recover_key_and_decode(cells)
    if not key:
        print("  !! clé non retrouvée — EEPROM inattendue. Dump brut:\n", dump); return
    print("  clé (identité) :", bytes(key).hex())
    cred = find_master_credential(dec)
    if not cred:
        print("  !! Master_GW introuvable dans le décodage."); return
    print("  Master_GW credential =", cred.hex().upper(), "-> on le forge en block 5")

    print("[2] Forge de la visite Master : write_block 5 =", cred.hex())
    r = tap_command(ser, f"write_block 5 {cred.hex()}", [b'"ok":true'], "write_block")
    if not r:
        print("  !! write_block échoué (pas de tap ?)."); return
    print("  block 5 écrit.")

    print("[3] Tap de vérification -> on attend le flag...")
    r = tap_command(ser, "", [b"esc_2026{", b"Access Granted"], "verify") if False else None
    # un simple tap suffit : on écoute pendant que tu tapes
    print("  TAPE LA CARTE (tap frais) — écoute 20s...")
    buf = drain(ser, 20, stop=b"esc_2026{")
    m = re.search(r"esc_2026\{[^}]*\}", buf)
    if m:
        print("\n[FLAG]", m.group(0))
        open("ch2_FLAG.txt", "w").write(m.group(0) + "\n")
    else:
        print("  pas de flag capté — re-tape et relance l'écoute. Sortie:\n", buf[-400:])
    ser.close()

if __name__ == "__main__":
    main()
