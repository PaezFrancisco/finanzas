# Wallet Sync (email → gastos)

Aplicación en Python que se conecta a tu correo por **IMAP**, detecta avisos de **Santander** y **ARQ** (antes DolarApp), extrae montos y metadatos, y los exporta a **CSV** para importarlos en tu app de finanzas (“wallet”). Incluye **deduplicación** local (SQLite) para no cargar dos veces el mismo gasto.

> Los formatos exactos de los mails cambian por país y campaña. Debes revisar **uno o dos correos reales** y ajustar los regex en `wallet_sync/parsers/` si hace falta.

## Requisitos

- Python 3.11+
- Acceso IMAP a tu buzón (Gmail, Outlook, etc.)
- Para Gmail: una [contraseña de aplicación](https://support.google.com/accounts/answer/185833), no la contraseña normal si tienes 2FA.

## Instalación

```bash
cd finanzas
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

Edita `.env` con host, usuario y contraseña IMAP. Edita `config.yaml` con palabras clave de remitente que veas en tus mails de Santander y ARQ.

## Uso

Desde la raíz del proyecto:

```bash
python -m wallet_sync sync
```

Verás en consola el flujo: archivo de config, parsers, conexión IMAP, cuántos mensajes hay en la ventana de fechas, cada gasto nuevo y un resumen final.

- **Más detalle** (cada UID, asunto, duplicados): `python -m wallet_sync sync -v`
- **Solo avisos/errores**: `python -m wallet_sync sync -q`
- **Nivel por entorno**: `WALLET_LOG_LEVEL=DEBUG` en `.env`

- Genera o actualiza `data/gastos_wallet.csv` (columnas: `fecha`, `monto`, `moneda`, `comercio`, `descripcion`).
- Estado de importación: `data/sync_state.db` (no lo subas a git si quieres privacidad; ya está ignorado en `.gitignore` vía `data/`).

La ruta del CSV se define en `wallet.csv_path` dentro de `config.yaml`.

Tras cada exportación con gastos nuevos, la consola muestra un **resumen de ARS por día** (separando ARQ y Santander) para que puedas cruzar cada fecha con los **USD** que convertiste en la app ARQ y cargarlos en tu cuenta USD de la wallet.

## ARQ: cuenta USD vs monto en ARS en el mail

En **ARQ** el aviso suele mostrar la operación en **pesos**, aunque tú hayas usado **dólares** convertidos. En la app wallet con dos cuentas (USD y ARS), lo coherente es:

1. **Mantener en el CSV** `monto` y `moneda` tal como vienen en el mail (hecho comprobable del aviso).
2. Indicar en **`descripcion`** que el cargo debe imputarse a la cuenta **USD** (u otra que uses).

En `config.yaml`, bajo `sources.arq` (o `sources.dolarapp` si aún tenés un yaml antiguo):

- `wallet_impute_currency: USD` — activa un texto por defecto en la descripción que deja explícito “imputar en saldo USD” y repite el importe del mail en ARS.
- `wallet_impute_description_template` (opcional) — plantilla propia. Placeholders: `{wallet_currency}`, `{amount}`, `{currency}`, `{merchant}`, `{description}`.

Si borras `wallet_impute_currency` o lo dejas vacío, no se antepone nada (solo la descripción del parser).

**Tipo de cambio / API de ARQ:** el rebranding a ARQ no implica una API pública documentada para cotización por fecha (acceso suele ser la app). Para convertir ARS→USD con un tipo de mercado podés ampliar el proyecto con una fuente externa (p. ej. APIs de cotización argentinas); **no** es lo mismo que el “tipo” interno del día en ARQ.

Para **descontar en USD un importe distinto** al ARS del mail, tendrías que ajustarlo a mano en la wallet o ampliar con un tipo de cambio configurable en config.

## Conectar con tu “wallet”

Muchas apps (Wallet de Apple, bancos propios, etc.) **no ofrecen API pública**. El flujo más seguro y portable es:

1. Exportar CSV desde este proyecto.
2. Importar manualmente o mediante la función “Importar CSV” de tu app, si existe.

Si más adelante tu app expone una API REST propia, puedes añadir un `WalletSink` en `wallet_sync/sinks/` que haga `POST` con los campos de `Expense`.

## Filtros (por correo real)

- **`imap_from_hints`**: el servidor IMAP solo trae mensajes cuyo `From` contiene esas cadenas (p. ej. `dolarapp.com`, `santander.com.ar`). Menos ruido y menos descargas.
- **`from_contains` / `subject_contains`**: cada parser solo procesa si el remitente y el asunto encajan (p. ej. `enviaste` para ARQ, `aviso de transferencia` para Santander).

Los mails HTML (p. ej. Santander) se convierten a texto plano antes de leer montos.

## Transferencias propias ARQ → Santander

Si mandás **pesos** desde ARQ a tu **cuenta Santander** (mismo titular), es un movimiento entre cuentas, no un gasto extra. En `sources.arq.self_transfer` podés activar `enabled: true` y listar **`match_hints`**: palabras que aparezcan en el destinatario o en el cuerpo del mail (por ejemplo `santander`, parte de tu CBU, o tu nombre si figurás como beneficiario). Esos avisos **no se escriben en el CSV** pero **sí se marcan como procesados** para no repetirlos.

Opcionalmente, `sources.santander.self_transfer` con `match_hints` (p. ej. `arq`, `dolarapp`) para **omitir** el aviso de Santander del mismo movimiento si no querés duplicar contabilidad.

## Afinar los parsers

1. Reenvía un mail de ejemplo a ti mismo o ábrelo en “ver origen” y copia el **cuerpo de texto**.
2. Edita `wallet_sync/parsers/santander.py` o `arq.py`:
   - `from_contains` / `subject_contains` en `config.yaml` deben coincidir con el remitente/asunto.
   - Ajusta `extract_money_ar` / `parse_amount_flexible` en `email_client.py` si el formato cambia.

## Automatizar (cron)

Ejemplo cada día a las 8:00 (macOS/Linux, ajusta rutas):

```cron
0 8 * * * cd /ruta/a/finanzas && /ruta/a/finanzas/.venv/bin/python -m wallet_sync sync >> /tmp/wallet_sync.log 2>&1
```

## Estructura del repositorio

```
wallet_sync/
  __main__.py       # python -m wallet_sync
  cli.py            # Click: subcomando sync
  config.py         # .env + YAML
  email_client.py   # IMAP + extracción de montos
  models.py         # Expense
  storage.py        # Dedup SQLite
  sync.py           # Orquestación
  parsers/          # Santander, ARQ (arq.py)
  sinks/            # CSV
  wallet_export.py  # reglas de descripción (p. ej. cuenta USD en ARQ)
  post_export.py    # resumen ARS por día tras el CSV (cruce con USD en ARQ)
  self_transfer.py  # omitir transferencias propias (p. ej. ARQ → Santander)
```

## Seguridad

- **No subas** `.env` ni bases `data/*.db` con datos personales a GitHub.
- Usa contraseñas de aplicación y restringe el acceso al repo.

## Licencia

Uso personal; añade la licencia que prefieras al publicar el repo.
