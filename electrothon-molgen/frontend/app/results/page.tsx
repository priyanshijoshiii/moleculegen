"use client";

import Script from "next/script";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface MoleculeResult {
  smiles: string;
  sdf_string?: string;
  qed: number;
  logp: number;
  tpsa?: number;
  mw?: number;
  lipinski?: number;
  reward_score?: number;
}

interface GenerateResponse {
  prompt: string;
  generator_backend: string;
  generator_model?: string | null;
  attempted_count: number;
  valid_count: number;
  returned_count: number;
  validity_pct: number;
  molecules: MoleculeResult[];
}

function StatTile({
  label,
  value,
  caption
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div className="glass-panel rounded-[1.3rem] p-4">
      <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">{label}</div>
      <div className="mt-3 text-3xl font-semibold text-white">{value}</div>
      <div className="mt-2 text-xs text-slate-400">{caption}</div>
    </div>
  );
}

export default function ResultsPage() {
  const router = useRouter();
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const viewerInstanceRef = useRef<any>(null);

  const [data, setData] = useState<GenerateResponse | null>(null);
  const [goal, setGoal] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [scriptLoaded, setScriptLoaded] = useState(false);

  const canRender3D = useMemo(() => typeof window !== "undefined", []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.sessionStorage.getItem("moleculeResults");
    const storedGoal = window.sessionStorage.getItem("molecularGoal");
    if (!stored) {
      router.replace("/");
      return;
    }

    try {
      const parsed = JSON.parse(stored) as GenerateResponse;
      setData(parsed);
    } catch {
      router.replace("/");
      return;
    }

    setGoal(storedGoal);
  }, [router]);

  useEffect(() => {
    if (typeof window !== "undefined" && window.$3Dmol) {
      setScriptLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!canRender3D || !scriptLoaded || !viewerRef.current || !window.$3Dmol) return;

    if (!viewerInstanceRef.current) {
      viewerInstanceRef.current = window.$3Dmol.createViewer(viewerRef.current, {
        backgroundColor: "#040814"
      });
    }

    const viewer = viewerInstanceRef.current;
    if (!viewer) return;

    const mol = data?.molecules?.[selectedIndex];
    if (!mol?.sdf_string) return;

    try {
      viewer.clear();
      viewer.addModel(mol.sdf_string, "sdf");
      viewer.setStyle({}, { stick: { radius: 0.22 }, sphere: { scale: 0.28 }, colorscheme: "cpk" });
      viewer.resize();
      viewer.zoomTo();
      viewer.zoom(0.88, 0);
      viewer.spin(true);
      viewer.render();
    } catch {
      // Ignore malformed viewer payloads and preserve the rest of the analysis screen.
    }
  }, [canRender3D, scriptLoaded, data, selectedIndex]);

  useEffect(() => {
    if (!canRender3D || !viewerRef.current || typeof ResizeObserver === "undefined") return;

    const element = viewerRef.current;
    const observer = new ResizeObserver(() => {
      const viewer = viewerInstanceRef.current;
      if (!viewer) return;

      try {
        viewer.resize();
        viewer.zoomTo();
        viewer.zoom(0.88, 0);
        viewer.render();
      } catch {
        // Ignore transient layout churn while the page is still mounting.
      }
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, [canRender3D]);

  const molecules = data?.molecules ?? [];
  const selected = molecules[selectedIndex];

  return (
    <>
      <Script
        src="https://3Dmol.org/build/3Dmol-min.js"
        strategy="afterInteractive"
        onLoad={() => setScriptLoaded(true)}
      />
      <main className="relative min-h-screen overflow-hidden px-6 py-8 text-slate-50">
        <div className="pointer-events-none absolute left-[-10rem] top-24 h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="pointer-events-none absolute right-[-8rem] top-24 h-96 w-96 rounded-full bg-emerald-400/10 blur-3xl" />

        <div className="relative mx-auto flex w-full max-w-7xl flex-col gap-8">
          <header className="grid gap-8 lg:grid-cols-[1.15fr,0.85fr] lg:items-end">
            <div className="space-y-5">
              <div className="glass-badge inline-flex items-center gap-3 rounded-full px-4 py-2">
                <span className="h-2 w-2 rounded-full bg-cyan-300 shadow-[0_0_18px_rgba(103,232,249,0.8)]" />
                <span className="text-sm font-semibold text-cyan-100">Discovery Lab</span>
              </div>

              <div className="space-y-4">
                <h1 className="text-5xl font-semibold leading-[0.95] text-white sm:text-6xl">
                  Generated Candidate Space
                </h1>
                <p className="max-w-3xl text-lg leading-8 text-slate-300">
                  Review the ranked structures, inspect the conformer geometry, and compare descriptor
                  alignment against the current medicinal chemistry brief.
                </p>
              </div>
            </div>

            <div className="flex justify-start lg:justify-end">
              <button
                onClick={() => router.push("/")}
                className="glass-badge inline-flex items-center justify-center rounded-full px-5 py-3 text-sm font-semibold text-slate-100 transition hover:border-cyan-300/30 hover:text-white"
              >
                Back to Design Studio
              </button>
            </div>
          </header>

          <section className="glass-panel-strong overflow-hidden rounded-[2rem] p-6 sm:p-8">
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
              <div className="min-w-0 rounded-[1.45rem] border border-slate-800/80 bg-slate-950/35 p-5">
                <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Research Brief</div>
                <div className="glass-scrollbar mt-4 max-h-40 overflow-y-auto pr-2 text-sm leading-7 text-slate-200">
                  {goal ? goal : "No molecular brief was captured for this run."}
                </div>
              </div>

              <div className="grid min-w-0 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatTile
                  label="Valid molecules"
                  value={data ? String(data.valid_count) : "--"}
                  caption="Candidates surviving chemistry filters"
                />
                <StatTile
                  label="Attempted"
                  value={data ? String(data.attempted_count) : "--"}
                  caption="Structures sampled during the run"
                />
                <StatTile
                  label="Pass rate"
                  value={data ? `${data.validity_pct.toFixed(1)}%` : "--"}
                  caption="Valid fraction of sampled candidates"
                />
                <StatTile
                  label="Backend"
                  value={data?.generator_backend ?? "--"}
                  caption={data?.generator_model ?? "No generator metadata available"}
                />
              </div>
            </div>
          </section>

          <section className="grid items-start gap-8 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.85fr)]">
            <div className="glass-panel-strong min-w-0 overflow-hidden rounded-[2rem] p-6 sm:p-8">
              <div className="flex flex-col gap-4 border-b border-slate-800/80 pb-5 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Conformation Viewer</div>
                  <h2 className="mt-2 text-2xl font-semibold text-white">3D Candidate Inspection</h2>
                </div>
                <div className="shrink-0 rounded-full border border-cyan-400/12 bg-slate-950/45 px-4 py-2 font-mono text-sm text-cyan-100">
                  {selected?.reward_score != null ? `score ${selected.reward_score.toFixed(3)}` : "no score"}
                </div>
              </div>

              <div className="mt-6 overflow-hidden rounded-[1.6rem] border border-slate-800/80 bg-[radial-gradient(circle_at_top,rgba(103,232,249,0.08),transparent_40%),linear-gradient(180deg,rgba(4,8,20,0.78),rgba(2,6,23,0.92))] p-4">
                <div className="min-w-0 overflow-hidden rounded-[1.3rem] border border-cyan-400/8 bg-slate-950">
                  <div
                    ref={viewerRef}
                    id="gldiv"
                    className="molecule-viewer-stage relative isolate h-[360px] w-full max-w-full min-w-0 overflow-hidden rounded-[1.3rem] sm:h-[440px] xl:h-[520px]"
                  />
                </div>
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                <div className="min-w-0 rounded-[1.35rem] border border-slate-800/80 bg-slate-950/35 p-5">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Selected Structure</div>
                  <div className="mt-4 text-sm leading-7 text-slate-300">
                    {selected?.smiles ? (
                      <>
                        <span className="font-semibold text-white">SMILES:</span>{" "}
                        <span className="break-all font-mono text-slate-200">{selected.smiles}</span>
                      </>
                    ) : (
                      "Select a candidate to inspect its 3D geometry."
                    )}
                  </div>
                  <div className="mt-4 text-xs text-slate-500">
                    The viewer is configured for exploratory shape inspection, not production docking or
                    binding validation.
                  </div>
                </div>

                <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                  <StatTile
                    label="QED"
                    value={selected?.qed != null ? selected.qed.toFixed(3) : "--"}
                    caption="Drug-likeness estimate"
                  />
                  <StatTile
                    label="logP"
                    value={selected?.logp != null ? selected.logp.toFixed(2) : "--"}
                    caption="Lipophilicity readout"
                  />
                  <StatTile
                    label="TPSA"
                    value={selected?.tpsa != null ? selected.tpsa.toFixed(1) : "--"}
                    caption="Polar surface area"
                  />
                  <StatTile
                    label="MW"
                    value={selected?.mw != null ? selected.mw.toFixed(0) : "--"}
                    caption="Molecular weight window"
                  />
                </div>
              </div>
            </div>

            <aside className="glass-panel min-w-0 self-start rounded-[2rem] p-6 sm:p-8">
              <div className="flex items-end justify-between border-b border-slate-800/80 pb-5">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Candidate Matrix</div>
                  <h2 className="mt-2 text-2xl font-semibold text-white">Top Ranked Molecules</h2>
                </div>
                <div className="text-[11px] uppercase tracking-[0.24em] text-slate-600">Click to inspect</div>
              </div>

              <div className="glass-scrollbar mt-6 max-h-[920px] min-w-0 space-y-4 overflow-y-auto pr-2">
                {molecules.map((mol, idx) => {
                  const isActive = idx === selectedIndex;
                  return (
                    <button
                      key={mol.smiles}
                      onClick={() => setSelectedIndex(idx)}
                      className={`w-full rounded-[1.4rem] border p-5 text-left transition ${
                        isActive
                          ? "border-cyan-300/28 bg-[linear-gradient(180deg,rgba(10,40,49,0.62),rgba(8,24,40,0.82))] shadow-[0_18px_48px_rgba(34,211,238,0.08)]"
                          : "border-slate-800/90 bg-slate-950/32 hover:border-cyan-400/20 hover:bg-slate-900/50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                            Rank {idx + 1}
                          </div>
                          <div className="mt-2 text-xl font-semibold text-white">Candidate {idx + 1}</div>
                        </div>
                        <div className="rounded-full border border-emerald-300/10 bg-slate-950/55 px-3 py-1 font-mono text-sm text-emerald-200">
                          {mol.reward_score != null ? mol.reward_score.toFixed(3) : "--"}
                        </div>
                      </div>

                      <div className="mt-4 overflow-hidden rounded-[1rem] border border-slate-800/70 bg-slate-950/45 px-3 py-3 font-mono text-[11px] leading-6 text-slate-300">
                        {mol.smiles}
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full border border-slate-700/80 bg-slate-950/45 px-3 py-1 text-slate-300">
                          QED {mol.qed?.toFixed(3) ?? "--"}
                        </span>
                        <span className="rounded-full border border-slate-700/80 bg-slate-950/45 px-3 py-1 text-slate-300">
                          logP {mol.logp?.toFixed(2) ?? "--"}
                        </span>
                        {typeof mol.tpsa === "number" ? (
                          <span className="rounded-full border border-slate-700/80 bg-slate-950/45 px-3 py-1 text-slate-300">
                            TPSA {mol.tpsa.toFixed(1)}
                          </span>
                        ) : null}
                        {typeof mol.mw === "number" ? (
                          <span className="rounded-full border border-slate-700/80 bg-slate-950/45 px-3 py-1 text-slate-300">
                            MW {mol.mw.toFixed(0)}
                          </span>
                        ) : null}
                        {typeof mol.lipinski === "number" ? (
                          <span
                            className={`rounded-full border px-3 py-1 ${
                              mol.lipinski === 0
                                ? "border-emerald-300/16 bg-emerald-500/8 text-emerald-200"
                                : mol.lipinski === 1
                                  ? "border-amber-300/16 bg-amber-500/8 text-amber-200"
                                  : "border-rose-300/16 bg-rose-500/8 text-rose-200"
                            }`}
                          >
                            {mol.lipinski === 0 ? "Lipinski clean" : `Lipinski ${mol.lipinski} violations`}
                          </span>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            </aside>
          </section>
        </div>
      </main>
    </>
  );
}
