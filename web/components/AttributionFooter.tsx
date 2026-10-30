export default function AttributionFooter({ note }: { note?: string }) {
  return (
    <footer className="mx-auto w-full max-w-4xl px-4 pb-8 pt-4 text-xs text-muted">
      <p>
        Weather and rainfall:{" "}
        <a className="underline hover:text-foreground" href="https://open-meteo.com/" target="_blank" rel="noopener">
          Open-Meteo.com
        </a>{" "}
        (CC BY 4.0) · Soil:{" "}
        <a className="underline hover:text-foreground" href="https://soilgrids.org/" target="_blank" rel="noopener">
          ISRIC SoilGrids v2.0
        </a>{" "}
        (CC BY 4.0) · Answers written by Google Gemini from this data only.
      </p>
      {note && <p className="mt-1">{note}</p>}
    </footer>
  );
}
