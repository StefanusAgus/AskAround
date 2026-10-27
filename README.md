# AskAround

A conversational place-discovery project. Its FastAPI service exposes three
Google Places API (New) operations:

- Text Search resolves postcodes, addresses, landmarks, and text queries.
- Nearby Search finds points of interest around known coordinates.
- Place Details retrieves richer information for a selected place ID.

## Setup

1. In Google Cloud, enable **Places API (New)** and create a server-side API
   key. Restrict the key to Places API (New) and, for deployment, to the
   backend's IP addresses.
2. Install dependencies:

   ```powershell
   uv sync
   ```

3. Set the API key for the current PowerShell session:

   ```powershell
   $env:GOOGLE_MAPS_API_KEY = "your-api-key"
   ```

4. Start the API:

   ```powershell
   uv run python main.py
   ```

Open `http://127.0.0.1:8000/docs` to test both endpoints interactively.

## Examples

Find the top three candidates for a postcode or address:

```powershell
$body = @{ query = "018956 Singapore"; max_results = 3 } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/places/search `
  -ContentType "application/json" `
  -Body $body
```

Use an `id` from the search response to retrieve place details:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/places/PLACE_ID
```

Find restaurants and cafes within 750 metres of a coordinate, ordered by
distance:

```powershell
$body = @{
  latitude = 1.2834
  longitude = 103.8607
  radius_meters = 750
  included_types = @("restaurant", "cafe")
  max_results = 10
  rank_preference = "DISTANCE"
  region_code = "SG"
} | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/places/nearby `
  -ContentType "application/json" `
  -Body $body
```

Run automated tests without making live Google API requests:

```powershell
uv run pytest
```

Google bills Places API requests according to the highest SKU associated with
the requested fields. The field masks are intentionally explicit in
`app/constants.py`; review them before adding fields.

## Locale defaults and place types

Every Google Places request sends `languageCode=en` and `regionCode=SG` by
default. The region is important because Google uses it when formatting and
selecting results. Callers can override either value when another locale is
required.

`app/constants.py` contains Google's Place Types (New), grouped according to
the official categories:

- `GOOGLE_PLACE_TYPES_BY_CATEGORY` documents the filterable Table A types.
- `GOOGLE_PLACE_FILTER_TYPES` provides a flat set used for request validation.
- `GOOGLE_PLACE_RESPONSE_ONLY_TYPES` documents Table B types that may be
  returned by Google but are invalid Nearby Search and Text Search filters.

Google updates these types periodically. Compare the constants with the
[official Place Types documentation](https://developers.google.com/maps/documentation/places/web-service/place-types)
when upgrading the integration.
