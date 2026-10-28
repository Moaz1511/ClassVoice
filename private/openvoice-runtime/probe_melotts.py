from melo.api import TTS

print("initializing")
tts = TTS(language="EN", device="cpu", use_hf=True)
print("tts-ready", tts.hps.data.sampling_rate, len(tts.hps.symbols))
