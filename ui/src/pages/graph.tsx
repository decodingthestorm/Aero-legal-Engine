import Head from "next/head";
import GraphViewer from "@/components/GraphViewer";
import Layout from "@/components/Layout";

export default function GraphPage() {
  return (
    <Layout>
      <Head>
        <title>Knowledge Graph — Legal Engine Platform</title>
      </Head>
      <h1 className="text-2xl font-semibold text-slate-100">Knowledge Graph</h1>
      <p className="mt-1 text-sm text-slate-400">
        Add statutes, resolve Article VI preemption, and search by semantic similarity.
      </p>
      <div className="mt-6">
        <GraphViewer />
      </div>
    </Layout>
  );
}
