"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, reset }: Readonly<{ error: Error & { digest?: string }; reset: () => void }>) {
  useEffect(() => { console.error(error); }, [error]);
  return <main className="error-state"><h1>We hit a recoverable error.</h1><p>Try the action again. If it continues, share the request ID shown by the API.</p><button className="button button-primary" type="button" onClick={reset}>Try again</button></main>;
}
