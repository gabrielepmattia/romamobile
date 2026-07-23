# coding: utf-8

#
#    Copyright 2013-2016 Roma servizi per la mobilità srl
#    Developed by Luca Allulli and Damiano Morosi
#
#    This file is part of Roma mobile.
#
#    Roma mobile is free software: you can redistribute it
#    and/or modify it under the terms of the GNU General Public License as
#    published by the Free Software Foundation, version 2.
#
#    Roma mobile is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
#    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
#    for more details.
#
#    You should have received a copy of the GNU General Public License along with
#    Roma mobile. If not, see http://www.gnu.org/licenses/.
#

"""
Il minimo indispensabile di compatibilita' Python 2 / 3.

Fa il lavoro di `six` per i pochi nomi che servono qui, senza aggiungere una
dipendenza a `requirements.txt` (e quindi senza obbligare a ricostruire
l'immagine Docker a ogni batch della migrazione).

Quando il backend girera' solo su Python 3, questo modulo si svuota: ogni
`text_type` diventa `str` e gli import spariscono.
"""

import base64

try:
	import cPickle as pickle
except ImportError:
	import pickle

try:
	# Python 2: il tipo testuale e' `unicode`, `str` sono byte.
	text_type = unicode
	# Per i controlli "e' una stringa?": su Python 2 vanno accettati entrambi,
	# altrimenti un letterale non-unicode sfugge al test.
	string_types = (str, unicode)
except NameError:
	# Python 3: `str` e' gia' testo.
	text_type = str
	string_types = (str,)


def cmp(a, b):
	"""
	Il `cmp()` builtin di Python 2, rimosso in Python 3.

	Serve alle funzioni di confronto a tre vie che sopravvivono nel codice; su
	Python 2 il comportamento e' identico a quello del builtin che oscura.
	"""
	return (a > b) - (a < b)


def with_metaclass(meta, *bases):
	"""
	Crea una classe base con la metaclasse `meta`, come `six.with_metaclass`.

	Su Python 2 la metaclasse si dichiara con `__metaclass__ = meta` nel corpo
	della classe; ma quell'attributo Python 3 lo **ignora in silenzio**, e la
	metaclasse non verrebbe applicata -- un cambiamento di comportamento
	invisibile, non un errore. Questa forma la applica su **entrambe** le
	versioni. Su Python 2 il risultato e' identico a `__metaclass__ = meta`.
	"""
	class metaclass(type):
		def __new__(cls, name, this_bases, d):
			return meta(name, bases, d)

		@classmethod
		def __prepare__(cls, name, this_bases):
			return meta.__prepare__(name, bases)

	return type.__new__(metaclass, 'temporary_class', (), {})


def b64encode_text(data):
	"""
	Base64 di `data` (byte) restituita come **testo** (str su Py3, unicode su
	Py2), identica sulle due versioni.

	Sostituisce due forme che si rompono al flip a Python 3, entrambe usate per
	salvare un pickle dentro una colonna di testo del DB:

	- `base64.encodestring`, **rimossa in Python 3.9** (deprecata dalla 3.1):
	  su Py3.9 e' un `AttributeError` secco;
	- il `base64.b64encode` grezzo, che su Python 3 restituisce `bytes` -- e
	  assegnare `bytes` a una colonna di testo Django la corrompe, perche' il
	  valore finisce stringato come `str(b'...')`, col prefisso `b'` incluso.

	L'output non ha a capo; l'inverso `b64decode_bytes` accetta comunque il
	vecchio formato di `encodestring` (a capo ogni 76 caratteri), che
	`b64decode` scarta -- quindi le righe gia' in tabella restano leggibili.
	"""
	out = base64.b64encode(data)
	return out.decode('ascii') if isinstance(out, bytes) else out


def b64decode_bytes(text):
	"""
	Inverso di `b64encode_text`: da testo base64 a `bytes`.

	`base64.b64decode` esiste identica su Py2 e Py3 e scarta i caratteri fuori
	alfabeto, quindi legge anche l'output storico di `encodestring` (con a
	capo). Misurato uguale su entrambe le versioni.
	"""
	return base64.b64decode(text)


def pickle_loads_py2compat(data):
	"""
	`pickle.loads` che tollera un pickle scritto da **Python 2**.

	Un pickle Py2 memorizza il testo come byte-string; su Python 3 `pickle.loads`
	prova a decodificarlo come ASCII e scoppia (`UnicodeDecodeError`) sul primo
	byte accentato. Si ritenta con `encoding='latin1'`, che mappa i byte 1:1
	senza mai fallire -- il testo davvero non-ASCII resta come latin1 (da
	riconvertire a monte, se serve), ma niente eccezione e niente perdita di
	byte. Su Python 2 il ramo di ripiego non e' raggiungibile: un pickle Py2 si
	carica in modo nativo.
	"""
	try:
		return pickle.loads(data)
	except UnicodeDecodeError:
		# Solo Python 3: il kwarg `encoding` non esiste su Py2, ma li' questo
		# ramo non parte (un pickle Py2 non solleva UnicodeDecodeError).
		return pickle.loads(data, encoding='latin1')
