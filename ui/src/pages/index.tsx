import Head from "next/head";
import Layout from "@/components/Layout";
import ProofInspector from "@/components/ProofInspector";
import SimulationCard from "@/components/SimulationCard";

export default function Home() {
  return (
    <Layout>
      <Head>
        <title>Legal Engine Platform</title>
      </Head>
      <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
      <p className="mt-1 text-sm text-slate-400">
        Formal verification and game-theoretic simulation against the Legal Engine API.
      </p>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ProofInspector />
        <SimulationCard />
      </div>
    </Layout>
  );
}
