# SPIR → BOM Working Template converter

Web tool that converts a **SPIR extraction** Excel file into the **BOM WORKING TEMPLATE** workbook
(Dukhan template or Other-than-Dukhan template), following the rules in [`docs/logic/`](docs/logic).

* **Frontend** – React + TypeScript (Vite), served by nginx
* **Backend** – Python 3.12, FastAPI, SQLAlchemy 2, openpyxl
* **Database** – PostgreSQL 16

User flow: select **Plant type** (Dukhan / Other) → optionally select **Maintenance planning plant** →
upload the SPIR extraction (.xlsx) → download the filled template. Every conversion (input + output file)
is kept in the history, visible to all users. There is no admin screen.

---

## 1. Run with Docker (recommended)

```bash
cp .env.example .env          # change POSTGRES_PASSWORD
docker compose up -d --build
```

Open **http://localhost:8080** (port set by `APP_PORT`). API docs: **http://localhost:8080/api/docs**.

### Users (sign-in)

Everyone must sign in. There is no admin screen – users are managed from the command line:

```bash
docker compose exec backend python -m app.manage create-user jsmith --email j.smith@example.com --name "John Smith"
docker compose exec backend python -m app.manage set-password jsmith
docker compose exec backend python -m app.manage disable-user jsmith    # signs the user out everywhere
docker compose exec backend python -m app.manage enable-user jsmith
docker compose exec backend python -m app.manage list-users
```

Sign in with the username or the e-mail. A session lasts 12 hours, or 30 days with **Remember this device**.
The history records the signed-in user's name. Set `COOKIE_SECURE=true` when the app is served over HTTPS.

## 2. Run locally (development)

```bash
# PostgreSQL: create an empty database, e.g.  createdb bom
cd backend
python -m venv .venv 
 .venv/bin/activate      # Windows: .venv\Scripts\activate
 python -m pip install --upgrade pip
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/bom
uvicorn app.main:app --reload --port 8000             # API docs: http://localhost:8000/api/docs

cd ../frontend
npm install
npm run dev                                            # http://localhost:5173 (proxies /api to :8000)
```

Tables are created automatically at start-up; plants and country codes are seeded at the same time.

## 3. Plant dropdown – `backend/app/resources/plants.json`

```json
[
  { "plant_type": "DUKHAN", "code": "DK01", "name": "Dukhan" },
  { "plant_type": "OTHER",  "code": "OT01", "name": "Other plant 1" }
]
```

* `plant_type` = `DUKHAN` or `OTHER` (decides the template), `code` = IWERK (max 4 characters).
* **The shipped codes are placeholders – replace them with your real plants**, then restart the backend
  (`docker compose restart backend`). Plants removed from the file disappear from the dropdown but stay in the history.

## 4. Material Temp Number

| Item | Dukhan | Other plants |
|---|---|---|
| Equipment (B) | next number from **40001** | SAP NUMBER if present, else next from **40001** |
| Spare (L) | next number from **500001** | SAP NUMBER if present, else next from **500001** |

* Numbers **continue across uploads** and are kept **per plant** (`NUMBERING_SCOPE=plant`); Dukhan has its own
  running sequence. With no planning plant selected, the sequence of the plant type is used.
  Set `NUMBERING_SCOPE=plant_type` for one sequence for Dukhan and one shared by all other plants.
* The same equipment tag / material (SAP no., else SPF no.) **keeps the same number** when uploaded again.
* Allocation locks the sequence row in PostgreSQL, so simultaneous uploads never get the same number.
* Start values: `EQUIPMENT_START`, `SPARE_START` in `.env`.

## 5. Conversion rules implemented

Input: first sheet, row 1 = headers, rows 2–3 (SAP field codes / lengths) skipped, data from row 4.
Columns are matched by name (case / spacing ignored); a clear error lists any missing column.

**Rows** – a row with `EQPT QTY` and no `QUANTITY IDENTICAL PARTS FITTED` is an equipment header.
Each TAG NO becomes **one** equipment line (B) even if it is repeated in several input sheets, followed by all
its spares (L) in input order.

| Output column | Rule |
|---|---|
| SERIAL NUMBER | 1, 2, 3 … |
| SAP MATERIAL NUMBER *(Dukhan)* | SAP NUMBER |
| MATERIAL TEMP NUMBER | see §4 |
| MATERIAL TYPEVCATEGORY | B = equipment, L = spare |
| OLD MATERIAL NUMBER/SPF NUMBER | OLD MATERIAL NUMBER/SPF NUMBER |
| MATERIAL DESCRIPTION | NEW DESCRIPTION OF PARTS (equipment: DESCRIPTION OF PARTS) |
| LEN(…) columns | live `=LEN()` formula of the column on the left |
| MAINTENANCE PLANNING PLANT | selected plant code, empty if not selected |
| BASE UNIT OF MEASURE | code part of UNIT OF MEASURE (`NO - NUMBERS` → `NO`) |
| MANUFACTURERS PART NUMBER | MANUFACTURER PART NUMBER; if longer than 35 → first 35 chars here, full value in CDC_ADD INFORMATION |
| MANUFACTURER NAME | SUPPLIER/ OCM NAME |
| MATERIAL IS AN EQUIPMENT INDICATOR | YES / NO |
| BOM HEADER NUMBER | temp number of the equipment the line belongs to |
| QUANTITY | EQPT QTY (equipment) / QUANTITY IDENTICAL PARTS FITTED (spare) |
| POSITION NUMBER | POSITION NUMBER |
| CDC_SPIR NUMBER | SPIR NO without revision (`…-0003-REV-A` → `…-0003`) |
| DELIVERY TIME IN WEEKS | DELIVERY TIME IN WEEKS |
| MANUFACTURER COUNTRY CODE | VENDOR COUNTRY looked up in the country reference (T005) |
| MM REQUIREMENT MOVING AVERAGE PRICE | UNIT PRICE (QAR) |
| REORDER POINT (MIN) / MAX STOCK LEVEL | MIN MAX STOCK LVLS QTY: single digit (0–9) → MIN; more digits (12, 120) → MAX; two values (`1/3`) → MIN 1, MAX 3 |
| MANUFACTURER COUNTRY NAME | VENDOR COUNTRY |
| CURRENCY CODE REF | code part of CURRENCY (`QAR - QATAR RIYAL` → `QAR`) |
| All other columns | left empty, as specified |

**SPIR TAG vs SUBMT** – one row per equipment tag: EQFNR = TAG NO, SUBMT = equipment temp number,
SPIR NO / REV split from SPIR NO, HERST = SUPPLIER/ OCM NAME, TYPBZ = EQPT MODEL, MAPAR = MANUFACTURER PART NUMBER
(empty for equipment rows), SERGE = EQPT SR NO, SPIR TYPE (column inserted before REMARKS with the same header
style), REMARKS empty.

**Template formatting** – the template files are filled value-by-value; header colours, fonts, borders, widths and
the template's own conditional formatting are not changed (covered by a test). In the data rows every cell that
gets a value has a thin border and empty cells have none. The header block is frozen (rows 1–5 on the BOM sheet,
rows 1–2 on the tag sheet). Checks such as "description longer than 40" or "country not found" are shown as
**warnings in the app**, not as colours in the file.

## 6. API

| Method | Path | |
|---|---|---|
| GET | `/api/plant-types` | DUKHAN / OTHER |
| GET | `/api/plants?plant_type=DUKHAN` | planning plants for the dropdown |
| POST | `/api/jobs` | multipart: `plant_type`, `plant_id` (optional), `user_name` (optional), `file` |
| GET | `/api/jobs?limit=&offset=&search=` | history |
| GET | `/api/jobs/{id}/output` · `/input` | download files |
| GET | `/api/health` | health check |

## 7. Tests

```bash
cd backend
createdb bom_test                                   # EMPTY database – it is wiped by the tests
export TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/bom_test
pytest -q
```

`tests/test_logic.py` (no DB) checks every rule against the sample SPIR in `tests/fixtures/` and that template
colours are unchanged; `tests/test_api.py` checks numbering continuity per plant, re-use of numbers, concurrent
uploads and validation errors.

## 8. Project structure

```
backend/app/
  main.py                FastAPI app, start-up seeding
  models.py              plants, country_codes, number_sequences, material_numbers, conversion_jobs
  seed.py                plants.json + country reference loader
  services/input_reader.py   read SPIR extraction
  services/bom_builder.py    all business rules (pure python)
  services/numbering.py      temp-number allocation in PostgreSQL
  services/excel_writer.py   fill the template without touching styles
  services/converter.py      one conversion end-to-end + history record
  resources/             the two templates, country reference, plants.json
frontend/src/            App.tsx (screen), api.ts, types.ts, styles.css
docs/logic/              the original logic documents
```

## 9. Replacing templates or the country list

Replace the files in `backend/app/resources/` keeping the same file names. Headers are matched by name, so
column order may change. After replacing `COUNTRY_REFERENCE.xlsx`, empty the `country_codes` table
(`DELETE FROM country_codes;`) and restart the backend to reload it.
