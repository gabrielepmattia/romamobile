# Accesso a rm.gpm.name: da basic-auth condiviso ad Authelia

**Stato:** in servizio dal 2026-07-22
**Ambito:** solo `rm.gpm.name`. Nessun altro servizio dell'host è stato toccato.

---

## 1. Il problema

Il sito non è pubblico: sta dietro il reverse proxy Traefik dell'host
`hetzner-4gb-1`, insieme ad altre ~40 applicazioni. La protezione era il
middleware `protected@file`, un **basic-auth con un unico file di credenziali**
(`configuration/auth.txt`) condiviso da tutti gli host.

Conseguenza: dare accesso a romamobile a una persona significava consegnarle la
password che apre anche tutto il resto. Non esisteva un accesso parziale, né un
modo di revocarlo per una persona sola, né attribuzione nei log — le richieste
autenticate erano indistinguibili fra loro.

## 2. La scelta

Un portale di autenticazione, **Authelia**, davanti al solo `rm.gpm.name`.

Le alternative scartate, e perché:

| Opzione | Perché no |
|---|---|
| Un secondo file htpasswd per romamobile | Risolve la separazione ma non l'identità: nessun logout, nessuna scadenza, credenziali che vivono nel browser |
| Un "container di accesso" con shell (bastione) | Per farci operare Docker serve il socket; anche dietro un socket-proxy, se abiliti la creazione di container sei root sull'host. Confine sottile e tutto da costruire a mano |
| Utente Linux separato + `sudo` ristretto | Necessario solo se serve una shell. Qui l'esigenza era usare il sito dal browser |
| Teleport / Portainer RBAC | Dimensionati per accesso amministrativo multi-servizio, sproporzionati per un sito |

Authelia sostituisce `protected@file` **solo** sul router di romamobile. Tutti
gli altri host restano esattamente come prima.

## 3. Com'è montato

```
~/apps/authelia/
├── docker-compose.yml          # container authelia, rete bridge_dns, router auth.gpm.name
├── authelia.env                # 3 segreti (modo 600, generati con openssl rand)
├── add-user.sh                 # aggiunge un utente e stampa la password
└── config/
    ├── configuration.yml       # policy di accesso e sessione
    ├── users_database.yml      # utenti + hash argon2id (modo 600)
    └── db.sqlite3              # storage interno

~/apps/traefik/configuration/
└── middlewares-authelia.yml    # il middleware forwardAuth, in un file a sé
```

Due scelte volute:

- **Il middleware sta in un file separato**, non dentro `middlewares.yml`. Quel
  file definisce `protected`, che copre tutti gli altri host, e non va toccato.
  Il file provider di Traefik carica l'intera directory `/configuration` e
  unisce le definizioni, quindi `authelia@file` è disponibile come qualsiasi
  altro middleware. Disinstallare Authelia = cancellare un file.
- **`auth.gpm.name` non è dietro alcun middleware di autenticazione.** È il
  portale: metterlo dietro `protected@file` sarebbe un cappio.

L'unica modifica a romamobile è una label in `~/apps/_romamobile/docker-compose.yml`:

```diff
- "...romamobile-secure.middlewares=headers-no-follow@file,protected@file"
+ "...romamobile-secure.middlewares=headers-no-follow@file,authelia@file"
```

Il certificato è il wildcard `*.gpm.name` già presente, quindi `auth.gpm.name`
non ha richiesto emissioni. È servito solo il record DNS su Cloudflare
(A → `23.88.51.143`, proxied), perché non esiste un wildcard DNS.

## 4. Gestione degli utenti

Non c'è auto-registrazione: il backend è a file e gli utenti li si aggiunge a
mano. Lo script fa i tre passi (password casuale, hash argon2id, blocco YAML):

```bash
~/apps/authelia/add-user.sh <username> "<Nome Cognome>" <email>
```

Per **revocare**: togliere il blocco dell'utente da `users_database.yml`. Non
serve riavviare nulla in nessuno dei due casi.

### Le due opzioni che è facile confondere

Costate un debug, quindi vale la pena fissarle:

| Opzione | Cosa fa davvero |
|---|---|
| `authentication_backend.file.watch: true` | Ricarica `users_database.yml` quando cambia. **Senza, un utente appena aggiunto risulta `user not found`** finché non riavvii il container |
| `authentication_backend.refresh_interval: 1 minute` | Rilegge i dettagli utente per le sessioni **già aperte**. È ciò che rende effettiva una revoca |

`refresh_interval` non ricarica il file utenti, che è l'errore che avevo fatto
inizialmente. Ed è l'opzione che conta di più qui: la sessione dura 6 mesi, e
senza di essa rimuovere una persona non avrebbe effetto pratico fino al 2027.

**Misurato:** dopo aver rimosso un utente dal file, la sua sessione attiva
smette di funzionare dopo **~51 secondi** (200 → 302 verso il portale).

### PUID / PGID

L'entrypoint di Authelia gira come root e fa `chown` di `/config`. Senza
`PUID=1000` / `PGID=1000` nel compose, `users_database.yml` diventa `root:root`
e non è più editabile senza `sudo` — proprio il file che si tocca a ogni utente.

## 5. Sessione lunga

```yaml
expiration: 6 months
inactivity: 0
remember_me: 6 months
```

`inactivity: 0` la disattiva: senza, la sessione morirebbe per inattività molto
prima dei sei mesi e l'`expiration` sarebbe decorativa. `remember_me` è allineato
allo stesso valore così il comportamento non dipende dalla casella spuntata al
login.

Il cookie è sul dominio `gpm.name`, necessariamente: deve essere padre sia del
portale (`auth.gpm.name`) sia del servizio protetto (`rm.gpm.name`). Gli altri
host `*.gpm.name` lo ricevono e lo ignorano — non sono dietro Authelia e non
sanno cosa farsene.

## 6. Verifica dell'isolamento

Stessi host, con e senza cookie di sessione Authelia valido:

| Host | senza cookie | con cookie | |
|---|---|---|---|
| `rm.gpm.name` | 302 → portale | **200** | ← l'unico che cambia |
| `traefik.gpm.name` | 401 | 401 | identico |
| `bw.gpm.name` | 200 | 200 | identico |
| `status.gpm.name` | 200 | 200 | identico |
| `waka.gpm.name` | 302 | 302 | identico |
| `shr.gpm.name` | 404 | 404 | identico |

La sessione cambia il risultato su **un solo host**. È la verifica che conta:
non basta che romamobile funzioni, serve che il resto resti chiuso.

`access_control` ha `default_policy: deny` e una sola regola (`rm.gpm.name`),
quindi aggiungere per sbaglio `authelia@file` a un altro router **nega**
l'accesso invece di aprirlo. Se un giorno un secondo servizio finirà dietro
Authelia, servirà distinguere per utente o gruppo con il campo `subject:` —
altrimenti chiunque sia nel file vedrà entrambi.

## 7. Protezione dal brute force

Due livelli, che contano cose diverse. Servono entrambi: da soli hanno ciascuno
un punto cieco che l'altro copre.

### Livello 1 — `regulation` interna di Authelia (per utente)

```yaml
regulation:
  max_retries: 5
  find_time: 2 minutes
  ban_time: 10 minutes
```

**Verificato:** dopo 5 password sbagliate sullo stesso utente, anche la password
**giusta** viene rifiutata per 10 minuti. Nel log:

```
Unsuccessful 1FA authentication attempt by user 'x' and they are banned until ...
```

**Punto cieco:** conta *per utente*. Chi prova un nome utente diverso a ogni
tentativo non incontra mai il contatore, e un utente inesistente non ne ha
nemmeno uno.

### Livello 2 — jail fail2ban `authelia-auth` (per IP)

Copre esattamente quel punto cieco.

**La jail `traefik-auth` che già esisteva NON bastava**, ed è la parte non
ovvia: il suo filtro pretende uno username valorizzato nel secondo campo
dell'access log (`usrre-normal = (?!- )`), che Traefik riempie **solo** con la
BasicAuth. Le richieste verso Authelia hanno `-` in quel campo:

```
<IP> - - [...] "POST /api/firstfactor HTTP/2.0" 401 74 ... "authelia-secure@docker"
```

Finché `rm.gpm.name` stava dietro `protected@file` i suoi 401 portavano lo
username ed erano intercettabili. **Spostandolo dietro Authelia il bersaglio del
brute force è uscito da sotto la jail esistente**, silenziosamente. È una
conseguenza facile da non notare quando si sostituisce un meccanismo di auth.

File aggiunti (bind mount da `~/apps/fail2ban/data-docker/`):

- `filter.d/authelia-auth.conf` — `failregex` su `POST /api/(first|second)factor` con esito 401
- `jail.d/authelia-auth.conf` — `maxretry = 15`, `findtime = 1h`, `bantime = 1h`

`maxretry` è volutamente alto: a 5 fallimenti sullo stesso utente interviene già
Authelia, e un ban all'edge è scomodo da subire per errore. Contro un attacco
vero, che di tentativi ne fa migliaia, 15 o 5 è indifferente.

**L'azione è `cloudflare-token`, non iptables.** Dietro Cloudflare i pacchetti
arrivano dagli IP dell'edge, quindi bannare l'IP reale a livello di firewall
locale non avrebbe alcun effetto: si banna via API sull'edge. Perché nel log
compaia l'IP reale del client serve `forwardedHeaders.trustedIPs` con i range
Cloudflare in `traefik.yml` — già configurato.

**Il filtro è stato provato prima di attivarlo**, con `fail2ban-regex` contro
l'access log reale: 24 righe agganciate su 5871, tutte tentativi di test, zero
falsi positivi sul traffico normale.

```bash
docker exec fail2ban-docker fail2ban-regex \
  /var/log/traefik/access.log /data/filter.d/authelia-auth.conf
```

**Trappola da ricordare:** al riavvio fail2ban rilegge il log dall'inizio della
`findtime`. Attivando la jail subito dopo una sessione di test, i propri
fallimenti vengono conteggiati e ci si autobanna. Lo sblocco è immediato:

```bash
docker exec fail2ban-docker fail2ban-client set authelia-auth unbanip <IP>
docker exec fail2ban-docker fail2ban-client status authelia-auth
```

## 8. Rollback

```bash
# 1. rimetti il basic-auth condiviso sul router di romamobile
sed -i 's/authelia@file/protected@file/' ~/apps/_romamobile/docker-compose.yml
cd ~/apps/_romamobile/repo/romamobile
docker compose -f docker-compose.yml -f ../../docker-compose.yml up -d web

# 2. rimuovi il middleware
rm ~/apps/traefik/configuration/middlewares-authelia.yml

# 3. (opzionale) spegni il portale
cd ~/apps/authelia && docker compose down
```

Nessun altro servizio è coinvolto in nessuno dei tre passi.

## 9. Passo successivo, se servirà

Il basic-auth condiviso `protected@file` copre ancora tutti gli altri host, con
gli stessi limiti di partenza: una credenziale sola, non revocabile per persona,
senza attribuzione. Estendere Authelia a quegli host è un lavoro incrementale —
una regola in `access_control` e una label per servizio — ma è una modifica che
li tocca, quindi va fatta quando c'è una ragione, non per simmetria.
