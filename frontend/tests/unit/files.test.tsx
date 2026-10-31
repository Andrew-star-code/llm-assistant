import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { attachmentSummary, checkFile, useAttachments } from "@/features/composer/attachments";
import type { FileOut } from "@/features/files/api";
import { parseDelimited } from "@/features/files/delimited";
import { extensionOf, formatBytes } from "@/lib/format";

import { json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const LIMITS = { max_file_mb: 1, max_files_per_message: 2, accept: ["docx", "pdf", "txt", "csv"] };

const READY: FileOut = {
  id: "f1",
  kind: "upload",
  filename: "Отчёт.docx",
  mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  file_type: "docx",
  size: 10,
  parse_status: "processing",
  parse_error: null,
  pages: null,
  has_preview: false,
  chat_id: null,
  message_id: null,
  created_at: "2026-10-31T10:00:00Z",
};

/** Фейковый XHR: «загружает» файл и отвечает 201 с записью файла. */
class FakeXhr {
  static response: unknown = READY;
  static status = 201;
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  response: unknown = null;
  responseType = "";
  withCredentials = false;
  headers: Record<string, string> = {};
  open() {}
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  abort() {}
  send() {
    setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
      this.status = FakeXhr.status;
      this.response = FakeXhr.response;
      this.onload?.();
    }, 0);
  }
}

afterEach(() => {
  useAttachments.setState({ lists: {} });
});

describe("Утилиты файлов", () => {
  it("форматирует размер и расширение", () => {
    expect(formatBytes(512)).toBe("512 Б");
    expect(formatBytes(1536)).toBe("1,5 КБ");
    expect(formatBytes(50 * 1024 * 1024)).toBe("50 МБ");
    expect(extensionOf("Отчёт.Final.DOCX")).toBe("docx");
  });

  it("разбирает CSV с кавычками и точкой с запятой", () => {
    expect(parseDelimited('Имя;Сумма\n"Иванов; И.";"1 ""200"""\n', "csv")).toEqual([
      ["Имя", "Сумма"],
      ["Иванов; И.", '1 "200"'],
    ]);
    expect(parseDelimited("a\tb\n1\t2", "tsv")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("проверяет файл до загрузки", () => {
    const small = new File(["x"], "a.docx");
    expect(checkFile(small, LIMITS, 0)).toBeNull();
    expect(checkFile(small, LIMITS, 2)).toBe("tooMany");
    expect(checkFile(new File(["x"], "a.exe"), LIMITS, 0)).toBe("unsupported");
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "big.pdf");
    expect(checkFile(big, LIMITS, 0)).toBe("tooLarge");
  });

  it("отправляет только прочитанные файлы и ждёт обработку", () => {
    const base = { name: "a", size: 1, progress: 1, error: null };
    const ready = { ...base, key: "1", status: "ready" as const, file: { ...READY, id: "r" } };
    const failed = { ...base, key: "2", status: "error" as const, file: null };
    expect(attachmentSummary([ready, failed])).toEqual({ ids: ["r"], pending: false });
    const reading = { ...base, key: "3", status: "processing" as const, file: null };
    expect(attachmentSummary([ready, reading]).pending).toBe(true);
  });
});

describe("Вложения в поле ввода", () => {
  it("загружает файл, ждёт разбор и отправляет его id", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    let polls = 0;
    const calls = mockFetch({
      "GET /api/auth/me": () => json(ME),
      "GET /ready": () => json({ status: "ready", checks: {} }),
      "GET /api/models/chat": () => json({ thinking_available: false, thinking_default: false }),
      "GET /api/folders": () => json([]),
      "GET /api/chats": () => json({ items: [], next_cursor: null }),
      "GET /api/auth/csrf": () => json({ csrf_token: "t" }),
      "GET /api/files/limits": () => json(LIMITS),
      "GET /api/files/f1": () => {
        polls += 1;
        return json({ ...READY, parse_status: "ready", pages: 3 });
      },
      "POST /api/chats": () => json({ id: "c9", messages: [] }, 201),
      "POST /api/chats/c9/messages": () => json({ error: { code: "x", message: "стоп" } }, 400),
    });
    renderApp("/");
    await screen.findByTestId("greeting");
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/api/files/limits"))).toBe(true);
    });

    const input = screen.getByTestId("file-input");
    await userEvent.upload(input, [
      new File(["hello"], "Отчёт.docx"),
      new File([new Uint8Array(2 * 1024 * 1024)], "Большой.pdf"),
    ]);
    const chips = await screen.findAllByTestId("attachment-chip");
    expect(chips).toHaveLength(2);
    // Слишком большой файл отклонён сразу, без загрузки.
    expect(chips[1]).toHaveAttribute("data-status", "error");
    expect(chips[1]).toHaveTextContent("ошибка: файл больше 1 МБ");
    expect(chips[0]).toHaveTextContent("читаю…");

    await userEvent.type(screen.getByTestId("composer-input"), "Что в отчёте?");
    expect(screen.getByTestId("send-button")).toBeDisabled();
    await waitFor(
      () => {
        expect(screen.getAllByTestId("attachment-chip")[0]).toHaveTextContent("готово");
      },
      { timeout: 3000 },
    );
    expect(polls).toBeGreaterThan(0);
    await userEvent.click(screen.getByTestId("send-button"));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/messages"))).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/messages"));
    expect(await post?.json()).toMatchObject({ content: "Что в отчёте?", attachment_ids: ["f1"] });
    expect(screen.queryAllByTestId("attachment-chip")).toHaveLength(0);
  });
});
