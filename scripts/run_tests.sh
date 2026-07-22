#!/bin/sh
#
# Rete di sicurezza della migrazione (Fase 0 della roadmap): esegue tutti i
# controlli e restituisce un solo exit code.
#
#   scripts/run_tests.sh              tutti i controlli
#   scripts/run_tests.sh smoke        solo lo smoke test HTTP
#   scripts/run_tests.sh imports      solo la verifica degli import
#   scripts/run_tests.sh rpc-dump     rifotografa il contratto RPC
#   scripts/run_tests.sh rpc-compare  lo riconfronta con il riferimento
#
# Va eseguito dalla radice del repo, sull'host dove gira lo stack: i controlli
# parlano con i container veri, non con un ambiente finto.
#
# E' /bin/sh e non un Makefile perche' sull'host di produzione `make` non c'e'
# -- e installarlo per lanciare tre docker run sarebbe sproporzionato. Il
# Makefile in radice esiste comunque e delega qui, per chi ha make sottomano.
#
# Variabili sovrascrivibili:
#   IMAGE=romamobile:test scripts/run_tests.sh     prova un'immagine appena costruita
#   BASE=http://127.0.0.1:8000 scripts/run_tests.sh

set -eu

IMAGE="${IMAGE:-romamobile:latest}"
NETWORK="${NETWORK:-romamobile_default}"
BASE="${BASE:-http://web:8000}"
# Il riferimento del contratto RPC vive sull'host: i controlli girano in
# container usa-e-getta, quindi un file scritto dentro sparirebbe con loro.
REF_DIR="${REF_DIR:-/tmp/romamobile-tests}"
RPC_REF=/ref/rpc-contract.json

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$REPO/secrets/settings.json" ]; then
	echo "errore: non trovo $REPO/secrets/settings.json" >&2
	echo "        va eseguito sull'host di deploy, dalla radice del repo" >&2
	exit 2
fi

mkdir -p "$REF_DIR"

# `src` e' montato in scrittura di proposito: il LOGGING di Django apre
# /app/atacmobile.log in append, e con /app in sola lettura ogni controllo
# fallisce all'avvio. E' lo stesso montaggio che usano i container in servizio.
run() {
	docker run --rm --network "$NETWORK" \
		-v "$REPO/src:/app" \
		-v "$REPO/scripts:/scripts:ro" \
		-v "$REPO/secrets/settings.json:/app/secrets/settings.json:ro" \
		-v "$REF_DIR:/ref" \
		-w /app -e APP_PATH=/app "$IMAGE" "$@"
}

imports() {
	echo "== import di tutti i moduli del backend"
	# L'output e' lungo una riga per modulo: interessa il riepilogo, ma se
	# fallisce va mostrato tutto, altrimenti non si sa *quale* modulo.
	out="$(mktemp)"
	if run python /scripts/check_imports.py > "$out" 2>&1; then
		tail -1 "$out"
		rm -f "$out"
	else
		cat "$out"
		rm -f "$out"
		return 1
	fi
}

smoke() {
	echo "== smoke test HTTP su $BASE"
	run python /scripts/smoke_test.py --base "$BASE"
}

rpc_dump() {
	echo "== nuovo riferimento del contratto RPC"
	run python /scripts/check_rpc_contract.py --dump "$RPC_REF"
}

rpc_compare() {
	echo "== contratto RPC web <-> giano"
	# Se il riferimento non c'e' ancora lo si crea, invece di fallire: al primo
	# giro non esiste un "prima" con cui confrontarsi.
	if [ -f "$REF_DIR/rpc-contract.json" ]; then
		run python /scripts/check_rpc_contract.py --compare "$RPC_REF"
	else
		echo "   nessun riferimento in $REF_DIR: lo creo adesso"
		run python /scripts/check_rpc_contract.py --dump "$RPC_REF"
	fi
}

case "${1:-all}" in
	all)
		# L'ordine non e' casuale: prima che i moduli si importino, poi che il
		# sito risponda, poi che il contratto RPC regga. Un fallimento in cima
		# rende poco informativi quelli sotto, e `set -e` ferma al primo.
		imports
		echo ""
		smoke
		echo ""
		rpc_compare
		echo ""
		echo "== tutti i controlli passati"
		;;
	imports)     imports ;;
	smoke)       smoke ;;
	rpc-dump)    rpc_dump ;;
	rpc-compare) rpc_compare ;;
	*)
		echo "uso: $0 [all|imports|smoke|rpc-dump|rpc-compare]" >&2
		exit 2
		;;
esac
