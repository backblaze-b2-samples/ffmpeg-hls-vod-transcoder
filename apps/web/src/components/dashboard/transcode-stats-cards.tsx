"use client";

import { Clapperboard, Layers, HardDrive, TrendingUp } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/error-state";
import { useVideoStats } from "@/lib/queries";

export function TranscodeStatsCards() {
  const { data: stats, isLoading, error, refetch } = useVideoStats();

  if (error) {
    return (
      <Card>
        <CardContent className="p-0">
          <ErrorState error={error} onRetry={() => refetch()} />
        </CardContent>
      </Card>
    );
  }

  const cards = [
    { title: "Videos", value: stats?.total_videos ?? 0, icon: Clapperboard },
    { title: "Renditions", value: stats?.total_renditions ?? 0, icon: Layers },
    {
      title: "Source → Rendition",
      value: `${stats?.source_bytes_human ?? "0 B"} → ${stats?.rendition_bytes_human ?? "0 B"}`,
      icon: HardDrive,
    },
    {
      title: "Amplification",
      value:
        typeof stats?.amplification_factor === "number"
          ? `${stats.amplification_factor}×`
          : "—",
      icon: TrendingUp,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card, i) => (
        <Card
          key={card.title}
          className={`card-hover animate-fade-in-up stagger-${i + 1}`}
        >
          <CardHeader className="flex flex-row items-center justify-between pt-4 pb-2 px-4 space-y-0">
            <CardTitle className="text-xs font-semibold text-muted-foreground">
              {card.title}
            </CardTitle>
            <div className="stat-icon-wrap">
              <card.icon className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent className="pb-5 px-4">
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <div className="stat-value text-lg">{card.value}</div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
