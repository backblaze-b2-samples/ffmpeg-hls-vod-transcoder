export type FileStatus = "uploading" | "complete" | "error";

export interface FileMetadata {
  key: string;
  filename: string;
  folder: string;
  size_bytes: number;
  size_human: string;
  content_type: string;
  uploaded_at: string;
  url: string | null;
}

export interface FileMetadataDetail {
  filename: string;
  size_bytes: number;
  size_human: string;
  mime_type: string;
  extension: string;
  md5: string;
  sha256: string;
  uploaded_at: string;
  /** Set when a format-specific extractor was skipped or failed (e.g. an image
   *  above the decompression-bomb decode limit). Core fields stay exact. */
  metadata_warning: string | null;
  // Image-specific
  image_width: number | null;
  image_height: number | null;
  exif: Record<string, string> | null;
  // PDF-specific
  pdf_pages: number | null;
  pdf_author: string | null;
  pdf_title: string | null;
  // Audio/Video
  duration_seconds: number | null;
  codec: string | null;
  bitrate: number | null;
}

export interface FileUploadResponse {
  key: string;
  filename: string;
  size_bytes: number;
  size_human: string;
  content_type: string;
  uploaded_at: string;
  url: string | null;
  metadata: FileMetadataDetail | null;
}

export interface DailyUploadCount {
  date: string;
  uploads: number;
}

export interface UploadStats {
  total_files: number;
  total_size_bytes: number;
  total_size_human: string;
  uploads_today: number;
  total_downloads: number;
}

// --- VOD transcode pipeline -------------------------------------------------

/** Quality-ladder preset: a ceiling that expands into every rung at or below
 *  its height (e.g. "720p" -> 360p + 720p). */
export type LadderPreset = "360p" | "720p" | "1080p";

export type TranscodeStatus = "transcoding" | "ready" | "failed";

export interface Rendition {
  name: string;
  height: number;
  width: number;
  video_kbps: number;
  playlist_key: string;
  segment_count: number;
  size_bytes: number;
  size_human: string;
}

export interface VideoAsset {
  id: string;
  title: string;
  status: TranscodeStatus;
  ladder: LadderPreset;
  source_key: string;
  source_filename: string;
  source_size_bytes: number;
  source_size_human: string;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  renditions: Rendition[];
  rendition_bytes: number;
  rendition_bytes_human: string;
  /** rendition_bytes / source_size_bytes — the headline write-amplification. */
  amplification_factor: number | null;
  master_playlist_key: string | null;
  thumbnail_key: string | null;
  created_at: string;
  updated_at: string;
  error: string | null;
}

/** Immediate response to POST /videos — the transcode runs in the background. */
export interface IngestResponse {
  id: string;
  title: string;
  status: TranscodeStatus;
}

export interface TranscodeStats {
  total_videos: number;
  ready_videos: number;
  transcoding_videos: number;
  failed_videos: number;
  total_renditions: number;
  source_bytes: number;
  source_bytes_human: string;
  rendition_bytes: number;
  rendition_bytes_human: string;
  amplification_factor: number | null;
  recent: VideoAsset[];
}
