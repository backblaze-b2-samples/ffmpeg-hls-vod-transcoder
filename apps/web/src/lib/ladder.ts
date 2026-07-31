import type { LadderPreset } from "@ffmpeg-hls-vod-transcoder/shared";

/**
 * The finite quality-ladder presets, shared by the Ingest (create) form and the
 * Re-transcode (run) dialog so both use the same Select options. A preset is a
 * ceiling: it expands into every rung at or below its height (e.g. "720p" ->
 * 360p + 720p). The runner never upscales a rung above the source height.
 */
export const LADDER_OPTIONS: { value: LadderPreset; label: string }[] = [
  { value: "360p", label: "360p only" },
  { value: "720p", label: "Up to 720p" },
  { value: "1080p", label: "Up to 1080p" },
];

/** Fast, representative default for a demo ingest. */
export const DEFAULT_LADDER: LadderPreset = "720p";
