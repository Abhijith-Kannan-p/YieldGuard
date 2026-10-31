"use client";

import { useSyncExternalStore } from "react";
import DataRain from "./DataRain";

// Particle count by screen width: lighter on phones, fuller on desktops (the default scales up to 7000).
const PHONE_MAX_WIDTH = 768;
const COUNT_PHONE = 1800;
const COUNT_DESKTOP = 3500;

const subscribeResize = (cb: () => void) => {
  window.addEventListener("resize", cb);
  return () => window.removeEventListener("resize", cb);
};

/** Light green-and-blue DataRain for the landing page. Colours come from CSS variables in globals.css. */
export default function LandingBackground() {
  const isPhone = useSyncExternalStore(subscribeResize, () => window.innerWidth < PHONE_MAX_WIDTH, () => false);
  return (
    <DataRain
      theme="light"
      count={isPhone ? COUNT_PHONE : COUNT_DESKTOP}
      palette={{ calm: "var(--dr-calm)", mid: "var(--dr-mid)", hot: "var(--dr-hot)" }}
    />
  );
}
