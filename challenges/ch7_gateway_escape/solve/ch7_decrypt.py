#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dechiffre un log_XXX.enc du Challenge 7 (AES-256-CBC, IV = 16 premiers octets).

Pre-requis : pip install cryptography

Usage :
  python ch7_decrypt.py ch7_fw/logs/log_015.enc ch7_fw/logs/log_015.csv \
         9c9b3432666fa8286a25e012e729eb97edaeedb4dd0e8c1b152c60927ad89665
(la cle = le champ "aes_key_hex" lu dans la caracteristique BLE)
"""
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

if len(sys.argv) != 4:
    sys.exit("usage: python ch7_decrypt.py <in.enc> <out.csv> <aes_key_hex>")

in_path, out_path, key_hex = sys.argv[1], sys.argv[2], sys.argv[3]
key = bytes.fromhex(key_hex)          # 32 octets = AES-256

raw = open(in_path, "rb").read()      # tout le fichier chiffre
iv, ct = raw[:16], raw[16:]           # IV = 16 premiers octets ; le reste = donnees chiffrees

# ouverture du "cadenas" AES-CBC
dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
pt = dec.update(ct) + dec.finalize()

# retrait du "bourrage" PKCS7 (octets de remplissage ajoutes a la fin)
pad = pt[-1]
if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
    pt = pt[:-pad]

open(out_path, "wb").write(pt)
print(f"OK -> {out_path}  ({len(pt)} octets)")
# apercu
head = pt[:200].decode("utf-8", "replace")
print("--- debut du fichier dechiffre ---")
print(head)
