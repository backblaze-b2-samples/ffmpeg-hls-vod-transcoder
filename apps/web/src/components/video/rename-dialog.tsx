"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRenameVideo } from "@/lib/queries";
import type { VideoAsset } from "@ffmpeg-hls-vod-transcoder/shared";

export function RenameDialog({ video }: { video: VideoAsset }) {
  const [open, setOpen] = useState(false);
  // Opens PRE-FILLED with the current title (edit forms need no default-hint).
  const [title, setTitle] = useState(video.title);
  const rename = useRenameVideo(video.id);

  const onOpenChange = (next: boolean) => {
    if (next) setTitle(video.title);
    setOpen(next);
  };

  const onSave = () => {
    const trimmed = title.trim();
    if (!trimmed) {
      toast.error("Title can’t be empty.");
      return;
    }
    rename.mutate(trimmed, {
      onSuccess: () => {
        toast.success("Title updated.");
        setOpen(false);
      },
      onError: (err) => toast.error(err.message),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          Rename
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename video</DialogTitle>
          <DialogDescription>
            Updates the title in this video’s <code>asset.json</code> manifest.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="video-title">Title</Label>
          <Input
            id="video-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={rename.isPending}>
            {rename.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
