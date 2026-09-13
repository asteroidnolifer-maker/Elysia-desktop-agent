# API Commands

## /chat

Send a message to the AI agent and receive a response.

**Endpoint:** `POST /chat`

**Request Body:**
```json
{
  "message": "string (required)",
  "session_id": "string (optional)"
}
```

**Response:**
```json
{
  "reply": "string",
  "error": "string"
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8085/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello, who are you?"}'
```

**Error Codes:**
- `400 Bad Request` - Returns `{"error":"message is required"}` if message is empty or missing
- `401 Unauthorized` - Returned if an `api_key` is configured and not supplied
- `403 Forbidden` - Returned if no `api_key` is configured and the request is not loopback
- `429 Too Many Requests` - Returned if the per-IP rate budget is exceeded
- `200 OK` - Response includes `error` field with empty string on success

**Notes:**
- The `session_id` parameter is optional; if omitted it defaults to `"default"`. Messages accumulate under this key and history is capped (user turns at 12, full history at 16)
- The endpoint routes the message through the agent, letting the LLM dispatch tools (search, sandbox, files, macros, games, projects) before answering
- The final reply is validated/cleaned (capped at 12000 bytes, stray control bytes stripped, empty output replaced)
- Response includes the AI's reply in the `reply` field
- Error messages are returned in the `error` field with an empty string on success

See [`docs/API.md`](docs/API.md) for the full chat endpoint reference.