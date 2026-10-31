"use client";

import { useRef, useState } from "react";

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const wholeSeconds = Math.floor(seconds);
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

type AudioPlayerProps = Readonly<{
  src: string;
  captionsSrc?: string;
  downloadName: string;
}>;

export function AudioPlayer({ src, captionsSrc, downloadName }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [message, setMessage] = useState("");

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      setPlaying(false);
      return;
    }
    try {
      await audio.play();
      setPlaying(true);
      setMessage("");
    } catch {
      setMessage("Playback could not start. Request a fresh authorized audio URL and try again.");
    }
  }

  function seek(nextTime: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = nextTime;
    setCurrentTime(nextTime);
  }

  function changeVolume(nextVolume: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = nextVolume;
    setVolume(nextVolume);
  }

  function changePlaybackRate(nextRate: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = nextRate;
    setPlaybackRate(nextRate);
  }

  return (
    <div className="audio-player" aria-label="Generated lesson audio player">
      <audio
        ref={audioRef}
        className="player-media"
        src={src}
        preload="metadata"
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onEnded={() => setPlaying(false)}
      >
        {captionsSrc ? <track kind="captions" src={captionsSrc} srcLang="en" label="English" default /> : null}
      </audio>
      <div className="audio-player-primary">
        <button className="icon-button player-toggle" type="button" aria-label={playing ? "Pause generated audio" : "Play generated audio"} onClick={togglePlayback}>
          <span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span>
        </button>
        <label className="player-seek">
          <span className="sr-only">Seek generated audio</span>
          <input
            type="range"
            min="0"
            max={Math.max(duration, 0)}
            step="0.1"
            value={Math.min(currentTime, Math.max(duration, 0))}
            disabled={duration <= 0}
            onChange={(event) => seek(Number(event.target.value))}
          />
        </label>
        <span className="player-time" aria-label={`${formatDuration(currentTime)} of ${formatDuration(duration)}`}>
          {formatDuration(currentTime)} / {formatDuration(duration)}
        </span>
      </div>
      <div className="audio-player-secondary">
        <label className="player-control">
          <span>Volume</span>
          <input type="range" min="0" max="1" step="0.1" value={volume} onChange={(event) => changeVolume(Number(event.target.value))} />
        </label>
        <label className="player-control">
          <span>Playback speed</span>
          <select value={playbackRate} onChange={(event) => changePlaybackRate(Number(event.target.value))}>
            <option value="0.75">0.75×</option>
            <option value="1">1×</option>
            <option value="1.25">1.25×</option>
            <option value="1.5">1.5×</option>
          </select>
        </label>
        <a className="button button-secondary" href={src} download={downloadName}>Download audio</a>
      </div>
      {message ? <p className="form-error" role="alert">{message}</p> : null}
      <p className="field-hint">AI-generated · private authorized output</p>
    </div>
  );
}
