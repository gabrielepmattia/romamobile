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
