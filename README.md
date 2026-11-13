# MLS Listing Search API

A Flask REST API that loads property listings from two mock MLS feeds, cleans up their formatting,
and serves search, filtering, ranking, pagination, and CRUD for a real-estate frontend.

- **Docs:** <http://127.0.0.1:5000/docs> (Swagger UI), spec at `/openapi.json`
- **Data:** `data/listings.json`, 80 sample listings from `MLS_A` and `MLS_B`

## Quick start

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

flask --app wsgi run --debug    # http://127.0.0.1:5000
pytest --cov=app                # tests
```

Production: `gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 wsgi:app`. Use one worker, because the data
lives in memory.

**Environment variables:** `LISTINGS_DATA_FILE` (default `data/listings.json`), `LISTINGS_PERSIST`
(save changes back to the file, default `false`), `DEFAULT_PAGE_SIZE` (20), `MAX_PAGE_SIZE` (100),
`CORS_ORIGINS` (`*`), `REFERENCE_DATE` (fixed "today" for demos, e.g. `2026-10-23`).

## Endpoints

| Method   | Path                             | Description                         |
|----------|----------------------------------|-------------------------------------|
| `GET`    | `/api/v1/listings`               | Search, filter, rank, paginate      |
| `POST`   | `/api/v1/listings`               | Create a listing                    |
| `GET`    | `/api/v1/listings/{source}/{id}` | Get one listing                     |
| `PUT`    | `/api/v1/listings/{source}/{id}` | Replace a listing                   |
| `PATCH`  | `/api/v1/listings/{source}/{id}` | Partial update                      |
| `DELETE` | `/api/v1/listings/{source}/{id}` | Delete                              |
| `GET`    | `/api/v1/locations`              | States/cities/ZIPs for dropdowns    |
| `GET`    | `/api/v1/health`                 | Health check                        |

Listings are addressed by `{source}/{id}` because ids are only unique within a feed.

### Search parameters

All optional. Different parameters are combined with AND. `city`, `state`, `zip`, `status` and
`source` accept comma-separated values, combined with OR.

| Param          | Example            | Notes                                              |
|----------------|--------------------|----------------------------------------------------|
| `minPrice`     | `300000`           | Inclusive                                          |
| `maxPrice`     | `700000`           | Inclusive                                          |
| `minBedrooms`  | `3`                | Inclusive                                          |
| `city`         | `Austin,Round Rock` | Case-insensitive                                  |
| `state`        | `TX` or `texas`    | Code or full name                                  |
| `zip`          | `78704`            |                                                    |
| `keyword`      | `pool renovated`   | Every word must appear in the description          |
| `status`       | `active,pending`   | `active`, `pending`, `sold`                        |
| `source`       | `MLS_A`            |                                                    |
| `targetBudget` | `500000`           | Turns on budget scoring                            |
| `sort`         | `relevance`        | `relevance` (default), `price_asc`, `price_desc`, `newest` |
| `page`         | `1`                | 1-based                                            |
| `pageSize`     | `20`               | 1–100                                              |

**Response** (trimmed):

```json
{
  "data": [
    {
      "id": "1036", "source": "MLS_B", "city": "Round Rock", "state": "TX", "zip": "78681",
      "price": 399000, "bedrooms": 3, "listedDate": "2026-10-10", "status": "sold",
      "rank": 1,
      "relevanceScore": 0.8166,
      "scoreBreakdown": { "budget": 0.8672, "recency": 0.7405 }
    }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalItems": 23, "totalPages": 2,
                  "hasNext": true, "hasPrevious": false },
  "query": { "city": ["Austin", "Round Rock"], "targetBudget": 450000.0, "sort": "relevance" }
}
```

### Errors

All errors use the same shape and list every invalid field:

```json
{ "error": { "status": 400, "code": "validation_error", "message": "Invalid search parameters.",
             "details": [ { "field": "minPrice", "message": "must be less than or equal to maxPrice" } ] } }
```

Codes: `400` validation error, `404` not found, `405` wrong method, `409` duplicate on create,
`413` body too large, `415` not JSON, `500` internal error. Unknown query parameters (e.g. the
typo `minprice`) return a 400.

## Scoring

Each result gets a `relevanceScore` from 0 to 1 (`app/scoring.py`):

```
with targetBudget:     score = 0.6 · budgetFit + 0.4 · recency
without targetBudget:  score = recency

budgetFit = 0.5 ^ ((d / tol)²)     d = (price − target) / target
                                   tol = 0.10 if over budget, 0.25 if under
recency   = 0.5 ^ (ageDays / 30)
```

- **Budget fit uses the percentage difference**, because $50k matters more on a $300k budget than on
  a $2M one.
- **Over budget is penalized more than under.** The score halves at 10% over budget but only at 25%
  under, since buyers are less willing to stretch up.
- **Recency halves every 30 days**, so new listings rise to the top.
- **Budget is weighted higher (60%)** because it's what the user asked for. Recency mostly breaks
  ties between similarly priced homes.
- **Filters don't affect the score.** They only decide which listings are included.

**Example** with `targetBudget=450000` and today = `2026-10-23`:

| Price    | Age     | budgetFit | recency | score | rank |
|----------|---------|-----------|---------|-------|------|
| $399,000 | 13 days | 0.87      | 0.74    | 0.82  | 1    |
| $450,000 | 60 days | 1.0       | 0.25    | 0.70  | 2    |
| $630,000 | 0 days  | ≈0        | 1.0     | 0.40  | 3    |

The brand-new listing ranks last because it's 40% over budget.

## Ranking

1. Filter the listings.
2. Score each match.
3. Sort by `sort`. For `relevance`, the order is highest score first, then newest, then lowest price,
   then `(source, id)`. The last key is unique, so the order is the same on every request and
   paging never repeats or skips a listing.
4. Return the requested page. `rank` is the position across all pages, so the first item on page 2
   (`pageSize=20`) has rank 21.

## Data cleanup

The two feeds format fields differently, so each record is normalized when it's loaded or written
(`app/normalize.py`):

| Field   | Feed values                           | Stored as  |
|---------|---------------------------------------|------------|
| `city`  | `"austin"`, `" AUSTIN "`              | `"Austin"` |
| `state` | `"Texas"`, `"tx"`, `"T.X."`           | `"TX"`     |
| `zip`   | `"78704-2231"`, `2134`                | `"78704"`, `"02134"` |
| `price` | `"$525,000"`, `"525000.00"`           | `525000`   |

Bad records in the data file are skipped and logged. Bad input sent through the API gets a 400.

## Trade-offs and next steps

- **In-memory store backed by a JSON file.** This is simple and fast for the sample data. With more
  data, or more than one server process, I'd move to SQLite or Postgres.
- **Simple keyword matching.** All words must appear, matched by word prefix, so `pool` matches
  "pools". There's no stemming or typo tolerance, and keywords don't affect the score. A search
  engine would add those.
- **No de-duplication across feeds.** The same house listed on both feeds appears twice.
- **Sold and pending listings are included** unless you filter with `status=active`.

## Project layout

```
app/
  routes.py       endpoints
  search.py       query parsing, filtering, sorting, pagination
  scoring.py      relevance score
  repository.py   in-memory store + JSON file
  normalize.py    field cleanup
  models.py       Listing model + validation
  errors.py       error handling
  docs.py         OpenAPI spec + Swagger UI
data/listings.json
tests/
```

## Try it

```bash
B=http://127.0.0.1:5000/api/v1

curl "$B/listings?city=austin"
curl "$B/listings?state=Texas&minBedrooms=3"
curl "$B/listings?minPrice=300000&maxPrice=600000"
curl "$B/listings?keyword=pool&status=active"
curl "$B/listings?targetBudget=450000"
curl "$B/listings?targetBudget=450000&sort=price_asc&page=2&pageSize=5"

curl -i -X POST "$B/listings" -H 'Content-Type: application/json' -d '{
  "id":"X1","source":"MLS_C","address":"1 Test Way","city":"austin","state":"texas",
  "zip":"78701","price":"$449,000","bedrooms":3,"bathrooms":2,"sqft":1700,
  "latitude":30.27,"longitude":-97.74,"listedDate":"2026-10-23","status":"active",
  "description":"Brand new with a pool"}'
curl -X PATCH "$B/listings/MLS_C/X1" -H 'Content-Type: application/json' -d '{"status":"pending"}'
curl -X DELETE -i "$B/listings/MLS_C/X1"
```
