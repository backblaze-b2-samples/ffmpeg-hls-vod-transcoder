"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type { Accept, FileRejection } from "react-dropzone";
import { FileVideo, X } from "lucide-react";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Dropzone } from "@/components/upload/dropzone";
import { useCreateVideo } from "@/lib/queries";
import { DEFAULT_LADDER, LADDER_OPTIONS } from "@/lib/ladder";
import type { LadderPreset } from "@ffmpeg-hls-vod-transcoder/shared";

const MAX_SOURCE_SIZE = 200 * 1024 * 1024; // 200 MB — mirrors max_source_size.

// Container types the backend accepts (extension + magic-byte validated there).
const VIDEO_ACCEPT: Accept = {
  "video/mp4": [".mp4", ".m4v"],
  "video/quicktime": [".mov"],
  "video/webm": [".webm"],
  "video/x-matroska": [".mkv"],
};

const ingestSchema = z.object({
  title: z.string().max(200).optional(),
  ladder: z.enum(["360p", "720p", "1080p"]),
});

type IngestValues = z.infer<typeof ingestSchema>;

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

export function IngestForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const createVideo = useCreateVideo();

  const form = useForm<IngestValues>({
    resolver: zodResolver(ingestSchema),
    defaultValues: { title: "", ladder: DEFAULT_LADDER },
  });

  const onFilesRejected = (rejections: FileRejection[]) => {
    const reason = rejections[0]?.errors[0];
    toast.error(
      reason?.code === "file-too-large"
        ? "That file is over the 200 MB source limit."
        : "Unsupported file. Use an MP4, MOV, WebM, or MKV video."
    );
  };

  const onSubmit = (values: IngestValues) => {
    if (!file) {
      toast.error("Choose a source video first.");
      return;
    }
    setProgress(0);
    createVideo.mutate(
      {
        file,
        ladder: values.ladder as LadderPreset,
        title: values.title?.trim() || file.name,
        onProgress: setProgress,
      },
      {
        onSuccess: (res) => {
          toast.success("Source uploaded — transcoding started.");
          router.push(`/videos/${res.id}`);
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  const uploading = createVideo.isPending;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <Card>
          <CardHeader className="border-b border-border py-4 px-5">
            <CardTitle className="card-title">Source video</CardTitle>
          </CardHeader>
          <CardContent className="p-5 space-y-4">
            {file ? (
              <div className="flex items-center gap-3 rounded-md border border-border p-3">
                <FileVideo className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{humanSize(file.size)}</p>
                </div>
                {!uploading && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    aria-label="Remove selected file"
                    onClick={() => setFile(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ) : (
              <Dropzone
                accept={VIDEO_ACCEPT}
                multiple={false}
                maxSize={MAX_SOURCE_SIZE}
                disabled={uploading}
                idleTitle="Drag & drop a source video, or click to browse"
                idleDescription="MP4, MOV, WebM, or MKV — up to 200 MB"
                onFilesSelected={(files) => setFile(files[0] ?? null)}
                onFilesRejected={onFilesRejected}
              />
            )}

            {uploading && (
              <div className="space-y-1.5">
                <Progress value={progress} />
                <p className="text-xs text-muted-foreground">
                  Uploading source… {progress}%
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border py-4 px-5">
            <CardTitle className="card-title">Transcode options</CardTitle>
          </CardHeader>
          <CardContent className="p-5 space-y-6">
            <FormField
              control={form.control}
              name="ladder"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Quality ladder</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger className="w-60">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {LADDER_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    720p is a fast, representative demo run. A preset expands into
                    every rung at or below its height; the encoder never upscales
                    above the source.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Title</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Big Buck Bunny — clip"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Optional. Defaults to the source filename if left blank.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <div className="flex items-center justify-end gap-2">
          <Button type="submit" disabled={uploading || !file}>
            {uploading ? "Uploading…" : "Ingest & transcode"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
