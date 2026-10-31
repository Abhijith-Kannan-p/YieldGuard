import Link from "next/link";
import ShaderBackground from "@/components/ShaderBackground";
import TextRoll from "@/components/TextRoll";
import TodayCard from "@/components/TodayCard";
import AttributionFooter from "@/components/AttributionFooter";

export default function Landing() {
  return (
    <div className="relative isolate flex min-h-screen flex-col overflow-hidden bg-background">
      <ShaderBackground className="absolute inset-0 -z-10" />
      {/* Darkens the shader's light areas so white text stays readable everywhere. */}
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,rgba(17,17,17,0.72)_0%,rgba(17,17,17,0.4)_70%)]" />

      <main className="flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
        <div className="w-full max-w-3xl rounded-xl bg-black/35 px-5 py-6 backdrop-blur-[2px] sm:px-12">
          <h1 className="text-5xl font-bold tracking-tight text-white sm:text-8xl [perspective:600px]">
            <TextRoll>YieldGuard</TextRoll>
          </h1>
          <p className="mt-3 text-lg font-medium text-[#c9d8cc] sm:text-xl">From sky to soil, every season</p>
        </div>

        <TodayCard />

        <Link
          href="/advice/"
          className="mt-6 inline-flex min-h-12 items-center rounded-md bg-primary px-6 text-lg font-semibold text-primary-foreground transition hover:brightness-110"
        >
          Get advice
        </Link>
      </main>

      <div className="bg-black/50">
        <AttributionFooter />
      </div>
    </div>
  );
}
