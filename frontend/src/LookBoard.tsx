import { useId } from 'react';

/**
 * Draws one look as a stylised front-facing figure, so a set of clothes reads at a
 * glance without shipping any garment photography. The shape follows the look's
 * style and season; the colours follow its palette.
 */

type Silhouette = 'tailored' | 'boxy' | 'flowy';
type Bottom = 'trousers' | 'wide' | 'cropped';

const silhouettes: Record<Silhouette, { shoulder: number; waist: number; hip: number }> = {
  tailored: { shoulder: 20, waist: 12.5, hip: 16 },
  boxy: { shoulder: 24.5, waist: 19.5, hip: 21 },
  flowy: { shoulder: 21.5, waist: 16.5, hip: 22.5 },
};
const bottoms: Record<Bottom, { y: number; flare: number }> = {
  trousers: { y: 146, flare: 1 },
  wide: { y: 143, flare: 1.35 },
  cropped: { y: 110, flare: 1.15 },
};

function silhouetteFor(style: string): Silhouette {
  if (style === '街头' || style === '运动') return 'boxy';
  if (style === '度假' || style === '复古') return 'flowy';
  return 'tailored';
}

function bottomFor(style: string, season: string): Bottom {
  if (season === '夏') return 'cropped';
  if (style === '度假' || style === '复古' || style === '街头') return 'wide';
  return 'trousers';
}

export function LookBoard({ palette, style, season, label }: {
  palette: string[]; style: string; season: string; label: string;
}) {
  const patternId = useId();
  const shape = silhouettes[silhouetteFor(style)];
  const hem = bottoms[bottomFor(style, season)];
  const cropped = bottomFor(style, season) === 'cropped';

  const top = palette[0] || '#c9d6bd';
  const lower = palette[1] || top;
  const shoe = palette[2] || lower;
  const accent = palette[3] || palette[2] || lower;

  const cx = 66;
  const shoulderY = 38;
  const waistY = 66;
  const hipY = 80;
  const topHem = 79;
  const ankleY = 146;
  const legOuter = shape.hip * hem.flare * 0.92;
  const stance = cropped ? 7 : (legOuter + 3.5) / 2;
  const shoeY = cropped ? ankleY + 2 : hem.y;

  const torso = [
    `M ${cx - shape.shoulder} ${shoulderY + 4}`,
    `Q ${cx - shape.shoulder} ${shoulderY} ${cx - shape.shoulder + 4.5} ${shoulderY}`,
    `L ${cx + shape.shoulder - 4.5} ${shoulderY}`,
    `Q ${cx + shape.shoulder} ${shoulderY} ${cx + shape.shoulder} ${shoulderY + 4}`,
    `L ${cx + shape.waist} ${waistY}`,
    `L ${cx + shape.hip * 0.88} ${topHem}`,
    `L ${cx - shape.hip * 0.88} ${topHem}`,
    `L ${cx - shape.waist} ${waistY}`,
    'Z',
  ].join(' ');
  const lowerPath = [
    `M ${cx - shape.hip} ${hipY}`,
    `L ${cx - legOuter} ${hem.y}`,
    `L ${cx - 3.5} ${hem.y}`,
    `L ${cx - 1.6} ${hipY + 16}`,
    `L ${cx + 1.6} ${hipY + 16}`,
    `L ${cx + 3.5} ${hem.y}`,
    `L ${cx + legOuter} ${hem.y}`,
    `L ${cx + shape.hip} ${hipY}`,
    'Z',
  ].join(' ');

  return <svg className="look-board" viewBox="0 0 132 168" role="img" aria-label={`${label} 穿搭示意`}>
    <defs>
      <pattern id={patternId} width="11" height="11" patternUnits="userSpaceOnUse">
        <path d="M 11 0 L 0 0 0 11" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.18" />
      </pattern>
    </defs>
    <rect width="132" height="168" className="look-board-ground" />
    <rect width="132" height="168" fill={`url(#${patternId})`} className="look-board-grid" />
    {/* bare limbs stay neutral, so the figure reads as a mannequin rather than a person */}
    <circle cx={cx} cy={22} r={8.6} className="look-board-head" />
    <rect x={cx - 4.6} y={27} width="9.2" height="14" rx="4" className="look-board-neck" />
    {cropped && <>
      <path d={`M ${cx - 6.5} ${hem.y - 4} L ${cx - 7} ${ankleY}`} className="look-board-limb"
        strokeWidth="8.5" strokeLinecap="round" fill="none" />
      <path d={`M ${cx + 6.5} ${hem.y - 4} L ${cx + 7} ${ankleY}`} className="look-board-limb"
        strokeWidth="8.5" strokeLinecap="round" fill="none" />
    </>}
    <path d={lowerPath} fill={lower} stroke="rgba(0,0,0,.14)" strokeWidth="0.8" />
    <path d={`M ${cx - shape.shoulder + 2} ${shoulderY + 4} L ${cx - shape.shoulder - 5} ${shoulderY + 33}`}
      stroke={top} strokeWidth="9.5" strokeLinecap="round" fill="none" />
    <path d={`M ${cx + shape.shoulder - 2} ${shoulderY + 4} L ${cx + shape.shoulder + 5} ${shoulderY + 33}`}
      stroke={top} strokeWidth="9.5" strokeLinecap="round" fill="none" />
    <path d={torso} fill={top} stroke="rgba(0,0,0,.14)" strokeWidth="0.8" />
    <rect x={cx - shape.waist - 1.5} y={waistY - 3.4} width={shape.waist * 2 + 3} height="3.4" rx="1.5" fill={accent} />
    <rect x={cx - stance - 6.5} y={shoeY} width="13" height="6.5" rx="3.2" fill={shoe} />
    <rect x={cx + stance - 6.5} y={shoeY} width="13" height="6.5" rx="3.2" fill={shoe} />
  </svg>;
}
