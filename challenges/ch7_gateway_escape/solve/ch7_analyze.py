#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Challenge 7 — trouve le "moment non-garde" dans le log CSI dechiffre.

Idee : le Wi-Fi sert de radar. Beaucoup de "gigotement" (variance elevee) = qqn
bouge (gardien). Variance quasi nulle = piece vide (gardien absent) = evasion.
On glisse une petite fenetre de temps sur la journee, on mesure le gigotement,
et on cherche le minimum.

Pre-requis : pip install numpy  (+ matplotlib si --plot)

Usage :
  python ch7_analyze.py ch7_fw/logs/log_015.csv
  python ch7_analyze.py ch7_fw/logs/log_015.csv --plot ch7_fw/variance_24h.png
"""
import sys, argparse, datetime
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("csv", help="log dechiffre (sortie de ch7_decrypt.py)")
ap.add_argument("--window", type=int, default=40, help="taille fenetre en echantillons (40 = 20s)")
ap.add_argument("--stride", type=int, default=10, help="pas de glissement en echantillons")
ap.add_argument("--plot", default="", help="chemin PNG optionnel")
args = ap.parse_args()

# ---- 1. lire le CSV : timestamp + les 64 amplitudes de chaque ligne ----
ts, amps = [], []
with open(args.csv, "rb") as f:
    f.readline()                                   # saute l'en-tete
    for line in f:
        if not line.strip():
            continue
        t = int(line[:line.find(b",")])            # timestamp_ms = avant la 1re virgule
        a = line.find(b"[") + 1                     # les 64 nombres sont entre [ et ]
        b = line.find(b"]", a)
        amps.append(np.array(line[a:b].split(b","), dtype=float))
        ts.append(t)
ts = np.array(ts)
A  = np.vstack(amps)                                # tableau (N lignes, 64 sous-porteuses)
print(f"lignes={len(ts)}  sous-porteuses={A.shape[1]}  "
      f"de {datetime.datetime.utcfromtimestamp(ts[0]/1000)} a "
      f"{datetime.datetime.utcfromtimestamp(ts[-1]/1000)}")

# ---- 2. variance en fenetre glissante (le "gigotement" dans le temps) ----
W, st = args.window, args.stride
centers, scores = [], []
for i in range(0, len(ts) - W, st):
    # pour chaque sous-porteuse : variance sur la fenetre ; puis moyenne des 64
    scores.append(A[i:i+W].var(axis=0).mean())
    centers.append(i + W // 2)
scores = np.array(scores)
centers = np.array(centers)

# ---- 3. le minimum = la piece la plus vide = le bon moment ----
j = scores.argmin()
t_min = int(ts[centers[j]])
print(f"\n>>> MOMENT NON-GARDE (variance minimale) :")
print(f"    {datetime.datetime.utcfromtimestamp(t_min/1000)} UTC")
print(f"    variance = {scores[j]:.5f}  (le 'sol' ailleurs est ~0.34, le reste ~22)")
print(f"    epoch a soumettre (SECONDES) = {t_min // 1000}")

# combien de fenetres sont anormalement basses (< moitie du sol 0.34)
print(f"    fenetres sous 0.17 : {(scores < 0.17).sum()}  (unique = creux etroit)")

# ---- 4. graphique optionnel ----
if args.plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hours = (ts[centers] - ts[0]) / 3600000.0
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.semilogy(hours, scores, lw=0.6, color="#2066d6")
    ax.scatter([hours[j]], [scores[j]], color="red", zorder=5)
    ax.annotate(f"{datetime.datetime.utcfromtimestamp(t_min/1000).strftime('%H:%M:%S')}"
                f"\nvar={scores[j]:.4f}", xy=(hours[j], scores[j]),
                xytext=(hours[j]+2.5, scores[j]*8), color="red",
                arrowprops=dict(color="red", arrowstyle="->"))
    ax.set_xlabel("heure UTC"); ax.set_ylabel("variance (echelle log)")
    ax.set_title("CSI Wi-Fi — gigotement sur 24h"); ax.set_xticks(range(0, 25, 2))
    ax.grid(alpha=.3, which="both")
    plt.tight_layout(); plt.savefig(args.plot, dpi=110)
    print(f"\ngraphe -> {args.plot}")
