import createClient from "openapi-fetch";

import type { paths } from "./schema.js";

export type { components, operations, paths } from "./schema.js";

export type ApiClientOptions = {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  headers?: HeadersInit;
};

/** Create a client whose paths, parameters, request bodies, and responses come from FastAPI OpenAPI. */
export function createApiClient(options: ApiClientOptions) {
  return createClient<paths>({
    baseUrl: options.baseUrl,
    fetch: options.fetch,
    headers: options.headers,
  });
}
