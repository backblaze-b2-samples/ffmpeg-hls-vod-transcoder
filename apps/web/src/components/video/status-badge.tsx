import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { TranscodeStatus } from "@ffmpeg-hls-vod-transcoder/shared";

const CONFIG: Record<
  TranscodeStatus,
  { label: string; variant: "default" | "secondary" | "destructive"; icon: typeof Loader2; spin?: boolean }
> = {
  transcoding: { label: "Transcoding", variant: "secondary", icon: Loader2, spin: true },
  ready: { label: "Ready", variant: "default", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "destructive", icon: XCircle },
};

export function StatusBadge({ status }: { status: TranscodeStatus }) {
  const { label, variant, icon: Icon, spin } = CONFIG[status];
  return (
    <Badge variant={variant} className="gap-1">
      <Icon className={`h-3 w-3 ${spin ? "animate-spin" : ""}`} aria-hidden="true" />
      {label}
    </Badge>
  );
}
