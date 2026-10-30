#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Challenge 7 — interaction BLE (lecture des infos, puis evasion).

Deux sous-commandes :
  read   : scanne, se connecte, lit les 3 caracteristiques (indice, cle AES +
           log_id, et la write-char d'horloge).
  escape : regle l'horloge sur l'instant non-garde (--epoch) puis envoie `escape`
           sur l'UART (le CLI UART n'est actif QUE si une connexion BLE est ouverte)
           et affiche le flag.

Pre-requis : pip install bleak  (+ pyserial pour `escape`)

Exemples (Windows ; adapter le port serie) :
  python ch7_ble.py read
  python ch7_ble.py escape --epoch 1767242895 --port COM12

NOTE MATERIEL : l'ESP32 ARRETE d'emettre en BLE apres chaque deconnexion ->
appuyer sur RESET avant chaque lancement. Le CLI UART affiche "connect via BLE
first" tant qu'aucun central n'est connecte.
"""
from __future__ import annotations
import argparse, asyncio, re, sys, time

# UUIDs du service custom (vus a l'enumeration GATT)
SVC   = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
MSG   = "beb5483e-36e1-4688-b7f5-ea07361b26a8"   # read : l'indice
DATA  = "d0e12345-6789-4abc-def0-123456789abc"   # read : {log_id, aes_key_hex, drive_url}
CLOCK = "cba1d466-344c-4be3-ab3f-189f80dd7518"   # write: CLOCK_SET_CHAR (epoch SECONDES, ASCII)
NAME  = "Gateway_Escape_7"
FLAGRE = re.compile(r"(esc_2026|ESC)\{[^}]*\}", re.I)


async def find():
    from bleak import BleakScanner
    dev = await BleakScanner.find_device_by_address(ADDR, timeout=15.0) if ADDR else None
    if not dev:
        dev = await BleakScanner.find_device_by_name(NAME, timeout=12.0)
    return dev


async def cmd_read():
    from bleak import BleakClient
    dev = await find()
    if not dev:
        sys.exit("Appareil non trouve (reboote la carte pour relancer l'advertising).")
    async with BleakClient(dev, timeout=20.0) as c:
        print("connecte:", c.is_connected)
        for name, uuid in (("INDICE", MSG), ("DATA", DATA)):
            v = await c.read_gatt_char(uuid)
            print(f"[{name}] {v.decode('utf-8','replace')}")
        print("[CLOCK] caracteristique en ecriture (regler l'epoch ici)")


def uart_open(port):
    import serial
    s = serial.Serial(); s.port = port; s.baudrate = 115200; s.timeout = 0.3
    s.dtr = False; s.rts = False; s.open(); time.sleep(0.2); s.reset_input_buffer()
    return s


def uart_drain(s, w):
    end = time.time() + w; b = b""
    while time.time() < end:
        n = s.in_waiting
        if n: b += s.read(n)
        else: time.sleep(0.03)
    return b.decode("utf-8", "replace")


async def cmd_escape(epoch, port):
    from bleak import BleakClient
    s = uart_open(port)
    dev = await find()
    if not dev:
        sys.exit("Appareil non trouve (reboote la carte).")
    async with BleakClient(dev, timeout=20.0) as c:
        print("connecte:", c.is_connected); uart_drain(s, 0.8)
        print(f">>> set clock {epoch} (epoch SECONDES)")
        await c.write_gatt_char(CLOCK, str(epoch).encode(), response=True)
        print(uart_drain(s, 5.0).strip()[-200:])   # attend GUARDED -> UNGUARDED
        for attempt in range(6):
            s.reset_input_buffer()
            print(f">>> escape (essai {attempt+1})")
            s.write(b"escape\n")
            u = uart_drain(s, 4.0)
            print(u.strip()[-300:])
            m = FLAGRE.search(u)
            if m:
                print("\n*** FLAG ***", m.group(0)); break
            if "initial" in u.lower():   # "System initialising - wait"
                time.sleep(4)
    s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("read")
    pe = sub.add_parser("escape")
    pe.add_argument("--epoch", type=int, required=True, help="epoch SECONDES du moment non-garde")
    pe.add_argument("--port", default="COM12", help="port serie (COM12, /dev/ttyUSB0...)")
    ap.add_argument("--addr", default="", help="adresse BLE (optionnel ; sinon recherche par nom)")
    args = ap.parse_args()
    ADDR = args.addr
    if args.cmd == "read":
        asyncio.run(cmd_read())
    else:
        asyncio.run(cmd_escape(args.epoch, args.port))
