import { Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Загрузка нескольких файлов перетаскиванием или кнопкой (§7.8). */
export function UploadZone({
  onFiles,
  busy,
  accept,
}: {
  onFiles: (files: File[]) => void;
  busy: boolean;
  accept?: string;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    onFiles(Array.from(event.dataTransfer.files));
  };
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground",
        over && "border-primary bg-primary/5",
      )}
      data-testid="kb-upload-zone"
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => {
        setOver(false);
      }}
      onDrop={onDrop}
    >
      <Upload className="size-5" aria-hidden />
      <span>{t("kb.dropHere")}</span>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={accept}
        data-testid="kb-file-input"
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
        {t("kb.chooseFiles")}
      </Button>
    </div>
  );
}
