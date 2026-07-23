# -*- coding: utf-8 -*-
"""
Patch a Django 1.5 per farlo girare su Python 3.

Django 1.5 e' del 2013 e la sua compatibilita' Py3 era per 3.2/3.3: alcune
parti interne usano nomi rimossi nelle versioni successive. Qui restiamo su
Django 1.5 (l'upgrade a LTS e' la Fase 2), quindi le tocchiamo dall'esterno,
sull'immagine -- esattamente come il workaround GEOS gia' nel Dockerfile.

Sono due incompatibilita' che impediscono l'import dei modelli:

1. `django.utils.html_parser` usa `HTMLParseError`, rimosso da `html.parser`
   in Python 3.5. Lo rendiamo un fallback (una sottoclasse di Exception): non
   e' un percorso che il sito esercita davvero (era per parser HTML rotti).

2. `ModelBase.__new__` crea la classe con un namespace ridotto e non propaga
   `__classcell__` a `type.__new__`; da Python 3.6 questo e' un errore, e fa
   esplodere *ogni* modello con un metodo che chiama `super()` (es. un
   `save()` sovrascritto). Lo passiamo nel namespace, come fara' poi Django
   ufficialmente nelle versioni successive.
"""
import os
import django

D = os.path.dirname(django.__file__)


def patch(path, old, new):
    full = os.path.join(D, path)
    s = open(full).read()
    if new in s:
        return  # gia' applicata (idempotente: l'immagine la bake, i test la rifanno)
    assert old in s, "stringa da patchare non trovata in %s" % path
    open(full, 'w').write(s.replace(old, new))


# 1) html_parser.HTMLParseError
patch(
    os.path.join('utils', 'html_parser.py'),
    'HTMLParseError = _html_parser.HTMLParseError',
    "HTMLParseError = getattr(_html_parser, 'HTMLParseError', "
    "type('HTMLParseError', (Exception,), {}))",
)

# 2) ModelBase.__new__ deve propagare __classcell__
patch(
    os.path.join('db', 'models', 'base.py'),
    "new_class = super_new(cls, name, bases, {'__module__': module})",
    "_classcell = attrs.pop('__classcell__', None)\n"
    "        _ns = {'__module__': module}\n"
    "        if _classcell is not None:\n"
    "            _ns['__classcell__'] = _classcell\n"
    "        new_class = super_new(cls, name, bases, _ns)",
)

# 3) QuerySet._result_iter e' un generatore che fa `raise StopIteration` per
#    fermarsi. Da Python 3.7 (PEP 479) uno StopIteration che esce da un
#    generatore diventa RuntimeError, e questo rompe *ogni* iterazione di
#    QuerySet ("generator raised StopIteration"). Si sostituisce con `return`.
#    (I `raise StopIteration()` di multipartparser NON si toccano: sono in
#    metodi __next__, dove sono corretti e non soggetti alla PEP 479.)
patch(
    os.path.join('db', 'models', 'query.py'),
    "            if not self._iter:\n                raise StopIteration",
    "            if not self._iter:\n                return",
)

print("Django %s patchato per Python 3 (html_parser + __classcell__)"
      % django.get_version())
