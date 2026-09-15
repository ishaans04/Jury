"use client";

import {
  ClipboardCheck,
  Gavel,
  History,
  MessageSquareText,
  Swords,
  type LucideIcon,
} from "lucide-react";

import { CHAIR_FLOW, SEATS } from "@/lib/chairs";
import type { Chair } from "@/lib/types";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

export type StepNode = "pitch" | "hearing" | "cross" | "verdict" | "ledger";
type NodeId = StepNode | Chair;

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
type Pt = [number, number];
interface Edge {
  from: NodeId;
  to: NodeId;
  d: string;
  label?: { text: string; at: Pt };
  slow?: boolean;
}
interface Layout {
  key: string;
  width: number;
  height: number;
  compact: boolean;
  boxes: Record<NodeId, Box>;
  edges: Edge[];
}

export const STEP_OF: Record<NodeId, number> = {
  pitch: 0,
  hearing: 1,
  market: 2,
  customer: 2,
  precedent: 2,
  dependencies: 2,
  economics: 2,
  cross: 3,
  verdict: 4,
  ledger: 5,
};

const MAIN: Record<StepNode, { title: string; sub: string; icon: LucideIcon }> = {
  pitch: { title: "Pitch", sub: "Your idea in brief", icon: MessageSquareText },
  hearing: { title: "Hearing", sub: "Confirm assumptions", icon: ClipboardCheck },
  cross: { title: "Cross-exam", sub: "Conflicts & shifts", icon: Swords },
  verdict: { title: "Verdict", sub: "Proceed · Pivot · Stop", icon: Gavel },
  ledger: { title: "Living ledger", sub: "Results → causal diff", icon: History },
};

const right = (b: Box): Pt => [b.x + b.w, b.y + b.h / 2];
const left = (b: Box): Pt => [b.x, b.y + b.h / 2];
const top = (b: Box): Pt => [b.x + b.w / 2, b.y];
const bottom = (b: Box): Pt => [b.x + b.w / 2, b.y + b.h];
const hCurve = ([x1, y1]: Pt, [x2, y2]: Pt) => {
  const m = (x1 + x2) / 2;
  return `M${x1} ${y1} C${m} ${y1} ${m} ${y2} ${x2} ${y2}`;
};
const vCurve = ([x1, y1]: Pt, [x2, y2]: Pt) => {
  const m = (y1 + y2) / 2;
  return `M${x1} ${y1} C${x1} ${m} ${x2} ${m} ${x2} ${y2}`;
};

function wide(): Layout {
  const boxes = {
    pitch: { x: 10, y: 186, w: 190, h: 88 },
    hearing: { x: 250, y: 186, w: 195, h: 88 },
    cross: { x: 785, y: 186, w: 195, h: 88 },
    verdict: { x: 1035, y: 118, w: 215, h: 96 },
    ledger: { x: 1035, y: 290, w: 215, h: 88 },
  } as Record<NodeId, Box>;
  CHAIR_FLOW.forEach((c, i) => (boxes[c] = { x: 515, y: 34 + i * 84, w: 190, h: 60 }));
  const econ = boxes.economics;
  const edges: Edge[] = [
    { from: "pitch", to: "hearing", d: hCurve(right(boxes.pitch), left(boxes.hearing)) },
    ...CHAIR_FLOW.map((c) => ({ from: "hearing" as NodeId, to: c, d: hCurve(right(boxes.hearing), left(boxes[c])) })),
    ...CHAIR_FLOW.map((c) => ({ from: c, to: "cross" as NodeId, d: hCurve(right(boxes[c]), left(boxes.cross)) })),
    { from: "cross", to: "verdict", d: hCurve(right(boxes.cross), left(boxes.verdict)) },
    { from: "verdict", to: "ledger", d: vCurve(bottom(boxes.verdict), top(boxes.ledger)) },
    {
      from: "ledger",
      to: "economics",
      slow: true,
      d: `M${bottom(boxes.ledger)[0]} ${boxes.ledger.y + boxes.ledger.h} L${bottom(boxes.ledger)[0]} 470 L${econ.x + econ.w / 2} 470 L${econ.x + econ.w / 2} ${econ.y + econ.h}`,
      label: { text: "New result → re-run only what it affects", at: [880, 462] },
    },
  ];
  return { key: "wide", width: 1260, height: 490, compact: false, boxes, edges };
}

function narrow(): Layout {
  const boxes = {
    pitch: { x: 40, y: 8, w: 260, h: 64 },
    hearing: { x: 40, y: 118, w: 260, h: 64 },
    cross: { x: 40, y: 372, w: 260, h: 64 },
    verdict: { x: 40, y: 482, w: 260, h: 64 },
    ledger: { x: 40, y: 592, w: 260, h: 64 },
  } as Record<NodeId, Box>;
  CHAIR_FLOW.forEach((c, i) => (boxes[c] = { x: 6 + i * 64, y: 238, w: 56, h: 74 }));
  const econ = boxes.economics;
  const edges: Edge[] = [
    { from: "pitch", to: "hearing", d: vCurve(bottom(boxes.pitch), top(boxes.hearing)) },
    ...CHAIR_FLOW.map((c) => ({ from: "hearing" as NodeId, to: c, d: vCurve(bottom(boxes.hearing), top(boxes[c])) })),
    ...CHAIR_FLOW.map((c) => ({ from: c, to: "cross" as NodeId, d: vCurve(bottom(boxes[c]), top(boxes.cross)) })),
    { from: "cross", to: "verdict", d: vCurve(bottom(boxes.cross), top(boxes.verdict)) },
    { from: "verdict", to: "ledger", d: vCurve(bottom(boxes.verdict), top(boxes.ledger)) },
    {
      from: "ledger",
      to: "economics",
      slow: true,
      d: `M300 ${boxes.ledger.y + 32} L334 ${boxes.ledger.y + 32} L334 ${econ.y + econ.h + 14} L${econ.x + econ.w / 2} ${econ.y + econ.h + 14} L${econ.x + econ.w / 2} ${econ.y + econ.h}`,
    },
  ];
  return { key: "narrow", width: 340, height: 664, compact: true, boxes, edges };
}

const LAYOUTS = [wide(), narrow()];
const ACCENT = "#4F7BF7";

interface PipelineFlowProps {
  activeStep: number;
  onSelectStep: (step: number) => void;
  onSelectChair: (chair: Chair) => void;
}

/** The validation pipeline as a flow chart. Every connector carries arrow
 * pointers travelling toward the next block; nodes are buttons that drive
 * the step detail panel. */
export function PipelineFlow({ activeStep, onSelectStep, onSelectChair }: PipelineFlowProps) {
  const reduced = usePrefersReducedMotion();

  return (
    <>
      {LAYOUTS.map((layout) => (
        <svg
          key={layout.key}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="group"
          aria-label="The Jury validation pipeline"
          className={layout.compact ? "mx-auto block w-full max-w-sm md:hidden" : "hidden w-full md:block"}
        >
          <defs>
            <marker
              id={`arrow-${layout.key}`}
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0 0 L10 5 L0 10 z" fill="#C5CCD8" />
            </marker>
            <filter id={`shadow-${layout.key}`} x="-20%" y="-20%" width="140%" height="160%">
              <feDropShadow dx="0" dy="6" stdDeviation="8" floodColor="#1B2033" floodOpacity="0.08" />
            </filter>
          </defs>

          {layout.edges.map((edge, i) => {
            const hot = STEP_OF[edge.to] === activeStep;
            const dur = edge.slow ? 5 : 2.4;
            return (
              <g key={`${edge.from}-${edge.to}`}>
                <path
                  d={edge.d}
                  fill="none"
                  stroke={hot ? ACCENT : "#D3D9E3"}
                  strokeOpacity={hot ? 0.7 : 1}
                  strokeWidth={layout.compact ? 1.5 : 2}
                  strokeDasharray="5 6"
                  className={reduced ? undefined : "flow-dash"}
                  markerEnd={`url(#arrow-${layout.key})`}
                />
                {!reduced &&
                  [0, 0.5].map((phase) => (
                    <path
                      key={phase}
                      d="M-6 -4.5 L2 0 L-6 4.5"
                      fill="none"
                      stroke={hot ? ACCENT : "#8E98AB"}
                      strokeWidth={layout.compact ? 2 : 2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <animateMotion
                        dur={`${dur}s`}
                        begin={`-${(phase * dur + i * 0.13).toFixed(2)}s`}
                        repeatCount="indefinite"
                        rotate="auto"
                        path={edge.d}
                      />
                    </path>
                  ))}
                {edge.label && (
                  <text
                    x={edge.label.at[0]}
                    y={edge.label.at[1]}
                    textAnchor="middle"
                    fontSize="12"
                    fill="#6B7280"
                    className="[paint-order:stroke] [stroke:#FBFBFD] [stroke-width:6px]"
                  >
                    {edge.label.text}
                  </text>
                )}
              </g>
            );
          })}

          {(Object.keys(MAIN) as StepNode[]).map((id) => {
            const b = layout.boxes[id];
            const meta = MAIN[id];
            const Icon = meta.icon;
            const step = STEP_OF[id];
            const active = step === activeStep;
            const iconSize = layout.compact ? 30 : 40;
            return (
              <g
                key={id}
                role="button"
                tabIndex={0}
                aria-label={`Step ${step + 1}: ${meta.title}`}
                aria-pressed={active}
                onClick={() => onSelectStep(step)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectStep(step);
                  }
                }}
                className="flow-node cursor-pointer outline-none"
              >
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  rx={layout.compact ? 18 : 22}
                  fill="#FFFFFF"
                  stroke={active ? ACCENT : "#E3E7EE"}
                  strokeWidth={active ? 2 : 1}
                  filter={`url(#shadow-${layout.key})`}
                />
                <rect
                  x={b.x + 12}
                  y={b.y + (b.h - iconSize) / 2}
                  width={iconSize}
                  height={iconSize}
                  rx={iconSize / 3.2}
                  fill={active ? ACCENT : "#EEF2FB"}
                />
                <Icon
                  x={b.x + 12 + iconSize * 0.25}
                  y={b.y + (b.h - iconSize) / 2 + iconSize * 0.25}
                  width={iconSize * 0.5}
                  height={iconSize * 0.5}
                  color={active ? "#FFFFFF" : ACCENT}
                />
                <text x={b.x + 24 + iconSize} y={b.y + b.h / 2 - (layout.compact ? 4 : 8)} fontSize={layout.compact ? 14 : 16} fontWeight="600" fill="#1B2033">
                  {meta.title}
                </text>
                <text x={b.x + 24 + iconSize} y={b.y + b.h / 2 + (layout.compact ? 13 : 14)} fontSize={layout.compact ? 11 : 12} fill="#6B7280">
                  {meta.sub}
                </text>
              </g>
            );
          })}

          {CHAIR_FLOW.map((chair) => {
            const b = layout.boxes[chair];
            const meta = SEATS[chair];
            const Icon = meta.icon;
            const active = activeStep === 2;
            const select = () => onSelectChair(chair);
            const common = {
              role: "button",
              tabIndex: 0,
              "aria-label": `${meta.name} chair`,
              onClick: select,
              onKeyDown: (e: React.KeyboardEvent) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  select();
                }
              },
              className: "flow-node cursor-pointer outline-none",
            } as const;
            if (layout.compact) {
              const cx = b.x + b.w / 2;
              return (
                <g key={chair} {...common}>
                  <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="16" fill="#FFFFFF" stroke={active ? meta.color : "#E3E7EE"} filter={`url(#shadow-${layout.key})`} />
                  <circle cx={cx} cy={b.y + 28} r="16" fill={meta.color} />
                  <Icon x={cx - 8} y={b.y + 20} width={16} height={16} color="#FFFFFF" />
                  <text x={cx} y={b.y + 62} textAnchor="middle" fontSize="9" fontWeight="600" fill="#1B2033">
                    {meta.name.length > 9 ? "Depend." : meta.name}
                  </text>
                </g>
              );
            }
            return (
              <g key={chair} {...common}>
                <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="18" fill="#FFFFFF" stroke={active ? meta.color : "#E3E7EE"} strokeWidth={active ? 1.8 : 1} filter={`url(#shadow-${layout.key})`} />
                <circle cx={b.x + 30} cy={b.y + b.h / 2} r="16" fill={meta.color} />
                <Icon x={b.x + 22} y={b.y + b.h / 2 - 8} width={16} height={16} color="#FFFFFF" />
                <text x={b.x + 56} y={b.y + b.h / 2 - 3} fontSize="14" fontWeight="600" fill="#1B2033">
                  {meta.name}
                </text>
                <text x={b.x + 56} y={b.y + b.h / 2 + 14} fontSize="11" fill="#6B7280">
                  {meta.tagline}
                </text>
              </g>
            );
          })}
        </svg>
      ))}
    </>
  );
}
