#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test di caratterizzazione sul parsing dei feed GTFS-realtime.

Serve a validare l'aggiornamento di `protobuf` e `gtfs-realtime-bindings`.
Il parsing e' l'unica parte viva della catena GTFS-RT (veicoli e alert), ed e'
alimentata da byte che arrivano dalla rete: se le due versioni interpretassero
lo stesso payload in modo diverso, il sintomo sarebbe dati sbagliati in pagina,
non un errore.

Il feed cambia di minuto in minuto, quindi confrontare due esecuzioni live non
direbbe nulla: si scaricano i byte **una volta sola** (`--fetch`), poi li si fa
interpretare alle due versioni (`--dump` / `--compare`) partendo dallo stesso
identico payload.

    python scripts/check_gtfs_rt_equivalence.py --fetch /tmp/feeds       # una volta
    python scripts/check_gtfs_rt_equivalence.py --dump /tmp/a.json --feeds /tmp/feeds
    python scripts/check_gtfs_rt_equivalence.py --compare /tmp/a.json --feeds /tmp/feeds
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys


VEHICLES = 'vehicles.pb'
ALERTS = 'alerts.pb'

# Deve restare allineato a paline/gtfs/realtime.py.
NO_DATA_AVAILABLE = 7


def fetch(dest):
	import requests
	os.path.isdir(dest) or os.makedirs(dest)
	# Le stesse URL di settings.py, ripetute per non dover caricare Django.
	urls = {
		VEHICLES: 'https://romamobilita.it/sites/default/files/rome_rtgtfs_vehicle_positions_feed.pb',
		ALERTS: 'https://romamobilita.it/sites/default/files/rome_rtgtfs_service_alerts_feed.pb',
	}
	for name, url in urls.items():
		# allow_redirects: romamobilita.it 301-redirige le vecchie URL da quando
		# e' passato a WordPress (vedi il fix in gtfs/realtime.py).
		content = requests.get(url, verify=False, allow_redirects=True).content
		with open(os.path.join(dest, name), 'wb') as f:
			f.write(content)
		print("%s: %d byte, sha1 %s"
		      % (name, len(content), hashlib.sha1(content).hexdigest()))


def summarize(feeds):
	"""Riassunto strutturale del feed: quello che il codice a valle legge davvero."""
	from google.transit import gtfs_realtime_pb2
	import google.protobuf

	out = {'protobuf_version': google.protobuf.__version__}

	with open(os.path.join(feeds, VEHICLES), 'rb') as f:
		fm = gtfs_realtime_pb2.FeedMessage()
		fm.ParseFromString(f.read())
	veicoli = []
	for e in fm.entity:
		v = e.vehicle
		veicoli.append({
			'id': e.id,
			'trip_id': v.trip.trip_id,
			'route_id': v.trip.route_id,
			'lat': round(v.position.latitude, 6),
			'lon': round(v.position.longitude, 6),
			'stop_id': v.stop_id,
			'timestamp': v.timestamp,
			# Due letture distinte, e la distinzione e' il punto del test:
			#
			#  - `occupancy_raw` e' cio' che la libreria consegna. Cambia fra le
			#    versioni, perche' le bindings 0.0.7 riconoscono un valore di
			#    enum che le 0.0.6 scartavano: e' informativo, ed escluso dal
			#    confronto.
			#  - `occupancy` e' cio' che l'applicazione ne ricava, con la stessa
			#    regola di `_occupancy()` in paline/gtfs/realtime.py. E' questo
			#    che deve restare identico: un aggiornamento di dipendenza non
			#    deve cambiare cosa vede l'utente.
			'occupancy_raw': v.occupancy_status if v.HasField('occupancy_status') else None,
			'occupancy': (None
			              if (not v.occupancy_status or v.occupancy_status == NO_DATA_AVAILABLE)
			              else int(v.occupancy_status)),
		})
	out['header_vehicles'] = {
		'version': fm.header.gtfs_realtime_version,
		'timestamp': fm.header.timestamp,
	}
	out['vehicles'] = sorted(veicoli, key=lambda x: x['id'])

	with open(os.path.join(feeds, ALERTS), 'rb') as f:
		fa = gtfs_realtime_pb2.FeedMessage()
		fa.ParseFromString(f.read())
	alerts = []
	for e in fa.entity:
		a = e.alert
		alerts.append({
			'id': e.id,
			'cause': a.cause,
			'effect': a.effect,
			'header': [t.text for t in a.header_text.translation],
			'description': [t.text for t in a.description_text.translation],
			'informed': [(s.route_id, s.stop_id) for s in a.informed_entity],
		})
	out['alerts'] = sorted(alerts, key=lambda x: x['id'])
	return out


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--fetch", metavar="DIR")
	ap.add_argument("--feeds", metavar="DIR", default="/tmp/feeds")
	ap.add_argument("--dump", metavar="FILE")
	ap.add_argument("--compare", metavar="FILE")
	args = ap.parse_args()

	if args.fetch:
		fetch(args.fetch)
		return 0

	data = summarize(args.feeds)
	print("protobuf %s: %d veicoli, %d alert"
	      % (data['protobuf_version'], len(data['vehicles']), len(data['alerts'])))

	if args.dump:
		with open(args.dump, "w") as f:
			json.dump(data, f, indent=1, sort_keys=True)
		print("scritto %s" % args.dump)
		return 0

	if not args.compare:
		ap.error("serve --fetch, --dump o --compare")

	with open(args.compare) as f:
		ref = json.load(f)
	print("riferimento: protobuf %s, %d veicoli, %d alert"
	      % (ref['protobuf_version'], len(ref['vehicles']), len(ref['alerts'])))

	# Confronto sul contenuto interpretato, non sui byte: e' cio' che il resto
	# dell'applicazione consuma.
	def comparabile(d):
		d = {k: v for k, v in d.items() if k != 'protobuf_version'}
		# `occupancy_raw` e' informativo: cambia per costruzione fra le due
		# versioni delle bindings, ed e' proprio la differenza che il codice
		# applicativo deve assorbire.
		d['vehicles'] = [{k: v for k, v in x.items() if k != 'occupancy_raw'}
		                 for x in d['vehicles']]
		return json.dumps(d, sort_keys=True)

	a = comparabile(ref)
	b = comparabile(data)
	if a == b:
		print("ESITO: IDENTICI (%d byte di riassunto confrontati)" % len(a))
		return 0

	print("ESITO: DIFFERENZE")
	for key in ('header_vehicles', 'vehicles', 'alerts'):
		if json.dumps(ref.get(key), sort_keys=True) != json.dumps(data.get(key), sort_keys=True):
			print("  differisce: %s" % key)
	return 1


if __name__ == "__main__":
	sys.exit(main())
