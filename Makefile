# Sottile involucro su scripts/run_tests.sh, che e' l'implementazione vera.
#
#   make test         tutti i controlli della Fase 0, un solo exit code
#   make smoke        solo lo smoke test HTTP
#   make imports      solo la verifica degli import
#   make rpc-dump     rifotografa il contratto RPC (nuovo riferimento)
#   make rpc-compare  lo riconfronta con il riferimento
#
# La logica sta nello script e non qui perche' sull'host di produzione `make`
# non e' installato: lo script funziona comunque, questo file e' solo comodita'
# per chi ha make sottomano. Le variabili si passano come sempre:
#
#   make test IMAGE=romamobile:test

.PHONY: test smoke imports rpc-dump rpc-compare

test:
	@scripts/run_tests.sh all

smoke:
	@scripts/run_tests.sh smoke

imports:
	@scripts/run_tests.sh imports

rpc-dump:
	@scripts/run_tests.sh rpc-dump

rpc-compare:
	@scripts/run_tests.sh rpc-compare
