# Challenge 6 — Silicon Badge (450 pts) — notes

Matériel : ESP32 + RC522 (RFID carte + badge) + Bluetooth/BLE. UART 115200.
Firmware : ../csaw_esc_2026/challenges/SET 3/firmware/6-badge/6-badge_merged.bin (flash 0x0).

## Énoncé (indices)
- « An Agent lost his card and his badge » → carte + badge RFID à exploiter.
- « this soldier doesn't have access to anything classified » → accès limité par défaut.
- « When the same cat crosses the same doorway, look again » → replay / relire ?
- « unlock their secret safe full of keys » → keystore (clés Mifare des secteurs ?).
- « Blue teeth are not for smiles » → Bluetooth/BLE.
- **But : « Find the name of the Architect »** (= flag/objectif).
- « Prepare for a deep dive. »

## Avancement
- [ ] Flasher 6-badge, lire banner + help (découvrir les commandes).
- [ ] Explorer RFID (carte + badge) et BLE.
- [ ] Trouver le keystore / déverrouiller les secteurs.
- [ ] Trouver le nom de l'Architecte.

NB matériel : sur board de substitution (WROOM, pas d'écran), le RFID du firmware peut être
flaky (bus SPI partagé TFT absent + brown-out) — prévoir alim 5V stable.

## Découvertes (session)
MAC board: BC:DD:C2:C1:F6:50 ; BLE: Silicon_Badge_6 @ BC:DD:C2:C1:F6:52

### Commandes firmware
- about -> fw 2.3.1, issuer SHG-GW-2.3.1, build-tag: try-harder{keystream_reuse_is_only_half_the_story}
- get_mac, my_keys (coffre chiffré), unlock [32-hex-key] (auth par keystream)
- enroll_master / clear_card / read_block / dump_card (tap requis 15s)

### Format badge (secteur 2)
- block 8 = LEVEL (ASCII paddé '0' -> 16o) XOR keystream
- block 9 = card id (16o) XOR keystream
- Même keystream réutilisé pour le coffre (my_keys).

### Coffre (my_keys), 80 o = 5 blocs XOR keystream(16o)
9E01E012F5D24A0289A0A5E08971D568 981BEE57EACE134993B4ABE68D73C642
9D0EE657EDC4091889A3A5E78A77D042 8C0BEE57F6C81E1889B4A1E08C7EC642
9303F303E9D14A029FADA5EE8B72D154
- Keystream binaire (MSB pattern 1010 1100 1111 1010) -> PAS ASCII -> non crackable
  depuis 5 blocs seuls. Il FAUT le keystream via le badge (known-plaintext block 8).

### BLE
- Service custom 4bf0ff01-2a01-4c1d-9e6b-123456789abc
  -> char 4bf0ff03-... [read] mais EXIGE bonding (passkey) -> read hang sans pairing.
- Passkey: pas affiché sur UART (pas d'OLED). Source inconnue -> probablement dans le
  coffre déchiffré, OU statique. "keystream_reuse is only HALF" + BLE = l'autre moitié.

## BLOCAGE
RFID flaky (tâche OLED sature le bus/CPU après ~1.3s post-boot) -> enroll_master/dump_card
timeout quasi toujours. Le keystream (clé de tout) vient du badge -> bloqué par le même
problème board que ch2. Hardware RFID prouvé OK (MicroPython lit VER=0x92 + UID).

## Chaîne de solve (théorique)
badge -> keystream -> déchiffrer my_keys -> (passkey BLE ?) -> bond BLE -> read 4bf0ff03 -> Architecte
