# coding: utf-8
"""
Verifica che il passaggio da `sort(cmp=f)` a `sort(key=cmp_to_key(f))` non cambi
l'ordine prodotto (vedi documentation/features/migrazione-stack-modernizzazione.md).

Va eseguito con **Python 2**, l'unico che ha ancora `sorted(..., cmp=...)` con cui
confrontarsi. Le funzioni di confronto in gioco sono a piu' livelli (tempo di
attesa, distanza in fermate, capolinea, prossima partenza) e riscriverle come
`key=` sarebbe stato facile da sbagliare in silenzio: qui si confrontano le due
strade su input generati a caso, inclusi i casi limite (-1, capolinea, partenza
sconosciuta) e i pareggi.

    python scripts/check_sort_equivalence.py
"""

from __future__ import print_function

import os
import random
import sys
from functools import cmp_to_key

SRC = '/app' if os.path.isdir('/app/paline') else os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
sys.path.insert(0, SRC)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

from paline.models import cmp_tempi_attesa, _cmp_linea_tempo


def arrivo(rnd):
	"""Un arrivo plausibile, con i casi limite ben rappresentati."""
	a_capolinea = rnd.random() < 0.4
	return {
		# -1 significa "tempo sconosciuto" ed e' trattato a parte dal confronto
		'tempo_attesa': rnd.choice([-1, -1, 0, 1, 2, 5, 10, 30]),
		'distanza_fermate': rnd.choice([0, 1, 2, 5, 12, 26]),
		'a_capolinea': a_capolinea,
		'prossima_partenza': rnd.choice(['', '', '20:04', '20:12', '20:22']),
		'linea': rnd.choice(['62', '64', '64', 'MEA', 'N1']),
	}


def main():
	if sys.version_info[0] != 2:
		print('Serve Python 2: e\' l\'unico che ha sorted(..., cmp=...)')
		return 2

	rnd = random.Random(20260721)  # deterministico: un fallimento e' riproducibile
	for name, func in [('cmp_tempi_attesa', cmp_tempi_attesa), ('_cmp_linea_tempo', _cmp_linea_tempo)]:
		for trial in range(2000):
			data = [arrivo(rnd) for _ in range(rnd.randint(2, 15))]
			atteso = sorted(data, cmp=func)
			ottenuto = sorted(data, key=cmp_to_key(func))
			if atteso != ottenuto:
				print('DIVERSI su %s, tentativo %d' % (name, trial))
				print('  input:    %r' % (data,))
				print('  cmp=:     %r' % (atteso,))
				print('  key=:     %r' % (ottenuto,))
				return 1
		print('ok %s: 2000 permutazioni casuali ordinate in modo identico' % name)
	return 0


if __name__ == '__main__':
	sys.exit(main())
