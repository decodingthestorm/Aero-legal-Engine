import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { getHealth } from "@/lib/api";
import { useApiToken } from "@/lib/useApiToken";

export default function Layout({ children }: { children: ReactNode }) {
  const { token, setToken } = useApiToken();
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [tokenInput, setTokenInput] = useState("");

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("ok"))
      .catch(() => setApiStatus("down"));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/60">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <span className="text-lg font-semibold tracking-tight">Legal Engine Platform</span>
            <nav className="flex gap-4 text-sm text-slate-300">
              <Link href="/" className="hover:text-white">
                Dashboard
              </Link>
              <Link href="/graph" className="hover:text-white">
                Knowledge Graph
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span
              className={`h-2 w-2 rounded-full ${
                apiStatus === "ok" ? "bg-emerald-400" : apiStatus === "down" ? "bg-red-400" : "bg-amber-400"
              }`}
              title={`API: ${apiStatus}`}
            />
            <span className="text-slate-400">
              {apiStatus === "checking" ? "Checking API…" : apiStatus === "ok" ? "API online" : "API unreachable"}
            </span>
          </div>
        </div>
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-6 pb-3 text-xs text-slate-400">
          <span>API token (only needed if the gateway's auth is enabled):</span>
          <input
            className="w-64 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100"
            placeholder={token ? "•••• saved ••••" : "paste a bearer token"}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
          />
          <button
            className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600"
            onClick={() => {
              setToken(tokenInput || null);
              setTokenInput("");
            }}
          >
            Save
          </button>
          {token && (
            <button className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700" onClick={() => setToken(null)}>
              Clear
            </button>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  );
}
