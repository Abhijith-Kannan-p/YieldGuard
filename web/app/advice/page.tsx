import type { Metadata } from "next";
import AdviceApp from "@/components/AdviceApp";

export const metadata: Metadata = {
  title: "Farm advice – YieldGuard",
};

export default function AdvicePage() {
  return <AdviceApp />;
}
