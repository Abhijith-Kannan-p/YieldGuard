"use client";

import { motion, useReducedMotion } from "motion/react";

/**
 * TextRoll – each letter rolls up into place, staggered left to right.
 * The animation runs once when the component mounts (i.e. on every page load or
 * refresh). There is no loop, timer or re-trigger.
 */
export default function TextRoll({
  children,
  className,
  duration = 0.55,
  stagger = 0.06,
}: {
  children: string;
  className?: string;
  duration?: number;
  stagger?: number;
}) {
  const reduce = useReducedMotion();
  const letters = Array.from(children);

  return (
    <span className={className} aria-label={children} role="text">
      {letters.map((ch, i) => (
        <span key={i} aria-hidden="true" className="inline-block overflow-hidden align-bottom leading-[1.1]">
          <motion.span
            className="inline-block"
            initial={reduce ? false : { y: "110%", rotateX: -70, opacity: 0 }}
            animate={{ y: "0%", rotateX: 0, opacity: 1 }}
            transition={{ duration, delay: i * stagger, ease: [0.22, 1, 0.36, 1] }}
          >
            {ch === " " ? " " : ch}
          </motion.span>
        </span>
      ))}
    </span>
  );
}
