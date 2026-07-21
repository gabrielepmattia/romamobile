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

| Pattern | Occorrenze | Difficoltà | Stato |
|---|---|---|---|
| `print "..."` statement | 33 file | Banale | ✅ batch 1 |
| `except X, e:` / `raise X, msg` | 48 punti | Banale | ✅ batch 2 |
| `cPickle` / `Queue` / `xrange` / `iteritems` / `has_key` | 22 file | Meccanico | ✅ batch 2 |
| `django.conf.urls.defaults` / `patterns()` (rimosso) | 32 file | Meccanico | Fase 2 |
| `unicode()` / `basestring` / `cmp=` | ~40 punti | Medio (str/bytes) | da fare |
| import relativi impliciti (`from models import *`) | diffusi | Medio | da fare |
| `.pyx` Cython (grafo, geocoder) | 6 file | Ricompilazione + fix minori | da fare |

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
  - [x] `iteritems` / `iterkeys` / `has_key` / `xrange`
  - [x] `except X, e:` → `except X as e:`
  - [x] `raise X, msg` → `raise X(msg)`
  - [x] literal `long` (`123L`) e `TabError` (mix tab/spazi)
- [x] Normalizzare `cPickle`→`pickle`, `Queue`→`queue` (via `try/except ImportError`,
      senza introdurre dipendenze nuove: nessun rebuild immagine richiesto).
- [x] Import relativi impliciti → espliciti (`import views` → `from . import views`)
      nei `.py` dei package applicativi. Restano da fare i `.pyx` (insieme alla
      ricompilazione Cython) e i moduli top-level di `src/`, che sono caricati come
      top-level e quindi devono restare assoluti.
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
| Toccare un `.pyx` allunga il restart (ricompilazione `pyximport`): ~30 s di 500 sugli endpoint RPC | Basso | Atteso e documentato; verificare dopo la finestra, non durante |

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
  - ✅ Validato in deploy (`hetzner-4gb-1`, 2026-07-21): vedi sotto.
- **Fase 1 · batch 2 — sintassi Py2/Py3 comune.** Trasformazioni meccaniche, tutte
  valide **sia** su Py2.7 **sia** su Py3. 38 file toccati (frontend `percorso/js/`
  sempre escluso):
  - `except X, e:` → `except X as e:` — 30 punti in 18 file.
  - `raise X, msg` → `raise X(msg)` — 18 punti nei due `dbf.py`.
  - `.has_key(k)` → `k in d` (3 punti), `.iteritems()` → `list(.items())`,
    `.iterkeys().next()` → `next(iter(...))`.
  - `xrange` in `paline/osm.py`: shim locale `xrange = range` sotto `except
    NameError`, per non perdere la lazyness su Py2 in `load_graph`.
  - `import cPickle as pickle` → `try/except ImportError` (19 file, inclusi
    `grafo.pyx` e `geocoder.pyx`); idem per `Queue`/`queue` (5 file). Niente `six`:
    evita di toccare `requirements.txt` e quindi il rebuild dell'immagine.
  - Rimosso un doppio `import pickle` ridondante in `carpooling/models.py`.
  - `13800207392955L` → senza suffisso `L` (`paline/tomtom.py`) e `TabError`
    (mix tab/spazi) nei due `binnum.py`.
  - **Verifica:** `python -m compileall` sull'intero backend passa pulito in Docker
    **sia** con `python:2.7-slim` **sia** con `python:3.11-slim`. Il backend non ha
    più errori di *sintassi* Py3 (restano quelli semantici: `unicode`, str/bytes,
    import impliciti, Django 1.5).
  - ✅ Validato in deploy (`hetzner-4gb-1`, 2026-07-21): vedi sotto.

- **Bugfix — `/metro` mostrava `None` al posto dei nomi delle linee.** Il feed GTFS
  non valorizza più `route_long_name` (è vuoto per **tutte** le route), quindi
  `Percorso.descrizione` è `NULL`: in produzione 8/8 metro, 17/17 tram, 970/1113 bus.
  Il fallback che esisteva già per le ferrovie concesse è stato fattorizzato in
  `linee_da_percorsi()` e ora copre anche le metro (`MEA` → "Metro A", …).
  Effetto collaterale utile: la chiave di ordinamento non è più `None`, che su
  Python 3 sarebbe un `TypeError`.
  - Il feed ha anche perso del tutto le `route_type=2`: non esiste più nessuna
    ferrovia concessa, quindi la sezione viene nascosta se vuota invece di mostrare
    un titolo spoglio. _(commit separato, non parte della migrazione.)_
- **Fase 0 · primo mattone — `scripts/check_imports.py`.** Importa ogni modulo del
  backend con i settings Django caricati: è l'unico modo di intercettare un import
  rotto, che `compileall` non vede. Ogni modulo viene importato in un **fork**
  dedicato, altrimenti si ottengono falsi positivi (`paline.gtfs_pb2` e
  `google.transit.gtfs_realtime_pb2` registrano lo stesso `.proto` nel descriptor
  pool e la seconda import esplode). Va eseguito con `/app` **scrivibile**: il
  `LOGGING` di Django apre `/app/atacmobile.log` in append.
- **Fase 1 · batch 3 — import relativi impliciti → espliciti.** 116 righe in 75 file:
  `import views` → `from . import views` (33), `from models import *` →
  `from .models import *` (29), più i moduli interni di `paline` (`grafo`, `tratto`,
  `geomath`, `tomtom`, …). Su Py2 la forma esplicita è supportata da 2.6, quindi il
  comportamento non cambia; su Py3 è l'unica che funziona.
  - **Esclusi di proposito:** i moduli top-level di `src/` (`urls`, `settings`,
    `xmlrpchandler`, …). Sono caricati *come* top-level (`DJANGO_SETTINGS_MODULE`,
    `ROOT_URLCONF`), quindi un `from . import` li romperebbe: per loro l'import
    assoluto è già corretto anche su Py3.
  - **Restano da fare i `.pyx`** (`grafo.pyx: import tratto`, `geocoder.pyx: from
    tomtom import …`, `bt/*.pyx: from cwalker import …`): vanno insieme alla
    ricompilazione con Cython moderno, dove il `language_level` cambia la semantica
    degli import.
  - Attenzione a un caso che ha morso: in `dbf.py` l'import era dentro uno statement
    composto su una riga (`try: import binnum`), e una riscrittura riga-per-riga
    ingenua cancella il `try:`.
  - **Verifica:** `compileall` pulito su Py2.7 e Py3.11; ogni import relativo risolve
    a un file esistente (127 controllati); `check_imports.py` nel container di
    produzione dà **201 moduli, 4 falliti** — *identici* ai 4 della baseline
    (`paline.carpoolinggraph`, `paline.osm`, `paline.raggiungibilita`,
    `paline.management.commands.romatpl_decoder`, tutti già rotti prima e da
    guardare a parte).

### Validazione deploy 2026-07-21 (`hetzner-4gb-1`)

- Ambiente: `~/apps/_romamobile/repo/romamobile`, stack compose `romamobile`
  (`postgis` + `web` + `giano`), reverse proxy Traefik su `rm.gpm.name`.
- Il server era fermo a `6ce20d5`, quindi **senza** il fix degli alert GTFS: `/metro`
  rispondeva **500**. Confermato prima dell'aggiornamento.
- `git merge --ff-only origin/master` → `d5200f0`. Il codice è montato via bind
  (`./src:/app`), perciò non serve rebuild: basta riavviare `giano` e `web`.
- Dopo `docker restart romamobile-giano-1 romamobile-web-1`, smoke test su
  `127.0.0.1:8000` (dietro Traefik):

  | Endpoint | Prima (`6ce20d5`) | Dopo batch 1 | Dopo batch 2 |
  |---|---|---|---|
  | `/` | 200 | 200 | 200 (7426 b) |
  | `/metro` | **500** | 200 | 200 (5329 b) |
  | `/paline/linea/64` | **500** | 200 | 200 (4659 b) |
  | `/paline/percorso/RM173` | — | 200 | 200 (10925 b) |
  | `/paline/palina/73992` (RPC → `giano`) | — | 200 | 200 (5370 b) |
  | `/paline/elenco_linee` | — | 200 | 200 (215721 b) |
  | `/news/`, `/percorso/` | 200 | 200 | 200 |

  Le dimensioni delle risposte sono **identiche** tra batch 1 e batch 2: nessuna
  differenza di contenuto renderizzato. Il dettaglio palina mostra il riquadro
  previsioni ("Nessun autobus" fuori orario di servizio), quindi la catena
  `web` → RPyC → `giano` è integra.

- **Batch 3 + fix `/metro`** (`9ccf579`, `3bdb1d9`): dopo `git pull` + restart, tutti
  gli endpoint sopra restano **200** con le stesse dimensioni di risposta, e si
  aggiungono `/paline/linea/MEA`, `/meteo/`, `/parcheggi/`, `/ztl/`, `/lingua/`,
  `/percorso/js/` → 200. `/metro` rende "Metro A / Metro B / Metro B1 / Metro C".
  Nei log del `web` nessun `ImportError`: gli unici due 500 sono quelli della finestra
  di riavvio descritta sotto.
- **Preesistente, non toccato:** `/info/...` risponde 404 perché l'app `info` non è in
  `settings.XHTML_APPS` e quindi non è instradata — ma il banner dei cookie punta a
  `/info/info-cookies`. Da decidere a parte se instradare l'app o correggere il link.

**Nota operativa (da tenere nel runbook di deploy):** quando un batch tocca un
`.pyx`, `pyximport` invalida la cache in `~/.pyxbld` e **ricompila a runtime** al
riavvio di `giano`. Per ~30 s dopo il restart tutti gli endpoint che passano dall'RPC
rispondono **500** (`AttributeError: 'NoneType' object has no attribute 'root'` in
`mercury/models.py:sync_any`, cioè connessione RPyC non ancora disponibile). Non è una
regressione: va atteso il completamento prima di dichiarare fallito un deploy. Un
`restart` che non tocca i `.pyx` è invece immediato.
