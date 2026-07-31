"use client";

import Link from "next/link";
import { Clapperboard } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useVideos } from "@/lib/queries";
import { VideoCard } from "./video-card";

export function VideoLibraryGrid() {
  const { data: videos, isLoading, isError, error, refetch } = useVideos();

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="aspect-[4/3] w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  if (!videos || videos.length === 0) {
    return (
      <EmptyState
        icon={Clapperboard}
        title="No videos yet"
        description="Ingest a source video to fan it out into an HLS ladder on B2."
        action={
          <Button asChild size="sm">
            <Link href="/upload">Ingest a video</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {videos.map((video) => (
        <VideoCard key={video.id} video={video} />
      ))}
    </div>
  );
}
