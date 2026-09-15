"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type LedgerVersion, type VersionDiffOut } from "@/lib/api";
import type { Experiment } from "@/lib/types";
import { CausalDiff } from "./CausalDiff";
import { LogResultForm } from "./LogResultForm";
import { VersionList } from "./VersionList";

interface LedgerPanelProps {
  projectId: string;
  accessToken: string;
  experiments: Experiment[];
  onLogged?: () => void;
}

/** The Living Ledger: immutable versions, the causal diff for the selected
 * one, and result logging for each pre-registered experiment. */
export function LedgerPanel({ projectId, accessToken, experiments, onLogged }: LedgerPanelProps) {
  const [versions, setVersions] = useState<LedgerVersion[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [diff, setDiff] = useState<VersionDiffOut | null>(null);
  const [loadError, setLoadError] = useState(false);

  const loadVersions = useCallback(async () => {
    try {
      const rows = await api.listVersions(accessToken, projectId);
      setVersions(rows);
      setLoadError(false);
      const latest = rows.reduce<number | null>((m, v) => (m === null || v.version > m ? v.version : m), null);
      setSelected((cur) => (cur !== null && rows.some((v) => v.version === cur) ? cur : latest));
    } catch {
      setLoadError(true);
    }
  }, [accessToken, projectId]);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    setDiff(null);
    api
      .getVersionDiff(accessToken, projectId, selected)
      .then((d) => !cancelled && setDiff(d))
      .catch(() => !cancelled && setDiff({ entries: [], causal_sentence: "" }));
    return () => {
      cancelled = true;
    };
  }, [accessToken, projectId, selected]);

  const loggable = experiments.filter((e) => e.id);

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-[#2A2620]">Versions</h3>
        {loadError ? (
          <p className="text-sm text-[#6B645A]">Could not load ledger versions.</p>
        ) : (
          <VersionList versions={versions} selected={selected} onSelect={setSelected} />
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-6">
        {selected !== null && (
          <section aria-labelledby="diff-title" className="flex flex-col gap-3">
            <h3 id="diff-title" className="text-sm font-semibold text-[#2A2620]">
              What changed in v{selected}
            </h3>
            {diff ? (
              <CausalDiff sentence={diff.causal_sentence} entries={diff.entries} />
            ) : (
              <div className="h-16 animate-pulse rounded-2xl bg-[#EFE6D6]" />
            )}
          </section>
        )}

        <section aria-labelledby="log-title" className="flex flex-col gap-3">
          <h3 id="log-title" className="text-sm font-semibold text-[#2A2620]">
            Log a return-visit result
          </h3>
          {loggable.length === 0 ? (
            <p className="text-sm text-[#6B645A]">No experiments have been proposed for this project yet.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {loggable.map((experiment) => (
                <div key={experiment.id} className="shadow-soft rounded-3xl border border-white/80 bg-white/80 p-4">
                  <LogResultForm
                    experiment={experiment}
                    accessToken={accessToken}
                    onLogged={() => {
                      loadVersions();
                      onLogged?.();
                    }}
                  />
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
