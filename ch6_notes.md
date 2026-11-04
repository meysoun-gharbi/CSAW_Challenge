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
