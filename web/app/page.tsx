import Link from "next/link";
import ShaderBackground from "@/components/ShaderBackground";
import TextRoll from "@/components/TextRoll";
import AttributionFooter from "@/components/AttributionFooter";

export default function Landing() {
  return (
    <div className="relative isolate flex min-h-screen flex-col overflow-hidden bg-background">
      <ShaderBackground className="absolute inset-0 -z-10" />
      {/* Darkens the shader's light areas so white text stays readable everywhere. */}
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,rgba(17,17,17,0.72)_0%,rgba(17,17,17,0.35)_70%)]" />

      <main className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="w-full max-w-3xl rounded-xl bg-black/35 px-5 py-8 backdrop-blur-[2px] sm:px-12">
          <h1 className="text-5xl font-bold tracking-tight text-white sm:text-8xl [perspective:600px]">
            <TextRoll>YieldGuard</TextRoll>
          </h1>
          <p className="mt-3 text-lg font-medium text-[#c9d8cc] sm:text-xl">From sky to soil, every season</p>
          <p className="mx-auto mt-6 max-w-xl text-base text-white/90">
            Ask a farming question in English, Hindi or Kannada and get advice for your village, built from live
            weather, rainfall and soil data, with the source and time of every number.
          </p>
          <Link
            href="/advice/"
            className="mt-8 inline-block rounded-md bg-primary px-6 py-3 font-semibold text-primary-foreground transition hover:brightness-110"
          >
            Get advice
          </Link>
        </div>
      </main>

      <div className="bg-black/50">
        <AttributionFooter />
      </div>
    </div>
  );
}
