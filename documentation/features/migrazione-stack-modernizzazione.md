# Roadmap: modernizzazione dello stack (uscita da Python 2.7 / Django 1.5)

**Stato:** proposta / in corso
**Obiettivo primario:** uscire dallo stack EOL (Python 2.7 + Django 1.5) riducendo al minimo
il rischio di regressioni, mantenendo il sistema sempre rilasciabile.
**Non obiettivo:** riscrittura big-bang in un altro linguaggio (es. Go). Vedi
[Perché non un rewrite in Go](#perché-non-un-rewrite-in-go).

---

## 1. Contesto e principi

Roma mobile è un sistema Django legacy (~46k righe Python + ~2,2k righe Cython +
un frontend pyjs + 71 template) fortemente accoppiato. Il pezzo genuinamente
CPU-bound (grafo di routing, geocoder) è già compilato in **Cython → C**; il resto
(web, admin, CRUD, RPC) è I/O-bound.

Poiché il driver è la **manutenibilità / fine supporto**, la strada a minor rischio è
modernizzare *lo stack*, non cambiare *linguaggio*:

- Cambi **linguaggio** per un problema di *performance / concorrenza*.
- Cambi **versione** per un problema di *EOL*. → il nostro caso.

### Principi guida

1. **Incrementale e sempre rilasciabile.** Ogni fase termina con un sistema
   funzionante e deployabile. Niente rami di rewrite che divergono per mesi.
2. **Test prima di toccare.** Non si può migrare in sicurezza ciò che non si può
   verificare. Prima creiamo una rete di sicurezza (smoke test + test sui percorsi
   critici), poi migriamo.
3. **Un cambiamento per volta.** Prima Python 2→3 *senza* toccare Django; poi Django
   un major alla volta; poi il frontend. Mai due migrazioni contemporanee.
4. **Strangler Fig per eventuali riscritture.** Se e quando un componente andrà
   riscritto (es. il core routing), lo si isola dietro il contratto RPC esistente e
   lo si sostituisce a caldo, senza toccare il resto.

---

## 2. Stato attuale (inventario)

### Servizi runtime (docker-compose)

| Servizio | Ruolo | Perf-critical |
|---|---|---|
| `postgis` | PostgreSQL/PostGIS | — |
| `web` | Django 1.5 + gunicorn (view, template, admin, ORM, XML/JSON-RPC) | No (I/O-bound) |
| `giano` | Daemon RPyC: grafo routing, geocoder, rete in RAM, GTFS-RT, veicoli | **Sì** |

### Frontend

`src/percorso/js/` (~10k righe): **Python compilato in JavaScript con pyjs/pyjamas**,
tecnologia morta da oltre un decennio. È probabilmente il maggior rischio EOL del
progetto e va trattato come progetto indipendente dal backend.

### "Landmine" Python 2 → 3 (misurate)

| Pattern | Occorrenze | Difficoltà |
|---|---|---|
| `print "..."` statement | 33 file | Banale |
| `django.conf.urls.defaults` / `patterns()` (rimosso) | 32 file | Meccanico |
| `cPickle` / `Queue` / `xrange` / `iteritems` / `has_key` | 22 file | Meccanico |
| `unicode()` / `basestring` / `cmp=` | ~40 punti | Medio (str/bytes) |
| `.pyx` Cython (grafo, geocoder) | 6 file | Ricompilazione + fix minori |

### Dipendenze morte / da sostituire

| Attuale | Sostituto |
|---|---|
| `BeautifulSoup==3.2.1` | `beautifulsoup4` |
| `pycrypto==2.6.1` (morto, CVE noti) | `pycryptodome` |
| `Cython==0.23.4` | Cython moderno |
| `pyproj==1.9.5.1` | `pyproj` 3.x (API cambiata) |
| `rpyc==3.3.0` | RPyC attuale |
| `django-json-rpc`, `django-constance`, `gtfs-realtime-bindings==0.0.6` | versioni correnti |
| `Django==1.5.12` | Django LTS |

---

## 3. Fasi

### Fase 0 — Rete di sicurezza (prerequisito)

**Perché:** non esiste (ancora) una suite di test; migrare senza verifica è cieco.

- [ ] Inventario degli endpoint/servizi critici da non rompere: `/metro`, ricerca
      linee, dettaglio palina, cerca percorso, arrivi in tempo reale, news.
- [ ] Smoke test end-to-end (anche solo HTTP status + presenza contenuti chiave) sui
      percorsi critici, eseguibili in Docker.
- [ ] Test di caratterizzazione sul contratto RPC `web` ↔ `giano` (input/output dei
      metodi `exposed_*` più usati: `route_stats`, `tempi_attesa`, `cerca_percorso`).
- [ ] Fissare i dati/fixtures minimi per far girare i test in modo riproducibile.

**Exit criteria:** una `make test` (o equivalente) che gira in CI/Docker e passa sullo
stack attuale (Py2/Django1.5).

### Fase 1 — Fondamenta Python 3 (compatibilità Py2/3)

**Strategia:** rendere il codice eseguibile su **entrambi** Py2 e Py3 (via `six`/
`future`), così da poter migrare a piccoli passi restando sempre rilasciabili su Py2.

- [ ] Sostituire le dipendenze morte con equivalenti Py3-compatibili (tabella sopra).
- [ ] Automatizzare le trasformazioni meccaniche (`futurize`/`2to3` mirati):
  - [x] `print` statement → `print()` funzione + `from __future__ import print_function`
        (40 file backend; frontend `percorso/js/` escluso, è Fase 3).
  - [ ] `iteritems` / `itervalues` / `has_key` / `xrange`
  - [ ] `except X, e:` → `except X as e:`
- [ ] Normalizzare `cPickle`→`pickle` (via `six.moves`), `Queue`→`queue`.
- [ ] Affrontare a mano i punti str/bytes/`unicode` e i `cmp=` (→ `key=`).
- [ ] Ricompilare le estensioni `.pyx` con Cython moderno; correggere le differenze
      di tipizzazione emerse.
- [ ] Aggiornare `requirements.txt` e il `Dockerfile` (immagine base Py3).

**Exit criteria:** l'intero stack parte e passa i test di Fase 0 **su Python 3**,
ancora con Django 1.5 (via layer di compatibilità dove necessario).

### Fase 2 — Upgrade Django 1.5 → LTS

**Strategia:** un major (o due) alla volta, guidati dalle note di deprecazione
ufficiali e dai test. Mai saltare direttamente all'ultima.

- [ ] `django.conf.urls.defaults` / `patterns()` → nuovo stile `urlpatterns`.
- [ ] Middleware: `MIDDLEWARE_CLASSES` → `MIDDLEWARE`.
- [ ] Template engine e tag/filter deprecati.
- [ ] `syncdb` → sistema di **migrations**.
- [ ] Cambiamenti ORM (manager, `get_query_set`→`get_queryset`, ecc.).
- [ ] Adeguare app di terze parti (constance, redis, captcha, json-rpc) alle versioni
      compatibili con la Django target.

**Exit criteria:** stack su Python 3 + Django LTS, test verdi, deploy verificato.

### Fase 3 — Modernizzazione frontend (indipendente)

- [ ] Congelare il comportamento attuale dell'app pyjs (screenshot/test funzionali).
- [ ] Reimplementare progressivamente in **JS/TS** moderno, schermata per schermata,
      consumando gli stessi endpoint del backend.
- [ ] Dismettere la toolchain pyjs/pyjamas e `dep/pyjs`.

**Nota:** ortogonale a Fase 1–2; può procedere in parallelo.

### Fase 4 — (Eventuale) estrazione del core routing

**Solo se** un profiling dimostra che `giano` è il collo di bottiglia reale.

- [ ] Profilare `giano` (Dijkstra vs geocoding vs serializzazione RPyC vs query DB).
- [ ] Se giustificato, estrarre il solo core routing come servizio dedicato (anche in
      Go) **dietro lo stesso contratto RPC**, in Strangler Fig.

**Nota:** non è un obiettivo dell'uscita da EOL; resta opzionale e data-driven.

---

## 4. Perché non un rewrite in Go

- Il pezzo lento è **già compilato** (Cython→C): Go non lo batterebbe di molto.
- Riscrivere il web I/O-bound in Go butta via Django admin, ORM, migrations, form,
  i18n e template per riottenere le stesse pagine alla stessa velocità.
- Il frontend è codice browser: Go non lo tocca.
- Un big-bang costringe a mantenere **due sistemi in parallelo** per anni con
  ri-sincronizzazione continua della logica — il modo classico in cui questi progetti
  falliscono a metà.

Go resta un'opzione valida come **bisturi** per il solo core routing (Fase 4), non
come martello per l'intero sistema.

---

## 5. Registro dei rischi

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Nessuna suite di test iniziale | Alto | Fase 0 prima di ogni modifica |
| str/bytes silenziosi (pickle, RPyC, I/O) | Alto | Test sul contratto RPC; passaggio esplicito bytes |
| Estensioni Cython non ricompilano | Medio | Isolare in Fase 1, fallback documentato |
| App di terze parti senza versione compatibile | Medio | Valutare sostituti in Fase 0; elenco alternative |
| Deploy: `giano` va riavviato per ricaricare la rete | Basso | Documentato nel runbook di deploy |

---

## 6. Ordine di esecuzione consigliato

```
Fase 0 (test)  →  Fase 1 (Py3)  →  Fase 2 (Django LTS)
                        └── Fase 3 (frontend) in parallelo
                                             └── Fase 4 (routing) opzionale, data-driven
```

---

## 7. Diario di avanzamento

Log cronologico di ogni batch di modifiche. Ogni voce è un commit isolato e
reversibile. La validazione runtime (avvio stack Docker su Py2 attuale + smoke
test manuali) è a carico dell'ambiente di deploy dopo ogni batch.

### 2026-07-21

- **Bugfix pre-migrazione** — `500` su `/metro` e ricerca linee quando gli alert
  GTFS non sono disponibili (`gtfs_alerts is None`). Guardia in
  `paline/trovalinea.py` + `try/except` su `read_alerts()` in `paline/tpl.py`.
  _(commit separato, non parte della migrazione ma sbloccante.)_
- **Fase 1 · batch 1 — `print` statement → funzione.** Convertiti tutti i `print`
  del backend a `print(...)` con `from __future__ import print_function` per
  restare compatibili Py2 **e** Py3. 40 file toccati. Escluso il frontend
  `percorso/js/` (pyjs, Fase 3) e il generato `gtfs_pb2.py`.
  - Note: corretto un BOM UTF-8 in `mercury/management/commands/jobs.py` e
    `run_job.py` che confondeva il posizionamento del future-import.
  - Verifica: `lib2to3 -f print` sull'intero backend non segnala più alcuno
    statement da convertire né ParseError.
  - ⚠️ Da validare nel deploy: riavvio `giano` + smoke test su `/metro`,
    ricerca linee, cerca percorso.
