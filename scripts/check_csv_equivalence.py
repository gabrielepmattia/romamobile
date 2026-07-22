#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test di caratterizzazione su `servizi/unicode_csv.py`.

Quel modulo e' impalcatura per il `csv` di Python 2, che non sa gestire il
testo: si scrive in byte e si converte a mano. Su Python 3 il `csv` lavora
gia' in testo, quindi il modulo va ridotto a un passacarte.

Riscriverlo significa cambiare come vengono prodotti file che qualcuno
consuma. Questo script fissa i byte esatti generati dalla versione attuale su
Python 2, cosi' che la riscrittura possa essere confrontata invece che
sperata; e verifica che Python 3 produca gli stessi byte.

    python scripts/check_csv_equivalence.py --dump /tmp/csv-before.json
    python scripts/check_csv_equivalence.py --compare /tmp/csv-before.json

Va eseguito con `src/` nel path (`-w /app` nel container).
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys
import tempfile

from servizi.unicode_csv import UnicodeDictReader, UnicodeLazyDictWriter

# Righe scelte per i casi che rompono un writer CSV scritto a mano: accenti non
# ASCII, il delimitatore dentro un campo, virgolette da raddoppiare, un a capo
# incorporato, campi vuoti e una stringa gia' byte invece che testo.
ROWS = [
	{u'nome': u'Città del Vaticano', u'note': u'accenti: àèìòù ÀÈÌÒÙ', u'n': u'1'},
	{u'nome': u'Punto e virgola; dentro', u'note': u'virgolette "doppie" qui', u'n': u'2'},
	{u'nome': u'A capo\nincorporato', u'note': u'', u'n': u'3'},
	{u'nome': u'', u'note': u'euro € e simboli ©®', u'n': u'4'},
	{u'nome': u'ordine dei campi', u'note': u'ultimo', u'n': u'5'},
]

ENCODINGS = ['utf-8', 'latin-1']


def _csv_open():
	"""
	`csv_open` del modulo, se esiste; altrimenti l'`open` semplice.

	Il fallback serve a catturare il riferimento *prima* della riscrittura,
	quando quella funzione ancora non c'e': i chiamanti usavano `open(path, 'w')`
	direttamente. Su Linux 'w' e 'wb' danno gli stessi byte, quindi il confronto
	fra il prima e il dopo resta legittimo.
	"""
	try:
		from servizi.unicode_csv import csv_open
		return csv_open
	except ImportError:
		return lambda path, mode, encoding=None: open(path, mode)


def scrivi(encoding):
	"""Scrive le righe con UnicodeLazyDictWriter e restituisce i byte del file."""
	fd, path = tempfile.mkstemp(suffix='.csv')
	os.close(fd)
	try:
		# Il modo di apertura e' quello usato dai chiamanti reali
		# (risorse/management/commands/csv2risorsa.py).
		csv_open = _csv_open()
		f = csv_open(path, 'w', encoding=encoding)
		try:
			w = UnicodeLazyDictWriter(f, delimiter=';', encoding=encoding)
			w.writerows(ROWS)
		finally:
			f.close()
		with open(path, 'rb') as f:
			return f.read()
	finally:
		os.unlink(path)


def rileggi(data, encoding):
	"""Rilegge i byte con UnicodeDictReader: il giro completo deve tornare."""
	fd, path = tempfile.mkstemp(suffix='.csv')
	os.close(fd)
	try:
		with open(path, 'wb') as f:
			f.write(data)
		csv_open = _csv_open()
		f = csv_open(path, 'r', encoding=encoding)
		try:
			return [dict(r) for r in UnicodeDictReader(f, delimiter=';', encoding=encoding)]
		finally:
			f.close()
	finally:
		os.unlink(path)


def measure():
	out = {'python': sys.version_info[0], 'per_encoding': {}}
	for enc in ENCODINGS:
		try:
			data = scrivi(enc)
		except Exception as e:
			# Solo il tipo, non il messaggio: la posizione del carattere
			# incriminato dipende da dove avviene la codifica, che e'
			# esattamente cio' che la riscrittura cambia.
			out['per_encoding'][enc] = {'errore': type(e).__name__}
			continue
		try:
			riletto = rileggi(data, enc)
		except Exception as e:
			riletto = {'errore': type(e).__name__}
		out['per_encoding'][enc] = {
			'sha1': hashlib.sha1(data).hexdigest(),
			'lunghezza': len(data),
			# Repr dei byte: se qualcosa cambia, si vede *cosa* invece del solo hash.
			'testo': data.decode(enc, 'replace'),
			'riletto': riletto,
		}
	return out


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--dump', metavar='FILE')
	ap.add_argument('--compare', metavar='FILE')
	args = ap.parse_args()

	data = measure()
	for enc, r in sorted(data['per_encoding'].items()):
		if 'errore' in r:
			print("py%d %-8s ERRORE %s" % (data['python'], enc, r['errore']))
		else:
			print("py%d %-8s %d byte, sha1 %s" % (data['python'], enc, r['lunghezza'], r['sha1']))

	if args.dump:
		with open(args.dump, 'w') as f:
			json.dump(data, f, indent=1, sort_keys=True)
		print("scritto %s" % args.dump)
		return 0

	if not args.compare:
		ap.error("serve --dump o --compare")

	with open(args.compare) as f:
		ref = json.load(f)
	print("riferimento: python %s" % ref['python'])

	# Due livelli di pretesa, perche' non sono la stessa cosa:
	#
	#  - stesso interprete del riferimento: i byte devono coincidere. E' il
	#    requisito di oggi, visto che in produzione gira ancora Python 2.
	#  - interprete diverso: si pretende che il *contenuto* riletto coincida.
	#    L'ordine delle colonne no: nasce da `list(row)` su un dict, quindi
	#    ordine di hash su Py2 e ordine di inserimento su Py3.7+. Il file resta
	#    corretto (l'intestazione nomina le colonne), ma un consumatore che
	#    legge per posizione anziche' per nome si romperebbe.
	stesso_interprete = ref['python'] == data['python']
	print("confronto: %s" % ("byte a byte (stesso interprete)" if stesso_interprete
	                         else "solo contenuto (interpreti diversi)"))

	ok = True
	for enc in ENCODINGS:
		a = ref['per_encoding'].get(enc, {})
		b = data['per_encoding'].get(enc, {})

		if a.get('errore') or b.get('errore'):
			if a.get('errore') == b.get('errore'):
				print("  %-8s stesso errore atteso: %s" % (enc, a.get('errore')))
			else:
				ok = False
				print("  %-8s ERRORE DIVERSO prima=%r dopo=%r"
				      % (enc, a.get('errore'), b.get('errore')))
			continue

		if a.get('riletto') != b.get('riletto'):
			ok = False
			print("  %-8s CONTENUTO DIVERSO" % enc)
			print("      prima=%r" % (a.get('riletto'),))
			print("      dopo =%r" % (b.get('riletto'),))
			continue

		if stesso_interprete and a.get('sha1') != b.get('sha1'):
			ok = False
			print("  %-8s BYTE DIVERSI (%s -> %s)" % (enc, a.get('sha1'), b.get('sha1')))
			print("      prima=%r" % a.get('testo'))
			print("      dopo =%r" % b.get('testo'))
			continue

		if a.get('sha1') != b.get('sha1'):
			print("  %-8s contenuto identico; byte diversi (ordine colonne): %r -> %r"
			      % (enc, _intestazione(a), _intestazione(b)))
		else:
			print("  %-8s identico" % enc)

	print("ESITO: %s" % ("IDENTICI" if ok else "DIFFERENZE"))
	return 0 if ok else 1


def _intestazione(r):
	testo = r.get('testo') or ''
	return testo.split('\r\n')[0]


if __name__ == '__main__':
	sys.exit(main())
