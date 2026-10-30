// Small inline SVG icons (stroke style), sized with the surrounding text.
const base = {
  width: "1.15em",
  height: "1.15em",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function MicIcon() {
  return (
    <svg {...base}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 17v4" />
      <path d="M8 21h8" />
    </svg>
  );
}

export function StopIcon() {
  return (
    <svg {...base}>
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}

export function SpeakerIcon() {
  return (
    <svg {...base}>
      <path d="M11 5 6 9H3v6h3l5 4V5Z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

export function PinIcon() {
  return (
    <svg {...base}>
      <path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12Z" />
      <circle cx="12" cy="9" r="2.5" />
    </svg>
  );
}

export function Spinner() {
  return (
    <svg {...base} className="animate-spin">
      <path d="M21 12a9 9 0 1 1-6.2-8.6" />
    </svg>
  );
}
