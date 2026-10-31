import Link from "next/link";
import LandingBackground from "@/components/LandingBackground";
import TextRoll from "@/components/TextRoll";
import TodayCard from "@/components/TodayCard";
import AttributionFooter from "@/components/AttributionFooter";

export default function Landing() {
  return (
    // Light green-to-blue gradient (.landing-light in globals.css) with the DataRain canvas above it.
    <div className="landing-light relative isolate flex min-h-screen flex-col overflow-hidden">
      <div className="absolute inset-0 -z-10">
        <LandingBackground />
      </div>

      {/* Content sits above the animation; the animation itself ignores pointer events. */}
      <main className="relative z-10 flex flex-1 flex-col items-center justify-center px-4 py-10 text-center">
        <div className="w-full max-w-3xl rounded-xl bg-[var(--landing-panel)] px-5 py-6 shadow-sm backdrop-blur-sm sm:px-12">
          <h1 className="text-5xl font-bold tracking-tight text-[var(--landing-ink)] sm:text-8xl [perspective:600px]">
            <TextRoll>YieldGuard</TextRoll>
          </h1>
          <p className="mt-3 text-lg font-semibold text-[var(--landing-ink-soft)] sm:text-xl">From sky to soil, every season</p>
        </div>

        <TodayCard />

        <Link
          href="/advice/"
          className="mt-6 inline-flex min-h-12 items-center rounded-md bg-primary px-6 text-lg font-semibold text-primary-foreground shadow-sm transition hover:bg-accent hover:text-accent-foreground"
        >
          Get advice
        </Link>
      </main>

      <div className="relative z-10 bg-background">
        <AttributionFooter />
      </div>
    </div>
  );
}
