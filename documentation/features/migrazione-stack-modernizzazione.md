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
| `unicode()` / `basestring` / `cmp=` | ~40 punti | Medio (str/bytes) | ✅ batch 4, coda in batch 10 |
| import relativi impliciti (`from models import *`) | diffusi | Medio | ✅ batch 3 (`.py`) e 7 (`.pyx`) |
| `.pyx` Cython (grafo, geocoder) | 6 file | Ricompilazione + fix minori | ✅ batch 7 (Cython 3 resta con Py3) |

### Dipendenze morte / da sostituire

| Attuale | Sostituto | Stato |
|---|---|---|
| `BeautifulSoup==3.2.1` | `beautifulsoup4` | ✅ batch 6 |
| `pycrypto==2.6.1` (morto, CVE noti) | nessuno: non era importato | ✅ batch 6 (via rimozione di `paramiko`) |
| `pycha`, `pycurl`, `PyYAML` | nessuno: non importati | ✅ batch 6 |
| `cGPolyEncode==0.1.1` (nessuna release Py3) | `polyline` | ✅ batch 8 |
| `Cython==0.23.4` | Cython moderno | ✅ batch 7 |
| `pyproj==1.9.5.1` | `pyproj` 2.2.2 (ultima con Py2) | ✅ batch 9 |
| `rpyc==3.3.0` | `rpyc` 4.1.5 (ultima con Py2) | ✅ batch 13 |
| `django-json-rpc`, `django-constance` | versioni correnti | Fase 2 |
| `protobuf` / `gtfs-realtime-bindings` | ultime con Py2 | ✅ batch 11 |
| `Django==1.5.12` | Django LTS | Fase 2 |

### Dipendenze ancora da affrontare, e cosa comporta ciascuna

| Pacchetto | Nota |
|---|---|
| ~~`pyproj==1.9.5.1`~~ | ✅ batch 9. Il timore sull'API era mal riposto: cambia `pyproj.transform()`, che `geomath` non chiama mai. Il rischio vero era sotto, PROJ 4 → PROJ 6; misurato nullo. |
| ~~`rpyc==3.3.0`~~ | ✅ batch 13, → 4.1.5 (ultima con Py2; la 5.0 la droppa). Il protocollo **cambia** davvero, ed è per questo che `web` e `giano` si aggiornano insieme: resta l'unico passo non incrementale. Ma il payload viaggia come byte picklati **passati per valore**, non sulla serializzazione di RPyC — forma e tipi identici, misurati su Py2.7+4.1.5. Nessun servizio ha `on_connect`/`__init__(conn)`, quindi il cambio di istanziazione dei servizi 3→4 non ci tocca. L'unico default cambiato di nascosto (`sync_request_timeout`: assente → 30 s) è rifissato a `None`. |
| ~~`gtfs-realtime-bindings==0.0.6`~~ | ✅ batch 11, insieme a `protobuf`. Attenzione: non era neutro — le 0.0.7 riconoscono `occupancy_status = 7` che le 0.0.6 scartavano. |
| `django-json-rpc`, `django-constance` | Versioni vincolate a Django: si muovono in Fase 2. `django-json-rpc` su Py3 vuole `six`. |
| ~~`django-simple-captcha`~~, ~~`django-redis`~~ | ✅ batch 14: **rimosse**, non usate. `captcha` non è in `INSTALLED_APPS` né importato; era anche la causa del conflitto pip `Django>=1.7`. `django-redis` non è importato da nessuna parte e la cache è `LocMemCache`. |
| `Pillow==2.3.0`, `requests==2.9.1`, `pytz==2015.7` | Nessun ostacolo noto: hanno tutte versioni Py3. Aggiornabili col flip. |
| ~~`lxml==3.3.3`~~, ~~`redis==2.10.5`~~ | ✅ batch 14: **rimosse**, non importate (`lxml`: il codice usa solo `xml.etree` stdlib e `bs4` con `html.parser`; `redis`: nessun uso). Tolgono due dipendenze C-extension dal flip. |

---

## 3. Fasi

### Fase 0 — Rete di sicurezza (prerequisito)

**Perché:** non esiste (ancora) una suite di test; migrare senza verifica è cieco.

- [x] Inventario degli endpoint critici: non è un elenco a parte, sta in
      `scripts/smoke_test.py`. Un inventario che non viene eseguito invecchia
      senza che nessuno se ne accorga; quello lì dentro fallisce se sbaglia.
- [x] Smoke test end-to-end: `scripts/smoke_test.py`, 14 controlli, eseguibile in
      Docker. Verifica stato **e** contenuto — vedi sotto perché le due cose non
      coincidono.
- [x] Test di caratterizzazione sul contratto RPC `web` ↔ `giano`:
      `scripts/check_rpc_contract.py`.
- [ ] Fissare i dati/fixtures minimi. **Deliberatamente non fatto, per ora**: i
      due test sopra sono costruiti per non dipendere dai *valori*, quindi girano
      contro lo stack reale senza bisogno di un DB precaricato. Resta però una
      dipendenza da tre identificativi (palina `73992`, percorso `RM173`, linea
      `64`) che un domani il feed GTFS potrebbe non contenere più. Il rischio è
      contenuto perché entrambi gli script **falliscono in modo rumoroso** se
      quegli id smettono di restituire dati: un'impronta vuota non coincide con
      il riferimento, e una pagina sotto i 500 byte è già un errore. Le fixture
      vere servono quando ci sarà una CI senza rete verso il feed.
- [x] `scripts/check_imports.py`: importa ogni modulo del backend (un fork per
      modulo) con i settings Django caricati. Intercetta gli import rotti, che
      `compileall` non vede.
- [x] `scripts/check_sort_equivalence.py`: test di caratterizzazione sull'ordinamento
      degli arrivi, usato per validare il passaggio da `cmp=` a `key=`.

### Come si eseguono

Un comando solo, dalla radice del repo sull'host di deploy:

```
./scripts/run_tests.sh              # tutti i controlli, un solo exit code (~2m15s)
./scripts/run_tests.sh smoke        # solo lo smoke test
./scripts/run_tests.sh rpc-dump     # rifotografa il contratto RPC
IMAGE=romamobile:test ./scripts/run_tests.sh   # prova un'immagine appena costruita
```

C'è anche un `Makefile` (`make test`), ma è un involucro: **l'implementazione è
nello script**, perché sull'host di produzione `make` non è installato e
installarlo per lanciare tre `docker run` sarebbe sproporzionato.

I controlli girano in container usa-e-getta sulla rete dello stack, montando
`src/`, `scripts/` e i secrets — `scripts/` non è dentro il bind mount di `src/`,
ed è il motivo per cui questo script esiste invece di tre comandi ricordati a
memoria. Il riferimento del contratto RPC vive **sull'host** (`/tmp/romamobile-tests`
di default): scritto dentro un container `--rm` sparirebbe con lui.

### Due lezioni finite dentro questi test

**Stato HTTP e funzionamento non sono la stessa cosa.** Il 22 luglio `giano` è
rimasto giù per 441 restart mentre `web` rispondeva **200 su ogni pagina**: erano
pagine vuote di dati. Perciò i casi dello smoke test portano due tipi di
marcatore — quelli che devono esserci sempre, e quelli che compaiono **solo** se
la catena `web` → RPyC → `giano` è viva. Se mancano i secondi il verdetto non è
"passato" ma `CIECO`, con uscita diversa da zero e il comando per controllare
`giano`. Il ramo è stato verificato forzandolo: un rilevatore di guasti mai visto
scattare non è una garanzia.

**Il contratto RPC si caratterizza sulla forma, non sui valori.** I dati sono in
tempo reale e cambiano a ogni chiamata. Ciò che deve restare stabile è quali
chiavi tornano e di che tipo è ciascun valore — che è anche esattamente il
rischio del salto a Python 3, dove il payload è pickle e un `unicode` che diventa
`bytes` non fa rumore. Rendere quell'impronta stabile ha richiesto tre tentativi,
e ogni fallimento era lo stesso errore travestito: **trattare dati come se
fossero struttura**.

| Sintomo | Causa | Rimedio |
|---|---|---|
| `arrivi` cambiava a ogni giro | le sue chiavi sono id di palina, cioè dati | dichiarato come mappa: le chiavi si collassano |
| ogni veicolo dava un'impronta diversa | l'insieme delle varianti dipende da quanti veicoli sono in strada | gli elementi di una lista si **fondono** in un'impronta sola |
| `stato_occupazione`: `None\|int` → `int` | in quel campione nessun veicolo aveva il valore nullo | il confronto ignora `None`: un campione sempre-assente non dice nulla sul tipo |

I **tipi** invece devono coincidere: è la proprietà che serve tenere. Stabilità
confermata su tre esecuzioni consecutive contro dati vivi.

**Un difetto trovato provando l'attrezzatura, non usandola.** Il test sul
contratto RPC faceva il suo lavoro e poi **non usciva**: RPyC 3.3 tiene thread di
servizio non demoni sulla connessione, e l'interprete restava ad aspettarli. Le
prime esecuzioni sembravano riuscite solo perché un `timeout` le uccideva *dopo*
aver stampato l'esito. In uno script di deploy sarebbe stata una pipeline appesa
invece di un errore — il modo peggiore di fallire. Ora la connessione viene
chiusa esplicitamente, con un `os._exit` come rete di sicurezza: da indefinito a
**1,8 secondi**.

**Exit criteria:** ✅ per la parte eseguibile — `./scripts/run_tests.sh` gira in
Docker contro lo stack attuale (Py2/Django 1.5), 2m15s, exit 0. Verificato anche
il caso opposto: con un servizio irraggiungibile esce **1** e non dichiara
successo. Resta da fare una **CI** che lo esegua da sola: oggi va lanciato a mano
sull'host di deploy.

### Fase 1 — Fondamenta Python 3 (compatibilità Py2/3)

**Strategia:** rendere il codice eseguibile su **entrambi** Py2 e Py3 (via `six`/
`future`), così da poter migrare a piccoli passi restando sempre rilasciabili su Py2.

- [x] Sostituire le dipendenze morte con equivalenti Py3-compatibili (tabella
      sopra). Fatte tutte, `rpyc` incluso (batch 13): era l'unica non
      incrementale, e va deployata con `web` e `giano` insieme.
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
- [x] Affrontare a mano i punti `unicode()` e i `cmp=` (→ `cmp_to_key`), via
      `servizi/py3compat.py`. I punti str/bytes veri sui pickle sono chiusi: cache su
      file e PEP 479 di Django (batch 19), pickle base64 su colonne di testo (batch 20).
      Resta il **payload RPyC**, che non è codice da cambiare ma la fotografia del
      contratto da rifare su Py3 al deploy (rete costruita in Fase 0).
- [x] Cython 0.23.4 → 0.29.37 (ultima serie con target Py2) e `language_level=2`
      fissato esplicitamente in ogni `.pyx`. Il salto a **Cython 3** resta da fare
      insieme a Python 3: i warning già segnalano `cpdef variables` e un
      `cdef variable 'time' declared after it is used` in `grafo.pyx`.
- [x] `pyproj` 1.9.5.1 → 2.2.2 (ultima serie con target Py2), validato con
      `scripts/check_proj_equivalence.py`. Restano `rpyc` e
      `gtfs-realtime-bindings`/`protobuf`.
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

- **Bugfix maggiore — tutte le linee risultavano "non attive adesso".** Stesso guasto
  di `9fa9beb`, sul feed rimasto indietro: `romamobilita.it` è passato da Drupal a
  WordPress e ora **301-redirige** le vecchie URL. `requests.head()` non segue i
  redirect, quindi `get_gtfs_rt_last_update()` leggeva `Last-Modified` da una risposta
  di redirect che non ce l'ha → `KeyError`. Essendo la **prima** istruzione di
  `dati_da_gtfs_rt()`, ogni giro di aggiornamento moriva prima di toccare i dati:
  `stat_percorsi` restava agli zeri iniziali, ogni percorso aveva
  `departures + vehicles == 0` e la UI nascondeva tutto — metro **e** autobus.
  - **Sintomo nei log:** `Aggiornamento arrivi!` mai seguito da `completato!!`, con il
    watchdog che riavviava in ciclo. Utile come check di salute.
  - Se `Last-Modified` manca comunque, ora si ripiega sull'ora corrente: il chiamante
    aspetta in loop finché il valore *cambia*, quindi un header assente bloccherebbe
    l'aggiornamento per sempre. Rielaborare un feed già visto costa meno.
  - Dopo il fix: `MEA` 🕒 14 partenze/ora, linea `64` 🚍 2 veicoli, dettaglio palina
    con arrivi e occupazione posti. _(commit separato, non parte della migrazione.)_
- **Fase 1 · batch 4 — `unicode()`, `cmp=`, indicizzazione di `.values()`.**
  Introdotto `servizi/py3compat.py` con i due soli nomi che servono davvero
  (`text_type` e un `cmp()` scritto come `(a > b) - (a < b)`): fa il lavoro di `six`
  senza toccare `requirements.txt` e quindi senza rebuild dell'immagine. Quando il
  backend sarà solo Py3 quel modulo si svuota.
  - `unicode(x)` → `text_type(x)`: 27 punti in 10 file.
  - `unicode(cell, encoding)` → `cell.decode(encoding)` in `unicode_csv.py`, che è la
    scrittura onesta di ciò che fa. Quel modulo è impalcatura CSV di Py2 e va
    **eliminato**, non portato: annotato nella sua docstring.
  - `sort(cmp=f)` → `sort(key=cmp_to_key(f))` (5 punti) e `int.__cmp__` → `cmp()`.
    Le funzioni di confronto sono a più livelli: riscriverle come `key=` sarebbe
    stato facile da sbagliare in silenzio, `cmp_to_key` è la conversione che non può
    cambiare l'ordine.
  - `tp.percorsi.values()[0]` → `list(...)[0]` in `tpl.py`, dove `percorsi` è un dict.
    **Non** applicato a `news/views.py`: lì `.values()` è un QuerySet Django, che
    resta indicizzabile su Py3 — e `list()` caricherebbe tutte le righe.
  - **Verifica:** `compileall` pulito su 2.7 e 3.11; `check_imports` dà 202 moduli con
    gli stessi 4 fallimenti preesistenti; nuovo `scripts/check_sort_equivalence.py`
    confronta `sort(cmp=)` e `sort(key=cmp_to_key())` su 4000 permutazioni casuali
    (con i casi limite: `-1`, capolinea, partenza sconosciuta, pareggi) e ottiene
    ordinamenti identici.

- **Fase 1 · batch 5 — moduli stdlib rinominati.** Stesso approccio del batch 2
  (`try/except ImportError`, nessuna dipendenza nuova): `xmlrpclib` →
  `xmlrpc.client` (10 file), `SocketServer` → `socketserver`, `urllib2` →
  `urllib.request` (alias: `urlopen`, `Request`, `build_opener`, `ProxyHandler`,
  `install_opener` vivono tutti lì), `urllib.urlencode`/`quote`/`unquote` e
  `urlparse.parse_qs` → `urllib.parse` (importati per nome, visto che il modulo è
  stato spezzato in due), `StringIO` di byte dbf → `io.BytesIO` (che esiste identico
  su entrambe le versioni: nessuno shim), `iteratore.next()` → `next(iteratore)`.
  - Rimossi 4 import già morti (`urllib2` in `paline/models.py`, `urllib` in
    `osm.py` e `percorso/views.py`, `StringIO` e `quote` in `paline/views.py`).
  - **Verifica aggiuntiva:** `pyflakes` (nel container `python:3.11-slim`, senza
    aggiungerlo alle dipendenze) per intercettare i `NameError` latenti che un
    import rimosso può lasciare — che né `compileall` né `check_imports` vedono:

    ```
    docker run --rm -v "$PWD/src:/src:ro" python:3.11-slim \
      sh -c 'pip install -q pyflakes; cp -r /src /work && cd /work && python -m pyflakes .'
    ```

    Segnala gli stessi 6 nomi non definiti di prima del batch, tutti preesistenti:
    `servizi/utils.py` (`current`), `servizi/crud.py` (`values`), `paline/jobs.py`
    (`esci`), `paline/osm.py` (`raggiungibilita`), `paline/gtfs/realtime.py`
    (`test_decode`), `romatpl_decoder.py` (`PORT`).

- **Fase 1 · batch 6 — dipendenze morte.** Primo batch che tocca
  `requirements.txt`, quindi il primo che **richiede il rebuild dell'immagine**.
  - Rimossi 4 pacchetti che nel codice non sono importati da nessuna parte:
    `pycrypto` (abbandonato, CVE note), `pycha`, `pycurl`, `PyYAML`.
  - ⚠️ **Il nome del pacchetto PyPI non è il nome del modulo.** Avevo tolto anche
    `cGPolyEncode` cercando `import cGPolyEncode`: il modulo che installa si chiama
    **`cgpolyencode`**, e `paline/gmaps.py` importa proprio quello. Con la nuova
    immagine 21 moduli non si importavano più, tutti a valle di `paline.gmaps`.
    Ripristinato. **Quando si cerca se un pacchetto è usato, va cercato il nome del
    modulo importabile, non quello del pacchetto** — e i due coincidono solo per
    caso (`PyYAML` → `yaml`, `pyshp` → `shapefile`, `gtfs-realtime-bindings` →
    `google.transit`, `django-json-rpc` → `jsonrpc`).
  - Da fare in seguito: `cGPolyEncode` è un binding C **senza release Python 3**,
    quindi resta un bloccante. Il sostituto è il pacchetto puro-Python `polyline`;
    attenzione all'ordine delle coordinate, questo encoder prende `(lon, lat)`.
  - **Trappola:** togliere `pycrypto` da `requirements.txt` non lo toglie affatto —
    la build continuava a compilarlo, perché lo richiede `paramiko` 1.16. Anche
    `paramiko` però serve a una cosa sola, `gtfs_rt_upload`, che è **spenta**:
    l'unica chiamata in `tpl.Aggiornatore.run()` è commentata e i settings che legge
    (`WEBSERVER_HOST/USER/PASSWORD`) non esistono. Bastava però l'`import paramiko`
    in cima al modulo — importato da `trovalinea.py` — per renderlo obbligatorio.
    Spostato dentro le due funzioni che lo usano e rimosso dalle dipendenze.
  - `BeautifulSoup` 3.2.1 (nessuna release Py3) → `beautifulsoup4`. Usato in due
    punti, entrambi via `BeautifulStoneSoup`: `paline/atac_website.py` (solo dal suo
    `__main__`) e `servizi/infopoint.py`, dove `infopoint_url` è la stringa vuota,
    quindi quelle chiamate non raggiungono comunque alcun server.
    - **Il parser scelto è `'html.parser'`, non `'xml'`:** `BeautifulStoneSoup`
      metteva in minuscolo i nomi dei tag e quel codice ci conta
      (`soup.contextname`, `soup.coord_x`). Con il parser XML i nomi manterrebbero
      la capitalizzazione originale e quegli accessi tornerebbero `None` — una
      regressione silenziosa.
  - **Procedura di deploy diversa dai batch precedenti:** immagine ricostruita con
    tag `romamobile:test`, verificata con `check_imports` *contro la nuova immagine*,
    e solo dopo ritaggata e messa in servizio. Il bind mount del codice non basta
    più: cambiano i pacchetti installati. È esattamente questo gate ad aver
    intercettato il pasticcio di `cgpolyencode` prima che arrivasse in produzione.

    ```
    sudo docker build -t romamobile:test .
    sudo docker run --rm --network romamobile_default \
      -v /tmp/rmsrc:/app -v "$PWD/secrets/settings.json:/app/secrets/settings.json:ro" \
      -v /tmp/check_imports.py:/tmp/check_imports.py:ro \
      -w /app romamobile:test python /tmp/check_imports.py
    # solo se 0 falliti:
    sudo docker tag romamobile:test romamobile:latest && docker restart ...
    ```

- **Fase 1 · batch 7 — Cython.** `Cython==0.23.4` (2015) → **0.29.37**, l'ultima serie
  che compila ancora per Python 2.7: si aggiorna il compilatore *prima* che cambi
  l'interprete sotto di lui.
  - **La parte che conta è il pin del `language_level`.** Ogni `.pyx` ora dichiara
    `# cython: language_level=2`. Senza, il livello lo decide il default del
    compilatore: 2 con un warning su 0.29, ma **3 su Cython 3.x** — e cambierebbe la
    semantica di stringhe e divisione dentro il core di routing nel giorno in cui
    qualcuno aggiorna.
  - Resi espliciti gli import relativi *dentro* i `.pyx` (`import tratto` →
    `from . import tratto` in `grafo.pyx`, idem `geocoder.pyx` e `bt/*.pyx`): è la
    parte che il batch 3 aveva lasciato indietro. I `cimport` non si toccano, si
    risolvono tramite i `.pxd` accanto e seguono regole proprie.
  - **Su `bt/`:** nessuno importa `FastAVLTree` & co., solo l'`AVLTree` puro Python
    che usa `paline/tpl.py`, e `bt/__init__.py` ha già il fallback. Quindi il rumore
    `ctrees.h: No such file` che quei `.pyx` producono nel log di `giano` a ogni
    avvio è **innocuo**: `pyximport` li compila senza la directory sorgente negli
    include path e il fallback interviene. Sono candidati alla rimozione, non a una
    riparazione.
  - **Test di caratterizzazione sul routing**, che è ciò che un cambio di compilatore
    mette davvero a rischio — calcolo percorso reale via HTTP, senza dipendere dal
    geocoder esterno:

    ```
    curl -sLG --data-urlencode "start_address=punto:(41.8902,12.4922)" \
              --data-urlencode "stop_address=punto:(41.9009,12.5020)" \
              --data-urlencode "quando=0" --data-urlencode "mezzo=1" \
              --data-urlencode "Submit=Cerca" http://127.0.0.1:8000/percorso/
    ```

    | | prima (Cython 0.23.4) | dopo (Cython 0.29.37) |
    |---|---|---|
    | esito | 200, **13311 b** | 200, **13311 b** (identico byte per byte) |
    | itinerario | Colosseo → Metro B/B1 → Termini | uguale |
    | durata / distanza | 18 minuti, 1.9 km, 550 m a piedi | uguale |

  - **Regalo del compilatore nuovo:** warning che la 0.23 non dava, e che dicono in
    anticipo cosa romperà il passaggio a Cython 3 — da affrontare quando si farà
    quel salto:
    - `grafo.pyx:68,69` — `cpdef variables will not be supported in Cython 3`
    - `grafo.pyx:69` — `cdef variable 'time' declared after it is used`

- **Fase 1 · batch 8 — `cGPolyEncode` → `polyline`.** Chiude l'ultimo bloccante Py3
  noto fra le dipendenze: `cGPolyEncode` è un binding C senza release Python 3, e
  serve a un solo punto, l'encoding delle polilinee per le mappe statiche di Google
  in `paline/gmaps.py`.
  - **Le due librerie non sono equivalenti**, e `scripts/check_polyline_equivalence.py`
    misura quanto invece di andare a intuito: `cGPolyEncode` scarta i vertici sotto
    una soglia (come il vecchio encoder Google Maps v2), `polyline` li tiene tutti.

    | vertici in ingresso | tenuti da cGPolyEncode | tenuti da polyline | caratteri (vecchio → nuovo) |
    |---|---|---|---|
    | 10 | 10.0 | 10.0 | 44.5 → 44.7 |
    | 50 | 49.7 | 50.0 | 197.3 → 198.4 |
    | 200 | 198.9 | 200.0 | 770.0 → 773.8 |

    Cioè: tracciato semmai **più fedele**, stringa più lunga dello **0.5 %** — molto
    lontano dal limite di lunghezza degli URL di Static Maps.
  - ⚠️ Attenzione all'ordine delle coordinate: i punti vengono da
    `geomath.gbfe_to_wgs84()`, che restituisce **`(lon, lat)`**, mentre
    `polyline.encode()` di default si aspetta `(lat, lon)`. Serve `geojson=True`.
  - Trovato per strada: `settings.GOOGLE_MAPS_API_KEY` era letto da `gmaps.py` ma
    **non definito da nessuna parte** — `AttributeError` non appena quel codice
    veniva raggiunto. Ora ha un default vuoto letto dai secrets: le mappe statiche
    restano non funzionanti (Google rifiuta le richieste senza chiave) ma non si
    portano dietro la pagina.

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

- **Batch 4 + fix feed realtime** (`dc58e65`, `4a498b9`): dopo il restart, tutti gli
  endpoint 200 e le risposte **più grandi** di prima (dettaglio palina 5370 → 8576 b,
  linea 64 4659 → 5483 b) perché le linee non sono più nascoste e mostrano previsioni
  e occupazione posti. Nei log di `giano` ricompare `Aggiornamento arrivi completato!!`.

- **Batch 6** (`0e2040f`, `0ecad2b`, `d629ceb`): primo deploy con **immagine
  ricostruita**. `requirements.txt` passa da 30 a 25 pacchetti. Nell'immagine in
  servizio non ci sono più né `pycrypto` né `paramiko`; c'è `beautifulsoup4 4.9.3`.
  `check_imports` contro l'immagine nuova: **202 moduli, 0 falliti**. Container
  ricreati con `docker compose up -d --force-recreate giano web`, risalita in ~60 s,
  smoke test tutto 200 e linee di nuovo attive (`🚍 3 🕒 5` sulla 64). Vecchia
  immagine conservata come `romamobile:rollback`.

- **Fase 1 · batch 9 — `pyproj` 1.9.5.1 → 2.2.2.** Ultima serie che supporta
  ancora Python 2.7: si aggiorna la libreria prima dell'interprete, come già
  fatto con Cython nel batch 7.
  - **Il timore registrato in questa roadmap era mal riposto.** Quello che cambia
    in pyproj 2.x è `pyproj.transform()`, e `geomath` non lo chiama mai: usa il
    `Proj` *chiamabile* (`gbfe(x, y)` e `inverse=True`), che nelle due versioni
    si scrive identico. Nessuna riga di conversione è stata toccata.
  - **Il rischio vero era sotto il Python:** la libreria C passa da **PROJ 4 a
    PROJ 6**. Un datum trattato diversamente avrebbe spostato *tutte* le
    conversioni Gauss-Boaga ↔ WGS84 senza che cambiasse una riga di codice — il
    tipo di regressione che non si vede finché qualcuno non nota le paline fuori
    posto.
  - `scripts/check_proj_equivalence.py` lo misura invece di supporlo: griglia di
    441 punti su Roma, entrambe le direzioni più l'andata e ritorno.

    | | scarto massimo |
    |---|---|
    | WGS84 → GBFE | 0,0000023 m (2,3 µm) |
    | GBFE → WGS84 | 0,0000000000037° (~0,004 mm) |
    | andata e ritorno | 0 |

    È rumore di virgola mobile. La tolleranza è fissata a **1 mm**, tre ordini di
    grandezza sotto ciò che questo codice può rappresentare: le coordinate delle
    paline hanno precisione metrica e in `geomath.py` convive una correzione
    fissa `corr_gbfe = (-16, 78)`, cioè decine di metri applicati a mano. Una
    differenza di *modello geodetico* si manifesterebbe con decine di metri e
    supererebbe quella soglia con enorme margine.
  - **Conferma end-to-end:** il test di caratterizzazione sul routing del batch 7
    (stesso input, Colosseo → Termini) restituisce **13311 byte, identici byte
    per byte** al valore di allora. Un cambio di proiezione si sarebbe visto lì.
  - Rimosso l'`import pyproj` morto in `trovalinea.py` (zero usi di `pyproj.`).
    **Lasciati stare** i `gbfo` in `geomath.py` e `infopoint.py`: sono `Proj`
    costruiti ma mai usati, servono solo a codice commentato. Vanno tolti, ma in
    un batch di pulizia, non in uno di aggiornamento dipendenze.
  - **Trovato per strada** (pyflakes, non introdotto da questo batch): restano 3
    nomi non definiti su Py3 — `unicode` in `paline/models.py:119` e `:365`,
    sfuggiti al batch 4, e `reduce` in `xhtml/views.py:58`, che su Py3 vive in
    `functools`. Candidati per il prossimo batch.

- **Fase 1 · batch 10 — gli ultimi `NameError` latenti.** I tre nomi che pyflakes
  segnalava su Py3 sono in codice che gira, e sarebbero stati **500 a runtime**,
  non errori di import: né `compileall` né `check_imports` li avrebbero mai visti.
  - `paline/models.py` — due `unicode` in controlli "è una stringa?", sfuggiti al
    batch 4. Ora passano da `string_types`, aggiunto a `servizi/py3compat.py`
    accanto al `text_type` che c'era già.
  - Uno dei due usava `type(x) == str` invece di `isinstance`: un proxy di
    traduzione lazy (o qualunque sottoclasse di `str`) cadeva nel ramo "lista" e
    veniva iterato **carattere per carattere**. Passare a `isinstance` è quindi
    una correzione, non una riscrittura equivalente.
  - `xhtml/views.py` — `reduce`, builtin su Py2 e in `functools` su Py3. La metà
    difficile era il seme dell'accumulatore: `struct.pack` restituisce `str` su
    Py2 ma `bytes` su Py3, quindi partire da `''` sarebbe stato un `TypeError`.
    Ora parte da `b''`, che su Py2 è lo stesso oggetto ed è anche il tipo che
    `HttpResponse` si aspetta.
  - **Verifica del GIF:** i due interpreti costruiscono gli stessi 42 byte
    (sha1 `d5fceb65…`, header `GIF89a`), e l'endpoint che li serve in produzione
    (`/xhtml/ga`) restituisce **lo stesso sha1**: 200, `image/gif`, 42 byte.
  - **Trovato per strada:** `from Cookie import …`, modulo stdlib rinominato in
    `http.cookies`, sfuggito al batch 5. Convertito con lo stesso `try/except
    ImportError`. Una battuta su tutti gli altri moduli rinominati (`ConfigParser`,
    `HTMLParser`, `thread`, `copy_reg`, `__builtin__`, …) ha trovato solo
    `cStringIO` in `servizi/unicode_csv.py`, **lasciato apposta**: quel modulo è
    impalcatura CSV di Py2 da eliminare, non da portare, come già dice la sua
    docstring.
  - **Verifica:** `compileall` pulito su 2.7 e 3.11; `check_imports` 202 moduli,
    0 falliti; **pyflakes non segnala più alcun nome non definito** in tutto il
    backend. Nessuna modifica a `requirements.txt`, quindi nessun rebuild: solo
    bind mount e restart.

- **Fase 1 · batch 11 — `protobuf` 3.11.2 → 3.17.3 e `gtfs-realtime-bindings`
  0.0.6 → 0.0.7.** Ultime release con Python 2.7 (la 3.18 di protobuf lo droppa,
  e `gtfs-realtime-bindings` 1.0.0 è solo Py3).
  - **Non è un aggiornamento neutro, e il test di caratterizzazione è ciò che
    l'ha scoperto.** Dando lo stesso feed catturato ai due stack, **103 veicoli
    su 920** cambiano: il feed porta `occupancy_status = 7`
    (`NO_DATA_AVAILABLE`), un valore aggiunto allo standard **dopo** le bindings
    0.0.6. Quelle vecchie non lo conoscevano, lo trattavano come enum sconosciuto
    e lo scartavano, quindi il campo risultava assente; le 0.0.7 lo restituiscono.
  - **Sarebbe stata una regressione visibile.** `decode_occupation_status` manda
    nel secchio "molto affollato" tutto ciò che è `>= 4`, quindi quei 103 veicoli
    avrebbero mostrato l'icona dei tre omini accanto alla scritta *"Nessun dato
    sulla disponibilità di posti"*. La mappa delle etichette **conosceva già** il
    7; era solo il calcolo dell'icona a non saperlo.
  - Corretto alla sorgente con un `_occupancy()` in `gtfs/realtime.py`: il 7
    significa letteralmente "nessun dato", e `None` è come questo codice ha
    sempre scritto quel concetto — così resta una sola rappresentazione per una
    sola cosa. Con la correzione, l'output applicativo dei due stack è
    **identico** su tutto il feed (211716 byte di riassunto confrontati).
  - **Annotato, non corretto:** il test è sulla *verità* del valore, quindi anche
    `EMPTY` (0) diventa `None`. Oggi non si vede perché il feed di Roma non manda
    mai 0, ma è una perdita di informazione preesistente.
  - **Rimossi `paline/gtfs_rt.py` e il generato `paline/gtfs_pb2.py`.** Sono
    morti — in `tpl.py` sia l'import sia tutte le chiamate sono commentate — e
    costavano due cose vere:
    - `gtfs_pb2.py` è generato da un `protoc` dell'era 3.0–3.5, che **protobuf
      3.20+ rifiuta di caricare**: sarebbe stato un bloccante per il passaggio a
      Python 3.
    - Registra gli stessi messaggi `transit_realtime.*` delle bindings ufficiali,
      quindi **importare entrambi nello stesso processo fallisce** (verificato).
      È esattamente il motivo per cui `check_imports` deve forkare a ogni modulo.
  - **Verifica:** `check_imports` **200 moduli** (due in meno, i due rimossi),
    0 falliti; equivalenza del feed IDENTICI; `giano` `RestartCount=0` su 70 s e
    `Aggiornamento arrivi completato!!` nel log; icone di occupazione renderizzate
    correttamente (`people_1/2/3`, nessuna `people_None.png`).
  - **Preesistente, non toccato:** nel log di `giano` compaiono `KeyError` in
    `costruisci_percorso_intersezione` (percorsi citati dal feed ma assenti nella
    rete caricata). Sono in `atacmobile.log` fin dalla riga 2 di un file da
    4,8 MB, quando quel codice stava a `tpl.py:2001`: vengono da lontano e
    meritano un'analisi a parte.

- **Fase 1 · batch 12 — `unicode_csv` e un modulo mai eseguito.**
  - **`paline/gtfs.py` non è mai stato raggiungibile.** Accanto c'è un *package*
    omonimo, `paline/gtfs/`, e in Python il package vince sul modulo: `import
    paline.gtfs` ha sempre risolto a `paline/gtfs/__init__.py`. Verificato in
    container (`paline.gtfs.__file__` → `paline/gtfs/__init__.pyc`,
    `hasattr(g, 'generate_gtfs')` → `False`). Entrambi nascono nell'*Initial
    reimport*, quindi la cosa precede la storia visibile: **l'export GTFS
    statico è spento da sempre**, e `generate_gtfs` non ha alcun chiamante.
    Rimosso; con lui se ne vanno 7 dei 9 usi di `unicode_csv`.
  - **`servizi/unicode_csv.py` era l'ultimo modulo a importare un nome stdlib
    solo-Py2** (`cStringIO`). La roadmap dice di eliminarlo, non di portarlo — e
    resta giusto, ma solo *quando* il backend sarà su Py3: finché in produzione
    gira Py2, i chiamanti hanno ancora bisogno di quella impalcatura.
  - Ora contiene due implementazioni dietro un controllo di versione: su Py2 il
    comportamento storico, su Py3 una delega diretta a `csv`, che lavora in testo
    da sempre. Un `csv_open()` mette l'encoding dove ciascuna versione lo vuole:
    binario su 2, `io.open(encoding=…, newline='')` su 3 — quel `newline=''` è
    richiesto dalla documentazione di `csv`, senza si corrompono i campi quotati
    che contengono a capo.
  - **Verificato invece che sperato**, con `scripts/check_csv_equivalence.py`
    (accenti, delimitatore dentro il campo, virgolette da raddoppiare, a capo
    incorporato, campi vuoti, due encoding):

    | | byte | sha1 | intestazione |
    |---|---|---|---|
    | Py2, modulo storico | 204 | `78ba629f…` | `note;n;nome` |
    | Py2, modulo riscritto | 204 | `78ba629f…` | `note;n;nome` |
    | Py3, modulo riscritto | 204 | `31f9d609…` | `nome;note;n` |

    Su Py2 **byte-identico**, incluso lo stesso `UnicodeEncodeError` sul simbolo
    € in latin-1. Il giro attraverso `cStringIO` con encoder incrementale che è
    stato eliminato era un viaggio a vuoto: codificava in utf-8, decodificava,
    ricodificava.
  - **Differenza non risolvibile qui, documentata nel modulo:**
    `UnicodeLazyDictWriter` prende l'ordine delle colonne da `list(row)`, che è
    ordine di *hash* su Py2 e di *inserimento* su Py3.7+. Stesso contenuto,
    stessa lunghezza, **colonne in ordine diverso**. Chi legge quei file per nome
    non se ne accorge; chi legge per posizione si romperebbe al passaggio.
  - **Verifica:** `check_imports` **199 moduli** (uno in meno, il modulo
    oscurato), 0 falliti; `giano` `RestartCount=0` su 60 s; smoke test tutto 200.
    Nessuna modifica a `requirements.txt`, quindi nessun rebuild.

- **Bugfix — il tronco comune Metro B/B1 non è mai stato costruito.** I `KeyError`
  in `costruisci_percorso_intersezione` che comparivano nei log di `giano` a ogni
  avvio erano `PERCORSI_INTERSEZIONE`, che fissava a mano quattro id di percorso
  GTFS: nessuno dei quattro esiste più (oggi sono `RM597`/`RM625` e
  `RM598`/`RM321`). Quelle righe non erano mai state toccate dall'*Initial
  reimport*, quindi la funzione è rimasta spenta per tutta la storia visibile —
  stessa forma di `paline/gtfs.py`, codice che non è mai partito.
  - **Cosa costava.** La funzione fonde le frequenze delle due linee come
    `1/(1/f1 + 1/f2)`: sul tronco Laurentina–Bologna vale il primo treno che
    passa, quindi l'attesa è quella delle due frequenze sommate. Senza, ognuna
    delle **15 fermate condivise** veniva modellata sulla frequenza di una linea
    sola, e il calcolo percorso sovrastimava l'attesa. Non un errore visibile: un
    risultato peggiore che nessuno poteva notare.
  - **Perché sulla metro pesa più che altrove:** il feed realtime **non contiene
    veicoli della metro** — 289 `route_id`, tutti di superficie. Verificato anche
    lato applicazione: `route_stats` dà `veicoli=0` su tutti e quattro i percorsi
    di B e B1, contro `veicoli=2` sulla linea 64. Gli alert invece la coprono
    (`MEA` compare nel feed). Quindi per la metro la frequenza è **l'unico**
    segnale disponibile, e sbagliarla è tutto ciò che c'è da sbagliare.
  - **Gli id ora si ricavano dalla rete** (`Rete.coppie_tronco_comune`): due
    percorsi che *partono* dalla stessa palina vanno nella stessa direzione, e
    così due che vi *arrivano*. Tanto basta ad appaiare `MEB` con `MEB1` senza
    nominare nulla che il feed generi. È la terza volta in un giorno che id GTFS
    scritti a mano si rivelano scaduti, e `6ce20d5` ne aveva già corretta una
    passando agli id interni stabili: qui si fa un passo oltre. Se
    l'appaiamento non trova nulla, ora lo dice — prima falliva dentro un
    `try/except`.
  - **Corretto anche un difetto latente** nella funzione riaccesa: il capolinea
    veniva preso dall'ultima palina di `p1` invece che dall'ultima **condivisa**.
    Per la B1 sarebbe stato Jonio, che sul tronco comune non è nemmeno una
    fermata. Mai eseguito, mai notato.
  - **Verifica:** allo start di `giano` compaiono `Tronco comune MEBCom1:
    RM597 + RM625 -> MEBCom11` e `RM598 + RM321 -> MEBCom12`, **zero `KeyError`**;
    `MEBCom11` ha 15 fermate; un percorso Piramide → Bologna ora è pianificato su
    *"Metro B - B1"* (21 minuti). `./scripts/run_tests.sh` verde, contratto RPC
    invariato.
  - **Aperto:** `route_stats` dà `partenze/h=0` sul percorso sintetico, perché
    quelle statistiche vengono dai dati osservati e nel feed `MEBCom1` non
    esiste. Non tocca il pianificatore (che usa le frequenze), ma se un giorno si
    volessero mostrare le attese sulle pagine delle paline metro, quel numero va
    preso dal modello di frequenza e non da `stat_percorsi`.

### Validazione deploy 2026-07-22 (`hetzner-4gb-1`)

- **Batch 7 e 8 erano arrivati sul server senza rebuild, e `giano` era giù.**
  Il codice è bind-mounted (`./src:/app`), quindi un `git pull` lo porta in
  servizio **subito**; `requirements.txt` invece vive nell'immagine. Il batch 8
  ha introdotto `import polyline` in `paline/gmaps.py`, che nell'immagine non
  c'era: `runtrovalinea_new` moriva all'avvio con `ImportError: No module named
  polyline`, e il `restart: always` lo faceva ripartire all'infinito.
  **`RestartCount` era a 441.** Il daemon di routing era fermo: niente arrivi in
  tempo reale, niente calcolo percorso. `web` restava su e serviva le pagine, ed
  è il motivo per cui il guasto non si vedeva da un check HTTP sulla home.

  - **La lezione, da mettere nel runbook:** *un batch che tocca
    `requirements.txt` non è deployato finché l'immagine non è ricostruita.* Il
    batch 6 lo aveva già scritto, ma come procedura da seguire, non come
    condizione da verificare. Il controllo che l'avrebbe intercettato in un
    secondo è `docker ps`: `Restarting (1)` invece di `Up`.
  - **Sintomo utile:** `RestartCount` alto su `giano` con `web` sano. Un
    monitoraggio che guardi solo gli endpoint HTTP pubblici non lo vede, perché
    le pagine continuano a rispondere 200 — solo più povere.

- **Rimessa in servizio** seguendo la procedura del batch 6: `docker build -t
  romamobile:test .` → `check_imports` **contro l'immagine nuova** (202 moduli,
  **0 falliti**) → `docker tag romamobile:latest romamobile:rollback-20260722` →
  promozione a `latest` → `docker compose -f docker-compose.yml -f
  ../../docker-compose.yml up -d --force-recreate giano web`.

  - **Attenzione al comando compose:** lo stack si avvia con **due file
    sovrapposti** (`repo/romamobile/docker-compose.yml` più l'override in
    `~/apps/_romamobile/`) e `working_dir` sul primo. Lanciare `docker compose
    up` dalla directory dell'override usa solo quello, e i path relativi
    (`./src`, `./secrets`) non risolvono: fallisce con `bind source path does
    not exist`. Il comando giusto è quello sopra, dal repo.

- **Smoke test dopo il rebuild**, tutti 200:

  | Endpoint | Dopo batch 8 | | Endpoint | Dopo batch 8 |
  |---|---|---|---|---|
  | `/` | 11029 b | | `/paline/elenco_linee` | 215721 b |
  | `/metro/` | 7069 b | | `/news/` | 5745 b |
  | `/paline/linea/64` | 7168 b | | `/percorso/` | 8382 b |
  | `/paline/linea/MEA` | 7146 b | | `/meteo/` | 5982 b |
  | `/paline/palina/73992` (RPC → `giano`) | 10408 b | | `/paline/percorso/RM173` | 13759 b |

  Le risposte sono più grandi della baseline del batch 2 (palina 5370 → 10408 b,
  linea 64 4659 → 7168 b): le linee sono attive e mostrano previsioni, quindi la
  catena `web` → RPyC → `giano` è integra. `/metro/` rende "Metro A / Metro B /
  Metro B1 / Metro C". `/metro` senza slash risponde 301 (`APPEND_SLASH` di
  Django), non è una regressione.

- **Batch 9** (`a5dc7ae`): secondo deploy con immagine ricostruita della giornata.
  `check_imports` contro la nuova immagine: **202 moduli, 0 falliti**;
  `check_proj_equivalence` contro l'immagine reale: **EQUIVALENTI**. In servizio
  `pyproj 2.2.2` con `PROJ 6.1.1`. `giano` risalito con `RestartCount=0` stabile
  su 60 s di osservazione. Smoke test tutto 200, con le dimensioni invariate
  tranne le tre pagine che mostrano partenze in tempo reale (`/metro/`,
  `/paline/percorso/RM173`, `/paline/palina/73992`), che variano di minuto in
  minuto per natura. Immagine precedente conservata come
  `romamobile:rollback-pyproj-20260722`.

- **Nota non legata alla migrazione:** da oggi `rm.gpm.name` non è più dietro il
  basic-auth condiviso di Traefik ma dietro un portale Authelia dedicato, per
  poter dare accesso al sito a una persona senza darle anche gli altri servizi
  dell'host. Vedi [Accesso e autenticazione](accesso-e-autenticazione.md).

### 2026-07-23

- **Fase 1 · batch 13 — `rpyc` 3.3.0 → 4.1.5.** L'ultima release che gira ancora
  su Python 2.7 (la 5.0.0 lo droppa): come Cython (batch 7) e pyproj (batch 9),
  si aggiorna la libreria *prima* dell'interprete. È il passo che la roadmap
  segnava da sempre come **l'unico non incrementale** — il protocollo di RPyC
  cambia fra 3.3 e 4.x, quindi `web` e `giano` vanno deployati **insieme**, senza
  poter tornare indietro un pezzo alla volta. Fase 0 aveva costruito
  `scripts/check_rpc_contract.py` esattamente per questo salto.
  - **Perché il salto è risultato quasi vuoto di codice.** Il payload fra `web` e
    `giano` non cavalca la serializzazione di RPyC: è **byte picklati passati per
    valore** (`pickle.loads(getattr(c.root, m)(pickle.dumps(param, 2)))`). Una
    stringa di byte attraversa il canale identica su 3.3 e su 4.1.5, e proprio i
    **tipi** — `unicode` vs `str` (poi `str` vs `bytes` su Py3) — sono ciò che il
    test di contratto sorveglia. Misurato in container Py2.7+4.1.5: round-trip
    con `unicode`/`str`/`None` **intatti**.
  - **E perché il resto della superficie non si è rotto.** Nessun servizio
    (`MercuryListener`, `MercuryProxy`, `Trovalinea`) definisce `on_connect`,
    `on_disconnect` o `__init__(self, conn)`, né usa `self._conn`: il cambiamento
    3→4 nel modo in cui i servizi vengono istanziati e connessi non ci tocca. Il
    resto del pattern è invariato fra le due serie e l'ho verificato *misurandolo*
    invece di fidarmi: `ThreadedServer(classe, port=0, protocol_config=config)`
    con la porta auto-assegnata rileggibile subito da `.port`; `rpyc.connect(host,
    port, config=config)`; l'attributo arbitrario `c.peer = s` sulla connessione;
    `getattr(c.root, metodo)(...)`; `c.root.ping()` e `c.close()` del watchdog.
  - **L'unica riga di sorgente cambiata, e perché.** RPyC 3.3 **non aveva**
    `sync_request_timeout` nel `DEFAULT_CONFIG`: una chiamata sincrona a `giano`
    attendeva senza limite. La 4.x lo introduce con default **30 s**. Il nostro
    `config` non fissava quella chiave, quindi avremmo ereditato il nuovo default
    in silenzio, e una chiamata lenta mai vista scadere prima sarebbe diventata un
    `TimeoutError`. Rifissato a `None` in `mercury/models.py`: il batch aggiorna la
    libreria **senza cambiare il comportamento**. Misurato che regge il carico
    della prova: con un timeout finito la sync *scade* anche sul nostro pattern
    pickle-over-bytes, con `None` completa. Se un domani un timeout finito servisse
    davvero, è una decisione a parte — annotata nel commento del codice.
  - **Superfici morte confermate innocue, non toccate:**
    - `run_mercury_proxy` (il proxy che restituisce un client Mercury come netref)
      **non è avviato**: docker-compose lancia solo `web` e `giano`
      (`runtrovalinea_new cpd tr in_docker`). Il path netref vive solo nell'esempio
      in docstring; quello reale è la connessione persistente diretta di
      `get_web_cl_mercury()`.
    - `calcola_frequenze.py` e `attivacpd.py` fanno solo `from rpyc.utils.server
      import ThreadedServer` senza mai istanziarlo — import morto, e su 4.x il path
      d'import è identico.
  - **Trovato per strada, non corretto:** `paline/views.py:1104` ha un
    `# caricatore = rpyc.async(c.root.carica_rete)` commentato. `async` è parola
    chiave da Py3.7: quella riga, se riesumata, sarebbe un `SyntaxError` su Py3 (in
    4.x il nome è `rpyc.async_`). È dentro il blocco `carica_rete` tutto commentato,
    quindi oggi non gira: è un mina per la Fase 2/3, non per questo batch.
  - **Deploy — richiede il rebuild dell'immagine** (`requirements.txt` cambia): vale
    il gate del batch 6. La validazione è quella per cui Fase 0 esisteva:
    1. **Prima**, nel container `web` ancora su 3.3.0:
       `./scripts/run_tests.sh rpc-dump` (fotografa il contratto su `/tmp/...`).
    2. Ricostruire l'immagine, `check_imports` **contro la nuova immagine**.
    3. **Dopo**, con `web`+`giano` su 4.1.5:
       `python scripts/check_rpc_contract.py --compare <dump>` →
       atteso **CONTRATTO INVARIATO**. Poi `./scripts/run_tests.sh` verde, smoke
       test tutto 200, `giano` `RestartCount=0`.
  - **Validato in deploy** (`hetzner-4gb-1`, 2026-07-23): vedi sotto. Il contratto
    RPC risulta **INVARIATO** fra `rpyc [3,3,0]` e `(4,1,5)` sullo stack vivo.

### Validazione deploy 2026-07-23 (`hetzner-4gb-1`)

- **Il salto è andato liscio, ed è il primo che valida il test costruito apposta
  in Fase 0.** Sequenza esatta:
  1. **Dump PRIMA** sullo stack pristino ancora a `06df1c8` (`giano`+`web` su
     `rpyc (3,3,0)`, `RestartCount=0`): `./scripts/run_tests.sh rpc-dump` →
     5 chiamate ok, impronta scritta in `/tmp/romamobile-tests/`.
  2. `git merge --ff-only origin/master` → `6deaf4f`. `requirements.txt` cambia,
     quindi **rebuild**: `docker build -t romamobile:test .` (`rpyc 4.1.5` +
     `plumbum 1.7.2` installati puliti su Py2.7).
  3. Gate del batch 6: `IMAGE=romamobile:test ./scripts/run_tests.sh imports`
     **contro la nuova immagine** → **199 moduli, 0 falliti** (identico alla
     baseline del batch 12).
  4. `romamobile:latest` (il 3.3.0) conservato come
     `romamobile:rollback-rpyc-20260723`; `test` promosso a `latest`;
     `docker compose -f docker-compose.yml -f ../../docker-compose.yml up -d
     --force-recreate giano web`.
- **Avvio di `giano`:** ~135 s prima di `Aggiornamento arrivi completato!!`. La
  finestra è il caricamento della rete più la ricompilazione `pyximport` dei
  `.pyx` (cache `.pyxbld` vuota nel container ricreato, non perché il batch li
  tocchi: non li tocca). Nel log l'avvio pulito atteso — `Tronco comune MEBCom1:
  RM597 + RM625 -> MEBCom11` e `-> MEBCom12`, `Server listening`, feed in ciclo,
  **zero `KeyError`/`Traceback`**. `RestartCount=0` stabile su entrambi.
- **`rpyc (4,1,5)`** confermato in servizio dentro `giano` **e** `web`.
- **Contratto RPC — la prova che questo batch esisteva per fare:**
  `./scripts/run_tests.sh` verde su tutti e tre i controlli, con `rpc-compare`
  che confronta il client/server 4.1.5 contro il dump 3.3.0:

  ```
  == contratto RPC web <-> giano
  riferimento: python 2, rpyc [3, 3, 0]
    coordinate_palina      identico
    percorso_fermate_ap    identico
    route_stats            identico
    tempi_attesa_ap        identico
    veicoli_percorso_ap    identico
  ESITO: CONTRATTO INVARIATO
  ```

  L'impronta è sui **tipi** di ogni valore di ritorno: nessun `unicode` è
  diventato `bytes`, nessuna chiave è cambiata. Il rischio nominale del salto —
  un tipo che scivola in silenzio perché il payload è pickle — misurato **nullo**.
- **Smoke test** (interno, `web:8000`): 14/14 a 200, incluso *calcolo percorso*
  (routing via RPC, 13341 b) e *dettaglio palina* (RPC, 10261 b) — dimensioni in
  linea con lo stack vivo, quindi le previsioni in tempo reale passano.
- **Rollback pronto** in un comando: `docker tag romamobile:rollback-rpyc-20260723
  romamobile:latest` e stesso `up --force-recreate giano web`.

### Verso il flip a Python 3.10 (2026-07-23)

Con `rpyc` chiuso, l'ultima voce della Fase 1 è il flip dell'interprete. Le app di
terze parti accoppiate a Django (`constance`, `json-rpc`, `picklefield`) **si importano**
su Py3 + Django 1.5, quindi non obbligano ad anticipare la Fase 2.

**Sul target Python — una lezione su cosa vuol dire "misurare".** Un primo probe
minimo (import + `settings.configure` + un template + `urlresolvers`) passava fino a
Python **3.10** e si fermava a **3.11** (`inspect.getargspec`, rimosso in 3.11 e usato
da `template/base.py`). Da lì avevo concluso "target 3.10" — **sbagliato**: quel probe
non toccava l'ORM. Appena un probe esercita un `models.Field` con `choices` (via il
test del batch 16), Python **3.10** si rompe pure lui: Django 1.5 usa
`collections.Iterator` e `collections.Sequence` in `utils/itercompat.py`, alias
**rimossi in 3.10** (spostati in `collections.abc`, deprecati dal 3.3). Su **3.9** gli
alias ci sono ancora (solo un `DeprecationWarning`) e l'ORM gira. Quindi:
- **Python 3.9**: Django 1.5 gira *senza patch* (è il soffitto pulito).
- **Python 3.10**: serve uno shim di ~5 righe che ripristina gli alias
  (`collections.Iterator/Sequence/...` da `collections.abc`) a import-time.
- **Python 3.11**: fuori, `getargspec` è una funzione rimossa, non un alias.

Da decidere al batch del flip: 3.9 pulito o 3.10+shim. La morale sta nel metodo — il
soffitto vero l'ha dato solo il probe che esercitava il pezzo giusto (l'ORM), non
quello che sembrava "abbastanza".

Il flip però non è un batch solo: è una fase con più pezzi indipendenti e ognuno
rischioso a modo suo (Cython 3 sul core routing, `pyshp` 1→2, Pillow, il
`PickledObjectField` con `__metaclass__` Py2-only, str/bytes). Strategia scelta:
**ritirare su Py2 tutto ciò che è both-compatible**, un batch alla volta e validato sul
live, così il flip finale irreversibile resta il più piccolo possibile.

- **Fase 1 · batch 14 — rimozione dipendenze morte.** Tolte da `requirements.txt`
  quattro dipendenze mai usate, verificato ovunque nel repo (non solo `.py`):
  - `lxml` — nessun import; il codice fa XML solo con `xml.etree` stdlib e HTML con
    `bs4`/`html.parser`. Toglie un'estensione C (header libxml2) dal build del flip.
  - `django-simple-captcha` — non è in `INSTALLED_APPS`, non è importata, non compare
    in url o template. Era anche la causa del `ResolutionImpossible` di pip su Py3
    (dichiara `Django>=1.7`): rimuovendola, l'install su Py3.10 non ha più conflitti.
  - `django-redis` + `redis` — nessun import (`redis` compariva solo nell'header di
    licenza), e la cache è `LocMemCache`. Muore la catena di compatibilità
    redis-py ↔ django-redis che altrimenti andava districata nel flip.
  - **Tenuta** `django-picklefield`: non importata dal backend, ma non sono riuscito a
    escludere che `constance` la usi internamente — si rimuove solo ciò che è certo.
  - Richiede rebuild immagine; la validazione è il solito gate `check_imports` contro
    l'immagine nuova (la lezione `cgpolyencode` del batch 6: una rimozione va provata
    contro l'immagine ricostruita, non a vista). Ancora su Py2: nessun cambio di
    comportamento, solo meno dipendenze.

- **Fase 1 · batch 15 — `pyshp` 1.1.4 → 2.1.3.** La 2.x è l'unica con wheel su Py3, ma
  cambia l'API del `Writer`; la **2.1.3** è l'ultima serie che regge ancora Python 2.7
  **ed** è pura-Python, quindi gira anche su Py3.10 — così il flip finale non deve
  ritoccarla. È usata per l'export shapefile dei percorsi (`geomath.zipped_shapefile`,
  chiamata da `tpl.py`).
  - **Cosa cambia nell'API, misurato non supposto:** nella 1.x il `Writer` bufferizza
    in memoria e scrive tutto in `save(path)`; nella 2.x scrive **in modo incrementale**
    e vuole il nome del file già alla costruzione (`Writer(base_path, shapeType=...)`),
    e `save()` sparisce a favore di `close()`. Perciò `zipped_shapefile` è stato
    ristrutturato: la directory temporanea si crea *prima* del `Writer`, non dopo il
    blocco. Inoltre `line(parts=[x])` → `line([x])` (il kwarg `parts=` non esiste più):
    due punti in `tpl.py`. `point`, `field`, `record(**kw)` e il `Reader` di
    `shapereader.py` sono invariati fra le due serie.
  - **Verifica su entrambe le versioni** (`scripts`-style, container usa-e-getta): il
    pattern migrato — `Writer` come context manager, `line([line])`, `record` keyword,
    `point`, e il round-trip con `Reader` (`shapeRecords`, `fields` con `DeletionFlag`
    in testa, `record[i-1]` posizionale, `shape.points`) — dà lo **stesso risultato**
    su Py2.7+pyshp 2.1.3 e Py3.10+pyshp 2.1.3. Both-compatible: deployabile sul live
    Py2, validazione end-to-end sull'endpoint di export.

- **Fase 1 · batch 16 — `PickledObjectField` e il `__metaclass__` fantasma.** Il campo
  custom in `servizi/utils.py` (usato da `paline.models` per `eid`, `punti`,
  `percorso`, `opzioni`) dichiarava `__metaclass__ = models.SubfieldBase`. Quella
  sintassi è **Python 2 soltanto**: su Python 3 l'attributo `__metaclass__` è
  ignorato in silenzio, e la metaclasse — che installa il descriptor che chiama
  `to_python()` all'assegnazione — non verrebbe applicata. Non un errore: un campo
  che smette di deserializzare, restituendo la stringa base64 grezza al posto
  dell'oggetto. Il tipo di regressione che né `compileall` né `check_imports` vedono.
  - Convertito con `six.with_metaclass(SubfieldBase, Field)`, ma scritto a mano in
    `servizi/py3compat.py` per non aggiungere `six` alle dipendenze (stessa scelta di
    `text_type`/`cmp`: niente rebuild per un batch che tocca solo `src`).
  - **Misurato su entrambe le versioni + Django 1.5**, con un modello che ha sia il
    campo vecchio sia il nuovo, assegnando un valore picklato+b64:

    | | Py2.7 | Py3.9 |
    |---|---|---|
    | `with_metaclass(...)` | decodificato `{'k': 1}` | decodificato `{'k': 1}` |
    | `__metaclass__ = ...` | decodificato `{'k': 1}` | **`b'gAJ9...'` grezzo** |

    Cioè: su Py2 le due forme sono **identiche** (il fix non cambia nulla in
    produzione oggi); su Py3 la vecchia forma era rotta e la nuova la ripara. Il caso
    di prova è esattamente il rischio reale del campo. Both-compatible, `src`-only.
  - **Nota:** resta un tema str/bytes più sotto nel campo (`PickledObject(str)`,
    `b64encode` che torna `bytes`, `force_unicode`): è correttezza da validare *al
    flip* caricando/salvando davvero i campi su Py3, non parte di questo batch.

### Validazione deploy 2026-07-23 (`hetzner-4gb-1`, pre-batch 14-16)

I tre pre-batch (ancora su Py2) deployati insieme in un solo rebuild — restano commit
isolati per la reversibilità, ma il rischio è basso e la validazione li copre tutti.

- Rebuild `romamobile:test` → `check_imports` contro la nuova immagine: **199 moduli,
  0 falliti**. La rimozione delle quattro dipendenze non trascina via nulla di
  transitivo (il gate della lezione `cgpolyencode`). Immagine 4.1.5 precedente
  conservata come `romamobile:rollback-prebatch-20260723`.
- Recreate `giano`+`web`; `giano` pronto in ~95 s, `RestartCount=0`, `rpyc (4,1,5)` +
  `pyshp 2.1.3` in servizio, tronco Metro B/B1 costruito, nessun `Traceback`.
- `./scripts/run_tests.sh` verde: smoke 14/14 a 200, **contratto RPC INVARIATO**
  (i pre-batch non toccano il contratto, come atteso).
- **Batch 15 provato dal vero** (non solo in laboratorio): `geomath.zipped_shapefile`
  nel container di produzione genera uno zip di 852 byte con tutti e quattro i pezzi
  (`.shp/.shx/.dbf/.prj`) su pyshp 2.1.3. La migrazione dell'API Writer regge end-to-end.

- **Fase 1 · batch 17 — `grafo.pyx` pronto per Cython 3.** Il batch 7 aveva già
  avvisato: la 0.29 dava *warning* su `grafo.pyx` che Cython 3 avrebbe trasformato in
  errori. Sono due, entrambi nel `cdef class DijkstraVars`, e li ho verificati
  cythonizzando davvero con Cython 3:
  - `cpdef long versione_cp` / `cpdef object time` → **`cdef`**. Cython 3 non supporta
    più `cpdef` sulle *variabili*; già in 0.29 era trattato come `cdef` (privato), e
    sono le `property` esplicite sotto a esporli a Python — quindi il cambio è a
    **semantica invariata**.
  - `import time` **rimosso**: il modulo non era mai usato (nessun `time.xxx`), ma il
    nome collideva con l'attributo `time` della classe e con la locale `time = vv.time`
    in `dijkstra()`. In 0.29 era il warning *"cdef variable 'time' declared after it is
    used"*; in Cython 3 è un **errore duro**. Tolto l'import morto, la collisione sparisce.
  - **Misurato, non supposto:** dopo il fix, `cython grafo.pyx` con **Cython 3** genera
    il `.c` (48951 righe) senza errori, **e** `grafo.pyx` continua a compilare con
    **Cython 0.29** (il compilatore del deploy attuale). Quindi è both-compatible: si
    deploya oggi su Py2, e non ha più nulla che blocchi il flip.
  - **Resta per il flip (batch 18), non per ora:** grafo e geocoder hanno ancora
    `print "..."` statement (`grafo.pyx:336`, `geocoder.pyx:250/389/395`), che a
    `language_level=2` Cython accetta ma a **`language_level=3`** rifiuta. Vanno
    convertiti in `print(...)` insieme al cambio di pragma. `geocoder.pyx` per il resto
    compila già sotto Cython 3. I `bt/*.pyx` restano fuori: falliscono-e-fanno-fallback
    già oggi (batch 7), su Cython 3 idem.
  - `src`-only (nessun `requirements`): deploy = `git pull` + restart di `giano`
    (`pyximport` ricompila il `.pyx`). Validazione sul live: il test di caratterizzazione
    del routing, impronta identica prima/dopo.
  - **Validato in deploy** (`hetzner-4gb-1`, 2026-07-23): `giano` ricompila `grafo.pyx`
    col nuovo sorgente (solo il warning C `-Wmaybe-uninitialized` noto dal batch 7,
    nessun errore Cython), `RestartCount=0`, suite verde (199 moduli, smoke 14/14,
    **contratto INVARIATO**). Il test di routing dà lo stesso **itinerario** (Colosseo →
    Metro B → Termini): non è byte-identico solo perché la pagina include un commento
    `<!--Tempo di calcolo...-->` che varia a ogni richiesta — verificato che due catture
    sullo stesso grafo differiscono già di quello, non del percorso.
  - **Trovato per strada, preesistente, non toccato:** al primo caricamento del feed è
    comparso un `ZeroDivisionError` in `tpl.py:568` (`calcola_percorrenze`,
    `tempo_percorrenza = dist / v` con `v == 0`, cioè una velocità nulla nei dati
    realtime). È in codice non toccato da questo batch, non ricorre dopo l'avvio, e
    l'aggiornamento arrivi torna a completare. Un guasto latente data-dipendente, da
    guardare a parte (una guardia su `v == 0`), non parte del flip.

- **Fase 1 · batch 18 — IL FLIP a Python 3.9.** L'ultimo passo, irreversibile, che
  porta l'*intero* runtime su Python 3 (lo stage JS `pyjs` resta Py2.7: è morto, va in
  Fase 3). Ogni pezzo rischioso era già stato ritirato nei batch 14-17, quindi qui
  restano l'interprete, i bump di dipendenza Py3-only, e Cython 3.
  - **Base image `python:3.9-buster`, non bullseye/bookworm.** Scelta a rischio minimo:
    stesso Debian **buster** del vecchio stage Py2, quindi **stesse** GEOS 3.7 / GDAL /
    PROJ. GeoDjango di Django 1.5 è ctypes puro e sensibile alla versione di GEOS;
    tenendo la libreria identica, i suoi binding si comportano come su Py2 — cambia solo
    l'interprete. Misurato: `from django.contrib.gis.geos import Point; Point(12.5,41.9)`
    funziona su `python:3.9-buster` col solito workaround (che ora patcha
    `python3.9/.../libgeos.py`, non `python2.7`).
  - **`Dockerfile`:** runtime `python:2.7.18-buster` → `python:3.9-buster`;
    `python-dev python-psycopg2` → `python3-dev` (psycopg2 arriva dal wheel binario).
  - **`requirements.txt` — i bump Py3-only**, con le versioni scelte non a caso:
    - `Cython` 0.29.37 → **3.0.11** (i `.pyx` sono a `language_level=3`).
    - `Pillow` 2.3.0 → **9.5.0**: ultima major con `draw.textsize()`, usata da
      `views.py`; la 10 la rimuove.
    - `pyproj` 2.2.2 → **3.6.1** (PROJ 9), `protobuf` 3.17.3 → **3.20.3** (con le
      bindings gtfs 0.0.7), `marisa-trie` → 1.2.1, `psycopg2-binary` → 2.9.9,
      `requests`/`pytz`/`gunicorn`/`ipython`/`Markdown` aggiornati.
    - **`+six`**, richiesto da `django-json-rpc` su Py3.
    - `Django` resta **1.5.12**, `rpyc` 4.1.5, `pyshp` 2.1.3, `polyline` 1.4.0,
      `beautifulsoup4` 4.9.3, `django-constance`/`json-rpc`/`picklefield` invariati.
    - Non serve più `--no-deps`: era `django-simple-captcha` (rimosso al batch 14) a
      far esplodere il resolver con `Django>=1.7`; senza, l'install è pulito.
  - **`.pyx` a `language_level=3`** (grafo, geocoder — i `bt/*` restano lv2, fanno
    fallback): convertiti i 12 `print "..."` → `print(...)`, e `c = i / 2` → `c = i // 2`
    in `grafo.pyx:480` (con lv3 la `/` diventa divisione vera `double`, ma è un indice
    heap `long`: sotto lv2 era già floor division, `//` è l'equivalente esatto).
  - **Validato in laboratorio prima del deploy** (container `python:3.9-buster`):
    install pulito, GeoDjango+Point ok, il path Pillow di `views.py` (`textsize`+`text`+
    `save`) ok, e `grafo.pyx`/`geocoder.pyx` cythonizzano sotto **Cython 3 +
    `language_level=3`**. L'import dei moduli che parlano col DB va provato sull'host
    (in locale falliscono solo perché manca `postgis`, non per Py3).
  - **Ciò che il deploy deve verificare, e che il resto della migrazione ha preparato:**
    - `check_imports` **200-ish moduli, 0 falliti** contro l'immagine Py3.
    - **tutte le equivalenze** (`check_proj_equivalence`, `check_gtfs_rt_equivalence`,
      `check_polyline_equivalence`, `check_csv_equivalence`, `check_sort_equivalence`)
      contro l'immagine Py3, perché i bump di `pyproj`/`protobuf` cambiano libreria.
    - il **contratto RPC**: qui l'impronta *cambierà* per forza — su Py2 un testo si
      picklava `unicode`, su Py3 `str`; un byte `str`→`bytes`. Va guardata una per una:
      `unicode→str` (testo) e `str→bytes` (byte veri) sono i rename attesi di Py3;
      l'unica cosa da temere è un **testo che diventa `bytes`**, la deriva che tutta la
      Fase 1 ha inseguito. Va poi rifatta la fotografia di riferimento su Py3.
    - routing (itinerario invariato) e smoke 14/14.

### Tentativo di deploy del flip 2026-07-23 (`hetzner-4gb-1`) — rollback

Il flip è stato provato in produzione e **riportato indietro**: import, dipendenze e
immagine erano a posto, ma è emerso a runtime il rischo che questa roadmap teneva in
cima al registro fin dall'inizio — **str/bytes nei pickle**.

- **Fino a dove è arrivato, tutto verde:** immagine Py3.9 costruita; `check_imports`
  **199 moduli, 0 falliti**; equivalenze **proj** (PROJ 6→9, scarto 1 nm), **gtfs**
  (protobuf 3.17→3.20, identici) e **csv** tutte passate. Per arrivarci sono servite le
  due patch a Django 1.5 (`dep/patch_django_py3.py`) e i cinque fix app del commit
  precedente.
- **Dove si è rotto:** promossa l'immagine e ricreati `giano`+`web`, `giano` è entrato
  in **restart loop**. `web` reggeva (Python 3.9), ma `giano` moriva al caricamento
  della rete con `UnicodeDecodeError: 'ascii' codec can't decode byte 0xcb`. Localizzato
  con un traceback pulito a **`tpl.py:2190`**:

  ```python
  res = pickle.loads(f.read())   # rete*.v3.dat, serializzata su Py2
  ```

  La cache di rete (`rete.v3.dat`) è un pickle scritto da Py2, con stringhe di byte
  (nomi di fermate accentati). Su Py3 `pickle.loads` prova a decodificarle come ASCII e
  scoppia sul primo `0xcb`. Serve `encoding=` (o rigenerare la cache su Py3), e lo stesso
  vale per il `deserialize` del grafo e per il payload RPyC — tutti pickle Py2.
- **Rollback pulito, servizio ripristinato.** Reimmagine Py2, e — la parte che il primo
  tentativo di rollback ha mancato — **anche la `src`**: i `.pyx` erano a
  `language_level=3`, che su un interprete Py2 dà semantiche stringa sbagliate e fa
  ripartire il loop pure sul Py2. Riportata la `src` al commit pre-flip (`d6e41b6`),
  `giano` è tornato **RestartCount=0** su Python 2.7.18, smoke 14/14. **Lezione per il
  runbook: il flip non è solo l'immagine, è immagine + `language_level` dei `.pyx`; il
  rollback deve riportare entrambi.** L'host è stato riportato interamente a `d6e41b6`
  (tree pulito), così un eventuale rebuild dà di nuovo l'immagine Py2 funzionante.
- **Stato:** i commit del flip restano su `origin/master` (import/dipendenze/immagine
  sono lavoro valido e corretto), ma il flip **non è deployabile** finché non si chiude
  lo str/bytes runtime. La produzione è su Py2 (batch 17 + bugfix), sana. L'immagine Py3
  resta pronta come `romamobile:test`, e `romamobile:rollback-py2-preflip-20260723`
  conserva il Py2 promosso.
- **Cosa manca per ri-tentare:** un giro di correzioni str/bytes sui pickle Py2↔Py3
  (`tpl.py:2190` e i fratelli: `deserialize` del grafo, le altre cache, il payload
  RPyC), con il test del contratto RPC a fare da rete — è esattamente il punto per cui
  era stato costruito. È una fase a sé, non un ritocco.

### 2026-07-24 — la fase str/bytes runtime (ripresa dopo il rollback)

Il flip (batch 18) era tornato indietro sul rischio in cima al registro: str/bytes nei
pickle. La roadmap lo aveva isolato come "una fase a sé". Eccola: due batch, entrambi
`src`-only (nessun rebuild immagine) e both-compatible Py2/Py3 — deployabili sul live
Py2 senza cambiarne il comportamento, e costruiti per reggere il flip.

- **Fase 1 · batch 19 — str/bytes nei pickle su file + PEP 479 di Django** (`51d2ba0`).
  I pickle che il flip ha fatto esplodere in `giano` sono cache su file scritte da Py2.
  Stanati riproducendo il caricamento completo della rete su Python 3:
  - `tpl.py` — le cache `rete*.v3.dat` e `archi_geocoding*.v3.dat` sono pickle Py2 che
    su Py3 falliscono (`UnicodeDecodeError` sui nomi di fermata accentati). Sono **solo
    ottimizzazioni** (il DB è la sorgente): il fallback di caricamento è passato da
    `except IOError` a `except Exception`, così una cache illeggibile/incompatibile
    viene **ricostruita dal DB** e riscritta nel formato dell'interprete corrente, una
    volta sola. Il pickle del grafo OSM è numerico e si carica su Py3 senza problemi; la
    cache del geocoder aveva già un `except` ampio.
  - `patch_django_py3.py` — `QuerySet._result_iter` di Django 1.5 è un generatore che fa
    `raise StopIteration` per fermarsi; da Python 3.7 (PEP 479) quello diventa
    `RuntimeError` e rompe **ogni** iterazione di QuerySet. Patchato a `return`. (I
    `raise StopIteration()` di `multipartparser` sono in metodi `__next__`, corretti lì,
    lasciati stare.) Reso idempotente lo script di patch: gira sia al build sia nei test.
  - **Misurato:** il caricamento completo della rete (`carica` → grafo →
    `carica_rete_su_grafo`) ora **completa su Python 3** — 8291 paline, 1151 percorsi.

- **Fase 1 · batch 20 — str/bytes nei pickle base64 su colonne di testo.** Restavano "le
  altre cache" e i pickle persistiti: tre campi serializzano un oggetto in pickle →
  base64 → `TextField`, e tutti e tre si rompono al flip in modi che né `compileall` né
  `check_imports` vedono:
  - `PickledObjectField` (`servizi/utils.py`, `dbsafe_encode`/`dbsafe_decode`), usato da
    `paline.models` per `ArcoRimosso.eid` e `PercorsoSalvato`;
  - `paline.models.ReteDinamicaSerializzata` (`set_rete`/`get_rete`);
  - `carpooling.models.PercorsoSalvato` (`set_percorso`/`get_percorso`).
  - **Due bug distinti, entrambi certi su Py3.9:**
    - `base64.encodestring`/`decodestring` sono **rimosse in Python 3.9** (deprecate
      dalla 3.1) → `AttributeError` secco. Colpisce `ReteDinamicaSerializzata` e la
      `PercorsoSalvato` del carpooling.
    - `base64.b64encode` su Py3 torna **`bytes`**: wrapparlo in `PickledObject`
      (sottoclasse di `str`) o assegnarlo a una colonna di testo lo stringa come
      `"b'gAJ9...'"`, col prefisso `b'` incluso — dato corrotto. Colpisce ogni scrittura
      di `PickledObjectField` (misurato: `PickledObject(raw)` su Py3.9 = `"b'gAJ9cQBY…='"`).
  - **La correzione, centralizzata in `servizi/py3compat.py`** (stessa scelta di
    `text_type`/`cmp`: nessuna dipendenza nuova, nessun rebuild):
    - `b64encode_text(data)` — base64 come **testo** su entrambe le versioni (su Py2
      byte-identico al vecchio `b64encode`, che è già ASCII);
    - `b64decode_bytes(text)` — inverso via `b64decode`, che su entrambe **scarta i
      caratteri fuori alfabeto**, quindi legge anche le righe storiche scritte da
      `encodestring` (a capo ogni 76 char);
    - `pickle_loads_py2compat(data)` — `pickle.loads` che su un `UnicodeDecodeError`
      (pickle Py2 con byte-string) ritenta con `encoding='latin1'`: mappa i byte 1:1 e
      non fallisce mai. Su Py2 il ramo di ripiego non è raggiungibile.
  - **Misurato invece che sperato** — `scripts/check_pickle_field_equivalence.py`, sui
    tre payload reali (tupla di interi come `eid`, testo accentato, struttura annidata
    tipo percorso salvato), su Py2.7/Py3.9/Py3.11:

    | | round-trip locale | no-corruzione | cross-version (blob Py2 → letto su Py3) | byte-identità Py2 |
    |---|---|---|---|---|
    | Py2.7 | OK | OK | (sorgente) | **identico** al vecchio b64encode |
    | Py3.9 | OK | OK | **OK** | — |
    | Py3.11 | OK | OK | **OK** | — |

    Cioè: una riga scritta da Python 2 (incluso testo accentato) si rilegge intatta su
    Python 3, il round-trip regge sull'interprete nuovo, e su Python 2 la
    rappresentazione in colonna **non cambia** (le righe già in tabella non si toccano).
    `compileall` pulito su 2.7 e 3.11; pyflakes senza nomi non definiti.
  - **Validato anche contro l'immagine Py3.9 vera** (build locale `romamobile:test`,
    non il deploy di produzione): l'immagine si costruisce pulita (dipendenze Py3
    installate, Django patchato), `check_imports` contro l'immagine dà **200 moduli,
    0 falliti** (i moduli toccati importano sotto Django reale su Py3.9), e un
    **round-trip ORM su PostgreSQL** — `ArcoRimosso.eid` (PickledObjectField), la
    `PercorsoSalvato` del carpooling e `ReteDinamicaSerializzata.rete`, con testo
    accentato e simbolo € — salva e rilegge **identico**, con la colonna che contiene
    testo base64 (non `b'...'`). È la verifica "caricando/salvando davvero i campi su
    Py3" che il batch 16 aveva rimandato al flip: chiusa.
  - **Rimossi tre import diventati orfani** (`import base64` in `paline/models.py` e
    `carpooling/models.py`, `from base64 import b64encode, b64decode` in `utils.py`),
    per tenere pyflakes pulito come dai batch 5/10.
  - **Nota su `ReteDinamicaSerializzata`:** è di fatto **codice morto** — l'unico
    chiamante (`runtrovalinea_new.py:98`, `deserializza_dinamico_db()`) invoca un metodo
    **che non esiste**, dentro un `try/except` che stampa "fallita" e prosegue. Corretto
    comunque per uniformità con gli altri due (stesso identico pattern, così `encodestring`
    sparisce dal tree), ma non è sul percorso caldo.
  - **Trovato per strada, preesistente, non toccato:** `paline/views.py:1438`, l'endpoint
    JSON-RPC `GetVeicoliPercorsoConPrevisioni` (integrazione Università di Tor Vergata)
    chiama `c.root.veicoliarshali_percorsi(True, True)` — nome di metodo **corrotto**
    (nessun `exposed_veicoliarshali_percorsi` esiste) e per giunta senza passare
    `id_percorso`. Rotto dall'*Initial reimport*, non è str/bytes né migrazione: va
    corretto a parte, capendo la semantica voluta (probabilmente
    `veicoli_percorso(id_percorso, True, True)`).

- **Cosa resta della fase str/bytes:** il **payload RPyC** fra `web` e `giano`. Su uno
  stack Py3 omogeneo è pickle Py3→Py3 passato per valore: atteso intatto, ma è
  esattamente ciò che il **test del contratto RPC** deve misurare sul live dopo il flip —
  un `unicode→str` (testo) e uno `str→bytes` (byte veri) sono i rename attesi; l'unica
  cosa da temere è un testo che diventa `bytes`. Va poi rifatta la fotografia di
  riferimento su Py3. Non è codice da cambiare qui: è la verifica di deploy che la
  Fase 0 ha costruito.

**Nota operativa (da tenere nel runbook di deploy):** quando un batch tocca un
`.pyx`, `pyximport` invalida la cache in `~/.pyxbld` e **ricompila a runtime** al
riavvio di `giano`. Per ~30 s dopo il restart tutti gli endpoint che passano dall'RPC
rispondono **500** (`AttributeError: 'NoneType' object has no attribute 'root'` in
`mercury/models.py:sync_any`, cioè connessione RPyC non ancora disponibile). Non è una
regressione: va atteso il completamento prima di dichiarare fallito un deploy. Un
`restart` che non tocca i `.pyx` è invece immediato.
