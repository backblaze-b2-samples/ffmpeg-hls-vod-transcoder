"use client";

import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useVideoStats } from "@/lib/queries";
import { StatusBadge } from "@/components/video/status-badge";
import { Clapperboard } from "lucide-react";

export function RecentTranscodesTable() {
  const { data: stats, isLoading, error, refetch } = useVideoStats();

  return (
    <Card>
      <CardHeader className="border-b border-border py-4 px-5">
        <CardTitle className="card-title">Recent transcodes</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && (
          <div className="space-y-2 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}
        {error && <ErrorState error={error} onRetry={() => refetch()} />}
        {!isLoading && !error && stats && stats.recent.length === 0 && (
          <EmptyState
            icon={Clapperboard}
            title="No transcodes yet"
            description="Ingested videos will show up here."
          />
        )}
        {!isLoading && !error && stats && stats.recent.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Amplification</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stats.recent.map((video) => (
                <TableRow key={video.id}>
                  <TableCell className="max-w-[220px] truncate font-medium">
                    <Link href={`/videos/${video.id}`} className="hover:underline">
                      {video.title}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={video.status} />
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {video.amplification_factor !== null
                      ? `${video.amplification_factor}×`
                      : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
