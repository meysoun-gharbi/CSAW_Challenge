# Challenge 5 — Minions Lockout (SET 2, 350 pts) · ⏸️ NON RÉSOLU (recon + plan)

> **Ports & commandes** : remplace `<PORT>` par ton port série — **`COMx`** sous Windows, **`/dev/ttyUSBx`** (ou `/dev/ttyACMx`) sous Linux/macOS. Utilise **`python`** sous Windows, **`python3`** sous Linux/macOS. Les commandes ci-dessous sont valables pour les deux OS.

Type : **filaire (UART) + attaque matérielle I2C**. Boîte noire.
**En pause** : nécessite du matériel (2ᵉ carte + fils) non disponible au moment de
la recon.

Énoncé : *« …son père a sécurisé l'alarme. Entre sans déclencher l'alarme. À chaque
intrus → lockout, reset nécessaire, le mot de passe change. Ça peut sembler
**bruteal** mais si tu **clock out** tes sentiments, la solution se révèle. »*

---

## 0. Flash
Firmware + wordlist fournis ici : `firmware/5-lockout_merged.bin`,
`minions_wordlist.txt` (157 prénoms de Minions).
```bash
python -m esptool --port <PORT> --baud 460800 write_flash 0x0 firmware/5-lockout_merged.bin
```

## Ce qu'on a établi (recon live)
CLI UART (115200) :
- `unlock_key minion1-minion2` — soumettre une **PAIRE** de noms (du wordlist, séparés par `-`).
- `status` → `{"status":"locked","reason":"bus_fault_lockdown","storage":"I2C_BUS_FAULT","watchdog":"TRIPPED"}`
- `help`, et un **hint** sur demande.

Boot banner : *« Lockout counter: I2C EEPROM (1-strike policy) »*, watchdog 8 s,
*« I2C Bus Fault Detected! BUS FAULT LOCKDOWN »*.
Hint : *« Persistent attempt counters rely on external I2C EEPROM storage.
**Clock out the bus** if security feels locked! For this Challenge **timing is
everything** »*.

## Mécanisme (attaque matérielle I2C)
- Le compteur de lockout « 1-strike » est sur une **EEPROM I2C externe** (fils
  **SDA**/**SCL**). La **FireBeetle ESP32-E n'a pas d'EEPROM** → d'où le
  `bus_fault_lockdown` permanent.
- **« Clock out the bus »** = agir sur la **ligne d'horloge SCL** ; **« timing is
  everything »** = empêcher l'écriture du strike **au moment précis** → compteur
  reste à 0 → **plus de lockout** → brute-force des ~157×157 paires de Minions.

## Plan (quand le matériel sera là)
- **Option A (recommandée)** : une 2ᵉ carte (Arduino/ESP32) **émule l'EEPROM**
  (esclave I2C qui répond compteur=0 et ignore les écritures) → tentatives
  illimitées → script PC qui brute-force les paires sur l'UART.
- **Option B** : glitcher SCL à la masse pile pendant l'écriture du strike.
- À préparer : sketch émulateur EEPROM + script PC de brute-force des paires.
  Broches I2C probables : SDA=IO21, SCL=IO22 (à confirmer en live).

## Fichiers
`firmware/5-lockout_merged.bin`, `minions_wordlist.txt`.
