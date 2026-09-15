import { useId } from "react";

import { SEATS, type Seat } from "@/lib/chairs";
import { cn } from "@/lib/utils";

interface MiniBotProps {
  seat: Seat;
  /** `back` renders the juror seen from behind its chair. */
  view?: "front" | "back";
  thinking?: boolean;
  className?: string;
  /** Stagger offset for the bob animation, in seconds. */
  delay?: number;
}

/** A suited mini-bot juror in a white office chair: glossy helmet, dark
 * visor with the chair's emblem glowing on it. Decorative only. */
export function MiniBot({ seat, view = "front", thinking = false, className, delay = 0 }: MiniBotProps) {
  const meta = SEATS[seat];
  const Icon = meta.icon;
  const id = useId().replace(/:/g, "");
  const shell = `shell-${id}`;
  const chair = `chair-${id}`;
  const suit = `suit-${id}`;

  const defs = (
    <defs>
      <linearGradient id={shell} x1="0.2" y1="0" x2="0.8" y2="1">
        <stop offset="0" stopColor="#FFFFFF" />
        <stop offset="1" stopColor="#E4E8EF" />
      </linearGradient>
      <linearGradient id={chair} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#FFFFFF" />
        <stop offset="1" stopColor="#E6E9EF" />
      </linearGradient>
      <linearGradient id={suit} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={meta.color} />
        <stop offset="1" stopColor={meta.color} stopOpacity="0.78" />
      </linearGradient>
    </defs>
  );

  return (
    <div
      aria-hidden
      className={cn("relative aspect-[4/5] w-full", thinking ? "bot-think" : "bot-idle", className)}
      style={{ animationDelay: `${delay}s` }}
    >
      {view === "front" ? (
        <>
          <svg viewBox="0 0 120 150" className="h-full w-full overflow-visible">
            {defs}
            <ellipse cx="60" cy="146" rx="42" ry="4" fill="#1B2033" opacity="0.08" />
            <rect x="14" y="26" width="92" height="110" rx="28" fill={`url(#${chair})`} stroke="#DFE3EA" />
            <rect x="5" y="98" width="16" height="36" rx="8" fill={`url(#${chair})`} stroke="#DFE3EA" />
            <rect x="99" y="98" width="16" height="36" rx="8" fill={`url(#${chair})`} stroke="#DFE3EA" />
            <path d="M24 140 V110 C24 95 37 86 50 86 H70 C83 86 96 95 96 110 V140 Z" fill={`url(#${suit})`} />
            <path d="M50 86 H70 L60 112 Z" fill="#FFFFFF" />
            <path d="M50 86 L60 112 L44 100 Z M70 86 L60 112 L76 100 Z" fill="#000000" opacity="0.14" />
            <path d="M57.5 90 H62.5 L64.5 106 L60 113 L55.5 106 Z" fill="#1B2033" />
            <rect x="52" y="76" width="16" height="12" rx="4" fill="#CBD1DB" />
            <rect x="18" y="38" width="13" height="24" rx="6.5" fill="#E3E7EE" stroke="#D5DAE3" />
            <rect x="89" y="38" width="13" height="24" rx="6.5" fill="#E3E7EE" stroke="#D5DAE3" />
            <circle cx="24.5" cy="50" r="3" fill={meta.color} />
            <circle cx="95.5" cy="50" r="3" fill={meta.color} />
            <rect x="27" y="14" width="66" height="66" rx="31" fill={`url(#${shell})`} stroke="#DADFE7" />
            <rect x="35" y="28" width="50" height="40" rx="19" fill="#0E1120" />
            <path d="M42 35 Q52 30.5 66 31.5" stroke="#FFFFFF" strokeOpacity="0.28" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
          <Icon
            className={cn(
              "absolute left-1/2 top-[32%] h-[17%] w-[17%] -translate-x-1/2 -translate-y-1/2",
              thinking && "bot-visor",
            )}
            style={{ color: meta.color, filter: `drop-shadow(0 0 4px ${meta.color})` }}
            strokeWidth={2.5}
          />
        </>
      ) : (
        <svg viewBox="0 0 120 150" className="h-full w-full overflow-visible">
          {defs}
          <ellipse cx="60" cy="146" rx="42" ry="4" fill="#1B2033" opacity="0.08" />
          <path d="M16 130 V104 C16 91 31 82 46 82 H74 C89 82 104 91 104 104 V130 Z" fill={`url(#${suit})`} />
          <rect x="18" y="30" width="13" height="24" rx="6.5" fill="#E3E7EE" stroke="#D5DAE3" />
          <rect x="89" y="30" width="13" height="24" rx="6.5" fill="#E3E7EE" stroke="#D5DAE3" />
          <rect x="27" y="8" width="66" height="66" rx="31" fill={`url(#${shell})`} stroke="#DADFE7" />
          <path d="M40 20 Q60 10 80 20" stroke={meta.color} strokeWidth="5" fill="none" strokeLinecap="round" opacity="0.85" />
          <rect x="14" y="56" width="92" height="84" rx="26" fill={`url(#${chair})`} stroke="#DFE3EA" />
          <path d="M30 74 H90" stroke="#DFE3EA" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )}
    </div>
  );
}
