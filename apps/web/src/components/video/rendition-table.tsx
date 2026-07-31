import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Rendition } from "@ffmpeg-hls-vod-transcoder/shared";

export function RenditionTable({ renditions }: { renditions: Rendition[] }) {
  if (renditions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No renditions yet — they appear here once the transcode finishes.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Rendition</TableHead>
          <TableHead>Resolution</TableHead>
          <TableHead className="text-right">Bitrate</TableHead>
          <TableHead className="text-right">Segments</TableHead>
          <TableHead className="text-right">Size</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {renditions.map((r) => (
          <TableRow key={r.name}>
            <TableCell className="font-medium">{r.name}</TableCell>
            <TableCell className="font-mono tabular-nums">
              {r.width}×{r.height}
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {r.video_kbps} kbps
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {r.segment_count}
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {r.size_human}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
