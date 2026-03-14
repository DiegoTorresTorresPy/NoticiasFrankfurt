# Noticias Frankfurt

Briefing operativo para Frankfurt con foco en transporte, alertas, clima y contexto urbano relevante.

## Que hace

- Consulta Google News RSS con busquedas enfocadas en movilidad, huelgas, alertas, ciudad y contexto social, filtrando a las ultimas 24 horas.
- Añade bloques de Alemania para economia, finanzas, cultura y conciertos.
- Consulta el forecast de Open-Meteo para la zona objetivo y destaca temperatura actual, lluvia, hoy, manana y el proximo fin de semana.
- Consulta festivos cercanos de Alemania y Hesse para anticipar cierres o cambios de ritmo en la ciudad.
- Añade una agenda deportiva con Champions League, Formula 1, MotoGP, tenis si aparece Alcaraz y proximos partidos de Real Madrid, Barcelona y Atletico de Madrid.
- Genera una pagina estatica lista para GitHub Pages.
- Usa Azure OpenAI para resumir y priorizar si existen secretos configurados; si no, aplica reglas locales y sigue funcionando.

## Ejecucion local

```powershell
uv run generate_site.py
```

La salida se escribe en `dist/`.

Si prefieres seguir usando `python` directamente, instala antes las dependencias del proyecto:

```powershell
python -m pip install beautifulsoup4
python generate_site.py
```

## Despliegue en GitHub Pages

El workflow esta en [`.github/workflows/publish.yml`](./.github/workflows/publish.yml) y se ejecuta:

- En `push` a `main` o `master`
- Manualmente con `workflow_dispatch`
- Cada hora en UTC (`0 * * * *`), además de en push y manualmente
- Equivale aprox. al inicio de cada hora local en cada zona por cambio automático de huso horario.

El despliegue usa `uv` y resuelve dependencias desde [`pyproject.toml`](./pyproject.toml), incluyendo `beautifulsoup4` para la agenda deportiva mejorada.

## Lo que tienes que hacer en GitHub

1. Subir este proyecto a un repositorio de GitHub.
2. En `Settings -> Pages`, elegir `Source: GitHub Actions`.
3. En `Settings -> Secrets and variables -> Actions`, crear estos secretos:
   - `AZURE_OPENAI_ENDPOINT`
   - `AZURE_OPENAI_API_KEY`
   - `AZURE_OPENAI_DEPLOYMENT_NAME`
   - `AZURE_OPENAI_MODEL` (opcional si ya usas `DEPLOYMENT_NAME`)
   - `AZURE_OPENAI_API_VERSION` (opcional)
4. Lanzar el workflow manualmente una vez para validar el primer despliegue.

## Personalizacion rapida

Si quieres cambiar el enfoque editorial, edita `CATEGORY_CONFIGS` en [`generate_site.py`](./generate_site.py):

- `commute`: trayecto y huelgas
- `alerts`: alertas y emergencias
- `city`: noticias de ciudad y barrio
- `social`: vivienda, sociedad, cultura y economia
- `germany_economy`: economia y finanzas en Alemania
- `germany_culture`: conciertos y cultura en Alemania
