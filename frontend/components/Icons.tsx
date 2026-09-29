// Small stroke icon set (24px grid, 1.8 stroke) so the UI needs no icon library.
type P = { size?: number };
const base = (size: number) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true,
});

export const IconGrid = ({ size = 18 }: P) => (
  <svg {...base(size)}><rect x="3.5" y="3.5" width="7" height="7" rx="2" /><rect x="13.5" y="3.5" width="7" height="7" rx="2" /><rect x="3.5" y="13.5" width="7" height="7" rx="2" /><rect x="13.5" y="13.5" width="7" height="7" rx="2" /></svg>
);
export const IconChart = ({ size = 18 }: P) => (
  <svg {...base(size)}><path d="M4 19V5" /><path d="M4 19h16" /><path d="m7 14 4-4 3 3 5-6" /></svg>
);
export const IconCompare = ({ size = 18 }: P) => (
  <svg {...base(size)}><path d="M7 4v16" /><path d="M17 4v16" /><path d="m4 8 3-4 3 4" /><path d="m14 16 3 4 3-4" /></svg>
);
export const IconModel = ({ size = 18 }: P) => (
  <svg {...base(size)}><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 7.5 10.8 16M16 7.5 13.2 16M8.5 6h7" /></svg>
);
export const IconTable = ({ size = 18 }: P) => (
  <svg {...base(size)}><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M3.5 9.5h17M9.5 9.5v10" /></svg>
);
export const IconData = ({ size = 18 }: P) => (
  <svg {...base(size)}><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6" /><path d="M4.5 12v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6" /></svg>
);
export const IconSearch = ({ size = 17 }: P) => (
  <svg {...base(size)}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg>
);
export const IconRefresh = ({ size = 17 }: P) => (
  <svg {...base(size)}><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16" /><path d="M20 20v-4h-4" /></svg>
);
export const IconChevron = ({ size = 14 }: P) => (
  <svg {...base(size)}><path d="m6 9 6 6 6-6" /></svg>
);
export const IconArrow = ({ up, size = 10 }: P & { up: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden="true">
    <path d={up ? "M5 1.5 9 7.5H1z" : "M5 8.5 1 2.5h8z"} fill="currentColor" />
  </svg>
);
