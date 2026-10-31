# Challenge 5 — « Minions Lockout » (350 pts)

> CSAW Embedded Security Challenge (ESC) 2026 — **SET 2**, thème « smart home ».
> Épreuve **filaire** (*wired*) : se résout en manipulant physiquement le matériel,
> pas seulement en tapant des commandes.

> ## ✅ RÉSOLU
> **`esc_2026{minions_lockout_d222507605fc0af9}`**
> Méthode : **clock out the bus** (SCL débranché = fail-open → essais illimités, jamais de
> lockout) + brute-force des 157×157 paires sur des fenêtres successives jusqu'à aligner la
> bonne paire. 100 % en live, **sans aucun désassemblage**. → voir **§9. Solution**.

---

## 1. Le cadre

Habillage *Moi, moche et méchant* : Margo (fille de Gru) va au bal de promo, son père a
armé l'alarme de la maison, et on doit **entrer sans déclencher l'alarme**.

Concrètement : une **passerelle domotique (gateway)** sur **ESP32** est verrouillée par un
mot de passe. Chaque mauvaise tentative est traitée comme une **intrusion** et enclenche un
mode **lockout**.

Les épreuves sortent par lots. Le SET 2 contient trois challenges :
- **radio** (challenge 3, UDP),
- **web** (challenge 4),
- **filaire** (challenge 5 — celui-ci).

---

## 2. Où sont les fichiers

Dépôt GitHub de l'organisateur (TrustworthyComputing), tout est public :

`github.com/TrustworthyComputing/csaw_esc_2026` → dossier **`challenges/SET 2/`**

| Fichier | Rôle |
|---|---|
| `README.md` | Énoncé des trois challenges du set + texte-énigme de chacun. |
| `firmware/5-lockout/5-lockout_merged.bin` | Firmware à **flasher** sur l'ESP32 → transforme la carte en cible « Minions Lockout ». **On le flashe, on ne le désassemble pas.** |
| `firmware/5-lockout/minions_wordlist.txt` | **157 prénoms de Minions** — le dictionnaire dans lequel le mot de passe est puisé. |
| `img/` | Visuels de présentation. |

Les sous-dossiers `firmware/3-udp` et `firmware/4-web` = challenges 3 et 4 du même set.

---

## 3. Le matériel (kit officiel, identique pour chaque équipe)

- **1× ESP32-WROOM-32** avec écran **ST7789 (135×240)** soudé → la carte cible.
- **1× module EEPROM I2C AT24C256** → mémoire externe à câbler sur le bus I2C de l'ESP32.
- **Câbles Dupont** (M-M, M-F, F-F) + **1× splitter Dupont 2-vers-1**.
- 1× lecteur RFID **RC522** + carte + porte-clés → **autre challenge, pas le 5**.
- 1× câble **USB-C data**.

> Pour le challenge 5, le trio qui compte : **ESP32 (flashé) + AT24C256 + Dupont/splitter**.
> Pas d'analyseur logique, pas de second micro dans le kit — **c'est voulu**.

---

## 4. Comment on interagit

1. **Flasher** `5-lockout_merged.bin` sur l'ESP32 (esptool / Arduino, via l'USB-C).
2. Ouvrir le **port série à 115200 bauds** (`/dev/ttyUSB0` sous Linux) → on tombe sur une
   console texte : le **CLI de la passerelle**.
3. Commandes de base (découvrables en live) :
   - `help` — menu.
   - `status` — état système & stockage.
   - `unlock_key minion1-minion2` — soumettre une **paire** de prénoms (séparés par un tiret)
     pour déverrouiller.
   - `hint` — commande d'indice (**pas forcément listée dans `help`**, à repérer en tâtonnant).
4. L'**EEPROM AT24C256** se câble sur le bus I2C de l'ESP32 (**SDA/SCL + 3V3 via le splitter + GND**).

### Flash — rappel esptool

```bash
# repérer le port
ls /dev/ttyUSB*            # Linux

# flasher le binaire mergé (offset 0x0 car c'est un "merged bin")
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 \
  write_flash 0x0 5-lockout_merged.bin

# ouvrir la console série
# (picocom / screen / minicom / miniterm, 115200 8N1)
picocom -b 115200 /dev/ttyUSB0
```

---

## 5. Le but

Trouver la bonne **paire de Minions** et la soumettre via `unlock_key` pour obtenir le
**flag au format `esc_2026{...}`** — **sans** se faire piéger par le mode lockout qui
s'enclenche à chaque intrusion détectée (et qui, selon l'énoncé, **change aussi le mot de
passe après un reset**).

---

## 6. La règle à ne jamais oublier

> **Le reverse engineering du binaire est INTERDIT.**

La résolution se fait **uniquement en interagissant en live** avec l'interface réelle
(console UART + manipulation physique du matériel).

- Flasher le firmware → **OK**.
- Le désassembler / l'analyser statiquement pour en tirer la solution → **interdit**.

Toute la démarche doit partir de **ce que la cible dit et fait quand on la sollicite**.

---

## 7. L'énigme de l'énoncé

> *« Margo is going to the prom and her father secured the alarm. Try to get in without
> sounding the alarm. Every time an intruder is detected lockout mode starts. A reset will
> be necessary and the password changes. This challenge might sound brutal but if you clock
> out your feelings the solution prompts itself. »*

Lecture au premier degré pour démarrer :
- **« brutal »** → ça *ressemble* à du brute-force.
- il y a un **lockout** à chaque erreur,
- le **mot de passe tourne** après reset,
- la clé est dans l'idée de **« clock out »** — le mot **« clock »** est à creuser,
- le reste se découvre **en sollicitant le device**, notamment via `hint`.

---

## 8. Premiers pas / checklist d'investigation

> Objectif de cette section : un ordre de passage concret pour l'équipe, et une liste
> d'**hypothèses à tester en live** (pas des certitudes). On note tout ce que la cible
> répond — c'est la seule source autorisée.

### Phase 0 — Mise en place (sans rien câbler)

- [ ] Récupérer `5-lockout_merged.bin` + `minions_wordlist.txt` depuis le repo.
- [ ] Flasher le `.bin`, ouvrir la série **115200 8N1**, vérifier qu'on a bien le prompt du CLI.
- [ ] `help` → **relever chaque commande**. Puis tester des commandes **hors menu** : au moins
      `hint`, et tâtonner (`debug`, `dump`, `read`, `eeprom`, `clock`, `time`, `reset`…).
- [ ] `status` → **noter mot pour mot** : état système, état « storage », compteur de
      tentatives, état lockout, toute mention d'horloge / timer / offset.
- [ ] `hint` → lancer **plusieurs fois** (l'indice peut tourner, dépendre de l'état, ou
      débloquer une étape). Consigner chaque sortie.
- [ ] **Ne pas cramer d'essais** `unlock_key` au hasard tant qu'on n'a pas compris le
      mécanisme de lockout + rotation. Chaque essai raté coûte potentiellement un reset.

### Phase 1 — Comprendre le lockout et la rotation

Le cœur du challenge : *« lockout à chaque intrusion + le mot de passe change après reset »*
casse le brute-force naïf (la cible bouge entre deux essais).

- [ ] Déclencher **volontairement 1 seul** mauvais `unlock_key` et observer **précisément** :
      message, passage en lockout, ce que demande la cible (reset ?), ce que `status` affiche après.
- [ ] Faire le reset demandé et **comparer** : le comportement / l'indice / la « cible »
      a-t-il changé ? → confirme ou non la rotation.
- [ ] Chercher **de quoi dépend** la rotation : un compteur ? une horloge interne ? une valeur
      persistée ? (`status`, `hint`, messages d'erreur sont les seules fenêtres autorisées.)

### Phase 2 — Le rôle de l'EEPROM AT24C256 (le « filaire »)

Le kit impose une **EEPROM externe** + un **splitter 2-vers-1** et **interdit le logic
analyzer**. Donc l'astuce passe par **ce qu'on fait physiquement du bus I2C**, pas par
l'écoute passive.

Pistes à tester (une par une, en notant l'effet) :

- [ ] **Câbler l'EEPROM** proprement : `SDA`, `SCL`, `3V3` (via splitter), `GND`. Voir si
      `status` / le boot détecte le module et change de comportement.
- [ ] Hypothèse **« la cible persiste son état dans l'EEPROM »** : le compteur de tentatives /
      la graine de rotation / le mot de passe courant y seraient stockés. → tester si une
      commande CLI permet de **lire ou dumper** ce stockage (« clock out the data »).
- [ ] Hypothèse **« geler l'horloge » (`clock out`)** : si la rotation dépend d'une horloge
      ou d'écritures I2C vers l'EEPROM, **empêcher/figer ces écritures** (jouer sur `SCL`, le
      splitter, ou retirer l'EEPROM au bon moment) pourrait **stopper la rotation** → le mot
      de passe redevient **fixe**, et le brute-force (« brutal ») des paires redevient viable.
- [ ] Hypothèse **« EEPROM pré-provisionnée »** : vérifier si le module doit contenir / contient
      une valeur que la cible lit au boot (et donc si on peut influencer ce qu'elle lit).

> ⚠️ Ces 3 pistes sont des **hypothèses** cohérentes avec les indices (`clock`, EEPROM imposée,
> splitter, pas de logic analyzer). À **valider ou éliminer en live** — ne pas les traiter comme acquises.

### Phase 3 — Attaque de la paire de Minions

Une fois la rotation neutralisée **ou** comprise :

- [ ] Modéliser l'espace : **157 prénoms**, soumission par **paire `a-b`** → au plus ~157×157
      combinaisons (vérifier si l'ordre compte, si `a == b` est permis — à déduire des réponses).
- [ ] Vérifier **comment répond** `unlock_key` sur une paire fausse mais **bien formée** vs
      malformée → chercher un éventuel **oracle** (message/latence différents) qui distingue
      « format OK, paire fausse » de « proche ».
- [ ] Scripter l'envoi série **seulement si** le lockout a été neutralisé (sinon on se bloque).
      Débit prudent, lecture de la réponse entre chaque essai.
- [ ] Récupérer le **flag `esc_2026{...}`** et le consigner.

### À garder en tête

- **Journaliser chaque session** (copie brute de la console) : les indices et messages sont
  la matière première, et l'état peut ne pas être reproductible après un reset.
- **Interdit = désassembler / analyser le `.bin`.** Tout ce qui est écrit ici se vérifie
  **au device**, pas dans le binaire.
- Si un essai met la cible en lockout, **comprendre d'abord la condition de sortie** avant
  de ré-essayer, sinon on brûle des resets (et on fait tourner le mot de passe).

---

## 9. Solution (write-up complet)

> **FLAG : `esc_2026{minions_lockout_d222507605fc0af9}`**
> Résolu uniquement par interaction live (UART + manipulation physique du bus I2C).
> **Aucun désassemblage du binaire.**

### 9.1 Mécanique réelle (découverte au device)

Bannière de boot : `Lockout counter: I2C EEPROM (1-strike policy)` + `Hardware diagnostics
watchdog: 8.0s interval`. Commande cachée `hint` :

> *« Persistent attempt counters rely on external I2C EEPROM storage. Clock out the bus if
> security feels locked! For this Challenge timing is everything »*

Comportement observé, état par état :

| État du bus I2C | `storage` (status) | Compteur d'échecs | Essais `unlock_key` | Déverrouillage possible ? |
|---|---|---|---|---|
| **Sain** (SCL branché) | `I2C_EEPROM` | lisible ; **1 mauvais essai → `fail_counter=1` → lock immédiat** | **1 seul** puis refusés | ✅ (mdp lisible) mais 1 essai |
| **Fail-open** (SCL débranché, <8 s) | `I2C_EEPROM_NAK (FAILOPEN)` | lecture NAK → **traité comme 0 → jamais de lock** | **illimités**, tous évalués | ✅ **oui** (le mdp n'est PAS dans l'EEPROM) |
| **Bus fault** (SCL débranché ≥8 s) | `I2C_BUS_FAULT`, `watchdog:TRIPPED` | — | tous refusés (`bus_fault_lockdown`) | ❌ |

Points clés établis expérimentalement :

1. **1-strike** : un seul mauvais essai sur bus sain verrouille (`too_many_failed_attempts`).
   Pendant le lock, `unlock_key` est **refusé sans être évalué**.
2. **Seul le compteur est dans l'EEPROM externe** (comme dit l'indice). Le **mot de passe est
   interne** (flash/RAM) → **lisible même bus coupé** → on peut déverrouiller en fail-open.
3. **Fail-open** : SCL débranché → l'EEPROM NAK → le firmware lit le compteur comme 0
   (*fail-open*) → **plus aucun lockout**, on peut spammer les essais. Mais le **watchdog
   coupe à 8,0 s** pile (`BUS FAULT LOCKDOWN`).
4. **Le mot de passe CHANGE** à **chaque** recovery de bus (`{"status":"bus_recovered",
   "event":"password_changed"}`) **et** à chaque reset. Il n'est donc **figé que dans une
   seule fenêtre fail-open continue** (~8 s). Chaque nouvelle fenêtre = **nouveau mot de passe**.
5. **WP (write-protect) inopérant** sur le module bleu AT24C256 fourni (le pin WP du header
   ne commande pas la puce) → impossible de bloquer juste l'écriture du compteur. Impasse.
6. **Pas de course** : sur bus sain, le verrou s'arme synchroniquement (1 essai évalué, puis
   `locked`). Spammer ne fait rien passer de plus.

### 9.2 L'attaque

Conséquence des points ci-dessus : le seul couple gagnant est **fail-open (essais illimités)
+ mot de passe interne (déverrouillable)**. Comme le mot de passe **tourne à chaque fenêtre**,
on ne peut pas le cibler ; on gagne par **coïncidence** : balayer les paires sur des fenêtres
successives jusqu'à tomber sur une fenêtre dont le **mot de passe courant = la paire testée**.

- Espace : 157 noms → paires `minion1-minion2` → **157×157 = 24 964** (ordonnées, répétitions
  incluses ; le fichier lu donnait 158 lignes non vides → 24 964 dans le script).
- Débit UART : ~**20-35 essais/s** (proc interne ~11 ms/essai), soit ~**110-180 essais par
  fenêtre** de 8 s.
- Pour enchaîner les fenêtres **sans les mains**, on **reset par DTR** (ligne série) à chaque
  fenêtre : chaque boot rouvre une fenêtre fail-open (SCL reste débranché). Reset = nouveau
  mot de passe, mais ça n'a pas d'importance (on joue la coïncidence de toute façon).
- **Proba ≈ 63 % par passe complète** des 24 964 paires (espérance ~1 touche/passe).
  En pratique **1-2 passes** suffisent (~12 min/passe). Touche obtenue cette fois vers
  l'indice ~12 550 (≈50 % de la 1ʳᵉ passe « chanceuse »).

Réponse de succès (texte brut UART) :
```json
{"status":"unlocked","flag":"esc_2026{minions_lockout_d222507605fc0af9}"}
```

### 9.3 Flow de test / reproduction

1. **Flash** : `esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 5-lockout_merged.bin`
2. **Série** : 115200 8N1 sur `/dev/ttyUSB0`.
3. **Câblage EEPROM** : SDA, SCL, 3V3 (VCC), GND entre l'ESP32 et l'AT24C256.
   Mettre **SCL sur un jumper débranchable** (ou via le splitter).
4. **Débrancher SCL** → la carte passe en fail-open (`status` affiche `I2C_EEPROM_NAK
   (FAILOPEN)`, `fail_counter:0`). Laisser débranché, mains off ensuite.
5. **Lancer le brute-force auto** (ci-dessous) : il resette par DTR à chaque fenêtre et
   bombarde les paires ; il s'arrête dès qu'il voit `unlocked`/`esc_2026{`.
6. Au bout d'**1-2 passes**, une fenêtre aligne la bonne paire → **flag**.

> Vérif d'état utile à tout moment : `status`
> - sain : `{"status":"locked","reason":"ready","storage":"I2C_EEPROM","fail_counter":0}`
> - fail-open : `...,"storage":"I2C_EEPROM_NAK (FAILOPEN)","fail_counter":0}`
> - fault : `...,"reason":"bus_fault_lockdown","watchdog":"TRIPPED"}`

### 9.4 Script de résolution (minimal, reproductible)

> Prérequis : `pip install pyserial`. **SCL débranché** avant de lancer. Mains off : le script
> gère seul les resets (DTR) et donc l'enchaînement des fenêtres.

```python
#!/usr/bin/env python3
# solve5.py  --  SCL DEBRANCHE (fail-open). Lance: python3 solve5.py
import time, serial
PORT="/dev/ttyUSB0"; BAUD=115200
WL="minions_wordlist.txt"          # les 157 noms fournis
ns=[l.strip() for l in open(WL) if l.strip()]
pairs=[f"{a}-{b}" for a in ns for b in ns]        # 157x157
ser=serial.Serial(PORT,BAUD,timeout=0.03)

def boot():                                        # reset DTR -> nouvelle fenetre fail-open
    ser.setDTR(False); ser.setRTS(True); time.sleep(0.07); ser.setRTS(False)
    end=time.time()+1.6; b=b""
    while time.time()<end:
        b+=ser.read(512)
        if b"UART CLI active" in b: break
    ser.reset_input_buffer()

while True:                                        # passes successives jusqu'au flag
    i=0
    while i<len(pairs):
        boot()
        deadline=time.time()+7.2                    # fenetre avant trip watchdog (8s)
        while time.time()<deadline and i<len(pairs):
            batch=pairs[i:i+12]
            for p in batch: ser.write(f"unlock_key {p}\r\n".encode())
            ser.flush(); time.sleep(0.25)
            resp=ser.read(8192)
            if b"esc_2026{" in resp or b'"unlocked"' in resp:
                print("FLAG:", resp.decode(errors="replace")); raise SystemExit
            j=resp.count(b'"invalid_key"')          # avancer seulement sur les essais evalues
            if j==0: break                          # fenetre finie -> reset
            i+=min(j,len(batch))
        print(f"progress {i}/{len(pairs)}")
```

### 9.5 Impasses testées (pour mémoire)

- **WP → 3V3** (bloquer l'écriture du compteur) : sans effet sur ce module → écrasé.
- **SCL coupé en continu** : watchdog trippe à 8 s → `bus_fault_lockdown`, tout refusé.
- **Brute-force bus sain** : 1 essai/mot de passe (lock immédiat), effacer le compteur change
  le mdp → non viable.
- **Écran ST7789** : HS sur le board reçu → inexploitable (tout est passé par l'UART).
- **Commandes cachées / leak** : seules `unlock_key` / `status` / `help` / `hint` ; aucune
  fuite de mot de passe (y compris sur l'événement `bus_recovered`).
