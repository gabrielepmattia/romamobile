#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Smoke test end-to-end sui percorsi critici di Roma mobile.

Verifica lo stato HTTP **e** la presenza di contenuto atteso. Le due cose non
sono equivalenti, ed e' il punto di questo script: il 22 luglio 2026 il daemon
`giano` e' rimasto giu' per 441 restart senza che nessun controllo se ne
accorgesse, perche' `web` continuava a rispondere 200 su ogni pagina. Erano solo
pagine vuote di dati -- niente arrivi in tempo reale, niente calcolo percorso.

Da qui la distinzione fra due tipi di controllo:

  - `contiene`: marcatori che devono esserci comunque. Se mancano, la pagina e'
    rotta.
  - `richiede_rpc`: marcatori che compaiono **solo** se la catena
    `web` -> RPyC -> `giano` e' viva. Se mancano, il sito e' su ma cieco: e'
    esattamente il guasto che era sfuggito.

Uso (dal container `web`, o da qualunque posto che raggiunga il servizio):

    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://127.0.0.1:8000
    python scripts/smoke_test.py --verbose

Esce con 0 se tutto passa, 1 se qualcosa fallisce: e' pensato per essere
incatenato in uno script di deploy.
"""

from __future__ import print_function

import argparse
import re
import sys

try:
	from urllib.request import urlopen, Request
	from urllib.error import HTTPError, URLError
	from urllib.parse import urlencode
except ImportError:  # Python 2
	from urllib2 import urlopen, Request, HTTPError, URLError
	from urllib import urlencode


BASE_DEFAULT = 'http://127.0.0.1:8000'

# Un percorso a piedi + metro fra due punti noti del centro (Colosseo ->
# Termini), espresso in coordinate per non dipendere dal geocoder esterno. E'
# lo stesso input usato come test di caratterizzazione del routing nel batch 7.
PERCORSO_QUERY = urlencode([
	('start_address', 'punto:(41.8902,12.4922)'),
	('stop_address', 'punto:(41.9009,12.5020)'),
	('quando', '0'),
	('mezzo', '1'),
	('Submit', 'Cerca'),
])

# (nome, percorso, stato atteso, marcatori sempre attesi, marcatori che
#  richiedono giano vivo)
CASI = [
	('home',            '/',                        200, ['Roma'], []),
	('metro',           '/metro/',                  200, ['Metro A', 'Metro B', 'Metro C'], []),
	('linea bus',       '/paline/linea/64',         200, ['64'], []),
	('linea metro',     '/paline/linea/MEA',        200, [], []),
	('percorso linea',  '/paline/percorso/RM173',   200, [], []),
	# Il dettaglio palina e' l'unica pagina che passa dall'RPC per forza: se
	# `giano` e' giu' resta 200 ma perde il riquadro delle previsioni.
	('dettaglio palina','/paline/palina/73992',     200, [], [r'people_[0-9]', r'\bmin\b']),
	('elenco linee',    '/paline/elenco_linee',     200, [], []),
	('news',            '/news/',                   200, [], []),
	('meteo',           '/meteo/',                  200, [], []),
	('parcheggi',       '/parcheggi/',              200, [], []),
	('ztl',             '/ztl/',                    200, [], []),
	('lingua',          '/lingua/',                 200, [], []),
	('form percorso',   '/percorso/',               200, [], []),
	# Il calcolo percorso vero: esercita grafo e routing dentro `giano`.
	('calcolo percorso','/percorso/?' + PERCORSO_QUERY, 200, [], ['minut', r'\d+[.,]\d+ km|\d+ m ']),
]

# Dimensione sotto la quale una pagina e' sospetta anche se risponde 200.
MINIMO_BYTE = 500


def scarica(url, timeout):
	req = Request(url, headers={'User-Agent': 'romamobile-smoke-test'})
	try:
		r = urlopen(req, timeout=timeout)
		return r.getcode(), r.read()
	except HTTPError as e:
		return e.code, e.read() if hasattr(e, 'read') else b''
	except URLError as e:
		return None, str(e).encode('utf-8', 'replace')


def controlla(base, caso, timeout, verbose):
	nome, percorso, atteso, contiene, richiede_rpc = caso
	url = base.rstrip('/') + percorso
	codice, corpo = scarica(url, timeout)

	if codice is None:
		return False, 'irraggiungibile: %s' % corpo.decode('utf-8', 'replace')[:80], False
	if codice != atteso:
		return False, 'HTTP %s (atteso %s)' % (codice, atteso), False

	testo = corpo.decode('utf-8', 'replace')

	if len(corpo) < MINIMO_BYTE:
		return False, 'HTTP %s ma solo %d byte' % (codice, len(corpo)), False

	mancanti = [m for m in contiene if not re.search(m, testo)]
	if mancanti:
		return False, 'HTTP %s, %d byte, manca %s' % (codice, len(corpo), mancanti), False

	# I marcatori RPC non fanno fallire da soli: distinguono "rotto" da "cieco".
	rpc_mancanti = [m for m in richiede_rpc if not re.search(m, testo)]
	degradato = bool(rpc_mancanti)

	dettaglio = 'HTTP %s, %d byte' % (codice, len(corpo))
	if degradato:
		dettaglio += ' -- SENZA DATI RPC (manca %s)' % rpc_mancanti
	elif verbose and richiede_rpc:
		dettaglio += ', dati RPC presenti'
	return True, dettaglio, degradato


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--base', default=BASE_DEFAULT,
	                help='URL di base del servizio (default %s)' % BASE_DEFAULT)
	ap.add_argument('--timeout', type=float, default=60.0)
	ap.add_argument('--verbose', action='store_true')
	args = ap.parse_args()

	print("smoke test su %s" % args.base)
	falliti = []
	degradati = []
	for caso in CASI:
		nome = caso[0]
		ok, dettaglio, degradato = controlla(args.base, caso, args.timeout, args.verbose)
		stato = 'ok  ' if ok else 'FAIL'
		if degradato:
			stato = 'CIECO'
		print("  %-5s %-18s %s" % (stato, nome, dettaglio))
		if not ok:
			falliti.append(nome)
		elif degradato:
			degradati.append(nome)

	print("")
	if falliti:
		print("ESITO: %d falliti (%s)" % (len(falliti), ', '.join(falliti)))
		return 1
	if degradati:
		print("ESITO: tutte le pagine rispondono, ma %d sono senza dati in tempo reale"
		      % len(degradati))
		print("       (%s)" % ', '.join(degradati))
		print("       Controllare `giano`: docker inspect romamobile-giano-1"
		      " --format '{{.State.Status}} {{.RestartCount}}'")
		return 1
	print("ESITO: tutto ok (%d controlli)" % len(CASI))
	return 0


if __name__ == '__main__':
	sys.exit(main())
