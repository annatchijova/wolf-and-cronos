# CRONOS — Runbook de demo y guion de video

Kit para ensayar la demo tantas veces como haga falta y grabar el video
de la submission. Todo el flujo es reseteable: `demo_seed.py --reset`
deja la base limpia para la siguiente toma.

---

## 1. Checklist previo (una sola vez)

Antes de la primera prueba, verificá en orden:

1. **Sandbox de Slack** creado desde el Developer Program, con la app
   instalada. Guardá la URL del workspace: la piden en la submission.
2. **Manifest actualizado**: scopes `search:read.public`,
   `search:read.private`, `search:read.im`, `search:read.mpim` agregados,
   y la función Agents & AI Apps habilitada en la configuración de la app
   (requisito para que la RTS API responda).
3. **Capacidades RTS del sandbox**: llamá a `assistant.search.info` con el
   token del bot. Si el plan no incluye Slack AI Search, la búsqueda
   semántica no está — la keyword search alcanza para la demo, pero
   conviene saberlo antes de grabar.
4. **Historial para el RECALL**: la RTS busca en mensajes reales. Plantá
   contexto en un canal `#incidents` del sandbox: tres o cuatro mensajes
   describiendo incidentes pasados (un timeout de auth resuelto con
   rotación de token, un bug de cache con Redis, una escalación IAM).
   Con eso, cuando el agente busque "ticket auth", la RTS devuelve
   resultados reales del workspace y el video muestra permalinks
   verdaderos.
5. **Servidor MCP registrado** en Claude Code
   (`claude mcp add cronos -- python /ruta/mcp_server.py` o el bloque
   JSON del docstring de `mcp_server.py`), con `CRONOS_DB_PATH` apuntando
   a LA MISMA base que usa el bot y `SLACK_BOT_TOKEN` seteado.
6. **Bot corriendo**: `python main.py` con Socket Mode conectado.
7. **Miembros del sandbox**: invitá a `slackhack@salesforce.com` y
   `testing@devpost.com` — es requisito de la submission y conviene
   hacerlo antes de olvidarlo.

---

## 2. Matriz de pruebas

Corré `python demo_seed.py --reset` y después probá cada fila. La
columna "qué verificar" es lo que tiene que verse para que la demo esté
lista.

### 2.1 Slash commands sobre datos sembrados

| Acción | Qué verificar |
|---|---|
| `/cronos status` | 4 agentes (support-resolver, deploy-guard, incident-triage, claude-code), 8 trazas |
| `/cronos trace` | Lista con badges de calidad FULL/PARTIAL/MINIMAL mezclados |
| `/cronos trace deploy-guard` | Solo las 3 trazas de deploy-guard |
| `/cronos explain b2b06c` | La traza MINIMAL: confianza 60% con warning "capped at 3/5 (diversity ceiling)" — el agente reclamó 95% |
| `/cronos explain 72e4de` | 2 contradicciones listadas (tipo A: network_issue; tipo B: dns_failure descartada con evidencia a favor) |
| `/cronos explain a29434` | Piso: reclamó 2%, guardado 10% con warning |
| `/cronos audit` | Cadena VERIFIED, 8 entradas |

Nota: los IDs cambian en cada seed — usá los prefijos que imprime
`demo_seed.py` al terminar.

### 2.2 Flujo forense (tamper)

| Paso | Comando | Resultado esperado |
|---|---|---|
| 1 | `/cronos audit` en Slack | VERIFIED |
| 2 | `python demo_seed.py --tamper` en terminal | Imprime la decisión original y la falsificada |
| 3 | `/cronos audit` en Slack | BROKEN — identifica la entrada exacta con hash almacenado vs recomputado |
| 4 | `python demo_seed.py --reset` | Base limpia para la próxima toma |

### 2.3 Agente en vivo (RTS)

| Acción | Qué verificar |
|---|---|
| Mencionar al bot: `@cronos fix ticket #842 login timeout auth` | Responde en thread con decisión + trace card |
| `/cronos explain` inmediato | El paso TOOL `workspace_recall` dice `source=rts` y los RECALL tienen permalinks del workspace |
| Repetir con la app sin scopes RTS (o token inválido) | `source=local_fallback:<razón>` — la traza documenta su propia degradación |

### 2.4 MCP con Claude Code

Abrí Claude Code con el servidor registrado y pegá este prompt:

> Resolvé este problema y registrá tu razonamiento completo en CRONOS
> usando las tools cronos_*: "El test test_chain.py falla
> intermitentemente en CI pero pasa local". Abrí una traza con
> agent_id="claude-code" y channel_id="<TU_CANAL>", registrá cada
> hipótesis que consideres, la evidencia a favor y en contra, descartá
> las que rechaces con su razón, y cerrá con tu decisión y confianza.

| Qué verificar |
|---|
| Claude llama a `cronos_open_trace`, varias `cronos_add_hypothesis` / `cronos_add_evidence` / `cronos_discard_hypothesis`, y `cronos_close_trace` |
| Al cerrar, la trace card aparece sola en el canal indicado |
| `/cronos trace claude-code` muestra la traza nueva junto a la sembrada |
| Si Claude reclama confianza alta con pocos pasos, el response de `close_trace` muestra `confidence_stored` menor que `confidence_submitted` |

### 2.5 Robustez (probar al menos una vez)

`/cronos explain zzzzz` responde "No trace found" sin romperse; el bot
ignora mensajes sin patrón de ticket; dos trazas MCP abiertas en paralelo
no se pisan (los `trace_id` son UUID independientes).

---

## 3. Guion del video (3 minutos)

Estructura: problema, solución en vivo, momento forense, cierre técnico.
Cada bloque mapea a un criterio de evaluación.

**0:00–0:25 — El problema** (criterio: Quality of the Idea)

Pantalla: un canal de Slack donde un agente ya respondió "Deploy
approved". Texto sugerido:

> "Los agentes de IA ya toman decisiones en producción. Cuando algo sale
> mal, la pregunta no es qué hizo el agente — eso está en el canal. Es
> por qué. Qué consideró, qué descartó, y cuánta certeza tenía de
> verdad. CRONOS es la caja negra de los agentes: como en un avión,
> graba el razonamiento mientras ocurre, no después."

**0:25–1:10 — El agente razona en vivo** (criterio: Technological
Implementation — RTS API)

Mandás `@cronos fix ticket #842 login timeout auth`. Mientras responde:

> "El agente abre una traza y recuerda: busca incidentes similares en el
> historial real del workspace con la Real-Time Search API de Slack,
> acotado a lo que este usuario puede ver. Cada memoria queda registrada
> con su procedencia y permalink."

Mostrás la trace card en el thread y abrís `/cronos explain`: recall con
permalinks, hipótesis, evidencia, descarte, decisión.

**1:10–1:50 — Cualquier agente, vía MCP** (criterio: Technological
Implementation — MCP)

Cortás a Claude Code resolviendo el prompt de la sección 2.4, con las
llamadas a `cronos_*` visibles. Cuando cierra, volvés a Slack: la card
apareció sola.

> "CRONOS no es una función de un bot: es infraestructura. Cualquier
> agente compatible con MCP graba su caja negra con cinco tools. Y miren
> el detalle: Claude reclamó 90% de confianza, CRONOS guardó 85% — la
> diversidad de su evidencia no daba para más. La caja negra no deja que
> un agente afirme una certeza que su evidencia no sostiene."

(Si en la toma real Claude registra suficientes pasos y no hay clampeo,
usá la traza sembrada `b2b06c` con `/cronos explain` para mostrar el
techo 95%→60%.)

**1:50–2:35 — El momento forense** (criterio: Potential Impact)

`/cronos audit` → VERIFIED. Cambiás a la terminal:
`python demo_seed.py --tamper` — se ve la decisión original y la
falsificada. Volvés a Slack: `/cronos audit` → BROKEN.

> "Cada traza queda sellada en una cadena SHA-256. Alguien acaba de
> editar una decisión directamente en la base, sin pasar por la API.
> La auditoría no solo detecta la manipulación: identifica la entrada
> exacta. Esto es lo que un equipo de compliance necesita cuando un
> agente autónomo tocó producción."

**2:35–3:00 — Cierre**

Diagrama de arquitectura en pantalla:

> "CRONOS: MCP server para que cualquier agente grabe, Real-Time Search
> para que recuerde del workspace real, Block Kit para que los humanos
> entiendan, y una cadena de hashes para que nadie reescriba la
> historia. Los agentes ya deciden. CRONOS hace que rindan cuentas."

### Consejos de grabación

Ensayá el flujo completo dos veces antes de grabar; el seed hace cada
toma reproducible. Grabá en ventanas limpias (Slack y terminal, nada
más), con el tema claro de Slack para legibilidad. Si la RTS del sandbox
falla el día de la grabación, el fallback local mantiene la demo viva y
podés narrarlo como feature — pero verificalo antes con
`assistant.search.info`. Guardá una toma de respaldo de cada bloque; el
montaje de bloques cortos es más fácil que una toma única de 3 minutos.

---

## 4. Checklist de submission (Devpost)

Video de ~3 minutos mostrando el proyecto funcionando; URL del sandbox
con `slackhack@salesforce.com` y `testing@devpost.com` invitados;
diagrama de arquitectura (bot Bolt + MCP server + RTS + SQLite/cadena);
selección de track; texto que mencione explícitamente las dos
tecnologías requeridas usadas: MCP server integration y Real-Time
Search API; repo con README actualizado incluyendo la sección de uso
por MCP y la nota de diseño sobre trazas abiertas en memoria.
