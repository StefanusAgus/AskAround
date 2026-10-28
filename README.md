# AskAround

A conversational place-discovery project based on Agentic conversational workflow and tools built on top of Google Places API:

- Text Search resolves postcodes, addresses, landmarks, and text queries.
- Nearby Search finds points of interest around known coordinates.

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
   # Optional; defaults to openai/gpt-5.6-luna
   $env:OPENROUTER_MODEL = "openai/gpt-5.6-luna"
   ```

4. Start the API:

   ```powershell
   uv run python main.py
   ```

Open `http://127.0.0.1:8000/docs` to inspect and test the API routes.

## Agent API

`POST /agent/chat` runs one AskAround agent through OpenRouter using the OpenAI
Agents SDK:

- Google Places Text Search to resolve postcodes, addresses, and landmarks.
- Nearby Search to find points of interest around resolved coordinates.

Its prompt defines the workflow: resolve the location anchor with Text Search,
reuse the returned coordinates for Nearby Search, run one Nearby Search per
requested category, and synthesize only from tool results.

The agent infers an ISO two-letter region code from a clear country hint and
defaults to Singapore (`SG`) otherwise. Response language remains English.

The response is a Server-Sent Events stream with focused events:

- `agent_thinking` with concise agent reasoning.
- `tool_call` with the tool name and parsed parameters.
- `tool_output` with the parsed tool result.
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
omitted. Trace events include the agent name and execution scope.

The cost-control constants are explicit in `app/constants.py`. A run may make
at most `MAX_AGENT_TOOL_CALLS` Google calls. Text and Nearby Search result
counts are also capped. The limit is enforced in application code.

## Chat interface

The `frontend` directory contains a small Vue/Vite single-page chat interface.
It displays each assistant answer with a collapsible execution trace containing
only reasoning, tool calls, tool outputs, final output, and errors. A
conversation keeps the same `session_id` across messages, while the
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

Run the fixture-backed agent evaluation suite with the configured OpenRouter
model. These evaluations do not call Google Places:

```powershell
uv run python -m evals.runner
```

Add `--judge` to run the optional LLM-as-a-judge grader, or use `--case
location_not_found` to run one scenario. See `evals/README.md` for the covered
behaviors and report location.

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
