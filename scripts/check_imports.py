# coding: utf-8
"""
Importa ogni modulo del backend e riporta i fallimenti.

Rete di sicurezza per la migrazione Python 2 -> 3 (vedi
documentation/features/migrazione-stack-modernizzazione.md): `compileall` verifica
solo la sintassi, non che gli import risolvano davvero. Questo script carica ogni
modulo con i settings Django configurati, cosi' un import relativo implicito rotto
(o una dipendenza mancante) emerge subito invece che al primo hit di produzione.

Uso, dentro un container con lo stack installato:

    python scripts/check_imports.py            # tutto il backend
    python scripts/check_imports.py paline     # solo un package

Exit code 0 se tutti i moduli si importano, 1 altrimenti.
"""

from __future__ import print_function

import os
import sys
import traceback

# I sorgenti stanno in src/; lo script vive in scripts/, ma dentro l'immagine
# Docker src/ e' montato direttamente su /app.
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/app' if os.path.isdir('/app/paline') else os.path.join(os.path.dirname(HERE), 'src')

# Directory da non attraversare: frontend pyjs (Fase 3, non e' Python eseguibile
# lato server), build artefatti, migrazioni sud e dati.
SKIP_DIRS = set([
	'js', 'output', 'migrations', 'rete', 'static', 'admin_media',
	'templates', 'locale', 'fixtures', '.git',
])

# Moduli che all'import fanno lavoro pesante o hanno side effect indesiderati.
SKIP_MODULES = set([
	'manage',  # esegue execute_from_command_line
	'wsgi',    # istanzia l'applicazione
])


def module_names():
	for dirpath, dirnames, filenames in os.walk(SRC):
		dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
		rel = os.path.relpath(dirpath, SRC)
		if rel == '.':
			prefix = ''
		else:
			# Una directory e' importabile solo se e' un package
			if not os.path.exists(os.path.join(dirpath, '__init__.py')):
				continue
			prefix = rel.replace(os.sep, '.') + '.'
		for f in sorted(filenames):
			if not f.endswith('.py'):
				continue
			name = prefix + (f[:-3] if f != '__init__.py' else '')
			name = name.rstrip('.')
			if name and name not in SKIP_MODULES:
				yield name


def import_isolated(name):
	"""
	Importa `name` in un processo figlio e ritorna True se ci riesce.

	L'isolamento non e' un vezzo: importare tutto nello stesso interprete produce
	falsi positivi (per esempio paline.gtfs_pb2 e google.transit.gtfs_realtime_pb2
	registrano lo stesso .proto nel descriptor pool e la seconda import esplode).
	Il fork parte da un processo che ha gia' caricato Django, quindi costa poco.
	"""
	pid = os.fork()
	if pid == 0:
		try:
			__import__(name)
		except Exception:
			traceback.print_exc()
			os._exit(1)
		os._exit(0)
	_, status = os.waitpid(pid, 0)
	return status == 0


def main(argv):
	os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
	sys.path.insert(0, SRC)

	# Carica i settings una volta sola nel padre: i figli li ereditano.
	__import__(os.environ['DJANGO_SETTINGS_MODULE'])

	only = argv[1] if len(argv) > 1 else None
	failures = []
	checked = 0

	for name in module_names():
		if only and not (name == only or name.startswith(only + '.')):
			continue
		checked += 1
		sys.stdout.flush()
		if import_isolated(name):
			print('ok   %s' % name)
		else:
			failures.append(name)
			print('FAIL %s' % name)

	print('')
	print('%d moduli importati, %d falliti' % (checked, len(failures)))
	for name in failures:
		print('FAIL %s' % name)
	return 1 if failures else 0


if __name__ == '__main__':
	sys.exit(main(sys.argv))
