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
   $env:OPENROUTER_API_KEY = "your-openrouter-key"
   # Optional; defaults to openai/gpt-4.1-mini
   $env:OPENROUTER_MODEL = "openai/gpt-4.1-mini"
   ```

4. Start the API:

   ```powershell
   uv run python main.py
   ```

Open `http://127.0.0.1:8000/docs` to inspect and test the API routes.

## Agent API

`POST /agent/chat` runs the AskAround manager through OpenRouter using the
OpenAI Agents SDK. It remains the conversational entry point and can either
answer directly or invoke one Places Specialist agent as a tool. There is no
separate routing-model request.

The specialist receives the complete place-discovery request and can chain:

- Google Places Text Search to resolve postcodes, addresses, and landmarks.
- Nearby Search to find points of interest around resolved coordinates.

The specialist's first action is forced to be a real Google tool call. If the
manager returns a progress-only message such as "Calling the tool" without
emitting a tool call, or returns an empty/null-like answer, the application
removes that incomplete response and retries once with `places_agent` forced.
The same recovery applies when the manager explicitly expresses tool intent in
its streamed reasoning or sets its structured `needs_places_tool` fallback.
After the tool executes, the manager can synthesize normally. Generic answers
do not require a tool call.

The specialist infers an ISO two-letter region code when the user provides a
clear country or region hint. For example, `Paris, France` uses `FR`. If the
region is missing, ambiguous, or malformed by the model, the per-request agent
context defaults to Singapore (`SG`). Response language remains English.

The response is a Server-Sent Events stream so callers can observe both the
manager and nested specialist run as they happen. The stream emits:

- `agent_thinking` with concise manager or specialist reasoning.
- `tool_call` with the tool name, input, and parsed parameters.
- `tool_output` with the parsed tool result.
- `agent_output` with the specialist's structured output.
- `agent_completed` with the validated `AgentAnswer` output.
- `agent_error` with a clear exception type and message if the run fails.

Test the streaming endpoint from PowerShell:

```powershell
curl.exe -N `
  -X POST http://127.0.0.1:8000/agent/chat `
  -H "Content-Type: application/json" `
  -d '{"message":"Find sushi near Geylang Serai"}'
```

The focused trace events are also printed to stdout. Raw SDK lifecycle events,
token deltas, duplicate message envelopes, and HTTP client request logs are
omitted. Trace events include a `scope` field so the manager and Places
Specialist runs remain distinguishable.

The cost-control constants are explicit in `app/constants.py`. A specialist
run may make at most `MAX_PLACES_AGENT_TOOL_CALLS` Google calls. Text and Nearby
Search result counts are also capped. The shared limit is enforced in
application code, even if the model requests more.

## Chat interface

The `frontend` directory contains a small Vue/Vite single-page chat interface.
It displays each assistant answer with a collapsible execution trace containing
all non-delta manager and specialist events. A conversation keeps the same
`session_id` across messages, while the
**New chat** button clears the screen and creates a new backend session.

Run the backend in one PowerShell terminal:

```powershell
uv run python main.py
```

Run the frontend in a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to FastAPI at
`http://127.0.0.1:8000`. For a separately hosted frontend, set
`VITE_API_BASE_URL` to the public backend URL before building.

Create a production frontend bundle with:

```powershell
Set-Location frontend
npm run build
```

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
