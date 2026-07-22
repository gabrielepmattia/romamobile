#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test di caratterizzazione sulle conversioni Gauss-Boaga Est <-> WGS84.

Serve a validare l'aggiornamento di pyproj (1.9.5.1 -> 2.x), che porta con se'
il salto della libreria C sottostante da PROJ 4 a PROJ 6. L'API usata da
`geomath` e' il Proj chiamabile (`gbfe(x, y)` / `inverse=True`), che nelle due
versioni si scrive identica: proprio per questo un cambio di risultato
passerebbe inosservato, ed e' il motivo per cui questo confronto esiste.

Uso:

    # con la versione VECCHIA installata
    python scripts/check_proj_equivalence.py --dump /tmp/proj-before.json

    # con la versione NUOVA installata
    python scripts/check_proj_equivalence.py --compare /tmp/proj-before.json

Il dump non dipende dal resto del progetto (niente Django, niente DB): ricrea
le due proiezioni dalle stesse stringhe proj4 di `paline/geomath.py`.
"""

from __future__ import print_function

import argparse
import json
import sys

import pyproj

# Identiche a quelle in paline/geomath.py. Ripetute e non importate di
# proposito: il confronto deve restare valido anche se un giorno geomath
# cambiasse, e questo script deve poter girare senza i settings Django.
GBFE_PROJ = "+proj=tmerc +lat_0=0 +lon_0=15 +k=0.9996 +x_0=2520000 +y_0=0 +ellps=intl +units=m +no_defs"
CORR_GBFE = (-16, 78)

# Riquadro su Roma, abbondante: comprende il GRA e un margine oltre il confine
# comunale. I passi sono scelti per dare 21 x 21 = 441 punti.
LON_MIN, LON_MAX = 12.20, 12.70
LAT_MIN, LAT_MAX = 41.70, 42.10
STEPS = 20

# Soglia oltre la quale la differenza fra le due versioni conta davvero.
#
# 1 mm, cioe' circa 1e-8 gradi. Non e' un valore scelto per far passare il test:
# e' tre ordini di grandezza sotto qualunque cosa questo codice possa
# rappresentare. Le coordinate delle paline hanno precisione metrica, e proprio
# in geomath.py convive una correzione fissa `corr_gbfe = (-16, 78)` -- decine
# di metri applicati a mano. Una differenza sub-millimetrica fra PROJ 4 e PROJ 6
# e' rumore di virgola mobile; una differenza di *modello geodetico* (datum
# diverso, towgs84 mancante) si manifesterebbe con decine o centinaia di metri e
# verrebbe intercettata da questa soglia con enorme margine.
TOL_M = 1e-3
TOL_DEG = 1e-8


def build():
	return pyproj.Proj(GBFE_PROJ)


def gbfe_to_wgs84(gbfe, x, y):
	x, y = (x + CORR_GBFE[0], y + CORR_GBFE[1])
	return gbfe(x, y, inverse=True)


def wgs84_to_gbfe(gbfe, x, y):
	x, y = gbfe(x, y)
	return (x - CORR_GBFE[0], y - CORR_GBFE[1])


def grid():
	"""Punti WGS84 deterministici (nessun random: i due run devono coincidere)."""
	for i in range(STEPS + 1):
		for j in range(STEPS + 1):
			lon = LON_MIN + (LON_MAX - LON_MIN) * i / float(STEPS)
			lat = LAT_MIN + (LAT_MAX - LAT_MIN) * j / float(STEPS)
			yield (lon, lat)


def measure():
	gbfe = build()
	rows = []
	for lon, lat in grid():
		x, y = wgs84_to_gbfe(gbfe, lon, lat)
		lon2, lat2 = gbfe_to_wgs84(gbfe, x, y)
		rows.append({
			"lon": lon, "lat": lat,
			"x": x, "y": y,
			"lon_rt": lon2, "lat_rt": lat2,
		})
	return {
		"pyproj_version": getattr(pyproj, "__version__", "?"),
		"proj_version": str(getattr(pyproj, "proj_version_str", "?")),
		"rows": rows,
	}


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--dump", metavar="FILE")
	ap.add_argument("--compare", metavar="FILE")
	args = ap.parse_args()

	data = measure()
	print("pyproj %s (PROJ %s), %d punti"
	      % (data["pyproj_version"], data["proj_version"], len(data["rows"])))

	if args.dump:
		with open(args.dump, "w") as f:
			json.dump(data, f, indent=1, sort_keys=True)
		print("scritto %s" % args.dump)
		return 0

	if not args.compare:
		ap.error("serve --dump o --compare")

	with open(args.compare) as f:
		ref = json.load(f)

	print("riferimento: pyproj %s (PROJ %s)"
	      % (ref["pyproj_version"], ref["proj_version"]))

	if len(ref["rows"]) != len(data["rows"]):
		print("ERRORE: numero di punti diverso, confronto impossibile")
		return 2

	# Scarti massimi, separati per direzione: metri sul Gauss-Boaga, gradi sul
	# WGS84. Tenerli distinti evita di confrontare unita' diverse.
	worst_m = 0.0
	worst_deg = 0.0
	worst_rt = 0.0
	worst_point = None
	for a, b in zip(ref["rows"], data["rows"]):
		dm = max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"]))
		dd = max(abs(a["lon_rt"] - b["lon_rt"]), abs(a["lat_rt"] - b["lat_rt"]))
		# Errore di andata e ritorno *dentro* la versione nuova: dice se la
		# conversione e' autoconsistente, indipendentemente dal riferimento.
		rt = max(abs(b["lon"] - b["lon_rt"]), abs(b["lat"] - b["lat_rt"]))
		if dm > worst_m:
			worst_m, worst_point = dm, (b["lon"], b["lat"])
		worst_deg = max(worst_deg, dd)
		worst_rt = max(worst_rt, rt)

	print("scarto max WGS84 -> GBFE : %.9f m" % worst_m)
	print("scarto max GBFE -> WGS84 : %.12f gradi (~%.4f mm)"
	      % (worst_deg, worst_deg * 111320.0 * 1000))
	print("errore andata/ritorno    : %.12f gradi" % worst_rt)
	if worst_point:
		print("punto peggiore           : lon=%.5f lat=%.5f" % worst_point)

	ok = worst_m < TOL_M and worst_deg < TOL_DEG
	print("tolleranza               : %g m / %g gradi" % (TOL_M, TOL_DEG))
	print("ESITO: %s" % ("EQUIVALENTI" if ok else "DIFFERENZE SIGNIFICATIVE"))
	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main())
