# coding: utf-8
"""
Confronta l'encoder polyline attuale (cGPolyEncode, binding C senza release
Python 3) con il candidato sostituto puro-Python `polyline`.

Le due non sono equivalenti, ed e' bene saperlo con un numero in mano invece che
a intuito: `cGPolyEncode` **semplifica** la polilinea (scarta i vertici sotto una
soglia, come faceva l'encoder di Google Maps v2), `polyline` la codifica tutta.
Questo script misura di quanto: quanti vertici in meno e quanto si sposta il
tracciato.

Conseguenza pratica da tenere a mente: senza semplificazione l'URL della mappa
statica si allunga, e Google Static Maps ha un limite di lunghezza.

Attenzione all'ordine delle coordinate: qui i punti arrivano da
geomath.gbfe_to_wgs84(), che restituisce (lon, lat) — mentre `polyline.encode()`
di default si aspetta (lat, lon) e vuole `geojson=True` per invertire.

    python scripts/check_polyline_equivalence.py
"""

from __future__ import print_function

import math
import random
import sys

import cgpolyencode
import polyline as polyline_lib


def punti_roma(rnd, n):
	"""Una polilinea plausibile dentro Roma, in (lon, lat) come nel codice."""
	lon, lat = 12.4922, 41.8902
	out = []
	for _ in range(n):
		lon += rnd.uniform(-0.002, 0.002)
		lat += rnd.uniform(-0.002, 0.002)
		out.append((lon, lat))
	return out


def metri(p, q):
	"""Distanza approssimata fra due (lon, lat), sufficiente a questa scala."""
	dlon = (p[0] - q[0]) * 111320.0 * math.cos(math.radians(p[1]))
	dlat = (p[1] - q[1]) * 110540.0
	return math.sqrt(dlon * dlon + dlat * dlat)


def main():
	rnd = random.Random(20260721)
	encoder = cgpolyencode.GPolyEncoder()
	scarto_max = 0.0
	lunghezza_max = 0.0

	print('%8s %10s %10s %12s %12s' % ('punti', 'vecchio', 'nuovo', 'len vecchio', 'len nuovo'))
	for n in [2, 3, 5, 10, 50, 200]:
		v_punti = n_punti = v_len = n_len = 0
		for _ in range(50):
			punti = punti_roma(rnd, n)
			s_vecchio = encoder.encode(punti)['points']
			s_nuovo = polyline_lib.encode(punti, geojson=True)
			d_vecchio = polyline_lib.decode(s_vecchio, geojson=True)
			d_nuovo = polyline_lib.decode(s_nuovo, geojson=True)
			v_punti += len(d_vecchio)
			n_punti += len(d_nuovo)
			v_len += len(s_vecchio)
			n_len += len(s_nuovo)
			# scarto fra i due tracciati: per ogni vertice del nuovo, la distanza
			# dal vertice piu' vicino del vecchio
			for b in d_nuovo:
				scarto_max = max(scarto_max, min(metri(a, b) for a in d_vecchio))
		print('%8d %10.1f %10.1f %12.1f %12.1f' % (n, v_punti / 50.0, n_punti / 50.0, v_len / 50.0, n_len / 50.0))
		lunghezza_max = max(lunghezza_max, n_len / 50.0)

	print('')
	print('scarto massimo del tracciato: %.1f metri' % scarto_max)
	print('(colonne: vertici e caratteri prodotti, media su 50 polilinee)')
	return 0


if __name__ == '__main__':
	sys.exit(main())
