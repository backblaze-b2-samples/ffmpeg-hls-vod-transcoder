"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRetranscodeVideo } from "@/lib/queries";
import { LADDER_OPTIONS } from "@/lib/ladder";
import type { LadderPreset, VideoAsset } from "@ffmpeg-hls-vod-transcoder/shared";

export function RetranscodeDialog({ video }: { video: VideoAsset }) {
  const [open, setOpen] = useState(false);
  const [ladder, setLadder] = useState<LadderPreset>(video.ladder);
  const retranscode = useRetranscodeVideo(video.id);

  const onRun = () => {
    retranscode.mutate(ladder, {
      onSuccess: () => {
        toast.success("Re-transcode started.");
        setOpen(false);
      },
      onError: (err) => toast.error(err.message),
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={video.status === "transcoding"}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Re-transcode
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-transcode</DialogTitle>
          <DialogDescription>
            Re-runs FFmpeg on the stored source — e.g. to add a higher rung
            later. Existing renditions are replaced.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>Quality ladder</Label>
          <Select value={ladder} onValueChange={(v) => setLadder(v as LadderPreset)}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LADDER_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={onRun} disabled={retranscode.isPending}>
            {retranscode.isPending ? "Starting…" : "Re-transcode"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
