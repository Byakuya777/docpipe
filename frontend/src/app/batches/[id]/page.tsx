"use client";

import { useParams } from "next/navigation";
import { BatchProgress } from "@/components/BatchProgress";

export default function BatchPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-12">
      <BatchProgress batchId={id} />
    </div>
  );
}
