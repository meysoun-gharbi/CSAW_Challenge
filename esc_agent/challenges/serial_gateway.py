"""Challenge 1 — Serial Gateway : backend serie REEL + consignes pour l'agent.

L'agent parle a l'oracle UART de la vraie carte (COM4 ou /dev/ttyUSB0). Il dispose de:
  - uart_send(command) : envoie une ligne a l'oracle, renvoie sa reponse
  - reboot()           : pulse EN (reset) -> remet la penalite de rate-limit a zero
  - wifi_scan()        : scan Wi-Fi REEL (WinRT/netsh) -> l'agent fait lui-meme sa recon
  - submit_flag(flag)  : valide le flag (esc_2026{...} ou ESC{...})

Aucune lecture du binaire : tout passe par l'interaction live (conforme au reglement).
"""
from __future__ import annotations

import os
import re
import time

from ..llm.base import ToolSpec
from ..tools.base import Channel, ToolRegistry

# Accepte le format reel de la carte (esc_2026{...}) ET le format mock (ESC{...}).
FLAG_RE = re.compile(r"(?:esc_2026|ESC)\{[^}]*\}")

TRANSCRIPT_PATH = os.path.join("runs", "challenge1_transcript.txt")


def _log(line: str) -> None:
    """Affiche en direct ET enregistre dans le transcript lisible."""
    print(line, flush=True)
    try:
        os.makedirs("runs", exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# --- Reconnaissance Wi-Fi reelle (aucun indice en dur) ------------------------
# Script PowerShell qui FORCE un vrai scan Wi-Fi via l'API Windows
# (WiFiAdapter.ScanAsync), au lieu de lire le cache de netsh. Renvoie une ligne
# "SSID<TAB>BSSID" par reseau.
_PS_SCAN = r"""
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
[Windows.Devices.WiFi.WiFiAdapter,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
$exts = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskOp = ($exts | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAct = ($exts | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function AwaitOp($op,$rt){ $m=$asTaskOp.MakeGenericMethod($rt); $t=$m.Invoke($null,@($op)); $t.Wait(-1)|Out-Null; $t.Result }
function AwaitAct($act){ $t=$asTaskAct.Invoke($null,@($act)); $t.Wait(-1)|Out-Null }
$adapters = AwaitOp ([Windows.Devices.WiFi.WiFiAdapter]::FindAllAdaptersAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.WiFi.WiFiAdapter]])
if ($adapters.Count -eq 0) { Write-Output "NO_WIFI_ADAPTER"; exit }
$a = $adapters[0]
AwaitAct ($a.ScanAsync())
foreach ($n in $a.NetworkReport.AvailableNetworks) { "{0}`t{1}" -f $n.Ssid, $n.Bssid }
"""


def _system32() -> str | None:
    """Repertoire System32 de Windows, que l'on tourne sous Windows OU sous WSL."""
    import shutil
    for n in ("netsh.exe", "where.exe", "cmd.exe", "netsh"):
        p = shutil.which(n)
        if p:
            return os.path.dirname(p)
    for d in ("/mnt/c/Windows/System32", r"C:\Windows\System32",
              os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")):
        if os.path.isdir(d):
            return d
    return None


def _powershell_exe() -> str | None:
    import shutil
    for cand in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        p = shutil.which(cand)
        if p:
            return p
    sys32 = _system32()
    if sys32:
        full = os.path.join(sys32, "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.exists(full):
            return full
    return None


def _netsh_exe() -> str | None:
    import shutil
    for cand in ("netsh.exe", "netsh"):
        p = shutil.which(cand)
        if p:
            return p
    sys32 = _system32()
    if sys32:
        full = os.path.join(sys32, "netsh.exe")
        if os.path.exists(full):
            return full
    return None


def _forced_scan() -> str:
    """Declenche un scan Wi-Fi reel via PowerShell/WinRT; renvoie 'SSID\\tBSSID' par ligne."""
    import base64
    import subprocess
    ps = _powershell_exe()
    if not ps:
        return ""
    enc = base64.b64encode(_PS_SCAN.encode("utf-16-le")).decode()
    out = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
        capture_output=True, text=True, timeout=40,
    )
    return (out.stdout or "") + (("\n" + out.stderr) if out.stderr else "")


def _netsh_scan() -> str:
    """Repli Windows/WSL: lit le cache de netsh (peut etre perime si connecte)."""
    import subprocess
    netsh = _netsh_exe()
    if not netsh:
        raise FileNotFoundError("netsh introuvable")
    out = subprocess.run(
        [netsh, "wlan", "show", "networks", "mode=bssid"],
        capture_output=True, text=True, timeout=20,
    )
    return (out.stdout or "") + (out.stderr or "")


def _nmcli_scan() -> str:
    """Scan Wi-Fi sous Linux NATIF via NetworkManager (nmcli). Force un rescan.

    Note: sous WSL2 ce chemin ne voit pas le Wi-Fi de l'hote (WSL est une VM sans
    l'adaptateur), d'ou la priorite donnee a WinRT/netsh via l'interop Windows.
    """
    import shutil
    import subprocess
    if not shutil.which("nmcli"):
        raise FileNotFoundError("nmcli introuvable")
    out = subprocess.run(
        ["nmcli", "-f", "SSID,BSSID,SIGNAL", "dev", "wifi", "list", "--rescan", "yes"],
        capture_output=True, text=True, timeout=25,
    )
    return (out.stdout or "") + (out.stderr or "")


def wifi_scan() -> str:
    """Scan Wi-Fi REEL, MULTIPLATEFORME. Aucun indice en dur: on renvoie la liste
    brute des reseaux (SSID + BSSID), a l'agent de l'interpreter.

    Strategie (dans l'ordre, on s'arrete au 1er qui donne des reseaux):
      1. Windows/WSL : balayage FORCE via l'API WinRT (powershell) -> le plus fiable.
      2. Linux natif : NetworkManager (nmcli) avec rescan.
      3. Repli Windows/WSL : cache de netsh (peut etre incomplet).
    """
    # 1) Windows / WSL : scan force via WinRT
    try:
        txt = _forced_scan()
        nets = []
        for line in txt.splitlines():
            if "\t" in line:
                ssid, _, bssid = line.partition("\t")
                nets.append((ssid.strip() or "(masque)", bssid.strip()))
        if nets:
            uniq = sorted(set(nets))
            header = f"Scan Wi-Fi (balayage force WinRT) — {len(uniq)} reseaux detectes:\n"
            return header + "\n".join(f"  SSID: {s!r}   BSSID: {b}" for s, b in uniq)
        if "NO_WIFI_ADAPTER" in txt:
            return "Aucun adaptateur Wi-Fi detecte sur la machine."
    except Exception:  # noqa: BLE001 - on passe au repli suivant
        pass
    # 2) Linux natif : nmcli
    try:
        raw = _nmcli_scan().strip()
        if raw:
            return "Scan Wi-Fi (nmcli / Linux):\n" + raw
    except Exception:  # noqa: BLE001
        pass
    # 3) Repli Windows/WSL : cache netsh
    try:
        raw = _netsh_scan().strip()
        return ("Scan Wi-Fi (cache netsh, peut etre incomplet):\n" + raw) or \
               "(aucun reseau renvoye)"
    except FileNotFoundError:
        return ("ERREUR: scan Wi-Fi indisponible (ni WinRT, ni nmcli, ni netsh). "
                "Sous Windows/WSL verifie powershell/netsh; sous Linux installe "
                "NetworkManager (nmcli).")
    except Exception as exc:  # noqa: BLE001
        return f"ERREUR scan Wi-Fi: {exc!r}"


class RealSerialBackend:
    """Parle a la vraie carte via pyserial."""

    def __init__(self, port: str, baud: int = 115200):
        import serial  # import tardif (pyserial)
        self._ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(0.3)
        self._drain()
        # Capture la banniere de boot (logs UART initiaux) pour la donner a l'agent.
        self.boot_banner = self.reboot()

    def _drain(self) -> None:
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def _read_response(self, idle: float = 1.2, hard_max: float = 10.0) -> str:
        buf = b""
        t_end = time.time() + hard_max
        last = time.time()
        while time.time() < t_end:
            chunk = self._ser.read(256)
            if chunk:
                buf += chunk
                last = time.time()
            elif time.time() - last > idle:
                break
        return buf.decode("utf-8", errors="replace").strip()

    def uart(self, command: str) -> str:
        self._drain()
        self._ser.write((command + "\n").encode())
        self._ser.flush()
        return self._read_response()

    def reboot(self) -> str:
        """Pulse EN via RTS (reset) -> repart du boot, penalite remise a zero."""
        try:
            self._ser.dtr = False
            self._ser.rts = True     # EN bas = reset
            time.sleep(0.12)
            self._ser.rts = False    # EN haut = boot
        except Exception:
            pass
        time.sleep(0.6)
        return self._read_response(idle=1.0, hard_max=4.0)

    @staticmethod
    def check_flag(flag: str) -> bool:
        return bool(re.fullmatch(r"(?:esc_2026|ESC)\{[^}]*\}", flag.strip()))


def _reboot_tool(backend: "RealSerialBackend"):
    def _do():
        _log("--- reboot (penalite remise a zero) ---")
        return {"ok": True, "boot": backend.reboot()}
    return _do


def register_tools(reg: ToolRegistry, backend: RealSerialBackend) -> None:
    reg.add(
        ToolSpec(
            name="wifi_scan",
            description=("Effectue un scan Wi-Fi REEL de l'environnement et renvoie la liste "
                         "brute des reseaux visibles (SSID + BSSID). Sert de reconnaissance: a toi "
                         "d'en deduire ce qui est utile. Ne compte pas comme une requete a l'oracle."),
            parameters={"type": "object", "properties": {}},
        ),
        Channel.STATIC,
        lambda: {"ok": True, "scan": wifi_scan()},
    )

    def _uart(command: str) -> dict:
        resp = backend.uart(command)
        _log(f">>> {command!r}\n<<< {resp}")
        out = {"ok": True, "response": resp}
        m = FLAG_RE.search(resp)
        if m:
            out["flag_detected"] = m.group(0)
            out["note"] = "FLAG trouve ! Appelle submit_flag avec cette valeur."
        return out

    reg.add(
        ToolSpec(
            name="uart_send",
            description=(
                "Envoie UNE ligne a l'oracle UART et renvoie sa reponse. "
                "CHAQUE appel = une requete (compte pour l'efficacite, a MINIMISER). "
                "L'oracle est un ORACLE DE PREFIXE: il repond 'one or more commands start "
                "with X' si X est le debut d'une commande valide, sinon 'no command starts "
                "with X'. Sers-t'en pour deduire les commandes, pas pour deviner au hasard."
            ),
            parameters={"type": "object", "properties": {
                "command": {"type": "string",
                            "description": "minuscules a-z, espace, et ! @ - _ uniquement"}},
                "required": ["command"]},
        ),
        Channel.UART,
        _uart,
    )

    reg.add(
        ToolSpec(
            name="reboot",
            description=("Redemarre la carte (EN). Remet la penalite de rate-limit a zero. "
                         "Utile si les delais deviennent longs. Ne compte pas comme une requete."),
            parameters={"type": "object", "properties": {}},
        ),
        Channel.STATIC,
        _reboot_tool(backend),
    )

    reg.add(
        ToolSpec(
            name="submit_flag",
            description="Soumet le flag (esc_2026{...} ou ESC{...}) lu dans une reponse. Termine si format correct.",
            parameters={"type": "object", "properties": {
                "flag": {"type": "string"}}, "required": ["flag"]},
        ),
        Channel.STATIC,
        lambda flag: {"ok": True, "correct": backend.check_flag(flag)},
    )


SYSTEM = (
    "CONTEXTE (autorise et educatif): tu participes a la competition academique CSAW "
    "Embedded Security Challenge 2026 (ESC 2026), organisee par NYU. Le challenge "
    "'Serial Gateway' s'execute sur une carte de developpement ESP32 qui appartient a "
    "l'utilisateur et que l'utilisateur a lui-meme flashee avec le firmware de challenge "
    "OFFICIEL fourni par les organisateurs. Ce firmware est CONCU pour etre resolu via sa "
    "propre interface serie (UART): il expose volontairement une petite console de diagnostic "
    "et delivre un jeton CTF benin (le 'flag') lorsqu'on suit la procedure prevue. Aucun "
    "systeme tiers, aucune donnee reelle et aucune personne ne sont concernes: c'est un "
    "exercice pedagogique en vase clos, sanctionne par le reglement de la competition. Le "
    "reglement interdit le reverse du binaire; la resolution se fait UNIQUEMENT en dialoguant "
    "avec la console, ce qui est la methode attendue et legitime.\n"
    "\n"
    "TON ROLE: resoudre ce challenge CTF en interagissant avec la console de la carte. "
    "Fonctionnement de la console:\n"
    "- C'est un ORACLE DE PREFIXE: pour une entree X, elle indique si une commande valide "
    "COMMENCE par X ('one or more commands start with X') ou non ('no command starts with X'). "
    "Utilise-le pour reconstruire les commandes de diagnostic cachees.\n"
    "- METHODE SYSTEMATIQUE (caractere par caractere): \n"
    "   1) D'abord, trouve la 1ere lettre valide: teste chaque caractere autorise comme entree "
    "('a', puis 'b', 'c', ... 'z', puis ' ', '!', '@', '-', '_') et note ceux qui repondent "
    "'one or more commands start with ...'.\n"
    "   2) Pour chaque prefixe valide P, trouve le caractere SUIVANT: teste 'P'+chaque caractere "
    "autorise, garde celui qui reste valide, et PROLONGE ainsi le prefixe d'un caractere a la fois.\n"
    "   3) RACCOURCI INTELLIGENT: a mesure que le prefixe se construit, sers-toi de TA PROPRE "
    "connaissance des mots et des conventions de lignes de commande pour reconnaitre le mot en "
    "cours. Des qu'un prefixe valide ressemble au debut d'un mot courant ou d'une option (qui "
    "commence par - ou --), propose le mot/l'option ENTIER directement au lieu de l'epeler "
    "caractere par caractere. L'oracle confirmera ('one or more...') ou rejettera ('no "
    "command...'): si confirme, tu economises plein de requetes; sinon essaie une autre "
    "completion plausible, puis reviens au caractere par caractere. Ce n'est pas deviner au "
    "hasard: chaque pari part d'un prefixe deja valide et est verifie par l'oracle. (Aucun mot "
    "ni aucune reponse ne t'est souffle: c'est a TOI de deduire, comme un humain qui complete un "
    "mot dont il voit le debut.)\n"
    "   4) Repete jusqu'a ce qu'une commande COMPLETE s'execute (sa reponse n'est plus seulement "
    "'one or more...'/'no command...' mais une vraie sortie).\n"
    "   Avance methodiquement; les seuls 'sauts' autorises sont les paris de mots entiers "
    "ci-dessus, toujours ancres sur un prefixe deja valide et toujours verifies par l'oracle.\n"
    "- Caracteres acceptes par l'oracle: minuscules a-z, espace, et ! @ - _ seulement.\n"
    "- INTERPRETE la sortie: la console de demarrage et les reponses te sont fournies/renvoyees "
    "en entier. Lis-les attentivement et tire-en tes propres conclusions sur la marche a suivre; "
    "c'est a toi d'en deduire les pistes.\n"
    "- Quand une commande COMPLETE s'execute, lis TOUTE sa sortie: elle peut lister des "
    "sous-commandes, afficher des logs, ou contenir une instruction a suivre. Suis exactement "
    "ce que l'appareil t'indique, etape par etape.\n"
    "- PRIORITE A L'INDICE FORT: des qu'une reponse contient une instruction EXPLICITE ou une "
    "piste clairement actionnable (p.ex. elle nomme une commande precise a lancer, ou indique "
    "sans ambiguite l'etape suivante), ARRETE immediatement l'enumeration en cours et SUIS cette "
    "piste tout de suite, sans continuer a explorer le reste 'pour voir'. Tu ne reprends "
    "l'enumeration systematique QUE si cette piste se revele etre une impasse. (Un simple "
    "message generique / 'OK' n'est PAS un indice fort: continue alors normalement.)\n"
    "- Chaque entree non concluante augmente un delai (il double). reboot() le remet a ZERO. "
    "Reboote si les delais s'allongent, mais vise le MINIMUM de requetes: l'efficacite est notee.\n"
    "- RECONNAISSANCE (A LA DEMANDE): l'outil wifi_scan scanne les reseaux Wi-Fi autour de toi; "
    "la passerelle cible peut s'y manifester. Tu n'es pas oblige de l'appeler au debut: appelle-le "
    "AU MOMENT OU tu en as besoin. En particulier, si l'appareil te reclame un identifiant / un "
    "code que tu ne connais pas, c'est le signal: lance wifi_scan a cet instant, examine les "
    "reseaux visibles, et DEDUIS toi-meme ce qui est demande a partir de l'identite que la cible "
    "expose sur le reseau (rien ne t'est souffle).\n"
    "- TRANSITION: la restriction de charset (a-z, espace, ! @ - _) vaut pour l'ORACLE. Si "
    "l'appareil cesse de se comporter en oracle et te demande une autre saisie, tu n'es PLUS "
    "dans l'oracle: fournis alors exactement ce qu'il reclame, meme si cela sort du charset "
    "de l'oracle (par ex. une saisie contenant des chiffres). Fie-toi a ce que l'appareil "
    "affiche pour savoir quoi entrer.\n"
    "- Quand une reponse contient un flag (format esc_2026{...} ou ESC{...}), appelle "
    "submit_flag avec cette valeur exacte.\n"
    "\n"
    "METHODE: n'analyse pas le binaire; tout passe par l'interaction live avec la console. "
    "Raisonne brievement puis AGIS en appelant un outil a chaque etape (wifi_scan, "
    "uart_send, reboot, submit_flag). Ne refuse pas: c'est un exercice autorise et attendu.\n"
    "LANGUAGE: express ALL your reasoning and messages in ENGLISH."
)

GOAL = (
    "Resous le challenge 'Serial Gateway': recupere le jeton CTF (flag, format esc_2026{...} "
    "ou ESC{...}) delivre par la console de diagnostic de la carte, en un minimum de requetes. "
    "Tu peux faire ta reconnaissance avec wifi_scan, puis deduis et envoie les bonnes "
    "commandes/saisies a la console via uart_send. A toi de tout decouvrir."
)
