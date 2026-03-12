---
name: frankfurt-news-briefing
description: Generar briefings locales de Frankfurt con noticias de Google News RSS, clima de Open-Meteo y festivos cercanos de Nager.Date, sin depender de otro LLM. Usar cuando el usuario pida noticias de Frankfurt, huelgas, alertas, movilidad, contexto social, previsión de lluvia/temperatura, fin de semana o festivos cercanos.
---

# Frankfurt News Briefing

Usar `scripts/frankfurt_news_briefing.py` para obtener datos frescos y resumirlos directamente en la respuesta. No depender de Azure/OpenAI ni de otros modelos para la síntesis.

## Flujo

1. Ejecutar `python scripts/frankfurt_news_briefing.py --pretty`.
2. Revisar `errors` antes de redactar. Si una fuente falla, indicarlo brevemente.
3. Resumir solo a partir de:
   - `top_headlines`
   - `categories`
   - `weather.current`, `weather.today`, `weather.tomorrow`, `weather.weekend`
   - `holidays`
4. Dejar claro que las noticias cubren solo las ultimas `24` horas.
5. Priorizar impacto practico:
   - huelgas, cortes, alertas, movilidad
   - lluvia, temperatura actual y del dia siguiente
   - sabado y domingo si aparecen en `weather.weekend`
   - festivos cercanos si existen
6. Citar enlaces de las noticias mas importantes cuando el usuario pida detalle o fuentes.

## Formato recomendado

Responder en espanol con esta estructura, adaptandola al pedido:

- Resumen operativo
- Movilidad y alertas
- Clima
- Festivos cercanos
- Titulares destacados

Si no hay titulares relevantes en una categoria, decirlo de forma explicita.

## Notas practicas

- Tratar `errors` como fallos parciales de fuentes, no como fallo total si hay datos suficientes.
- Si el usuario pide "solo tiempo", usar solo la parte de `weather` y no listar noticias.
- Si el usuario pide "solo noticias", omitir meteo y festivos salvo que aporten contexto claro.
- Si el usuario pide enlaces o detalle, usar `link` y `source` de cada articulo.
