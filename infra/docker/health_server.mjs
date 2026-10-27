import http from "node:http";

const args = process.argv.slice(2);
const portIndex = args.indexOf("--port");
const port = portIndex >= 0 ? Number(args[portIndex + 1]) : 3000;
const checkIndex = args.indexOf("--check");

if (checkIndex >= 0) {
  const response = await fetch(args[checkIndex + 1]);
  process.exit(response.ok ? 0 : 1);
}

const server = http.createServer((request, response) => {
  if (!["/", "/health/live", "/health/ready"].includes(request.url)) {
    response.writeHead(404);
    response.end();
    return;
  }

  const body = JSON.stringify({ status: "ok", service: "classvoice-placeholder" });
  response.writeHead(200, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  response.end(body);
});

server.listen(port, "0.0.0.0");
