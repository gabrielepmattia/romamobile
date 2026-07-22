# coding: utf-8
"""
Compatibilita' CSV fra Python 2 e Python 3.

Il modulo `csv` di Python 2 non sa gestire il testo: legge e scrive byte, e chi
ha a che fare con caratteri non ASCII deve convertire a mano. Da qui questo
wrapper. Su Python 3 il problema non esiste, `csv` lavora gia' in testo: la
conversione la fa il file, aperto con l'encoding giusto.

Quindi qui dentro convivono due implementazioni. Quella per Python 2 riproduce
byte per byte il comportamento storico (validata da
`scripts/check_csv_equivalence.py`); quella per Python 3 e' un passacarte sul
modulo standard. **Quando il backend sara' solo Python 3 questo file sparisce**
e i chiamanti useranno `csv` direttamente: restano due, `paline/gtfs.py` non e'
piu' fra loro perche' e' stato rimosso (era irraggiungibile).

Differenza nota fra le due versioni, non risolvibile qui: `UnicodeLazyDictWriter`
deduce l'ordine delle colonne da `list(row)` sul primo dizionario scritto. Su
Python 2 e' l'ordine di hash delle chiavi, su Python 3.7+ quello di inserimento,
quindi **l'ordine delle colonne nel file cambia** al passaggio. L'intestazione
nomina le colonne, quindi chi legge per nome non se ne accorge; chi legge per
posizione si romperebbe.
"""

from __future__ import print_function

import csv
import io
import sys

PY2 = sys.version_info[0] == 2


def csv_open(path, mode, encoding='utf-8'):
	"""
	Apre un file CSV nel modo che l'interprete corrente si aspetta.

	Su Python 2 in binario, perche' il `csv` lavora su byte e la conversione la
	fanno le classi qui sotto. Su Python 3 in testo con l'encoding richiesto, e
	`newline=''` come impone la documentazione del modulo `csv`: senza, i
	ritorni a capo dentro i campi quotati vengono tradotti e il file si corrompe.
	"""
	if PY2:
		return open(path, mode + 'b')
	return io.open(path, mode, encoding=encoding, newline='')


if PY2:

	class UnicodeCsvReader(object):
		"""Legge righe di byte e le restituisce decodificate."""

		def __init__(self, f, encoding="utf-8", **kwargs):
			self.csv_reader = csv.reader(f, **kwargs)
			self.encoding = encoding

		def __iter__(self):
			return self

		def next(self):
			row = next(self.csv_reader)
			return [cell.decode(self.encoding) for cell in row]

		@property
		def line_num(self):
			return self.csv_reader.line_num

	class UnicodeDictReader(csv.DictReader):
		def __init__(self, f, encoding="utf-8", fieldnames=None, **kwds):
			csv.DictReader.__init__(self, f, fieldnames=fieldnames, **kwds)
			# DictReader legge le righe da `self.reader`: sostituendolo con
			# quello che decodifica, sia i nomi dei campi sia i valori
			# arrivano gia' come testo.
			self.reader = UnicodeCsvReader(f, encoding=encoding, **kwds)

	class _DictWriter(object):
		"""
		DictWriter che codifica testo in byte prima di passarlo al `csv`.

		Rispetto alla versione storica non c'e' piu' il giro attraverso un
		`cStringIO` con un encoder incrementale: si codifica direttamente
		nell'encoding di destinazione e si scrive sul file. I byte prodotti
		sono gli stessi -- il passaggio intermedio codificava in utf-8, poi
		decodificava e ricodificava, cioe' un giro a vuoto.
		"""

		def __init__(self, f, fieldnames, dialect=csv.excel, encoding="utf-8", **kwds):
			self.encoding = encoding
			self.writer = csv.DictWriter(
				f, [self._enc(n) for n in fieldnames], dialect=dialect, **kwds)

		def _enc(self, v):
			if isinstance(v, unicode):  # noqa: F821 -- esiste solo su Python 2
				return v.encode(self.encoding)
			return v

		def writeheader(self):
			self.writer.writeheader()

		def writerow(self, d):
			self.writer.writerow(
				dict((self._enc(k), self._enc(v)) for k, v in d.items()))

		def writerows(self, rows):
			for d in rows:
				self.writerow(d)

else:

	class UnicodeDictReader(csv.DictReader):
		"""`csv.DictReader`; l'encoding lo gestisce il file, vedi `csv_open`."""

		def __init__(self, f, encoding=None, fieldnames=None, **kwds):
			csv.DictReader.__init__(self, f, fieldnames=fieldnames, **kwds)

	class _DictWriter(csv.DictWriter):
		"""`csv.DictWriter`; l'encoding lo gestisce il file, vedi `csv_open`."""

		def __init__(self, f, fieldnames, dialect=csv.excel, encoding=None, **kwds):
			csv.DictWriter.__init__(self, f, fieldnames, dialect=dialect, **kwds)


# Uguale sulle due versioni: la differenza sta tutta in `_DictWriter`.
class UnicodeLazyDictWriter(object):
	"""
	DictWriter che deduce i nomi delle colonne dalla prima riga scritta.

	Serve a chi produce un CSV senza conoscere in anticipo i campi. L'ordine
	delle colonne e' quello di `list(row)`: si veda la nota in cima al modulo.
	"""

	def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
		self.f = f
		self.dialect = dialect
		self.encoding = encoding
		self.kwds = kwds
		self.writer = None
		self.fields = None

	def writerow(self, row):
		if self.writer is None:
			self.fields = list(row)
			self.writer = _DictWriter(
				self.f, self.fields, dialect=self.dialect,
				encoding=self.encoding, **self.kwds)
			self.writer.writeheader()
		self.writer.writerow(row)

	def writerows(self, rows):
		for d in rows:
			self.writerow(d)
