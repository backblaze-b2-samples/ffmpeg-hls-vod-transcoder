"use client";

import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";

import { hlsMasterUrl, thumbnailUrl } from "@/lib/api-client";

// Client-only capability probe: native HLS (Safari) or hls.js MSE. Computed
// lazily (never during SSR — the player only mounts after the detail query
// resolves client-side), so no setState-in-effect is needed.
function detectSupport(): boolean {
  if (typeof document === "undefined") return true;
  const probe = document.createElement("video");
  return (
    probe.canPlayType("application/vnd.apple.mpegurl") !== "" || Hls.isSupported()
  );
}

/**
 * Adaptive HLS player. Prefers native HLS (Safari / iOS, which play
 * application/vnd.apple.mpegurl directly) and falls back to hls.js Media Source
 * Extensions everywhere else. The master playlist and its segments are served
 * by the API HLS proxy straight from B2.
 */
export function HlsPlayer({ videoId, hasThumbnail }: { videoId: string; hasThumbnail: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [supported] = useState(detectSupport);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const src = hlsMasterUrl(videoId);

    // Native HLS (Safari) — just set the source.
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      return;
    }

    if (Hls.isSupported()) {
      const hls = new Hls({ enableWorker: true });
      hls.loadSource(src);
      hls.attachMedia(video);
      return () => hls.destroy();
    }
  }, [videoId]);

  if (!supported) {
    return (
      <div className="flex aspect-video w-full items-center justify-center rounded-md border border-border bg-muted text-sm text-muted-foreground">
        This browser can’t play HLS. Try Safari, or a Chromium/Firefox build with
        Media Source Extensions.
      </div>
    );
  }

  return (
    <video
      ref={videoRef}
      controls
      playsInline
      poster={hasThumbnail ? thumbnailUrl(videoId) : undefined}
      className="aspect-video w-full rounded-md bg-black"
    />
  );
}
