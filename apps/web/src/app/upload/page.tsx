import { IngestForm } from "@/components/video/ingest-form";

export default function IngestPage() {
  return (
    <div className="space-y-8">
      <div className="animate-fade-in border-b border-border pb-5">
        <h1 className="page-title">Ingest</h1>
        <p className="mt-1.5 max-w-prose text-sm text-muted-foreground text-pretty">
          Upload a source video and pick a quality ladder. FFmpeg fans it out
          into an HLS adaptive-bitrate ladder on Backblaze B2, then you can watch
          it back adaptively.
        </p>
      </div>
      <div className="animate-fade-in-up stagger-2">
        <IngestForm />
      </div>
    </div>
  );
}
