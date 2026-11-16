# Semillas del Algarrobo

Plataforma web (Django 5.2 + SQLite) para conocer las comunidades que acompaña Semillas del Algarrobo, ver sus necesidades y colaborar con donaciones únicas o mensuales a través de **Mercado Pago**.

## Índice

1. [Inicio rápido](#inicio-rápido)
2. [Arquitectura](#arquitectura)
3. [Configuración de Mercado Pago](#configuración-de-mercado-pago)
4. [Donaciones únicas](#donaciones-únicas)
5. [Suscripciones (donación mensual)](#suscripciones-donación-mensual)
6. [Webhooks](#webhooks)
7. [Base de datos](#base-de-datos)
8. [Imágenes de las comunidades](#imágenes-de-las-comunidades)
9. [Comunidad destacada y prioridad de necesidades](#comunidad-destacada-y-prioridad-de-necesidades)
10. [Redes sociales](#redes-sociales)
11. [Pruebas](#pruebas)
12. [Producción](#producción)
13. [Seguridad](#seguridad)

---

## Inicio rápido

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env  → completar valores
python manage.py migrate
python manage.py runserver
```

- Sitio: <http://127.0.0.1:8000/>
- Ingreso / registro: <http://127.0.0.1:8000/ingresar/>
- Administración: <http://127.0.0.1:8000/admin/>

Base nueva (sin datos): `python manage.py loaddata usuarios_iniciales` y luego `python manage.py cargar_datos`.

Sin `MERCADOPAGO_ACCESS_TOKEN` el sitio funciona normalmente; solo los botones de pago muestran el aviso "Las donaciones online todavía no están habilitadas".

## Arquitectura

| App | Responsabilidad |
|---|---|
| `accounts` | Usuario propio (`accounts.User`) con tipo *donante* / *comunidad*. Login por email. |
| `communities` | Comunidades, necesidades (`Need`), aportes registrados por necesidad (`Donation`), **galería de fotos** (`CommunityImage`) y **cálculo de prioridad** (`priority.py`). Página de inicio. |
| `donations` | **Nueva.** Integración con Mercado Pago: donación única, suscripciones, webhooks, panel del donador. |
| `tickets` | Tickets de soporte (sin cambios). |

Archivos clave de `donations/`:

| Archivo | Qué hace |
|---|---|
| `gateway.py` | Único punto de contacto con la API de Mercado Pago, mediante el **SDK oficial `mercadopago` 3.6+**. |
| `services.py` | Crea órdenes y suscripciones; aplica los datos que devuelve la API a la base (idempotente). |
| `webhooks.py` | Valida firma `x-signature`, deduplica y procesa notificaciones. |
| `status.py` | Traduce estados de Mercado Pago a estados internos. |
| `forms.py` | Validación de importes en el servidor. |
| `management/commands/sincronizar_mercadopago.py` | Reconciliación de respaldo. |

## Configuración de Mercado Pago

### ¿Checkout Pro "tradicional" u Orders API?

Mercado Pago ofrece hoy dos formas de integrar Checkout Pro:

- **Preferences API** (`/checkout/preferences`, `init_point`): la integración clásica. Sigue funcionando pero Mercado Pago la presenta como la opción anterior.
- **Orders API** (`POST /v1/orders` con `type: "online"` y `processing_mode: "manual"`, devuelve `checkout_url`): es la **recomendada para integraciones nuevas** y donde Mercado Pago publica las funciones nuevas.

Este proyecto usa **Orders API**. La experiencia para el donador es la misma de Checkout Pro (página de pago de Mercado Pago con todos los medios disponibles); cambia la API del lado del servidor y la notificación (tópico **Order**).

Las **suscripciones** no forman parte de Orders API: se usan las *Suscripciones* de Mercado Pago (`/preapproval`), que es el mecanismo vigente para pagos recurrentes.

### 1. Credenciales

1. Entrá a <https://www.mercadopago.com.ar/developers/panel/app> y creá una aplicación (producto: *Pagos online / Checkout Pro*).
2. En **Credenciales de prueba** copiá *Public Key* y *Access Token*.
3. Pegalos en `.env`:

```env
MERCADOPAGO_ACCESS_TOKEN=APP_USR-...   # o TEST-...
MERCADOPAGO_PUBLIC_KEY=APP_USR-...
```

> Nunca escribas credenciales en el código ni subas `.env` al repositorio (`.gitignore` ya lo excluye). El Access Token solo se usa en el servidor; no se envía al navegador.

### 2. URLs

`SITE_URL` es la URL pública del sitio, sin barra final. Con ella se arman:

| Uso | URL |
|---|---|
| Retorno de la donación única (`success_url`, `failure_url`, `pending_url`) | `SITE_URL/donar/donacion/<referencia>/` |
| Retorno de la suscripción (`back_url`) | `SITE_URL/donar/suscripcion/<referencia>/` |
| Webhook | `SITE_URL/donar/webhooks/mercadopago/` |

Mercado Pago requiere URLs públicas. En desarrollo usá un túnel HTTPS (por ejemplo `cloudflared tunnel --url http://localhost:8000` o `ngrok http 8000`) y configurá:

```env
SITE_URL=https://tu-subdominio.trycloudflare.com
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,tu-subdominio.trycloudflare.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://tu-subdominio.trycloudflare.com
```

Cuando `SITE_URL` es `https://` se envía `auto_return: "all"`, de modo que Mercado Pago devuelve al donador al sitio automáticamente.

### 3. Webhooks

En el panel de tu aplicación → **Webhooks → Configurar notificaciones**:

1. URL de modo prueba (y luego la de producción): `https://TU-DOMINIO/donar/webhooks/mercadopago/`
2. Eventos a marcar:
   - **Order (Mercado Pago)** → donaciones únicas
   - **Planes y suscripciones** (`subscription_preapproval`, `subscription_authorized_payment`) → suscripciones y sus cobros
   - **Pagos** (opcional, respaldo)
3. Guardá y copiá la **Clave secreta** en `.env`:

```env
MERCADOPAGO_WEBHOOK_SECRET=...
```

Con `DJANGO_DEBUG=False` y sin clave secreta, el webhook responde 503 (no se aceptan notificaciones sin validar).

### 4. Entorno de pruebas

1. En el panel → **Cuentas de prueba**, creá una cuenta *Vendedor* y una *Comprador*.
2. Usá las credenciales de la aplicación de la cuenta vendedora de prueba.
3. Pagá iniciando sesión en Mercado Pago con la cuenta **compradora de prueba**.
4. Tarjetas de prueba (Argentina, ver la lista vigente en la documentación):
   - Mastercard `5031 7557 3453 0604`, Visa `4509 9535 6623 3704`, CVV `123`, vencimiento `11/30`.
   - El **nombre del titular** define el resultado: `APRO` aprobado, `OTHE` rechazado, `CONT` pendiente, `CALL` rechazado con validación, `FUND` fondos insuficientes.
   - DNI: `12345678`.
5. Para suscripciones, en el formulario ingresá el **email de la cuenta compradora de prueba** (Mercado Pago exige que coincida con la cuenta que autoriza el débito).

### 5. Producción

1. Pasá a **Credenciales de producción** (la cuenta debe estar verificada) y reemplazalas en `.env`.
2. Configurá la URL de webhooks de producción y su clave secreta.
3. `SITE_URL=https://tu-dominio`, `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY=<clave nueva>`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
4. Ver [Producción](#producción).

## Donaciones únicas

Flujo: **Comunidad → Quiero ayudar → Donación única → elegir importe → Mercado Pago → volver al sitio → estado**.

1. `/donar/unica/` (requiere sesión). El donador elige un importe sugerido o "Otro importe". Opcionalmente viene asociado a una comunidad (`?comunidad=ID`) o necesidad (`?necesidad=ID`).
2. El servidor valida el importe (`forms.OneTimeDonationForm`): solo acepta los importes de `DONATION_PRESET_AMOUNTS` o un importe libre entre `DONATION_MIN_AMOUNT` y `DONATION_MAX_AMOUNT`; si hay una necesidad, no puede superar lo que falta.
3. Se crea `OneTimeDonation` (estado *pendiente*) y una orden con `POST /v1/orders` usando la referencia de la donación como `external_reference` y como **clave de idempotencia**.
4. Se redirige a `checkout_url` (solo se permiten dominios de Mercado Pago).
5. Al volver, `/donar/donacion/<referencia>/` **consulta la orden en la API** y muestra *DONACIÓN APROBADA / PENDIENTE / EN PROCESO / RECHAZADA / CANCELADA / VENCIDA / REEMBOLSADA*. Los parámetros que agrega Mercado Pago a la URL **se ignoran**. Mientras esté pendiente, la página se refresca cada 20 s.
6. El webhook confirma el estado aunque el donador cierre el navegador.

Importes sugeridos (configurables sin tocar código):

```env
DONATION_PRESET_AMOUNTS=5000,10000,20000,50000
DONATION_MIN_AMOUNT=500
DONATION_MAX_AMOUNT=5000000
```

Estados (`OneTimeDonation.Status`) según `status` / `status_detail` de la orden:

| Mercado Pago | Sitio |
|---|---|
| `created`, `action_required` | Pendiente |
| `processing` | En proceso |
| `processed` + `accredited` | **Aprobada** |
| `processed` + `partially_refunded` | Reembolsada parcialmente |
| `failed` | Rechazada |
| `canceled` | Cancelada (`expired` → Vencida) |
| `refunded` | Reembolsada |

Cuando una donación dirigida a una **necesidad** se aprueba, se crea una vez (y solo una) un registro en `communities.Donation`, así la barra de progreso de la necesidad refleja dinero realmente cobrado. Si se reembolsa por completo, ese registro se elimina.

## Suscripciones (donación mensual)

Flujo: **Quiero ayudar → Donación mensual → elegir nivel → Mercado Pago → autorizar → volver → Mi actividad**.

Hay 4 niveles iniciales (modelo `DonorTier`, cargados por la migración `donations/0002_initial_donor_tiers.py`):

| Nivel | Importe inicial |
|---|---|
| Donador Inicial | $5.000 / mes |
| Donador Solidario | $10.000 / mes (destacado) |
| Donador Colaborador | $20.000 / mes |
| Donador Padrino | $50.000 / mes |

**Cómo configurarlos:** *Administración → Donaciones con Mercado Pago → Niveles de donador*. Se puede editar nombre, importe, frecuencia (meses), descripción, finalidad simbólica, orden, si aparece destacado y si está activo. Los textos iniciales son generales a propósito: **revisalos y adaptalos**; no prometen beneficios que la organización no haya definido. Cambiar el importe de un nivel no modifica las suscripciones ya creadas (cada una guarda el importe con el que se creó).

Funcionamiento técnico:

1. `/donar/mensual/<nivel>/` pide el email de la cuenta de Mercado Pago del donador y la aceptación del débito.
2. Se crea `Subscription` y una suscripción **sin plan con pago pendiente** (`POST /preapproval`, `status: "pending"`). El importe sale del nivel en la base, nunca del formulario.
3. Se redirige a `init_point`, donde el donador elige el medio de pago y autoriza.
4. Mercado Pago vuelve a `/donar/suscripcion/<referencia>/`, que consulta el estado real.
5. Estados: *Pendiente de autorización* (`pending`), *Activa* (`authorized`), *Pausada* (`paused`), *Cancelada* (`cancelled`).
6. Cada cobro mensual llega como `subscription_authorized_payment` y se guarda en `SubscriptionPayment`.
7. **Cancelación:** *Mi actividad → Cancelar* → confirmación → `PUT /preapproval/{id}` con `status: "cancelled"` → se vuelve a consultar y se actualiza la base. Si Mercado Pago falla, la suscripción local no cambia.

## Webhooks

Endpoint: `POST /donar/webhooks/mercadopago/` (exento de CSRF; se autentica con firma).

Por cada notificación:

1. **Valida la firma** `x-signature` con `MERCADOPAGO_WEBHOOK_SECRET` usando el validador oficial del SDK (HMAC-SHA256 sobre `id:<data.id>;request-id:<x-request-id>;ts:<ts>;`). Firma inválida → **401**.
2. **Identifica** el tópico (`type`/`topic`) y el ID (`data.id`).
3. **Registra** el evento en `WebhookEvent` con una clave única (tópico + recurso + acción + id + `x-request-id`). Si esa misma notificación ya se procesó, responde 200 sin volver a procesar.
4. **Consulta el recurso en la API** de Mercado Pago (nunca confía en el cuerpo de la notificación):

| Tópico | Consulta | Actualiza |
|---|---|---|
| `order` | `GET /v1/orders/{id}` | `OneTimeDonation` (+ progreso de la necesidad) |
| `subscription_preapproval` | `GET /preapproval/{id}` | `Subscription` |
| `subscription_authorized_payment` | `GET /authorized_payments/{id}` | `SubscriptionPayment` |
| `payment` | `GET /v1/payments/{id}` | Respaldo: vuelve a consultar la orden o registra el cobro de la suscripción |

5. Si la API de Mercado Pago falla, responde **500** para que Mercado Pago reintente. Recursos que no son de este sitio se marcan como *ignorados* y se responde 200.

Idempotencia: además del registro de eventos, toda actualización usa `select_for_update` y se basa en el estado consultado; el aporte a la necesidad es un `OneToOne`, por lo que repetir la misma notificación nunca duplica dinero.

**Respaldo:** `python manage.py sincronizar_mercadopago` revisa donaciones y suscripciones no finalizadas de los últimos 30 días (`--dias N`). Se recomienda programarlo (cron / Programador de tareas) cada hora. También existe la acción *"Verificar estado en Mercado Pago"* en el admin.

Las notificaciones recibidas se ven en *Administración → Notificaciones de Mercado Pago*.

## Base de datos

Migraciones nuevas (no destructivas, no borran ni renombran columnas):

- `communities/0003`: `Community.location`, `Community.is_featured`, modelo `CommunityImage`, categorías `Agua` y `Ropa`.
- `communities/0004`: copia la imagen existente de cada comunidad a la galería (apunta al mismo archivo; no se mueven archivos).
- `donations/0001`: modelos de donaciones.
- `donations/0002`: 4 niveles de donador.

```
Usuario ─┬─< OneTimeDonation ── mp_order_id (Orden MP) ──1:1── communities.Donation (aporte a la necesidad)
         │        └── community / need (opcionales)
         └─< Subscription ── mp_preapproval_id ─< SubscriptionPayment (cobros recurrentes)
                 └── tier → DonorTier
WebhookEvent: registro/auditoría de notificaciones
```

| Modelo | Datos principales |
|---|---|
| `DonorTier` | nombre, slug, importe, frecuencia, descripción, finalidad, orden, destacado, activo |
| `OneTimeDonation` | referencia (UUID), usuario, comunidad, necesidad, importe, moneda, estado, `mp_order_id`, estado y detalle MP, `mp_payment_id`, medio y tipo de pago, fechas (creada, aprobada, última verificación) |
| `Subscription` | referencia, usuario, nivel (+ copia de nombre e importe), email de MP, estado, `mp_preapproval_id`, próximo cobro, inicio, cancelación |
| `SubscriptionPayment` | ID del cobro y del pago de MP, importe, estados, fecha de débito |
| `WebhookEvent` | tópico, acción, recurso, `x-request-id`, contenido, resultado, intentos |

**No se guarda ningún dato de tarjeta**: Mercado Pago gestiona los medios de pago. Solo se guardan identificadores, importes y estados.

Antes de migrar se creó una copia de respaldo: `db.backup-antes-mercadopago.sqlite3`.

## Imágenes de las comunidades

*Administración → Comunidades → (elegir comunidad)*:

- **Agregar fotos a la galería:** seleccioná varias fotos a la vez; se ven en vista previa antes de guardar.
- **Galería de fotos:** cada foto muestra miniatura, descripción breve (texto alternativo y epígrafe), **orden** y casilla **Principal** (portada). Solo puede haber una principal: al marcar otra, la anterior se desmarca. Si se borra la principal, la siguiente pasa a serlo.
- **Eliminar:** casilla *Eliminar* de cada fila. El archivo se borra del disco salvo que otro registro lo use (las fotos migradas comparten archivo con el campo anterior).
- Tamaño máximo por foto: `COMMUNITY_IMAGE_MAX_MB` (8 MB por defecto). Las fotos se guardan en `media/communities/<id>/`.
- El campo anterior *Imagen* / *URL de imagen* sigue funcionando como respaldo si una comunidad no tiene galería.

En el sitio, la página de cada comunidad muestra la foto principal grande, miniaturas debajo y un visor ampliado (lightbox) con flechas, teclado y deslizamiento en celulares.

## Comunidad destacada y prioridad de necesidades

El inicio muestra arriba **"La comunidad que más necesita tu ayuda"** y debajo un carrusel con las demás (solución híbrida). El orden se calcula en `communities/priority.py` **solo con datos que ya se cargan**:

```
puntaje de una necesidad activa =
    1                              (por estar activa)
  + 3                              (si está marcada como urgente)
  + peso de la categoría           (Alimentos/Agua/Salud 2, Educación/Vivienda/Ropa 1, Otro 0)
  + 2 × fracción que falta cubrir  (0 si ya se recaudó todo)
puntaje de la comunidad = suma de sus necesidades activas
```

Los pesos se ajustan en `settings.NEED_PRIORITY_WEIGHTS`. El puntaje se ve en el admin (columna *Prioridad*).

**Qué debe cargar el administrador** para que el cálculo sea representativo:

- Cada necesidad con su **categoría** correcta y su **monto objetivo**.
- Marcar **Urgente** solo lo realmente urgente.
- Pasar a **Completada** las necesidades cubiertas (aparecen como "Necesidad cubierta" en verde) y a **Cancelada** las que ya no aplican.
- Completar la **ubicación general** de la comunidad.
- Opcional: **Destacar en el inicio** fuerza una comunidad arriba (tiene prioridad sobre el cálculo automático).

Indicadores: 🔴 urgente · 🟠 activa · 🟢 cubierta.

## Redes sociales

Botones de **Instagram** y **Facebook** en el pie de todas las páginas y en la sección *"Seguinos en nuestras redes"* del inicio. Abren en pestaña nueva. URLs configurables con `SOCIAL_INSTAGRAM_URL` y `SOCIAL_FACEBOOK_URL`.

## Pruebas

### Tests automáticos (sin dinero real ni llamadas a Mercado Pago)

```bash
python manage.py test
```

47 tests que usan un gateway falso de Mercado Pago y cubren: donación aprobada, rechazada, pendiente; que volver del checkout con `?status=approved` **no** aprueba; importes manipulados; límites; CSRF; permisos entre usuarios; webhooks con firma válida/inválida; duplicados; reintentos ante error de la API; importe inconsistente; reembolso; suscripción creada, activada, cobros, cancelación y errores; galería, foto principal, subida múltiple en el admin; prioridad; login con `next`.

### Prueba manual con Mercado Pago (modo prueba)

1. Configurá `.env` con credenciales de prueba, túnel HTTPS y webhooks (ver arriba).
2. Iniciá sesión en el sitio y andá a una comunidad → **Quiero ayudar → Donación única**.
3. Pagá con la cuenta compradora de prueba y tarjeta de prueba:
   - Titular `APRO` → debe verse **DONACIÓN APROBADA** y en el admin la orden con su ID.
   - Titular `OTHE` → **DONACIÓN RECHAZADA**.
   - Titular `CONT` → **DONACIÓN PENDIENTE**.
4. Verificá en *Admin → Notificaciones de Mercado Pago* que llegó el webhook `order` y que el estado de la donación coincide. Desde el panel de Webhooks de Mercado Pago se puede **simular** una notificación para probar la recepción.
5. **Suscripción:** *Donación mensual → nivel → email de la cuenta compradora de prueba → Autorizar*. Al volver: *SUSCRIPCIÓN ACTIVA* (puede pasar unos segundos por *pendiente*). En *Mi actividad* aparece con próximo cobro.
6. **Cancelación:** *Mi actividad → Cancelar → Sí, cancelar*. Debe quedar *Cancelada* en el sitio y en Mercado Pago.
7. **Duplicados:** reenviá la misma notificación desde el panel de MP; el aporte en la necesidad no debe duplicarse.

## Producción

- Variables: `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL=https://...`, credenciales y clave de webhooks de producción.
- `python manage.py collectstatic` y servir `/static/` y `/media/` con el servidor web (con `DEBUG=False` Django no sirve `media/`).
- HTTPS obligatorio (Mercado Pago lo exige para webhooks y retorno automático). Con `DEBUG=False` las cookies de sesión y CSRF se marcan como seguras.
- Programar `python manage.py sincronizar_mercadopago` cada hora.
- Considerar PostgreSQL si crece el tráfico.

## Seguridad

- Credenciales solo en variables de entorno (`.env` excluido de git).
- Importes calculados y validados en el servidor; el de las suscripciones sale de la base. Al confirmar, se compara el importe de la orden con el registrado.
- Estados confirmados siempre con la API de Mercado Pago (retorno del navegador y cuerpo del webhook no se usan como fuente de verdad).
- Webhooks con firma HMAC, deduplicación y transacciones con bloqueo de fila.
- CSRF activo en todos los formularios; el webhook es la única vista exenta.
- Cada donador solo puede ver y cancelar lo suyo (403 en otro caso).
- Redirección a checkout solo hacia dominios de Mercado Pago; `next` del login solo a URLs del propio sitio.
- Consultas mediante el ORM (sin SQL manual) y autoescape de templates (sin `|safe` en datos de usuarios).
- El endpoint anterior que registraba donaciones sin pago (`/comunidades/necesidades/<id>/donar/`) quedó restringido al personal administrativo, para registrar aportes recibidos fuera de la plataforma.
