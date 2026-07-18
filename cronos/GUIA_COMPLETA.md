# CRONOS — Guía completa: de cero a la submission

Esta guía cubre TODO, en orden, desde poner los archivos en su lugar
hasta enviar el proyecto a Devpost. Cada paso dice qué hacer, dónde,
y qué tenés que ver si salió bien. Fecha límite: 13 de julio de 2026,
17:00 hora del Pacífico (21:00 en Argentina).

Contexto en una frase: el hackathon exige que tu app use al menos una
de tres tecnologías (Slack AI, MCP server, Real-Time Search API).
CRONOS como estaba no usaba ninguna. Con los archivos que te entregué
usa dos: un servidor MCP propio y la Real-Time Search API. Esta guía
integra esos archivos, configura Slack, prueba todo, y arma el video
y la submission.

---

## FASE 1 — Poner los archivos en el repositorio

Te entregué cinco archivos en esta conversación. Van acá:

| Archivo entregado | Destino en el repo | Qué es |
|---|---|---|
| `mcp_server.py` | raíz del repo (junto a `main.py`) | Servidor MCP: cualquier agente graba su caja negra |
| `recall.py` | `demo/recall.py` (archivo NUEVO) | Paso RECALL usando la Real-Time Search API |
| `agent.py` | reemplaza `demo/agent.py` | Agente demo actualizado para usar el recall nuevo |
| `demo_seed.py` | raíz del repo | Generador de escenarios de demo |
| `DEMO.md` | raíz del repo | Matriz de pruebas y guion del video |

### 1.1 — Editar `slack/bot.py` (dos cambios chicos)

Los archivos nuevos necesitan que el bot les pase el `action_token`
que viene en los eventos. Abrí `slack/bot.py` y hacé estos dos
reemplazos.

**Cambio 1** — en el handler `handle_mention`. Buscá este bloque:

```python
    @app.event("app_mention")
    async def handle_mention(event, say, client):
        channel = event.get("channel", "")
        user    = event.get("user", "")
        text    = event.get("text", "")
        ts      = event.get("ts", "")
        await demo.handle_message(
            text=text,
            channel_id=channel,
            user_id=user,
            thread_ts=ts,
            say=say,
            client=client,
        )
```

Y reemplazalo por:

```python
    @app.event("app_mention")
    async def handle_mention(event, say, client):
        channel = event.get("channel", "")
        user    = event.get("user", "")
        text    = event.get("text", "")
        ts      = event.get("ts", "")
        action_token = event.get("action_token", "")
        await demo.handle_message(
            text=text,
            channel_id=channel,
            user_id=user,
            thread_ts=ts,
            say=say,
            client=client,
            action_token=action_token,
        )
```

**Cambio 2** — lo mismo en el handler `handle_message`. Buscá el
segundo `await demo.handle_message(...)` del archivo y agregale las
mismas dos líneas: `action_token = event.get("action_token", "")`
antes de la llamada, y `action_token=action_token,` como último
argumento.

### 1.2 — Editar `requirements.txt`

Agregá una línea al final:

```
mcp>=1.0
```

Y en `pyproject.toml`, si tenés lista de dependencias, agregá
`"mcp>=1.0"` ahí también.

### 1.3 — Editar `slack_manifest.yml`

Buscá la sección `oauth_config: → scopes: → bot:` y agregá estos
cuatro scopes a la lista existente (no borres los que ya están):

```yaml
      - search:read.public
      - search:read.private
      - search:read.im
      - search:read.mpim
```

### 1.4 — Instalar la dependencia nueva y commitear

```bash
pip install "mcp>=1.0"
git add -A
git commit -m "Add MCP server + RTS recall for hackathon requirements"
git push
```

Verificación de la fase: `python -c "import mcp; print('ok')"` imprime
`ok`, y `python -c "from demo.recall import WorkspaceRecall; print('ok')"`
ejecutado desde la raíz del repo también.

---

## FASE 2 — Configurar la app en Slack

### 2.1 — Conseguir el sandbox

1. Entrá a `api.slack.com/developer-program` e inscribite (gratis).
2. Desde el panel del Developer Program, creá un sandbox workspace.
   Es un workspace de Slack completo, tuyo, para desarrollo.
3. Anotá la URL del workspace (algo como `tuespacio.slack.com`):
   la vas a necesitar para la submission.

Nota: la búsqueda semántica de la RTS API solo existe en workspaces
con Slack AI Search. La página del hackathon indica cómo pedir un
sandbox con esa función al equipo de partnerships de Slack. Si no lo
conseguís, no es bloqueante: la RTS API hace búsqueda por keywords
igual, y la demo funciona.

### 2.2 — Actualizar la app con el manifest

1. Andá a `api.slack.com/apps` y entrá a tu app CRONOS (si todavía no
   la creaste, botón "Create New App" → "From an app manifest" →
   elegí tu sandbox → pegá el contenido de `slack_manifest.yml`).
2. Si la app ya existía: menú lateral → App Manifest → pegá el
   manifest actualizado con los scopes nuevos → Save Changes.
3. Menú lateral → busca la sección de funciones de IA (aparece como
   "Agents & AI Apps" o similar según la versión de la consola) y
   activá el toggle. Esto es obligatorio: la RTS API rechaza apps
   que no tengan las capacidades de IA habilitadas.
4. Menú lateral → Install App → botón "Reinstall to Workspace" →
   Allow. Cada vez que cambiás scopes hay que reinstalar, si no los
   tokens viejos no tienen los permisos nuevos.

### 2.3 — Copiar las credenciales

De la consola de la app, anotá tres valores:

- **Bot token** (`xoxb-...`): en OAuth & Permissions → Bot User OAuth Token.
- **App token** (`xapp-...`): en Basic Information → App-Level Tokens.
  Si no existe, creá uno con el scope `connections:write` (es para
  Socket Mode).
- **Signing secret**: en Basic Information → App Credentials.

### 2.4 — Preparar el workspace para la demo

1. Creá un canal `#incidents` en el sandbox.
2. Invitá al bot al canal: escribí `/invite @cronos` (o el nombre que
   tenga tu bot) dentro del canal.
3. Pegá estos tres mensajes en `#incidents`, como mensajes separados.
   Son el "historial" que la Real-Time Search va a encontrar cuando
   el agente busque incidentes similares:

   > Incident resolved: auth timeouts in service A were caused by an
   > expired token. Fixed by rotating the auth token and restarting
   > auth-service. Users confirmed login works again.

   > Postmortem: dashboard showed stale data for 3 hours. Root cause
   > was a cache invalidation bug in the Redis TTL configuration.
   > Fixed by flushing the cache and resetting TTL.

   > Security incident closed: a user accessed an admin-only report
   > due to a misconfigured IAM role with a wildcard grant. Fixed by
   > auditing IAM roles and revoking excess permissions.

4. Invitá a los jueces al workspace (Slack → menú del workspace →
   Invite people): `slackhack@salesforce.com` y `testing@devpost.com`.
   Es requisito de la submission.

---

## FASE 3 — Levantar el bot

En una terminal, parado en la raíz del repo:

```bash
export SLACK_BOT_TOKEN="xoxb-lo-que-copiaste"
export SLACK_APP_TOKEN="xapp-lo-que-copiaste"
export SLACK_SIGNING_SECRET="lo-que-copiaste"
export CRONOS_DB_PATH="$HOME/cronos.db"

python main.py
```

Importante: `CRONOS_DB_PATH` con ruta absoluta. El bot, el seeder y el
servidor MCP tienen que apuntar TODOS a ese mismo archivo, porque la
gracia es que compartan la base.

Qué tenés que ver: el proceso queda corriendo y loguea que Socket Mode
conectó. Si tira `ValueError: SLACK_BOT_TOKEN must start with 'xoxb-'`
es que la variable no se exportó en esa terminal.

Prueba rápida: en cualquier canal de Slack escribí `/cronos help`.
Tiene que responder con la lista de comandos. Si responde, el bot
está vivo. Dejá esta terminal corriendo.

---

## FASE 4 — Sembrar datos de demo y probar los comandos

En una SEGUNDA terminal (el bot sigue corriendo en la primera):

```bash
cd ruta/a/tu/repo
export CRONOS_DB_PATH="$HOME/cronos.db"
python demo_seed.py --reset
```

Qué tenés que ver: la lista de 8 escenarios con sus IDs, y al final
`Chain: 8 entries — VERIFIED`. Anotá los prefijos de ID que imprime
(cambian en cada seed).

Ahora en Slack probá, en este orden:

1. `/cronos status` → 4 agentes, 8 trazas.
2. `/cronos trace` → lista con badges FULL, PARTIAL y MINIMAL.
3. `/cronos explain <prefijo-de-la-traza-MINIMAL>` → tiene que mostrar
   confianza 60% con un warning que dice que el agente reclamó 95%
   pero la diversidad de observaciones no lo sostiene. Este es el
   momento más importante del producto: entendelo bien porque lo vas
   a narrar en el video.
4. `/cronos explain <prefijo-de-la-traza-de-contradicciones>` → dos
   contradicciones listadas.
5. `/cronos audit` → cadena VERIFIED.

Ensayo del momento forense (lo vas a repetir en el video):

```bash
python demo_seed.py --tamper
```

Imprime la decisión original y la falsificada. Volvé a Slack:
`/cronos audit` → ahora dice BROKEN e identifica la entrada exacta.
Para dejar todo limpio: `python demo_seed.py --reset`.

---

## FASE 5 — Probar el agente en vivo con la RTS API

1. En el canal `#incidents` (donde ya está el bot invitado y los
   mensajes plantados), escribí:

   `@cronos fix ticket #842 login timeout auth`

2. Qué tenés que ver: el bot responde en un thread con la decisión y
   la trace card debajo.
3. Inmediatamente: `/cronos explain` (sin argumento trae la última).
   Buscá el paso TOOL llamado `workspace_recall`. Ahí dice la verdad:
   - `source=rts` → la búsqueda en el workspace funcionó, y los pasos
     RECALL tienen fragmentos de tus mensajes de `#incidents` con
     permalinks. Excelente, esto es lo que querés para el video.
   - `source=local_fallback:<razón>` → la RTS falló y el agente usó
     las memorias locales. La razón te dice qué arreglar:
     - `missing_scope` → volvé a la fase 2.2 paso 4 (reinstalar app).
     - `not_allowed_token_type` o similar → falta activar Agents &
       AI Apps (fase 2.2 paso 3).
     - `invalid_arguments` relacionado a `action_token` → el token no
       vino en el evento. Agregá un log temporal en `bot.py` para ver
       el payload completo del evento (`log.info("EVENT: %s", event)`)
       y fijate con qué nombre y en qué nivel llega el token; ajustá
       la línea `event.get("action_token", "")` a lo que veas. Es un
       cambio de una línea.

El fallback no rompe nada: la demo sigue funcionando y la traza
documenta qué fuente usó. Pero para el video quiere verse `source=rts`.

---

## FASE 6 — Probar el servidor MCP con Claude Code

1. Si no tenés Claude Code instalado, instalalo desde la documentación
   oficial de Anthropic (`docs.claude.com`).
2. Registrá el servidor (una sola vez):

```bash
claude mcp add cronos \
  --env CRONOS_DB_PATH="$HOME/cronos.db" \
  --env SLACK_BOT_TOKEN="xoxb-tu-token" \
  -- python /ruta/absoluta/a/tu/repo/mcp_server.py
```

3. Abrí Claude Code en cualquier directorio y verificá con `/mcp` que
   el servidor `cronos` figura como conectado.
4. Pegá este prompt (reemplazá el ID del canal — lo sacás de Slack
   abriendo el canal → nombre del canal → View channel details →
   abajo dice el Channel ID, empieza con C):

   > Resolvé este problema y registrá tu razonamiento completo en
   > CRONOS usando las tools cronos_*: "El test test_chain.py falla
   > intermitentemente en CI pero pasa local". Abrí una traza con
   > agent_id="claude-code" y channel_id="C0XXXXXXX", registrá cada
   > hipótesis que consideres, la evidencia a favor y en contra,
   > descartá las que rechaces con su razón, y cerrá con tu decisión
   > y confianza.

5. Qué tenés que ver: Claude llama a `cronos_open_trace`, después
   varias `cronos_add_hypothesis`, `cronos_add_evidence`,
   `cronos_discard_hypothesis`, y al final `cronos_close_trace`.
   En ese momento, la trace card aparece SOLA en el canal de Slack
   que indicaste. Ese es el segundo momento clave del video.
6. Verificá en Slack: `/cronos trace claude-code` muestra la traza.

Si `/mcp` no muestra el servidor: revisá que la ruta a `mcp_server.py`
sea absoluta y que el Python del comando tenga instalado el paquete
`mcp` y las dependencias del repo.

---

## FASE 7 — Ensayo general

Corré el flujo completo de corrido, midiendo el tiempo:

1. `python demo_seed.py --reset`
2. Mención al bot en `#incidents` → card en vivo
3. `/cronos explain` → recall con `source=rts`
4. Prompt de MCP en Claude Code → card aparece sola
5. `/cronos audit` → VERIFIED
6. `python demo_seed.py --tamper` → `/cronos audit` → BROKEN
7. `python demo_seed.py --reset`

Cuando este circuito te salga fluido dos veces seguidas, estás para
grabar. El guion con tiempos y texto sugerido para narrar cada bloque
está en `DEMO.md`, sección 3.

---

## FASE 8 — Grabar el video

- Duración objetivo: 3 minutos. Herramienta: cualquier grabador de
  pantalla (OBS, Loom, QuickTime).
- Grabá cada bloque del guion por separado y unilos después; es mucho
  más fácil que una toma única.
- En pantalla solo Slack y la terminal. Cerrá todo lo demás.
- Subí el video a YouTube como "unlisted" (no listado) y guardá la URL.

---

## FASE 9 — Diagrama de arquitectura

La submission pide un diagrama. Tiene que mostrar: los agentes
(demo bot y agentes externos vía MCP) → CronosTracer → TraceStore
(SQLite + cadena SHA-256) → Slack (Block Kit cards y slash commands),
y la RTS API alimentando el paso RECALL. Pedímelo y te lo genero.

---

## FASE 10 — Submission en Devpost

1. Creá cuenta en Devpost si no tenés, y en `slackhack.devpost.com`
   apretá "Join hackathon".
2. "Enter a submission" y completá:
   - Nombre del proyecto y descripción. En la descripción decí
     EXPLÍCITAMENTE: "CRONOS uses two of the required technologies:
     a custom MCP server (any MCP-capable agent can record its black
     box) and the Real-Time Search API (assistant.search.context
     powers the agent's RECALL step)". Los jueces verifican el
     requisito contra este texto.
   - URL del video de YouTube.
   - URL del repositorio de GitHub (el repo tiene que ser accesible;
     si es privado, dale acceso a los jueces o hacelo público).
   - URL del sandbox de Slack, confirmando que invitaste a
     slackhack@salesforce.com y testing@devpost.com.
   - Diagrama de arquitectura (imagen adjunta o en el README).
   - Track: elegí el que mejor calce con un agente nuevo con
     capacidades forenses (revisá los nombres exactos de los tracks
     en la página al momento de enviar).
3. Enviá ANTES del 13 de julio 17:00 PDT. No lo dejes para el último
   día: Devpost permite editar la submission hasta el cierre, así que
   subí una versión temprana aunque el video no sea el final.

---

## Checklist final (imprimí esto)

- [ ] Archivos nuevos en su lugar y `bot.py` editado (fase 1)
- [ ] `mcp>=1.0` instalado y en requirements
- [ ] Manifest con scopes de search + Agents & AI Apps activado + app reinstalada
- [ ] Canal #incidents con mensajes plantados y bot invitado
- [ ] Jueces invitados al workspace
- [ ] `/cronos help` responde (bot vivo)
- [ ] Seed corre y `/cronos audit` da VERIFIED
- [ ] Mención en vivo produce card con `source=rts`
- [ ] Claude Code graba una traza vía MCP y la card aparece sola
- [ ] Flujo tamper → audit BROKEN ensayado
- [ ] Video grabado y subido (unlisted)
- [ ] Diagrama de arquitectura listo
- [ ] Submission enviada en Devpost con las dos tecnologías nombradas
