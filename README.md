# ESC 2026 — Harnais d'agent LLM instrumenté (ESP32 / Serial Gateway)

Orchestrateur **multi-backend** (Gemini / Claude / mock) qui pilote un agent LLM
pour résoudre les challenges **CSAW Embedded Security Challenge 2026** sur carte
ESP32, **entièrement mesuré** (requêtes cible / tokens / temps / succès /
répétabilité) — les métriques notées par le règlement (correction, support IA,
performance, livrables).

> **Cadrage règlement.** On ne *reverse* pas le flag depuis le binaire (interdit).
> Toute la résolution se fait **en live**, via l'interface réelle de la carte
> (UART, Wi-Fi, …). C'est la méthode attendue et légitime.

> **Note pour l'équipe.** Les exemples utilisent des **placeholders** :
> remplace `<PORT>` par **ton** port série et `<MODELE>` par le modèle choisi.
> Lance toujours les commandes **depuis le dossier du projet** (celui qui contient
> `run_challenge1.py`) ; aucun chemin absolu n'est supposé.

---

## 1. Étape 0 — Récupérer le firmware et flasher la carte

À faire **une fois** par personne, avant tout le reste.

### a) Pilote USB — **à installer si la carte n'est pas détectée**
La carte communique via une puce pont USB-série. **Symptôme d'un pilote manquant :**
aucun nouveau port n'apparaît quand tu branches la carte (pas de `COMx` sous
Windows, pas de `/dev/ttyUSB*`/`ttyACM*` sous Linux — voir §4), ou un périphérique
« inconnu » dans le Gestionnaire de périphériques.

- **Windows** : installe le pilote de la puce (la carte Ideaspark ESP32 utilise le
  plus souvent un **CP210x**) :
  - **CP210x (Silicon Labs)** : https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
  - **CH340 (WCH)** si ta carte en est équipée : http://www.wch-ic.com/downloads/CH341SER_ZIP.html
  → après installation, **débranche/rebranche** la carte, puis revérifie le port (§4).
- **Linux / macOS** : les pilotes CP210x et CH340 sont en général **déjà inclus**
  (le port apparaît directement). Sinon, installe le module du fabricant.

### b) Récupérer le binaire du challenge 1
Dépôt officiel : **https://github.com/TrustworthyComputing/csaw_esc_2026**
Le firmware du challenge 1 (Serial Gateway) :
```
challenges/SET 1/firmware/1-serial/1-serial_merged.bin
```
Deux façons de l'obtenir :
```bash
# Option 1 — cloner tout le dépôt
git clone https://github.com/TrustworthyComputing/csaw_esc_2026.git

# Option 2 — télécharger juste le binaire (attention a l'espace dans "SET 1" -> %20)
curl -L -o 1-serial_merged.bin \
  "https://raw.githubusercontent.com/TrustworthyComputing/csaw_esc_2026/main/challenges/SET%201/firmware/1-serial/1-serial_merged.bin"
```
> (Binaire d'auto-test : `challenges/setup/firmware/0-bist_merged.bin`.
>  Challenge 2 EEPROM : `challenges/SET 1/firmware/2-eeprom/2-eeprom_merged.bin`.)

### c) Flasher le binaire sur la carte (offset `0x0`, 460800 bauds)

**Méthode A — Navigateur (la plus simple, rien à installer).**
1. Branche la carte, ferme tout autre programme qui utilise le port série.
2. Ouvre **https://espressif.github.io/esptool-js/** dans **Chrome ou Edge**.
3. *Baudrate* : `460800` → **Connect** → choisis le port de la carte.
4. *Flash Address* : `0x0` → *Choose File* : `1-serial_merged.bin` → **Program**.
5. Attends « Hard resetting… », puis appuie sur le bouton **EN (reset)**.

**Méthode B — Ligne de commande (esptool).**
```bash
pip install esptool
esptool --chip esp32 --port <PORT> --baud 460800 write-flash 0x0 1-serial_merged.bin
# Windows ex : --port COM5     Linux ex : --port /dev/ttyUSB0
```

### d) Vérifier (optionnel)
Ouvre un moniteur série à **115200 bauds, 8N1** et appuie sur **EN** : tu dois voir
la bannière de boot de la passerelle. Sinon, lance directement le harnais (§6) :
le backend série lit la bannière automatiquement.

---

## 2. Versions testées

| Composant | Windows | Linux |
|---|---|---|
| Python | 3.14 | 3.8 |
| pyserial | 3.5 | 3.4 |
| google-genai (backend Gemini) | 2.28.0 | idem |
| anthropic (backend Claude) | 1.11.0 | idem |
| Modèles LLM | `gemini-flash-latest`, `gemini-3.x`, `claude-sonnet-5-5` | idem |

**Matériel** : carte **Ideaspark ESP32** (TFT ST7789 intégré) + lecteur RFID
MFRC522 (SPI) + EEPROM 24Cxx (I²C). **Série : 115200 bauds, 8N1.**

> Python **3.10+** recommandé. Le cœur (mode `mock`) ne dépend que de la stdlib.

---

## 3. Installation

```bash
pip install -r requirements.txt
# minimal pour parler a la carte :  pip install pyserial
# backend Gemini : pip install google-genai      backend Claude : pip install anthropic
```

### Clés API (selon le backend)

| Backend | Variable d'environnement |
|---|---|
| Gemini | `GEMINI_API_KEY` |
| Claude | `ANTHROPIC_API_KEY` |

**Windows (PowerShell), persistant :**
```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "ta_cle", "User")
```

**Linux (bash), persistant :**
```bash
echo 'export GEMINI_API_KEY="ta_cle"' >> ~/.bashrc && source ~/.bashrc
```

---

## 4. Trouver son port série (`<PORT>`)

Chacun a un port différent — repère le tien :

- **Windows** : *Gestionnaire de périphériques* → *Ports (COM & LPT)* → une entrée
  type `USB-SERIAL CH340` / `Silicon Labs CP210x` → le port est `COM3`, `COM5`, …
  (ou `mode` dans un cmd pour lister les `COMx`).
- **Linux** : branche la carte puis
  ```bash
  ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null   # souvent /dev/ttyUSB0 ou /dev/ttyACM0
  dmesg | tail                                # confirme quel périphérique vient d'apparaître
  ```
  Si « permission refusée » : `sudo usermod -aG dialout $USER` puis rouvre la session.

---

## 5. Démarrage rapide (sans carte, sans clé)

```bash
python run.py              # 1 run sur un challenge factice (backend mock, hors-ligne)
python bench.py -n 10      # 10 runs -> stats de répétabilité + CSV
```

Le backend `mock` est **déterministe** : il prouve que boucle + outils + métriques
marchent sans matériel ni API. Attendu : résolu en **1 requête UART**.

---

## 6. Lancer le VRAI challenge 1 (Serial Gateway)

Carte flashée (§1) et branchée. Remplace `<PORT>` par le tien (§4) et `<MODELE>`
par le modèle voulu.

**Windows :**
```powershell
python run_challenge1.py --port <PORT> --backend gemini --model <MODELE>
# ex : --port COM5 --model gemini-flash-latest
```

**Linux :**
```bash
python3 run_challenge1.py --port <PORT> --backend gemini --model <MODELE>
# ex : --port /dev/ttyUSB0 --model gemini-flash-latest
```

Options utiles : `--backend {gemini,claude,mock}`, `--model <nom>`,
`--max-steps 400` (plafond d'itérations), `--log runs/challenge1.jsonl`.

Pendant le run, le terminal affiche **en direct** :
- `[pensee du modele] …` — le raisonnement de l'agent (résumés de pensée),
- `[decision -> outil] {args}` — l'outil qu'il décide d'appeler,
- `>>> '...'` / `<<< ...` — la commande envoyée à la carte et sa réponse,
- puis un **résumé** (requêtes UART, appels LLM, tokens, temps, résolu/raison).

---

## 7. Comment l'agent résout le challenge (pédagogique)

Le firmware expose une **console de diagnostic** sur l'UART. Il n'y a **aucun
indice en dur** dans le harnais : l'agent découvre tout via ses outils.

1. **Oracle de préfixe.** Pour une entrée `X`, la console répond
   `one or more commands start with X` (préfixe valide) ou `no command starts
   with X`. L'agent reconstruit les commandes cachées **caractère par caractère**,
   avec un **raccourci** : dès qu'un préfixe suggère un mot courant, il tente le
   mot entier (toujours vérifié par l'oracle). Un **délai de pénalité** double à
   chaque essai raté ; `reboot()` le remet à zéro.
2. **Reconnaissance Wi-Fi.** Quand la console réclame un **identifiant** qu'il ne
   connaît pas, l'agent lance `wifi_scan` : il voit alors le **SSID** diffusé par
   la passerelle et en **déduit lui-même** l'identité à fournir.
3. **Exploration guidée.** Une fois « débloqué », il lit **toute** la sortie des
   commandes, repère une **instruction** affichée par la carte, et la suit jusqu'à
   obtenir le flag.
4. **Validation.** Le flag (`esc_2026{...}`) est soumis via `submit_flag`.

> Exemple de run réel : **résolu**, ~73 requêtes UART, ~77 appels LLM
> (`gemini-flash-latest`). L'ordre et le nombre de requêtes varient selon le
> modèle — c'est justement ce que mesurent les métriques.

### Outils fournis à l'agent
| Outil | Rôle | Compte comme requête cible ? |
|---|---|---|
| `wifi_scan()` | scan Wi-Fi réel (recon) | non (canal `STATIC`) |
| `uart_send(command)` | envoie 1 ligne à l'oracle UART | **oui** (`UART`) |
| `reboot()` | reset EN -> pénalité à zéro | non |
| `submit_flag(flag)` | valide `esc_2026{...}` / `ESC{...}` | non |

### Schéma : un seul agent, plusieurs outils

Un **unique** agent LLM décide, à chaque étape, **quel outil** appeler. Le jeu
d'outils **dépend du challenge**. ★ = canal ≠ `STATIC` → **compte comme « requête
cible »** (métrique d'efficacité) ; les outils `STATIC` (recon, validation) sont
gratuits côté métrique.

**Challenge 1 réel (`serial_gateway.py`) :**
```
            ┌──────────────────────────┐
            │  AGENT (1 cerveau LLM)    │   ← il décide
            └────────────┬─────────────┘
                         │ choisit UN outil par étape
     ┌────────────┬──────┴─────┬──────────────┐
  wifi_scan     uart_send     reboot        submit_flag
  (WIFI, recon)  (UART) ★      (STATIC)      (STATIC)
```

**Challenge factice (`device.py`, mode `mock`) :**
```
            ┌──────────────────────────┐
            │  AGENT (1 cerveau LLM)    │
            └────────────┬─────────────┘
     ┌───────────────┬───┴───┬───────────┬───────────┐
 static_analysis  uart_send  eeprom_read  http_get  submit_flag
  (STATIC, recon)  (UART) ★   (EEPROM) ★   (HTTP) ★   (STATIC)
```

> Les canaux **BLE / RFID** sont prévus (définis dans `Channel`) mais **pas encore
> implémentés** : ils arriveront avec les challenges suivants, en ajoutant un
> fichier dans `challenges/` (et un backend `bleak` pour le BLE).

---

## 8. Architecture des fichiers (rôle de chacun)

```
esc_agent-projet/
├── run.py                 # POINT D'ENTREE : 1 run sur le challenge "mock"
├── run_challenge1.py      # POINT D'ENTREE : 1 run sur le challenge 1 RÉEL (série)
├── bench.py               # POINT D'ENTREE : N runs -> statistiques + CSV
├── list_models.py         # utilitaire : liste les modèles Gemini de ta clé
├── requirements.txt       # dépendances + versions testées
├── .env.example           # modèle de fichier d'environnement (clés API)
├── README.md              # ce document
├── runs/                  # SORTIES : journaux JSONL, transcripts, CSV (générés)
└── esc_agent/             # LE PACKAGE (toute la logique)
    ├── __init__.py        # marque le dossier comme package Python
    ├── agent.py           # LA BOUCLE de l'agent (cœur)
    ├── metrics.py         # mesure & journalisation
    ├── llm/               # les "cerveaux" (un fichier par fournisseur)
    │   ├── base.py        # interface commune + types normalisés
    │   ├── mock.py        # backend hors-ligne déterministe
    │   ├── gemini.py      # backend Google Gemini
    │   └── claude.py      # backend Anthropic Claude
    ├── tools/             # les "mains" (ce que l'agent peut faire)
    │   ├── base.py        # registre d'outils + instrumentation
    │   └── device.py      # outils d'accès matériel (UART/EEPROM/HTTP)
    └── challenges/        # les "mondes" (une cible = un fichier)
        ├── mock_challenge.py   # cible simulée (pour tester le harnais)
        └── serial_gateway.py   # cible RÉELLE : challenge 1
```

### Les points d'entrée (ce que tu lances)
| Fichier | Rôle |
|---|---|
| `run.py` | Lance **1 run** sur le challenge factice (`mock`). Contient `build_llm(backend, model)` qui choisit le cerveau. Sert à vérifier que tout marche sans matériel. |
| `run_challenge1.py` | Lance **1 run** sur la **vraie carte** (challenge 1). Ouvre le port série, enregistre la bannière de boot, branche les outils, lance l'agent, affiche le résumé. |
| `bench.py` | Rejoue **N runs** et agrège les métriques (moyenne, écart-type, CV, taux de succès) + écrit un **CSV**. C'est le tableau du rapport. |
| `list_models.py` | Affiche les modèles Gemini utilisables avec ta `GEMINI_API_KEY`. |

### Le cœur (`esc_agent/`)
| Fichier | Rôle |
|---|---|
| `agent.py` | **La boucle** : Observer → appeler le LLM → exécuter l'outil demandé → vérifier (flag ?) → journaliser, et recommencer jusqu'au succès ou `max_steps`. Gère l'affichage verbeux (`[pensee du modele]`, `[decision -> outil]`) et relance le modèle s'il n'appelle aucun outil. **Ne dépend d'aucun fournisseur ni d'aucun challenge** (100 % générique). |
| `metrics.py` | La **mesure** : `EventLogger` écrit chaque évènement en **JSONL**, normalise l'usage de tokens, et agrège les runs (`aggregate`, `format_table`). C'est ce qui produit les chiffres notés. |

### Les cerveaux — `esc_agent/llm/` (un fichier = un fournisseur, **isolé**)
| Fichier | Rôle |
|---|---|
| `base.py` | Le **contrat** commun : classe abstraite `LLMClient` + types normalisés (`Message`, `ToolCall`, `ToolSpec`, `Usage`, `LLMResponse`). Tout le reste ne parle **qu'à** ces types. |
| `mock.py` | Cerveau **déterministe hors-ligne** : rejoue une solution fixe, sans API. Idéal pour tester la mécanique. |
| `gemini.py` | Traduit vers/depuis l'API **Google Gemini** (appel d'outils forcé, résumés de pensée, retry/backoff). |
| `claude.py` | Traduit vers/depuis l'API **Anthropic Claude** (API Messages, apparage des outils). |
> Pour **ajouter un fournisseur**, on crée un nouveau fichier ici qui implémente
> `LLMClient`, et on l'ajoute à `build_llm` dans `run.py`. Rien d'autre ne change.

### Les mains — `esc_agent/tools/`
| Fichier | Rôle |
|---|---|
| `base.py` | Le **registre d'outils** (`ToolRegistry`) et les **canaux** (`Channel` : UART, BLE, RFID, EEPROM, HTTP, WIFI, et STATIC = hors-ligne/gratuit). Il **compte et chronomètre** chaque appel sur un canal ≠ STATIC → c'est la source des métriques « requêtes cible ». |
| `device.py` | Outils d'accès matériel génériques (UART/EEPROM/HTTP) et leurs backends (mock / `pyserial`), utilisés par le challenge factice. |

### Les mondes — `esc_agent/challenges/` (une cible = un fichier)
| Fichier | Rôle |
|---|---|
| `mock_challenge.py` | Une cible **simulée** en mémoire (`MockBackend` + objectif) : permet de valider la chaîne complète sans carte. |
| `serial_gateway.py` | **Le challenge 1 réel** : `RealSerialBackend` (dialogue série avec la carte), l'outil `wifi_scan` (recon Wi-Fi multiplateforme), `register_tools` (déclare `wifi_scan`/`uart_send`/`reboot`/`submit_flag`), et les consignes de l'agent (`SYSTEM`, `GOAL`). **C'est ici qu'on décrit un challenge** sans toucher au reste. |
> Pour **ajouter un challenge** (EEPROM, BLE…), on crée un fichier ici sur le
> modèle de `serial_gateway.py`, puis un petit lanceur type `run_challengeN.py`.

### Les sorties — `runs/`
Fichiers **générés** à l'exécution : `*.jsonl` (journal rejouable), le transcript
lisible du dialogue avec la carte, et les `*.csv` de `bench.py`.

> **Principe clé** : la boucle (`agent.py`), la mesure (`metrics.py`) et le contrat
> (`llm/base.py`) sont stables ; on ne touche qu'à **un** fichier pour un nouveau
> fournisseur (`llm/`) ou un nouveau challenge (`challenges/`).

---

## 9. Métriques (ce que mesure le harnais)

- **requêtes vers la cible** par canal (UART/BLE/RFID/EEPROM/HTTP) — métrique
  d'efficacité clé (le scan Wi-Fi et l'analyse ne comptent pas comme requête) ;
- **appels LLM**, **tokens** (input / output / cache / thinking), **latences** ;
- **succès + raison** par run ;
- **répétabilité** : moyenne, écart-type, **CV** (σ/μ) et taux de succès sur N runs ;
- journal **JSONL** rejouable + **CSV** par run.

### Comparer les modèles (volet « support IA »)
```bash
python bench.py --backend gemini --model <MODELE_A> -n 10
python bench.py --backend gemini --model <MODELE_B> -n 10
# -> tableaux requêtes/tokens/temps/succès comparables, à mettre dans le rapport
```
`python list_models.py` liste les modèles utilisables avec ta clé Gemini.

---

## 10. Compatibilité OS

- **Série** : `pyserial` gère les ports Windows (`COMx`) comme Linux
  (`/dev/ttyUSBx`, `/dev/ttyACMx`). Voir §4 pour trouver le tien.
- **`wifi_scan`** est **multiplateforme** et choisit automatiquement :
  - **Windows** — balayage *forcé* via l'API Wi-Fi Windows (appelée par
    `powershell`), le plus fiable ; repli sur le cache `netsh`.
  - **Linux** — `nmcli` (NetworkManager) avec rescan.

---

## 11. Enregistrer une démo (reproductibilité)

```bash
asciinema rec --idle-time-limit 2 \
  -c "python run_challenge1.py --port <PORT> --backend gemini --model <MODELE>" \
  challenge1.cast
asciinema play challenge1.cast
```
Le `.cast` montre raisonnement + décisions + console en direct — idéal pour la
soutenance et le rapport.
