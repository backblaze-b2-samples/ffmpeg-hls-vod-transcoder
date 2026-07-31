"use client";

import { useCallback, useId } from "react";
import { useDropzone, type Accept, type FileRejection } from "react-dropzone";
import { Upload, FileIcon } from "lucide-react";
import { ACCEPTED_FILE_TYPES } from "@/lib/upload-file-types";

interface DropzoneProps {
  onFilesSelected: (files: File[]) => void;
  onFilesRejected: (rejections: FileRejection[]) => void;
  disabled?: boolean;
  /** Reusable across features: the video Ingest form passes a video `accept`
   *  map, a single-file constraint, and its own copy. Defaults keep the
   *  original generic-file behaviour. */
  accept?: Accept;
  multiple?: boolean;
  maxSize?: number;
  idleTitle?: string;
  idleDescription?: string;
}

const MAX_SIZE = 100 * 1024 * 1024; // 100MB

export function Dropzone({
  onFilesSelected,
  onFilesRejected,
  disabled,
  accept = ACCEPTED_FILE_TYPES,
  multiple = true,
  maxSize = MAX_SIZE,
  idleTitle = "Drag & drop files here, or click to browse",
  idleDescription = "Max file size: 100 MB per file",
}: DropzoneProps) {
  const descriptionId = useId();
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) {
        onFilesSelected(accepted);
      }
    },
    [onFilesSelected]
  );

  const onDropRejected = useCallback(
    (rejections: FileRejection[]) => {
      onFilesRejected(rejections);
    },
    [onFilesRejected]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept,
    maxSize,
    disabled,
    multiple,
  });

  const active = isDragActive && !disabled;
  let title = idleTitle;
  let description = idleDescription;

  if (disabled) {
    title = "Upload in progress";
    description = "Wait for the current upload to finish.";
  } else if (active) {
    title = "Drop to select";
    description = "Release to choose this file.";
  }

  let stateClasses = "border-border hover:border-primary/60 hover:bg-muted/60";
  if (disabled) {
    stateClasses = "border-border";
  } else if (active) {
    stateClasses = "border-primary bg-[var(--accent-subtle)] dropzone-active";
  }
  const disabledClasses = disabled
    ? "cursor-not-allowed bg-muted/40 text-muted-foreground opacity-80"
    : "cursor-pointer";

  return (
    <div
      {...getRootProps({
        "aria-describedby": descriptionId,
        "aria-disabled": disabled,
        "aria-label": "Upload files",
        role: "button",
      })}
      className={[
        "flex min-h-48 flex-col items-center justify-center rounded-md",
        "border-2 border-dashed px-4 py-8 text-center transition-colors",
        "sm:min-h-56 sm:p-10",
        stateClasses,
        disabledClasses,
      ].join(" ")}
    >
      <input
        {...getInputProps({
          "aria-describedby": descriptionId,
          "aria-label": "Choose files to upload",
        })}
      />
      <div className="flex flex-col items-center gap-3">
        {active ? (
          <>
            <div className="stat-icon-wrap !w-12 !h-12">
              <FileIcon className="h-5 w-5" aria-hidden="true" />
            </div>
            <p className="text-base font-semibold">{title}</p>
            <p
              id={descriptionId}
              className="max-w-sm text-xs text-muted-foreground"
            >
              {description}
            </p>
          </>
        ) : (
          <>
            <div className="flex items-center justify-center w-12 h-12 rounded-md bg-muted border border-border">
              <Upload
                className="h-5 w-5 text-muted-foreground"
                aria-hidden="true"
              />
            </div>
            <div className="min-w-0 max-w-full">
              <p className="text-base font-semibold [overflow-wrap:anywhere]">
                {title}
              </p>
              <p
                id={descriptionId}
                className="mt-1 text-xs text-muted-foreground"
              >
                {description}
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
