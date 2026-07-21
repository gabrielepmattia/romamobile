# PWA installabile e "Fermate vicine a me"

**Stato:** in produzione (`hetzner-4gb-1`, 2026-07-21)
**Principio seguito:** non introdurre uno stack frontend. Queste pagine non caricano
nessuna libreria JS (jQuery è dentro un `{% comment %}` in `base.html`), quindi il
codice nuovo è **vanilla ES5** e si appoggia agli endpoint che già esistono.

---

## 1. "Fermate vicine a me"

### Cosa fa

Bottone in cima alla home: prende la posizione dal browser, e porta all'elenco delle
fermate intorno, ordinate per distanza **a piedi** (non in linea d'aria: la calcola
`giano` sul grafo pedonale). Da lì si sceglie la fermata e si vede tutto ciò che sta
per passare.

### Perché è poco codice

Il percorso esisteva già per intero, usato dal frontend pyjs: la ricerca accetta il
formato `punto:(lat,lng)` e lo trasforma in coordinate Gauss-Boaga.

```
[browser] navigator.geolocation
   └─> /paline/?cerca=punto:(41.890210,12.492231)
         └─> servizi/infopoint.py:geocode_place()   riconosce "punto:(lat,lng)"
               └─> wgs84_to_gbfe(lng, lat)          ATTENZIONE all'ordine: (lng, lat)
                     └─> RPyC: oggetti_vicini_ap    Dijkstra sul grafo pedonale, 1 km
                           └─> elenco fermate + distanza + linee
                                 └─> /paline/palina/<id>  tutti gli arrivi
```

Quindi la modifica è solo lato template:

- `servizi/templates/servizi_new.html` — blocco `#vicine` + script.
- Il blocco è in `display: none` e viene **rivelato da JS** solo se
  `navigator.geolocation` esiste: senza JS, o su un browser che non geolocalizza, non
  compare un bottone che non funziona.
- `/?vicine=1` avvia la ricerca da solo — è il bersaglio della scorciatoia dell'app
  installata (vedi manifest).
- Le stringhe passano per `{% filter escapejs %}`: **un apostrofo in una traduzione
  romperebbe il JavaScript** (e il sito è tradotto).
- Traduzioni inglesi aggiunte in `servizi/locale/en/LC_MESSAGES/django.po` + `.mo`
  ricompilato con `msgfmt`.

### Verificato

In Chrome, con posizione simulata al Colosseo (41.890210, 12.492231):

| Passo | Esito |
|---|---|
| Home | bottone visibile, etichetta tradotta (`📍 Stops near me` in EN) |
| Click con posizione simulata | redirect a `/paline/?cerca=punto%3A(41.890210%2C12.492231)` |
| Fermate trovate | Colosseo/Fori Imperiali (70340) 300 m, (70479) 300 m, Colosseo (MB) 400 m, Labicana/Colosseo 350 m, … |
| Dettaglio fermata | `51 Arriving`, `85` e `87` a 4 fermate (8'), con occupazione posti |

---

## 2. PWA installabile

### Pezzi aggiunti

| File | Servito su | Note |
|---|---|---|
| `xhtml/static/manifest.json` | `/xhtml/s/manifest.json` | nome, `display: standalone`, `theme_color` `#f84f00` (il colore del sito), 2 scorciatoie |
| `xhtml/static/img/icon-192.png`, `icon-512.png` | `/xhtml/s/img/` | ricampionate da `favicon.png` (240×240) con Lanczos |
| `xhtml/static/js/sw.js` | **`/sw.js`** | rotta esplicita in `urls.py` |
| `xhtml/static/html/offline.html` | `/xhtml/s/html/offline.html` | pagina di cortesia |
| `xhtml/templates/base.html` | — | `<link rel="manifest">`, `theme-color`, meta `apple-mobile-web-app-*`, registrazione del SW |

### Due decisioni che vale la pena ricordare

**Il service worker sta in root, non in `/xhtml/s/`.** Lo scope di un service worker è
la directory da cui è servito: da `/xhtml/s/sw.js` controllerebbe solo quel percorso e
non il sito. Serve quindi una `url()` dedicata in `src/urls.py`, sul modello di quella
già presente per `^favicon.png`.

**Il service worker non mette in cache nessuna pagina HTML.** Qui i contenuti sono
tempi di attesa in tempo reale: servire una pagina dalla cache significherebbe mostrare
autobus passati dieci minuti fa, che è peggio che non mostrare nulla. Quindi:

- navigazioni → **solo rete**, con fallback alla pagina offline;
- asset statici (`/<app>/s/*.css|js|png|…`) → cache, aggiornata in background;
- tutto il resto → rete.

### Verificato

In Chrome su `http://localhost` (contesto sicuro, come `https://`):

- service worker **registrato e attivo**, scope `/` (non `/xhtml/s/`);
- `manifest.json` valido, icone 192/512/240 servite con `image/png`;
- `/sw.js` servito come `application/javascript`;
- sintassi di `sw.js` e dello script inline renderizzato validate con `node --check`
  (il secondo *dopo* il rendering Django, perché è lì che entrano le traduzioni).

---

## 3. Lavoro non fatto (di proposito)

- **Icone**: sono un upscale del favicon 240×240. Per un risultato pulito servirebbe un
  sorgente vettoriale o comunque ≥512 px. Nessuna icona `maskable`.
- **Traduzioni**: fatte solo per `en`, l'unica lingua con catalogo esistente.
- **Niente cache offline dei dati**: per scelta, vedi sopra. Se un giorno si volesse
  una "ultima fermata vista" consultabile offline, andrebbe fatta con un timestamp
  bene in vista, mai spacciandola per informazione corrente.
- **`display: standalone`** senza `display_override`: nessun comportamento speciale su
  desktop.
