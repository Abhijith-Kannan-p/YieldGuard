import Link from "next/link";
import HoarfrostPane from "@/components/ui/hoarfrost-pane";
import TextRoll from "@/components/TextRoll";
import TodayCard from "@/components/TodayCard";
import AttributionFooter from "@/components/AttributionFooter";

export default function Landing() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Frosted window: the title and button sit on the glass. HoarfrostPane passes pointer events
          through to links and buttons, so "Get advice" stays clickable above the frost. */}
      <HoarfrostPane height="100svh">
        <div className="flex h-full flex-col items-center justify-center px-5 text-center text-white [text-shadow:0_1px_24px_rgba(8,14,28,0.6)]">
          {/* A soft, borderless glow in the text-shadow colour keeps white text readable when a bright
              street lamp in the frost scene sits behind it (worst on narrow phones). Not a panel: it fades to nothing. */}
          <div className="flex max-w-3xl flex-col items-center bg-[radial-gradient(closest-side,rgba(8,14,28,0.8),rgba(8,14,28,0.65)_65%,rgba(8,14,28,0))] px-8 py-12 sm:px-16">
            <h1 className="text-5xl font-bold tracking-tight sm:text-8xl [perspective:600px]">
              <TextRoll>YieldGuard</TextRoll>
            </h1>
            <p className="mt-3 text-lg font-semibold sm:text-2xl">From sky to soil, every season</p>
            <p className="mt-4 max-w-xl text-base sm:text-lg">
              Ask a farming question in English, Hindi or Kannada and get advice for your village, built from live weather,
              rainfall and soil data, with the source and time of every number.
            </p>
            <Link
              href="/advice/"
              className="mt-8 inline-flex min-h-12 items-center rounded-md bg-primary px-6 text-lg font-semibold text-primary-foreground shadow-sm transition [text-shadow:none] hover:bg-accent hover:text-accent-foreground"
            >
              Get advice
            </Link>
          </div>
        </div>
      </HoarfrostPane>

      {/* The live card is tall on phones, so it sits below the 100svh pane instead of being clipped by it. */}
      <section className="px-4 pb-10">
        <TodayCard />
      </section>

      <AttributionFooter />
    </div>
  );
}
