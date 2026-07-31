import Link from "next/link";
import { Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TranscodeStatsCards } from "@/components/dashboard/transcode-stats-cards";
import { RecentTranscodesTable } from "@/components/dashboard/recent-transcodes-table";

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <div className="animate-fade-in border-b border-border pb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Transcode activity and the source → rendition write-amplification
            that makes self-hosted VOD on B2 economical.
          </p>
        </div>
        <Button asChild size="sm" className="h-8">
          <Link href="/upload">
            <Upload className="h-3.5 w-3.5" />
            Ingest a video
          </Link>
        </Button>
      </div>
      <TranscodeStatsCards />
      <div className="animate-fade-in-up stagger-4">
        <RecentTranscodesTable />
      </div>
    </div>
  );
}
