import Link from "next/link";
import openapi from "../../../../packages/api-client/openapi.json";

type OpenApiOperation = Readonly<{
  operationId?: string;
  requestBody?: Readonly<{ content?: Record<string, Readonly<{ schema?: Readonly<{ $ref?: string }> }>> }>;
  responses?: Record<string, unknown>;
  summary?: string;
  tags?: string[];
}>;

type OpenApiDocument = Readonly<{
  info?: Readonly<{ title?: string; version?: string }>;
  paths: Record<string, Record<string, OpenApiOperation>>;
}>;

const document = openapi as OpenApiDocument;
const httpMethods = new Set(["get", "post", "put", "patch", "delete"]);
const endpointEntries = Object.entries(document.paths).flatMap(([path, pathItem]) =>
  Object.entries(pathItem)
    .filter(([method]) => httpMethods.has(method))
    .map(([method, operation]) => ({ method: method.toUpperCase(), operation, path })),
);

const quickstartCurl = [
  "# 1. Set the API base URL and credentials.",
  "export CLASSVOICE_API_URL=\"http://localhost:8000\"",
  "export CLASSVOICE_API_KEY=\"cv_live_replace_me\"",
  "export WORKSPACE_ID=\"00000000-0000-0000-0000-000000000000\"",
  "export VOICE_PROFILE_ID=\"00000000-0000-0000-0000-000000000000\"",
  "",
  "# 2. Submit exactly one idempotent generation request.",
  "JOB=$(curl --fail-with-body -sS -X POST \"$CLASSVOICE_API_URL/v1/generations\" \\",
  "  -H \"X-API-Key: $CLASSVOICE_API_KEY\" \\",
  "  -H \"Idempotency-Key: lesson-2026-01-01-001\" \\",
  "  -H \"Content-Type: application/json\" \\",
  "  -d '{",
  "    \"workspace_id\": \"'\"$WORKSPACE_ID\"'\",",
  "    \"voice_profile_id\": \"'\"$VOICE_PROFILE_ID\"'\",",
  "    \"input_text\": \"Welcome to today’s lesson.\",",
  "    \"language_code\": \"en-US\",",
  "    \"output_format\": \"mp3\",",
  "    \"speed\": 1.0,",
  "    \"model_key\": \"<approved-model-key>\",",
  "    \"model_version\": \"<approved-model-version>\",",
  "    \"checkpoint_sha256\": \"<64-character-approved-sha256>\"",
  "  }')",
  "export JOB_ID=$(printf '%s' \"$JOB\" | jq -r '.data.id')",
  "",
  "# 3. Poll until data.status is succeeded or failed.",
  "curl --fail-with-body -sS \"$CLASSVOICE_API_URL/v1/generations/$JOB_ID\" \\",
  "  -H \"X-API-Key: $CLASSVOICE_API_KEY\"",
  "",
  "# 4. Ask for a 10-minute private download URL, then follow it.",
  "DOWNLOAD=$(curl --fail-with-body -sS \"$CLASSVOICE_API_URL/v1/generations/$JOB_ID/download\" \\",
  "  -H \"X-API-Key: $CLASSVOICE_API_KEY\")",
  "printf '%s' \"$DOWNLOAD\" | jq -r '.data.download.url' | xargs curl --fail-with-body -L -o lesson.mp3",
].join("\n");

const keyIssuanceCurl = [
  "# API-key creation requires a verified JWT and owner/admin membership.",
  "curl --fail-with-body -sS -X POST \"$CLASSVOICE_API_URL/v1/api-keys\" \\",
  "  -H \"Authorization: Bearer $CLASSVOICE_ACCESS_TOKEN\" \\",
  "  -H \"Content-Type: application/json\" \\",
  "  -d '{",
  "    \"workspace_id\": \"'\"$WORKSPACE_ID\"'\",",
  "    \"name\": \"lesson-agent\",",
  "    \"scopes\": [\"generations:create\", \"generations:read\"],",
  "    \"expires_at\": \"2027-01-01T00:00:00Z\"",
  "  }'",
  "# Copy data.secret immediately. The API never returns it again.",
].join("\n");

const javascriptExample = [
  "const response = await fetch(",
  "  process.env.CLASSVOICE_API_URL + \"/v1/generations\",",
  "  {",
  "    method: \"POST\",",
  "    headers: {",
  "      \"X-API-Key\": process.env.CLASSVOICE_API_KEY,",
  "      \"Idempotency-Key\": \"lesson-2026-01-01-001\",",
  "      \"Content-Type\": \"application/json\",",
  "    },",
  "    body: JSON.stringify({",
  "      workspace_id: process.env.WORKSPACE_ID,",
  "      voice_profile_id: process.env.VOICE_PROFILE_ID,",
  "      input_text: \"Welcome to today’s lesson.\",",
  "      language_code: \"en-US\",",
  "      output_format: \"mp3\",",
  "      speed: 1,",
  "      model_key: process.env.CLASSVOICE_MODEL_KEY,",
  "      model_version: process.env.CLASSVOICE_MODEL_VERSION,",
  "      checkpoint_sha256: process.env.CLASSVOICE_CHECKPOINT_SHA256,",
  "    }),",
  "  },",
  ");",
  "const envelope = await response.json();",
  "if (!response.ok) throw new Error(envelope.error?.message ?? \"ClassVoice request failed\");",
  "console.log(envelope.data.id);",
].join("\n");

function schemaName(operation: OpenApiOperation) {
  const schemaRef = operation.requestBody?.content?.["application/json"]?.schema?.$ref;
  return schemaRef?.split("/").pop() ?? "No request body";
}

export function ApiDocsScreen() {
  const version = document.info?.version ?? "generated contract";
  const title = document.info?.title ?? "ClassVoice API";

  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb">
        <Link href="/dashboard">Dashboard</Link><span aria-hidden="true">/</span><span>API documentation</span>
      </div>
      <div className="page-heading docs-heading">
        <div><p className="eyebrow">Agent integration</p><h1>{title}</h1><p>Use the generated OpenAPI contract to create consented academic audio and retrieve private outputs safely.</p></div>
        <span className="status-badge status-badge-success"><span className="status-dot" />OpenAPI {version}</span>
      </div>
      <div className="docs-layout">
        <aside className="card docs-sidebar" aria-label="API documentation navigation">
          <div className="card-kicker">On this page</div>
          <nav className="docs-nav">
            <a href="#quickstart">Quickstart</a>
            <a href="#authentication">Authentication</a>
            <a href="#generation-flow">Generation flow</a>
            <a href="#reference">Endpoint reference</a>
            <a href="#safety">Safety and limits</a>
          </nav>
          <p className="implementation-note">Generated from <code>packages/api-client/openapi.json</code>.</p>
        </aside>
        <main className="docs-main">
          <section className="card docs-section" id="quickstart" aria-labelledby="quickstart-heading">
            <div className="card-kicker">Five-minute path</div><h2 id="quickstart-heading">Create, poll, and download</h2>
            <p className="muted">The example uses an API key with only <code>generations:create</code> and <code>generations:read</code>. Replace every angle-bracket placeholder with values from an approved workspace model registry.</p>
            <pre className="docs-code"><code>{quickstartCurl}</code></pre>
          </section>
          <section className="card docs-section" id="authentication" aria-labelledby="authentication-heading">
            <div className="card-kicker">Credentials</div><h2 id="authentication-heading">Authenticate without leaking secrets</h2>
            <div className="docs-two-column"><div><h3>Machine agents</h3><p className="muted">Use <code>X-API-Key: cv_live_…</code> for generation and read operations. Scope the key to the smallest required permissions and rotate it before expiry.</p></div><div><h3>Dashboard and key issuance</h3><p className="muted">Create keys with a verified JWT from the dashboard or an owner/admin service. The returned secret is shown once and is never persisted in browser storage.</p></div></div>
            <pre className="docs-code"><code>{keyIssuanceCurl}</code></pre>
            <div className="notice">Never place a Supabase service-role key, JWT signing secret, webhook secret, or raw voice/audio bytes in client-side code or a notebook checked into source control.</div>
          </section>
          <section className="card docs-section" id="generation-flow" aria-labelledby="generation-heading">
            <div className="card-kicker">Typed request example</div><h2 id="generation-heading">JavaScript agent request</h2>
            <p className="muted">Every generation request is bounded to 10,000 characters and requires an idempotency key. The response envelope always includes <code>data</code>, <code>error</code>, and <code>request_id</code> fields.</p>
            <pre className="docs-code"><code>{javascriptExample}</code></pre>
          </section>
          <section className="card docs-section" id="reference" aria-labelledby="reference-heading">
            <div className="card-kicker">Generated reference</div><h2 id="reference-heading">Endpoint reference</h2>
            <p className="muted">{endpointEntries.length} operations are present in the checked-in OpenAPI document. Response schemas are intentionally summarized here; use the generated TypeScript client for compile-time types.</p>
            <div className="docs-endpoint-list">{endpointEntries.map(({ method, operation, path }) => <article className="docs-endpoint" key={method + path}><div className="docs-endpoint-header"><span className={"docs-method docs-method-" + method.toLowerCase()}>{method}</span><code>{path}</code></div><p>{operation.summary ?? operation.operationId ?? "API operation"}</p><div className="docs-endpoint-meta"><span>Tag: {operation.tags?.[0] ?? "core"}</span><span>Body: {schemaName(operation)}</span><span>Responses: {Object.keys(operation.responses ?? {}).join(", ") || "documented"}</span></div></article>)}</div>
          </section>
          <section className="card docs-section" id="safety" aria-labelledby="safety-heading">
            <div className="card-kicker">Operational contract</div><h2 id="safety-heading">Safety and limits</h2>
            <ul className="safety-list"><li>Only approved voices with active consent can enter the generation queue.</li><li>Upload intents accept WAV, MP3, or M4A up to 25 MB; the server validates magic bytes and decoded audio.</li><li>Signed output URLs are private and expire after 600 seconds. Do not cache or expose them in logs.</li><li>Use one stable <code>Idempotency-Key</code> per logical create request and retry only with the same key.</li><li>List and audit responses omit raw input text, audio bytes, embeddings, storage keys, and secrets.</li></ul>
            <div className="action-row"><Link className="button button-secondary" href="/api-keys">Manage API keys</Link><Link className="button button-secondary" href="/settings/safety">Review safety settings</Link></div>
          </section>
        </main>
      </div>
    </>
  );
}
