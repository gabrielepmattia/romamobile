#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test di caratterizzazione sui pickle salvati come base64 in colonne di testo.

Tre campi del backend serializzano un oggetto Python in pickle, lo codificano
base64 e lo mettono in una `TextField`:

- `PickledObjectField` (`servizi/utils.py`: `dbsafe_encode`/`dbsafe_decode`),
  usato da `paline.models` per `ArcoRimosso.eid` e `PercorsoSalvato`;
- `paline.models.ReteDinamicaSerializzata` (`set_rete`/`get_rete`);
- `carpooling.models.PercorsoSalvato` (`set_percorso`/`get_percorso`).

Al flip a Python 3 tutti e tre si rompono in modi che ne' `compileall` ne'
`check_imports` vedono:

- `base64.encodestring`/`decodestring` sono **rimosse in Python 3.9**;
- `base64.b64encode` su Python 3 torna `bytes`, e wrapparlo in `PickledObject`
  (sottoclasse di `str`) o assegnarlo a una colonna di testo lo corrompe come
  `str(b'...')`;
- un pickle scritto da Python 2 (byte-string per il testo) su Python 3 esplode
  in `pickle.loads` con `UnicodeDecodeError` sul primo byte accentato.

Questo script misura, invece di supporre, che dopo il batch:
1. il round-trip encode->decode regge sull'interprete corrente (numeri, testo
   accentato, struttura annidata, e il ramo compresso);
2. una riga scritta da **Python 2** si rilegge su **Python 3** (cross-version):
   `--dump` la fotografa su Py2, `--compare` la rilegge su Py3;
3. su Python 2 l'output e' **byte-identico** a quello del vecchio `b64encode`,
   cosi' le righe gia' in tabella non cambiano rappresentazione.

    # su Py2:
    python scripts/check_pickle_field_equivalence.py --dump /tmp/pkl-before.json
    # su Py3:
    python scripts/check_pickle_field_equivalence.py --compare /tmp/pkl-before.json
    # su ciascun interprete, il round-trip locale:
    python scripts/check_pickle_field_equivalence.py

Va eseguito con `src/` nel path (`-w /app` nel container), ma non richiede
Django: importa solo `servizi.py3compat`.
"""

from __future__ import print_function

import argparse
import base64
import json
import sys
import zlib
from copy import deepcopy

try:
	import cPickle as pickle
except ImportError:
	import pickle

from servizi.py3compat import (
	b64encode_text,
	b64decode_bytes,
	pickle_loads_py2compat,
)


# Payload scelti per coprire cio' che i tre campi contengono davvero:
# - `eid` di ArcoRimosso: tupla di interi (nessun str/bytes: deve reggere
#   ovunque, anche cross-version, senza scomodare il fallback latin1);
# - testo accentato (unicode, come lo da' l'ORM Django): e' il caso in cui un
#   pickle porta testo, e cross-version deve tornare identico;
# - struttura annidata tipo percorso salvato (coordinate + opzioni + testo).
PAYLOADS = {
	'eid_numerico': (12, 12345, 0),
	'testo_accentato': {u'nome': u'Città del Vaticano', u'via': u"Sant'Eustachio àèìòù"},
	'percorso_annidato': {
		'punti': [(41.9028, 12.4964), (41.8902, 12.4922)],
		'opzioni': {'mezzo': 1, 'nome': u'a piedi €'},
		'percorso': [1, 2, 3, u'fermata àccentata'],
	},
}


def encode_plain(value):
	"""Esattamente cio' che fa `dbsafe_encode(compress_object=False)` e
	`carpooling.PercorsoSalvato.set_percorso`."""
	return b64encode_text(pickle.dumps(deepcopy(value)))


def decode_plain(text):
	"""Inverso: `dbsafe_decode(compress_object=False)` /
	`get_percorso`."""
	return pickle_loads_py2compat(b64decode_bytes(text))


def encode_compressed(value):
	"""Ramo compresso: `dbsafe_encode(compress_object=True)` e la forma di
	`ReteDinamicaSerializzata.set_rete` (compress + b64)."""
	return b64encode_text(zlib.compress(pickle.dumps(deepcopy(value))))


def decode_compressed(text):
	"""Inverso: `dbsafe_decode(compress_object=True)` / `get_rete`."""
	return pickle_loads_py2compat(zlib.decompress(b64decode_bytes(text)))


def _label():
	return "Python %s, pickle proto default" % sys.version.split()[0]


def roundtrip_locale():
	"""Round-trip sull'interprete corrente, piano e compresso, piu' la prova
	che l'output e' testo (non bytes) e non si corrompe in una str-subclass."""
	ok = True
	print("== round-trip locale (%s)" % _label())

	class PickledObject(str):
		pass  # la vera classe di servizi/utils.py: sottoclasse di str

	for nome, payload in sorted(PAYLOADS.items()):
		enc = encode_plain(payload)
		# 1) l'output e' testo su entrambe le versioni
		is_text = not isinstance(enc, bytes)
		# 2) wrapparlo in una str-subclass non lo corrompe con "b'...'"
		wrapped = str(PickledObject(enc))
		no_corruption = "b'" not in wrapped[:2] and wrapped == enc
		# 3) round-trip
		back = decode_plain(enc)
		rt = back == payload
		# 4) ramo compresso
		back_c = decode_compressed(encode_compressed(payload))
		rt_c = back_c == payload
		esito = is_text and no_corruption and rt and rt_c
		ok = ok and esito
		print("  %-20s testo=%s no-corruzione=%s rt=%s rt_compresso=%s -> %s" % (
			nome, is_text, no_corruption, rt, rt_c, "OK" if esito else "FALLITO"))
	return ok


def byte_identita_py2():
	"""Solo su Python 2: `b64encode_text` deve dare lo stesso contenuto del
	vecchio `b64encode` grezzo, cosi' le righe gia' scritte non cambiano."""
	if sys.version_info[0] != 2:
		return True
	print("== byte-identita' con il vecchio b64encode (Python 2)")
	ok = True
	for nome, payload in sorted(PAYLOADS.items()):
		vecchio = base64.b64encode(pickle.dumps(deepcopy(payload)))  # str su Py2
		nuovo = encode_plain(payload)  # via b64encode_text
		# su Py2 il nuovo e' unicode; il confronto e' sul contenuto ASCII
		uguale = str(nuovo) == vecchio
		ok = ok and uguale
		print("  %-20s identico=%s" % (nome, uguale))
	return ok


def dump(path):
	"""Fotografa i blob prodotti dall'interprete corrente (da lanciare su Py2)."""
	ref = {'python': sys.version_info[0], 'plain': {}, 'compressed': {}}
	for nome, payload in PAYLOADS.items():
		ref['plain'][nome] = encode_plain(payload)
		ref['compressed'][nome] = encode_compressed(payload)
	with open(path, 'w') as f:
		json.dump(ref, f, indent=2, sort_keys=True)
	print("Riferimento scritto (%s): %d payload" % (_label(), len(PAYLOADS)))


def compare(path):
	"""Rilegge i blob del riferimento sull'interprete corrente (da lanciare su
	Py3): e' la prova cross-version che una riga Py2 sopravvive al flip."""
	with open(path) as f:
		ref = json.load(f)
	print("== cross-version: blob scritti da Python %s, riletti da %s" % (
		ref['python'], _label()))
	ok = True
	for nome, payload in sorted(PAYLOADS.items()):
		back = decode_plain(ref['plain'][nome])
		back_c = decode_compressed(ref['compressed'][nome])
		esito = back == payload and back_c == payload
		ok = ok and esito
		print("  %-20s plain=%s compresso=%s -> %s" % (
			nome, back == payload, back_c == payload, "OK" if esito else "FALLITO"))
	return ok


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	g = ap.add_mutually_exclusive_group()
	g.add_argument('--dump', metavar='FILE', help="scrive i blob dell'interprete corrente")
	g.add_argument('--compare', metavar='FILE', help="rilegge i blob del riferimento")
	args = ap.parse_args()

	if args.dump:
		dump(args.dump)
		return 0
	if args.compare:
		return 0 if compare(args.compare) else 1

	ok = roundtrip_locale()
	ok = byte_identita_py2() and ok
	print("ESITO:", "TUTTO OK" if ok else "FALLITO")
	return 0 if ok else 1


if __name__ == '__main__':
	sys.exit(main())
