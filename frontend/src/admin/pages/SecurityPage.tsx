import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Table, Td } from "@/admin/components/Table";
import { api, ApiError, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hasPermission, useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/lib/format";

const BLOCKS = ["admin", "ip-blocks"] as const;
const TRUSTED = ["admin", "trusted-networks"] as const;

function ErrorText({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-red-600">
      {error instanceof ApiError ? error.message : t("common.loadError")}
    </p>
  );
}

/** «Безопасность» (§13.4): блокировки IP и подсетей, доверенные подсети. */
export function SecurityPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canManage = hasPermission(me, "admin.security.manage");
  const queryClient = useQueryClient();
  const [expired, setExpired] = useState(false);
  const [cidr, setCidr] = useState("");
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState("");
  const [trustCidr, setTrustCidr] = useState("");
  const [note, setNote] = useState("");

  const blocks = useQuery({
    queryKey: [...BLOCKS, expired],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/admin/ip-blocks", { params: { query: { include_expired: expired } } }),
      ),
  });
  const trusted = useQuery({
    queryKey: TRUSTED,
    queryFn: async () => unwrap(await api.GET("/api/admin/trusted-networks")),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: BLOCKS });
    void queryClient.invalidateQueries({ queryKey: TRUSTED });
  };
  const block = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/ip-blocks", {
          body: { cidr, reason, minutes: minutes ? Number(minutes) : null },
        }),
      ),
    onSuccess: () => {
      setCidr("");
      setReason("");
      setMinutes("");
      refresh();
    },
  });
  const unblock = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/admin/ip-blocks/{block_id}", { params: { path: { block_id: id } } }),
      );
    },
    onSuccess: refresh,
  });
  const trust = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/admin/trusted-networks", {
          body: { cidr: trustCidr, note: note || null },
        }),
      ),
    onSuccess: () => {
      setTrustCidr("");
      setNote("");
      refresh();
    },
  });
  const untrust = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/admin/trusted-networks/{network_id}", {
          params: { path: { network_id: id } },
        }),
      );
    },
    onSuccess: refresh,
  });
  const submitBlock = (event: SubmitEvent) => {
    event.preventDefault();
    block.mutate();
  };
  const submitTrust = (event: SubmitEvent) => {
    event.preventDefault();
    trust.mutate();
  };

  return (
    <section className="flex max-w-5xl flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("admin.nav.security")}</h1>
      <p className="text-sm text-muted-foreground">{t("admin.security.hint")}</p>

      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">{t("admin.security.blocks")}</h2>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={expired}
            onChange={(e) => {
              setExpired(e.target.checked);
            }}
          />
          {t("admin.security.showExpired")}
        </label>
      </div>
      <Table
        head={[
          t("admin.security.cidr"),
          t("admin.security.reason"),
          t("admin.security.until"),
          t("admin.security.source"),
          "",
        ]}
      >
        {(blocks.data ?? []).map((b) => (
          <tr key={b.id} data-testid="ip-block-row">
            <Td>
              <code>{b.cidr}</code>
            </Td>
            <Td className="max-w-sm">{b.reason}</Td>
            <Td className="whitespace-nowrap">
              {b.until ? formatDateTime(b.until) : t("admin.security.forever")}
              {!b.active && <Badge tone="muted">{t("admin.security.expired")}</Badge>}
            </Td>
            <Td className="text-xs">
              {t(`admin.security.sources.${b.source}`, { defaultValue: b.source })}
              {b.created_by ? ` · ${b.created_by}` : ""}
            </Td>
            <Td>
              {canManage && b.active && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    unblock.mutate(b.id);
                  }}
                >
                  {t("admin.security.unblock")}
                </Button>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      {blocks.isSuccess && blocks.data.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("admin.security.empty")}</p>
      )}
      {canManage && (
        <form
          onSubmit={submitBlock}
          className="flex flex-wrap items-center gap-2"
          data-testid="ip-block-form"
        >
          <Input
            required
            className="w-56"
            aria-label={t("admin.security.cidr")}
            placeholder={t("admin.security.cidrPlaceholder")}
            value={cidr}
            onChange={(e) => {
              setCidr(e.target.value);
            }}
          />
          <Input
            required
            className="w-64"
            aria-label={t("admin.security.reason")}
            placeholder={t("admin.security.reason")}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <Input
            type="number"
            min={1}
            className="w-48"
            aria-label={t("admin.security.minutes")}
            placeholder={t("admin.security.minutes")}
            value={minutes}
            onChange={(e) => {
              setMinutes(e.target.value);
            }}
          />
          <Button type="submit" disabled={block.isPending}>
            {t("admin.security.block")}
          </Button>
        </form>
      )}
      <ErrorText error={block.error ?? unblock.error} />

      <h2 className="pt-4 font-medium">{t("admin.security.trusted")}</h2>
      <Table
        head={[t("admin.security.cidr"), t("admin.security.note"), t("admin.security.author"), ""]}
      >
        {(trusted.data ?? []).map((n) => (
          <tr key={n.id} data-testid="trusted-row">
            <Td>
              <code>{n.cidr}</code>
            </Td>
            <Td>{n.note ?? "—"}</Td>
            <Td className="text-xs">{n.created_by ?? "—"}</Td>
            <Td>
              {canManage && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    untrust.mutate(n.id);
                  }}
                >
                  {t("admin.security.untrust")}
                </Button>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      {canManage && (
        <form onSubmit={submitTrust} className="flex flex-wrap items-center gap-2">
          <Input
            required
            className="w-56"
            aria-label={`${t("admin.security.trusted")}: ${t("admin.security.cidr")}`}
            placeholder={t("admin.security.cidrPlaceholder")}
            value={trustCidr}
            onChange={(e) => {
              setTrustCidr(e.target.value);
            }}
          />
          <Input
            className="w-64"
            aria-label={t("admin.security.note")}
            placeholder={t("admin.security.note")}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
          <Button type="submit" variant="outline" disabled={trust.isPending}>
            {t("admin.security.trust")}
          </Button>
        </form>
      )}
      <ErrorText error={trust.error ?? untrust.error} />
    </section>
  );
}
