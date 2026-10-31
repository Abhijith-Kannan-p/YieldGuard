import Link from "next/link";
import ShaderBackground from "@/components/ShaderBackground";
import TextRoll from "@/components/TextRoll";
import TodayCard from "@/components/TodayCard";
import AttributionFooter from "@/components/AttributionFooter";

export default function Landing() {
  return (
    <div className="relative isolate flex min-h-screen flex-col overflow-hidden bg-background">
      <ShaderBackground className="absolute inset-0 -z-10" />
      {/* Darkens the shader's light areas (with the neutral background colour) so text stays readable. */}
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,color-mix(in_srgb,var(--background)_72%,transparent)_0%,color-mix(in_srgb,var(--background)_40%,transparent)_70%)]" />

      <main className="flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
        <div className="w-full max-w-3xl rounded-xl bg-background/70 px-5 py-6 backdrop-blur-[2px] sm:px-12">
          <h1 className="text-5xl font-bold tracking-tight text-foreground sm:text-8xl [perspective:600px]">
            <TextRoll>YieldGuard</TextRoll>
          </h1>
          <p className="mt-3 text-lg font-medium text-primary sm:text-xl">From sky to soil, every season</p>
        </div>

        <TodayCard />

        <Link
          href="/advice/"
          className="mt-6 inline-flex min-h-12 items-center rounded-md bg-primary px-6 text-lg font-semibold text-primary-foreground transition hover:bg-accent hover:text-accent-foreground"
        >
          Get advice
        </Link>
      </main>

      <div className="bg-background/70">
        <AttributionFooter />
      </div>
    </div>
  );
}
