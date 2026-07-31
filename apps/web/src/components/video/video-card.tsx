import Link from "next/link";
import { Film } from "lucide-react";

import { Card } from "@/components/ui/card";
import { thumbnailUrl } from "@/lib/api-client";
import type { VideoAsset } from "@ffmpeg-hls-vod-transcoder/shared";
import { StatusBadge } from "./status-badge";

export function VideoCard({ video }: { video: VideoAsset }) {
  const hasThumb = video.status === "ready" && video.thumbnail_key;

  return (
    <Link href={`/videos/${video.id}`} className="group block">
      <Card className="overflow-hidden transition-colors hover:border-primary/60">
        <div className="relative aspect-video w-full bg-muted">
          {hasThumb ? (
            // The sprite is an API-proxied B2 object, not a static asset, so
            // next/image adds no value here.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={thumbnailUrl(video.id)}
              alt=""
              className="h-full w-full object-cover object-left-top"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <Film className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            </div>
          )}
          <div className="absolute right-2 top-2">
            <StatusBadge status={video.status} />
          </div>
        </div>
        <div className="space-y-1 p-3">
          <p className="truncate text-sm font-medium">{video.title}</p>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {video.ladder} · {video.renditions.length} rendition
              {video.renditions.length === 1 ? "" : "s"}
            </span>
            {video.amplification_factor !== null && (
              <span className="font-mono tabular-nums">
                {video.amplification_factor}× storage
              </span>
            )}
          </div>
        </div>
      </Card>
    </Link>
  );
}
