import Link from "next/link";
import { Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { VideoLibraryGrid } from "@/components/video/video-library-grid";

export default function VideosPage() {
  return (
    <div className="space-y-8">
      <div className="animate-fade-in flex flex-wrap items-start justify-between gap-4 border-b border-border pb-5">
        <div className="min-w-0">
          <h1 className="page-title">Videos</h1>
          <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
            Every ingested asset and its transcoded renditions, scoped to the
            <code className="mx-1">videos/</code>prefix in your bucket.
          </p>
        </div>
        <Button asChild size="sm" className="h-8 shrink-0">
          <Link href="/upload">
            <Upload aria-hidden="true" className="h-3.5 w-3.5" />
            Ingest a video
          </Link>
        </Button>
      </div>
      <div className="animate-fade-in-up stagger-2">
        <VideoLibraryGrid />
      </div>
    </div>
  );
}
