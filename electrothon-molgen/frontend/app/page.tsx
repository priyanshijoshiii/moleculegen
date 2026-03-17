"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

interface MoleculeResult {
  smiles: string;
  sdf_string?: string;
  qed: number;
  logp: number;
  tpsa: number;
  mw: number;
  lipinski: number;
  reward_score: number;
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

const API_BASE_URL = (() => {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  return process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "";
})();
const GENERATION_BATCH_SIZE = 50;
const RETURNED_CANDIDATE_COUNT = 5;

function MetricCard({
  label,
  value,
  caption
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div className="glass-panel rounded-[1.35rem] p-4">
      <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">{label}</div>
      <div className="mt-3 text-3xl font-semibold text-white">{value}</div>
      <div className="mt-2 text-xs text-slate-400">{caption}</div>
    </div>
  );
}

function DescriptorControl({
  label,
  value,
  unit,
  min,
  max,
  step,
  onChange,
  hint
}: {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  step: number;
  onChange: (next: number) => void;
  hint: string;
}) {
  const formatted =
    step >= 1 ? value.toFixed(0) : step >= 0.1 ? value.toFixed(1) : value.toFixed(2);

  return (
    <div className="glass-panel rounded-[1.25rem] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">{label}</div>
          <div className="mt-1 text-xs text-slate-400">{hint}</div>
        </div>
        <div className="rounded-full border border-cyan-400/20 bg-slate-950/60 px-3 py-1 font-mono text-sm text-cyan-100">
          {formatted} {unit}
        </div>
      </div>
      <div className="mt-5">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="scientific-slider"
        />
        <div className="mt-2 flex justify-between text-[10px] uppercase tracking-[0.22em] text-slate-600">
          <span>{min}</span>
          <span>{max}</span>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();

  const [molecularGoal, setMolecularGoal] = useState("");
  const [qed, setQed] = useState(0.9);
  const [logp, setLogp] = useState(2.0);
  const [tpsa, setTpsa] = useState(70.0);
  const [mw, setMw] = useState(320.0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);

    try {
      if (!API_BASE_URL) {
        throw new Error("Frontend API base URL is missing. Set NEXT_PUBLIC_API_BASE_URL in Vercel.");
      }

      const body = {
        prompt: molecularGoal,
        qed,
        logp,
        tpsa,
        mw,
        n: GENERATION_BATCH_SIZE,
        top_k: RETURNED_CANDIDATE_COUNT
      };

      const res = await fetch(`${API_BASE_URL}/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        let backendMessage = "";
        try {
          const payload = (await res.json()) as { detail?: string };
          backendMessage = payload?.detail ?? "";
        } catch {
          backendMessage = "";
        }

        throw new Error(backendMessage || `Backend error (${res.status})`);
      }

      const data = (await res.json()) as GenerateResponse;
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("moleculeResults", JSON.stringify(data));
        window.sessionStorage.setItem("molecularGoal", molecularGoal);
      }

      router.push("/results");
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Failed to generate molecules";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden px-6 py-8 text-slate-50">
      <div className="pointer-events-none absolute left-[-8rem] top-16 h-72 w-72 rounded-full bg-emerald-400/10 blur-3xl" />
      <div className="pointer-events-none absolute right-[-6rem] top-24 h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" />

      <div className="relative mx-auto flex w-full max-w-7xl flex-col gap-10">
        <header className="grid gap-8 lg:grid-cols-[1.2fr,0.8fr] lg:items-end">
          <div className="space-y-6">
            <div className="glass-badge inline-flex items-center gap-3 rounded-full px-4 py-2">
              <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(52,211,153,0.9)]" />
              <span className="text-sm font-semibold text-emerald-200">Computational Design Studio</span>
            </div>

            <div className="space-y-4">
              <h1 className="max-w-4xl text-5xl font-semibold leading-[0.95] text-white sm:text-6xl">
                Molecular Design Studio
              </h1>
              <p className="max-w-3xl text-lg leading-8 text-slate-300">
                Configure an in silico design brief, tune target descriptor windows, and query the
                learned molecular prior through a glass-lab interface built for medicinal chemistry
                exploration.
              </p>
            </div>

            <div className="flex flex-wrap gap-3 text-xs text-slate-300">
              <div className="glass-badge rounded-full px-4 py-2">Learned molecular prior</div>
              <div className="glass-badge rounded-full px-4 py-2">RDKit descriptor screening</div>
              <div className="glass-badge rounded-full px-4 py-2">3D conformer generation</div>
            </div>
          </div>

          <div className="glass-panel-strong rounded-[1.8rem] p-6">
            <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Protocol Summary</div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <MetricCard label="Batch size" value={String(GENERATION_BATCH_SIZE)} caption="Candidates sampled per run" />
              <MetricCard label="Top hits" value={String(RETURNED_CANDIDATE_COUNT)} caption="Returned to the analysis lab" />
            </div>
            <div className="mt-5 rounded-[1.3rem] border border-cyan-400/10 bg-slate-950/40 p-4 text-sm leading-7 text-slate-300">
              The current pipeline uses a learned generative model to sample structures, then ranks
              candidates against your descriptor envelope before producing viewable 3D conformers.
            </div>
          </div>
        </header>

        <section className="grid gap-8 lg:grid-cols-[1.25fr,0.85fr]">
          <div className="glass-panel-strong rounded-[2rem] p-7 sm:p-8">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-[0.28em] text-slate-500">Design Brief</div>
                <h2 className="mt-2 text-2xl font-semibold text-white">Protocol Input</h2>
              </div>
              <div className="rounded-full border border-cyan-400/12 bg-slate-950/45 px-4 py-2 text-[11px] uppercase tracking-[0.22em] text-slate-400">
                Tune descriptors, then launch the run
              </div>
            </div>

            <div className="mt-8 grid gap-8 xl:grid-cols-[1.15fr,0.85fr]">
              <div className="space-y-6">
                <div className="glass-panel rounded-[1.6rem] p-5">
                  <label className="text-[11px] uppercase tracking-[0.24em] text-slate-500">
                    Molecular Goal
                  </label>
                  <textarea
                    value={molecularGoal}
                    onChange={(e) => setMolecularGoal(e.target.value)}
                    placeholder="Describe the scaffold, route of administration, permeability profile, and any medicinal chemistry intent you want the generator to bias toward."
                    rows={6}
                    className="glass-scrollbar mt-4 w-full resize-none rounded-[1.25rem] border border-slate-700/70 bg-slate-950/55 px-4 py-4 text-base leading-7 text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400/40 focus:ring-2 focus:ring-cyan-400/20"
                  />
                </div>

                <div className="glass-panel rounded-[1.6rem] p-5">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Design Notes</div>
                  <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div className="rounded-[1.1rem] border border-slate-800/90 bg-slate-950/35 p-4">
                      <div className="text-sm font-semibold text-white">Prompt heuristics</div>
                      <p className="mt-2 text-sm leading-6 text-slate-400">
                        Terms like oral, CNS, brain, polar, soluble, lipophilic, and fragment-like are
                        currently interpreted as soft biases during scoring.
                      </p>
                    </div>
                    <div className="rounded-[1.1rem] border border-slate-800/90 bg-slate-950/35 p-4">
                      <div className="text-sm font-semibold text-white">Screening behavior</div>
                      <p className="mt-2 text-sm leading-6 text-slate-400">
                        The backend keeps molecules inside practical descriptor windows before computing
                        rewards, so unrealistic settings will naturally collapse the candidate pool.
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <DescriptorControl
                  label="QED"
                  value={qed}
                  unit="score"
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={setQed}
                  hint="Composite drug-likeness objective"
                />
                <DescriptorControl
                  label="logP"
                  value={logp}
                  unit="log units"
                  min={-1}
                  max={6}
                  step={0.1}
                  onChange={setLogp}
                  hint="Lipophilicity and membrane affinity"
                />
                <DescriptorControl
                  label="TPSA"
                  value={tpsa}
                  unit="A^2"
                  min={0}
                  max={150}
                  step={1}
                  onChange={setTpsa}
                  hint="Topological polar surface area"
                />
                <DescriptorControl
                  label="Molecular Weight"
                  value={mw}
                  unit="Da"
                  min={150}
                  max={550}
                  step={5}
                  onChange={setMw}
                  hint="Mass window for tractable leads"
                />
              </div>
            </div>

            {error ? (
              <div className="mt-6 rounded-[1.3rem] border border-rose-500/20 bg-rose-950/40 px-5 py-4 text-sm text-rose-200">
                {error}
              </div>
            ) : null}

            <div className="mt-8 flex flex-col gap-4 border-t border-slate-800/80 pt-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Execution Mode</div>
                <div className="text-sm text-slate-300">
                  Sampling {GENERATION_BATCH_SIZE} candidates and returning the top {RETURNED_CANDIDATE_COUNT} ranked hits.
                </div>
              </div>
              <button
                onClick={handleGenerate}
                disabled={loading}
                className="inline-flex items-center justify-center rounded-full border border-emerald-300/20 bg-[linear-gradient(135deg,rgba(52,211,153,0.96),rgba(34,211,238,0.92))] px-7 py-3 text-sm font-semibold text-slate-950 shadow-[0_12px_36px_rgba(16,185,129,0.28)] transition hover:scale-[1.01] hover:shadow-[0_16px_48px_rgba(52,211,153,0.32)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Sampling Chemical Space..." : "Run Molecular Design"}
              </button>
            </div>
          </div>

          <aside className="glass-panel rounded-[2rem] p-7 sm:p-8">
            <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Scientific Snapshot</div>
            <h2 className="mt-2 text-2xl font-semibold text-white">Current Target Envelope</h2>
            <p className="mt-4 text-sm leading-7 text-slate-300">
              This control state favors compact, high-QED compounds with moderate lipophilicity and
              balanced polarity. Use the cards below to observe how the target envelope shifts before
              launching a run.
            </p>

            <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <MetricCard label="QED target" value={qed.toFixed(2)} caption="Higher values bias toward stronger drug-likeness" />
              <MetricCard label="logP target" value={logp.toFixed(2)} caption="Centers the hydrophobicity window" />
              <MetricCard label="TPSA target" value={tpsa.toFixed(1)} caption="Controls polar surface exposure" />
              <MetricCard label="MW target" value={mw.toFixed(0)} caption="Keeps designs within mass range" />
            </div>

            <div className="mt-8 rounded-[1.4rem] border border-cyan-400/10 bg-slate-950/35 p-5">
              <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Run Path</div>
              <div className="mt-4 space-y-3 text-sm text-slate-300">
                <div className="flex items-start gap-3">
                  <span className="mt-1 h-2 w-2 rounded-full bg-cyan-300" />
                  <span>Learned model samples candidate SMILES sequences.</span>
                </div>
                <div className="flex items-start gap-3">
                  <span className="mt-1 h-2 w-2 rounded-full bg-emerald-300" />
                  <span>RDKit validates chemistry, computes descriptors, and ranks against your envelope.</span>
                </div>
                <div className="flex items-start gap-3">
                  <span className="mt-1 h-2 w-2 rounded-full bg-lime-300" />
                  <span>The top hits receive 3D conformers for downstream inspection.</span>
                </div>
              </div>
            </div>
          </aside>
        </section>
      </div>

      {loading ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-6 backdrop-blur-xl">
          <div className="glass-panel-strong w-full max-w-xl rounded-[1.8rem] p-8 text-center">
            <div className="text-[11px] uppercase tracking-[0.32em] text-cyan-200">Active Simulation</div>
            <h2 className="mt-4 text-3xl font-semibold text-white">Generating Candidate Molecules</h2>
            <p className="mt-4 text-base leading-7 text-slate-300">
              Sampling from the learned chemical prior, screening descriptor windows, and assembling
              3D conformers for the highest-ranked structures.
            </p>
          </div>
        </div>
      ) : null}
    </main>
  );
}
