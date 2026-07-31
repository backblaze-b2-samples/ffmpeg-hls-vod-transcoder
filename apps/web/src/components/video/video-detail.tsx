"use client";

import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteVideo, useVideo } from "@/lib/queries";
import { HlsPlayer } from "./hls-player";
import { RenditionTable } from "./rendition-table";
import { RenameDialog } from "./rename-dialog";
import { RetranscodeDialog } from "./retranscode-dialog";
import { StatusBadge } from "./status-badge";

export function VideoDetail({ videoId }: { videoId: string }) {
  const router = useRouter();
  const { data: video, isLoading, isError, error, refetch } = useVideo(videoId);
  const deleteVideo = useDeleteVideo();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="aspect-video w-full rounded-md" />
        <Skeleton className="h-40 w-full rounded-md" />
      </div>
    );
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  if (!video) return null;

  const onDelete = () => {
    deleteVideo.mutate(video.id, {
      onSuccess: () => {
        toast.success("Video deleted.");
        router.push("/videos");
      },
      onError: (err) => toast.error(err.message),
    });
  };

  return (
    <div className="space-y-8">
      <div className="animate-fade-in flex flex-wrap items-start justify-between gap-4 border-b border-border pb-5">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="page-title truncate">{video.title}</h1>
            <StatusBadge status={video.status} />
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {video.source_filename} · {video.source_size_human}
            {video.width && video.height ? ` · ${video.width}×${video.height}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RenameDialog video={video} />
          <RetranscodeDialog video={video} />
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                Delete
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete this video?</AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently removes the source, every rendition, and the
                  manifest under <code>videos/{video.id}/</code>. It cannot be
                  undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {video.status === "failed" && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Transcode failed</AlertTitle>
          <AlertDescription>
            {video.error ?? "The transcode job failed."} Re-transcode to try
            again.
          </AlertDescription>
        </Alert>
      )}

      {video.status === "transcoding" && (
        <div className="flex aspect-video w-full items-center justify-center rounded-md border border-border bg-muted">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Transcoding… this view updates automatically.
          </div>
        </div>
      )}

      {video.status === "ready" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <HlsPlayer videoId={video.id} hasThumbnail={!!video.thumbnail_key} />
          </div>
          <Card>
            <CardHeader className="border-b border-border py-4 px-5">
              <CardTitle className="card-title">Write amplification</CardTitle>
            </CardHeader>
            <CardContent className="p-5 space-y-3">
              <div>
                <p className="font-mono text-3xl font-semibold tabular-nums">
                  {video.amplification_factor ?? "—"}×
                </p>
                <p className="text-xs text-muted-foreground">
                  rendition storage ÷ source
                </p>
              </div>
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Source</dt>
                  <dd className="font-mono tabular-nums">{video.source_size_human}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Renditions</dt>
                  <dd className="font-mono tabular-nums">
                    {video.rendition_bytes_human}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader className="border-b border-border py-4 px-5">
          <CardTitle className="card-title">Renditions</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <RenditionTable renditions={video.renditions} />
        </CardContent>
      </Card>
    </div>
  );
}
