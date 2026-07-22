#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test di caratterizzazione sul contratto RPC fra `web` e `giano`.

E' il prerequisito per aggiornare RPyC (3.3 -> 4.x), l'unico passo della
migrazione che non e' incrementale: il protocollo cambia e i due servizi vanno
aggiornati insieme, senza possibilita' di tornare indietro un pezzo alla volta.

**Cosa confronta, e perche' non i valori.** Il payload che viaggia sul canale e'
pickle protocollo 2 in entrambe le direzioni:

    pickle.loads(getattr(connection.root, metodo)(pickle.dumps(param, 2)))

I dati che tornano sono in tempo reale -- arrivi, posizioni, previsioni -- e
cambiano a ogni chiamata: confrontarli sarebbe rumore. Quello che deve restare
stabile e' la **forma**: quali chiavi tornano, e di che tipo e' ciascun valore.

E' anche la cosa giusta da sorvegliare per questo salto in particolare. Il
rischio vero non e' che una chiave sparisca, ma che un valore cambi tipo in
silenzio: su Python 2 il pickle di una stringa di testo torna `unicode`, di una
stringa di byte torna `str`, e i due si confondono ovunque. Su Python 3 quella
distinzione diventa `str` contro `bytes` e smette di perdonare. Un'impronta dei
tipi intercetta il giorno in cui un `unicode` diventa `bytes`; un confronto sui
valori no.

Uso, dentro il container `web` (che ha i settings e la rete per parlare con
`giano`):

    python scripts/check_rpc_contract.py --dump /tmp/rpc-before.json
    python scripts/check_rpc_contract.py --compare /tmp/rpc-before.json

Gli argomenti delle chiamate sono fissi (vedi CHIAMATE) proprio perche' il
confronto abbia senso fra esecuzioni diverse.
"""

from __future__ import print_function

import argparse
import json
import os
import sys

# I settings vivono in src/, e i moduli top-level vanno importati come tali.
sys.path.insert(0, os.environ.get('APP_PATH', '/app'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')


# Chiamate a input fisso. Sono i metodi che la roadmap indica come piu' usati,
# piu' qualcuno scelto per coprire tipi di ritorno diversi.
#
# Gli identificativi vengono dagli endpoint gia' usati negli smoke test: la
# palina 73992 e la linea 64 esistono e hanno traffico, quindi la risposta non e'
# vuota -- una risposta vuota avrebbe un'impronta povera e non direbbe nulla.
CHIAMATE = [
	('tempi_attesa_ap', {'id_palina': '73992'}),
	# route_stats vuole gli id_percorso (RM173), non il nome della linea: con
	# quello sbagliato torna un dict vuoto, cioe' un'impronta che non dice nulla.
	('route_stats', {'route_ids': ['RM173']}),
	('percorso_fermate_ap', {'id_percorso': 'RM173'}),
	('veicoli_percorso_ap', {'id_percorso': 'RM173', 'get_arrivi': True}),
	('coordinate_palina', {'id_palina': '73992'}),
]


# Dizionari le cui **chiavi sono dati**, non struttura: `arrivi` mappa
# id_palina -> orario, quindi le chiavi cambiano a ogni veicolo e a ogni
# chiamata. Vanno dichiarati, perche' da un solo campione non c'e' modo di
# distinguere un record da una mappa.
CHIAVI_MAPPA = set(['arrivi'])

VUOTO = '(vuoto)'
ASSENTE = '(assente)'


def impronta(v, chiave=None, profondita=0):
	"""
	Riduce un valore alla sua forma: tipi e chiavi, senza i dati.

	Liste e mappe non producono una *varieta'* di impronte ma una sola, fusa:
	altrimenti il risultato dipenderebbe da quanti veicoli sono in strada e da
	quali fermate hanno davanti, cioe' da dati che cambiano ogni minuto.
	"""
	if profondita > 8:
		return '...'

	if v is None:
		return 'None'
	if isinstance(v, bool):
		return 'bool'

	if isinstance(v, dict):
		if chiave in CHIAVI_MAPPA:
			fusa = VUOTO
			for val in v.values():
				fusa = unisci(fusa, impronta(val, None, profondita + 1))
			return {'mappa di': fusa}
		return dict((str(k), impronta(v[k], str(k), profondita + 1))
		            for k in sorted(v, key=lambda x: str(x)))

	if isinstance(v, (list, tuple, set)):
		fusa = VUOTO
		for el in v:
			fusa = unisci(fusa, impronta(el, chiave, profondita + 1))
		return {type(v).__name__ + ' di': fusa}

	# Per gli scalari conta solo il tipo. In particolare `unicode` contro `str`
	# su Python 2: e' la distinzione che il passaggio a Python 3 mette alla prova.
	return type(v).__name__


def unisci(a, b):
	"""
	Fonde due impronte in una che descrive entrambe.

	I tipi scalari diversi diventano un'unione ordinata (`None|int` per un campo
	che a volte non c'e'), e una chiave presente solo da una parte viene marcata
	come opzionale. Cosi' l'impronta descrive il contratto e non il campione.
	"""
	if a == VUOTO:
		return b
	if b == VUOTO:
		return a
	if a == b:
		return a

	if isinstance(a, dict) and isinstance(b, dict):
		out = {}
		for k in set(a) | set(b):
			out[k] = unisci(a.get(k, ASSENTE), b.get(k, ASSENTE))
		return out

	if isinstance(a, dict) or isinstance(b, dict):
		# Forme incompatibili: va segnalato, non appiattito.
		return {'incoerente': sorted([json.dumps(a, sort_keys=True),
		                              json.dumps(b, sort_keys=True)])}

	return '|'.join(sorted(set(str(a).split('|')) | set(str(b).split('|'))))


def esegui():
	import django
	if hasattr(django, 'setup'):
		django.setup()

	from paline.models import get_web_cl_mercury

	merc = get_web_cl_mercury()

	out = {
		'python': sys.version_info[0],
		'chiamate': {},
	}
	try:
		import rpyc
		out['rpyc_version'] = getattr(rpyc, '__version__', '?')
	except Exception:
		out['rpyc_version'] = '?'

	for metodo, param in CHIAMATE:
		chiave = '%s(%s)' % (metodo, json.dumps(param, sort_keys=True))
		try:
			ris = merc.sync_any(metodo, param)
		except Exception as e:
			out['chiamate'][chiave] = {'errore': type(e).__name__}
			print("  %-52s ERRORE %s: %s" % (metodo, type(e).__name__, e))
			continue
		imp = impronta(ris)
		out['chiamate'][chiave] = {'impronta': imp}
		print("  %-52s ok" % metodo)

	chiudi(merc)
	return out


def chiudi(merc):
	"""
	Chiude la connessione RPyC verso `giano`.

	Senza, il processo **non esce**: RPyC 3.3 tiene thread di servizio non
	demoni sulla connessione, e l'interprete resta ad aspettarli a tempo
	indefinito. Il lavoro risulta fatto -- l'output e' completo, il file
	scritto -- ma il comando non torna mai, e in uno script di deploy questo
	significa una pipeline appesa invece di un errore.
	"""
	try:
		if getattr(merc, 'connection', None) is not None:
			merc.connection.close()
	except Exception:
		# La chiusura e' un dovere di pulizia, non un risultato da riportare:
		# se fallisce c'e' comunque la rete di sicurezza in main().
		pass


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--dump', metavar='FILE')
	ap.add_argument('--compare', metavar='FILE')
	args = ap.parse_args()

	print("contratto RPC web <-> giano")
	data = esegui()
	print("python %d, rpyc %s, %d chiamate"
	      % (data['python'], data['rpyc_version'], len(data['chiamate'])))

	if args.dump:
		with open(args.dump, 'w') as f:
			json.dump(data, f, indent=1, sort_keys=True)
		print("scritto %s" % args.dump)
		return 0

	if not args.compare:
		ap.error("serve --dump o --compare")

	with open(args.compare) as f:
		ref = json.load(f)
	print("riferimento: python %s, rpyc %s"
	      % (ref['python'], ref.get('rpyc_version')))

	ok = True
	chiavi = sorted(set(ref['chiamate']) | set(data['chiamate']))
	for k in chiavi:
		a = ref['chiamate'].get(k)
		b = data['chiamate'].get(k)
		nome = k.split('(')[0]
		if a is None or b is None:
			ok = False
			print("  %-52s MANCANTE (%s)" % (nome, 'prima' if a is None else 'dopo'))
			continue
		if compatibili(a.get('impronta'), b.get('impronta')):
			print("  %-52s identico" % nome)
			continue
		ok = False
		print("  %-52s DIVERSO" % nome)
		for riga in _differenze(a.get('impronta'), b.get('impronta'), ''):
			print("      %s" % riga)

	print("ESITO: %s" % ("CONTRATTO INVARIATO" if ok else "CONTRATTO CAMBIATO"))
	return 0 if ok else 1


def _tipi_informativi(imp):
	"""
	I tipi che un'impronta scalare dichiara davvero, tolti i non-informativi.

	`None` e `(assente)` dicono che *in quel campione* il valore mancava, non
	che il contratto sia cambiato: un campo nullable e' `None` in un giro e
	`int` in quello dopo a seconda di cosa passa in strada in quel momento.
	"""
	return set(str(imp).split('|')) - set([('None'), ASSENTE])


def compatibili(a, b):
	"""
	Se due impronte descrivono lo stesso contratto.

	Piu' permissiva dell'uguaglianza, ma solo sulla nullabilita': i **tipi**
	devono coincidere. Un `unicode` che diventa `bytes` -- il rischio vero del
	passaggio a Python 3 -- resta incompatibile.
	"""
	if isinstance(a, dict) and isinstance(b, dict):
		if set(a) != set(b):
			return False
		return all(compatibili(a[k], b[k]) for k in a)
	if isinstance(a, dict) or isinstance(b, dict):
		return False
	ta, tb = _tipi_informativi(a), _tipi_informativi(b)
	# Un campione in cui il valore era sempre assente non dice nulla sul tipo:
	# non e' una prova di cambiamento.
	if not ta or not tb:
		return True
	return ta == tb


def _differenze(a, b, prefisso):
	"""Elenca i punti in cui due impronte divergono, con il percorso della chiave."""
	if isinstance(a, dict) and isinstance(b, dict):
		righe = []
		for k in sorted(set(a) | set(b)):
			p = '%s.%s' % (prefisso, k) if prefisso else k
			if k not in a:
				righe.append('%s: comparso (%r)' % (p, b[k]))
			elif k not in b:
				righe.append('%s: sparito (%r)' % (p, a[k]))
			else:
				righe.extend(_differenze(a[k], b[k], p))
		return righe
	if not compatibili(a, b):
		return ['%s: %r -> %r' % (prefisso or '(radice)', a, b)]
	return []


if __name__ == '__main__':
	rc = main()
	# Rete di sicurezza per l'uscita: se `chiudi()` non e' bastato a liberare i
	# thread di RPyC, `sys.exit` resterebbe ad aspettarli. Qui il lavoro e'
	# finito e l'output e' gia' stampato, quindi terminare di netto e' corretto
	# -- purche' lo stdout sia stato svuotato prima, altrimenti l'ultima riga
	# si perde.
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(rc)
