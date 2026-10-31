function createSyntheticWav(): Uint8Array {
  const sampleRate = 8_000;
  const sampleCount = 16_000;
  const dataSize = sampleCount * 2;
  const bytes = new Uint8Array(44 + dataSize);
  const view = new DataView(bytes.buffer);
  const writeAscii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) bytes[offset + index] = value.charCodeAt(index);
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, dataSize, true);
  return bytes;
}

export function GET() {
  if (process.env.CLASSVOICE_E2E_FIXTURES !== "1") return new Response(null, { status: 404 });
  const wav = createSyntheticWav();
  return new Response(wav.buffer as ArrayBuffer, {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "audio/wav",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
