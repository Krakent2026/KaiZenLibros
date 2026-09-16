# Artículos del blog

Un fichero `.md` por artículo, con cabecera YAML. Los ficheros sin cabecera (como este) se ignoran.

```markdown
---
titulo: Por qué esta colección no tiene ningún test
fecha: 2026-10-08
resumen: Reconocerse en un libro no es un diagnóstico. Qué hace Mente distinta en su lugar.
serie: mente_distinta          # id de serie del YAML (opcional)
libro: no-es-pereza            # slug del libro del que sale (opcional; añade la caja de compra)
slug: sin-ningun-test          # opcional; si falta se deriva del título
---

Cuerpo en Markdown...
```

En Fase 3 el Redactor genera estos ficheros a partir de los átomos; el humano los aprueba y el
workflow `web.yml` publica al hacer push.
