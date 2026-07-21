# coding: utf-8

#
#    Copyright 2021 Skeed by Luca Allulli
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

from __future__ import print_function
from paline.models import *
from django.template.response import TemplateResponse

# Il feed GTFS di Roma servizi per la mobilita' non valorizza piu' route_long_name
# (e' vuoto per tutte le linee), quindi Percorso.descrizione arriva a None e senza
# fallback la pagina mostrerebbe "None" al posto del nome della linea.
MISSING_DESCRIPTIONS = {
	'MEA': 'Metro A',
	'MEB': 'Metro B',
	'MEB1': 'Metro B1',
	'MEC': 'Metro C',
	'RL': 'Roma-Lido',
	'RMG': 'Roma-Centocelle',
	'RMVT': 'Roma-Civita Castellana-Viterbo'
}


def linee_da_percorsi(percorsi):
	"""
	Raggruppa i percorsi per linea, dandole una descrizione presentabile.

	La descrizione della linea e' quella del percorso; se manca si ripiega sulla
	tabella qui sopra e, in ultimo, sull'id della linea. Cosi' l'ordinamento ha
	sempre stringhe da confrontare (su Python 3 un None qui sarebbe un TypeError).
	"""
	linee = set()
	for p in percorsi:
		l = p.linea
		d = p.descrizione
		if d is None:
			d = MISSING_DESCRIPTIONS.get(l.id_linea, l.id_linea)
		l.descrizione = d
		if hasattr(p, 'alerts'):
			l.alerts = p.alerts
		linee.add(l)
	return sorted(linee, key=lambda l: l.descrizione)


def default(request):
	ps_metro = list(
		Percorso.objects.by_date().filter(linea__tipo='ME', soppresso=False).select_related('linea')
	)
	ps_fc = list(
		Percorso.objects.by_date().filter(linea__tipo='FC', soppresso=False).select_related('linea')
	)
	enhance_routes_with_stats(ps_metro)
	enhance_routes_with_stats(ps_fc)
	ctx = {
		'linee_metro': linee_da_percorsi(ps_metro),
		'linee_fc': linee_da_percorsi(ps_fc),
	}
	return TemplateResponse(request, 'metro.html', ctx)
