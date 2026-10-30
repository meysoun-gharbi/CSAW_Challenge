# Challenge 4 — Hidden Portal (SET 2, 250 pts)

> **Ports & commandes** : remplace `<PORT>` par ton port série — **`COMx`** sous Windows, **`/dev/ttyUSBx`** (ou `/dev/ttyACMx`) sous Linux/macOS. Utilise **`python`** sous Windows, **`python3`** sous Linux/macOS.

**Flag : `esc_2026{50_shades_of_grey_7685f0ebd0f4df28}`**
*(la partie hexadécimale change à chaque boot ; la méthode reste identique.)*

Type : **web + stéganographie + Gray code → pivot UART**. Boîte noire.
Résumé : trouver un endpoint caché → télécharger une image → en extraire un **PIN**
(zsteg) → le saisir sur le pin-pad pour ouvrir un coffre → décoder le payload du
coffre (**Gray code**) → taper une commande sur l'**UART** → flag.

---

## 0. Préparer (une seule fois)

1. **Pilote USB** si la carte n'apparaît pas (CH340 / CP210x).
2. **Flasher** le firmware fourni :
   ```bash
   python -m esptool --port <PORT> --baud 460800 write_flash 0x0 firmware/4-web_merged.bin
   ```
3. Au boot, un **réseau Wi-Fi** `SmartHomeGW_xxxxxx` apparaît → **connecte ton
   PC à ce Wi-Fi**. Le tableau de bord est sur **http://192.168.4.1**.
4. **Garde le câble USB branché** (on en a besoin à la toute fin, pour l'UART).
5. Installe **zsteg** (outil stégano, en Ruby) :
   ```bash
   gem install zsteg          # (Ruby requis : apt install ruby / choco install ruby)
   ```

---

## ✅ Méthode A — à la main dans le navigateur (recommandée, très simple)

**1) Ouvrir le site et inspecter.**
Ouvre **http://192.168.4.1** dans ton navigateur. Appuie sur **`Ctrl+Shift+C`**
(inspecteur) ou **`F12`** → onglet *Sources/Elements* et cherche dans le code/JS
un chemin prometteur : on tombe sur **`/api/admin`** (un endpoint « diagnostic »
laissé par un dev, non lié dans la page).

**2) Aller sur l'endpoint caché.**
Mets ce chemin dans l'URL : **http://192.168.4.1/api/admin** → une page
*« Diagnostic Carrier Asset »* affiche une **image** (épée dans la pierre) avec un
message de diagnostic, et un lien de **téléchargement**. Télécharge l'image
(clic sur *Download raw asset*, ou ouvre **http://192.168.4.1/api/admin?raw=1** et
enregistre le `.png`).

**3) Chercher du texte caché dans l'image (zsteg).**
```bash
zsteg admin_asset.png
```
Dans la sortie, une ligne révèle le **PIN** :
```
b1,r,lsb,xy   .. text: "PIN:9573"
```
(C'est du **LSB** dans le canal Rouge — zsteg teste tout automatiquement.)

**4) Saisir le PIN sur le pin-pad.**
Reviens sur le dashboard → page **« PIN Pad » / « Classifier PIN Pad »** → **dessine
les 4 chiffres** du PIN un par un (le classifieur les reconnaît), puis **Verify
PIN**. Résultat : **« Vault Open »** — le coffre s'ouvre.

**5) Lire le payload du coffre.**
La page **Vault** (`/vault`) affiche un **payload hexadécimal** « encoded at rest »
+ un indice : *« **50 shades of grey?** 256 would've been better… »*.
→ « grey » = jeu de mots sur le **Gray code** (code de Gray).

**6) Décoder le Gray code.**
Le plus simple : **CyberChef** → recette **`From Hex`** puis **`From Gray Code`**,
colle le payload → le message en clair apparaît :
```
run this command in uart to get the flag: diag_dump <TOKEN>
```
*(hors-ligne : `python solve/ch4_solve.py` fait aussi ce décodage ; ou en une
ligne Python : `g^=g>>4; g^=g>>2; g^=g>>1` octet par octet.)*

**7) Pivot UART → flag.**
Ouvre un **moniteur série** (115200) sur la carte et tape :
```
diag_dump <TOKEN>
```
→ le **flag** s'affiche : `esc_2026{50_shades_of_grey_...}`. 🏁

---

## ⚡ Méthode B — tout automatique (un seul script)

Associé au SoftAP + câble USB branché :
```bash
python solve/ch4_solve.py --port <PORT>
```
Le script enchaîne exactement les mêmes étapes (recon `/api/admin` → stego LSB →
`/api/verify-pin` → `/vault` → Gray code → `diag_dump` sur l'UART) et affiche le
flag. Le script **recalcule** le PIN et le token à chaque exécution (ils changent
à chaque boot — rien n'est codé en dur).

Recon seul (pour voir les endpoints + la négociation de contenu de `/api/admin`) :
```bash
python solve/ch4_recon.py --out ch4_loot
```

---

## Fichiers
`firmware/4-web_merged.bin`, `solve/ch4_recon.py`, `solve/ch4_solve.py`,
`refs.md` (sources & détails techniques).
