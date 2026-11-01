import Link from "next/link";
import type { Labels } from "@/lib/i18n";

const LINKS = [
  { href: "/", key: "navHome" },
  { href: "/advice/", key: "navAdvice" },
  { href: "/mandi/", key: "navMandi" },
] as const;

/** Home · Farm advice · Mandi prices, in the page's language; the current page is marked. */
export default function SiteNav({ current, L }: { current: "/" | "/advice/" | "/mandi/"; L: Labels }) {
  return (
    <nav aria-label="YieldGuard" className="flex flex-wrap gap-1">
      {LINKS.map(({ href, key }) => (
        <Link
          key={href}
          href={href}
          aria-current={href === current ? "page" : undefined}
          className={`inline-flex min-h-11 items-center rounded-md px-3 ${
            href === current ? "bg-muted font-semibold text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {L[key]}
        </Link>
      ))}
    </nav>
  );
}
