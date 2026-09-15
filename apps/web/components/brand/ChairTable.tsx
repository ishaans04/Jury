"use client";

import { Gavel } from "lucide-react";

import { SEATS, type Seat } from "@/lib/chairs";
import type { Chair } from "@/lib/types";
import { cn } from "@/lib/utils";
import { GlassOrb } from "./GlassOrb";
import { MiniBot } from "./MiniBot";

/** Where each juror sits, in % of the 16:11 scene: centre-x, top, width. The
 * back row faces the viewer from behind the table; the front row is seen
 * from behind its chairs, in front of the table. */
const SCENE: { seat: Seat; x: number; y: number; w: number; view: "front" | "back" }[] = [
  { seat: "market", x: 27, y: 30, w: 15, view: "front" },
  { seat: "chairman", x: 50, y: 24, w: 15, view: "front" },
  { seat: "customer", x: 73, y: 30, w: 15, view: "front" },
  { seat: "precedent", x: 23, y: 60, w: 17, view: "back" },
  { seat: "economics", x: 50, y: 74, w: 13, view: "back" },
  { seat: "dependencies", x: 77, y: 60, w: 17, view: "back" },
];

/** Callout label boxes (`side` = which edge `x` anchors) and their leader
 * lines, in the same % space as `SCENE`. */
const CALLOUTS: Record<Seat, { x: number; y: number; side: "left" | "right"; line: [number, number][] }> = {
  chairman: { x: 60, y: 21, side: "left", line: [[59.5, 24], [56, 27]] },
  market: { x: 16, y: 24, side: "right", line: [[16.5, 27], [22, 27], [24, 31]] },
  customer: { x: 84, y: 24, side: "left", line: [[83.5, 27], [78, 27], [76, 31]] },
  precedent: { x: 12, y: 66, side: "right", line: [[12.5, 69], [16, 69]] },
  dependencies: { x: 88, y: 66, side: "left", line: [[87.5, 69], [84, 69]] },
  economics: { x: 60, y: 88, side: "left", line: [[59.5, 91], [56.5, 91]] },
};

interface ChairTableProps {
  thinking?: boolean;
  activeSeat?: Seat | null;
  counts?: Partial<Record<Chair, number>>;
  partial?: Chair[];
  onSelect?: (seat: Seat) => void;
  selectLabel?: (seat: Seat) => string;
  /** Show name/tagline callouts with leader lines (large screens only). */
  callouts?: boolean;
  className?: string;
}

/** The boardroom: six mini-bot jurors around a glowing round table. Each
 * juror is a real button, so the scene is keyboard- and screen-reader
 * operable. The liquid-glass orb turns at the centre while `thinking`. */
export function ChairTable({
  thinking = false,
  activeSeat = null,
  counts,
  partial = [],
  onSelect,
  selectLabel = (s) => `${SEATS[s].name}`,
  callouts = false,
  className,
}: ChairTableProps) {
  return (
    <div className={cn("relative mx-auto aspect-[16/11] w-full max-w-5xl select-none", className)}>
      {/* table */}
      <div className="table-glass absolute inset-x-[13%] bottom-[8%] top-[46%] z-20 rounded-[50%]">
        <div className="absolute inset-[7%] rounded-[50%] bg-gradient-to-b from-white to-[#F1F3F7]" />
      </div>
      <div
        aria-hidden
        className={cn(
          "absolute left-1/2 top-[58%] z-20 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 text-[#B8C0CF] transition-all duration-500",
          thinking ? "scale-75 opacity-0" : "opacity-100",
        )}
      >
        <Gavel className="h-5 w-5 sm:h-8 sm:w-8" />
        <span className="text-[9px] font-semibold tracking-[0.35em] sm:text-[11px]">THE JURY</span>
      </div>
      <GlassOrb
        active={thinking}
        className="absolute left-1/2 top-[58%] z-20 h-[19%] -translate-x-1/2 -translate-y-1/2"
      />

      {/* jurors */}
      {SCENE.map(({ seat, x, y, w, view }, i) => {
        const meta = SEATS[seat];
        const count = seat === "chairman" ? undefined : counts?.[seat];
        const isActive = activeSeat === seat;
        const isPartial = seat !== "chairman" && partial.includes(seat);
        return (
          <button
            key={seat}
            type="button"
            onClick={() => onSelect?.(seat)}
            aria-label={selectLabel(seat)}
            aria-pressed={onSelect ? isActive : undefined}
            className={cn(
              "group absolute -translate-x-1/2 rounded-[30%] outline-none focus-visible:ring-4 focus-visible:ring-[#4F7BF7]/40",
              view === "front" ? "z-10" : "z-30",
            )}
            style={{ left: `${x}%`, top: `${y}%`, width: `${w}%` }}
          >
            <span
              className={cn(
                "relative block transition-transform duration-300 ease-out group-hover:-translate-y-[4%] group-hover:scale-[1.04]",
                isActive && "-translate-y-[4%] scale-[1.05]",
              )}
            >
              <span
                className={cn(
                  "absolute inset-[10%] -z-10 rounded-full blur-2xl transition-opacity duration-300",
                  isActive ? "opacity-50" : "opacity-0 group-hover:opacity-30",
                )}
                style={{ background: meta.color }}
              />
              <MiniBot seat={seat} view={view} thinking={thinking} delay={i * 0.25} />
              {count !== undefined && count > 0 && (
                <span
                  className="absolute right-[4%] top-[6%] min-w-6 rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-white shadow-md sm:text-xs"
                  style={{ background: meta.color }}
                >
                  {count}
                </span>
              )}
              {isPartial && (
                <span className="absolute left-[4%] top-[6%] rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                  partial
                </span>
              )}
            </span>
            {!callouts && (
              <span className="pointer-events-none absolute left-1/2 top-full z-40 mt-1 hidden -translate-x-1/2 whitespace-nowrap rounded-full bg-white/90 px-2.5 py-1 text-xs font-medium text-[#1B2033] opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 sm:block">
                {meta.name}
              </span>
            )}
          </button>
        );
      })}

      {/* callouts */}
      {callouts && (
        <div aria-hidden className="pointer-events-none absolute inset-0 z-40 hidden lg:block">
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
            {SCENE.map(({ seat }) => (
              <polyline
                key={seat}
                points={CALLOUTS[seat].line.map((p) => p.join(",")).join(" ")}
                fill="none"
                stroke="#B7BFCC"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          {SCENE.map(({ seat }) => {
            const c = CALLOUTS[seat];
            const meta = SEATS[seat];
            return (
              <div
                key={seat}
                className={cn("absolute flex flex-col whitespace-nowrap", c.side === "right" ? "items-end text-right" : "items-start")}
                style={c.side === "right" ? { right: `${100 - c.x}%`, top: `${c.y}%` } : { left: `${c.x}%`, top: `${c.y}%` }}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-[#1B2033]">
                  <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
                  The {meta.name}
                </span>
                <span className="text-xs text-[#6B7280]">{meta.tagline}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
