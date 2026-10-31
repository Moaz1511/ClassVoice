export function GET() {
  if (process.env.CLASSVOICE_E2E_FIXTURES !== "1") return new Response(null, { status: 404 });
  return new Response("WEBVTT\n\n00:00.000 --> 00:02.000\nSynthetic academic narration test fixture.\n", {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/vtt; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
