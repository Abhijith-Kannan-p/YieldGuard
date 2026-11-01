import type { Metadata } from "next";
import MandiApp from "@/components/MandiApp";

export const metadata: Metadata = {
  title: "Mandi prices – YieldGuard",
};

export default function MandiPage() {
  return <MandiApp />;
}
