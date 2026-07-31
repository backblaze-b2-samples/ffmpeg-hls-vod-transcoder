import type {
  DailyUploadCount,
  FileMetadata,
  FileMetadataDetail,
  IngestResponse,
  LadderPreset,
  TranscodeStats,
  UploadStats,
  VideoAsset,
} from "@ffmpeg-hls-vod-transcoder/shared";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type ApiClientRoute = {
  method: "delete" | "get" | "patch" | "post";
  path: string;
};

export const API_CLIENT_ROUTES = {
  health: { method: "get", path: "/health" },
  files: { method: "get", path: "/files" },
  fileStats: { method: "get", path: "/files/stats" },
  uploadActivity: { method: "get", path: "/files/stats/activity" },
  fileByKeyDownload: { method: "get", path: "/files-by-key/download" },
  fileByKeyPreview: { method: "get", path: "/files-by-key/preview" },
  fileByKeyMetadata: { method: "get", path: "/files-by-key/metadata" },
  fileByKeyDetail: { method: "get", path: "/files-by-key/detail" },
  fileByKeyDelete: { method: "delete", path: "/files-by-key" },
  legacyFileDownload: { method: "get", path: "/files/{key}/download" },
  legacyFilePreview: { method: "get", path: "/files/{key}/preview" },
  legacyFileMetadata: { method: "get", path: "/files/{key}" },
  legacyFileDelete: { method: "delete", path: "/files/{key}" },
  // Video (VOD) routes. Paths mirror the OpenAPI templates ({video_id}, {path})
  // so the contract test can match them 1:1.
  videos: { method: "get", path: "/videos" },
  videoCreate: { method: "post", path: "/videos" },
  videoStats: { method: "get", path: "/videos/stats" },
  video: { method: "get", path: "/videos/{video_id}" },
  videoRename: { method: "patch", path: "/videos/{video_id}" },
  videoDelete: { method: "delete", path: "/videos/{video_id}" },
  videoRetranscode: { method: "post", path: "/videos/{video_id}/retranscode" },
} as const satisfies Record<string, ApiClientRoute>;

/** Absolute URL to the master HLS playlist — fed to hls.js / native <video>. */
export function hlsMasterUrl(videoId: string): string {
  return `${API_BASE}/videos/${encodeURIComponent(videoId)}/hls/master.m3u8`;
}

/** Absolute URL to a video's sprite thumbnail — used in <img>. */
export function thumbnailUrl(videoId: string): string {
  return `${API_BASE}/videos/${encodeURIComponent(videoId)}/thumbnail`;
}

/** Typed API error with HTTP status code for caller-side branching. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True for 408, 429, 500, 502, 503, 504 — worth retrying. */
  get isRetryable(): boolean {
    return [408, 429, 500, 502, 503, 504].includes(this.status);
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
}

/**
 * Build the right status-0 ApiError for a thrown fetch().
 *
 * fetch() rejects with a TypeError for genuinely-offline/DNS failures AND for
 * responses the browser refused to expose — most notably a cross-origin 500
 * that shipped without `Access-Control-Allow-Origin`. We can't tell those apart
 * from the error object, but `navigator.onLine === false` reliably means the
 * device has no connectivity. Anything else reached the network, so the most
 * likely cause is the server erroring with a CORS-blocked response — point the
 * developer at the API logs instead of blaming their connection.
 */
function networkError(): ApiError {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return new ApiError("You appear to be offline — check your connection", 0);
  }
  return new ApiError(
    "Couldn't reach the API, or the server returned an error the browser blocked (CORS). Check the API logs.",
    0,
  );
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw networkError();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      body.detail || `API error: ${res.status}`,
      res.status,
    );
  }
  return res.json();
}

function isEndpointUnavailable(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    (error.message === "Not Found" || error.message === "API error: 404")
  );
}

async function apiFetchWithLegacyFallback<T>(
  path: string,
  legacyPath: () => string,
  init?: RequestInit
): Promise<T> {
  try {
    return await apiFetch<T>(path, init);
  } catch (error) {
    if (isEndpointUnavailable(error)) {
      return apiFetch<T>(legacyPath(), init);
    }
    throw error;
  }
}

function fileKeyQuery(key: string): string {
  if (key.length === 0) {
    throw new ApiError("File key is required", 400);
  }
  return new URLSearchParams({ key }).toString();
}

function legacyFileKeyPath(
  key: string,
  options: { blockRouteCollisions?: boolean } = {}
): string {
  if (!isLegacyPathFallbackSafe(key, options)) {
    throw new ApiError("Current API version required for this file key", 404);
  }
  return encodeURIComponent(key);
}

/**
 * Substitute a file key into a legacy `{key}` path template. The parameter type
 * requires the literal `{key}` placeholder, so passing a registry path that has
 * no placeholder is a compile error rather than a silent no-op that would send
 * the request to a keyless URL.
 */
function legacyFileKeyRoute(
  path: `${string}{key}${string}`,
  key: string,
  options: { blockRouteCollisions?: boolean } = {}
): string {
  return path.replace("{key}", legacyFileKeyPath(key, options));
}

function isLegacyPathFallbackSafe(
  key: string,
  { blockRouteCollisions = false }: { blockRouteCollisions?: boolean } = {}
): boolean {
  if (/(\.\.\/|\/\.\.|\\|%2e%2e|%00|\x00)/i.test(key)) return false;
  if (!blockRouteCollisions) return true;

  const lowerKey = key.toLowerCase();
  if (lowerKey === "stats" || lowerKey === "stats/activity") return false;
  if (lowerKey.endsWith("/download") || lowerKey.endsWith("/preview")) return false;
  return true;
}

export async function getHealth() {
  return apiFetch<{ status: string; b2_connected: boolean }>(
    API_CLIENT_ROUTES.health.path
  );
}

export async function getFiles(prefix = "", limit = 100) {
  return apiFetch<FileMetadata[]>(
    `${API_CLIENT_ROUTES.files.path}?prefix=${encodeURIComponent(prefix)}&limit=${limit}`
  );
}

export async function getFileStats() {
  return apiFetch<UploadStats>(API_CLIENT_ROUTES.fileStats.path);
}

export async function getUploadActivity(days = 7) {
  return apiFetch<DailyUploadCount[]>(
    `${API_CLIENT_ROUTES.uploadActivity.path}?days=${days}`
  );
}

export async function getFile(key: string) {
  return apiFetchWithLegacyFallback<FileMetadata>(
    `${API_CLIENT_ROUTES.fileByKeyMetadata.path}?${fileKeyQuery(key)}`,
    () =>
      legacyFileKeyRoute(API_CLIENT_ROUTES.legacyFileMetadata.path, key, {
        blockRouteCollisions: true,
      })
  );
}

/**
 * Rich metadata (checksums, image/PDF fields) for an already-stored file.
 * The server recomputes this on demand by downloading the object, so it's a
 * heavier call than getFile — fetch it lazily (only when the user asks to see
 * details). No legacy path fallback: this endpoint is new, so an older backend
 * wouldn't serve it under any route.
 */
export async function getFileDetail(key: string) {
  return apiFetch<FileMetadataDetail>(
    `${API_CLIENT_ROUTES.fileByKeyDetail.path}?${fileKeyQuery(key)}`
  );
}

export async function getDownloadUrl(key: string) {
  return apiFetchWithLegacyFallback<{ url: string }>(
    `${API_CLIENT_ROUTES.fileByKeyDownload.path}?${fileKeyQuery(key)}`,
    () => legacyFileKeyRoute(API_CLIENT_ROUTES.legacyFileDownload.path, key)
  );
}

/** Preview-only presigned URL — does NOT increment the download counter. */
export async function getPreviewUrl(key: string) {
  return apiFetchWithLegacyFallback<{ url: string }>(
    `${API_CLIENT_ROUTES.fileByKeyPreview.path}?${fileKeyQuery(key)}`,
    () => legacyFileKeyRoute(API_CLIENT_ROUTES.legacyFilePreview.path, key)
  );
}

export async function deleteFile(key: string) {
  return apiFetchWithLegacyFallback<{ deleted: boolean; key: string }>(
    `${API_CLIENT_ROUTES.fileByKeyDelete.path}?${fileKeyQuery(key)}`,
    () => legacyFileKeyRoute(API_CLIENT_ROUTES.legacyFileDelete.path, key),
    {
      // Derived from the registry so the verb the contract test checks is the
      // verb actually sent — a hardcoded "DELETE" could silently disagree.
      method: API_CLIENT_ROUTES.fileByKeyDelete.method.toUpperCase(),
    }
  );
}

// --- Video (VOD) client -----------------------------------------------------

function videoPath(template: string, videoId: string): string {
  return template.replace("{video_id}", encodeURIComponent(videoId));
}

export async function getVideos() {
  return apiFetch<VideoAsset[]>(API_CLIENT_ROUTES.videos.path);
}

export async function getVideoStats() {
  return apiFetch<TranscodeStats>(API_CLIENT_ROUTES.videoStats.path);
}

export async function getVideo(videoId: string) {
  return apiFetch<VideoAsset>(
    videoPath(API_CLIENT_ROUTES.video.path, videoId)
  );
}

export async function renameVideo(videoId: string, title: string) {
  return apiFetch<VideoAsset>(
    videoPath(API_CLIENT_ROUTES.videoRename.path, videoId),
    {
      method: API_CLIENT_ROUTES.videoRename.method.toUpperCase(),
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }
  );
}

export async function deleteVideo(videoId: string) {
  return apiFetch<{ deleted: boolean; id: string; objects: number }>(
    videoPath(API_CLIENT_ROUTES.videoDelete.path, videoId),
    { method: API_CLIENT_ROUTES.videoDelete.method.toUpperCase() }
  );
}

export async function retranscodeVideo(videoId: string, ladder: LadderPreset) {
  return apiFetch<IngestResponse>(
    videoPath(API_CLIENT_ROUTES.videoRetranscode.path, videoId),
    {
      method: API_CLIENT_ROUTES.videoRetranscode.method.toUpperCase(),
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ladder }),
    }
  );
}

/**
 * Upload a source video (multipart) and queue transcoding. Uses XHR, not fetch,
 * so the dropzone can show real upload progress — the transcode itself runs in
 * the background and is observed by polling GET /videos/{id}.
 */
export function createVideo(
  file: File,
  ladder: LadderPreset,
  title: string,
  onProgress?: (percent: number) => void
): Promise<IngestResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("ladder", ladder);
    formData.append("title", title);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new ApiError(body.detail || `Ingest failed: ${xhr.status}`, xhr.status));
        } catch {
          reject(new ApiError(`Ingest failed: ${xhr.status}`, xhr.status));
        }
      }
    });

    xhr.addEventListener("error", () => reject(networkError()));
    xhr.addEventListener("abort", () =>
      reject(new ApiError("Ingest aborted", 0)),
    );

    xhr.open(
      API_CLIENT_ROUTES.videoCreate.method.toUpperCase(),
      `${API_BASE}${API_CLIENT_ROUTES.videoCreate.path}`
    );
    xhr.send(formData);
  });
}
